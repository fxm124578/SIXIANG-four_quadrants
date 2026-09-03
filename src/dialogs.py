"""对话框：新建任务、任务详情、日报中心（含自绘日历）、日期范围导出、设置。

全部使用 tkinter 标准库实现，无第三方依赖；颜色随当前主题动态读取。
"""
from __future__ import annotations

import re
import threading
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import autostart
from db import Database
from models import QUADRANTS, Task, quadrant_name, tags_to_raw
from report import (
    CSV_HEADERS,
    build_report_stats,
    export_report,
    export_report_range,
)
from styles import THEMES, T, ensure_app_icon, font, theme_names
import updater

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]

# 窗口模式：固定桌面 / 置顶最前 / 普通窗口
WINDOW_MODES = {
    "desktop": {"name": "固定桌面", "desc": "无边框、不置顶，不影响其他应用显示"},
    "topmost": {"name": "置顶最前", "desc": "无边框，悬浮在所有应用之上"},
    "normal": {"name": "普通窗口", "desc": "带系统标题栏，支持最小化 / 最大化 / 关闭"},
}


# --------------------------------------------------------------------------
# 通用小部件
# --------------------------------------------------------------------------
def safe_messagebox(parent, kind: str, title: str, message: str) -> None:
    """先临时取消主窗口置顶，避免系统消息框被悬浮窗挡住。"""
    root = parent.winfo_toplevel()
    was_topmost = False
    try:
        was_topmost = bool(root.attributes("-topmost"))
        if was_topmost:
            root.attributes("-topmost", False)
    except tk.TclError:
        pass
    try:
        func = {
            "info": messagebox.showinfo,
            "warning": messagebox.showwarning,
            "error": messagebox.showerror,
            "askyesno": messagebox.askyesno,
        }[kind]
        func(title, message, parent=parent)
    finally:
        try:
            if was_topmost:
                root.attributes("-topmost", True)
        except tk.TclError:
            pass


def flat_button(parent, text: str, command=None, *, bg=None, fg=None,
                hover_bg=None, press_bg=None, font_=None,
                padx=12, pady=5) -> tk.Label:
    """自绘扁平按钮（Label 实现），带悬停 / 按下反馈，颜色取自当前主题。"""
    if bg is None:
        bg = T.panel
    if fg is None:
        fg = T.text
    if hover_bg is None:
        hover_bg = T.btn_hover
    if press_bg is None:
        press_bg = T.btn_press
    btn = tk.Label(
        parent, text=text, bg=bg, fg=fg, font=font_ or font(12),
        padx=padx, pady=pady, cursor="hand2", takefocus=0,
    )
    btn._base = bg
    btn._hover = hover_bg
    btn._press = press_bg

    def on_enter(_event):
        btn.configure(bg=btn._hover)

    def on_leave(_event):
        btn.configure(bg=btn._base)

    def on_press(_event):
        btn.configure(bg=btn._press)

    def on_release(event):
        inside = btn.winfo_containing(event.x_root, event.y_root) is btn
        btn.configure(bg=btn._hover if inside else btn._base)
        if inside and command is not None:
            command()

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    btn.bind("<ButtonPress-1>", on_press)
    btn.bind("<ButtonRelease-1>", on_release)
    return btn


