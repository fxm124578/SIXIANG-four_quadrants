"""WebView 版主窗口：pywebview + JsApi 桥接 SQLite 数据层。

功能：四象任务 CRUD、跨象限拖拽、日报/导出、设置（主题/模式），
      模式切换时自动重启进程。
"""
from __future__ import annotations

import sys
import webview
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import Database
from report import export_report, export_report_range
import autostart
import theme_loader
import updater

THIS_DIR = Path(__file__).resolve().parent


def _render_html() -> str:
    """渲染 app.html 模板：注入可插拔主题 CSS 与主题清单。

    打包 onefile 下 app.html 位于临时解压目录（_MEIPASS），而主题目录
    在 exe 同目录 themes/，故不能用 <link> 相对路径，改为启动时把全部
    主题 CSS 与清单 JSON 内联注入后以 html 字符串加载。
    """
    template = (THIS_DIR / "web" / "app.html").read_text(encoding="utf-8")
    css = theme_loader.all_themes_css()
    meta = theme_loader.theme_meta_json()
    return (template
            .replace("/*__THEMES_CSS__*/",
                     "/* ============ 主题（themes/ 目录可插拔） ============ */\n" + css)
            .replace("/*__THEMES_META__*/",
                     f"window.__PROMATHEMES__ = {meta};"))


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
        return [t.to_dict() for t in self.db.get_active_tasks()]

    def get_task(self, task_id: int) -> Optional[Dict]:
        task = self.db.get_task(task_id)
        return task.to_dict() if task else None

    def add_task(self, title: str, description: str = "", tag: str = "",
                 quadrant: int = 0) -> Dict:
        task_id = self.db.add_task(title, description, tag, int(quadrant))
        return {"id": task_id}

    def complete_task(self, task_id: int) -> bool:
        self.db.complete_task(task_id)
        return True

    def uncomplete_task(self, task_id: int) -> bool:
        """取消完成：清空完成时间，任务回到四象限主页。"""
        self.db.update_task(task_id, completed_at="")
        return True

    def delete_task(self, task_id: int) -> bool:
        self.db.delete_task(task_id)
        return True

    def update_task(self, task_id: int, title: Optional[str] = None,
                    description: Optional[str] = None,
                    tag: Optional[str] = None, quadrant: int = -1,
                    completed_at: Optional[str] = None) -> bool:
        """更新任务；None 表示不改，空字符串表示用户明确清空该字段。"""
        self.db.update_task(
            task_id,
            title=title,
            description=description,
            tag=tag,
            quadrant=int(quadrant) if int(quadrant) >= 0 else None,
            completed_at=completed_at,
        )
        return True

    def set_quadrant(self, task_id: int, quadrant: int) -> bool:
        task = self.db.get_task(task_id)
        if task and task.quadrant != int(quadrant):
            self.db.update_task(task_id, quadrant=int(quadrant))
        return True

    # ------------------------------------------------------------------- 标签
    def get_all_tags(self) -> List[str]:
        """获取所有任务中的标签列表。"""
        return self.db.get_all_tags()


    # ------------------------------------------------------------------- 日报
    def get_completed_tasks(self, date_str: str) -> List[Dict]:
        return [t.to_dict() for t in self.db.get_completed_tasks(date_str)]

    def get_completed_dates(self) -> List[str]:
        return self.db.get_completed_dates()

    def export_day(self, date_str: str) -> List[str]:
        directory = self._choose_dir()
        if not directory:
            return []
        try:
            files = export_report(self.db, date_str, directory)
            return [str(f) for f in files]
        except OSError as exc:
            raise RuntimeError(f"无法写入导出目录：{exc}") from exc

    def export_range(self, start: str, end: str) -> List[str]:
        directory = self._choose_dir()
        if not directory:
            return []
        try:
            files = export_report_range(self.db, start, end, directory)
            return [str(f) for f in files]
        except OSError as exc:
            raise RuntimeError(f"无法写入导出目录：{exc}") from exc

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
        # 仅当窗口模式实际变化时才重启（避免只改自启动/主题也强制重启，
        # 并确保自启动等写操作在重启前完成）
        restart = False
        if "window_mode" in patch:
            restart = str(patch["window_mode"]) != self.settings.get(
                "window_mode", "topmost")
        for key, value in patch.items():
            value_str = str(value)
            self.settings[key] = value_str
            self.db.set_setting(key, value_str)
        if restart:
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

    # --------------------------------------------------------------- 主题
    def get_theme_list(self) -> List[Dict]:
        """主题清单（设置下拉框用）。"""
        return theme_loader.theme_list()

    def import_theme(self, file_name: str, content: str) -> Dict:
        """导入主题：把 CSS 内容写入用户 themes/ 目录（快速安装）。"""
        import re as _re
        if not file_name or not content:
            return {"ok": False, "error": "文件为空"}
        name = Path(file_name).name.strip()
        if not _re.match(r"^[a-z0-9][a-z0-9_-]*\.css$", name):
            return {"ok": False, "error": "文件名需为 ASCII 且以 .css 结尾（如 my-theme.css）"}
        tid = name[:-4]
        if not _re.search(rf"body\.{_re.escape(tid)}\s*{{", content):
            return {"ok": False, "error": f"CSS 中缺少 body.{tid}{{...}} 定义"}
        if len(content) > 1024 * 512:
            return {"ok": False, "error": "文件过大（>512KB）"}
        try:
            dst = theme_loader.themes_dir() / name
            dst.write_text(content, encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "error": f"写入失败：{exc}"}
        return {"ok": True, "id": tid, "file": name}

    # --------------------------------------------------------------- 开机自启动
    def get_autostart(self) -> bool:
        """当前是否已注册开机自启动。"""
        return autostart.is_enabled()

    def set_autostart(self, enabled: bool) -> bool:
        """开启 / 关闭开机自启动（写入 HKCU Run 注册表）。"""
        return autostart.set_enabled(bool(enabled))

    # --------------------------------------------------------------- 更新
    def get_app_version(self) -> Dict[str, str]:
        return {"version": updater.APP_VERSION}

    def start_check_update(self) -> Dict:
        """后台线程检查 GitHub release；返回当前状态，UI 轮询。"""
        return updater.start_check()

    def get_update_state(self) -> Dict:
        return updater.get_state()

    def start_download_update(self) -> Dict:
        return updater.start_download()

    def apply_update(self) -> Dict:
        r = updater.apply_update()
        if r.get("ok"):
            # 更新已进入应用流程，清除持久化就绪状态
            self.db.set_setting("update_ready_path", "")
        return r

    def resize(self, width: int, height: int) -> bool:
        """调整窗口大小（JS 端拖拽边缘时调用）。"""
        if self._window:
            try:
                self._window.resize(int(width), int(height))
            except Exception:
                pass
        return True

    # --------------------------------------------------------------- 工具
