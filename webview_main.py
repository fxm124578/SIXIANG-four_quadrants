"""WebView 版主窗口：pywebview + JsApi 桥接 SQLite 数据层。

功能：四象任务 CRUD、跨象限拖拽、日报/导出、设置（主题/模式），
      模式切换时自动重启进程。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import webview
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import Database
from models import quadrant_name
from report import build_report_stats, export_report, export_report_range

THIS_DIR = Path(__file__).resolve().parent


class JsApi:
    """Python→JS 桥，供 window.pywebview.api.* 调用。"""

    def __init__(self, db: Database, settings: Dict[str, str]):
        self.db = db
        self.settings = settings
        self.restart_requested = False
        self._window: Optional[webview.Window] = None

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    # ------------------------------------------------------------------- 任务
    def get_active_tasks(self) -> List[Dict]:
        return [self._task_dict(t) for t in self.db.get_active_tasks()]

    def get_task(self, task_id: int) -> Optional[Dict]:
        task = self.db.get_task(task_id)
        return self._task_dict(task) if task else None

    def add_task(self, title: str, description: str = "", tag: str = "",
                 quadrant: int = 0) -> Dict:
        task_id = self.db.add_task(title, description, tag, int(quadrant))
        return {"id": task_id}

    def complete_task(self, task_id: int) -> bool:
        self.db.complete_task(task_id)
        return True

    def delete_task(self, task_id: int) -> bool:
        self.db.delete_task(task_id)
        return True

    def update_task(self, task_id: int, title: str = "",
                    description: str = "", tag: str = "",
                    quadrant: int = -1) -> bool:
        self.db.update_task(
            task_id,
            title=title or None,
            description=description if description != "" else None,
            tag=tag if tag != "" else None,
            quadrant=int(quadrant) if int(quadrant) >= 0 else None,
        )
        return True

    def set_quadrant(self, task_id: int, quadrant: int) -> bool:
        task = self.db.get_task(task_id)
        if task and task.quadrant != int(quadrant):
            self.db.set_quadrant(task_id, int(quadrant))
        return True

    @staticmethod
    def _task_dict(t) -> Dict:
        return {
            "id": t.id, "title": t.title, "description": t.description,
            "tag": t.tag, "quadrant": t.quadrant,
            "quadrant_label": t.quadrant_label,
            "quadrant_color": t.quadrant_color,
            "completed_at": t.completed_at, "created_at": t.created_at,
        }

    # ------------------------------------------------------------------- 日报
    def get_completed_tasks(self, date_str: str) -> List[Dict]:
        return [self._task_dict(t) for t in self.db.get_completed_tasks(date_str)]

    def get_completed_dates(self) -> List[str]:
        return self.db.get_completed_dates()

    def export_day(self, date_str: str) -> List[str]:
        directory = self._choose_dir()
        if not directory:
            return []
        try:
            files = export_report(self.db, date_str, directory)
            return [str(f) for f in files]
        except OSError:
            return []

    def export_range(self, start: str, end: str) -> List[str]:
        directory = self._choose_dir()
        if not directory:
            return []
        try:
            files = export_report_range(self.db, start, end, directory)
            return [str(f) for f in files]
        except OSError:
            return []

    @staticmethod
    def _choose_dir() -> str:
        """pywebview 无法直接弹 native 文件夹对话框（无 GUI 线程安全）；
        默认导出到桌面。"""
        desktop = Path.home() / "Desktop"
        if not desktop.is_dir():
            desktop = Path.home()
        out = desktop / "四象限日报导出"
        out.mkdir(parents=True, exist_ok=True)
        return str(out)

    # ------------------------------------------------------------------- 设置
    def get_settings(self) -> Dict[str, str]:
        return dict(self.settings)

    def save_settings(self, patch: Dict[str, Any]) -> bool:
        for key, value in patch.items():
            value_str = str(value)
            self.settings[key] = value_str
            self.db.set_setting(key, value_str)
        # 窗口模式变更需要重启（关闭当前窗口，run() 循环会重新创建）
        if "window_mode" in patch:
            self.restart_requested = True
            if self._window:
                try:
                    self._window.destroy()
                except Exception:
                    pass
        return True

    def quit(self) -> None:
        if self._window:
            self._window.destroy()

    def resize(self, width: int, height: int) -> bool:
        """调整窗口大小（JS 端拖拽边缘时调用）。"""
        if self._window:
            try:
                self._window.resize(int(width), int(height))
            except Exception:
                pass
        return True

    # --------------------------------------------------------------- 工具
    @staticmethod
    def _tag_list(raw: str) -> List[str]:
        if not raw or not raw.strip():
            return []
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(t).strip() for t in data if str(t).strip()]
        except (ValueError, TypeError):
            pass
        return [raw.strip()]


def _read_settings(db: Database) -> Dict[str, str]:
    keys = ("theme", "window_mode", "window_x", "window_y",
            "window_width", "window_height", "locked", "opacity")
    return {k: (db.get_setting(k) or "") for k in keys}


def _set_window_icon(window, ico_path: str) -> None:
    """用 ctypes 设置 pywebview 窗口的 ICO 图标（任务栏 + 标题栏）。"""
    try:
        import ctypes
        user32 = ctypes.windll.user32

        # 方式1：直接从 pywebview window 对象获取句柄
        hwnd = getattr(window, '_hwnd', None)
        if not hwnd:
            hwnd = getattr(window, 'native_handle', None)

        # 方式2：按窗口标题查找（兜底，兼容 pywebview 不同版本）
        if not hwnd:
            hwnd = user32.FindWindowW(None, "四象")
        if not hwnd:
            # 遍历所有顶层窗口找 pywebview 的
            def _enum_cb(h, _):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(h, buf, 256)
                if "四象限" in buf.value or "pywebview" in buf.value.lower():
                    nonlocal hwnd
                    hwnd = h
                return True
            ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(ENUMPROC(_enum_cb), 0)

        if not hwnd:
            return

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        # 设置 32x32 大图标（任务栏）和 16x16 小图标（标题栏）
        hicon_big = user32.LoadImageW(None, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        hicon_small = user32.LoadImageW(None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        WM_SETICON = 0x0080
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, hicon_big)  # ICON_BIG
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, hicon_small)  # ICON_SMALL
    except Exception:
        pass


def _set_icon_with_retry(window, ico_path: str) -> None:
    """延迟重试设置图标（窗口初始化可能需要时间）。"""
    import threading
    import time

    def _try():
        for delay in (0.5, 1.0, 2.0):
            time.sleep(delay)
            _set_window_icon(window, ico_path)

    threading.Thread(target=_try, daemon=True).start()


def _make_window(api: JsApi, db: Database, html_path: str) -> webview.Window:
    settings = api.settings
    mode = settings.get("window_mode", "topmost")
    frameless = mode != "normal"
    on_top = mode == "topmost"

    try:
        width = max(600, min(int(settings.get("window_width") or 800), 1600))
    except ValueError:
        width = 800
    try:
        height = max(450, min(int(settings.get("window_height") or 600), 1200))
    except ValueError:
        height = 600
    try:
        x = int(settings.get("window_x") or 100)
        y = int(settings.get("window_y") or 100)
    except ValueError:
        x, y = 100, 100

    window = webview.create_window(
        "四象",
        url=html_path,
        js_api=api,
        width=width, height=height, x=x, y=y,
        frameless=frameless,
        on_top=on_top,
        easy_drag=True,  # 默认整个窗口可拖动，CSS 排除交互区域
    )
    api.set_window(window)
    return window


def run() -> int:
    db = Database()
    try:
        settings = _read_settings(db)
        api = JsApi(db, settings)
        html_path = str(THIS_DIR / "web" / "app.html")

        while True:
            settings = _read_settings(db)
            api.settings = settings
            api.restart_requested = False
            window = _make_window(api, db, html_path)

            # 监听窗口 move/size 事件持久化
            def on_moved(w, x, y, _w=window):
                db.set_setting("window_x", str(x))
                db.set_setting("window_y", str(y))

            def on_resized(w, width, height, _w=window):
                db.set_setting("window_width", str(width))
                db.set_setting("window_height", str(height))

            window.events.moved += on_moved
            window.events.resized += on_resized

            # 设置四象限应用图标
            from styles import ensure_app_icon
            ico_path = ensure_app_icon()
            if ico_path:
                def _on_loaded(*_a, _ico=ico_path, _w=window):
                    _set_icon_with_retry(_w, _ico)
                window.events.loaded += _on_loaded

            webview.start(debug=False)

            # 窗口关闭后检查是否需要重启（模式切换）
            if api.restart_requested:
                settings = _read_settings(db)
                continue
            break

        db.close()
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        db.close()
        return 1


if __name__ == "__main__":
    sys.exit(run())
