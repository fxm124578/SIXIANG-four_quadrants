"""日报统计与 CSV / JSON / HTML 导出。"""
from __future__ import annotations

import csv
import html as html_mod
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from db import Database
from models import QUADRANTS, Task, quadrant_name

CSV_HEADERS = ["完成时间", "标题", "标签", "象限", "任务描述"]

# 标签配色（与 WebView 端 TAG_PALETTE 保持一致）
TAG_PALETTE = [
    ("#5b4bb5", "#e8e3ff"), ("#8a5a10", "#fff0d4"), ("#2e7d52", "#dcf5e8"),
    ("#2f6fc4", "#dcebff"), ("#b04a3c", "#fde3de"), ("#a83e80", "#fde3f2"),
]

# 时段分布：每 4 小时一段
HOUR_SLOTS = [
    ("深夜", "0-4", 0, 4), ("清晨", "4-8", 4, 8), ("上午", "8-12", 8, 12),
    ("下午", "12-16", 12, 16), ("傍晚", "16-20", 16, 20),
    ("夜晚", "20-24", 20, 24),
]


def build_report_stats(tasks: List[Task]) -> Dict:
    """统计任务总数、按象限分布、按标签分布（多标签逐一计数）。"""
    by_quadrant = {item["key"]: 0 for item in QUADRANTS}
    by_tag: Dict[str, int] = {}
    for task in tasks:
        by_quadrant[task.quadrant] += 1
        tags = task.tags or ["（无标签）"]
        for tag in tags:
            by_tag[tag] = by_tag.get(tag, 0) + 1
    return {
        "total": len(tasks),
        "by_quadrant": by_quadrant,
        "by_tag": by_tag,
    }


def _esc(value) -> str:
    return html_mod.escape(str(value if value is not None else ""))


def _hour_distribution(tasks: List[Task]) -> List[int]:
    """24 小时完成数量分布。"""
    hours = [0] * 24
    for task in tasks:
        completed = task.completed_at or ""
        if " " not in completed:
            continue
        try:
            hour = int(completed.split(" ", 1)[1].split(":", 1)[0])
            if 0 <= hour <= 23:
                hours[hour] += 1
        except (ValueError, IndexError):
            continue
    return hours


def _slot_distribution(hours: List[int]) -> List[int]:
    return [sum(hours[start:end]) for _, _, start, end in HOUR_SLOTS]


def _avg_interval_minutes(tasks: List[Task]) -> Optional[int]:
    """相邻完成时间的平均间隔（分钟）；不足 2 条返回 None。"""
    times = []
    for task in tasks:
        completed = task.completed_at or ""
        try:
            times.append(datetime.strptime(completed, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
    if len(times) < 2:
        return None
    times.sort()
    total = sum(
        (curr - prev).total_seconds()
        for prev, curr in zip(times, times[1:])
    )
    return int(round(total / (len(times) - 1) / 60))


def _fmt_interval(minutes: Optional[int]) -> str:
    if minutes is None:
        return "—"
    if minutes < 1:
        return "<1 分钟"
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, remainder = divmod(minutes, 60)
    return f"{hours} 小时 {remainder} 分" if remainder else f"{hours} 小时"


def _donut_svg(segments, total: int, size: int = 168,
               stroke: int = 22) -> str:
    """象限分布环形图：segments 为 [(名称, 数量, 颜色)]。"""
    radius = (size - stroke) / 2
    circumference = 2 * math.pi * radius
    center = size / 2
    circles = []
    acc = 0.0
    for _, value, color in segments:
        if value <= 0:
            continue
        frac = value / total
        length = frac * circumference
        rotate = acc * 360 - 90
        acc += frac
        circles.append(
            f'<circle cx="{center:.1f}" cy="{center:.1f}" '
            f'r="{radius:.1f}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'transform="rotate({rotate:.2f} {center:.1f} {center:.1f})"/>'
        )
    text = (
        f'<text x="{center:.1f}" y="{center - 1:.1f}" '
        f'text-anchor="middle" class="donut-num">{total}</text>'
        f'<text x="{center:.1f}" y="{center + 15:.1f}" '
        f'text-anchor="middle" class="donut-cap">完成任务</text>'
    )
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}"'
        f' class="donut">{"".join(circles)}{text}</svg>'
    )


