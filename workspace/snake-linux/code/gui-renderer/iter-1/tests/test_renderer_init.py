"""Renderer 构造校验测试。"""
import pytest

from gui_renderer import Renderer
from gui_renderer.errors import RenderError
from gui_renderer.types import Color, Skin


def test_renderer_constructs_with_minimal_window():
    """最小可玩尺寸构造成功。"""
    r = Renderer((512, 472))
    assert r is not None


def test_renderer_constructs_with_larger_window():
    """更大窗口（设计默认 640×480）也构造成功。"""
    r = Renderer((640, 480))
    assert r is not None


def test_renderer_rejects_too_small_window_width():
    """窗口宽度过小 → RenderError（最小 = GRID_COLS * CELL_SIZE + 2 * PLAYFIELD_X）。"""
    with pytest.raises(RenderError):
        Renderer((100, 472))


def test_renderer_rejects_too_small_window_height():
    """窗口高度过小 → RenderError（最小 = PLAYFIELD_Y + GRID_ROWS * CELL_SIZE + PLAYFIELD_X）。"""
    with pytest.raises(RenderError):
        Renderer((512, 100))


def test_renderer_accepts_custom_skin():
    """自定义皮肤合法时构造成功（仅校验字段合法性，不绘制）。"""
    custom = Skin(
        name="custom",
        background=Color(0, 0, 0),
        grid_line=Color(10, 10, 10),
        snake_head=Color(100, 100, 100),
        snake_body=Color(80, 80, 80),
        food=Color(200, 50, 50),
        food_outline=Color(255, 255, 255),
        hud_text=Color(200, 200, 200),
        hud_accent=Color(255, 200, 0),
    )
    r = Renderer((512, 472), skin=custom)
    assert r is not None


def test_renderer_rejects_color_out_of_range():
    """皮肤颜色 RGB 越界（r > 255） → RenderError。"""
    bad = Skin(
        name="bad",
        background=Color(300, 0, 0),  # r 越界
        grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0),
        snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0),
        food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0),
        hud_accent=Color(0, 0, 0),
    )
    with pytest.raises(RenderError):
        Renderer((512, 472), skin=bad)


def test_renderer_rejects_negative_color():
    """皮肤颜色 RGB < 0 → RenderError。"""
    bad = Skin(
        name="bad",
        background=Color(-1, 0, 0),
        grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0),
        snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0),
        food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0),
        hud_accent=Color(0, 0, 0),
    )
    with pytest.raises(RenderError):
        Renderer((512, 472), skin=bad)


def test_renderer_vsync_param_recorded_without_error():
    """vsync=True / False 均不报错（仅记录，pygame 是否真支持由环境决定）。"""
    r1 = Renderer((512, 472), vsync=True)
    r2 = Renderer((512, 472), vsync=False)
    assert r1 is not None
    assert r2 is not None


def test_renderer_default_grid_params():
    """默认 grid_cols / grid_rows / cell_size 与设计常量一致。"""
    from gui_renderer.constants import CELL_SIZE, GRID_COLS, GRID_ROWS

    r = Renderer((512, 472))
    assert r.cell_size == CELL_SIZE
    assert r.grid_cols == GRID_COLS
    assert r.grid_rows == GRID_ROWS


def test_renderer_custom_grid_params():
    """自定义 cell_size / grid_cols / grid_rows 生效。"""
    r = Renderer((640, 640), cell_size=16, grid_cols=20, grid_rows=20)
    assert r.cell_size == 16
    assert r.grid_cols == 20
    assert r.grid_rows == 20


def test_renderer_default_skin_used_when_none():
    """不传 skin 时使用 DEFAULT_SKIN。"""
    from gui_renderer.constants import DEFAULT_SKIN

    r = Renderer((512, 472))
    assert r.skin.name == DEFAULT_SKIN.name


def test_renderer_rejects_non_tuple_window_size():
    """window_size 不是 tuple → RenderError。"""
    with pytest.raises(RenderError):
        Renderer([512, 472])  # type: ignore[arg-type]


def test_renderer_rejects_negative_cell_size():
    """cell_size <= 0 → RenderError。"""
    with pytest.raises(RenderError):
        Renderer((512, 472), cell_size=0)


def test_renderer_rejects_non_positive_grid_cols():
    """grid_cols <= 0 → RenderError。"""
    with pytest.raises(RenderError):
        Renderer((512, 472), grid_cols=0)


def test_renderer_rejects_non_positive_grid_rows():
    """grid_rows <= 0 → RenderError。"""
    with pytest.raises(RenderError):
        Renderer((512, 472), grid_rows=0)