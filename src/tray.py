"""Windows 托盘常驻（纯 ctypes + 标准库，无第三方依赖）。

- start() 启动守护线程：注册窗口类 → 创建隐藏消息窗口 → 加载托盘图标
  （app_icon.ico，经 LoadImageW；文件缺失/加载失败时兜底绘制 32×32 纯色
  HICON，兜底再失败则托盘项不带图标仍可显示）→ Shell_NotifyIconW(NIM_ADD)
  → GetMessageW 消息循环。
- 托盘消息：单击/双击左键 = 显示主窗口；右键 = 弹出菜单（显示主窗口 /
  分隔线 / 退出）。菜单不加多余项。
- 线程安全设计：托盘命令处理全部发生在托盘线程——「显示」直接对主窗口
  hwnd 调 ShowWindow/SetForegroundWindow（跨线程安全，无需主 GUI 线程
  参与，hwnd 由接入层 getter 每次现查）；「退出」调用接入层 on_quit 回调
  （WebView 版 = 置退出标志 + PostMessageW(hwnd, WM_CLOSE) 走 GUI 正常
  关闭流程；tkinter 版 = after(0, ...) 回主线程销毁），具体退出动作由接入
  层决定，本模块不替 GUI 做决定。
- stop() 幂等、可跨线程：向托盘窗口投递 WM_CLOSE → 托盘线程内
  NIM_DELETE + DestroyIcon + 退出消息循环 → join 至多 2 秒。

非 win32（macOS 开发机）：模块可正常 import；start() 返回 False（未启动），
stop() 无操作。所有 windll 访问都发生在 win32 函数体内，import 零副作用。
"""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

from win32_wnd import WNDPROC, create_message_window, def_window_proc

# ------------------------------------------------------------ win32 常量
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_WM_APP = 0x8000
_WM_CLOSE = 0x0010
_WM_LBUTTONUP = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205
_WM_CONTEXTMENU = 0x007B
_NIM_ADD = 0x00000000
_NIM_DELETE = 0x00000002
_NIF_MESSAGE = 0x00000001
_NIF_ICON = 0x00000002
_NIF_TIP = 0x00000004
_TPM_RIGHTBUTTON = 0x0002
_TPM_RETURNCMD = 0x0100
_MF_STRING = 0x0000
_MF_SEPARATOR = 0x0800
_SW_SHOW = 5
_SW_RESTORE = 9

ICON_ID = 1                # NOTIFYICONDATAW.uID
WM_TRAY_CALLBACK = _WM_APP + 1
MENU_SHOW = 1              # 菜单命令 id（TrackPopupMenu 返回值）
MENU_QUIT = 2

_READY_TIMEOUT = 3.0       # start() 等待托盘线程就绪的秒数
_STOP_JOIN_TIMEOUT = 2.0   # stop() join 等待秒数

# ------------------------------------------------------------ 模块级托盘状态
# 单实例应用至多一个托盘，用模块级状态即可；WndProc 需访问回调与窗口句柄。
_worker: Optional[threading.Thread] = None
_tray_hwnd = 0
_icon_handle = 0
_app_hwnd_getter: Optional[Callable[[], Optional[int]]] = None
_on_quit: Optional[Callable[[], None]] = None
_ready: Optional[threading.Event] = None
_wnd_proc_refs: list = []  # 持有历次 ctypes 回调引用防 GC（窗口类可能重注册）

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    _kernel32 = ctypes.windll.kernel32
    _shell32 = ctypes.windll.shell32


# ------------------------------------------------------------ 显示主窗口
def _activate_main() -> None:
    """托盘线程内唤起主窗口：ShowWindow + SetForegroundWindow（跨线程安全）。"""
    getter = _app_hwnd_getter
    hwnd = getter() if getter else None
    if not hwnd:
        return
    try:
        _user32.ShowWindow(hwnd, _SW_RESTORE)
        _user32.ShowWindow(hwnd, _SW_SHOW)
        _user32.SetForegroundWindow(hwnd)
    except (AttributeError, OSError):
        pass


