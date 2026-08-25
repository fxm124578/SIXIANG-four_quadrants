# 四象

四象限桌面任务管理小组件 —— 悬浮窗 + 四套主题 + WebView / tkinter 双引擎。

## 功能

- 桌面悬浮窗：无边框、置顶、可拖动、边缘拖拽调整大小
- 四象限：紧急且重要 / 紧急不重要 / 不紧急重要 / 不紧急不重要
- 任务管理：新建、编辑、删除、多标签、跨象限拖拽、勾选归档
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
python main.py
```

Windows 也可双击 `run.bat`（自动优先 `pythonw`，无控制台窗口）。

若未安装 pywebview，`main.py` 会自动回退到 tkinter 版（零依赖，视觉近似）。

## 目录结构

```
├─ main.py              入口（webview 优先，tkinter 回退）
├─ webview_main.py      WebView 版：JsApi 桥 + 窗口管理
├─ web/app.html         单页应用：四套主题 + 全部功能
├─ db.py                SQLite 数据层
├─ models.py            数据模型 + 四象限常量
├─ report.py            日报统计与 CSV/JSON 导出
├─ widgets/             tkinter 回退版（main_widget / quadrant_card / task_item）
├─ dialogs.py           tkinter 回退版对话框
├─ styles.py            主题系统 + ICO 图标
├─ designs/             四套 HTML 设计方案（预览 / 参考）
├─ app_icon.svg         应用图标源文件
├─ run.bat              Windows 启动脚本
├─ LICENSE              MIT
└─ DESIGN.md            WebView 版改造方案文档
```

## 数据

- SQLite 单文件 `data.db`，默认在程序目录，不可写时回退 `~/.quadrant_tasks/data.db`
- 导出文件默认到桌面 `~/Desktop/四象日报导出/`

## 打包

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=app_icon.ico main.py
```

## 许可证

[MIT](LICENSE)