# --------------------------------------------------------------------------
# 模态对话框基类
# --------------------------------------------------------------------------
class ModalDialog(tk.Toplevel):
    """深色主题、居中、置顶的模态对话框基类。"""

    def __init__(self, parent, title: str):
        super().__init__(parent)
        self.result = None
        self.title(title)
        self.configure(bg=T.bg)
        self.resizable(False, False)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda e: self._close())
        try:
            self.iconbitmap(ensure_app_icon())
        except tk.TclError:
            pass
        # 先隐藏，run() 定位完成后再显示，避免在左上角闪烁
        self.withdraw()

    def run(self):
        """进入模态循环，返回对话框结果（默认 None 表示取消）。"""
        self.update_idletasks()
        parent = self.master
        width = self.winfo_reqwidth()
        height = self.winfo_reqheight()
        x = max(0, parent.winfo_rootx()
                + (parent.winfo_width() - width) // 2)
        y = max(0, parent.winfo_rooty()
                + (parent.winfo_height() - height) // 2)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.wait_window()
        return self.result

    def _close(self) -> None:
        self.result = None
        self.destroy()


# --------------------------------------------------------------------------
# 新建任务
# --------------------------------------------------------------------------
class AddTaskDialog(ModalDialog):
    def __init__(self, parent, default_quadrant: int = 0):
        super().__init__(parent, "新建任务")
        self._vcmds = []

        body = tk.Frame(self, bg=T.bg)
        body.pack(fill="both", expand=True, padx=18, pady=18)

        tk.Label(body, text="标题 *", bg=T.bg, fg=T.text,
                 font=font(12)).grid(row=0, column=0, sticky="e",
                                     padx=(0, 10), pady=(0, 8))
        self.title_var = tk.StringVar()
        self.title_entry = tk.Entry(
            body, textvariable=self.title_var, bg=T.panel, fg=T.text,
            insertbackground=T.text, relief="flat", font=font(12), width=30,
        )
        self._limit(self.title_entry, 80)
        self.title_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8),
                              ipady=4)
        self.title_entry.bind("<Return>", lambda e: self._submit())

        tk.Label(body, text="描述", bg=T.bg, fg=T.text,
                 font=font(12)).grid(row=1, column=0, sticky="ne",
                                     padx=(0, 10), pady=(0, 8))
        self.desc_text = tk.Text(
            body, height=4, width=30, bg=T.panel, fg=T.text,
            insertbackground=T.text, relief="flat", font=font(12), wrap="word",
            undo=False,
        )
        self.desc_text.grid(row=1, column=1, sticky="ew", pady=(0, 8))

        tk.Label(body, text="标签", bg=T.bg, fg=T.text,
                 font=font(12)).grid(row=2, column=0, sticky="e",
                                     padx=(0, 10), pady=(0, 4))
        self.tag_var = tk.StringVar()
        self.tag_entry = tk.Entry(
            body, textvariable=self.tag_var, bg=T.panel, fg=T.text,
            insertbackground=T.text, relief="flat", font=font(12), width=30,
        )
        self._limit(self.tag_entry, 60)
        self.tag_entry.grid(row=2, column=1, sticky="ew", pady=(0, 4), ipady=4)
        self.tag_entry.bind("<Return>", lambda e: self._submit())
        tk.Label(body, text="支持多个标签，用逗号或空格分隔，例如：工作 个人",
                 bg=T.bg, fg=T.muted, font=font(10)).grid(
            row=3, column=1, sticky="w", pady=(0, 8))

        tk.Label(body, text="所属象限", bg=T.bg, fg=T.text,
                 font=font(12)).grid(row=4, column=0, sticky="ne",
                                     padx=(0, 10), pady=(4, 0))
        self.quad_var = tk.IntVar(
            value=max(0, min(int(default_quadrant), len(QUADRANTS) - 1)))
        quad_box = tk.Frame(body, bg=T.bg)
        quad_box.grid(row=4, column=1, sticky="w", pady=(4, 0))
        for quadrant in range(4):
            info = QUADRANTS[quadrant]
            rb = tk.Radiobutton(
                quad_box, text=info["name"], variable=self.quad_var,
                value=quadrant, bg=T.bg, fg=T.text, selectcolor=T.panel,
                activebackground=T.bg, activeforeground=T.text, font=font(11),
                anchor="w", highlightthickness=0, bd=0,
            )
            rb.grid(row=quadrant // 2, column=quadrant % 2, sticky="w",
                    padx=(0, 14), pady=2)

        btn_row = tk.Frame(self, bg=T.bg)
        btn_row.pack(fill="x", padx=18, pady=(0, 16))
        flat_button(btn_row, "取消", command=self._close).pack(side="right")
        flat_button(btn_row, "添加", bg=T.accent, fg="#ffffff",
                    hover_bg=T.accent_light, press_bg=T.accent_dark,
                    command=self._submit).pack(side="right", padx=(0, 8))
        # 模态显示后聚焦标题输入框
        self.after(200, self.title_entry.focus_set)

    def _limit(self, entry: tk.Entry, max_len: int) -> None:
        vcmd = (self.register(self._limit_len), "%P", max_len)
        self._vcmds.append(vcmd)
        entry.configure(validate="key", validatecommand=vcmd)

    @staticmethod
    def _limit_len(text: str, max_len) -> bool:
        # Tk 的 validatecommand 会把所有替换参数传成字符串
        try:
            return len(text) <= int(max_len)
        except (TypeError, ValueError):
            return False

    def _submit(self) -> None:
        if not self.title_var.get().strip():
            safe_messagebox(self, "warning", "提示", "任务标题不能为空。")
            self.title_entry.focus_set()
            return
        # 多个标签用逗号 / 顿号 / 分号 / 空白分隔
        raw_tags = re.split(r"[,，;；、\s]+", self.tag_var.get())
        self.result = {
            "title": self.title_var.get().strip(),
            "description": self.desc_text.get("1.0", "end").strip(),
            "tag": tags_to_raw(raw_tags),
            "quadrant": int(self.quad_var.get()),
        }
        self.destroy()


