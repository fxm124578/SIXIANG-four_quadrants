"""主题系统：颜色、字体与通用样式工具（纯标准库 tkinter 版）。

主题配色由 ``themes/`` 目录下的 CSS 文件提供（可插拔、可快速安装），
通过 ``T`` 代理对象动态读取当前主题配色，运行时切换无需重启。
默认主题为「晨雾纸墨」；主题文件丢失时自动回退默认。
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from theme_loader import DEFAULT_THEME, load_tk_themes

# ---------------------------------------------------------------- 主题表
# 从 themes/ 目录动态构建（每个 CSS 文件的 --tk-* 变量）；空时已内置兜底
THEMES = load_tk_themes()

_current_theme = DEFAULT_THEME if DEFAULT_THEME in THEMES else next(iter(THEMES))


class _ThemeProxy:
    """按 key 动态读取当前主题颜色：``T.bg``、``T.quadrant_card_bg``。"""

    def __getattr__(self, key: str):
        try:
            return THEMES[_current_theme][key]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(key) from exc


T = _ThemeProxy()


def set_theme(name: str) -> None:
    """切换当前主题；未知主题名回退到默认主题（晨雾纸墨）。"""
    global _current_theme
    _current_theme = name if name in THEMES else DEFAULT_THEME


def theme_name() -> str:
    return _current_theme


def theme_names() -> list:
    return list(THEMES)


FONT_FAMILY = "Microsoft YaHei UI"


def blend(color1: str, color2: str, ratio: float) -> str:
    """按 ratio（0~1）把 color2 混入 color1，返回十六进制颜色。"""
    ratio = max(0.0, min(1.0, ratio))
    c1 = [int(color1[i:i + 2], 16) for i in (1, 3, 5)]
    c2 = [int(color2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(
        f"{max(0, min(255, round(c1[k] + (c2[k] - c1[k]) * ratio))):02x}"
        for k in range(3))


def font(size: int = 12, bold: bool = False) -> tuple:
    """返回 tkinter 字体元组；字体族不存在时 Tk 会自动替换。"""
    return (FONT_FAMILY, size, "bold") if bold else (FONT_FAMILY, size)


# ---------------------------------------------------------------- ttk 深色主题
def apply_dark_ttk_style(root: tk.Misc) -> ttk.Style:
    """为 ttk 组件（树形表格 / 滚动条）应用当前主题配色。"""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Dark.Treeview",
        background=T.panel, fieldbackground=T.panel, foreground=T.text,
        borderwidth=0, relief="flat", rowheight=26, font=font(12),
    )
    style.configure(
        "Dark.Treeview.Heading",
        background=T.panel2, foreground=T.secondary, relief="flat",
        borderwidth=0, font=font(12, bold=True), padding=(6, 7),
    )
    style.map("Dark.Treeview.Heading", background=[("active", T.panel2)])
    style.map(
        "Dark.Treeview",
        background=[("selected", T.accent)],
        foreground=[("selected", "#ffffff")],
    )
    for name in ("Dark.Vertical.TScrollbar", "Dark.Horizontal.TScrollbar"):
        style.configure(
            name,
            background=T.panel2, troughcolor=T.panel, bordercolor=T.panel,
            arrowcolor=T.muted, relief="flat",
        )
        style.map(
            name,
            background=[("active", T.secondary), ("pressed", T.secondary)],
        )
    return style


# ---------------------------------------------------------------- 应用图标（静态文件）
_ICON_PATH = str(Path(__file__).resolve().parent / "app_icon.ico")


def ensure_app_icon() -> str | None:
    """返回应用 ICO 路径；文件不存在时返回 None。"""
    return _ICON_PATH if Path(_ICON_PATH).is_file() else None