# ------------------------------------------------------------ 图标
def _make_fallback_icon() -> int:
    """ICO 文件加载失败时的兜底：绘制 32×32 纯色块图标（HICON 或 0）。

    正常路径永远用 app_icon.ico；此兜底只保证托盘「有东西可点」。
    """
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", ctypes.c_int32), ("xHotspot", ctypes.c_uint32),
                    ("yHotspot", ctypes.c_uint32),
                    ("hbmMask", ctypes.c_void_p),
                    ("hbmColor", ctypes.c_void_p)]

    hdc = None
    try:
        hdc = _user32.GetDC(None)
        if not hdc:
            return 0
        size = 32
        brush = _gdi32.CreateSolidBrush(0x003A6EA5)  # COLORREF：品牌蓝（BGR）
        color_bmp = _gdi32.CreateCompatibleBitmap(hdc, size, size)
        mask_bmp = _gdi32.CreateBitmap(size, size, 1, 1, None)
        mem = _gdi32.CreateCompatibleDC(hdc)
        old_bmp = _gdi32.SelectObject(mem, color_bmp)
        rect = RECT(0, 0, size, size)
        _gdi32.FillRect(mem, ctypes.byref(rect), brush)
        _gdi32.SelectObject(mem, old_bmp)
        _gdi32.DeleteDC(mem)
        _gdi32.DeleteObject(brush)
        info = ICONINFO(1, 0, 0, mask_bmp, color_bmp)
        hicon = _user32.CreateIconIndirect(ctypes.byref(info))
        _gdi32.DeleteObject(mask_bmp)
        _gdi32.DeleteObject(color_bmp)
        return hicon or 0
    except Exception:
        return 0
    finally:
        if hdc:
            _user32.ReleaseDC(None, hdc)


def _load_icon(icon_path: Optional[str]) -> int:
    """加载托盘图标：LoadImageW(app_icon.ico) → 兜底纯色图标 → 0。"""
    if icon_path:
        try:
            _user32.LoadImageW.restype = ctypes.c_void_p
            hicon = _user32.LoadImageW(
                None, icon_path, _IMAGE_ICON, 32, 32, _LR_LOADFROMFILE)
            if hicon:
                return hicon
        except (AttributeError, OSError):
            pass
    return _make_fallback_icon()


# ------------------------------------------------------------ 窗口与托盘
class _NotifyIconData(ctypes.Structure):
    """NOTIFYICONDATAW（截取到 szTip 为止，Windows 7+ 布局稳定）。"""

    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint32),
        ("uFlags", ctypes.c_uint32),
        ("uCallbackMessage", ctypes.c_uint32),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
    ]


def _remove_icon() -> None:
    """从通知区域移除图标（NIM_DELETE）。"""
    if not _tray_hwnd:
        return
    nid = _NotifyIconData()
    nid.cbSize = ctypes.sizeof(_NotifyIconData)
    nid.hWnd = _tray_hwnd
    nid.uID = ICON_ID
    try:
        _shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(nid))
    except (AttributeError, OSError):
        pass


def _show_menu() -> None:
    """右键弹出托盘菜单；TrackPopupMenu(TPM_RETURNCMD) 同步取选中项。"""
    try:
        menu = _user32.CreatePopupMenu()
        if not menu:
            return
        _user32.AppendMenuW(menu, _MF_STRING, MENU_SHOW, "显示主窗口")
        _user32.AppendMenuW(menu, _MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, _MF_STRING, MENU_QUIT, "退出")
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        # SetForegroundWindow 保证菜单出现即选中即消失（托盘菜单惯例）
        _user32.SetForegroundWindow(_tray_hwnd)
        cmd = _user32.TrackPopupMenu(
            menu, _TPM_RIGHTBUTTON | _TPM_RETURNCMD,
            pt.x, pt.y, 0, _tray_hwnd, None)
        _user32.DestroyMenu(menu)
        if cmd == MENU_SHOW:
            _activate_main()
        elif cmd == MENU_QUIT:
            callback = _on_quit
            if callback:
                callback()
    except (AttributeError, OSError):
        pass