# --------------------------------------------------------------------------
# 任务详情
# --------------------------------------------------------------------------
class TaskDetailDialog(ModalDialog):
    def __init__(self, parent, task: Task):
        super().__init__(parent, "任务详情")

        body = tk.Frame(self, bg=T.bg)
        body.pack(fill="both", expand=True, padx=20, pady=(20, 10))

        tk.Label(body, text=task.title, bg=T.bg, fg=T.title_text,
                 font=font(16, bold=True), anchor="w", justify="left",
                 wraplength=440).pack(fill="x")

        meta = tk.Frame(body, bg=T.bg)
        meta.pack(fill="x", pady=(8, 12))
        tk.Label(meta, text="●", fg=task.quadrant_color, bg=T.bg,
                 font=font(9)).pack(side="left", padx=(0, 5))
        tk.Label(meta, text=task.quadrant_label, bg=T.bg, fg=T.muted,
                 font=font(11)).pack(side="left")
        for tag in task.tags:
            tk.Label(meta, text=tag, bg=T.tag_bg, fg=T.tag_fg,
                     font=font(10), padx=8, pady=1).pack(
                side="left", padx=(8, 0))

        desc_box = tk.Frame(body, bg=T.panel, bd=0)
        desc_box.pack(fill="x")
        tk.Label(desc_box, text="任务描述", bg=T.panel, fg=T.muted,
                 font=font(11)).pack(anchor="w", padx=12, pady=(10, 2))
        # Message 组件支持 \n 换行（Label 不渲染换行符）
        tk.Message(desc_box, text=task.description or "（无描述）", bg=T.panel,
                   fg=T.text, font=font(12), anchor="w", justify="left",
                   width=36).pack(fill="x", padx=12, pady=(0, 12))

        meta2 = tk.Frame(body, bg=T.bg)
        meta2.pack(fill="x", pady=(10, 0))
        tk.Label(meta2, text=f"创建时间：{task.created_at}", bg=T.bg,
                 fg=T.muted, font=font(11)).pack(anchor="w")
        if task.is_completed:
            tk.Label(meta2, text=f"完成归档：{task.completed_at}", bg=T.bg,
                     fg=T.muted, font=font(11)).pack(anchor="w")
        else:
            tk.Label(meta2, text="状态：进行中",
                     bg=T.bg, fg=T.muted, font=font(11)).pack(anchor="w")

        flat_button(self, "关闭", command=self._close, font_=font(12),
                    padx=16).pack(anchor="e", padx=20, pady=(10, 16))


