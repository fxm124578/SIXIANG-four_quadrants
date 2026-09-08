"""WebView 版主窗口：pywebview + JsApi 桥接 SQLite 数据层。

功能：四象任务 CRUD、跨象限拖拽、日报/导出、设置（主题/模式），
      模式切换时自动重启进程。

v2.0：页面不再以 html 字符串加载，改为进程内本地静态服务
（127.0.0.1 随机端口，daemon 线程）提供拆分后的 index.html /
app.css / app.js；主题 CSS 与主题清单由服务端注入（见 web_base_url）。
"""
from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

# pywebview 仅 Windows/桌面目标机必需；macOS 开发机未安装时模块仍可
# import（平台守卫：走 tkinter 回退或测试加载），run() 入口会先行判断。
try:
    import webview
except ImportError:
    webview = None  # type: ignore[assignment]

from db import Database
from report import export_report, export_report_range
import autostart
import hotkey
import single_instance
import theme_loader
import tray
import updater

THIS_DIR = Path(__file__).resolve().parent


# ------------------------------------------------------------------ 资源定位
def _resolve_web_file(name: str) -> Optional[Path]:
    """定位页面资源文件：用户外置层优先，内置目录兜底。

    - 外置层：应用数据目录 web/（onedir 安装 = exe 同目录 web/，安装时从
      _internal/web 复制一份，用户可直接改文件、重启即生效）；
      源码模式下通常不存在（项目根无 web/）。
    - 内置兜底：本文件同目录 web/（源码 = src/web；打包 onedir 后模块在
      _internal/ 内，与 --add-data "src/web;web" 的落点一致，无需 _MEIPASS）。

    按文件粒度回退：外置层缺个别文件时仍可用内置对应文件，避免 404 白屏。
    """
    for base in (theme_loader.app_dir() / "web", THIS_DIR / "web"):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


# ------------------------------------------------------------------ 页面渲染
def render_index_page() -> str:
    """渲染 index.html：把主题清单 JSON 注入 /*__THEMES_META__*/ 占位。

    注入后生成 ``window.__PROMATHEMES__ = [...]`` 内联脚本，先于 app.js
    执行（app.js 顶层 ``THEME_LIST = window.__PROMATHEMES__ || []`` 依赖它）。
    """
    template = _resolve_web_file("index.html")
    if template is None:
        raise RuntimeError("内置页面 index.html 缺失，请检查安装完整性")
    html = template.read_text(encoding="utf-8")
    meta = theme_loader.theme_meta_json()
    return html.replace("/*__THEMES_META__*/",
                        f"window.__PROMATHEMES__ = {meta};")


def render_style_sheet() -> str:
    """渲染 app.css：把全部主题 CSS 注入 /*__THEMES_CSS__*/ 占位。

    主题目录在应用目录 themes/（可插拔、可导入），故每次请求现读现注入，
    导入新主题后重启窗口或刷新页面即生效（v2.0「改文件刷新」目标）。
    """
    template = _resolve_web_file("app.css")
    if template is None:
        raise RuntimeError("内置页面 app.css 缺失，请检查安装完整性")
    css = template.read_text(encoding="utf-8")
    themes_css = theme_loader.all_themes_css()
    return css.replace(
        "/*__THEMES_CSS__*/",
        "/* ============ 主题（themes/ 目录可插拔） ============ */\n" + themes_css)


# ------------------------------------------------------------------ 本地静态服务
class _PageHandler(BaseHTTPRequestHandler):
    """页面资源端点：/ 与 /app.css / /app.js；白名单外一律 404。"""

    # 路由表：请求路径 → (渲染函数或 None=原样文件, Content-Type)
    _ROUTES = {
        "": (render_index_page, "text/html; charset=utf-8"),
        "index.html": (render_index_page, "text/html; charset=utf-8"),
        "app.css": (render_style_sheet, "text/css; charset=utf-8"),
        "app.js": (None, "text/javascript; charset=utf-8"),
    }

    def do_GET(self):
        name = urlsplit(self.path).path.lstrip("/")
        route = self._ROUTES.get(name)
        try:
            if route is None:
                self._send(b"404 Not Found", "text/plain; charset=utf-8", 404)
                return
            render, ctype = route
            if render is not None:
                body = render().encode("utf-8")
            else:
                file = _resolve_web_file(name)
                if file is None:
                    self._send(b"404 Not Found", "text/plain; charset=utf-8", 404)
                    return
                body = file.read_bytes()
            self._send(body, ctype)
        except Exception as exc:
            # 渲染/读取异常给明确文本，避免窗口静默白屏
            msg = f"500 Server Error: {exc}".encode("utf-8")
            self._send(msg, "text/plain; charset=utf-8", 500)

    def _send(self, body: bytes, ctype: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 页面资源一律不缓存：外置改文件后重启/刷新即生效
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        """GUI 应用不向终端刷访问日志。"""
        pass


class _LocalWebServer:
    """进程内本地静态服务：绑定 127.0.0.1 随机端口，daemon 线程常驻。"""

    def __init__(self):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), _PageHandler)
        except OSError as exc:
            raise RuntimeError(
                f"内置页面服务启动失败（{exc}）。请稍后重试，"
                "或卸载重装本应用。"
            ) from exc
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self.base_url = f"http://127.0.0.1:{self.port}/"
        threading.Thread(
            target=httpd.serve_forever,
            daemon=True,
            name=f"sixiang-web-{self.port}",
        ).start()

    def shutdown(self):
        """停止服务（测试用；生产进程退出时 daemon 线程自动终止）。"""
        self._httpd.shutdown()
        self._httpd.server_close()


