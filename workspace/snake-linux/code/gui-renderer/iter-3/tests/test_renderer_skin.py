"""Renderer 切皮肤测试（设计 §7.6）。"""
import pytest

from gui_renderer import HudData, Renderer
from gui_renderer.constants import (
    COLORBLIND_FRIENDLY_SKIN,
    DARK_SKIN,
    DEFAULT_SKIN,
    GRID_COLS,
    GRID_ROWS,
    PLAYFIELD_X,
    PLAYFIELD_Y,
    SKIN_REGISTRY,
)
from gui_renderer.errors import SkinNotFoundError
from tests.conftest import _pg_module

from game_core import Difficulty, GameStatus, Point, Snapshot


def _snapshot() -> Snapshot:
    body = tuple(Point(x=1 + i, y=1) for i in range(3))
    return Snapshot(
        snake_body=body,
        food=Point(5, 5),
        score=10,
        length=3,
        status=GameStatus.RUN,
        difficulty=Difficulty.MEDIUM,
        tick_ms=150,
    )


def _hud() -> HudData:
    return HudData(10, 100, 3, "MEDIUM", "RUN")


# ========================================================================
# §7.6 test_renderer_skin.py 5 条
# ========================================================================


def test_set_skin_classic_is_idempotent(fake_pygame, renderer):
    """set_skin('classic') 幂等。"""
    r = renderer
    r.set_skin("classic")
    assert r.current_skin_name == "classic"
    assert r.skin.name == "classic"


def test_set_skin_multiple_switches(fake_pygame, renderer):
    """多次切换皮肤：classic → dark → colorblind_friendly → classic。"""
    r = renderer
    r.set_skin("dark")
    assert r.current_skin_name == "dark"
    r.set_skin("colorblind_friendly")
    assert r.current_skin_name == "colorblind_friendly"
    r.set_skin("classic")
    assert r.current_skin_name == "classic"


def test_set_skin_unknown_raises_skin_not_found(fake_pygame, renderer):
    """set_skin('nope') → SkinNotFoundError；e.name == 'nope' 且 e.available 包含 3 个 key。"""
    r = renderer
    with pytest.raises(SkinNotFoundError) as exc_info:
        r.set_skin("nope")
    e = exc_info.value
    assert e.name == "nope"
    assert "classic" in e.available
    assert "dark" in e.available
    assert "colorblind_friendly" in e.available
    assert len(e.available) == 3


def test_current_skin_name_defaults_to_classic(fake_pygame, renderer):
    """current_skin_name 默认为 'classic'（DEFAULT_SKIN.name）。"""
    r = renderer
    assert r.current_skin_name == "classic"


def test_set_skin_affects_next_render(fake_pygame, renderer):
    """set_skin 后下一帧 render 使用新皮肤颜色（断言 draw.rect 颜色变更）。"""
    r = renderer
    r.set_skin("classic")
    _pg_module.draw_calls.reset()
    r.render(_snapshot(), _hud())
    classic_snake_color = _pg_module.draw_calls.records[0][0]  # 蛇头颜色

    r.set_skin("dark")
    _pg_module.draw_calls.reset()
    r.render(_snapshot(), _hud())
    dark_snake_color = _pg_module.draw_calls.records[0][0]

    assert classic_snake_color != dark_snake_color
    # dark 皮肤的蛇头 = (140, 255, 200)（MTO-4-01 修复：pygame 收到 tuple）
    head = DARK_SKIN.snake_head
    assert dark_snake_color == (head.r, head.g, head.b)
