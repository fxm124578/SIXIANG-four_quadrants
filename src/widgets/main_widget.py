"""悬浮主窗口：无边框、始终置顶、可拖动位置、右下角缩放、四象限网格。

- overrideredirect + -topmost 实现无边框置顶悬浮
- 顶部标题栏拖动窗口；右下角手柄调整大小
- 位置 / 大小 / 锁定 / 透明度 / 窗口模式 / 主题自动持久化到 settings 表
- 跨象限拖拽：超过阈值显示幽灵窗口，释放时命中测试目标象限
- 主题切换：重建内容区即时换肤
"""
from __future__ import annotations

import tkinter as tk
from datetime import date

import dialogs
import updater
from db import Database
from styles import (
    T,
    apply_dark_ttk_style,
    ensure_app_icon,
    font,
    set_theme,
    theme_name,
)
from widgets.quadrant_card import QuadrantCard

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
MIN_WIDTH, MIN_HEIGHT = 400, 500


class MainWindow(tk.Tk):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._locked = False
        self._opacity = 0.97
        self._save_after_id = None
        self._window_drag = None
        self._resize_drag = None
        self._task_drag = None
        self._ghost = None
        self._report_dialog = None
        self._window_mode = "topmost"

        # 先隐藏，设置全部就绪后再显示，避免闪烁
        self.withdraw()
        self.title("四象")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.configure(bg=T.card)
        try:
            self.iconbitmap(ensure_app_icon())
        except tk.TclError:
            pass

        apply_dark_ttk_style(self)
        self._load_settings()
        self._build_ui()
        self._sync_lock_btn()
        self._apply_window_mode(self._window_mode)
        self.attributes("-alpha", self._opacity)
        self._refresh_all()

        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.bind_all("<MouseWheel>", self._on_global_wheel)
        self.deiconify()
        self.lift()

    # ------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self.card = tk.Frame(self, bg=T.bg, bd=0, highlightthickness=1,
                             highlightbackground=T.border,
                             highlightcolor=T.border)
        self.card.pack(fill="both", expand=True)

        # 背景氛围层：垂直渐变 / 角落光斑 / 霓虹网格 / 顶部装饰线
        self.bg_canvas = tk.Canvas(self.card, bg=T.bg, highlightthickness=0,
                                   bd=0, takefocus=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.bg_canvas.bind("<Configure>", self._draw_background)

        content = tk.Frame(self.card, bg=T.bg)
        content.pack(fill="both", expand=True)

        # 顶部：标题 + 日期；空白区域可拖动整个窗口
        header = tk.Frame(content, bg=T.bg)
        header.pack(fill="x", padx=14, pady=(16, 0))
        self.title_label = tk.Label(header, text="四象", bg=T.bg,
                                    fg=T.title_text, font=font(15, bold=True))
        self.title_label.pack(side="left")
        self.date_label = tk.Label(header, text=self._today_str(),
                                   bg=T.bg, fg=T.secondary, font=font(12))
        self.date_label.pack(side="right")
        for widget in (header, self.title_label, self.date_label):
            widget.bind("<ButtonPress-1>", self._on_window_press)
            widget.bind("<B1-Motion>", self._on_window_drag)
            widget.bind("<ButtonRelease-1>", self._on_window_release)

        # 中部：2x2 四象限网格
        grid = tk.Frame(content, bg=T.bg)
        grid.pack(fill="both", expand=True, padx=14, pady=10)
        for index in range(2):
            grid.columnconfigure(index, weight=1, uniform="quad")
            grid.rowconfigure(index, weight=1, uniform="quad")
        self.cards = []
        for quadrant in range(4):
            quadrant_card = QuadrantCard(grid, quadrant, self)
            quadrant_card.grid(row=quadrant // 2, column=quadrant % 2,
                               sticky="nsew", padx=4, pady=4)
            self.cards.append(quadrant_card)

        # 底部工具栏
        footer = tk.Frame(content, bg=T.bg)
        footer.pack(fill="x", padx=14, pady=(0, 10))

        # 右下角缩放手柄
        self.grip = tk.Canvas(footer, width=14, height=14, bg=T.bg,
                              highlightthickness=0, bd=0,
                              cursor="size_nw_se", takefocus=0)
        for (x1, y1, x2, y2) in ((2, 12, 12, 2), (5, 12, 12, 5),
                                 (8, 12, 12, 8)):
            self.grip.create_line(x1, y1, x2, y2, fill=T.grip, width=1)
        self.grip.bind("<ButtonPress-1>", self._on_grip_press)
        self.grip.bind("<B1-Motion>", self._on_grip_drag)
        self.grip.bind("<ButtonRelease-1>", self._on_grip_release)
        self.grip.pack(side="right", padx=(10, 2))

        self.quit_btn = dialogs.flat_button(footer, "退出",
                                            command=self.quit_app)
        self.quit_btn.pack(side="right", padx=(0, 6))

        self.lock_btn = dialogs.flat_button(footer, "锁定",
                                            command=self.toggle_lock)
        self.lock_btn.pack(side="right", padx=(0, 8))

        # 设置按钮按 HTML 布局放底部工具栏（右侧组：设置 锁定 退出）
        self.settings_btn = dialogs.flat_button(
            footer, "设置", command=self.open_settings_dialog)
        self.settings_btn.pack(side="right", padx=(0, 8))

        self.add_btn = dialogs.flat_button(
            footer, "＋ 新建任务", bg=T.accent, fg="#ffffff",
            hover_bg=T.accent_light, press_bg=T.accent_dark,
            command=lambda: self.open_add_task_dialog(0))
        self.add_btn.pack(side="left")

        # 日报入口：绿色高亮，便于快速找到
        self.report_btn = dialogs.flat_button(
            footer, "日报", bg=T.report_bg, fg=T.report_fg,
            hover_bg=T.report_hover, press_bg=T.report_press,
            command=self.open_report_dialog)
        self.report_btn.pack(side="left", padx=(8, 0))

    def _draw_background(self, _event=None) -> None:
        """绘制主题背景氛围：垂直渐变 + 光斑 + 网格 + 顶部装饰线。"""
        try:
            from styles import blend
            canvas = self.bg_canvas
            canvas.delete("all")
            width = canvas.winfo_width()
            height = canvas.winfo_height()
            if width <= 0 or height <= 0:
                return
            # 垂直渐变（呼应 HTML 的玻璃/纸感背景）
            rows = 44
            for index in range(rows):
                y0 = height * index // rows
                y1 = height * (index + 1) // rows + 1
                canvas.create_rectangle(
                    0, y0, width, y1,
                    fill=blend(T.grad_hi, T.grad_lo,
                               index / (rows - 1)), outline="")
            # 左上角斜向玻璃高光（呼应 HTML 的 ::after 斜光）
            if T.topline != "neon":  # 霓虹主题保持锐利，不加白光
                for index in range(26):
                    x1 = max(0, int(width * (1 - index * 0.028)))
                    y0 = index * 3
                    canvas.create_rectangle(
                        0, y0, x1, y0 + 2,
                        fill=blend(T.grad_hi, "#ffffff",
                                   0.10 * (1 - index / 26)), outline="")
            # 角落氛围光斑
            for index, accent in enumerate(T.bg_accent):
                color = blend(T.grad_lo, accent, 0.16)
                if index == 0:
                    canvas.create_oval(-width * 0.2, -height * 0.28,
                                       width * 0.55, height * 0.32,
                                       fill=color, outline="")
                else:
                    canvas.create_oval(width * 0.55, height * 0.72,
                                       width * 1.25, height * 1.3,
                                       fill=color, outline="")
            # 霓虹网格线（neon 主题专属）
            if T.bg_grid:
                grid_color = blend(T.grad_lo, T.accent, 0.10)
                spacing = 26
                for x in range(0, width + spacing, spacing):
                    canvas.create_line(x, 0, x + width * 0.25, height,
                                       fill=grid_color, width=1)
                for y in range(0, height + spacing, spacing):
                    canvas.create_line(0, y, width, y, fill=grid_color,
                                       width=1)
            self._draw_topline(canvas, width)
        except tk.TclError:
            pass

    def _draw_topline(self, canvas: tk.Canvas, width: int) -> None:
        """按主题绘制顶部装饰线：彩虹光谱 / 白色高光 / 霓虹 / 朱砂红绳。"""
        try:
            from styles import blend
            kind = T.topline
            if kind == "spectrum":
                from models import QUADRANTS as QUAD_COLORS
                stops = [item["color"] for item in QUAD_COLORS]
                base = [int(T.grad_hi[i:i + 2], 16) for i in (1, 3, 5)]
                top, bar_h, steps = 7, 3, 48
                for index in range(steps):
                    frac = index / (steps - 1)
                    pos = frac * (len(stops) - 1)
                    lo_i = int(pos)
                    hi_i = min(lo_i + 1, len(stops) - 1)
                    mix = pos - lo_i
                    c1 = [int(stops[lo_i][i:i + 2], 16) for i in (1, 3, 5)]
                    c2 = [int(stops[hi_i][i:i + 2], 16) for i in (1, 3, 5)]
                    rgb = [c1[k] + (c2[k] - c1[k]) * mix for k in range(3)]
                    if frac > 0.8:  # 尾部渐隐
                        fade = (frac - 0.8) / 0.2
                        rgb = [rgb[k] + (base[k] - rgb[k]) * fade
                               for k in range(3)]
                    color = "#" + "".join(
                        f"{max(0, min(255, int(v))):02x}" for v in rgb)
                    x0 = width * index // steps
                    x1 = width * (index + 1) // steps
                    canvas.create_rectangle(x0, top, x1, top + bar_h,
                                            fill=color, outline="")
            elif kind == "glow":
                # 左上至右下的白色磨砂高光
                for index in range(16):
                    y = 4 + index * 2
                    canvas.create_rectangle(
                        0, y, width, y + 1,
                        fill=blend(T.grad_hi, "#ffffff",
                                   0.45 - index * 0.02), outline="")
            elif kind == "neon":
                top = 7
                canvas.create_rectangle(14, top, width - 14, top + 2,
                                        fill=T.accent, outline="")
            elif kind == "thread":
                # 朱砂装订红绳 + 两端圆点
                top = 8
                canvas.create_line(26, top, width - 26, top, fill=T.accent,
                                   width=2)
                for x in (26, width - 26):
                    canvas.create_oval(x - 3, top - 3, x + 3, top + 3,
                                       fill=T.accent, outline="")
        except tk.TclError:
            pass

    def _rebuild_ui(self) -> None:
        """主题切换后重建内容区（保留窗口几何与状态）。"""
        self.card.destroy()
        self._build_ui()
        self._sync_lock_btn()
        apply_dark_ttk_style(self)
        self._refresh_all()
        self._schedule_save()

    # ------------------------------------------------------------ 窗口拖动
    def _on_window_press(self, event) -> None:
        if self._locked:
            return
        self._window_drag = (event.x_root - self.winfo_x(),
                             event.y_root - self.winfo_y())

    def _on_window_drag(self, event) -> None:
        if self._window_drag is None:
            return
        x = event.x_root - self._window_drag[0]
        y = event.y_root - self._window_drag[1]
        self.geometry(f"+{x}+{y}")
        self._schedule_save()

    def _on_window_release(self, _event) -> None:
        self._window_drag = None
        self._schedule_save()

    # ------------------------------------------------------------ 窗口缩放
    def _on_grip_press(self, event) -> None:
        self._resize_drag = (self.winfo_width() - event.x_root,
                             self.winfo_height() - event.y_root)

    def _on_grip_drag(self, event) -> None:
        if self._resize_drag is None:
            return
        width = max(MIN_WIDTH, event.x_root + self._resize_drag[0])
        height = max(MIN_HEIGHT, event.y_root + self._resize_drag[1])
        self.geometry(f"{width}x{height}")
        self._schedule_save()

    def _on_grip_release(self, _event) -> None:
        self._resize_drag = None
        self._schedule_save()

    # ------------------------------------------------------------ 任务操作
    def _refresh_all(self) -> None:
        try:
            self.date_label.configure(text=self._today_str())
        except tk.TclError:
            pass
        by_quadrant = {q: [] for q in range(4)}
        for task in self.db.get_active_tasks():
            if 0 <= task.quadrant <= 3:
                by_quadrant[task.quadrant].append(task)
        for quadrant_card in self.cards:
            quadrant_card.set_tasks(by_quadrant[quadrant_card.quadrant_key])

    def refresh_all(self) -> None:
        """延迟刷新：避免在勾选 / 拖放回调栈内销毁控件。"""
        self.after(60, self._refresh_all)

    def complete_task(self, task_id: int) -> None:
        self.db.complete_task(task_id)
        self.refresh_all()
        self._refresh_report_marks()

    def show_task_detail(self, task_id: int) -> None:
        task = self.db.get_task(task_id)
        if task is not None:
            dialogs.TaskDetailDialog(self, task).run()

    def open_add_task_dialog(self, default_quadrant: int = 0) -> None:
        dialog = dialogs.AddTaskDialog(self,
                                       default_quadrant=default_quadrant)
        if dialog.run():
            values = dialog.result
            self.db.add_task(title=values["title"],
                             description=values["description"],
                             tag=values["tag"],
                             quadrant=values["quadrant"])
            self.refresh_all()

    def open_report_dialog(self) -> None:
        if (self._report_dialog is not None
                and self._report_dialog.winfo_exists()):
            self._report_dialog.lift()
            self._report_dialog.focus_force()
            return
        self._report_dialog = dialogs.ReportDialog(self, self.db)

    def _refresh_report_marks(self) -> None:
        """任务完成后同步刷新已打开日报的日历绿色标记。"""
        if self._report_dialog is not None:
            try:
                if self._report_dialog.winfo_exists():
                    self._report_dialog.calendar.refresh_marks()
            except tk.TclError:
                pass

    # ------------------------------------------------------------ 跨象限拖拽
    def begin_task_drag(self, row, x_root: int, y_root: int) -> None:
        """开始拖拽：创建跟随鼠标的幽灵窗口。"""
        if self._task_drag is not None:
            return
        self._task_drag = {"row": row, "task_id": row.task.id,
                           "source": row.quadrant, "hover": None}
        ghost = tk.Toplevel(self)
        ghost.overrideredirect(True)
        ghost.attributes("-topmost", True)
        ghost.attributes("-alpha", 0.9)
        ghost.configure(bg=T.ghost_bg, highlightthickness=1,
                        highlightbackground=T.accent)
        tk.Label(ghost, text=row.task.title, bg=T.ghost_bg, fg=T.text,
                 font=font(12), padx=12, pady=8).pack()
        ghost.geometry(f"+{x_root + 10}+{y_root + 10}")
        self._ghost = ghost
        row.set_dragging(True)

    def drag_move_task(self, x_root: int, y_root: int) -> None:
        """拖拽移动：移动幽灵窗口并高亮悬停象限。"""
        if self._ghost is not None:
            self._ghost.geometry(f"+{x_root + 10}+{y_root + 10}")
        if self._task_drag is None:
            return
        target = self._quadrant_at(x_root, y_root)
        hover = self._task_drag["hover"]
        if target != hover:
            if hover is not None:
                self.cards[hover].set_drag_hover(False)
            self._task_drag["hover"] = target
            if target is not None:
                self.cards[target].set_drag_hover(True)

    def end_task_drag(self, x_root: int, y_root: int) -> None:
        """释放：命中其他象限则切换并刷新，否则恢复源行样式。"""
        if self._task_drag is None:
            return
        drag = self._task_drag
        self._task_drag = None
        if self._ghost is not None:
            self._ghost.destroy()
            self._ghost = None
        target = self._quadrant_at(x_root, y_root)
        if drag["hover"] is not None:
            self.cards[drag["hover"]].set_drag_hover(False)
        if target is not None and target != drag["source"]:
            self.db.update_task(drag["task_id"], quadrant=target)
            self.refresh_all()
        else:
            drag["row"].set_dragging(False)

    def _quadrant_at(self, x_root: int, y_root: int):
        widget = self._find_ancestor(
            self.winfo_containing(x_root, y_root),
            lambda w: getattr(w, "quadrant_key", None) is not None,
        )
        return int(widget.quadrant_key) if widget is not None else None

    @staticmethod
    def _find_ancestor(widget, predicate):
        """沿 master 链向上查找满足条件的控件。"""
        while widget is not None:
            if predicate(widget):
                return widget
            widget = getattr(widget, "master", None)
        return None

    # ------------------------------------------------------------ 全局滚轮
    def _on_global_wheel(self, event) -> None:
        """滚轮：悬停在四象限列表滚动列表，悬停在日报表格滚动表格。"""
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is not None:
            canvas = self._find_ancestor(
                widget,
                lambda w: (isinstance(w, tk.Canvas)
                           and getattr(w, "_quadrant_scroll", False)),
            )
            if canvas is not None:
                canvas.yview_scroll(-2 if event.delta > 0 else 2, "units")
                return
        for toplevel in self.winfo_children():
            if not isinstance(toplevel, dialogs.ReportDialog):
                continue
            try:
                if not toplevel.winfo_viewable():
                    continue
            except tk.TclError:
                continue
            if toplevel.winfo_containing(event.x_root, event.y_root) is not None:
                toplevel.tree.yview_scroll(-2 if event.delta > 0 else 2,
                                           "units")
                return

    # ------------------------------------------------------------ 锁定
    def toggle_lock(self) -> None:
        self._locked = not self._locked
        self._sync_lock_btn()
        self._schedule_save()

    def _sync_lock_btn(self) -> None:
        if self._locked:
            self.lock_btn.configure(text="已锁定", bg=T.lock_bg)
            self.lock_btn._base, self.lock_btn._hover, self.lock_btn._press = (
                T.lock_bg, T.lock_hover, T.lock_press)
        else:
            self.lock_btn.configure(text="锁定", bg=T.panel)
            self.lock_btn._base, self.lock_btn._hover, self.lock_btn._press = (
                T.panel, T.btn_hover, T.btn_press)

    # ------------------------------------------------------------ 设置 / 主题
    def open_settings_dialog(self) -> None:
        dialog = dialogs.SettingsDialog(self, self._window_mode,
                                        theme_name())
        result = dialog.run()
        if not result:
            return
        mode = result.get("mode")
        theme = result.get("theme")
        if mode and mode != self._window_mode:
            self._apply_window_mode(mode)
        if theme and theme != theme_name():
            self.apply_theme(theme)

    def apply_theme(self, name: str) -> None:
        """切换主题并即时重建界面（含窗口透明度跟随主题）。"""
        set_theme(name)
        self.db.set_setting("theme", theme_name())
        self._opacity = T.alpha
        self.attributes("-alpha", self._opacity)
        self._rebuild_ui()

    # ------------------------------------------------------------ 窗口模式
    def _apply_window_mode(self, mode: str) -> None:
        """切换窗口模式：固定桌面 / 置顶最前 / 普通窗口。"""
        self._window_mode = (mode if mode in dialogs.WINDOW_MODES
                             else "topmost")
        self.withdraw()
        if self._window_mode == "normal":
            self.overrideredirect(False)   # 恢复系统标题栏（- □ X）
            self.attributes("-topmost", False)
        else:
            self.overrideredirect(True)
            self.attributes("-topmost", self._window_mode == "topmost")
        self.deiconify()
        self.lift()
        self._schedule_save()

    # ------------------------------------------------------------ 设置持久化
    @staticmethod
    def _today_str() -> str:
        today = date.today()
        return (f"{today.strftime('%Y-%m-%d')} "
                f"{WEEKDAY_NAMES[today.weekday()]} · v{updater.APP_VERSION}")

    def _load_settings(self) -> None:
        # 主题（先于 _build_ui 生效）
        set_theme(self.db.get_setting("theme") or "midnight")
        # 窗口透明度跟随主题设计（玻璃/纸感）
        self._opacity = T.alpha

        def setting_int(key: str, default: int) -> int:
            try:
                return int(self.db.get_setting(key) or default)
            except ValueError:
                return default

        width = max(MIN_WIDTH, min(setting_int("window_width", 420), 1400))
        height = max(MIN_HEIGHT, min(setting_int("window_height", 540), 1400))
        x = setting_int("window_x", -1)
        y = setting_int("window_y", -1)
        locked = (self.db.get_setting("locked") or "0") == "1"
        mode = self.db.get_setting("window_mode") or "topmost"
        self._window_mode = (mode if mode in dialogs.WINDOW_MODES
                             else "topmost")
        self._locked = locked

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        if x < 0 or y < 0:
            x = screen_w - width - 24
            y = 24
        # 钳制到屏幕内（底部预留任务栏空间）
        x = max(0, min(x, screen_w - width + 1))
        y = max(24, min(y, screen_h - height - 48))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _persist_settings(self) -> None:
        try:
            self.db.set_setting("window_x", str(self.winfo_x()))
            self.db.set_setting("window_y", str(self.winfo_y()))
            self.db.set_setting("window_width", str(self.winfo_width()))
            self.db.set_setting("window_height", str(self.winfo_height()))
            self.db.set_setting("opacity", f"{self._opacity:.2f}")
            self.db.set_setting("locked", "1" if self._locked else "0")
            self.db.set_setting("window_mode", self._window_mode)
            self.db.set_setting("theme", theme_name())
        except tk.TclError:
            pass

    def _schedule_save(self) -> None:
        if self._save_after_id is not None:
            try:
                self.after_cancel(self._save_after_id)
            except tk.TclError:
                pass
        self._save_after_id = self.after(500, self._do_save)

    def _do_save(self) -> None:
        self._save_after_id = None
        self._persist_settings()

    # ------------------------------------------------------------ 生命周期
    def quit_app(self) -> None:
        self._persist_settings()
        try:
            self.destroy()
        except tk.TclError:
            pass
