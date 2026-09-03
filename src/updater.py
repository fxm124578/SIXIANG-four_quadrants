"""应用版本与自动更新（GitHub Releases）。

流程：检查最新 release → 下载 Setup → 退出应用 → 安装器覆盖当前目录并启动。
仅在 PyInstaller onefile 打包环境（sys.frozen）下执行；源码运行可检查更新。
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
APP_VERSION = "1.3.29"
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
        expected_name = f"SIXIANG-Setup-v{info['latest_version']}.exe"
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
    """安装目录：打包后为 SIXIANG.exe 所在目录（从 .__update__ 启动时取其父目录）。"""
    if getattr(sys, "frozen", False):
        from theme_loader import app_dir
        return app_dir()
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
    """用户确认后：拉起已下载的 Setup，本进程退出，由安装器覆盖并启动。"""
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

    if "Setup" not in local_path.name:
        with _state["lock"]:
            _state["phase"] = "error"
            _state["error"] = "更新包不是安装器"
        return {"ok": False, "error": "更新包不是安装器"}

    try:
        _launch_replace_script(local_path)
    except Exception as exc:
        with _state["lock"]:
            _state["phase"] = "error"
            _state["error"] = f"启动更新失败：{exc}"
        return {"ok": False, "error": str(exc)}

    threading.Thread(target=_delayed_exit, daemon=True).start()
    return {"ok": True, "restarting": True}


def _vbs_string(value: Path | str) -> str:
    """返回可嵌入 VBScript 双引号字符串的文本。"""
    return str(value).replace('"', '""')


def _launch_replace_script(local_path: Path) -> None:
    """等旧进程退出后，静默运行 Setup，安装目录为当前安装目录。"""
    update_dir = _update_dir()
    update_dir.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    install_dir = _exe_dir()
    lock_path = update_dir / "apply.lock"
    log_path = update_dir / "update.log"
    setup_log = update_dir / "setup.log"

    vbs_lines = [
        "Option Explicit",
        "Dim fso, shell, pid, staged, installDir, lockPath, logPath, setupLog, cmd, i",
        "Set fso = CreateObject(\"Scripting.FileSystemObject\")",
        "Set shell = CreateObject(\"WScript.Shell\")",
        f"pid = {pid}",
        f'staged = "{_vbs_string(local_path)}"',
        f'installDir = "{_vbs_string(install_dir)}"',
        f'lockPath = "{_vbs_string(lock_path)}"',
        f'logPath = "{_vbs_string(log_path)}"',
        f'setupLog = "{_vbs_string(setup_log)}"',
        "If Not AcquireLock() Then",
        "  WScript.Quit 0",
        "End If",
        "LogLine \"start\"",
        "For i = 1 To 120",
        "  If Not IsRunning(pid) Then Exit For",
        "  WScript.Sleep 250",
        "Next",
        "If IsRunning(pid) Then",
        "  LogLine \"failed: old process did not exit\"",
        "  ReleaseLock",
        "  WScript.Quit 1",
        "End If",
        "If Not fso.FileExists(staged) Then",
        "  LogLine \"failed: setup package missing\"",
        "  ReleaseLock",
        "  WScript.Quit 1",
        "End If",
        "LogLine \"launching setup\"",
        "shell.CurrentDirectory = installDir",
        "cmd = Chr(34) & staged & Chr(34) & \" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES /DIR=\" & Chr(34) & installDir & Chr(34) & \" /LOG=\" & Chr(34) & setupLog & Chr(34)",
        "shell.Run cmd, 1, False",
        "LogLine \"setup started\"",
        "ReleaseLock",
        "WScript.Quit 0",
        "",
        "Function AcquireLock()",
        "  On Error Resume Next",
        "  If fso.FileExists(lockPath) Then",
        "    If DateDiff(\"s\", fso.GetFile(lockPath).DateLastModified, Now) > 120 Then",
        "      fso.DeleteFile lockPath, True",
        "    End If",
        "  End If",
        "  Err.Clear",
        "  Dim lockFile",
        "  Set lockFile = fso.CreateTextFile(lockPath, False)",
        "  If Err.Number <> 0 Then",
        "    LogLine \"another updater running\"",
        "    AcquireLock = False",
        "    Err.Clear",
        "    On Error GoTo 0",
        "    Exit Function",
        "  End If",
        "  lockFile.WriteLine CStr(pid)",
        "  lockFile.Close",
        "  AcquireLock = True",
        "  On Error GoTo 0",
        "End Function",
        "",
        "Sub ReleaseLock()",
        "  On Error Resume Next",
        "  If fso.FileExists(lockPath) Then fso.DeleteFile lockPath, True",
        "  On Error GoTo 0",
        "End Sub",
        "",
        "Function IsRunning(processId)",
        "  Dim rc",
        "  rc = shell.Run(\"cmd /c tasklist /FI \"\"PID eq \" & CStr(processId) & \"\"\" /NH | find /I \"\"SIXIANG.exe\"\"\", 0, True)",
        "  IsRunning = (rc = 0)",
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
    vbs_path.write_text("\r\n".join(vbs_lines) + "\r\n", encoding="utf-16", newline="")
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
    exe_dir = _exe_dir()
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
