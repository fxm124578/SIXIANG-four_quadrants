"""全局唤醒快捷键（RegisterHotKey）。

- 配置存 settings（key: hotkey，格式如 Ctrl+Alt+S），由接入方把字符串传入；
  本模块负责把 spec 解析为（MOD_* 修饰位, 虚拟键码）并注册到独立隐藏消息
  窗口线程（不额外占用可见窗口，也不与托盘共窗——两模块生命周期相互独立，
  避免耦合）。
- register() 失败（组合被其他程序占用、spec 非法）→ 返回 (False, 中文错误
  描述)，不上报崩溃，由接入方决定是否提示。
- 热键触发 → 隐藏窗口 WndProc 收 WM_HOTKEY → 执行回调（运行于热键线程；
  回调内容为唤起主窗口等 user32 操作，跨线程安全）。
- stop() 幂等、可跨线程：向热键窗口投递 WM_CLOSE → 线程内 UnregisterHotKey
  + DestroyWindow + 退出消息循环 → join 至多 2 秒。

非 win32（macOS 开发机）：模块可正常 import；parse_hotkey / format_hotkey
纯逻辑可用；register() 返回 (False, "仅支持 Windows")；stop() 无操作。
"""
from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional, Tuple

# 热键默认值与 id（win32 常量，定义与平台无关，便于单测）
DEFAULT_HOTKEY = "Ctrl+Alt+S"
HOTKEY_ID = 0xB007

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

WM_HOTKEY = 0x0312
WM_CLOSE = 0x0010
_ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_READY_TIMEOUT = 3.0
_STOP_JOIN_TIMEOUT = 2.0

# 修饰键别名表（小写 → MOD 位）
_MODIFIER_ALIASES = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}
# 规范化输出顺序（format_hotkey 用）
_MODIFIER_ORDER = (
    ("Ctrl", MOD_CONTROL),
    ("Alt", MOD_ALT),
    ("Shift", MOD_SHIFT),
    ("Win", MOD_WIN),
)


# ------------------------------------------------------------ spec 纯逻辑
def parse_hotkey(spec: str) -> dict:
    """解析热键 spec，如 'Ctrl+Alt+S'。

    返回 {"mods": int, "vk": int}：
    - mods：MOD_CONTROL/MOD_ALT/MOD_SHIFT/MOD_WIN 按位或；
    - vk：Windows 虚拟键码（字母取大写 ASCII，数字取 ASCII，F1-F12 取 0x70+）。
    修饰符顺序不敏感；修饰键重复、主键缺失/重复/不支持、空串 → ValueError。
    本版本只支持 字母 / 数字 / F1-F12 作主键（其余按键留给设置 UI 后续扩展）。
    """
    tokens = [token.strip() for token in str(spec).split("+")]
    tokens = [token for token in tokens if token]
    if not tokens:
        raise ValueError("热键不能为空（格式如 Ctrl+Alt+S）")
    mods = 0
    vk: Optional[int] = None
    for token in tokens:
        alias = _MODIFIER_ALIASES.get(token.lower())
        if alias is not None:
            if mods & alias:
                raise ValueError(f"修饰键重复：{token}")
            mods |= alias
            continue
        if vk is not None:
            raise ValueError(f"主键只能有一个：{token}")
        vk = _parse_main_key(token)
    if vk is None:
        raise ValueError("热键缺少主键（如 Ctrl+Alt+S 中的 S）")
    if not mods:
        raise ValueError("热键至少需要一个修饰键（Ctrl/Alt/Shift/Win）")
    return {"mods": mods, "vk": vk}


def _parse_main_key(token: str) -> int:
    """单键 token → 虚拟键码；不支持时报 ValueError。"""
    upper = token.upper()
    if len(token) == 1 and token.isalpha():
        return ord(upper)
    if len(token) == 1 and token.isdigit():
        return ord(token)
    if upper.startswith("F") and upper[1:].isdigit():
        number = int(upper[1:])
        if 1 <= number <= 12:
            return 0x70 + number - 1  # VK_F1 = 0x70
    raise ValueError(f"不支持的主键：{token}（支持字母/数字/F1-F12）")


def format_hotkey(parsed: dict) -> str:
    """把 parse_hotkey 结果规范化为显示串，如 'Ctrl+Alt+S'。"""
    mods = int(parsed["mods"])
    vk = int(parsed["vk"])
    parts = [name for name, bit in _MODIFIER_ORDER if mods & bit]
    if 0x70 <= vk <= 0x7B:
        key = f"F{vk - 0x70 + 1}"
    elif ord("A") <= vk <= ord("Z") or ord("0") <= vk <= ord("9"):
        key = chr(vk)
    else:
        key = f"0x{vk:X}"
    return "+".join(parts + [key])


# ------------------------------------------------------------ 热键线程状态
_worker: Optional[threading.Thread] = None
_hotkey_hwnd = 0
_hotkey_active = False        # 当前已注册成功的 spec
_callback: Optional[Callable[[], None]] = None
_ready: Optional[threading.Event] = None
_wnd_proc_refs: list = []  # 持有历次 ctypes 回调引用防 GC（窗口类可能重注册）

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.DefWindowProcW.restype = ctypes.c_void_p
    _kernel32.GetModuleHandleW.restype = ctypes.c_void_p