def _legend_html(segments, total: int) -> str:
    rows = []
    for name, value, color in segments:
        pct = round(value / total * 100) if total else 0
        rows.append(
            f'<div class="legend-row">'
            f'<span class="legend-dot" style="background:{color}"></span>'
            f'<span class="legend-name">{_esc(name)}</span>'
            f'<span class="legend-val">{value}</span>'
            f'<span class="legend-pct">{pct}%</span></div>'
        )
    return "".join(rows)


def _tag_bars_html(by_tag: Dict[str, int]) -> str:
    if not by_tag:
        return '<div class="chart-empty">今日无标签记录</div>'
    items = sorted(by_tag.items(), key=lambda kv: -kv[1])[:8]
    top = items[0][1]
    rows = []
    for index, (tag, count) in enumerate(items):
        fg, _bg = TAG_PALETTE[index % len(TAG_PALETTE)]
        pct = count / top * 100
        rows.append(
            f'<div class="tbar-row">'
            f'<span class="tbar-name" title="{_esc(tag)}">{_esc(tag)}</span>'
            f'<div class="tbar-track"><div class="tbar-fill" '
            f'style="width:{pct:.1f}%;background:{fg}"></div></div>'
            f'<span class="tbar-val">{count}</span></div>'
        )
    return "".join(rows)


def _slot_bars_html(slots: List[int]) -> str:
    top = max(slots) if slots else 0
    cols = []
    for (name, span, _s, _e), count in zip(HOUR_SLOTS, slots):
        pct = count / top * 100 if top else 0
        empty = " empty" if count == 0 else ""
        cols.append(
            f'<div class="hbar-col{empty}">'
            f'<span class="hbar-val">{count}</span>'
            f'<div class="hbar" style="height:{pct:.1f}%"></div>'
            f'<span class="hbar-label">{name}<br>{span}</span></div>'
        )
    return f'<div class="horbars">{"".join(cols)}</div>'


def _cards_html(total: int, tag_count: int, peak: Optional[tuple],
                interval: Optional[int]) -> str:
    peak_text = "—" if peak is None else f"{peak[0]} {peak[1]}"
    cards = [
        (total, "完成任务", QUADRANTS[3]["color"]),
        (tag_count, "涉及标签", QUADRANTS[2]["color"]),
        (peak_text, "高峰时段", QUADRANTS[1]["color"]),
        (_fmt_interval(interval), "平均完成间隔", QUADRANTS[0]["color"]),
    ]
    return "".join(
        f'<div class="hero-card">'
        f'<span class="hero-bar" style="background:{color}"></span>'
        f'<div class="hero-num">{_esc(str(num))}</div>'
        f'<div class="hero-label">{label}</div></div>'
        for num, label, color in cards
    )


def _tags_cell_html(tags: List[str]) -> str:
    return "".join(
        f'<span class="tag" style="background:{bg};color:{fg}">'
        f'{_esc(tag)}</span>'
        for index, tag in enumerate(tags)
        for fg, bg in [TAG_PALETTE[index % len(TAG_PALETTE)]]
    )


def _table_html(tasks: List[Task]) -> str:
    rows = []
    for task in tasks:
        completed = task.completed_at or ""
        time_part = (completed.split(" ")[1][:5]
                     if " " in completed else completed)
        rows.append(
            f'<tr><td>{_esc(time_part)}</td><td>{_esc(task.title)}</td>'
            f'<td>{_tags_cell_html(task.tags)}</td>'
            f'<td>{_esc(task.quadrant_label)}</td>'
            f'<td class="desc">{_esc(task.description)}</td></tr>'
        )
    return "".join(rows)


