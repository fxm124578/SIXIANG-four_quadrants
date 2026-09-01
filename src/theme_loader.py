"""主题加载器：themes 目录扫描、元数据解析与 CSS 注入数据。

主题插拔约定：
- 一个 ``.css`` 文件 = 一个主题，文件名即主题 id（ASCII，如 ``paper.css``）。
- 文件头部 ``/*!`` 注释块提供元数据：id / name / desc / default。
- ``body.<id>{...}`` 为该主题全部样式（自包含，不依赖其他主题）。
- ``--tk-*`` CSS 变量为 tkinter 回退版配色（可选，缺失则回退默认主题配色）。
- 应用目录 ``themes/`` 为用户层主题目录（快速安装：丢文件即可）；
  源码内置 ``src/themes/`` 为兜底（用户目录缺失时补回，同名文件用户优先）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 内置主题目录：源码 = src/themes；打包后 = _MEIPASS/themes
BUILTIN_DIR = Path(__file__).resolve().parent / "themes"

DEFAULT_THEME = "paper"

# 最后兜底配色（仅当 themes 目录完全缺失时使用；与 paper.css 的 --tk-* 一致）
FALLBACK_TK_COLORS = {
    "name": "晨雾纸墨", "desc": "暖米纸张质感，朱砂印章点缀",
    "bg": "#e8e0cc", "card": "#fbf6e8", "panel": "#f3ecd9",
    "panel2": "#ede4cd", "row_bg": "#fdf8ea", "row_hover": "#ffffff",
    "row_active": "#f5edd8", "text": "#3d3a33", "title_text": "#2c2a24",
    "muted": "#9a927e", "secondary": "#8d856f", "border": "#d8cfb4",
    "accent": "#b23a2e", "accent_light": "#c4554a",
    "accent_dark": "#93301f", "green": "#5f8c6b", "tag_bg": "#e8eef4",
    "tag_fg": "#4d6b8c", "check_box": "#fdf8ea", "check_border": "#9a927e",
    "check_border_hover": "#b23a2e", "btn_hover": "#ffffff",
    "btn_press": "#f0e8d3", "report_bg": "#e4efe7", "report_fg": "#44664e",
    "report_hover": "#d8e9dd", "report_press": "#cde0d4", "grip": "#8d856f",
    "lock_bg": "#c9973a", "lock_hover": "#d8a94e", "lock_press": "#a87e2c",
    "ghost_bg": "#fbf6e8",
}

_TID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\.css$")
_META_RE = re.compile(r"/\*!\s*\n(.*?)\*/", re.S)
_TK_RE = re.compile(r"--tk-([a-zA-Z0-9_]+)\s*:\s*([^;]+)\s*;?")
_BODY_RE = re.compile(r"body\.([a-z0-9_-]+)\s*\{")
_QC_RE = re.compile(r"^qc(\d+)$")
_QB_RE = re.compile(r"^qb(\d+)$")


def app_dir() -> Path:
    """应用数据目录：打包 = exe 同目录；源码 = 项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def themes_dir() -> Path:
    return app_dir() / "themes"


def ensure_themes_dir() -> Path:
    """确保用户 themes 目录存在，并把内置主题补齐（同名不覆盖）。"""
    user_dir = themes_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    if BUILTIN_DIR.is_dir():
        for src in sorted(BUILTIN_DIR.glob("*.css")):
            dst = user_dir / src.name
            if not dst.exists():
                try:
                    dst.write_text(src.read_text(encoding="utf-8"),
                                   encoding="utf-8")
                except OSError:
                    pass
    return user_dir


def _parse_meta(css: str) -> Dict[str, str]:
    """从 /*! 头注释解析 id/name/desc/default。"""
    meta: Dict[str, str] = {}
    m = _META_RE.search(css)
    if m:
        for line in m.group(1).splitlines():
            line = line.strip().lstrip("*").strip()
            if line and ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return meta


def _collect_css_files() -> List[Path]:
    """收集主题文件：用户目录优先，内置兜底补缺失；按文件名排序。"""
    ensure_themes_dir()
    seen = set()
    files: List[Path] = []
    for base in (themes_dir(), BUILTIN_DIR):
        if not base.is_dir():
            continue
        for f in sorted(base.glob("*.css")):
            if not _TID_RE.match(f.name) or f.name.startswith("."):
                continue
            if f.name in seen:
                continue
            seen.add(f.name)
            files.append(f)
    return files


