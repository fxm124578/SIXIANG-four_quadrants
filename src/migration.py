"""schema 迁移框架（v2.0 底层重构）。

背景：旧版 data.db 只靠 CREATE TABLE IF NOT EXISTS 建表，无版本管理，
后续版本（时间机制/周期任务）新增列与表时老库无法平滑升级。本模块提供
settings.schema_version 驱动的有序迁移：旧库（无版本记录）视为 version 0，
按 MIGRATIONS 顺序逐级应用；每级迁移与其版本登记同处一个事务，失败整体
回滚、版本不前进；已成功的前序迁移保留，下次运行从断点续跑（幂等）。

版本号存放于 settings 表（key = "schema_version"）而非 PRAGMA user_version：
settings 是项目既有的 key/value 机制（与 db.py 的 set_setting 同一 upsert
写法），应用内可直接读取，不会形成第二套状态源。user_version 仅在需要
原生整数槽时才有优势，本项目不需要。

事务说明：框架为每级迁移显式 BEGIN/COMMIT/ROLLBACK，不依赖
`with conn` 的隐式事务——Python sqlite3 在 legacy 模式（默认
isolation_level=""）下只有 DML 才触发隐式 BEGIN，DDL 会直接自动
提交；3.12+ 默认 autocommit 下 `with conn` 更是完全无效。显式事务
才能保证迁移中的 DDL（如 ALTER TABLE）可随失败一起回滚。

约定：
- 迁移函数 up(conn) 只做 DDL/DML，不得自行 COMMIT/ROLLBACK；
- 调用 run_migrations 时连接上不得已有未提交的写事务（否则 BEGIN 会抛错）。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, List

SCHEMA_VERSION_KEY = "schema_version"


@dataclass(frozen=True)
class Migration:
    """一条 schema 迁移：version 从 1 起严格递增，应用顺序即注册顺序。"""

    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]


def _migration_001(conn: sqlite3.Connection) -> None:
    """001 基线迁移（v2.0.0）：安全无害的版本登记占位。

    本版不修改任何业务表结构，仅随框架把 schema_version 登记为 1，为后续
    迁移（tasks 扩展列、recurring_series、task_outcomes 等）建立注册样板。
    后续新增迁移时复制本函数签名，version 顺延（002、003…）。
    """
    # no-op：版本登记由 run_migrations 统一写入同一事务
    pass


MIGRATIONS: List[Migration] = [
    Migration(1, "001-schema-version-baseline", _migration_001),
]


def _validate_registry() -> None:
    """校验注册表：version 从 1 起严格递增、无重复（防御乱序注册跳版本）。"""
    prev = 0
    for item in MIGRATIONS:
        if item.version < 1:
            raise ValueError(
                f"迁移版本必须 >= 1，实际 {item.version}（{item.name}）"
            )
        if item.version <= prev:
            raise ValueError(
                f"迁移版本必须严格递增：{prev} 之后出现 "
                f"{item.version}（{item.name}）"
            )
        prev = item.version


def _ensure_settings_table(conn: sqlite3.Connection) -> None:
    """幂等补建 settings 表（兼容连 settings 都没有的极老库）。

    单条幂等 DDL，无需事务包裹；调用方保证无未提交写事务。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        " key TEXT PRIMARY KEY,"
        " value TEXT NOT NULL"
        ")"
    )


def get_schema_version(conn: sqlite3.Connection) -> int:
    """读取当前 schema 版本；settings 中无记录（老库）视为 0。

    前置：settings 表必须存在（run_migrations 会自动补建；
    对尚未初始化过的库请先调用 run_migrations）。
    """
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (SCHEMA_VERSION_KEY,)
    ).fetchone()
    if row is None:
        return 0
    raw = str(row[0]).strip()
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(
            f"settings.{SCHEMA_VERSION_KEY} 的值不是合法版本号：{raw!r}；"
            "拒绝自动升级，请人工检查该数据库。"
        ) from None


def run_migrations(conn: sqlite3.Connection) -> None:
    """把 conn 上的库升级到 MIGRATIONS 最新版本（幂等，可反复调用）。

    流程：
    1. 校验注册表（严格递增）；
    2. 幂等补建 settings 表；
    3. 读当前版本（无记录 = 0）；
    4. 依序应用 version > current 的迁移。每级迁移与其版本登记处在同一
       显式事务（BEGIN → up → upsert 版本 → COMMIT）中：up 抛错则
       ROLLBACK——迁移内 DDL 一并撤销（SQLite DDL 可回滚）、版本不前进、
       异常向外传播；已成功的前序迁移保留，下次调用从断点续跑。

    前置：conn 上无未提交的写事务（db.py 集成点在 _init_schema 提交后调用）。
    """
    _validate_registry()
    _ensure_settings_table(conn)
    current = get_schema_version(conn)
    for item in MIGRATIONS:
        if item.version <= current:
            continue
        conn.execute("BEGIN")
        try:
            item.up(conn)
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION_KEY, str(item.version)),
            )
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass  # 回滚失败（连接已坏）时保留原始异常
            raise
