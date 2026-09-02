"""应用版本与自动更新（GitHub Releases）。

流程：检查最新 release → 用户确认后下载新 exe → 用户确认后替换并重启。
仅在 PyInstaller onefile 打包环境（sys.frozen）下执行替换；
源码运行时仍可检查更新，但自动替换会给出提示。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------- 版本与仓库
APP_VERSION = "1.3.20"
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
        for asset in data.get("assets", []) or []:
            name = str(asset.get("name") or "")
            if name.lower().endswith(".exe"):
                info["file_name"] = name
                info["download_url"] = asset.get("browser_download_url")
                info["size"] = int(asset.get("size") or 0)
                break
        if not info["download_url"]:
            info["error"] = "发现新版本，但 release 中没有可下载的 exe 文件"
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
    threading.Thread(target=_download_worker, args=(url, name), daemon=True).start()
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


def _download_file(url: str, name: str):
    """下载到程序目录 .__update__，返回 (ok, 本地路径或错误信息)。

    下载过程中更新 _state 进度；供 WebView（后台线程）与 tkinter（同步）复用。
    """
    tmp_path = None
    try:
        update_dir = _update_dir()
        update_dir.mkdir(parents=True, exist_ok=True)
        # 校验目标 exe 所在目录可写（exe 同目录替换需要写权限）
        target_dir = _exe_dir()
        if not os.access(str(target_dir), os.W_OK):
            raise PermissionError("程序目录不可写，无法自动更新（请以管理员身份运行）")

        total = 0
        written = 0
        with _github_request(url, timeout=DOWNLOAD_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            tmp_path = update_dir / f"{name}.part"
            with open(tmp_path, "wb") as fh:
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    if total:
                        with _state["lock"]:
                            _state["progress"] = written / total * 100
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


def _download_worker(url: str, name: str) -> None:
    ok, result = _download_file(url, name)
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


def _launch_replace_script(local_path: Path) -> None:
    """生成并启动 update.bat：等旧进程退出 → 替换 exe → 启动新版本。

    重命名目标固定为 ASCII 的「SIXIANG.exe」（与当前 exe 名、release 资产名
    无关），保证开机自启等依赖固定路径/名称的机制始终有效；bat 内容保持纯
    ASCII，任何代码页下解析一致，彻底避免中文文件名乱码问题。
    结束旧进程改用 PID，不依赖进程映像名。
    """
    update_dir = _update_dir()
    update_dir.mkdir(parents=True, exist_ok=True)
    new_name = local_path.name  # release 资产名为 ASCII，如 SIXIANG-v1.3.6.exe
    pid = os.getpid()

    bat_lines = [
        "@echo off",
        'set LOG=%~dp0..\\update.log',
        'echo [%date% %time%] start >> "%LOG%"',
        'cd /d "%~dp0"',
        "ping -n 3 127.0.0.1 >nul",
        'echo kill-old >> "%LOG%"',
        f"taskkill /f /pid {pid} >nul 2>&1",
        "ping -n 2 127.0.0.1 >nul",
        # 清理可能残留的 SIXIANG 实例，避免旧进程占用导致 move 失败
        "taskkill /f /im SIXIANG.exe >nul 2>&1",
        "ping -n 2 127.0.0.1 >nul",
        'echo move >> "%LOG%"',
        f'move /y "%~dp0{new_name}" "%~dp0..\\SIXIANG.exe" >nul',
        "if errorlevel 1 goto :fail",
        # 替换后等约 1 秒再启动：给杀软实时扫描/文件系统稳定时间
        "ping -n 2 127.0.0.1 >nul",
        # 清理 Temp 残留的 PyInstaller 解压目录：多次强杀/更新后残留 _MEI*，
        # Windows PID 复用时新进程解压到同名残留目录导致 python DLL 加载失败
        'for /d %%d in ("%TEMP%\\_MEI*") do rd /s /q "%%d" >nul 2>&1',
        'echo start-1 >> "%LOG%"',
        # /d 指定新进程起始目录为 exe 同目录，避免其 cwd 落在 __update__ 导致清理失败
        'start "" /d "%~dp0.." "%~dp0..\\SIXIANG.exe"',
        # 双段观察：6 秒后检查存活，若存活再过 4 秒二次确认，
        # 避免“进程仍在解压/加载中但即将失败”被误判为成功；中途退出则重试
        "ping -n 7 127.0.0.1 >nul",
        'tasklist /fi "imagename eq SIXIANG.exe" | findstr /i "SIXIANG.exe" >nul',
        "if errorlevel 1 goto :retry",
        "ping -n 5 127.0.0.1 >nul",
        'tasklist /fi "imagename eq SIXIANG.exe" | findstr /i "SIXIANG.exe" >nul',
        "if errorlevel 1 goto :retry",
        "goto :done",
        ":retry",
        'echo retry >> "%LOG%"',
        "ping -n 3 127.0.0.1 >nul",
        'for /d %%d in ("%TEMP%\\_MEI*") do rd /s /q "%%d" >nul 2>&1',
        'start "" /d "%~dp0.." "%~dp0..\\SIXIANG.exe"',
        ":done",
        'echo ok >> "%LOG%"',
        # bat 流式读取：自删须放最后一行。__update__ 空目录残留无害（下次更新复用）；
        # 日志删除 + bat 自删保证更新目录只剩空壳
        "cd ..",
        'del "%LOG%" >nul 2>&1',
        '(goto) 2>nul & del "%~f0"',
        ":fail",
        'echo fail >> "%LOG%"',
        "ping -n 6 127.0.0.1 >nul",
        "exit /b 1",
    ]
    bat_path = update_dir / "update.bat"
    # 全 ASCII 内容，任何代码页下解析一致，无需 chcp / GBK
    bat_path.write_text("\r\n".join(bat_lines), encoding="ascii")

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        cwd=str(update_dir),
        creationflags=creation_flags,
        close_fds=True,
    )


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
    for legacy in ("四象.exe",):
        p = exe_dir / legacy
        if p.is_file() and p.resolve() != current:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------- 便捷入口
def download_now(url: str, name: str):
    """同步下载更新文件；返回 (ok, 路径或错误信息)。

    供 tkinter 回退版等简单场景使用（无进度回调）。
    """
    ok, result = _download_file(url, name)
    if ok:
        with _state["lock"]:
            _state["phase"] = "ready"
            _state["progress"] = 100.0
            _state["local_path"] = result
    return ok, result