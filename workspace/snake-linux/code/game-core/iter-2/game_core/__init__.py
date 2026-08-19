"""game_core 包对外 re-export。

迭代 2 增量：
  - speed_curve + MIN_TICK_MS（取代迭代 1 的 DIFFICULTY_PARAMS）
  - ScoreCallback 类型别名
  - 删除 DirectionError（迭代 2 反向输入统一静默/放行）

注意导入顺序：params 必须在 types 之后导入（property 运行时绑定）。
"""
from .types import (
    Direction,
    Difficulty,
    Food,
    GameStatus,
    Point,
    Snake,
    Snapshot,
)
from .state import GameState, spawn_food, ScoreCallback
from .errors import InvalidStateError

# params 必须在 types 之后导入（property 绑定）
from . import params  # noqa: F401  # speed_curve + MIN_TICK_MS + Difficulty.base_tick_ms

# 提升到包级
from .params import speed_curve, MIN_TICK_MS  # noqa: F401

__all__ = [
    "Direction",
    "Difficulty",
    "Food",
    "GameStatus",
    "GameState",
    "InvalidStateError",
    "MIN_TICK_MS",
    "Point",
    "ScoreCallback",
    "Snake",
    "Snapshot",
    "speed_curve",
    "spawn_food",
]