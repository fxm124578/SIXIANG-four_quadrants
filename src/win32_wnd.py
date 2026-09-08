"""Win32 隐藏消息窗口。

Python 3.13+ 的 ctypes.wintypes 不再提供 WNDPROC / WNDCLASSW；
且 CreateWindowExW 默认把 hInstance 当成 32 位 int，64 位下会 OverflowError。
托盘与热键都走这里建窗，缺了会在后台线程静默失败（pythonw 无 stderr）。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


_ERROR_CLASS_ALREADY_EXISTS = 1410

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    _kernel32.GetLastError.argtypes = []
    _kernel32.GetLastError.restype = wintypes.DWORD
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    _user32.RegisterClassW.restype = wintypes.ATOM
    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    _user32.CreateWindowExW.restype = wintypes.HWND
    _user32.DefWindowProcW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.DefWindowProcW.restype = ctypes.c_ssize_t


def def_window_proc(hwnd, msg, wparam, lparam) -> int:
    """DefWindowProcW；64 位 LPARAM 必须按 LPARAM 传递。"""
    if sys.platform != "win32":
        return 0
    return int(_user32.DefWindowProcW(hwnd, msg, wparam, lparam) or 0)


def create_message_window(class_name: str, title: str, wnd_proc) -> int:
    """注册窗口类并创建 0 尺寸隐藏窗，返回 hwnd。非 win32 抛 OSError。"""
    if sys.platform != "win32":
        raise OSError("仅支持 Windows")
    wc = WNDCLASSW()
    wc.lpfnWndProc = wnd_proc
    wc.hInstance = _kernel32.GetModuleHandleW(None)
    wc.lpszClassName = class_name
    if not _user32.RegisterClassW(ctypes.byref(wc)):
        err = _kernel32.GetLastError()
        if err != _ERROR_CLASS_ALREADY_EXISTS:
            raise OSError(f"注册窗口类失败（{err}）")
    hwnd = _user32.CreateWindowExW(
        0, class_name, title, 0, 0, 0, 0, 0,
        None, None, wc.hInstance, None)
    if not hwnd:
        raise OSError("创建消息窗口失败")
    return int(hwnd)
