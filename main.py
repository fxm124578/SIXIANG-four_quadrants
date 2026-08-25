"""四象桌面小组件入口。

优先使用 pywebview（WebView 版，四套设计 100% 还原）；
若 pywebview 不可用则回退 tkinter 版（零依赖近似实现）。

运行：python main.py 或 pythonw main.py
"""
from __future__ import annotations

import ctypes
import sys
import traceback


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _try_webview() -> bool:
    """尝试 import webview，返回 True 表示可用。"""
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def _run_webview() -> int:
    _enable_dpi_awareness()
    from webview_main import run
    return run()


def _run_tkinter() -> int:
    _enable_dpi_awareness()
    import tkinter as tk
    from tkinter import messagebox
    from db import Database
    from widgets.main_widget import MainWindow

    db = None
    try:
        db = Database()
        window = MainWindow(db)
        window.mainloop()
        return 0
    except Exception as exc:
        detail = traceback.format_exc()
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("启动失败", f"程序启动失败：\n{exc}")
            root.destroy()
        except Exception:
            print(detail, file=sys.stderr)
        return 1
    finally:
        if db is not None:
            db.close()


def main() -> int:
    if _try_webview():
        try:
            return _run_webview()
        except Exception:
            traceback.print_exc()
            # webview 失败则回退 tkinter
    return _run_tkinter()


if __name__ == "__main__":
    raise SystemExit(main())
