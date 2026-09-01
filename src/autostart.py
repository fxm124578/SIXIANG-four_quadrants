r"""开机自启动：通过注册表 HKCU\Software\Microsoft\Windows\CurrentVersion\Run 实现。

- 源码运行：写入当前解释器（pythonw.exe / python.exe）+ main.py 绝对路径
- PyInstaller onefile 打包：写入 exe 绝对路径（sys.executable，不依赖 __file__）

仅 Windows 生效；非 Windows 平台所有操作返回 False / 关闭状态。
"""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "SIXIANG"


def _run_command() -> str:
    """返回写入注册表的启动命令。"""
    exe = sys.executable
    if getattr(sys, "frozen", False):
        return f'"{exe}"'
    # 源码运行：使用与当前进程相同的解释器启动 main.py
    main_py = Path(__file__).resolve().parent / "main.py"
    return f'"{exe}" "{main_py}"'


def is_enabled() -> bool:
    """当前是否已注册开机自启动。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    """设置 / 取消开机自启动；成功返回 True。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                                  _run_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass  # 本就未注册，视为成功
        return True
    except OSError:
        return False
