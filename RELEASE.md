# 发布流程（SIXIANG · 四象）

本文档固定四象（SIXIANG）的版本发布流程，每次发版严格按此执行。
AGENTS.md 通过 `@RELEASE.md` 引用本文档。

## 版本号

- 唯一维护点：`src/updater.py` 的 `APP_VERSION`（如 `"1.3.6"`）
- `src/web/app.html` 无硬编码版本号：顶部小字显示时钟，版本号仅在设置页从 API 读取，无需同步

## 发布步骤

1. **bump 版本号**
   `src/updater.py`: `APP_VERSION = "X.Y.Z"`（按补丁/特性递增）

2. **编译检查**
   `python -m py_compile src/*.py src/widgets/*.py`

3. **提交并打 tag**
   ```
   git add -A
   git commit -m "chore: bump vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```

4. **打包**
   ```
   python -m PyInstaller --noconfirm --clean --onefile --windowed --name SIXIANG --icon=src/app_icon.ico --add-data "src/web;web" --add-data "src/themes;themes" --add-data "src/app_icon.ico;." src/main.py
   ```
   产物：`dist/SIXIANG.exe`

5. **复制 ASCII 资产名**
   `cp dist/SIXIANG.exe dist/SIXIANG-vX.Y.Z.exe`

6. **创建 Release**
   ```
   gh release create vX.Y.Z "dist/SIXIANG-vX.Y.Z.exe" --title "vX.Y.Z" --notes "..."
   ```

7. **验证**
   - 升级链路：临时将 `updater.APP_VERSION` 设为旧版本，`check_for_update()` 应发现新版本并**仅**定位 `SIXIANG-vX.Y.Z.exe`；确认 API 返回的资产 `size` 与 `digest`（`sha256:`）均存在。
   - 更新替换：在独立测试目录放一份旧版 `SIXIANG.exe`，完成下载后点击重启更新；确认新版启动、旧版保留为 `SIXIANG.previous.exe`，并检查 `.__update__/update.log` 无失败记录。
   - exe 冒烟：启动 `dist/SIXIANG.exe`，确认主窗口出现、`data.db` 生成在 exe 同目录

## 命名与编码约定

- 应用文件名**统一 SIXIANG**（英文名，避免中文文件名乱码）：
  - 打包名：`SIXIANG.exe`
  - Release 资产：`SIXIANG-vX.Y.Z.exe`（必须 ASCII，中文名会被 GitHub 强制替换为 default.exe）
  - 应用内自动更新替换目标固定：`SIXIANG.exe`；更新助手使用 UTF-16 编码的 `apply_update.vbs`，支持中文安装路径。
- 开机自启动注册表值名：`SIXIANG`（HKCU\Software\Microsoft\Windows\CurrentVersion\Run）
- 窗口标题仍为「四象」（中文产品名）
- `apply_update.vbs` 由 `src/updater.py::_launch_replace_script` 生成：仅等待旧 PID 自行退出，不按进程名强杀、不删除 PyInstaller 的 `%TEMP%\\_MEI*` 目录；替换前保留 `SIXIANG.previous.exe`，新版未能维持启动时自动回滚。

## 主题可插拔（快速安装）

- 主题目录：应用目录 `themes/`（打包 = exe 同目录；源码 = 项目根），首次启动自动从内置复制全部内置主题
- 单文件 = 单主题：`<主题id>.css`（ASCII 文件名），头部 `/*!` 注释提供 `id/name/desc/default`
- 快速安装：把 `.css` 丢进 `themes/` 重启即生效（或设置 → 主题外观 →「导入主题」文件选择器）
- 卸载：删除对应 `.css`；当前主题文件丢失时自动回归默认「晨雾纸墨」
- 内置兜底：`src/themes/`（打包进 exe），用户目录缺失自动补回，同名用户文件优先
- 回退版配色：主题 CSS 内 `--tk-*` 变量（tkinter 回退版用）；新主题可只写 WebView 样式，回退版仍用默认色