def _hotkey_wnd_proc(hwnd, msg, wparam, lparam):
    """热键隐藏窗口消息处理（运行于热键线程）。"""
    try:
        if msg == WM_HOTKEY and wparam == HOTKEY_ID:
            callback = _callback
            if callback:
                try:
                    callback()
                except Exception:
                    pass
            return 0
        if msg == WM_CLOSE:
            # stop() 从任意线程投递：注销热键并退出消息循环
            if _hotkey_active:
                _user32.UnregisterHotKey(hwnd, HOTKEY_ID)
            _user32.PostQuitMessage(0)
            return 0
    except (AttributeError, OSError):
        pass
    # 默认处理：DefWindowProcW 返回 0 时 ctypes 给 None，转 0 保证回调
    # 返回值可被 WNDPROC（LRESULT）正常转换
    try:
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam) or 0
    except (AttributeError, OSError):
        return 0


def _worker_main(spec: str) -> None:
    """热键线程体：建隐藏窗、RegisterHotKey、进消息循环。

    RegisterHotKey 失败（被占用等）→ 设置失败标志并退出线程。
    """
    global _hotkey_hwnd, _hotkey_active
    try:
        parsed = parse_hotkey(spec)
    except ValueError as exc:
        print(f"[hotkey] 配置无效：{exc}", file=sys.stderr)
        if _ready is not None:
            _ready.set()
        return

    try:
        wnd_proc = wintypes.WNDPROC(_hotkey_wnd_proc)
        _wnd_proc_refs.append(wnd_proc)  # 防回调对象被 GC

        class_name = "SIXIANG_Hotkey_Window"
        wc = wintypes.WNDCLASSW()
        wc.lpfnWndProc = wnd_proc
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        wc.lpszClassName = class_name
        if not _user32.RegisterClassW(ctypes.byref(wc)):
            err = _kernel32.GetLastError()
            if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS → 已注册，继续
                raise OSError(f"注册热键窗口类失败（{err}）")

        _user32.CreateWindowExW.restype = ctypes.c_void_p
        hwnd = _user32.CreateWindowExW(
            0, class_name, "SIXIANG.Hotkey", 0, 0, 0, 0, 0,
            None, None, wc.hInstance, None)
        if not hwnd:
            raise OSError("创建热键消息窗口失败")

        if not _user32.RegisterHotKey(hwnd, HOTKEY_ID,
                                      parsed["mods"], parsed["vk"]):
            err = _kernel32.GetLastError()
            detail = ("组合已被其他程序占用" if err == _ERROR_HOTKEY_ALREADY_REGISTERED
                      else f"注册失败（错误码 {err}）")
            _user32.DestroyWindow(hwnd)
            raise OSError(f"全局热键 {format_hotkey(parsed)} {detail}")

        _hotkey_hwnd = hwnd
        _hotkey_active = True
    except Exception as exc:
        print(f"[hotkey] {exc}", file=sys.stderr)
        if _ready is not None:
            _ready.set()
        return

    if _ready is not None:
        _ready.set()

    msg = wintypes.MSG()
    try:
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        if _hotkey_hwnd:
            _user32.DestroyWindow(_hotkey_hwnd)
        _hotkey_hwnd = 0
        _hotkey_active = False


# ------------------------------------------------------------ 对外 API
def register(spec: str, callback: Callable[[], None]) -> Tuple[bool, str]:
    """注册全局热键（非 win32 → (False, '仅支持 Windows')）。

    重复调用会先注销旧热键（线程退出后重建），以新 spec 生效。
    返回 (True, "") 或 (False, 中文错误信息)；失败不抛异常。
    """
    if sys.platform != "win32":
        return False, "仅支持 Windows"
    try:
        parse_hotkey(spec)  # 提前校验，非法 spec 不启线程
    except ValueError as exc:
        return False, str(exc)

    global _worker, _callback, _ready, _hotkey_hwnd, _hotkey_active
    if _worker is not None and _worker.is_alive():
        stop()
    _hotkey_hwnd = 0
    _hotkey_active = False
    _callback = callback
    _ready = threading.Event()
    _worker = threading.Thread(
        target=_worker_main, args=(spec,),
        daemon=True, name="sixiang-hotkey")
    _worker.start()
    _ready.wait(_READY_TIMEOUT)
    if _hotkey_active:
        return True, ""
    return False, f"全局热键 {format_hotkey(parse_hotkey(spec))} 注册失败（可能被占用），详见 stderr"


def stop() -> None:
    """注销热键并退出热键线程（幂等、任意线程可调）。"""
    global _worker
    worker = _worker
    if worker is None or not worker.is_alive():
        return
    if _hotkey_hwnd:
        try:
            _user32.PostMessageW(_hotkey_hwnd, WM_CLOSE, 0, 0)
        except (AttributeError, OSError):
            pass
    worker.join(_STOP_JOIN_TIMEOUT)
    _worker = None
