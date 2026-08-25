"""数据模型与四象限常量定义。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

# 四象限顺序：0 紧急重要 / 1 紧急不重要 / 2 不紧急重要 / 3 不紧急不重要
QUADRANTS = [
    {"key": 0, "name": "紧急且重要", "short": "Q1", "color": "#e5533c"},
    {"key": 1, "name": "紧急不重要", "short": "Q2", "color": "#e8912d"},
    {"key": 2, "name": "不紧急重要", "short": "Q3", "color": "#3f7fd9"},
    {"key": 3, "name": "不紧急不重要", "short": "Q4", "color": "#4caf7d"},
]

QUADRANT_BY_KEY = {q["key"]: q for q in QUADRANTS}


def quadrant_name(quadrant: int) -> str:
    return QUADRANT_BY_KEY.get(quadrant, {}).get("name", f"象限 {quadrant}")


def quadrant_color(quadrant: int) -> str:
    return QUADRANT_BY_KEY.get(quadrant, {}).get("color", "#8a93a6")


# ---------------------------------------------------------------- 多标签
# 标签以 JSON 数组字符串存储；兼容旧版本的单个标签纯文本。
def parse_tags(raw: str) -> List[str]:
    """把存储的标签字段解析为标签列表（自动兼容旧单标签数据）。"""
    if not raw or not raw.strip():
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            seen: List[str] = []
            for item in data:
                tag = str(item).strip()
                if tag and tag not in seen:
                    seen.append(tag)
            return seen
    except (ValueError, TypeError):
        pass
    return [raw.strip()]


def tags_to_raw(tags: List[str]) -> str:
    """把标签列表序列化为存储字段。"""
    seen: List[str] = []
    for tag in tags:
        tag = tag.strip()
        if tag and tag not in seen:
            seen.append(tag)
    return json.dumps(seen, ensure_ascii=False)


@dataclass
class Task:
    id: int
    title: str
    description: str = ""
    tag: str = ""
    quadrant: int = 0
    completed_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    @property
    def quadrant_label(self) -> str:
        return quadrant_name(self.quadrant)

    @property
    def quadrant_color(self) -> str:
        return quadrant_color(self.quadrant)

    @property
    def tags(self) -> List[str]:
        """标签列表（支持多标签，兼容旧单标签数据）。"""
        return parse_tags(self.tag)

    @property
    def is_completed(self) -> bool:
        return bool(self.completed_at)
