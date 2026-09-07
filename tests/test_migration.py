"""schema 迁移框架测试（S1 / v2.0 底层重构）。

覆盖：
- 新库从 0 跑到最新；
- 旧库（预置 tasks/settings 表与数据）升级后数据无损；
- 重复运行幂等（版本不再变、数据不重复）；
- 迁移失败回滚（含 DDL 回滚）且版本不前进、可续跑；
- settings 表中 schema_version 正确；
- 注册表防御（乱序/重复拒绝、脏版本值拒绝）。

全部在临时目录建库，不触碰仓库内 data.db。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 自包含地把 src/ 挂入 sys.path（discover 在 Python 3.10 下按顶层模块导入，
# 不保证执行 tests/__init__.py；此段幂等，包式运行时无副作用）
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import db
import migration

# 与 db.py _init_schema 中 v1 时代（本重构前）的基线 DDL 一致，
# 用于模拟老用户 data.db。
_LEGACY_TASKS_DDL = """
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tag TEXT NOT NULL DEFAULT '',
    quadrant INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _table_names(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [str(r[0]) for r in rows]


def _column_names(conn: sqlite3.Connection, table: str) -> list:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [str(r[1]) for r in rows]


class MigrationAPITests(unittest.TestCase):
    """直接连 sqlite3 调 migration 模块，验证框架独立可用。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "test.db"
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.latest = migration.MIGRATIONS[-1].version

    def _legacy_db(self, with_settings: bool = True) -> None:
        """预置 v1 老库：tasks 表 + 两行数据（+ settings 表与旧键值）。"""
        self.conn.execute(_LEGACY_TASKS_DDL)
        self.conn.execute(
            "INSERT INTO tasks (title, description, tag, quadrant,"
            " completed_at, created_at, updated_at) VALUES"
            " ('老任务甲', '', '', 0, NULL, '2026-09-01 09:00:00',"
            " '2026-09-01 09:00:00'),"
            " ('老任务乙', '旧描述', 'work', 2, '2026-09-02 18:00:00',"
            " '2026-09-01 10:00:00', '2026-09-02 18:00:00')"
        )
        if with_settings:
            self.conn.execute(
                "CREATE TABLE settings (key TEXT PRIMARY KEY,"
                " value TEXT NOT NULL)"
            )
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("user_key", "user_value"),
            )
        self.conn.commit()

    # 1. 新库从 0 跑到最新
    def test_new_db_upgrades_to_latest(self) -> None:
        migration.run_migrations(self.conn)
        self.assertEqual(migration.get_schema_version(self.conn), self.latest)

    # 2. 旧库升级后数据无损
    def test_legacy_db_data_preserved(self) -> None:
        self._legacy_db()
        migration.run_migrations(self.conn)
        self.assertEqual(migration.get_schema_version(self.conn), self.latest)
        rows = self.conn.execute(
            "SELECT id, title, description, tag, quadrant, completed_at"
            " FROM tasks ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["title"], "老任务甲")
        self.assertEqual(rows[1]["description"], "旧描述")
        self.assertEqual(rows[1]["tag"], "work")
        self.assertEqual(rows[1]["quadrant"], 2)
        # 旧设置键值仍在
        val = self.conn.execute(
            "SELECT value FROM settings WHERE key='user_key'"
        ).fetchone()
        self.assertEqual(val["value"], "user_value")

    # 3. 极老库（连 settings 表都没有）也能进入版本管理
    def test_missing_settings_table_created(self) -> None:
        self._legacy_db(with_settings=False)
        migration.run_migrations(self.conn)
        self.assertIn("settings", _table_names(self.conn))
        self.assertEqual(migration.get_schema_version(self.conn), self.latest)
        # 数据仍无损
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"],
            2,
        )

    # 4. 重复运行幂等
    def test_idempotent_rerun(self) -> None:
        self._legacy_db()
        migration.run_migrations(self.conn)
        before = migration.get_schema_version(self.conn)
        rows_before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM tasks"
        ).fetchone()["n"]
        migration.run_migrations(self.conn)  # 第二次：不应有任何动作
        self.assertEqual(migration.get_schema_version(self.conn), before)
        rows_after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM tasks"
        ).fetchone()["n"]
        self.assertEqual(rows_after, rows_before)
        self.assertEqual(rows_after, 2)

    # 5. 迁移失败：DDL 与版本号一起回滚
    def test_failed_migration_rolls_back(self) -> None:
        self._legacy_db()

        def bad_up(conn: sqlite3.Connection) -> None:
            # 先做真实 DDL 再抛错，验证回滚会把列撤销
            conn.execute("ALTER TABLE tasks ADD COLUMN boom TEXT")
            raise RuntimeError("模拟迁移失败")

        fake = [migration.Migration(self.latest + 1, "t-bad", bad_up)]
        with mock.patch.object(migration, "MIGRATIONS", fake):
            with self.assertRaises(RuntimeError):
                migration.run_migrations(self.conn)
        # 版本不前进（仍停在老库的 0）
        self.assertEqual(migration.get_schema_version(self.conn), 0)
        self.assertNotIn("boom", _column_names(self.conn, "tasks"))
        # 数据无损
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"],
            2,
        )
        # 移除坏迁移后再跑成功
        migration.run_migrations(self.conn)
        self.assertEqual(migration.get_schema_version(self.conn), self.latest)

    # 6. 中途失败：前序迁移保留，续跑不重复
    def test_failure_keeps_previous_migrations_and_resumes(self) -> None:
        self._legacy_db()
        applied = []

        def good1(conn: sqlite3.Connection) -> None:
            applied.append("good1")

        def bad2(conn: sqlite3.Connection) -> None:
            applied.append("bad2")
            raise RuntimeError("2 号迁移失败")

        fake = [
            migration.Migration(1, "t-good1", good1),
            migration.Migration(2, "t-bad2", bad2),
        ]
        with mock.patch.object(migration, "MIGRATIONS", fake):
            with self.assertRaises(RuntimeError):
                migration.run_migrations(self.conn)
            self.assertEqual(migration.get_schema_version(self.conn), 1)
            self.assertEqual(applied, ["good1", "bad2"])
            # 续跑：1 号不重跑，只重试 2 号
            with self.assertRaises(RuntimeError):
                migration.run_migrations(self.conn)
            self.assertEqual(applied, ["good1", "bad2", "bad2"])

            # 修复 2 号后：1 号仍不重跑，直接应用 2 号到最新
            def good2(conn: sqlite3.Connection) -> None:
                applied.append("good2")

            fixed = [
                migration.Migration(1, "t-good1", good1),
                migration.Migration(2, "t-good2", good2),
            ]
            with mock.patch.object(migration, "MIGRATIONS", fixed):
                migration.run_migrations(self.conn)
        self.assertEqual(migration.get_schema_version(self.conn), 2)
        self.assertEqual(applied, ["good1", "bad2", "bad2", "good2"])

    # 7. settings 表中 schema_version 行正确
    def test_schema_version_written_in_settings_table(self) -> None:
        migration.run_migrations(self.conn)
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (migration.SCHEMA_VERSION_KEY,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["value"], str(self.latest))

    # 8. 脏版本值拒绝盲目覆盖
    def test_invalid_stored_version_raises(self) -> None:
        self.conn.execute(
            "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            (migration.SCHEMA_VERSION_KEY, "abc"),
        )
        self.conn.commit()
        with self.assertRaises(RuntimeError):
            migration.run_migrations(self.conn)

    # 9. 注册表乱序/重复被拒绝
    def test_out_of_order_registry_rejected(self) -> None:
        bad = [
            migration.Migration(2, "t-first", lambda conn: None),
            migration.Migration(1, "t-second", lambda conn: None),
        ]
        with mock.patch.object(migration, "MIGRATIONS", bad):
            with self.assertRaises(ValueError):
                migration.run_migrations(self.conn)
        dup = [
            migration.Migration(1, "t-a", lambda conn: None),
            migration.Migration(1, "t-b", lambda conn: None),
        ]
        with mock.patch.object(migration, "MIGRATIONS", dup):
            with self.assertRaises(ValueError):
                migration.run_migrations(self.conn)


class DatabaseIntegrationTests(unittest.TestCase):
    """走真实 db.Database 集成点：验证 db.py 的 _init_schema 接上迁移器。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "data.db"
        self.latest = migration.MIGRATIONS[-1].version

    def _legacy_db_file(self) -> None:
        """用原生 sqlite3 写一个老用户 data.db（含数据，未做版本登记）。"""
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(_LEGACY_TASKS_DDL)
            conn.execute(
                "CREATE TABLE settings (key TEXT PRIMARY KEY,"
                " value TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("user_key", "user_value"),
            )
            conn.execute(
                "INSERT INTO tasks (title, description, tag, quadrant,"
                " completed_at, created_at, updated_at) VALUES"
                " ('老任务甲', '', '', 0, NULL, '2026-09-01 09:00:00',"
                " '2026-09-01 09:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

    # 10. 新库初始化即达最新版本
    def test_new_database_init_reaches_latest(self) -> None:
        database = db.Database(self.path)
        try:
            self.assertEqual(
                migration.get_schema_version(database.conn), self.latest
            )
            self.assertEqual(
                database.get_setting(migration.SCHEMA_VERSION_KEY),
                str(self.latest),
            )
        finally:
            database.close()

    # 11. 老库打开自动升级，数据无损、功能可用
    def test_legacy_database_open_upgrades_lossless(self) -> None:
        self._legacy_db_file()
        database = db.Database(self.path)
        try:
            self.assertEqual(
                migration.get_schema_version(database.conn), self.latest
            )
            task = database.get_task(1)
            self.assertIsNotNone(task)
            self.assertEqual(task.title, "老任务甲")
            # 升级后旧设置仍在、读写都正常
            self.assertEqual(
                database.get_setting("user_key"), "user_value"
            )
            new_id = database.add_task(
                "新任务", description="升级后新增", quadrant=1
            )
            self.assertEqual(database.get_task(new_id).title, "新任务")
            self.assertEqual(len(database.get_active_tasks()), 2)
        finally:
            database.close()

    # 12. 重复打开同一库幂等
    def test_reopen_idempotent(self) -> None:
        self._legacy_db_file()
        first = db.Database(self.path)
        first.close()
        second = db.Database(self.path)
        try:
            self.assertEqual(
                migration.get_schema_version(second.conn), self.latest
            )
            self.assertEqual(
                second.conn.execute(
                    "SELECT COUNT(*) AS n FROM tasks"
                ).fetchone()["n"],
                1,
            )
        finally:
            second.close()


if __name__ == "__main__":
    unittest.main()