# --------------------------------------------------------------------------
# 自绘日历
# --------------------------------------------------------------------------
class Calendar(tk.Frame):
    """自绘月历：年月导航 + 日期按钮网格。

    有完成记录的日期绿色标记；点击日期回调 on_select(date_str)；
    点击相邻月份的日期会切换到对应月份并选中。
    """

    def __init__(self, parent, db: Database, on_select=None,
                 selected: date | None = None):
        super().__init__(parent, bg=T.bg)
        self.db = db
        self.on_select = on_select
        self.selected = selected or date.today()
        self.year = self.selected.year
        self.month = self.selected.month
        self.completed_dates = set(db.get_completed_dates())
        self._cells: list[tuple[tk.Canvas, date | None]] = []
        self._build()
        self._render()

    def refresh_marks(self) -> None:
        """完成记录变化后刷新绿色标记。"""
        self.completed_dates = set(self.db.get_completed_dates())
        self._render()

    def _build(self) -> None:
        nav = tk.Frame(self, bg=T.bg)
        nav.pack(fill="x", pady=(0, 8))
        self.prev_btn = flat_button(
            nav, "‹", command=self._prev_month, bg=T.bg, hover_bg=T.panel,
            press_bg=T.panel2, font_=font(13, bold=True), padx=10, pady=2)
        self.prev_btn.pack(side="left")
        self.month_label = tk.Label(nav, text="", bg=T.bg, fg=T.title_text,
                                    font=font(13, bold=True))
        self.month_label.pack(side="left", expand=True)
        self.next_btn = flat_button(
            nav, "›", command=self._next_month, bg=T.bg, hover_bg=T.panel,
            press_bg=T.panel2, font_=font(13, bold=True), padx=10, pady=2)
        self.next_btn.pack(side="right")

        grid = tk.Frame(self, bg=T.bg)
        grid.pack()
        for col, name in enumerate(WEEKDAY_NAMES):
            tk.Label(grid, text=name, bg=T.bg, fg=T.muted, font=font(11),
                     width=4).grid(row=0, column=col, padx=1, pady=(0, 4))
        for week in range(6):
            for day_col in range(7):
                cell = tk.Canvas(grid, width=34, height=30, bg=T.bg,
                                 highlightthickness=0, bd=0,
                                 cursor="hand2")
                cell.grid(row=week + 1, column=day_col, padx=1, pady=1)
                cell.bind(
                    "<Button-1>",
                    self._make_cell_handler(len(self._cells)))
                self._cells.append((cell, None))

    def _make_cell_handler(self, index: int):
        def handler(_event):
            _cell, day = self._cells[index]
            if day is None:
                return
            self.selected = day
            self.year, self.month = day.year, day.month
            self._render()
            if self.on_select is not None:
                self.on_select(day.strftime("%Y-%m-%d"))
        return handler

    def _prev_month(self) -> None:
        self.year, self.month = self._shift_month(self.year, self.month, -1)
        self._render()

    def _next_month(self) -> None:
        self.year, self.month = self._shift_month(self.year, self.month, 1)
        self._render()

    @staticmethod
    def _shift_month(year: int, month: int, delta: int) -> tuple:
        total = year * 12 + (month - 1) + delta
        return total // 12, total % 12 + 1

    def _render(self) -> None:
        self.month_label.configure(text=f"{self.year} 年 {self.month} 月")
        first = date(self.year, self.month, 1)
        offset = first.weekday()  # 周一 = 0
        today = date.today()
        for index, (cell, _day) in enumerate(self._cells):
            day = first + timedelta(days=index - offset)
            self._cells[index] = (cell, day)
            cell.delete("all")
            in_month = day.month == self.month
            is_today = day == today
            is_selected = day == self.selected
            completed = day.strftime("%Y-%m-%d") in self.completed_dates

            if completed:
                fill = T.green
            elif is_selected:
                fill = T.accent
            else:
                fill = T.panel
            cell.configure(bg=fill)

            if completed or is_selected:
                text_color = "#ffffff"
            elif in_month:
                text_color = T.text
            else:
                text_color = T.muted
            cell.create_text(
                17, 15, text=str(day.day), fill=text_color,
                font=font(11, bold=is_today or is_selected),
            )
            if is_selected:
                outline = "#ffffff" if completed else T.accent_light
                cell.create_rectangle(1, 1, 33, 29, outline=outline, width=2)
            elif is_today:
                cell.create_rectangle(1, 1, 33, 29, outline=T.secondary)