_HTML_CSS = """\
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Noto Sans SC","Microsoft YaHei","PingFang SC",sans-serif;\
background:#eef1f5;color:#2c3242;padding:30px 18px;line-height:1.5}
.wrap{max-width:960px;margin:0 auto}
header{background:#fff;border-radius:16px;padding:26px 30px;margin-bottom:16px;\
display:flex;align-items:flex-end;justify-content:space-between;\
box-shadow:0 2px 14px rgba(60,70,100,.07)}
h1{font-size:24px;font-weight:700;letter-spacing:.06em}
.sub{color:#8d94a8;font-size:12.5px;margin-top:6px}
.gen{color:#aab0c0;font-size:11.5px;text-align:right}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:16px}
.hero-card{position:relative;overflow:hidden;background:#fff;border-radius:14px;\
padding:18px 20px;box-shadow:0 2px 10px rgba(60,70,100,.06)}
.hero-bar{position:absolute;left:0;top:0;bottom:0;width:4px}
.hero-num{font-size:25px;font-weight:700;line-height:1.2}
.hero-label{font-size:12px;color:#8d94a8;margin-top:5px}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}
.chart{background:#fff;border-radius:14px;padding:20px 22px;box-shadow:0 2px 10px rgba(60,70,100,.06)}
.chart.full{grid-column:1/-1}
.chart h3{font-size:14px;font-weight:700;margin-bottom:14px;\
display:flex;align-items:center;gap:8px}
.chart h3::before{content:"";width:4px;height:14px;border-radius:2px;\
background:#b23a2e}
.donut-wrap{display:flex;align-items:center;gap:26px}
.donut-num{font-size:30px;font-weight:700;fill:currentColor}
.donut-cap{font-size:11px;fill:#8d94a8}
.legend{flex:1;display:flex;flex-direction:column;gap:9px;min-width:0}
.legend-row{display:flex;align-items:center;gap:8px;font-size:12.5px}
.legend-dot{width:10px;height:10px;border-radius:3px;flex-shrink:0}
.legend-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.legend-val{font-weight:600;min-width:22px;text-align:right}
.legend-pct{color:#8d94a8;font-size:11.5px;width:40px;text-align:right}
.tbar-row{display:flex;align-items:center;gap:10px;font-size:12.5px;margin-bottom:9px}
.tbar-name{width:76px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;\
white-space:nowrap}
.tbar-track{flex:1;height:10px;border-radius:5px;background:#f0f2f6;overflow:hidden}
.tbar-fill{height:100%;border-radius:5px}
.tbar-val{width:28px;text-align:right;font-weight:600}
.horbars{display:flex;align-items:flex-end;gap:18px;height:150px;padding:0 6px}
.hbar-col{flex:1;display:flex;flex-direction:column;align-items:center;\
height:100%;justify-content:flex-end;gap:7px}
.hbar{width:100%;max-width:54px;border-radius:6px 6px 3px 3px;\
background:linear-gradient(180deg,#6b9bff,#3f7fd9);min-height:2px}
.hbar-val{font-size:11px;font-weight:600;color:#5a6478}
.hbar-label{font-size:11px;color:#8d94a8;text-align:center;line-height:1.3}
.hbar-col.empty .hbar{background:#e3e7ee}
.hbar-col.empty .hbar-val{color:#c3c9d4}
.chart-empty{color:#aab0c0;font-size:12.5px;padding:14px 2px}
.table-wrap{background:#fff;border-radius:14px;padding:20px 22px;\
box-shadow:0 2px 10px rgba(60,70,100,.06)}
.table-wrap h3{font-size:14px;font-weight:700;margin-bottom:12px;\
display:flex;align-items:center;gap:8px}
.table-wrap h3::before{content:"";width:4px;height:14px;border-radius:2px;\
background:#b23a2e}
table{width:100%;border-collapse:collapse;font-size:12.5px;table-layout:fixed}
th{text-align:left;padding:9px 10px;border-bottom:2px solid #eef1f5;\
color:#5a6478;font-weight:600;white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid #f2f4f8;vertical-align:top;\
word-break:break-all}
tr:hover td{background:#f8fafc}
td:nth-child(-n+4),td:nth-child(1){white-space:nowrap;overflow:hidden;\
text-overflow:ellipsis;word-break:normal}
th:nth-child(1){width:72px}th:nth-child(2){width:26%}th:nth-child(3){width:20%}
th:nth-child(4){width:15%}
td.desc{white-space:pre-wrap;word-break:break-word}
.tag{display:inline-block;font-size:10.5px;padding:2px 8px;border-radius:99px;\
margin:1px 4px 1px 0}
@media (max-width:720px){.cards{grid-template-columns:repeat(2,1fr)}\
.charts{grid-template-columns:1fr}.donut-wrap{flex-direction:column}}
"""


