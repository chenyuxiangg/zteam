"""gui_renderer 包：snake-linux v2.0.0 gui-renderer 迭代 1 首发。

对外 re-export（设计 §3.2）。后续迭代 3 增量（set_skin / handle_resize /
draw_animated / SkinRegistry / 皮肤系统 ≥3 套）通过扩展而非修改接入。
"""
from .constants import (
    CELL_SIZE,
    DEFAULT_SKIN,
    GRID_COLS,
    GRID_ROWS,
    HUD_HEIGHT,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from .errors import RenderError, SkinNotFoundError
from .renderer import Renderer
from .types import Color, FpsMetric, HudData, Rect, Skin

__all__ = [
    # 主类
    "Renderer",
    # 值对象
    "Color",
    "Rect",
    "Skin",
    "HudData",
    "FpsMetric",
    # 异常
    "RenderError",
    "SkinNotFoundError",
    # 常量
    "DEFAULT_SKIN",
    "WINDOW_WIDTH",
    "WINDOW_HEIGHT",
    "HUD_HEIGHT",
    "CELL_SIZE",
    "GRID_COLS",
    "GRID_ROWS",
]