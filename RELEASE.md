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
   python -m PyInstaller --noconfirm --clean --onefile --windowed --name SIXIANG --icon=src/app_icon.ico --add-data "src/web;web" --add-data "src/app_icon.ico;." src/main.py
   ```
   产物：`dist/SIXIANG.exe`

5. **复制 ASCII 资产名**
   `cp dist/SIXIANG.exe dist/SIXIANG-vX.Y.Z.exe`

6. **创建 Release**
   ```
   gh release create vX.Y.Z "dist/SIXIANG-vX.Y.Z.exe" --title "vX.Y.Z" --notes "..."
   ```

7. **验证**
   - 升级链路：临时将 `updater.APP_VERSION` 设为旧版本，`check_for_update()` 应发现新版本并定位 `SIXIANG-vX.Y.Z.exe`
   - exe 冒烟：启动 `dist/SIXIANG.exe`，确认主窗口出现、`data.db` 生成在 exe 同目录

## 命名与编码约定

- 应用文件名**统一 SIXIANG**（英文名，避免中文文件名乱码）：
  - 打包名：`SIXIANG.exe`
  - Release 资产：`SIXIANG-vX.Y.Z.exe`（必须 ASCII，中文名会被 GitHub 强制替换为 default.exe）
  - 应用内自动更新替换目标固定：`SIXIANG.exe`（update.bat 全 ASCII 硬编码目标名，与系统代码页无关）
- 开机自启动注册表值名：`SIXIANG`（HKCU\Software\Microsoft\Windows\CurrentVersion\Run）
- 窗口标题仍为「四象」（中文产品名）
- update.bat 由 `src/updater.py::_launch_replace_script` 生成：纯 ASCII，用 PID 结束旧进程，等旧进程退出后替换并重启
