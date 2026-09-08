# 四象

> Windows 桌面四象限任务管理小组件 —— 悬浮窗常驻桌面，让「紧急且重要」始终可见。

四象限桌面任务管理小组件：无边框悬浮窗 + 九套设计主题 + WebView / tkinter 双引擎，零必装第三方依赖，安装器分发 + onedir 多文件应用（1.8 起）。

## ✨ 亮点

- 🪟 桌面悬浮窗：无边框、置顶、可拖动、边缘拖拽调整大小，不打扰工作流
- 🎯 单实例常驻：重复启动只唤醒已有窗口；关闭最小化到托盘；全局热键唤起（默认 Ctrl+Alt+S，设置页可改）
- 🗂️ 四象限：紧急且重要 / 紧急不重要 / 不紧急重要 / 不紧急不重要
- 🎨 九套主题：午夜玻璃、雾白冰川、霓虹网格、晨雾纸墨等，可导入自定义 CSS 主题
- 📋 日报中心：底部抽屉式日历，按日查看完成任务 / 象限统计 / 标签统计
- 📤 导出：单日或日期范围批量导出 CSV + JSON
- 🔄 自动更新：设置页一键检查 GitHub Releases 新版，下载安装包后静默覆盖升级（data.db 与主题保留）
- ⚡ 零依赖：仅 Python 标准库实现，WebView 渲染 / tkinter 回退双引擎

## 功能

- 桌面悬浮窗：无边框、置顶、可拖动、边缘拖拽调整大小
- 单实例：重复启动 / 双击 exe 只唤醒已有窗口（不重复开进程）
- 托盘常驻：关闭窗口最小化到托盘继续运行；托盘菜单「显示主窗口 / 退出」
- 全局热键：默认 Ctrl+Alt+S 随时唤起窗口（设置页可改，冲突时自动降级不崩溃）
- 四象限：紧急且重要 / 紧急不重要 / 不紧急重要 / 不紧急不重要
- 任务管理：新建、编辑、删除、多标签、跨象限拖拽、勾选归档
- 标签筛选：底部「筛选」按钮，上拉面板多选标签，实时筛选四象限任务
- 日报中心：底部抽屉式日历，按日查看完成任务 / 象限统计 / 标签统计
- 导出：单日或日期范围批量导出 CSV + JSON
- 三种窗口模式：置顶最前 / 固定桌面 / 普通窗口（系统标题栏）
- 九套内置主题，支持导入自定义 CSS 主题
- 设置自动记忆：窗口位置、锁定、主题、模式（窗口尺寸固定为 4:3）
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
│  ├─ main.py          入口（单实例判定 → webview 优先，tkinter 回退）
│  ├─ migration.py     SQLite schema 版本迁移框架（settings.schema_version）
│  ├─ single_instance.py  单实例 Mutex + 重复启动窗口唤醒
│  ├─ tray.py          托盘常驻（纯 ctypes，Win32）
│  ├─ hotkey.py        全局唤醒热键（默认 Ctrl+Alt+S，Win32）
│  ├─ webview_main.py  WebView 版：JsApi 桥 + 窗口管理 + 内置本地页面服务
│  ├─ db.py            SQLite 数据层
│  ├─ models.py        数据模型 + 四象限常量
│  ├─ report.py        日报统计与 CSV/JSON 导出
│  ├─ updater.py       GitHub Releases 检查 / 下载 / 更新
│  ├─ theme_loader.py  主题目录扫描 / 元数据 / CSS 注入
│  ├─ autostart.py     开机自启动（HKCU Run）
│  ├─ dialogs.py       tkinter 回退版对话框
│  ├─ styles.py        主题系统 + ICO 图标
│  ├─ app_icon.ico/.svg  应用图标
│  ├─ web/             UI 资源（1.8 起拆分；打包后外置安装目录，改文件即生效）
│  │  ├─ index.html    页面骨架（主题清单注入占位）
│  │  ├─ app.css       布局与主题样式（/*__THEMES_CSS__*/ 注入占位）
│  │  └─ app.js        全部业务脚本
│  ├─ widgets/         tkinter 回退版（main_widget / quadrant_card / task_item）
│  └─ data.db          SQLite 数据文件（源码运行）
├─ tests/              unittest 测试（迁移 / 系统层 / web 拆分）
├─ designs/            四套 HTML 设计方案（预览 / 参考）
├─ setup/sixiang.iss   Inno Setup 安装脚本（onedir 递归安装 + web 外置复制）
├─ run.bat             Windows 启动脚本
├─ requirements.txt    依赖说明
├─ LICENSE             MIT
└─ DESIGN.md           WebView 版改造方案文档
```

## 数据

- SQLite 单文件 `data.db`：源码运行在 `src/`，打包版在 exe 同目录；不可写时回退 `~/.quadrant_tasks/data.db`
- 导出文件默认到桌面 `~/Desktop/四象日报导出/`

## 打包

1.8 起为 onedir 多文件应用：先打 onedir 目录（`dist/SIXIANG/` = 安装内容），再打安装器（发布资产为 `SIXIANG-Setup-vX.Y.Z.exe`）：

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onedir --windowed --name SIXIANG --icon=src/app_icon.ico --add-data "src/web;web" --add-data "src/themes;themes" --add-data "src/app_icon.ico;." src/main.py
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=X.Y.Z setup\sixiang.iss
```

安装目录布局：`SIXIANG.exe` + `_internal/`（Python 运行时与内置资源兜底）+ `web/`（外置 UI 资源，可直接改文件）+ `themes/` + `data.db`。发布流程详见本地文档 `RELEASE.md`。

## 许可证

[MIT](LICENSE)
