# 四象

> Windows 桌面四象限任务管理小组件 —— 悬浮窗常驻桌面，让「紧急且重要」始终可见。

四象限桌面任务管理小组件：无边框悬浮窗 + 四套设计主题 + WebView / tkinter 双引擎，零第三方依赖（纯 Python 标准库），单文件免安装。

## ✨ 亮点

- 🪟 桌面悬浮窗：无边框、置顶、可拖动、边缘拖拽调整大小，不打扰工作流
- 🗂️ 四象限：紧急且重要 / 紧急不重要 / 不紧急重要 / 不紧急不重要
- 🎨 四套主题：午夜玻璃 / 雾白冰川 / 霓虹网格 / 晨雾纸墨
- 📋 日报中心：底部抽屉式日历，按日查看完成任务 / 象限统计 / 标签统计
- 📤 导出：单日或日期范围批量导出 CSV + JSON
- 🔄 自动更新：设置页一键检查 GitHub Releases 新版，确认后自动下载并替换重启
- ⚡ 零依赖：仅 Python 标准库实现，WebView 渲染 / tkinter 回退双引擎

## 功能

- 桌面悬浮窗：无边框、置顶、可拖动、边缘拖拽调整大小
- 四象限：紧急且重要 / 紧急不重要 / 不紧急重要 / 不紧急不重要
- 任务管理：新建、编辑、删除、多标签、跨象限拖拽、勾选归档
- 标签筛选：底部「筛选」按钮，上拉面板多选标签，实时筛选四象限任务
- 日报中心：底部抽屉式日历，按日查看完成任务 / 象限统计 / 标签统计
- 导出：单日或日期范围批量导出 CSV + JSON
- 三种窗口模式：置顶最前 / 固定桌面 / 普通窗口（系统标题栏）
- 四套主题：午夜玻璃 / 雾白冰川 / 霓虹网格 / 晨雾纸墨
- 设置自动记忆：窗口位置、大小、锁定、主题、模式
- 软件更新：设置页一键检查 GitHub Releases 新版，确认后自动下载并替换重启

## 快速开始

```bash
# 安装依赖（仅 pywebview，系统需 Win10/11 自带 WebView2 Runtime）
pip install pywebview

# 启动
python src\main.py
```

Windows 也可双击 `run.bat`（自动优先 `pythonw`，无控制台窗口）。

若未安装 pywebview，`src/main.py` 会自动回退到 tkinter 版（零依赖，视觉近似）。

## 目录结构

```
├─ src/                应用源码
│  ├─ main.py          入口（webview 优先，tkinter 回退）
│  ├─ webview_main.py  WebView 版：JsApi 桥 + 窗口管理
│  ├─ db.py            SQLite 数据层
│  ├─ models.py        数据模型 + 四象限常量
│  ├─ report.py        日报统计与 CSV/JSON 导出
│  ├─ updater.py       GitHub Releases 检查 / 下载 / 自动更新
│  ├─ dialogs.py       tkinter 回退版对话框
│  ├─ styles.py        主题系统 + ICO 图标
│  ├─ app_icon.ico/.svg  应用图标
│  ├─ web/app.html     单页应用：四套主题 + 全部功能
│  ├─ widgets/         tkinter 回退版（main_widget / quadrant_card / task_item）
│  └─ data.db          SQLite 数据文件（源码运行）
├─ designs/            四套 HTML 设计方案（预览 / 参考）
├─ run.bat             Windows 启动脚本
├─ requirements.txt    依赖说明
├─ LICENSE             MIT
└─ DESIGN.md           WebView 版改造方案文档
```

## 数据

- SQLite 单文件 `data.db`：源码运行在 `src/`，打包版在 exe 同目录；不可写时回退 `~/.quadrant_tasks/data.db`
- 导出文件默认到桌面 `~/Desktop/四象日报导出/`

## 打包

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name 四象 --icon=src/app_icon.ico --add-data "src/web;web" --add-data "src/app_icon.ico;." src/main.py
```

## 许可证

[MIT](LICENSE)