def _read_settings(db: Database) -> Dict[str, str]:
    keys = ("theme", "window_mode", "window_x", "window_y",
            "locked", "opacity")
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


def _make_window(api: JsApi, db: Database, rendered_html: str) -> webview.Window:
    settings = api.settings
    mode = settings.get("window_mode", "topmost")
    frameless = mode != "normal"
    on_top = mode == "topmost"

    # 每次启动固定 4:3（800×600），不读取也不持久化窗口尺寸
    width, height = 800, 600
    try:
        x = int(settings.get("window_x") or 100)
        y = int(settings.get("window_y") or 100)
    except ValueError:
        x, y = 100, 100

    window = webview.create_window(
        "四象",
        html=rendered_html,
        js_api=api,
        width=width, height=height, x=x, y=y,
        frameless=frameless,
        on_top=on_top,
        easy_drag=False,  # 拖动仅限 .pywebview-drag-region 头部区域（见 run()）
    )
    api.set_window(window)
    return window


def run() -> int:
    db = Database()
    try:
        # 窗口拖动限定在标记了 .pywebview-drag-region 的头部区域：
        # pywebview 6.2.1 的 easy_drag=True 会无条件捕获 window mousedown 移动
        # 窗口（CSS no-drag 无效），导致长按选词/拖任务时误拖窗口，故关闭它。
        webview.settings['DRAG_REGION_SELECTOR'] = '.pywebview-drag-region'
        # 更新就绪状态持久化：下载完成写入 DB，重启后恢复，可随时进设置安装
        updater.set_persist_ready_cb(
            lambda p: db.set_setting("update_ready_path", p))
        ready_path = db.get_setting("update_ready_path") or ""
        if ready_path:
            if not updater.restore_ready(ready_path):
                # 文件已不存在（如手动删除），清除过期持久化状态
                db.set_setting("update_ready_path", "")
        # 统一 SIXIANG 命名：新命名已生效时清理历史遗留中文 exe，避免误开旧版
        updater.cleanup_legacy_exes()

        settings = _read_settings(db)
        api = JsApi(db, settings)
        # 主题目录初始化（首次复制内置）+ 渲染注入主题
        theme_loader.ensure_themes_dir()
        rendered_html = _render_html()

        while True:
            settings = _read_settings(db)
            api.settings = settings
            api.restart_requested = False
            window = _make_window(api, db, rendered_html)

            # 监听窗口位置持久化（尺寸固定 4:3，不保存）
            def on_moved(w, x, y, _w=window):
                db.set_setting("window_x", str(x))
                db.set_setting("window_y", str(y))

            window.events.moved += on_moved

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
