"""四象测试包。

把仓库 src/ 挂入 sys.path，使测试能以 src 平铺模块布局的方式
直接 import db / migration / models 等（与运行时 python src/main.py 一致）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