def _builtin_ids() -> set:
    """内置主题 id 集合（src/themes 下文件名），用于内置/自定义标记。"""
    if not BUILTIN_DIR.is_dir():
        return set()
    return {f.stem for f in BUILTIN_DIR.glob("*.css")
            if _TID_RE.match(f.name)}


def theme_list() -> List[Dict[str, str]]:
    """返回主题清单：[{id, name, desc, builtin, default}]，default 标记置顶。"""
    builtin_ids = _builtin_ids()
    items = []
    for f in _collect_css_files():
        try:
            css = f.read_text(encoding="utf-8")
        except OSError:
            continue
        meta = _parse_meta(css)
        tid = f.stem
        if not _BODY_RE.search(css) or not re.search(rf"body\.{re.escape(tid)}\s*\{{", css):
            continue  # 不是有效主题文件（缺 body.<id> 规则）
        items.append({
            "id": tid,
            "name": meta.get("name", tid),
            "desc": meta.get("desc", ""),
            "builtin": "1" if tid in builtin_ids else "0",
            "default": "1" if meta.get("default", "").strip() in ("1", "true", "yes") else "0",
            "file": f.name,
        })
    items.sort(key=lambda it: (it["default"] != "1", it["id"]))
    return items


def theme_file(theme_id: str) -> Optional[Path]:
    """按 id 定位主题文件（用户目录优先）。"""
    tid = theme_id.strip()
    for base in (themes_dir(), BUILTIN_DIR):
        f = base / f"{tid}.css"
        if f.is_file():
            return f
    return None


def read_theme_css(theme_id: str) -> str:
    f = theme_file(theme_id)
    if not f:
        return ""
    try:
        return f.read_text(encoding="utf-8")
    except OSError:
        return ""


def all_themes_css() -> str:
    """全部主题 CSS（按清单顺序拼接），用于注入 app.html。"""
    return "\n\n".join(
        read_theme_css(it["id"]) for it in theme_list()
    )


def theme_meta_json() -> str:
    """主题清单 JSON（JS 可直接 eval），转义 </script> 防注入逃逸。"""
    import json
    payload = json.dumps(theme_list(), ensure_ascii=False)
    return payload.replace("</", "<\\/")


def _post_process(colors: Dict[str, str]) -> Dict[str, object]:
    """把扁平 --tk-* 变量还原为 tkinter 版所需结构：
    qcN/qbN -> 象限卡片嵌套 dict；bg_accent -> list；数值/布尔字段转类型。
    """
    out: Dict[str, object] = dict(colors)
    qc: Dict[int, str] = {}
    qb: Dict[int, str] = {}
    for k in list(out):
        m = _QC_RE.match(k)
        if m:
            qc[int(m.group(1))] = str(out.pop(k))
        m = _QB_RE.match(k)
        if m:
            qb[int(m.group(1))] = str(out.pop(k))
    if qc:
        out["quadrant_card_bg"] = qc
    if qb:
        out["quadrant_border"] = qb
    if "bg_accent" in out:
        out["bg_accent"] = str(out["bg_accent"]).split()
    if "alpha" in out:
        try:
            out["alpha"] = float(out["alpha"])
        except ValueError:
            pass
    for key in ("bg_grid", "check_round"):
        if key in out:
            out[key] = str(out[key]) in ("1", "true", "True")
    return out


def extract_tk_colors(css: str) -> Dict[str, str]:
    """提取 --tk-* 变量为扁平 {key: value}。"""
    return {k: v.strip() for k, v in _TK_RE.findall(css)}


def load_tk_themes() -> Dict[str, Dict[str, str]]:
    """构建 tkinter 版主题表：{id: {name, desc, **colors}}。

    结果为空时回退内置默认配色（保证回退版永远可用）。
    """
    out: Dict[str, Dict[str, str]] = {}
    for f in _collect_css_files():
        try:
            css = f.read_text(encoding="utf-8")
        except OSError:
            continue
        tid = f.stem
        colors = extract_tk_colors(css)
        if not colors:
            continue
        meta = _parse_meta(css)
        out[tid] = {
            "name": meta.get("name", tid),
            "desc": meta.get("desc", ""),
            **_post_process(colors),
        }
    if not out:
        out[DEFAULT_THEME] = dict(FALLBACK_TK_COLORS)
    return out


def default_theme_id() -> str:
    """返回标记 default:1 的主题；无标记时回退 DEFAULT_THEME。"""
    for it in theme_list():
        if it["default"] == "1":
            return it["id"]
    return DEFAULT_THEME
