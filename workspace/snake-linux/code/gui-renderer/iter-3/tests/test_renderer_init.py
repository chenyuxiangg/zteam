"""Renderer 构造校验测试（迭代 1 既有 + 迭代 3 增量：enable_high_dpi）。

迭代 1 既有用例 100% 保留（zero-modify 兼容）。
"""
import pytest

from gui_renderer import Renderer
from gui_renderer.errors import RenderError
from gui_renderer.types import Color, Skin


# ========================================================================
# 迭代 1 既有用例（保留）
# ========================================================================


def test_renderer_constructs_with_minimal_window():
    """最小可玩尺寸构造成功。"""
    r = Renderer((640, 480))
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
    """窗口高度过小 → RenderError。"""
    with pytest.raises(RenderError):
        Renderer((640, 100))


def test_renderer_accepts_custom_skin():
    """自定义皮肤合法时构造成功。"""
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
    r = Renderer((640, 480), skin=custom)
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
        Renderer((640, 480), skin=bad)


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
        Renderer((640, 480), skin=bad)


def test_renderer_vsync_param_recorded_without_error():
    """vsync=True / False 均不报错。"""
    r1 = Renderer((640, 480), vsync=True)
    r2 = Renderer((640, 480), vsync=False)
    assert r1 is not None
    assert r2 is not None


def test_renderer_default_grid_params():
    """默认 grid_cols / grid_rows / cell_size 与设计常量一致。"""
    from gui_renderer.constants import CELL_SIZE, GRID_COLS, GRID_ROWS

    r = Renderer((640, 480))
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

    r = Renderer((640, 480))
    assert r.skin.name == DEFAULT_SKIN.name


def test_renderer_rejects_non_tuple_window_size():
    """window_size 不是 tuple → RenderError。"""
    with pytest.raises(RenderError):
        Renderer([640, 480])  # type: ignore[arg-type]


def test_renderer_rejects_negative_cell_size():
    """cell_size <= 0 → RenderError。"""
    with pytest.raises(RenderError):
        Renderer((640, 480), cell_size=0)


def test_renderer_rejects_non_positive_grid_cols():
    """grid_cols <= 0 → RenderError。"""
    with pytest.raises(RenderError):
        Renderer((640, 480), grid_cols=0)


def test_renderer_rejects_non_positive_grid_rows():
    """grid_rows <= 0 → RenderError。"""
    with pytest.raises(RenderError):
        Renderer((640, 480), grid_rows=0)


# ========================================================================
# 迭代 3 增量：enable_high_dpi（设计 §4.7 + §7.6）
# ========================================================================


def test_renderer_enable_high_dpi_default_true():
    """Renderer 默认 enable_high_dpi=True（不传即启用高分屏清晰）。"""
    r = Renderer((640, 480))
    # 通过 _enable_high_dpi 内部属性判断；不暴露 public 属性以保持 API 稳定
    assert r._enable_high_dpi is True


def test_renderer_enable_high_dpi_explicit_false():
    """Renderer 显式 enable_high_dpi=False 生效。"""
    r = Renderer((640, 480), enable_high_dpi=False)
    assert r._enable_high_dpi is False


def test_renderer_init_with_high_dpi_passes_scaled_flag(fake_pygame, renderer_high_dpi):
    """enable_high_dpi=True → init() 后 set_mode 收到的 flags 包含 SCALED 位。"""
    from tests.conftest import _pg_module, _set_mode_calls

    # 验证：set_mode 至少被调 1 次，且最后一次调用的 flags 含 SCALED 位
    assert len(_set_mode_calls) >= 1
    _, flags = _set_mode_calls[-1]
    assert (flags & _pg_module.SCALED) == _pg_module.SCALED, (
        f"enable_high_dpi=True 期望 flags 含 SCALED, got {flags:#x}"
    )


def test_renderer_init_without_high_dpi_passes_zero_flag(fake_pygame, renderer):
    """enable_high_dpi=False → init() 后 set_mode 收到的 flags == 0。"""
    from tests.conftest import _set_mode_calls

    assert len(_set_mode_calls) >= 1
    _, flags = _set_mode_calls[-1]
    assert flags == 0, f"enable_high_dpi=False 期望 flags=0, got {flags:#x}"