def _tray_wnd_proc(hwnd, msg, wparam, lparam):
    """托盘隐藏窗口消息处理（运行于托盘线程）。"""
    try:
        if msg == WM_TRAY_CALLBACK:
            code = lparam & 0xFFFF
            if code in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                _activate_main()
            elif code in (_WM_RBUTTONUP, _WM_CONTEXTMENU):
                _show_menu()
            return 0
        if msg == _WM_CLOSE:
            # stop() 从任意线程投递：清理并退出消息循环
            _remove_icon()
            icon = _icon_handle
            if icon:
                _user32.DestroyIcon(icon)
            _user32.PostQuitMessage(0)
            return 0
    except (AttributeError, OSError):
        pass
    # 默认处理：DefWindowProcW 返回 0 时 ctypes 给 None，转 0 保证回调
    # 返回值可被 WNDPROC（LRESULT）正常转换
    try:
        return def_window_proc(hwnd, msg, wparam, lparam)
    except (AttributeError, OSError, OverflowError):
        return 0


def _worker_main(icon_path: Optional[str]) -> None:
    """托盘线程体：建窗、加图标、进消息循环。"""
    global _tray_hwnd, _icon_handle
    try:
        wnd_proc = WNDPROC(_tray_wnd_proc)
        _wnd_proc_refs.append(wnd_proc)  # 防回调对象被 GC
        hwnd = create_message_window(
            "SIXIANG_Tray_Window", "SIXIANG.Tray", wnd_proc)

        icon = _load_icon(icon_path)

        nid = _NotifyIconData()
        nid.cbSize = ctypes.sizeof(_NotifyIconData)
        nid.hWnd = hwnd
        nid.uID = ICON_ID
        nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        nid.uCallbackMessage = WM_TRAY_CALLBACK
        nid.hIcon = icon
        nid.szTip = "四象"
        try:
            ok_add = bool(_shell32.Shell_NotifyIconW(
                _NIM_ADD, ctypes.byref(nid)))
        except (AttributeError, OSError):
            ok_add = False
        if not ok_add:
            # 通知区域不可用（explorer 未就绪等）→ 清理后失败返回
            if icon:
                _user32.DestroyIcon(icon)
            _user32.DestroyWindow(hwnd)
            raise OSError("Shell_NotifyIconW(NIM_ADD) 失败")

        _tray_hwnd = hwnd
        _icon_handle = icon
    except Exception as exc:
        if _ready is not None:
            _ready.set()  # start() 侧看 ready 后检查 _tray_hwnd == 0 判失败
        print(f"[tray] 托盘启动失败：{exc}", file=sys.stderr)
        return

    if _ready is not None:
        _ready.set()

    msg = wintypes.MSG()
    try:
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        if _tray_hwnd:
            _user32.DestroyWindow(_tray_hwnd)
        _tray_hwnd = 0


# ------------------------------------------------------------ 对外 API
def start(app_hwnd_getter: Callable[[], Optional[int]],
          on_quit: Callable[[], None],
          icon_path: Optional[str] = None) -> bool:
    """启动托盘（非 win32 / 已启动 / 启动失败 → False，调用方降级）。"""
    if sys.platform != "win32":
        return False
    global _worker, _app_hwnd_getter, _on_quit, _ready, _tray_hwnd
    if _worker is not None and _worker.is_alive():
        return True
    _tray_hwnd = 0
    _app_hwnd_getter = app_hwnd_getter
    _on_quit = on_quit
    _ready = threading.Event()
    _worker = threading.Thread(
        target=_worker_main, args=(icon_path,),
        daemon=True, name="sixiang-tray")
    _worker.start()
    _ready.wait(_READY_TIMEOUT)
    return _tray_hwnd != 0


def stop() -> None:
    """停止托盘并等待线程退出（幂等、任意线程可调）。"""
    global _worker
    worker = _worker
    if worker is None or not worker.is_alive():
        return
    if _tray_hwnd:
        try:
            _user32.PostMessageW(_tray_hwnd, _WM_CLOSE, 0, 0)
        except (AttributeError, OSError):
            pass
    worker.join(_STOP_JOIN_TIMEOUT)
    _worker = None
