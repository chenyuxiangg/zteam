"""params 模块：speed_curve + MIN_TICK_MS（迭代 2 单一数据源）。

NFR-01 量化：score=0 三档 250/160/100；任意 score HARD <= EASY*0.5；
三档独立下限 EASY=100 / MEDIUM=80 / HARD=50。

Difficulty.base_tick_ms property 在本模块 import 后运行时绑定（避免 types→params
循环导入）。
"""
from typing import Dict

from .types import Difficulty


# 内部常量：三档曲线参数（FO 实现可修改；UT 不修改此表）
_DIFFICULTY_CURVE_PARAMS: Dict[Difficulty, Dict[str, int]] = {
    Difficulty.EASY:   {"base": 250, "k": 4},
    Difficulty.MEDIUM: {"base": 160, "k": 4},
    Difficulty.HARD:   {"base": 100, "k": 3},
}


# 三档独立下限（per-difficulty dict；满足 NFR-01 量化：HARD_MIN=50 <= EASY_MIN*0.5=50）
MIN_TICK_MS: Dict[Difficulty, int] = {
    Difficulty.EASY:   100,
    Difficulty.MEDIUM: 80,
    Difficulty.HARD:   50,
}


def speed_curve(score: int, difficulty: Difficulty) -> int:
    """返回当前 score 在指定难度下应使用的 tick_ms。

    公式：tick_ms = max(MIN_TICK_MS[difficulty], base - k * score)
    约束（NFR-01）：
      - score=0 时 == difficulty.base_tick_ms（== 250 / 160 / 100）
      - 任意 score：tick_ms(HARD, score) <= tick_ms(EASY, score) * 0.5
      - tick_ms 不低于该档位独立下限 MIN_TICK_MS[difficulty]
    """
    p = _DIFFICULTY_CURVE_PARAMS[difficulty]
    return max(MIN_TICK_MS[difficulty], p["base"] - p["k"] * score)


# 运行时绑定 base_tick_ms property：Difficulty.base_tick_ms -> speed_curve(0, self)
def _base_tick_ms(self: Difficulty) -> int:
    """基线节拍（score=0 时）；走 speed_curve(0, self) 单一数据源。"""
    return speed_curve(0, self)


Difficulty.base_tick_ms = property(_base_tick_ms)  # type: ignore[attr-defined]