def _render_report_html(tasks: List[Task], date_str: str) -> str:
    stats = build_report_stats(tasks)
    by_quadrant = stats["by_quadrant"]
    by_tag = stats["by_tag"]

    hours = _hour_distribution(tasks)
    slots = _slot_distribution(hours)
    interval = _avg_interval_minutes(tasks)
    peak_index = max(range(len(slots)), key=slots.__getitem__) if any(slots) else None
    peak = HOUR_SLOTS[peak_index] if peak_index is not None else None

    segments = [
        (q["name"], by_quadrant[q["key"]], q["color"])
        for q in QUADRANTS
    ]
    total = len(tasks)

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    weekday = "一二三四五六日"[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    cards = _cards_html(total, len(by_tag), peak, interval)
    donut = _donut_svg(segments, total)
    legend = _legend_html(segments, total)
    tag_bars = _tag_bars_html(by_tag)
    slot_bars = _slot_bars_html(slots)
    table = _table_html(tasks)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>四象 · 日报 {_esc(date_str)}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>四象 · 日报</h1>
      <div class="sub">{_esc(date_str)} 周{_esc(weekday)} · 共完成 {total} 个任务</div>
    </div>
    <div class="gen">生成时间：{_esc(generated)}</div>
  </header>
  <div class="cards">{cards}</div>
  <div class="charts">
    <div class="chart">
      <h3>象限分布</h3>
      <div class="donut-wrap">{donut}{legend}</div>
    </div>
    <div class="chart">
      <h3>标签分布</h3>
      {tag_bars}
    </div>
    <div class="chart full">
      <h3>完成时段</h3>
      {slot_bars}
    </div>
  </div>
  <div class="table-wrap">
    <h3>任务明细（{total}）</h3>
    <table>
      <thead><tr><th>完成时间</th><th>标题</th><th>标签</th><th>象限</th><th>描述</th></tr></thead>
      <tbody>{table}</tbody>
    </table>
  </div>
</div>
</body>
</html>"""


def export_report_html(db: Database, date_str: str,
                       directory: str | Path,
                       tasks: Optional[List[Task]] = None) -> Path:
    """导出某一天的日报 HTML（自包含，可浏览器直接打开）。"""
    if tasks is None:
        tasks = db.get_completed_tasks(date_str)
    if not tasks:
        raise ValueError(f"{date_str} 没有已完成任务，无需导出 HTML。")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"daily_report_{date_str}.html"
    path.write_text(_render_report_html(tasks, date_str), encoding="utf-8")
    return path


def export_report(db: Database, date_str: str, directory: str | Path,
                  include_html: bool = True) -> List[Path]:
    """导出某一天的日报，生成 CSV（UTF-8-SIG）、JSON 与 HTML。"""
    tasks = db.get_completed_tasks(date_str)
    if not tasks:
        return []

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stats = build_report_stats(tasks)
    generated_files: List[Path] = []

    csv_path = directory / f"daily_report_{date_str}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(CSV_HEADERS)
        for task in tasks:
            writer.writerow(
                [
                    task.completed_at or "",
                    task.title,
                    "、".join(task.tags),
                    task.quadrant_label,
                    task.description,
                ]
            )
    generated_files.append(csv_path)

    json_path = directory / f"daily_report_{date_str}.json"
    payload = {
        "report_date": date_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_completed": stats["total"],
        "stats": {
            "by_quadrant": {
                quadrant_name(key): value
                for key, value in stats["by_quadrant"].items()
            },
            "by_tag": stats["by_tag"],
        },
        "tasks": [task.to_dict() for task in tasks],
    }
    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    generated_files.append(json_path)

    if include_html:
        generated_files.append(export_report_html(db, date_str, directory,
                                                  tasks))

    return generated_files


def export_report_range(
    db: Database,
    start_date: str,
    end_date: str,
    directory: str | Path,
) -> List[Path]:
    """批量导出日期范围内所有有完成记录的日报，并生成汇总 CSV。"""
    dates = sorted(
        date_str
        for date_str in db.get_completed_dates()
        if start_date <= date_str <= end_date
    )
    if not dates:
        return []

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    generated_files: List[Path] = []
    summary_rows: List[tuple[str, int]] = []

    for date_str in dates:
        files = export_report(db, date_str, directory, include_html=False)
        generated_files.extend(files)
        summary_rows.append(
            (date_str, len(db.get_completed_tasks(date_str)))
        )

    summary_path = directory / (
        f"daily_report_summary_{start_date}_{end_date}.csv"
    )
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["日期", "完成任务数"])
        writer.writerows(summary_rows)
    generated_files.append(summary_path)

    return generated_files
