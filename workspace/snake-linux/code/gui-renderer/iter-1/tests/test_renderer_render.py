"""Renderer.render 行为测试：调用次数 / 颜色 / 矩形 / 异常。"""
import pytest

from gui_renderer import HudData, Renderer
from gui_renderer.constants import CELL_SIZE, PLAYFIELD_Y
from gui_renderer.errors import RenderError
from tests.conftest import FakeSurface, _pg_module

from game_core import Difficulty, GameStatus, Point, Snapshot


def _snapshot(snake_len: int = 3) -> Snapshot:
    """构造测试用 Snapshot（蛇身长度 snake_len，蛇头在 (1,1)，食物在 (5,5)）。"""
    body = tuple(Point(x=1 + i, y=1) for i in range(snake_len))
    return Snapshot(
        snake_body=body,
        food=Point(5, 5),
        score=10,
        length=snake_len,
        status=GameStatus.RUN,
        difficulty=Difficulty.MEDIUM,
        tick_ms=150,
    )


def _hud() -> HudData:
    return HudData(
        score=10,
        high_score=100,
        length=3,
        difficulty_label="MEDIUM",
        status_label="RUN",
    )


def test_render_calls_surface_fill_with_background(fake_pygame, renderer):
    """渲染 1 次 → screen.fill(background) 被调用。"""
    r = renderer
    snap = _snapshot(3)
    hud = _hud()
    r.render(snap, hud)
    assert len(r._screen.fill_calls) == 1
    assert r._screen.fill_calls[0][0] == r.skin.background


def test_render_snake_len_3_calls_draw_rect_3_times(fake_pygame, renderer):
    """蛇身长度 3 → snake_body 部分 draw.rect 调用 3 次（蛇头 1 + 蛇身 2）。"""
    r = renderer
    _pg_module.draw_calls.reset()
    r.render(_snapshot(3), _hud())
    # 食物 (5,5) 在 PLAYFIELD_Y=96, PLAYFIELD_X=16 → 食物像素 y=216（> 蛇身 y=120）
    # 蛇身 y 都是 120；食物 y=216
    snake_rects = [
        c for c in _pg_module.draw_calls
        if c[1] is not None and len(c[1]) == 4 and c[1][1] == PLAYFIELD_Y + 1 * CELL_SIZE  # snake y=1 → py=120
    ]
    assert len(snake_rects) == 3


def test_render_snake_len_5_calls_draw_rect_5_times(fake_pygame, renderer):
    """蛇身长度 5 → snake_body 部分 draw.rect 调用 5 次。"""
    r = renderer
    _pg_module.draw_calls.reset()
    r.render(_snapshot(5), _hud())
    snake_rects = [
        c for c in _pg_module.draw_calls
        if c[1] is not None and len(c[1]) == 4 and c[1][1] == PLAYFIELD_Y + 1 * CELL_SIZE
    ]
    assert len(snake_rects) == 5


def test_render_food_calls_draw_rect_twice(fake_pygame, renderer):
    """食物 → draw.rect 调用 2 次（填充 + outline，width=1）。"""
    r = renderer
    _pg_module.draw_calls.reset()
    r.render(_snapshot(3), _hud())
    # food 有一次 width=1（outline）
    outline_calls = [c for c in _pg_module.draw_calls if c[2] == 1]
    assert len(outline_calls) == 1
    fill_calls_no_outline = [c for c in _pg_module.draw_calls if c[2] == 0]
    # 蛇身 3 + 食物填充 1 = 4
    assert len(fill_calls_no_outline) == 4


def test_render_hud_calls_font_render_5_times(fake_pygame, renderer):
    """HUD 5 行文本 → font.render 被调用 5 次。"""
    r = renderer
    r.render(_snapshot(3), _hud())
    font = r._font
    # font.render 调用次数（5 行 HUD 文本）
    assert len(font.render_calls) == 5


def test_render_hud_status_over_uses_accent_color(fake_pygame, renderer):
    """Status='OVER' 时 HUD 状态文字用 hud_accent 颜色（设计 §4.6）。"""
    r = renderer
    snap = Snapshot(
        snake_body=(Point(1, 1),),
        food=Point(5, 5),
        score=0,
        length=1,
        status=GameStatus.OVER,
        difficulty=Difficulty.MEDIUM,
        tick_ms=150,
    )
    hud = HudData(0, 0, 1, "MEDIUM", "OVER")
    r.render(snap, hud)
    font = r._font
    # 找到包含 "Status" 的那行
    status_text_call = next((c for c in font.render_calls if "Status" in c[0]), None)
    assert status_text_call is not None
    # OVER 时状态文字应使用 hud_accent
    assert status_text_call[2] == r.skin.hud_accent


def test_render_rejects_empty_snake_body(fake_pygame, renderer):
    """snapshot.snake_body 为空 → 抛 RenderError（设计 §5.5）。"""
    r = renderer
    snap = Snapshot(
        snake_body=(),
        food=Point(5, 5),
        score=0,
        length=0,
        status=GameStatus.RUN,
        difficulty=Difficulty.MEDIUM,
        tick_ms=150,
    )
    with pytest.raises(RenderError):
        r.render(snap, _hud())


def test_render_rejects_none_snapshot(fake_pygame, renderer):
    """snapshot 为 None → 抛 RenderError。"""
    r = renderer
    with pytest.raises(RenderError):
        r.render(None, _hud())  # type: ignore[arg-type]


def test_render_appends_to_fps_samples(fake_pygame, renderer):
    """每次 render 末尾采样耗时（samples 长度 +1）。"""
    r = renderer
    initial = len(r._fps.samples)
    r.render(_snapshot(3), _hud())
    assert len(r._fps.samples) == initial + 1


def test_render_multiple_times_accumulates_samples(fake_pygame, renderer):
    """多次 render 累加 fps samples。"""
    r = renderer
    r._fps.samples.clear()
    for _ in range(5):
        r.render(_snapshot(3), _hud())
    assert len(r._fps.samples) == 5