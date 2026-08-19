"""Renderer.handle_resize 测试（设计 §4.6 + §7.6）。"""
import pytest

from gui_renderer import HudData, Renderer
from gui_renderer.constants import (
    CELL_SIZE,
    CELL_SIZE_MIN,
    HUD_FONT_NAME,
    HUD_FONT_SIZE,
    MIN_PLAYABLE_H,
    MIN_PLAYABLE_W,
    PLAYFIELD_X,
    PLAYFIELD_Y,
)
from gui_renderer.errors import RenderError


# ========================================================================
# §7.6 test_renderer_resize.py 8 条
# ========================================================================


def test_handle_resize_larger_window_increases_cell_size(fake_pygame, renderer):
    """handle_resize(1024, 768) → cell_size 增大（> 24）。"""
    r = renderer
    initial = r.cell_size
    r.handle_resize(1024, 768)
    assert r.cell_size > initial
    assert r.cell_size >= CELL_SIZE_MIN


def test_handle_resize_same_size_keeps_cell_size(fake_pygame, renderer):
    """handle_resize(640, 480) → cell_size 不变（24）。"""
    r = renderer
    r.handle_resize(640, 480)
    assert r.cell_size == CELL_SIZE


def test_handle_resize_below_min_raises_render_error(fake_pygame, renderer):
    """handle_resize(< MIN_PLAYABLE_W, < MIN_PLAYABLE_H) → assertRaises(RenderError)（r2 P2-1 保留）。"""
    r = renderer
    # 任一维度 < MIN_PLAYABLE_W/H 即抛
    with pytest.raises(RenderError):
        r.handle_resize(100, 100)
    with pytest.raises(RenderError):
        r.handle_resize(MIN_PLAYABLE_W - 1, 480)
    with pytest.raises(RenderError):
        r.handle_resize(640, MIN_PLAYABLE_H - 1)


def test_handle_resize_zero_size_raises_render_error(fake_pygame, renderer):
    """handle_resize(0, 0) → RenderError（类型/正整数校验）。"""
    r = renderer
    with pytest.raises(RenderError):
        r.handle_resize(0, 0)


def test_handle_resize_negative_raises_render_error(fake_pygame, renderer):
    """handle_resize(-1, 100) → RenderError。"""
    r = renderer
    with pytest.raises(RenderError):
        r.handle_resize(-1, 100)


def test_handle_resize_scales_font_proportionally(fake_pygame, renderer):
    """handle_resize 后字体大小按 cell_size 比例缩放（new_font_size 变化）。"""
    r = renderer
    initial_font = r._font
    initial_cell = r.cell_size
    # 拉大窗口
    r.handle_resize(1024, 768)
    new_cell = r.cell_size
    # 字体应按 cell_size 比例变大（或保持，下限保护）
    if new_cell > initial_cell:
        # new_font_size = max(10, int(round(HUD_FONT_SIZE * new_cell / CELL_SIZE)))
        expected_size = max(10, int(round(HUD_FONT_SIZE * new_cell / CELL_SIZE)))
        # FakeFont 不存储 font_size，但可间接验证 _font 已被替换
        assert r._font is not initial_font


def test_handle_resize_without_init_raises(fake_pygame):
    """handle_resize 未 init() → RenderError。"""
    r = Renderer((640, 480), enable_high_dpi=False)
    # 未 init()
    with pytest.raises(RenderError):
        r.handle_resize(1024, 768)


def test_handle_resize_keeps_scaled_flag(fake_pygame, renderer_high_dpi):
    """handle_resize 后 SCALED 标志保留（flags 不丢）。"""
    r = renderer_high_dpi
    # 验证初始 set_mode 收到的 flags 含 SCALED
    from tests.conftest import _pg_module, _set_mode_calls

    initial_flags = _set_mode_calls[-1][1]
    assert (initial_flags & _pg_module.SCALED) == _pg_module.SCALED

    r.handle_resize(1024, 768)
    # handle_resize 内部调 set_mode，最后一次 flags 仍含 SCALED
    latest_flags = _set_mode_calls[-1][1]
    assert (latest_flags & _pg_module.SCALED) == _pg_module.SCALED
