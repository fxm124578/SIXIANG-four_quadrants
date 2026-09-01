# AGENTS.md — 四象（Four Quadrants）

Windows 桌面四象限任务管理小组件。无边框悬浮窗 + 四套主题 + WebView/tkinter 双引擎，纯 Python 标准库实现，单文件 exe 分发，GitHub Releases 自动更新。

## 目录结构

```
src/                  应用源码
  main.py             入口：优先 pywebview，失败回退 tkinter
  webview_main.py     WebView 版：JsApi 桥 + 窗口管理
  db.py               SQLite 数据层
  models.py           数据模型 + 四象限常量（Task.to_dict 统一序列化）
  report.py           日报统计与 CSV/JSON 导出
  updater.py          版本号 APP_VERSION + GitHub Releases 检查/下载/替换
  dialogs.py          tkinter 回退版对话框（safe_messagebox 支持 askyesno）
  styles.py           主题系统 + ICO 图标
  web/app.html        WebView 单页应用（设置/日报均为底部抽屉）
  widgets/            tkinter 回退版组件
  app_icon.ico/.svg   应用图标（打包必需，已入库）
designs/              四套 HTML 设计参考（非运行资源）
run.bat               Windows 启动脚本
RELEASE.md            版本发布流程（打包/tag/release 验证）
README.md / DESIGN.md / LICENSE / requirements.txt
```

## 命令

- 运行：`python src\main.py` 或双击 `run.bat`（优先 pythonw）
- 编译检查：`python -m py_compile src/*.py src/widgets/*.py`
- 打包：`python -m PyInstaller --noconfirm --clean --onefile --windowed --name SIXIANG --icon=src/app_icon.ico --add-data "src/web;web" --add-data "src/app_icon.ico;." src/main.py`
- 发布流程：@RELEASE.md

## 验证

- 启动冒烟：启动 exe 或 `python src\main.py`，确认主窗口出现、`data.db` 生成在 exe 同目录
- 发布前验证升级链路：临时将 `updater.APP_VERSION` 设为旧版本，`check_for_update()` 应发现新版本并定位 exe 资产

## 项目边界与关键决策

- 零第三方依赖（仅标准库）；pywebview 可选（WebView 版），缺失自动回退 tkinter
- 数据库：源码模式 `src/data.db`；打包模式 exe 同目录 `data.db`。onefile 下 `__file__` 指向临时解压目录，禁止用于数据落盘（用 `sys.executable`）
- 数据/产物不提交：`data.db`、`build/`、`dist/`、`*.spec`（见 .gitignore）
- 自动更新：update.bat（纯 ASCII，由 `updater.py::_launch_replace_script` 生成）等旧进程退出后替换 exe 为 `SIXIANG.exe` 并重启
- GitHub 资产名必须 ASCII：`SIXIANG-vX.Y.Z.exe`（中文名会被平台强制替换为 default.exe）
- 远端：https://github.com/fxm124578/SIXIANG-four_quadrants（公开），tag 与 release 一一对应

## 关键文档索引

- `README.md`：功能、快速开始、目录结构、打包命令
- `DESIGN.md`：WebView 版改造方案文档
- `designs/`：四套主题 HTML 设计参考
- `RELEASE.md`：版本发布流程（@RELEASE.md 引用）
