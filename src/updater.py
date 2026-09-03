"""应用版本与自动更新（GitHub Releases）。

流程：检查最新 release → 用户确认后下载新 exe → 用户确认后替换并重启。
仅在 PyInstaller onefile 打包环境（sys.frozen）下执行替换；
源码运行时仍可检查更新，但自动替换会给出提示。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------- 版本与仓库
APP_VERSION = "1.3.25"
REPO = "fxm124578/SIXIANG-four_quadrants"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
USER_AGENT = f"Sixiang/{APP_VERSION}"
DOWNLOAD_TIMEOUT = 20

_UPDATE_DIR_NAME = ".__update__"

# 「下载完成」持久化回调：WebView 版注册后写入设置库，重启后可恢复就绪状态
_persist_ready_cb = None


def set_persist_ready_cb(cb) -> None:
    """注册下载完成回调（接收本地 exe 路径）。"""
    global _persist_ready_cb
    _persist_ready_cb = cb


def restore_ready(local_path: str) -> bool:
    """启动时恢复上次已下载但未安装的更新；文件不存在则忽略。"""
    p = Path(local_path)
    if not p.is_file():
        return False
    with _state["lock"]:
        _state["phase"] = "ready"
        _state["progress"] = 100.0
        _state["local_path"] = str(p)
    return True


def _parse_version(version: str) -> tuple:
    """'v1.2.3-beta' -> (1, 2, 3)；无法解析的段按 0 计。"""
    parts = []
    for seg in str(version).lstrip("vV").split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _github_request(url: str, timeout: int = 10):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout)


# ---------------------------------------------------------------- 检查更新
def check_for_update() -> Dict[str, Any]:
    """同步查询 GitHub 最新 release，返回结构化结果（不抛异常）。"""
    info: Dict[str, Any] = {
        "current_version": APP_VERSION,
        "latest_version": None,
        "has_update": False,
        "notes": "",
        "file_name": None,
        "download_url": None,
        "size": 0,
        "sha256": None,
        "error": None,
    }
    try:
        with _github_request(RELEASE_API) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        info["error"] = f"检查更新失败：{exc}"
        return info

    tag = str(data.get("tag_name") or "")
    info["latest_version"] = tag.lstrip("vV")
    info["notes"] = str(data.get("body") or "")
    info["has_update"] = _parse_version(tag) > _parse_version(APP_VERSION)

    if info["has_update"]:
        # 只接受发布规范约定的资产，不能因为 release 里多了调试工具或
        # 其他架构的 exe 就误下载第一个 .exe。
        expected_name = f"SIXIANG-v{info['latest_version']}.exe"
        for asset in data.get("assets", []) or []:
            name = str(asset.get("name") or "")
            if name == expected_name and asset.get("state") == "uploaded":
                info["file_name"] = name
                info["download_url"] = asset.get("browser_download_url")
                info["size"] = int(asset.get("size") or 0)
                digest = str(asset.get("digest") or "")
                if digest.startswith("sha256:"):
                    info["sha256"] = digest.removeprefix("sha256:").lower()
                break
        if not info["download_url"]:
            info["error"] = (
                f"发现新版本，但 release 中缺少 {expected_name} 更新包"
            )
    return info


# ---------------------------------------------------------------- 下载状态机
_state = {
    "phase": "idle",       # idle|checking|result|downloading|ready|applying|error
    "progress": 0.0,
    "error": None,
    "info": None,
    "local_path": None,
    "lock": threading.Lock(),
}


def _snapshot() -> Dict[str, Any]:
    with _state["lock"]:
        info = _state["info"] or {}
        return {
            "phase": _state["phase"],
            "progress": round(_state["progress"], 1),
            "error": _state["error"],
            "current_version": APP_VERSION,
            "latest_version": info.get("latest_version"),
            "has_update": bool(info.get("has_update")),
            "notes": info.get("notes") or "",
            "file_name": info.get("file_name"),
            "size": int(info.get("size") or 0),
        }


def start_check() -> Dict[str, Any]:
    """后台线程检查更新；立即返回当前状态，UI 轮询 get_state()。

    若本地已有下载好的新包（phase=ready），保持就绪状态不重复检查/下载。
    注意：持锁期间不得调用 _snapshot()（锁不可重入）。
    """
    with _state["lock"]:
        phase = _state["phase"]
        if phase not in ("ready", "checking", "downloading", "applying"):
            _state["phase"] = "checking"
            _state["progress"] = 0.0
            _state["error"] = None
            _state["info"] = None
    if phase in ("ready", "checking", "downloading", "applying"):
        return _snapshot()
    threading.Thread(target=_check_worker, daemon=True).start()
    return _snapshot()


def _check_worker() -> None:
    info = check_for_update()
    with _state["lock"]:
        if info["error"]:
            _state["phase"] = "error"
            _state["error"] = info["error"]
            _state["info"] = None
        else:
            _state["phase"] = "result"
            _state["info"] = info


def get_state() -> Dict[str, Any]:
    return _snapshot()


def _exe_dir() -> Path:
    """打包后 exe 所在目录；源码运行时用当前目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _update_dir() -> Path:
    return _exe_dir() / _UPDATE_DIR_NAME


