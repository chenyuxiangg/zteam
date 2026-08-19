"""constants 模块测试：默认皮肤合法 + 布局常量几何自洽。"""
import pytest

from gui_renderer.constants import (
    CELL_SIZE,
    DEFAULT_SKIN,
    GRID_COLS,
    GRID_ROWS,
    HUD_HEIGHT,
    PLAYFIELD_X,
    PLAYFIELD_Y,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from gui_renderer.types import Color


def test_default_skin_name_is_classic():
    """经典皮肤名为 'classic'。"""
    assert DEFAULT_SKIN.name == "classic"


def test_default_skin_all_colors_in_range():
    """DEFAULT_SKIN 所有 Color 字段 r/g/b ∈ [0, 255]。"""
    colors = [
        DEFAULT_SKIN.background,
        DEFAULT_SKIN.grid_line,
        DEFAULT_SKIN.snake_head,
        DEFAULT_SKIN.snake_body,
        DEFAULT_SKIN.food,
        DEFAULT_SKIN.food_outline,
        DEFAULT_SKIN.hud_text,
        DEFAULT_SKIN.hud_accent,
    ]
    for c in colors:
        assert 0 <= c.r <= 255
        assert 0 <= c.g <= 255
        assert 0 <= c.b <= 255


def test_layout_constants_are_positive_integers():
    """所有布局常量为正整数。"""
    constants = {
        "WINDOW_WIDTH": WINDOW_WIDTH,
        "WINDOW_HEIGHT": WINDOW_HEIGHT,
        "HUD_HEIGHT": HUD_HEIGHT,
        "PLAYFIELD_X": PLAYFIELD_X,
        "PLAYFIELD_Y": PLAYFIELD_Y,
        "CELL_SIZE": CELL_SIZE,
        "GRID_COLS": GRID_COLS,
        "GRID_ROWS": GRID_ROWS,
    }
    for name, val in constants.items():
        assert isinstance(val, int), f"{name} 应为 int"
        assert val > 0, f"{name} 应 > 0"


def test_window_width_ge_grid_cols_times_cell_size():
    """窗口宽度能容纳游戏区（grid_cols × cell_size）+ 左右边距。"""
    assert WINDOW_WIDTH >= GRID_COLS * CELL_SIZE + 2 * PLAYFIELD_X


def test_window_height_ge_hud_plus_grid():
    """窗口高度能容纳 HUD + 游戏区（grid_rows × cell_size）+ 上下边距。"""
    playfield_height = GRID_ROWS * CELL_SIZE + (PLAYFIELD_Y - HUD_HEIGHT)  # 网格 + Y 偏移 - HUD
    # 简化：WINDOW_HEIGHT >= HUD_HEIGHT + (PLAYFIELD_Y - HUD_HEIGHT) + GRID_ROWS * CELL_SIZE + PLAYFIELD_X
    # 即 WINDOW_HEIGHT >= PLAYFIELD_Y + GRID_ROWS * CELL_SIZE + PLAYFIELD_X
    assert WINDOW_HEIGHT >= PLAYFIELD_Y + GRID_ROWS * CELL_SIZE + PLAYFIELD_X