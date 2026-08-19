"""constants 模块测试：迭代 1 既有 + 迭代 3 增量（DARK_SKIN / COLORBLIND_FRIENDLY_SKIN /
SKIN_REGISTRY / CELL_SIZE_MIN / MIN_PLAYABLE_W / MIN_PLAYABLE_H）。

修订 P2-1：hud_shadow 字段已删除 → 不校验 hud_shadow。
"""
import pytest

from gui_renderer.constants import (
    CELL_SIZE,
    CELL_SIZE_MIN,
    COLORBLIND_FRIENDLY_SKIN,
    DARK_SKIN,
    DEFAULT_SKIN,
    GRID_COLS,
    GRID_ROWS,
    MIN_PLAYABLE_H,
    MIN_PLAYABLE_W,
    PLAYFIELD_X,
    PLAYFIELD_Y,
    SKIN_REGISTRY,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from gui_renderer.types import Color, Skin


# ========================================================================
# 迭代 1 既有常量（保留）
# ========================================================================


def test_layout_constants_sane():
    """布局常量 = 迭代 1 既有值。"""
    assert WINDOW_WIDTH == 640
    assert WINDOW_HEIGHT == 480
    assert CELL_SIZE == 24
    assert GRID_COLS == 20
    assert GRID_ROWS == 15
    assert PLAYFIELD_X == 16
    assert PLAYFIELD_Y == 96  # HUD_HEIGHT (80) + 16


def test_default_skin_name_is_classic():
    """DEFAULT_SKIN.name == 'classic'。"""
    assert DEFAULT_SKIN.name == "classic"


def test_default_skin_new_fields_iter1_compat():
    """DEFAULT_SKIN 新字段（cell_gap/food_pattern/snake_pattern）走默认值。"""
    assert DEFAULT_SKIN.cell_gap == 1
    assert DEFAULT_SKIN.food_pattern == "solid"
    assert DEFAULT_SKIN.snake_pattern == "solid"


# ========================================================================
# 迭代 3 增量：DARK_SKIN / COLORBLIND_FRIENDLY_SKIN
# ========================================================================


def test_dark_skin_name():
    """DARK_SKIN.name == 'dark'。"""
    assert DARK_SKIN.name == "dark"


def test_dark_skin_new_fields():
    """DARK_SKIN 新字段（设计 §4.3）。"""
    assert DARK_SKIN.cell_gap == 2
    assert DARK_SKIN.food_pattern == "ringed"
    assert DARK_SKIN.snake_pattern == "solid"


def test_dark_skin_all_colors_in_range():
    """DARK_SKIN 所有 Color 字段 r/g/b ∈ [0, 255]。"""
    for fname in (
        "background",
        "grid_line",
        "snake_head",
        "snake_body",
        "food",
        "food_outline",
        "hud_text",
        "hud_accent",
    ):
        c = getattr(DARK_SKIN, fname)
        assert isinstance(c, Color)
        assert 0 <= c.r <= 255
        assert 0 <= c.g <= 255
        assert 0 <= c.b <= 255


def test_colorblind_friendly_skin_name():
    """COLORBLIND_FRIENDLY_SKIN.name == 'colorblind_friendly'。"""
    assert COLORBLIND_FRIENDLY_SKIN.name == "colorblind_friendly"


def test_colorblind_friendly_skin_new_fields():
    """COLORBLIND_FRIENDLY_SKIN 新字段（设计 §4.3）：纹理+形状辅助辨识。"""
    assert COLORBLIND_FRIENDLY_SKIN.cell_gap == 1
    assert COLORBLIND_FRIENDLY_SKIN.food_pattern == "checkered"
    assert COLORBLIND_FRIENDLY_SKIN.snake_pattern == "striped"


def test_colorblind_friendly_skin_all_colors_in_range():
    """COLORBLIND_FRIENDLY_SKIN 所有 Color 字段 r/g/b ∈ [0, 255]。"""
    for fname in (
        "background",
        "grid_line",
        "snake_head",
        "snake_body",
        "food",
        "food_outline",
        "hud_text",
        "hud_accent",
    ):
        c = getattr(COLORBLIND_FRIENDLY_SKIN, fname)
        assert isinstance(c, Color)
        assert 0 <= c.r <= 255
        assert 0 <= c.g <= 255
        assert 0 <= c.b <= 255


# ========================================================================
# 迭代 3 增量：SKIN_REGISTRY
# ========================================================================


def test_skin_registry_has_at_least_3_keys():
    """SKIN_REGISTRY 至少 3 个 key（FR-10 出口 ≥3 套）。"""
    assert len(SKIN_REGISTRY) >= 3


def test_skin_registry_contains_three_names():
    """SKIN_REGISTRY 含 'classic' / 'dark' / 'colorblind_friendly'。"""
    assert "classic" in SKIN_REGISTRY
    assert "dark" in SKIN_REGISTRY
    assert "colorblind_friendly" in SKIN_REGISTRY


def test_skin_registry_classic_is_default_skin():
    """SKIN_REGISTRY['classic'] is DEFAULT_SKIN（同一对象引用）。"""
    assert SKIN_REGISTRY["classic"] is DEFAULT_SKIN


def test_skin_registry_dark_is_dark_skin():
    """SKIN_REGISTRY['dark'] is DARK_SKIN。"""
    assert SKIN_REGISTRY["dark"] is DARK_SKIN


def test_skin_registry_colorblind_is_cb_skin():
    """SKIN_REGISTRY['colorblind_friendly'] is COLORBLIND_FRIENDLY_SKIN。"""
    assert SKIN_REGISTRY["colorblind_friendly"] is COLORBLIND_FRIENDLY_SKIN


def test_skin_registry_all_skins_have_valid_colors():
    """SKIN_REGISTRY 内所有皮肤的颜色全部合法（r/g/b ∈ [0, 255]）。"""
    for name, skin in SKIN_REGISTRY.items():
        assert isinstance(skin, Skin)
        for fname in (
            "background",
            "grid_line",
            "snake_head",
            "snake_body",
            "food",
            "food_outline",
            "hud_text",
            "hud_accent",
        ):
            c = getattr(skin, fname)
            assert 0 <= c.r <= 255
            assert 0 <= c.g <= 255
            assert 0 <= c.b <= 255


# ========================================================================
# 迭代 3 增量：缩放常量
# ========================================================================


def test_cell_size_min_is_8():
    """CELL_SIZE_MIN == 8（设计 §4.3 缩放下限）。"""
    assert CELL_SIZE_MIN == 8


def test_min_playable_w_formula():
    """MIN_PLAYABLE_W = GRID_COLS * CELL_SIZE_MIN + 2 * PLAYFIELD_X（设计 §2.3）。"""
    expected = GRID_COLS * CELL_SIZE_MIN + 2 * PLAYFIELD_X
    assert MIN_PLAYABLE_W == expected


def test_min_playable_h_formula():
    """MIN_PLAYABLE_H = GRID_ROWS * CELL_SIZE_MIN + PLAYFIELD_Y + PLAYFIELD_X。"""
    expected = GRID_ROWS * CELL_SIZE_MIN + PLAYFIELD_Y + PLAYFIELD_X
    assert MIN_PLAYABLE_H == expected


def test_min_playable_w_is_smaller_than_default_window():
    """MIN_PLAYABLE_W 严格小于默认窗口宽度。"""
    assert MIN_PLAYABLE_W < WINDOW_WIDTH


def test_min_playable_h_is_smaller_than_default_window():
    """MIN_PLAYABLE_H 严格小于默认窗口高度。"""
    assert MIN_PLAYABLE_H < WINDOW_HEIGHT
