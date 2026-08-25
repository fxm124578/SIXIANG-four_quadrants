"""SQLite 数据访问层。

数据库默认创建在程序目录下 data.db；若目录不可写则回退到用户主目录。
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from models import Task

TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _now() -> str:
    return datetime.now().strftime(TIME_FMT)


def _default_db_path() -> Path:
    """数据库默认位置：

    - 源码运行：程序目录（__file__ 所在目录）
    - PyInstaller onefile 打包：exe 所在目录。
      注意不能用 __file__，onefile 下它指向临时解压目录（_MEIPASS），
      进程退出后目录被清理，数据会丢失。
    - 以上目录不可写时回退 ~/.quadrant_tasks/data.db
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    candidates = [
        base / "data.db",
        Path.home() / ".quadrant_tasks" / "data.db",
    ]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8"):
                pass
            return path
        except OSError:
            continue
    raise RuntimeError("无法创建数据库文件，请检查目录写入权限。")


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _default_db_path()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ------------------------------------------------------------------ schema
    def _init_schema(self) -> None:
        with self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
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
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_completed_at "
                "ON tasks (completed_at)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_quadrant ON tasks (quadrant)"
            )

    # ------------------------------------------------------------------- task
    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            title=row["title"],
            description=row["description"] or "",
            tag=row["tag"] or "",
            quadrant=int(row["quadrant"]),
            completed_at=row["completed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def add_task(self, title: str, description: str = "", tag: str = "",
                 quadrant: int = 0) -> int:
        now = _now()
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO tasks (title, description, tag, quadrant,
                                   completed_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?)
                """,
                (title, description, tag, int(quadrant), now, now),
            )
        return int(cur.lastrowid)

    def get_task(self, task_id: int) -> Optional[Task]:
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (int(task_id),)
        ).fetchone()
        return self._row_to_task(row) if row else None

    def complete_task(self, task_id: int) -> None:
        """勾选任务：写入完成时间，自动归档（不再出现在四象限）。"""
        with self.conn:
            self.conn.execute(
                """
                UPDATE tasks
                SET completed_at = COALESCE(completed_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (_now(), _now(), int(task_id)),
            )

    def delete_task(self, task_id: int) -> None:
        """永久删除任务。"""
        with self.conn:
            self.conn.execute(
                "DELETE FROM tasks WHERE id = ?", (int(task_id),)
            )

    def update_task(self, task_id: int, title: str = None,
                    description: str = None, tag: str = None,
                    quadrant: int = None) -> None:
        """更新任务字段（仅传入需要更新的字段）。"""
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if tag is not None:
            updates.append("tag = ?")
            params.append(tag)
        if quadrant is not None:
            updates.append("quadrant = ?")
            params.append(int(quadrant))
        if not updates:
            return
        updates.append("updated_at = ?")
        params.append(_now())
        params.append(int(task_id))
        with self.conn:
            self.conn.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                params,
            )

    def get_active_tasks(self) -> List[Task]:
        """未完成任务，按创建时间倒序（新的在上）。"""
        rows = self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE completed_at IS NULL
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_completed_tasks(self, date_str: str) -> List[Task]:
        """某天（YYYY-MM-DD）完成归档的任务，按完成时间升序。"""
        rows = self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE date(completed_at) = ?
            ORDER BY completed_at ASC, id ASC
            """,
            (date_str,),
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_completed_dates(self) -> List[str]:
        """所有存在完成记录且已归档的日期（YYYY-MM-DD）。"""
        rows = self.conn.execute(
            """
            SELECT DISTINCT date(completed_at) AS d
            FROM tasks
            WHERE completed_at IS NOT NULL
            ORDER BY d DESC
            """
        ).fetchall()
        return [str(row["d"]) for row in rows]

    # --------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass
