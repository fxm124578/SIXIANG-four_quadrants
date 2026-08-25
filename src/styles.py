"""主题系统：颜色、字体与通用样式工具（纯标准库 tkinter 版）。

支持四套主题（午夜玻璃 / 雾白冰川 / 霓虹网格 / 晨雾纸墨），
通过 ``T`` 代理对象动态读取当前主题配色，运行时切换无需重启。
"""
from __future__ import annotations

import struct
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

# ---------------------------------------------------------------- 主题表
THEMES = {
    # 午夜玻璃：深靛蓝夜空 + 发光象限描边（默认）
    "midnight": {
        "name": "午夜玻璃",
        "desc": "深色玻璃质感，发光象限描边",
        "bg": "#0b0d18", "card": "#141830", "panel": "#1c2138",
        "panel2": "#232a45",
        "row_bg": "#1e2232", "row_hover": "#2b2e3f", "row_active": "#353849",
        "text": "#eef0fb", "title_text": "#ffffff", "muted": "#8f96b3",
        "secondary": "#9aa2b8", "border": "#333a55",
        "accent": "#5b8cff", "accent_light": "#7ba5ff", "accent_dark": "#4f7df9",
        "green": "#3dd68c", "tag_bg": "#3a3170", "tag_fg": "#cfc4ff",
        "check_box": "#141830", "check_border": "#6b7490",
        "check_border_hover": "#b9c0d8",
        "quadrant_card_bg": {0: "#242733", 1: "#24292f", 2: "#192737",
                             3: "#172b29"},
        "quadrant_border": {0: "#48323a", 1: "#473628", 2: "#223755",
                            3: "#1d3934"},
        "btn_hover": "#2b2f47", "btn_press": "#20243a",
        "report_bg": "#123426", "report_fg": "#7fe8b6",
        "report_hover": "#1a4a37", "report_press": "#0e2a1e",
        "grip": "#5b6474",
        "lock_bg": "#b06a1f", "lock_hover": "#c97a26", "lock_press": "#8f5517",
        "ghost_bg": "#141830",
        # 设计还原字段：窗口透明度 / 顶部装饰线 / 勾选框形状 / 渐变 / 光斑 / 网格
        "alpha": 0.90, "topline": "spectrum", "check_round": False,
        "grad_hi": "#1a1f3c", "grad_lo": "#10131f",
        "bg_accent": ["#3b2f8f", "#123f5e"], "bg_grid": False,
    },
    # 雾白冰川：明亮磨砂玻璃 + 莫兰迪柔色
    "frost": {
        "name": "雾白冰川",
        "desc": "明亮磨砂玻璃，柔和莫兰迪色",
        "bg": "#e6ebf3", "card": "#f4f7fb", "panel": "#ffffff",
        "panel2": "#e9eef6",
        "row_bg": "#fbfdff", "row_hover": "#ffffff", "row_active": "#eef3fa",
        "text": "#2c3242", "title_text": "#1f2430", "muted": "#8d94a8",
        "secondary": "#7c8498", "border": "#d6dcea",
        "accent": "#7b9bd2", "accent_light": "#8fb0e0", "accent_dark": "#6a8cc4",
        "green": "#8fc7a6", "tag_bg": "#ece4f6", "tag_fg": "#7a6aa8",
        "check_box": "#ffffff", "check_border": "#b6bccd",
        "check_border_hover": "#8fc7a6",
        "quadrant_card_bg": {0: "#f7e9e7", 1: "#f9f0e3", 2: "#e9eef8",
                             3: "#e9f3ec"},
        "quadrant_border": {0: "#d9a39c", 1: "#e3c193", 2: "#a9bce0",
                            3: "#a9cfb6"},
        "btn_hover": "#ffffff", "btn_press": "#e4e9f1",
        "report_bg": "#dcefe4", "report_fg": "#4e7d63",
        "report_hover": "#cbe7d6", "report_press": "#c3dccd",
        "grip": "#7882a0",
        "lock_bg": "#c9973a", "lock_hover": "#d8a94e", "lock_press": "#a87e2c",
        "ghost_bg": "#f4f7fb",
        "alpha": 0.88, "topline": "glow", "check_round": True,
        "grad_hi": "#f7fafd", "grad_lo": "#e0e7f1",
        "bg_accent": ["#f6cfd0", "#cfe0f2"], "bg_grid": False,
    },
    # 霓虹网格：赛博终端，透视网格 + 霓虹辉光
    "neon": {
        "name": "霓虹网格",
        "desc": "近黑终端风，霓虹描边辉光",
        "bg": "#04060d", "card": "#0a1022", "panel": "#0d1428",
        "panel2": "#111a33",
        "row_bg": "#101a30", "row_hover": "#16203a", "row_active": "#1a2545",
        "text": "#e8f2ff", "title_text": "#ffffff", "muted": "#5f708e",
        "secondary": "#77879f", "border": "#1e2c4a",
        "accent": "#00e5ff", "accent_light": "#33ecff", "accent_dark": "#00b8cc",
        "green": "#3dffa2", "tag_bg": "#062b36", "tag_fg": "#8ff0ff",
        "check_box": "#080c1a", "check_border": "#3f5270",
        "check_border_hover": "#3dffa2",
        "quadrant_card_bg": {0: "#041822", 1: "#180f22", 2: "#181703",
                             3: "#031a10"},
        "quadrant_border": {0: "#0e6b7d", 1: "#7d2a68", 2: "#6e6400",
                            3: "#0f7a44"},
        "btn_hover": "#0a2a38", "btn_press": "#06202c",
        "report_bg": "#063127", "report_fg": "#7dffc2",
        "report_hover": "#0a4235", "report_press": "#04261e",
        "grip": "#3fcee6",
        "lock_bg": "#ff4dd8", "lock_hover": "#ff6ee0", "lock_press": "#c42f9f",
        "ghost_bg": "#0a1022",
        "alpha": 0.90, "topline": "neon", "check_round": False,
        "grad_hi": "#0d1a30", "grad_lo": "#05070f",
        "bg_accent": ["#0a4a66", "#4a1250"], "bg_grid": True,
    },
    # 晨雾纸墨：暖米纸感 + 中国画颜料色
    "paper": {
        "name": "晨雾纸墨",
        "desc": "暖米纸张质感，朱砂印章点缀",
        "bg": "#e8e0cc", "card": "#fbf6e8", "panel": "#f3ecd9",
        "panel2": "#ede4cd",
        "row_bg": "#fdf8ea", "row_hover": "#ffffff", "row_active": "#f5edd8",
        "text": "#3d3a33", "title_text": "#2c2a24", "muted": "#9a927e",
        "secondary": "#8d856f", "border": "#d8cfb4",
        "accent": "#b23a2e", "accent_light": "#c4554a", "accent_dark": "#93301f",
        "green": "#5f8c6b", "tag_bg": "#e8eef4", "tag_fg": "#4d6b8c",
        "check_box": "#fdf8ea", "check_border": "#9a927e",
        "check_border_hover": "#b23a2e",
        "quadrant_card_bg": {0: "#f7ece6", 1: "#f7f0df", 2: "#eaeff4",
                             3: "#eaf2ec"},
        "quadrant_border": {0: "#d9a99c", 1: "#ddc489", 2: "#a9bcd0",
                            3: "#a9c9b2"},
        "btn_hover": "#ffffff", "btn_press": "#f0e8d3",
        "report_bg": "#e4efe7", "report_fg": "#44664e",
        "report_hover": "#d8e9dd", "report_press": "#cde0d4",
        "grip": "#8d856f",
        "lock_bg": "#c9973a", "lock_hover": "#d8a94e", "lock_press": "#a87e2c",
        "ghost_bg": "#fbf6e8",
        "alpha": 0.92, "topline": "thread", "check_round": True,
        "grad_hi": "#fbf6e8", "grad_lo": "#efe7d2",
        "bg_accent": ["#c9973a", "#5f8c6b"], "bg_grid": False,
    },
}

_ICON_COLORS = ("#e5533c", "#e8912d", "#3f7fd9", "#4caf7d")
_current_theme = "midnight"


class _ThemeProxy:
    """按 key 动态读取当前主题颜色：``T.bg``、``T.quadrant_card_bg``。"""

    def __getattr__(self, key: str):
        try:
            return THEMES[_current_theme][key]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(key) from exc


T = _ThemeProxy()


def set_theme(name: str) -> None:
    """切换当前主题；未知主题名回退到默认主题。"""
    global _current_theme
    _current_theme = name if name in THEMES else "midnight"


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