# --------------------------------------------------------------------------
# 日报中心
# --------------------------------------------------------------------------
class ReportDialog(tk.Toplevel):
    """日报：左侧自绘日历选择日期（默认今日），右侧统计与任务明细。"""

    def __init__(self, parent, db: Database):
        super().__init__(parent)
        self.db = db
        self.current_date_str = None
        self.title("日报")
        self.configure(bg=T.bg)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda e: self.destroy())
        try:
            self.iconbitmap(ensure_app_icon())
        except tk.TclError:
            pass
        # 先隐藏，定位完成后统一显示，避免在左上角闪烁
        self.withdraw()

        container = tk.Frame(self, bg=T.bg)
        container.pack(fill="both", expand=True, padx=16, pady=16)

        left = tk.Frame(container, bg=T.bg)
        left.pack(side="left", fill="y", padx=(0, 14))
        self.calendar = Calendar(left, db, on_select=self._load_date)
        self.calendar.pack(anchor="n")
        tk.Label(left, text="绿色日期表示有完成记录", bg=T.bg, fg=T.muted,
                 font=font(11)).pack(anchor="w", pady=(8, 0))

        right = tk.Frame(container, bg=T.bg)
        right.pack(side="left", fill="both", expand=True)

        self.date_title = tk.Label(right, text="", bg=T.bg, fg=T.title_text,
                                   font=font(16, bold=True), anchor="w")
        self.date_title.pack(fill="x")
        self.total_label = tk.Label(right, text="", bg=T.bg, fg=T.green,
                                    font=font(14, bold=True), anchor="w")
        self.total_label.pack(fill="x", pady=(4, 0))
        self.quadrant_stats = tk.Label(
            right, text="", bg=T.bg, fg=T.text, font=font(12), anchor="w",
            justify="left", wraplength=520)
        self.quadrant_stats.pack(fill="x", pady=(2, 0))
        self.tag_stats = tk.Label(
            right, text="", bg=T.bg, fg=T.text, font=font(12), anchor="w",
            justify="left", wraplength=520)
        self.tag_stats.pack(fill="x", pady=(2, 8))

        table_area = tk.Frame(right, bg=T.bg)
        table_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table_area,
            columns=("time", "title", "tag", "quadrant", "desc"),
            show="headings", style="Dark.Treeview", selectmode="browse",
        )
        widths = {"time": 80, "title": 150, "tag": 70, "quadrant": 95,
                  "desc": 240}
        for column, heading in zip(self.tree["columns"], CSV_HEADERS):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=widths[column], anchor="w",
                             stretch=False)
        self.tree.tag_configure("odd", background=T.panel2)
        vsb = ttk.Scrollbar(table_area, orient="vertical",
                            command=self.tree.yview,
                            style="Dark.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._open_task_detail)

        btn_row = tk.Frame(right, bg=T.bg)
        btn_row.pack(fill="x", pady=(10, 0))
        flat_button(btn_row, "取消完成", bg=T.green, fg="#ffffff",
                    hover_bg=T.accent_light, press_bg=T.accent_dark,
                    command=self._uncomplete_selected).pack(side="left")
        flat_button(btn_row, "导出所选日期",
                    command=self._export_current_day).pack(side="left",
                                                           padx=(8, 0))
        flat_button(btn_row, "导出日期范围",
                    command=self._export_range).pack(
            side="left", padx=(8, 0))
        flat_button(btn_row, "关闭", command=self.destroy).pack(side="right")

        self.update_idletasks()
        self._center_on_parent(1000, 620)
        self.minsize(880, 540)

        self._load_date(date.today().strftime("%Y-%m-%d"))
        self.deiconify()

    def _center_on_parent(self, width: int, height: int) -> None:
        parent = self.master
        x = max(0, parent.winfo_rootx() + (parent.winfo_width() - width) // 2)
        y = max(0, parent.winfo_rooty() + (parent.winfo_height() - height) // 2)
        x = min(x, max(0, parent.winfo_screenwidth() - width - 20))
        y = min(y, max(0, parent.winfo_screenheight() - height - 20))
        self.geometry(f"{width}x{height}+{x}+{y}")

    # --------------------------------------------------------------- 展示
    def _load_date(self, date_str: str) -> None:
        self.current_date_str = date_str
        tasks = self.db.get_completed_tasks(date_str)
        stats = build_report_stats(tasks)

        self.date_title.configure(text=f"{date_str} 日报")
        self.total_label.configure(text=f"当日完成任务：{stats['total']} 个")

        quadrant_lines = [
            f"{quadrant_name(key)}：{count}"
            for key, count in stats["by_quadrant"].items() if count
        ]
        self.quadrant_stats.configure(
            text="按象限统计："
            + ("、".join(quadrant_lines) if quadrant_lines else "无"))

        tag_lines = [
            f"{tag}：{count}"
            for tag, count in sorted(stats["by_tag"].items(),
                                     key=lambda item: -item[1])
        ]
        self.tag_stats.configure(
            text="按标签统计：" + ("、".join(tag_lines) if tag_lines else "无"))

        self.tree.delete(*self.tree.get_children())
        for index, task in enumerate(tasks):
            self.tree.insert(
                "", "end", iid=str(task.id),
                values=[
                    self._time_part(task.completed_at), task.title,
                    "、".join(task.tags), task.quadrant_label,
                    # Treeview 单元格不支持换行，用 ⏎ 保留换行信息，
                    # 完整换行在双击打开的任务详情中展示
                    task.description.replace("\n", "⏎"),
                ],
                tags=("odd",) if index % 2 else (),
            )

    @staticmethod
    def _time_part(value: str) -> str:
        """提取完成时间的 HH:MM 部分（对齐 WebView 日报列）。"""
        if not value:
            return ""
        parts = value.split(" ")
        return parts[1][:5] if len(parts) > 1 else value[:5]

    def _uncomplete_selected(self) -> None:
        """取消完成：清空完成时间，任务回到四象限主页。"""
        selection = self.tree.selection()
        if not selection:
            safe_messagebox(self, "warning", "提示",
                            "请先在列表中选择要恢复为未完成的任务。")
            return
        try:
            task = self.db.get_task(int(selection[0]))
        except (ValueError, TypeError):
            return
        if task is None:
            return
        if not safe_messagebox(
                self, "askyesno", "取消完成",
                f"确定将「{task.title}」恢复为未完成？任务将回到四象限主页。"):
            return
        self.db.update_task(task.id, completed_at="")
        self.calendar.refresh_marks()
        self._load_date(self.current_date_str
                        or date.today().strftime("%Y-%m-%d"))
        if hasattr(self.master, "refresh_all"):
            self.master.refresh_all()

    def _open_task_detail(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        try:
            task = self.db.get_task(int(iid))
        except ValueError:
            return
        if task is not None:
            TaskDetailDialog(self, task).run()

    # --------------------------------------------------------------- 导出
    def _choose_directory(self):
        return filedialog.askdirectory(
            parent=self, title="选择日报导出目录",
            initialdir=str(Path.home()),
        )

    def _show_export_result(self, files) -> None:
        if not files:
            safe_messagebox(self, "info", "提示",
                            "该范围内没有可导出的完成记录。")
            return
        shown = "\n".join(str(path) for path in files[:6])
        more = "" if len(files) <= 6 else f"\n……共 {len(files)} 个文件"
        safe_messagebox(self, "info", "导出完成",
                        f"已生成 {len(files)} 个文件：\n{shown}{more}")

    def _export_current_day(self) -> None:
        date_str = self.current_date_str or date.today().strftime("%Y-%m-%d")
        if not self.db.get_completed_tasks(date_str):
            safe_messagebox(self, "info", "提示",
                            f"{date_str} 没有已完成任务，无需导出。")
            return
        directory = self._choose_directory()
        if not directory:
            return
        try:
            files = export_report(self.db, date_str, directory)
        except OSError as exc:
            safe_messagebox(self, "warning", "导出失败",
                            f"无法写入导出目录：\n{exc}")
            return
        self._show_export_result(files)

    def _export_range(self) -> None:
        dialog = RangeExportDialog(self, self.db)
        if not dialog.run():
            return
        start, end = dialog.result
        if not any(start <= d <= end for d in self.db.get_completed_dates()):
            safe_messagebox(self, "info", "提示",
                            "该范围内没有可导出的完成记录。")
            return
        directory = self._choose_directory()
        if not directory:
            return
        try:
            files = export_report_range(self.db, start, end, directory)
        except OSError as exc:
            safe_messagebox(self, "warning", "导出失败",
                            f"无法写入导出目录：\n{exc}")
            return
        self._show_export_result(files)


# --------------------------------------------------------------------------
# 日期范围导出
# --------------------------------------------------------------------------
class RangeExportDialog(ModalDialog):
    def __init__(self, parent, db: Database):
        super().__init__(parent, "导出日期范围")

        today = date.today()
        first_day = date(today.year, today.month, 1)

        body = tk.Frame(self, bg=T.bg)
        body.pack(fill="both", expand=True, padx=18, pady=18)

        calendars = tk.Frame(body, bg=T.bg)
        calendars.pack()

        start_col = tk.Frame(calendars, bg=T.bg)
        start_col.pack(side="left", padx=(0, 16))
        tk.Label(start_col, text="开始日期", bg=T.bg, fg=T.text,
                 font=font(12, bold=True)).pack(anchor="w", pady=(0, 6))
        self.start_cal = Calendar(start_col, db, selected=first_day)
        self.start_cal.pack()

        end_col = tk.Frame(calendars, bg=T.bg)
        end_col.pack(side="left")
        tk.Label(end_col, text="结束日期", bg=T.bg, fg=T.text,
                 font=font(12, bold=True)).pack(anchor="w", pady=(0, 6))
        self.end_cal = Calendar(end_col, db, selected=today)
        self.end_cal.pack()

        tk.Label(body, text="仅导出所选范围内有完成记录的日期。", bg=T.bg,
                 fg=T.muted, font=font(11)).pack(anchor="w", pady=(10, 0))

        btn_row = tk.Frame(self, bg=T.bg)
        btn_row.pack(fill="x", padx=18, pady=(0, 16))
        flat_button(btn_row, "取消", command=self._close).pack(side="right")
        flat_button(btn_row, "导出", bg=T.accent, fg="#ffffff",
                    hover_bg=T.accent_light, press_bg=T.accent_dark,
                    command=self._submit).pack(side="right", padx=(0, 8))

    def _submit(self) -> None:
        start = self.start_cal.selected
        end = self.end_cal.selected
        if start > end:
            safe_messagebox(self, "warning", "提示",
                            "开始日期不能晚于结束日期。")
            return
        self.result = (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        self.destroy()


# --------------------------------------------------------------------------
# 设置：窗口模式 + 主题外观
# --------------------------------------------------------------------------
class SettingsDialog(ModalDialog):
    """设置对话框：切换窗口模式与主题外观。"""

    def __init__(self, parent, current_mode: str, current_theme: str):
        super().__init__(parent, "设置")
        self.current_mode = (current_mode if current_mode in WINDOW_MODES
                             else "topmost")
        self.current_theme = current_theme

        body = tk.Frame(self, bg=T.bg)
        body.pack(fill="both", expand=True, padx=18, pady=18)

        # ---- 窗口模式 ----
        tk.Label(body, text="窗口模式", bg=T.bg, fg=T.title_text,
                 font=font(13, bold=True)).pack(anchor="w", pady=(0, 8))
        self.mode_var = tk.StringVar(value=self.current_mode)
        for key, info in WINDOW_MODES.items():
            row = tk.Frame(body, bg=T.bg)
            row.pack(fill="x", pady=3)
            rb = tk.Radiobutton(
                row, text=info["name"], variable=self.mode_var, value=key,
                bg=T.bg, fg=T.text, selectcolor=T.panel, activebackground=T.bg,
                activeforeground=T.text, font=font(12, bold=True),
                anchor="w", highlightthickness=0, bd=0,
            )
            rb.pack(side="left")
            tk.Label(row, text=info["desc"], bg=T.bg, fg=T.muted,
                     font=font(10)).pack(side="left", padx=(10, 0))

        # ---- 主题外观 ----
        tk.Label(body, text="主题外观", bg=T.bg, fg=T.title_text,
                 font=font(13, bold=True)).pack(anchor="w", pady=(16, 8))
        self.theme_var = tk.StringVar(
            value=self.current_theme if self.current_theme
            in theme_names() else "midnight")
        for key in theme_names():
            row = tk.Frame(body, bg=T.bg)
            row.pack(fill="x", pady=2)
            rb = tk.Radiobutton(
                row, text=THEMES[key]["name"], variable=self.theme_var,
                value=key, bg=T.bg, fg=T.text, selectcolor=T.panel,
                activebackground=T.bg, activeforeground=T.text,
                font=font(12), anchor="w", highlightthickness=0, bd=0,
            )
            rb.pack(side="left", padx=(0, 10))
            tk.Label(row, text=THEMES[key]["desc"], bg=T.bg, fg=T.muted,
                     font=font(10)).pack(side="left")

        # ---- 开机自启动 ----
        tk.Label(body, text="开机自启动", bg=T.bg, fg=T.title_text,
                 font=font(13, bold=True)).pack(anchor="w", pady=(16, 8))
        self.autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        row = tk.Frame(body, bg=T.bg)
        row.pack(fill="x", pady=3)
        cb = tk.Checkbutton(
            row, text="登录 Windows 后自动启动四象",
            variable=self.autostart_var, bg=T.bg, fg=T.text,
            selectcolor=T.panel, activebackground=T.bg,
            activeforeground=T.text, font=font(12), anchor="w",
            highlightthickness=0, bd=0,
        )
        cb.pack(side="left")
        tk.Label(row, text="写入注册表 HKCU Run，仅 Windows 生效", bg=T.bg,
                 fg=T.muted, font=font(10)).pack(side="left", padx=(10, 0))

        btn_row = tk.Frame(self, bg=T.bg)
        btn_row.pack(fill="x", pady=(16, 0))
        flat_button(btn_row, "打开日报", bg=T.report_bg, fg=T.report_fg,
                    hover_bg=T.report_hover, press_bg=T.report_press,
                    command=self._open_report).pack(side="left")
        self._update_btn = flat_button(btn_row, "检查更新", bg=T.panel2,
                                       fg=T.text, hover_bg=T.btn_hover,
                                       press_bg=T.btn_press,
                                       command=self._check_update)
        self._update_btn.pack(side="left", padx=(8, 0))
        flat_button(btn_row, "取消", command=self._close).pack(side="right")
        flat_button(btn_row, "确定", bg=T.accent, fg="#ffffff",
                    hover_bg=T.accent_light, press_bg=T.accent_dark,
                    command=self._submit).pack(side="right", padx=(0, 8))

    # ---- 检查更新（GitHub Releases）----
    def _check_update(self) -> None:
        if self._update_btn is not None:
            try:
                self._update_btn.configure(state="disabled")
            except tk.TclError:
                pass
        threading.Thread(target=self._check_worker, daemon=True).start()

    def _check_worker(self) -> None:
        info = updater.check_for_update()
        self.after(0, lambda: self._on_check_result(info))

    def _on_check_result(self, info) -> None:
        self._restore_update_btn()
        if info.get("error"):
            safe_messagebox(self, "warning", "检查更新", info["error"])
            return
        if not info.get("has_update"):
            safe_messagebox(self, "info", "检查更新",
                            f"当前已是最新版本 v{info['current_version']}")
            return
        notes = (info.get("notes") or "").strip()
        msg = (f"发现新版本 v{info['latest_version']}（当前 v"
               f"{info['current_version']}）\n\n")
        if notes:
            msg += f"更新说明：\n{notes[:200]}\n\n"
        msg += "是否立即下载并更新？"
        if not safe_messagebox(self, "askyesno", "检查更新", msg):
            return
        self._download_and_apply(info)

    def _download_and_apply(self, info) -> None:
        if self._update_btn is not None:
            try:
                self._update_btn.configure(state="disabled", text="下载中…")
            except tk.TclError:
                pass

        def _worker():
            url = info.get("download_url")
            if not url:
                self.after(0, lambda: safe_messagebox(
                    self, "warning", "检查更新", "release 中没有可下载的 exe 文件"))
                return
            ok, msg = updater.download_now(
                url,
                info.get("file_name") or "update.exe",
                int(info.get("size") or 0),
                info.get("sha256"),
            )
            self.after(0, lambda: self._on_download_done(ok, msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_download_done(self, ok: bool, msg: str) -> None:
        if not ok:
            safe_messagebox(self, "error", "更新下载失败", msg)
            self._restore_update_btn()
            return
        if not safe_messagebox(self, "askyesno", "下载完成",
                               f"更新文件已下载：\n{msg}\n\n是否立即重启并完成更新？"):
            self._restore_update_btn()
            return
        result = updater.apply_update()
        if not result.get("ok"):
            safe_messagebox(self, "error", "应用更新", result.get("error") or "未知错误")
            self._restore_update_btn()
            return
        safe_messagebox(self, "info", "正在更新", "程序即将重启以完成更新…")
        self.master.after(300, self.master.destroy)

    def _restore_update_btn(self) -> None:
        if self._update_btn is not None:
            try:
                self._update_btn.configure(state="normal", text="检查更新")
            except tk.TclError:
                pass

    def _open_report(self) -> None:
        parent = self.master
        if hasattr(parent, "open_report_dialog"):
            parent.open_report_dialog()
        self._close()

    def _submit(self) -> None:
        autostart.set_enabled(bool(self.autostart_var.get()))
        self.result = {
            "mode": str(self.mode_var.get()),
            "theme": str(self.theme_var.get()),
        }
        self.destroy()
