"""gui_renderer 包：snake-linux v2.0.0 gui-renderer 迭代 3 增量。

迭代 1 首发（已 it_passed）→ 迭代 3 增量接入：平滑插值动画 / 皮肤系统 ≥3 套 /
窗口等比缩放 / 高分屏清晰（设计 §3.2 + §0.2）。
"""
from .constants import (
    CELL_SIZE,
    CELL_SIZE_MIN,
    COLORBLIND_FRIENDLY_SKIN,
    DARK_SKIN,
    DEFAULT_SKIN,
    GRID_COLS,
    GRID_ROWS,
    HUD_FONT_NAME,
    HUD_FONT_SIZE,
    HUD_HEIGHT,
    MIN_PLAYABLE_H,
    MIN_PLAYABLE_W,
    PLAYFIELD_X,
    PLAYFIELD_Y,
    SKIN_REGISTRY,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from .errors import RenderError, SkinNotFoundError
from .renderer import Renderer
from .types import (
    Color,
    FpsMetric,
    HudData,
    InterpolationState,
    Rect,
    Skin,
)

__all__ = [
    # 主类
    "Renderer",
    # 值对象
    "Color",
    "Rect",
    "Skin",
    "HudData",
    "FpsMetric",
    "InterpolationState",
    # 异常
    "RenderError",
    "SkinNotFoundError",
    # 常量
    "DEFAULT_SKIN",
    "DARK_SKIN",
    "COLORBLIND_FRIENDLY_SKIN",
    "SKIN_REGISTRY",
    "WINDOW_WIDTH",
    "WINDOW_HEIGHT",
    "HUD_HEIGHT",
    "CELL_SIZE",
    "CELL_SIZE_MIN",
    "GRID_COLS",
    "GRID_ROWS",
    "MIN_PLAYABLE_W",
    "MIN_PLAYABLE_H",
    "PLAYFIELD_X",
    "PLAYFIELD_Y",
    "HUD_FONT_NAME",
    "HUD_FONT_SIZE",
]
