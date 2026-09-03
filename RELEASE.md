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

4. **打包主程序**
   ```
   python -m PyInstaller --noconfirm --clean --onefile --windowed --name SIXIANG --icon=src/app_icon.ico --add-data "src/web;web" --add-data "src/themes;themes" --add-data "src/app_icon.ico;." src/main.py
   ```
   产物：`dist/SIXIANG.exe`（安装器的内部载荷，一般不单独发）

5. **打安装包**
   ```
   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DMyAppVersion=X.Y.Z setup\sixiang.iss
   ```
   产物：`dist/SIXIANG-Setup-vX.Y.Z.exe`

6. **创建 Release**
   ```
   gh release create vX.Y.Z "dist/SIXIANG-Setup-vX.Y.Z.exe" --title "vX.Y.Z" --notes "..."
   ```

7. **验证**
   - 升级链路：临时将 `updater.APP_VERSION` 设为旧版本，`check_for_update()` 应发现新版本并**仅**定位 `SIXIANG-Setup-vX.Y.Z.exe`；确认 API 返回的资产 `size` 与 `digest`（`sha256:`）均存在。
   - 更新安装：在独立测试目录放一份旧版，完成下载后点击重启更新；应拉起 Setup，`/DIR` 为该测试目录，安装完成后启动新版，且 `data.db` 仍在。
   - 冒烟：安装或启动后主窗口出现、`data.db` 生成在安装目录

## 命名与编码约定

- 应用内部文件名 **SIXIANG.exe**；产品名「四象」
- Release 资产：`SIXIANG-Setup-vX.Y.Z.exe`（必须 ASCII）
- 应用内更新：下载 Setup → 退出 → 安装器静默安装到**当前安装目录**（`/DIR`）并启动；不覆盖 `data.db`
- 助手 `apply_update.vbs` 为 UTF-16，支持中文安装路径；等旧 PID 退出后再跑 Setup
- 开机自启动注册表值名：`SIXIANG`（HKCU\Software\Microsoft\Windows\CurrentVersion\Run）
- 窗口标题仍为「四象」

## 主题可插拔（快速安装）

- 主题目录：应用目录 `themes/`（打包 = exe 同目录；源码 = 项目根），首次启动自动从内置复制全部内置主题
- 单文件 = 单主题：`<主题id>.css`（ASCII 文件名），头部 `/*!` 注释提供 `id/name/desc/default`
- 快速安装：把 `.css` 丢进 `themes/` 重启即生效（或设置 → 主题外观 →「导入主题」文件选择器）
- 卸载：删除对应 `.css`；当前主题文件丢失时自动回归默认「晨雾纸墨」
- 内置兜底：`src/themes/`（打包进 exe），用户目录缺失自动补回，同名用户文件优先
- 回退版配色：主题 CSS 内 `--tk-*` 变量（tkinter 回退版用）；新主题可只写 WebView 样式，回退版仍用默认色