_server: Optional[_LocalWebServer] = None


def web_base_url() -> str:
    """返回内置页面服务地址（进程级惰性单例，如 http://127.0.0.1:PORT/）。"""
    global _server
    if _server is None:
        _server = _LocalWebServer()
    return _server.base_url


_js_api: Optional["JsApi"] = None
_CLEAR_HOVER_JS = (
    "(function(){var b=document.body;if(!b)return;"
    "if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();"
    "b.style.pointerEvents='none';void b.offsetHeight;b.style.pointerEvents='';})()"
)


class JsApi:
    """Python→JS 桥，供 window.pywebview.api.* 调用。"""

    def __init__(self, db: Database, settings: Dict[str, str]):
        self.db = db
        self.settings = settings
        self.restart_requested = False  # 模式切换：窗口销毁后由 run() 重建
        self.quit_requested = False     # 托盘退出 / 更新退出 / 显式退出
        self.tray_ready = False         # 托盘就绪后才允许隐藏，避免窗口消失无法找回
        self._window: Optional[webview.Window] = None
        self._apply_hotkey = None       # run() 注入：热键配置变更时重注册

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
        # 热键配置变更：重注册全局热键（注册失败回滚旧组合并打 stderr）
        if "hotkey" in patch and self._apply_hotkey is not None:
            self._apply_hotkey(str(patch["hotkey"]))
        if restart:
            self.restart_requested = True
            if self._window:
                try:
                    self._window.destroy()
                except Exception:
                    pass
        return True

    def quit(self) -> None:
        """显式退出（UI 退出按钮）：置退出标志后放行关闭。"""
        self.quit_requested = True
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass

    def minimize(self) -> bool:
        """JS 前台最小化入口（与 hide_to_tray 相同）。"""
        return self.hide_to_tray()

    def hide_to_tray(self) -> bool:
        """前台最小化：隐藏窗口，不退出。不依赖托盘是否就绪。"""
        if self._window is None:
            return False
        try:
            native = getattr(self._window, "native", None)
            handle = getattr(native, "Handle", None) if native is not None else None
            if handle:
                import ctypes
                ctypes.windll.user32.ShowWindow(int(handle), 0)  # SW_HIDE
                return True
        except Exception:
            pass
        try:
            self._window.hide()
        except Exception:
            return False
        return True

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
            # 更新已进入应用流程：本进程干净退出，让安装器静默覆盖安装
            # （ShellExecute 已返回，Setup 独立运行不受影响；见 plan §10）
            self.quit_requested = True
            self.db.set_setting("update_ready_path", "")
            if self._window:
                try:
                    self._window.destroy()
                except Exception:
                    pass
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
            "locked", "opacity", "hotkey")
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


# ------------------------------------------------------------ 系统层（v2.0）
def _find_main_hwnd() -> int:
    """按标题现查主窗口句柄（win32；托盘/关闭投递用，非 win32 返回 0）。

    模式切换会重建窗口（句柄变化），后台线程每次现查避免持有失效句柄。
    """
    if sys.platform != "win32":
        return 0
    return single_instance.find_window_by_title()


def _show_main_window() -> None:
    """唤起主窗口：恢复显示并置前（win32 user32，跨线程安全）。

    托盘菜单/热键/单实例激活回调共用；非 win32 no-op。
    藏窗时按钮 :hover 不会自动清除，唤起后补一次。
    """
    if sys.platform != "win32":
        return
    single_instance.activate_window_by_title()
    api = _js_api
    window = api._window if api is not None else None
    if window is None:
        return
    try:
        window.evaluate_js(_CLEAR_HOVER_JS)
    except Exception:
        pass


def _close_main_window() -> None:
    """向主窗口投递 WM_CLOSE（跨线程安全；closing 处判断是否放行）。"""
    hwnd = _find_main_hwnd()
    if not hwnd:
        return
    try:
        import ctypes
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except (AttributeError, OSError):
        pass


