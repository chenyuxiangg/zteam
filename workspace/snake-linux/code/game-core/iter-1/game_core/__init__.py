"""game_core 包对外 re-export。

FR-01~05 玩法核心；NFR-05 零 GUI 依赖，可独立 UT。
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
from .state import GameState, spawn_food
from .errors import DirectionError, InvalidStateError

# 注意：params 模块必须在 types 之后导入（property 绑定）
from . import params  # noqa: F401  # DIFFICULTY_PARAMS 与 base_tick_ms property

# 将 DIFFICULTY_PARAMS 提升到包级，便于 `from game_core import DIFFICULTY_PARAMS`
from .params import DIFFICULTY_PARAMS  # noqa: F401

__all__ = [
    "Direction",
    "Difficulty",
    "DIFFICULTY_PARAMS",
    "Food",
    "GameStatus",
    "GameState",
    "InvalidStateError",
    "DirectionError",
    "Point",
    "Snake",
    "Snapshot",
    "spawn_food",
]