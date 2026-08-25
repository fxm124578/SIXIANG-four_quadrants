"""任务行组件：自绘勾选框 + 短标题 + 右侧标签胶囊。

点击行内区域查看任务详情；按住并拖拽超过阈值后进入跨象限拖拽模式
（拖拽流程由主窗口统一处理）。颜色随当前主题动态读取。
"""
from __future__ import annotations

import tkinter as tk

from models import Task
from styles import T, font

# 鼠标移动超过该阈值（像素）后判定为拖拽，否则视为点击查看详情
DRAG_THRESHOLD = 6


class CheckSquare(tk.Canvas):
    """18x18 自绘复选框：勾选后变绿并显示对勾，同时触发完成回调。"""

    def __init__(self, parent, on_check):
        super().__init__(
            parent, width=18, height=18, bg=T.row_bg,
            highlightthickness=0, bd=0, cursor="hand2", takefocus=0,
        )
        self._on_check = on_check
        self._done = False
        self._hover = False
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        round_box = bool(getattr(T, "check_round", False))
        if self._done:
            if round_box:
                self.create_oval(0, 0, 18, 18, fill=T.green, outline=T.green)
            else:
                self.create_rectangle(0, 0, 18, 18, fill=T.green,
                                      outline=T.green)
            self.create_line(4, 9, 8, 14, fill="#ffffff", width=2,
                             capstyle="round")
            self.create_line(8, 14, 14, 4, fill="#ffffff", width=2,
                             capstyle="round")
        else:
            outline = T.check_border_hover if self._hover else T.check_border
            if round_box:
                self.create_oval(0, 0, 18, 18, fill=T.check_box,
                                 outline=outline)
            else:
                self.create_rectangle(0, 0, 18, 18, fill=T.check_box,
                                      outline=outline)

    def _on_enter(self, _event) -> None:
        if not self._done:
            self._hover = True
            self._draw()

    def _on_leave(self, _event) -> None:
        self._hover = False
        self._draw()

    def _on_click(self, _event):
        if self._done:
            return "break"
        self._done = True
        self._draw()
        self._on_check()
        return "break"


class TaskRow(tk.Frame):
    """单个任务行：勾选框 + 标题 + 标签胶囊。"""

    def __init__(self, parent, task: Task, app):
        super().__init__(
            parent, bg=T.row_bg, bd=0, highlightthickness=0,
            cursor="hand2", takefocus=0,
        )
        self.task = task
        self.app = app
        self.quadrant = task.quadrant
        self._press_xy = None
        self._dragging = False

        self.check = CheckSquare(self, on_check=self._complete)
        self.check.pack(side="left", padx=(7, 0), pady=7)

        self.title = tk.Label(
            self, text=task.title, bg=T.row_bg, fg=T.text, font=font(12),
            anchor="w", justify="left", takefocus=0, cursor="hand2",
        )
        self.title.pack(side="left", fill="x", expand=True, padx=(8, 4),
                        pady=7)

        self.tag_frame = None
        self.tag_labels = []
        tags = task.tags
        if tags:
            self.tag_frame = tk.Frame(self, bg=T.row_bg)
            self.tag_frame.pack(side="right", padx=(4, 8), pady=7)
            shown = tags[:2]
            extra = len(tags) - 2
            for tag in shown:
                label = tk.Label(
                    self.tag_frame, text=tag, bg=T.tag_bg, fg=T.tag_fg,
                    font=font(10), padx=8, pady=2, takefocus=0,
                    cursor="hand2",
                )
                label.pack(side="left", padx=(4, 0))
                self.tag_labels.append(label)
            if extra > 0:
                label = tk.Label(
                    self.tag_frame, text=f"+{extra}", bg=T.tag_bg,
                    fg=T.tag_fg, font=font(10), padx=8, pady=2, takefocus=0,
                    cursor="hand2",
                )
                label.pack(side="left", padx=(4, 0))
                self.tag_labels.append(label)

        for widget in (self, self.title, self.tag_frame, *self.tag_labels):
            if widget is None:
                continue
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_motion)
            widget.bind("<ButtonRelease-1>", self._on_release)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

    # ---------------------------------------------------------------- 事件
    def _complete(self) -> None:
        self.app.complete_task(self.task.id)

    def _on_press(self, event) -> None:
        self._press_xy = (event.x_root, event.y_root)

    def _on_motion(self, event) -> None:
        if self._dragging:
            self.app.drag_move_task(event.x_root, event.y_root)
            return
        if self._press_xy is None:
            return
        dx = event.x_root - self._press_xy[0]
        dy = event.y_root - self._press_xy[1]
        if dx * dx + dy * dy >= DRAG_THRESHOLD * DRAG_THRESHOLD:
            self._dragging = True
            self.app.begin_task_drag(self, event.x_root, event.y_root)

    def _on_release(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self._press_xy = None
            self.app.end_task_drag(event.x_root, event.y_root)
        else:
            self._press_xy = None
            self.app.show_task_detail(self.task.id)

    def _on_enter(self, _event) -> None:
        if not self._dragging:
            self._apply_bg(T.row_hover)

    def _on_leave(self, _event) -> None:
        if not self._dragging:
            self._apply_bg(T.row_bg)

    def set_dragging(self, on: bool) -> None:
        """拖拽中高亮 / 恢复源行样式。"""
        self._apply_bg(T.row_active if on else T.row_bg)
        if self.title.winfo_exists():
            self.title.configure(fg=T.muted if on else T.text)

    def _apply_bg(self, color: str) -> None:
        try:
            if self.winfo_exists():
                self.configure(bg=color)
            if self.title.winfo_exists():
                self.title.configure(bg=color)
            if self.tag_frame is not None and self.tag_frame.winfo_exists():
                self.tag_frame.configure(bg=color)
        except tk.TclError:
            pass
