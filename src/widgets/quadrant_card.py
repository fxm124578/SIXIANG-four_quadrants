"""四象限卡片：标题 + 计数 + 可滚动任务列表（带象限色渐变背景）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from models import QUADRANT_BY_KEY
from styles import T, blend, font
from widgets.task_item import TaskRow


class QuadrantCard(tk.Frame):
    """一个象限：标题 + 计数 + 可滚动任务列表。

    ``quadrant_key`` 属性供主窗口的拖拽命中测试向上查找使用。
    背景为垂直渐变，轻染象限主色，呼应 HTML 方案的玻璃质感卡片。
    """

    def __init__(self, parent, quadrant: int, app):
        info = QUADRANT_BY_KEY[quadrant]
        self.quadrant_key = int(quadrant)
        self.app = app
        bg = T.quadrant_card_bg[self.quadrant_key]
        border = T.quadrant_border[self.quadrant_key]

        super().__init__(
            parent, bg=bg, bd=0, highlightthickness=1,
            highlightbackground=border, highlightcolor=border,
        )

        # 渐变背景层（铺满卡片，内容层在其上方）
        self.bg_canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0,
                                   takefocus=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.bg_canvas.bind("<Configure>", self._draw_gradient)

        header = tk.Frame(self, bg=bg)
        header.pack(fill="x", padx=8, pady=(8, 2))

        dot = tk.Label(header, text="●", fg=info["color"], bg=bg, font=font(9))
        dot.pack(side="left", padx=(2, 6))

        title = tk.Label(header, text=info["name"], bg=bg, fg=T.title_text,
                         font=font(11, bold=True))
        title.pack(side="left")

        self.count_label = tk.Label(header, text="0", bg=bg, fg=T.secondary,
                                    font=font(10))
        self.count_label.pack(side="left", padx=(6, 0))

        add_btn = tk.Label(header, text="＋", bg=bg, fg="#aeb6c8",
                           font=font(14, bold=True), cursor="hand2", padx=4)
        add_btn.pack(side="right")
        add_btn.bind("<Enter>", lambda e: add_btn.configure(fg=T.title_text))
        add_btn.bind("<Leave>", lambda e: add_btn.configure(fg="#aeb6c8"))
        add_btn.bind(
            "<Button-1>",
            lambda e: self.app.open_add_task_dialog(self.quadrant_key),
        )

        list_area = tk.Frame(self, bg=bg)
        list_area.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        self.canvas = tk.Canvas(
            list_area, bg=bg, highlightthickness=0, bd=0, takefocus=0,
        )
        # 标记：供主窗口全局滚轮路由识别
        self.canvas._quadrant_scroll = True
        self.scrollbar = ttk.Scrollbar(
            list_area, orient="vertical", command=self.canvas.yview,
            style="Dark.Vertical.TScrollbar",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner = tk.Frame(self.canvas, bg=bg)
        self._inner_item = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw",
        )
        self.inner.bind(
            "<Configure>",
            lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._inner_item,
                                                width=e.width),
        )

    def _draw_gradient(self, _event=None) -> None:
        """垂直渐变背景：主题渐变底色 + 轻染象限主色。"""
        try:
            info = QUADRANT_BY_KEY[self.quadrant_key]
            self.bg_canvas.delete("all")
            width = self.bg_canvas.winfo_width()
            height = self.bg_canvas.winfo_height()
            if width <= 0 or height <= 0:
                return
            hi = blend(info["color"], T.grad_hi, 0.82)
            lo = blend(info["color"], T.grad_lo, 0.72)
            rows = 30
            for index in range(rows):
                y0 = height * index // rows
                y1 = height * (index + 1) // rows + 1
                self.bg_canvas.create_rectangle(
                    0, y0, width, y1,
                    fill=blend(hi, lo, index / (rows - 1)), outline="")
        except tk.TclError:
            pass

    def set_tasks(self, tasks) -> None:
        """重建任务行列表；尽量保持刷新前的滚动位置。"""
        yview = self.canvas.yview()
        frac = yview[0] if yview else 0.0
        for child in self.inner.winfo_children():
            child.destroy()
        for task in tasks:
            row = TaskRow(self.inner, task, self.app)
            row.pack(fill="x", pady=(0, 4), padx=1)
        self.count_label.configure(text=str(len(tasks)))
        self.inner.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(frac)

    def set_drag_hover(self, on: bool) -> None:
        """拖拽悬停时用象限主色高亮边框。"""
        info = QUADRANT_BY_KEY[self.quadrant_key]
        color = info["color"] if on else T.quadrant_border[self.quadrant_key]
        self.configure(
            highlightbackground=color, highlightcolor=color,
            highlightthickness=2 if on else 1,
        )
