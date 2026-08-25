"""日报统计与 CSV / JSON 导出。"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from db import Database
from models import QUADRANTS, Task, quadrant_name

CSV_HEADERS = ["完成时间", "标题", "标签", "象限", "任务描述"]


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


def export_report(db: Database, date_str: str, directory: str | Path) -> List[Path]:
    """导出某一天的日报，生成 CSV（UTF-8-SIG）和 JSON。"""
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
        files = export_report(db, date_str, directory)
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
