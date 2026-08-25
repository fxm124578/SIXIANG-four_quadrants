# 四象 · WebView 版标准改造方案

> 状态：方案定稿，待按第 7 节顺序执行
> 日期：2026-08-25

## 1. 背景与结论

- tkinter 没有 HTML/CSS 渲染引擎，无法还原四套 HTML 设计（毛玻璃 `backdrop-filter`、霓虹辉光、纸纹等），此前"tkinter 逼近"路线已确认达不到设计目标。
- **最终结论：采用 pywebview（Windows 系统 WebView2 内核）直接渲染 HTML**，四套设计的视觉效果 100% 由浏览器还原。
- 唯一新增依赖：`pywebview`（pip 安装）。系统要求：Windows 10/11（自带 WebView2 Runtime；Windows 10 早期版本需安装 Microsoft Edge WebView2 Runtime，免费）。
- 数据层 `db.py / models.py / report.py`（纯标准库）**完全复用，不改动**，现有 `data.db` 数据直接可用。

## 2. 总体架构

```
main.py（入口）
 ├─ 检测 pywebview 可用
 │    ├─ 可用 → webview_main.py（窗口管理 + JsApi 桥）
 │    │            └─ web/app.html（单页应用：四套主题 CSS 内联 + 全部功能 JS）
 │    └─ 不可用 → 回退现有 tkinter 模式（widgets/、dialogs.py 保留，run.bat 永远可运行）
 └─ 数据层：db.py / models.py / report.py（不变）
```

- 前端 JS 通过 `window.pywebview.api.*` 调用 Python 的 `JsApi`，桥接 SQLite 数据层与日报导出。
- tkinter 代码（`widgets/`、`dialogs.py`、`styles.py`）**保留不删**，作为回退与并存实现。

## 3. 功能映射表（现有功能 → WebView 实现）

| 功能 | WebView 实现 |
|---|---|
| 四象限展示 | JS 渲染 2×2 网格，数据来自 `api.get_active_tasks()` |
| 新建任务（标题/描述/多标签/象限） | 模态弹窗 → `api.add_task()` |
| 任务详情 | 点击任务行弹窗 → `api.get_task()` |
| 勾选完成归档 | 勾选 → `api.complete_task()`，立即从象限移除 |
| 跨象限拖拽 | HTML5 drag/drop，drop 后 `api.set_quadrant()` |
| 多标签胶囊 | JS 渲染多胶囊（最多 2 个 + "+N"） |
| 日报中心 | JS 自绘日历（完成日期绿色标记）+ 统计 + 明细表 |
| 单日 / 范围导出 | `api.export_day()` / `api.export_range()`（复用 report.py） |
| 设置 · 主题 | JS 切换 body 主题 class（四套 CSS 内联），即时生效并持久化 |
| 设置 · 窗口模式 | 保存设置 → 自动重启进程（Python 端按设置重建窗口） |
| 位置 / 大小记忆 | JS 监听 move/resize → `api.save_window()`；启动时 Python 读取 |
| 退出 | 前端按钮 → `api.quit()` → 保存设置后退出 |

## 4. 窗口模式（WebView 实现，全部支持）

| 模式 | frameless | on_top | 效果 |
|---|---|---|---|
| 置顶最前 | true | true | 无边框，悬浮在所有应用之上 |
| 固定桌面 | true | false | 无边框、不置顶，不影响其他应用显示 |
| 普通窗口 | false | false | 系统标题栏（- □ X），可最小化 / 最大化 / 关闭 |

- 切换方式：设置面板选择 → 保存 `window_mode` 到 settings 表 → **自动重启进程**（`subprocess` 重启自身），新窗口按新模式创建。
- 说明：pywebview 的 `frameless / on_top` 在窗口创建时确定，因此用重启实现切换；位置、大小、主题、锁定等状态在重启前持久化，重启后恢复。

## 5. 主题四套（100% 还原 HTML 方案）

`web/app.html` 内联四套完整 CSS，切换主题 = 切换 `body` 的 theme class：

| 主题 | 还原要点 |
|---|---|
| midnight 午夜玻璃 | 深靛蓝渐变背景、漂浮光斑、顶部彩虹光谱线、象限发光描边、玻璃高光 |
| frost 雾白冰川 | 明亮磨砂玻璃、白色高光、莫兰迪柔色、圆形勾选 |
| neon 霓虹网格 | 近黑背景、透视网格、CRT 扫描线、霓虹描边与辉光 |
| paper 晨雾纸墨 | 暖米纸纹、朱砂装订红绳（两端圆点）、手绘印章式勾选动效 |

- 毛玻璃 `backdrop-filter: blur()`、渐变、动画全部由浏览器渲染，无近似。
- 主题选择持久化到 settings 表，重启后保持。

## 6. 数据与兼容

- `data.db` 表结构不变；tkinter 版与 WebView 版共用同一数据库，历史数据无损。
- 未安装 pywebview 的机器：`main.py` 自动回退 tkinter 版，功能等价、设计为近似风格。
- `started.log` 启动日志机制保留，便于核对实际运行版本。

## 7. 实施步骤（严格按此顺序执行）

1. 安装 `pywebview`（pip，TMP/TEMP 指到工作区 `.pipsrc`），验证 `import webview` 与 WebView2 Runtime 可用。
2. 编写 `web/app.html`：四套主题完整 CSS + 全部功能 JS（象限渲染、弹窗、拖拽、日报日历、导出）。
3. 编写 `webview_main.py`：`JsApi`（桥接 db/report）+ 窗口创建 + 模式重启 + 设置持久化。
4. 改造 `main.py`：webview 优先、tkinter 回退的入口分发。
5. 验证：启动、四主题切换、任务增删改、跨象限拖拽、勾选归档、日报与导出。
6. 更新 README（依赖说明、回退说明），`run.bat` 保持不变。

## 8. 验收标准

- [ ] `python main.py` 直接启动 WebView 版，四套设计与 HTML 方案视觉一致（毛玻璃、动效完整）
- [ ] 三种窗口模式可切换并实际生效
- [ ] 任务新建 / 详情 / 勾选归档 / 跨象限拖拽 / 多标签 / 日报导出与现版功能等价
- [ ] 未安装 pywebview 时自动回退 tkinter 版，应用仍可运行
- [ ] 位置 / 大小 / 锁定 / 主题 / 模式全部记忆，重启恢复

## 9. 风险与对策

| 风险 | 对策 |
|---|---|
| pywebview 6.x 对 Python 3.14 的兼容性 | 安装后立即验证 import 与窗口创建；不兼容则固定可用版本或降级 Python 3.12 |
| WebView2 Runtime 缺失（旧版 Win10） | 启动时检测，缺失则提示安装或自动回退 tkinter 版 |
| 真透明窗口（看穿桌面）在 WebView2 上不支持 | 四套方案背景均为 HTML 内部元素，效果自包含，不受影响 |
| 模式切换需重启窗口 | 重启前持久化全部状态，重启后无缝恢复 |