def start_download() -> Dict[str, Any]:
    """后台线程下载已确认的新版 exe；UI 轮询 get_state() 看进度。"""
    with _state["lock"]:
        phase = _state["phase"]
        info = _state["info"]
        url = info.get("download_url") if info else None
        if phase != "result" or not url:
            return _snapshot_locked()
        name = info["file_name"] or "update.exe"
        _state["phase"] = "downloading"
        _state["progress"] = 0.0
        _state["error"] = None
    threading.Thread(
        target=_download_worker,
        args=(url, name, int(info.get("size") or 0), info.get("sha256")),
        daemon=True,
    ).start()
    return _snapshot()


def _snapshot_locked() -> Dict[str, Any]:
    """仅在已持有 _state['lock'] 时调用：构造快照而不重复加锁。"""
    info = _state["info"] or {}
    return {
        "phase": _state["phase"],
        "progress": round(_state["progress"], 1),
        "error": _state["error"],
        "current_version": APP_VERSION,
        "latest_version": info.get("latest_version"),
        "has_update": bool(info.get("has_update")),
        "notes": info.get("notes") or "",
        "file_name": info.get("file_name"),
        "size": int(info.get("size") or 0),
    }


def _download_file(url: str, name: str, expected_size: int = 0,
                   expected_sha256: str | None = None):
    """下载到程序目录 .__update__，返回 (ok, 本地路径或错误信息)。

    下载过程中更新 _state 进度；供 WebView（后台线程）与 tkinter（同步）复用。
    """
    tmp_path = None
    try:
        if Path(name).name != name or not name.lower().endswith(".exe"):
            raise ValueError("更新包文件名无效")
        if expected_size < 1:
            raise ValueError("更新包大小无效")
        update_dir = _update_dir()
        update_dir.mkdir(parents=True, exist_ok=True)
        # 校验目标 exe 所在目录可写（exe 同目录替换需要写权限）
        target_dir = _exe_dir()
        if not os.access(str(target_dir), os.W_OK):
            raise PermissionError("程序目录不可写，无法自动更新（请以管理员身份运行）")

        total = 0
        written = 0
        hasher = hashlib.sha256()
        with _github_request(url, timeout=DOWNLOAD_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            tmp_path = update_dir / f"{name}.part"
            with open(tmp_path, "wb") as fh:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    hasher.update(chunk)
                    written += len(chunk)
                    if total:
                        with _state["lock"]:
                            _state["progress"] = written / total * 100
        if total and written != total:
            raise OSError(f"下载不完整：应为 {total} 字节，实际 {written} 字节")
        if written != expected_size:
            raise OSError(
                f"下载大小校验失败：应为 {expected_size} 字节，实际 {written} 字节"
            )
        actual_sha256 = hasher.hexdigest()
        if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
            raise OSError("下载校验失败：SHA-256 不匹配")
        # 防止代理返回 HTML 错误页却恰好满足其他异常条件。
        with open(tmp_path, "rb") as fh:
            if fh.read(2) != b"MZ":
                raise OSError("下载校验失败：文件不是 Windows 可执行程序")

        local_path = update_dir / name
        tmp_path.replace(local_path)
        return True, str(local_path)
    except Exception as exc:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        return False, str(exc)


def _download_worker(url: str, name: str, expected_size: int,
                     expected_sha256: str | None) -> None:
    ok, result = _download_file(url, name, expected_size, expected_sha256)
    with _state["lock"]:
        if ok:
            _state["phase"] = "ready"
            _state["progress"] = 100.0
            _state["local_path"] = result
        else:
            _state["phase"] = "error"
            _state["error"] = f"下载失败：{result}"
            _state["progress"] = 0.0
    if ok and _persist_ready_cb:
        try:
            _persist_ready_cb(result)
        except Exception:
            pass


# ---------------------------------------------------------------- 应用更新
def apply_update() -> Dict[str, Any]:
    """用户确认后：写替换脚本 → 启动脚本 → 退出当前程序。"""
    with _state["lock"]:
        if _state["phase"] != "ready" or not _state["local_path"]:
            return {"ok": False, "error": "没有已下载的更新文件"}
        phase_bak = _state["phase"]
        local_path = Path(_state["local_path"])
        _state["phase"] = "applying"

    if not getattr(sys, "frozen", False):
        with _state["lock"]:
            _state["phase"] = phase_bak
        return {"ok": False, "error": "源码运行版不支持自动替换，请重新克隆仓库运行"}

    try:
        _launch_replace_script(local_path)
    except Exception as exc:
        with _state["lock"]:
            _state["phase"] = "error"
            _state["error"] = f"启动更新失败：{exc}"
        return {"ok": False, "error": str(exc)}

    # 统一 SIXIANG 命名：若已开启自启动，把注册表指向新 exe 路径
    try:
        import autostart
        autostart.set_exe_path(str(_exe_dir() / "SIXIANG.exe"))
    except Exception:
        pass

    # 替换脚本会等旧进程退出后替换 exe；这里安排本进程尽快退出
    threading.Thread(target=_delayed_exit, daemon=True).start()
    return {"ok": True, "restarting": True}


def _vbs_string(value: Path | str) -> str:
    """返回可嵌入 VBScript 双引号字符串的文本。"""
    return str(value).replace('"', '""')


def _launch_replace_script(local_path: Path) -> None:
    """启动独立的更新助手：等旧进程退出 → 备份 → 替换 → 重启。

    更新助手必须脱离正在被替换的 exe；这里使用 Windows 自带的 WScript，
    但不再通过 cmd/bat、进程名强杀或删除 ``%TEMP%\\_MEI*``。PyInstaller
    的 onefile 运行目录是每个进程独有的，删除它会误伤其他进程，也会让
    正在解压的新进程找不到 python3xx.dll。
    """
    update_dir = _update_dir()
    update_dir.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    target_path = _exe_dir() / "SIXIANG.exe"
    backup_path = _exe_dir() / "SIXIANG.exe.bak"
    log_path = update_dir / "update.log"

    # 所有文本仅来自本地绝对路径和 PID；路径由 VBScript 字符串转义，支持中文目录。
    vbs_lines = [
        "Option Explicit",
        "Dim fso, shell, pid, staged, target, backup, logPath, i",
        "Set fso = CreateObject(\"Scripting.FileSystemObject\")",
        "Set shell = CreateObject(\"WScript.Shell\")",
        f"pid = {pid}",
        f'staged = "{_vbs_string(local_path)}"',
        f'target = "{_vbs_string(target_path)}"',
        f'backup = "{_vbs_string(backup_path)}"',
        f'logPath = "{_vbs_string(log_path)}"',
        "LogLine \"start\"",
        "For i = 1 To 120",
        "  If Not IsRunning(pid) Then Exit For",
        "  WScript.Sleep 250",
        "Next",
        "If IsRunning(pid) Then",
        "  LogLine \"failed: old process did not exit\"",
        "  WScript.Quit 1",
        "End If",
        "For i = 1 To 60",
        "  If InstallUpdate() Then Exit For",
        "  WScript.Sleep 500",
        "Next",
        "If Not fso.FileExists(target) Then",
        "  LogLine \"failed: replacement did not produce target\"",
        "  WScript.Quit 1",
        "End If",
        "LogLine \"launching updated app\"",
        "shell.Run Chr(34) & target & Chr(34), 1, False",
        "For i = 1 To 48",
        "  If IsImageRunning(\"SIXIANG.exe\") Then",
        "    LogLine \"updated app started\"",
        "    WScript.Quit 0",
        "  End If",
        "  WScript.Sleep 250",
        "Next",
        "LogLine \"updated app did not stay running; attempting rollback\"",
        "If fso.FileExists(backup) Then",
        "  On Error Resume Next",
        "  If fso.FileExists(target) Then fso.DeleteFile target, True",
        "  fso.MoveFile backup, target",
        "  If Err.Number = 0 Then",
        "    LogLine \"rollback complete; launching backup\"",
        "    shell.Run Chr(34) & target & Chr(34), 1, False",
        "  Else",
        "    LogLine \"rollback failed: \" & Err.Description",
        "  End If",
        "  On Error GoTo 0",
        "End If",
        "WScript.Quit 1",
        "",
        "Function IsRunning(processId)",
        "  Dim service, processes",
        "  On Error Resume Next",
        "  Set service = GetObject(\"winmgmts:\\\\.\\root\\cimv2\")",
        "  Set processes = service.ExecQuery(\"Select ProcessId from Win32_Process Where ProcessId = \" & processId)",
        "  IsRunning = (Err.Number = 0 And processes.Count > 0)",
        "  Err.Clear",
        "  On Error GoTo 0",
        "End Function",
        "",
        "Function IsImageRunning(imageName)",
        "  Dim service, processes",
        "  On Error Resume Next",
        "  Set service = GetObject(\"winmgmts:\\\\.\\root\\cimv2\")",
        "  Set processes = service.ExecQuery(\"Select Name from Win32_Process Where Name = '\" & imageName & \"'\")",
        "  IsImageRunning = (Err.Number = 0 And processes.Count > 0)",
        "  Err.Clear",
        "  On Error GoTo 0",
        "End Function",
        "",
        "Function InstallUpdate()",
        "  On Error Resume Next",
        "  InstallUpdate = False",
        "  If Not fso.FileExists(staged) Then",
        "    LogLine \"failed: staged package missing\"",
        "    Exit Function",
        "  End If",
        "  If fso.FileExists(target) Then",
        "    If fso.FileExists(backup) Then fso.DeleteFile backup, True",
        "    fso.MoveFile target, backup",
        "    If Err.Number <> 0 Then",
        "      LogLine \"replace retry: cannot back up current executable: \" & Err.Description",
        "      Err.Clear",
        "      Exit Function",
        "    End If",
        "  End If",
        "  fso.MoveFile staged, target",
        "  If Err.Number <> 0 Then",
        "    LogLine \"replace retry: cannot install new executable: \" & Err.Description",
        "    Err.Clear",
        "    If Not fso.FileExists(target) And fso.FileExists(backup) Then fso.MoveFile backup, target",
        "    Exit Function",
        "  End If",
        "  InstallUpdate = True",
        "  LogLine \"replacement complete; backup kept as SIXIANG.exe.bak\"",
        "  On Error GoTo 0",
        "End Function",
        "",
        "Sub LogLine(message)",
        "  Dim logFile",
        "  On Error Resume Next",
        "  Set logFile = fso.OpenTextFile(logPath, 8, True, -1)",
        "  logFile.WriteLine Now & \" \" & message",
        "  logFile.Close",
        "  On Error GoTo 0",
        "End Sub",
    ]
    vbs_path = update_dir / "apply_update.vbs"
    # WScript 对 UTF-8（无 BOM）的识别依赖系统代码页；UTF-16 自带 BOM，
    # 可以稳定承载用户可能存在的中文安装路径。
    vbs_path.write_text("\r\n".join(vbs_lines), encoding="utf-16")
    os.startfile(str(vbs_path))


def _delayed_exit() -> None:
    import time
    time.sleep(0.8)
    try:
        os._exit(0)
    except Exception:
        pass


def cleanup_legacy_exes() -> None:
    """统一 SIXIANG 命名后：若已存在 SIXIANG.exe（新命名已生效），
    删除历史遗留的中文名 exe，避免用户误开旧版本。仅在打包环境执行。
    """
    if not getattr(sys, "frozen", False):
        return
    exe_dir = Path(sys.executable).resolve().parent
    current = Path(sys.executable).resolve()
    target = exe_dir / "SIXIANG.exe"
    if not target.is_file():
        return
    for legacy in ("四象.exe", "SIXIANG.previous.exe"):
        p = exe_dir / legacy
        if p.is_file() and p.resolve() != current:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------- 便捷入口
def download_now(url: str, name: str, expected_size: int = 0,
                 expected_sha256: str | None = None):
    """同步下载更新文件；返回 (ok, 路径或错误信息)。

    供 tkinter 回退版等简单场景使用（无进度回调）。
    """
    ok, result = _download_file(url, name, expected_size, expected_sha256)
    if ok:
        with _state["lock"]:
            _state["phase"] = "ready"
            _state["progress"] = 100.0
            _state["local_path"] = result
    return ok, result
