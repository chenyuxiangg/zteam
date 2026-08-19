"""params 模块：难度参数表（单一数据源）。

迭代 2 将替换为 speed_curve(score, difficulty)；调用方仅通过
`Difficulty.base_tick_ms` property 访问，迁移对调用方透明。
"""
from typing import Dict
from .types import Difficulty


DIFFICULTY_PARAMS: Dict[Difficulty, Dict[str, int]] = {
    Difficulty.EASY: {"base_tick_ms": 250},
    Difficulty.MEDIUM: {"base_tick_ms": 160},
    Difficulty.HARD: {"base_tick_ms": 100},
}


# 绑定 property：Difficulty.base_tick_ms 走 DIFFICULTY_PARAMS（单一数据源）
def _base_tick_ms(self: Difficulty) -> int:
    """迭代 2 将改为调用 speed_curve(0, self)。"""
    return DIFFICULTY_PARAMS[self]["base_tick_ms"]


Difficulty.base_tick_ms = property(_base_tick_ms)  # type: ignore[attr-defined]