def _start_system_layer(api: JsApi, db: Database,
                        settings: Dict[str, str]) -> bool:
    """启动常驻系统层（win32）：全局热键 + 托盘图标。

    非 win32 返回 False（不启用常驻语义，关闭即退出，同 v1）。
    返回托盘是否就绪：关闭拦截依赖它决定「隐藏到托盘」还是「放行退出」，
    托盘启动失败时宁可直接退出，避免窗口"消失"后无法找回。
    热键注册失败只打 stderr，不阻断启动。
    """
    if sys.platform != "win32":
        return False

    # 热键默认值入库（settings key: hotkey；设置 UI 后续版本读写同一存储）
    if not settings.get("hotkey"):
        default = hotkey.DEFAULT_HOTKEY
        db.set_setting("hotkey", default)
        settings["hotkey"] = default
        api.settings = settings

    def _on_hotkey() -> None:
        _show_main_window()

    def _reapply_hotkey(new_spec: str) -> bool:
        """热键变更后重注册；失败回滚旧组合（UI 后续版本再做用户提示）。"""
        old = settings.get("hotkey") or hotkey.DEFAULT_HOTKEY
        ok, err = hotkey.register(new_spec, _on_hotkey)
        if ok:
            return True
        print(f"[hotkey] {err}", file=sys.stderr)
        hotkey.register(old, _on_hotkey)
        return False

    api._apply_hotkey = _reapply_hotkey
    ok, err = hotkey.register(
        settings.get("hotkey") or hotkey.DEFAULT_HOTKEY, _on_hotkey)
    if not ok:
        print(f"[hotkey] {err}", file=sys.stderr)

    # 托盘「退出」：置退出标志 + WM_CLOSE → GUI 正常关闭流程（closing 放行）
    def _on_tray_quit() -> None:
        api.quit_requested = True
        _close_main_window()

    from styles import ensure_app_icon
    return tray.start(_find_main_hwnd, _on_tray_quit,
                      icon_path=ensure_app_icon())


def _stop_system_layer() -> None:
    """收尾停止托盘与热键（幂等；非 win32 no-op）。"""
    try:
        tray.stop()
    except Exception:
        pass
    try:
        hotkey.stop()
    except Exception:
        pass


def _make_window(api: JsApi, db: Database) -> webview.Window:
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

    # v2.0：页面由进程内本地静态服务提供（url= 加载），
    # 资源外置后可改文件直接生效；js_api/窗口参数与旧 html= 方案一致。
    window = webview.create_window(
        "四象",
        url=web_base_url(),
        js_api=api,
        width=width, height=height, x=x, y=y,
        frameless=frameless,
        on_top=on_top,
        easy_drag=False,  # 拖动仅限 .pywebview-drag-region 头部区域（见 run()）
    )
    api.set_window(window)
    return window


def run() -> int:
    if webview is None:
        # 平台守卫：pywebview 不可用（非 Windows/未安装）时由 main.py
        # 走 tkinter 回退，本入口仅作防御，不让 run() 半途炸在 AttributeError。
        return 2
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
        global _js_api
        _js_api = api
        # 主题目录初始化（首次复制内置）
        theme_loader.ensure_themes_dir()
        # 启动内置页面服务（失败即抛明确错误，由 main.py 回退 tkinter 版）
        web_base_url()
        # v2.0 系统层：全局热键 + 托盘常驻（非 win32 / 失败自动降级）
        tray_ready = _start_system_layer(api, db, settings)
        api.tray_ready = tray_ready

        while True:
            settings = _read_settings(db)
            api.settings = settings
            api.restart_requested = False
            window = _make_window(api, db)

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

            # v2.0 常驻：窗口真正就绪后才注册单实例激活回调（幂等）——
            # 二次实例的激活事件若在窗口创建前到达会保持 signaled，
            # 此处注册后才启动等待线程，信号不丢失
            def _on_window_ready(*_a):
                single_instance.set_activate_callback(_show_main_window)
            window.events.loaded += _on_window_ready

            # v2.0 常驻：常规关闭（点 X / Alt+F4 / 任务栏关闭）→ 取消关闭并
            # 隐藏到托盘继续运行；模式切换重启 / 托盘退出 / 更新退出 /
            # 显式退出 → 放行真正关闭。托盘不可用时不隐藏（直接退出，
            # 避免窗口“消失”后无法找回）。
            # pywebview 6.2.1：closing handler 返回 False → WinForms
            # FormClosing args.Cancel=True（同步执行，异常被吞）
            def _on_closing():
                if api.restart_requested or api.quit_requested or not tray_ready:
                    return None
                try:
                    window.hide()
                except Exception:
                    return None
                return False
            window.events.closing += _on_closing

            webview.start(debug=False)

            # 窗口关闭后检查是否需要重启（模式切换）
            if api.restart_requested:
                settings = _read_settings(db)
                continue
            break

        # 常驻收尾：移除托盘图标并退出热键线程（幂等）
        _stop_system_layer()
        db.close()
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        # 异常退出也停托盘/热键，避免图标残留
        _stop_system_layer()
        db.close()
        return 1


if __name__ == "__main__":
    sys.exit(run())
