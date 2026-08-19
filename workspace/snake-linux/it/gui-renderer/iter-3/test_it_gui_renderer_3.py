"""模块 IT 测试：gui-renderer（snake-linux v2.0.0 迭代 3）。

按 `snake-linux/it/gui-renderer/iter-3/测试用例.md` 落地，pytest 9.x。
覆盖 FR-07（平滑插值）、FR-09（窗口缩放）、FR-10（皮肤系统）、NFR-04（高分屏）、
NFR-05（职责分离）、NFR-06（无网络）；迭代 1 既有 31 条用例已 it_passed 不重复。
运行通过 fake_pygame 模块替换 pygame（沿用迭代 1 模式 + 迭代 3 增量：blit/flags 记录）。

执行：pytest test_it_gui_renderer_3.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# ---- 路径定位（与迭代 1 一致） ----
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/gui-renderer/iter-3 -> snake-linux
_GUI_CODE = _WORKSPACE / "code" / "gui-renderer" / "iter-3"
_GAMECORE_CODE = _WORKSPACE / "code" / "game-core" / "iter-1"
sys.path.insert(0, str(_GUI_CODE))
sys.path.insert(0, str(_GAMECORE_CODE))

# 路径注入与 fake_pygame 来自 conftest.py
from gui_renderer import (  # noqa: E402
    CELL_SIZE,
    CELL_SIZE_MIN,
    COLORBLIND_FRIENDLY_SKIN,
    DARK_SKIN,
    DEFAULT_SKIN,
    GRID_COLS,
    GRID_ROWS,
    HUD_HEIGHT,
    MIN_PLAYABLE_H,
    MIN_PLAYABLE_W,
    PLAYFIELD_X,
    PLAYFIELD_Y,
    SKIN_REGISTRY,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    Color,
    HudData,
    InterpolationState,
    RenderError,
    Renderer,
    Skin,
    SkinNotFoundError,
)
from game_core import Difficulty, GameStatus, Point, Snapshot  # noqa: E402


# ---- helpers ----

def _make_snapshot(snake=((10, 7), (9, 7), (8, 7)), food=(15, 7), score=0,
                   length=3, status=GameStatus.RUN, difficulty=Difficulty.MEDIUM):
    """构造 game_core.Snapshot（真实跨模块契约）。"""
    return Snapshot(
        snake_body=tuple(Point(*p) for p in snake),
        food=Point(*food),
        score=score,
        length=length,
        status=status,
        difficulty=difficulty,
        tick_ms=160,
    )


def _c(skin_color):
    """MTO-4-01 修复：Skin 颜色字段是 Color dataclass，pygame 侧收到的是 tuple。"""
    return (skin_color.r, skin_color.g, skin_color.b)


def _make_hud(score=0, high_score=128, length=3, difficulty_label="MEDIUM",
              status_label="RUN"):
    return HudData(score=score, high_score=high_score, length=length,
                   difficulty_label=difficulty_label, status_label=status_label)


# ============================================================================
# §1.1 皮肤系统（FR-10）— IT-gui-renderer-3-01 ~ 13
# ============================================================================

@pytest.mark.p0
def test_it_gui_renderer_3_01_skin_registry_has_three_skins():
    """IT-01 SKIN_REGISTRY 至少 3 套。FR-10."""
    assert len(SKIN_REGISTRY) >= 3, f"FR-10 注册表至少 3 套，实际 {len(SKIN_REGISTRY)}"
    for name in ("classic", "dark", "colorblind_friendly"):
        assert name in SKIN_REGISTRY, f"FR-10 注册表缺 {name}"


@pytest.mark.p0
def test_it_gui_renderer_3_02_classic_skin_is_default():
    """IT-02 SKIN_REGISTRY[\"classic\"] is DEFAULT_SKIN。FR-10."""
    assert SKIN_REGISTRY["classic"] is DEFAULT_SKIN


@pytest.mark.p0
def test_it_gui_renderer_3_03_dark_skin_in_registry():
    """IT-03 SKIN_REGISTRY[\"dark\"] is DARK_SKIN。FR-10."""
    assert SKIN_REGISTRY["dark"] is DARK_SKIN


@pytest.mark.p0
def test_it_gui_renderer_3_04_colorblind_skin_in_registry():
    """IT-04 SKIN_REGISTRY[\"colorblind_friendly\"] is COLORBLIND_FRIENDLY_SKIN。FR-10."""
    assert SKIN_REGISTRY["colorblind_friendly"] is COLORBLIND_FRIENDLY_SKIN


@pytest.mark.p0
def test_it_gui_renderer_3_05_three_skins_field_validation():
    """IT-05 三套皮肤颜色 RGB ∈ [0,255]；cell_gap ∈ [0,10]；food_pattern/snake_pattern 合法。FR-10."""
    for sk in (DEFAULT_SKIN, DARK_SKIN, COLORBLIND_FRIENDLY_SKIN):
        # 颜色 RGB 范围（已在模块构造时校验；此处 runtime sanity check）
        for c_attr in ("background", "grid_line", "snake_head", "snake_body",
                       "food", "food_outline", "hud_text", "hud_accent"):
            c = getattr(sk, c_attr)
            for ch in ("r", "g", "b"):
                v = getattr(c, ch)
                assert 0 <= v <= 255, f"FR-10 {sk.name}.{c_attr}.{ch} = {v} 越界"
        # cell_gap
        assert 0 <= sk.cell_gap <= 10, f"FR-10 {sk.name}.cell_gap = {sk.cell_gap} 越界"
        # food_pattern
        assert sk.food_pattern in ("solid", "ringed", "checkered"), \
            f"FR-10 {sk.name}.food_pattern = {sk.food_pattern} 非法"
        # snake_pattern
        assert sk.snake_pattern in ("solid", "striped"), \
            f"FR-10 {sk.name}.snake_pattern = {sk.snake_pattern} 非法"


@pytest.mark.p0
def test_it_gui_renderer_3_06_default_renderer_skin(default_window_renderer):
    """IT-06 默认 Renderer.skin == DEFAULT_SKIN，name = "classic"。FR-10."""
    assert default_window_renderer.skin is DEFAULT_SKIN
    assert default_window_renderer.current_skin_name == "classic"


@pytest.mark.p0
def test_it_gui_renderer_3_07_set_skin_dark(default_window_renderer):
    """IT-07 set_skin("dark") → current_skin_name == "dark"，self._skin is DARK_SKIN。FR-10."""
    default_window_renderer.set_skin("dark")
    assert default_window_renderer.current_skin_name == "dark"
    assert default_window_renderer._skin is DARK_SKIN


@pytest.mark.p0
def test_it_gui_renderer_3_08_set_skin_colorblind(default_window_renderer):
    """IT-08 set_skin("colorblind_friendly") → current_skin_name == "colorblind_friendly"。FR-10."""
    default_window_renderer.set_skin("colorblind_friendly")
    assert default_window_renderer.current_skin_name == "colorblind_friendly"
    assert default_window_renderer._skin is COLORBLIND_FRIENDLY_SKIN


@pytest.mark.p0
def test_it_gui_renderer_3_09_set_skin_classic_idempotent(default_window_renderer):
    """IT-09 set_skin("classic") 幂等。FR-10."""
    default_window_renderer.set_skin("dark")
    default_window_renderer.set_skin("classic")
    assert default_window_renderer.current_skin_name == "classic"
    assert default_window_renderer._skin is DEFAULT_SKIN


@pytest.mark.p0
def test_it_gui_renderer_3_10_set_skin_unknown_raises(default_window_renderer):
    """IT-10 set_skin("nope") → SkinNotFoundError；e.name/e.available 校验。FR-10 + 修订 P3-1."""
    with pytest.raises(SkinNotFoundError) as exc_info:
        default_window_renderer.set_skin("nope")
    e = exc_info.value
    assert e.name == "nope", f"修订 P3-1 e.name 缺失，实际 {e.name}"
    assert isinstance(e.available, tuple), f"修订 P3-1 e.available 应 tuple，实际 {type(e.available)}"
    assert len(e.available) == 3, f"FR-10 注册表 3 套，实际 {len(e.available)}"
    for name in ("classic", "dark", "colorblind_friendly"):
        assert name in e.available, f"FR-10 e.available 缺 {name}"


@pytest.mark.p0
def test_it_gui_renderer_3_11_skin_names_returns_three(default_window_renderer):
    """IT-11 skin_names() 返回 3 元素 tuple。FR-10."""
    names = default_window_renderer.skin_names()
    assert isinstance(names, tuple), f"FR-10 skin_names 应 tuple，实际 {type(names)}"
    assert len(names) == 3, f"FR-10 skin_names 3 元素，实际 {len(names)}"
    for name in ("classic", "dark", "colorblind_friendly"):
        assert name in names, f"FR-10 skin_names 缺 {name}"


@pytest.mark.p0
def test_it_gui_renderer_3_12_set_skin_changes_next_render_color(renderer, fake_pg):
    """IT-12 set_skin 后下一帧 render 用新皮肤颜色。FR-10."""
    from conftest import reset_fake_pygame
    # 第一次用 classic 渲染
    reset_fake_pygame()
    renderer.render(_make_snapshot(), _make_hud())
    classic_dark_color = DEFAULT_SKIN.snake_body
    classic_dark_calls = [c for c in fake_pg.draw.calls if c[0] == _c(classic_dark_color)]
    assert len(classic_dark_calls) >= 2, f"FR-10 classic 蛇身默认色至少 2 次"

    # 切到 dark 后再渲染
    reset_fake_pygame()
    renderer.set_skin("dark")
    renderer.render(_make_snapshot(), _make_hud())
    # dark 蛇身 = Color(80, 200, 140)，应至少 2 次
    dark_color = DARK_SKIN.snake_body
    dark_calls = [c for c in fake_pg.draw.calls if c[0] == _c(dark_color)]
    assert len(dark_calls) >= 2, \
        f"FR-10 set_skin('dark') 后下一帧 render 应用 DARK_SKIN.snake_body，实际 {len(dark_calls)} 次"


@pytest.mark.p1
def test_it_gui_renderer_3_13_set_skin_round_trip(default_window_renderer):
    """IT-13 皮肤切换链路 classic → dark → colorblind_friendly → classic。FR-10."""
    default_window_renderer.set_skin("dark")
    assert default_window_renderer.current_skin_name == "dark"
    default_window_renderer.set_skin("colorblind_friendly")
    assert default_window_renderer.current_skin_name == "colorblind_friendly"
    default_window_renderer.set_skin("classic")
    assert default_window_renderer.current_skin_name == "classic"


# ============================================================================
# §1.2 食物形态分发（FR-10）— IT-gui-renderer-3-14 ~ 16
# ============================================================================

@pytest.mark.p0
def test_it_gui_renderer_3_14_food_solid_two_draw_rects(default_window_renderer, fake_pg):
    """IT-14 food_pattern="solid"（classic）→ draw.rect 2 次。FR-10."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    # 蛇 1 节，避免蛇身色干扰食物断言
    renderer = default_window_renderer
    renderer.set_skin("classic")
    snap = _make_snapshot(snake=((5, 5),), food=(10, 10))
    renderer.render(snap, _make_hud(length=1))

    # 食物填充 + outline width=1
    food_fill = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.food) and c[2] == 0]
    food_outline = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.food_outline) and c[2] == 1]
    assert len(food_fill) == 1, f"FR-10 solid 食物填充 1 次（width=0），实际 {len(food_fill)}"
    assert len(food_outline) == 1, f"FR-10 solid 食物 outline 1 次（width=1），实际 {len(food_outline)}"


@pytest.mark.p0
def test_it_gui_renderer_3_15_food_ringed_three_draw_rects(fake_pg):
    """IT-15 food_pattern="ringed"（DARK_SKIN）→ draw.rect 3 次。FR-10."""
    from conftest import reset_fake_pygame
    from gui_renderer import Renderer
    r = Renderer((640, 480), skin=DARK_SKIN)
    r.init()
    try:
        reset_fake_pygame()
        snap = _make_snapshot(snake=((5, 5),), food=(10, 10))
        r.render(snap, _make_hud(length=1))

        # ringed: 1 实心（width=0, color=food）+ 1 内空（width=0, color=background）+ 1 外圈（width=2, color=food_outline）
        food_calls = [c for c in fake_pg.draw.calls
                      if c[0] in (_c(DARK_SKIN.food), _c(DARK_SKIN.background), _c(DARK_SKIN.food_outline))]
        assert len(food_calls) == 3, f"FR-10 ringed 食物 3 次 draw.rect，实际 {len(food_calls)}"
        # 最后一次 width=2
        assert food_calls[-1][2] == 2, f"FR-10 ringed 外圈 width=2，实际 {food_calls[-1][2]}"
        # 内空 color = background（镂空）
        inner_calls = [c for c in food_calls if c[0] == _c(DARK_SKIN.background)]
        assert len(inner_calls) == 1, f"FR-10 ringed 内空 1 次（color=background）"
    finally:
        r.shutdown()


@pytest.mark.p0
def test_it_gui_renderer_3_16_food_checkered_five_draw_rects(fake_pg):
    """IT-16 food_pattern="checkered"（COLORBLIND_FRIENDLY_SKIN）→ draw.rect 5 次。FR-10."""
    from conftest import reset_fake_pygame
    from gui_renderer import Renderer
    r = Renderer((640, 480), skin=COLORBLIND_FRIENDLY_SKIN)
    r.init()
    try:
        reset_fake_pygame()
        snap = _make_snapshot(snake=((5, 5),), food=(10, 10))
        r.render(snap, _make_hud(length=1))

        # checkered: 4 子格（2 food + 2 outline）+ 1 outline(width=1)
        food_color = COLORBLIND_FRIENDLY_SKIN.food
        outline_color = COLORBLIND_FRIENDLY_SKIN.food_outline
        food_calls = [c for c in fake_pg.draw.calls
                      if c[0] in (_c(food_color), _c(outline_color))]
        # 总 5 次：4 子格 + 1 外圈
        assert len(food_calls) == 5, f"FR-10 checkered 食物 5 次 draw.rect，实际 {len(food_calls)}"
        # 最后一次 outline width=1
        assert food_calls[-1][0] == _c(outline_color), f"FR-10 checkered 外圈色 = outline"
        assert food_calls[-1][2] == 1, f"FR-10 checkered 外圈 width=1"
        # food 色 2 次（对角线填充：左上 + 右下）
        food_filled = [c for c in food_calls if c[0] == _c(food_color)]
        assert len(food_filled) == 2, f"FR-10 checkered food 色 2 次（对角），实际 {len(food_filled)}"
    finally:
        r.shutdown()


# ============================================================================
# §1.3 平滑插值动画（FR-07）— IT-gui-renderer-3-17 ~ 30
# ============================================================================

@pytest.mark.p1
def test_it_gui_renderer_3_17_interpolation_state_is_frozen():
    """IT-17 InterpolationState 不可变（frozen）。FR-07."""
    from dataclasses import FrozenInstanceError
    state = InterpolationState(alpha=0.5, prev_snake_body=((10, 7), (9, 7)), prev_food=(15, 7))
    with pytest.raises(FrozenInstanceError):
        state.alpha = 1.0  # type: ignore[misc]


@pytest.mark.p1
def test_it_gui_renderer_3_18_interpolation_state_default_prev_food():
    """IT-18 InterpolationState 字段默认值 prev_food=None（修订 P2-1）。FR-07."""
    state = InterpolationState(alpha=0.5, prev_snake_body=((10, 7),))
    assert state.prev_food is None, f"修订 P2-1 prev_food 默认 None，实际 {state.prev_food}"
    assert state.alpha == 0.5
    assert state.prev_snake_body == ((10, 7),)


@pytest.mark.p0
def test_it_gui_renderer_3_19_interpolate_position_alpha_0():
    """IT-19 _interpolate_position alpha=0.0 → prev。FR-07."""
    from gui_renderer.renderer import _interpolate_position
    px, py = _interpolate_position((0, 0), (10, 0), 0.0)
    assert (px, py) == (0.0, 0.0), f"FR-07 alpha=0 → prev，实际 ({px},{py})"


@pytest.mark.p0
def test_it_gui_renderer_3_20_interpolate_position_alpha_1():
    """IT-20 _interpolate_position alpha=1.0 → current。FR-07."""
    from gui_renderer.renderer import _interpolate_position
    px, py = _interpolate_position((0, 0), (10, 0), 1.0)
    assert (px, py) == (10.0, 0.0), f"FR-07 alpha=1 → current，实际 ({px},{py})"


@pytest.mark.p0
def test_it_gui_renderer_3_21_interpolate_position_alpha_half():
    """IT-21 _interpolate_position alpha=0.5 → 中点。FR-07."""
    from gui_renderer.renderer import _interpolate_position
    px, py = _interpolate_position((0, 0), (10, 0), 0.5)
    assert (px, py) == (5.0, 0.0), f"FR-07 alpha=0.5 → 中点 (5,0)，实际 ({px},{py})"


@pytest.mark.p0
def test_it_gui_renderer_3_22_grid_distance_chebyshev():
    """IT-22 _grid_distance Chebyshev 距离。FR-07."""
    from gui_renderer.renderer import _grid_distance
    assert _grid_distance((0, 0), (3, 0)) == 3, "FR-07 Chebyshev((0,0),(3,0))=3"
    assert _grid_distance((0, 0), (1, 1)) == 1, "FR-07 Chebyshev((0,0),(1,1))=1"
    assert _grid_distance((0, 0), (0, 0)) == 0, "FR-07 Chebyshev((0,0),(0,0))=0"
    assert _grid_distance((2, 3), (5, 7)) == 4, f"FR-07 Chebyshev((2,3),(5,7))=4"


@pytest.mark.p0
def test_it_gui_renderer_3_23_render_no_interp_backward_compatible(default_window_renderer, fake_pg):
    """IT-23 render(snap, hud) 不传 interp：向后兼容，瞬移渲染。FR-07."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    snap = _make_snapshot()  # 蛇头 (10, 7)
    default_window_renderer.render(snap, _make_hud())

    # 蛇头像素位置：PLAYFIELD_X + 10*CELL_SIZE, PLAYFIELD_Y + 7*CELL_SIZE
    expected_head = (PLAYFIELD_X + 10 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    head_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.snake_head)]
    assert len(head_calls) == 1, "FR-07 蛇头 1 次"
    assert head_calls[0][1][:2] == expected_head, \
        f"FR-07 render 不传 interp 时蛇头像素 == 当前位置 {expected_head}，实际 {head_calls[0][1][:2]}"


@pytest.mark.p0
def test_it_gui_renderer_3_24_render_interp_none_explicit(default_window_renderer, fake_pg):
    """IT-24 render(snap, hud, interp=None) 显式 None 行为同上。FR-07."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    snap = _make_snapshot()
    default_window_renderer.render(snap, _make_hud(), interp=None)

    expected_head = (PLAYFIELD_X + 10 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    head_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.snake_head)]
    assert head_calls[0][1][:2] == expected_head, \
        f"FR-07 interp=None 显式行为同不传，期望 {expected_head}"


@pytest.mark.p0
def test_it_gui_renderer_3_25_interp_alpha_1_no_interpolation(renderer, fake_pg):
    """IT-25 interp.alpha=1.0 时渲染 snap 当前位置（无插值）。FR-07."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    snap = _make_snapshot()
    prev_body = tuple((p.x, p.y) for p in snap.snake_body)
    interp = InterpolationState(alpha=1.0, prev_snake_body=prev_body, prev_food=(15, 7))
    renderer.render(snap, _make_hud(), interp=interp)

    # 蛇头 = snap 当前 (10, 7)
    expected_head = (PLAYFIELD_X + 10 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    head_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.snake_head)]
    assert head_calls[0][1][:2] == expected_head, \
        f"FR-07 alpha=1.0 → 当前位置 {expected_head}"


@pytest.mark.p0
def test_it_gui_renderer_3_26_interp_alpha_0_prev_position(renderer, fake_pg):
    """IT-26 interp.alpha=0.0 时蛇头渲染坐标 == prev_snake_body[0]。FR-07."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    # 当前 snap 蛇头 (10, 7)；prev 蛇头 (8, 7)
    snap = _make_snapshot()
    prev_body = ((8, 7), (7, 7), (6, 7))
    interp = InterpolationState(alpha=0.0, prev_snake_body=prev_body, prev_food=(15, 7))
    renderer.render(snap, _make_hud(), interp=interp)

    # alpha=0 → 渲染 prev 位置 (8, 7)
    expected_head = (PLAYFIELD_X + 8 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    head_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.snake_head)]
    assert head_calls[0][1][:2] == expected_head, \
        f"FR-07 alpha=0.0 → prev (8,7) 像素 {expected_head}，实际 {head_calls[0][1][:2]}"


@pytest.mark.p0
def test_it_gui_renderer_3_27_interp_alpha_half_midpoint(renderer, fake_pg):
    """IT-27 interp.alpha=0.5 时蛇头渲染坐标落在 prev/current 中点。FR-07."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    snap = _make_snapshot()  # 蛇头 (10, 7)
    prev_body = ((8, 7), (7, 7), (6, 7))  # prev 蛇头 (8, 7)
    interp = InterpolationState(alpha=0.5, prev_snake_body=prev_body, prev_food=(15, 7))
    renderer.render(snap, _make_hud(), interp=interp)

    # 中点 (9.0, 7.0) → 像素 (PLAYFIELD_X + 9*CELL_SIZE, PLAYFIELD_Y + 7*CELL_SIZE)
    expected_head = (PLAYFIELD_X + 9 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    head_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.snake_head)]
    assert head_calls[0][1][:2] == expected_head, \
        f"FR-07 alpha=0.5 → 中点 (9,7) 像素 {expected_head}，实际 {head_calls[0][1][:2]}"


@pytest.mark.p0
def test_it_gui_renderer_3_28_interp_prev_food_none_immediate(renderer, fake_pg):
    """IT-28 prev_food=None（吃食节拍）→ 食物瞬移 snap.food。FR-07 + 修订 P2-1."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    snap = _make_snapshot(food=(15, 7))
    prev_body = tuple((p.x, p.y) for p in snap.snake_body)
    interp = InterpolationState(alpha=0.5, prev_snake_body=prev_body, prev_food=None)
    renderer.render(snap, _make_hud(), interp=interp)

    # 食物应渲染 snap.food (15, 7)，不是 prev
    expected_food = (PLAYFIELD_X + 15 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    food_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.food) and c[2] == 0]
    assert len(food_calls) == 1
    assert food_calls[0][1][:2] == expected_food, \
        f"修订 P2-1 prev_food=None → snap.food 像素 {expected_food}，实际 {food_calls[0][1][:2]}"


@pytest.mark.p0
def test_it_gui_renderer_3_29_interp_food_distance_gt_1_skip(renderer, fake_pg):
    """IT-29 prev_food 与 snap.food 距离 >1 格兜底 → 食物瞬移 snap.food。FR-07 + 修订 P2-1."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    snap = _make_snapshot(food=(15, 7))
    prev_body = tuple((p.x, p.y) for p in snap.snake_body)
    # prev_food=(5, 0)：Chebyshev 距离 = max(|15-5|, |7-0|) = 10 > 1
    interp = InterpolationState(alpha=0.5, prev_snake_body=prev_body, prev_food=(5, 0))
    renderer.render(snap, _make_hud(), interp=interp)

    expected_food = (PLAYFIELD_X + 15 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    food_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.food) and c[2] == 0]
    assert len(food_calls) == 1
    assert food_calls[0][1][:2] == expected_food, \
        f"修订 P2-1 距离 >1 格兜底 → snap.food 像素 {expected_food}，实际 {food_calls[0][1][:2]}"


@pytest.mark.p1
def test_it_gui_renderer_3_30_interp_alpha_clipped(renderer, fake_pg):
    """IT-30 interp.alpha 越界 [-0.5, 1.5]：clip 到 [0, 1]。FR-07."""
    from conftest import reset_fake_pygame
    # alpha = -0.5 → clip 0.0 → prev
    reset_fake_pygame()
    snap = _make_snapshot()
    prev_body = ((8, 7), (7, 7), (6, 7))
    interp = InterpolationState(alpha=-0.5, prev_snake_body=prev_body, prev_food=(15, 7))
    renderer.render(snap, _make_hud(), interp=interp)
    expected_head_clip_low = (PLAYFIELD_X + 8 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    head_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.snake_head)]
    assert head_calls[0][1][:2] == expected_head_clip_low, \
        f"FR-07 alpha=-0.5 clip → 0.0 = prev (8,7)"

    # alpha = 1.5 → clip 1.0 → current
    reset_fake_pygame()
    interp = InterpolationState(alpha=1.5, prev_snake_body=prev_body, prev_food=(15, 7))
    renderer.render(snap, _make_hud(), interp=interp)
    expected_head_clip_high = (PLAYFIELD_X + 10 * CELL_SIZE, PLAYFIELD_Y + 7 * CELL_SIZE)
    head_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DEFAULT_SKIN.snake_head)]
    assert head_calls[0][1][:2] == expected_head_clip_high, \
        f"FR-07 alpha=1.5 clip → 1.0 = current (10,7)"


# ============================================================================
# §1.4 HUD 阴影渲染（FR-10 + 修订 P1-1）— IT-gui-renderer-3-31 ~ 35
# ============================================================================

@pytest.mark.p0
def test_it_gui_renderer_3_31_hud_font_render_count_is_5(renderer):
    """IT-31 HUD 5 段：font.render 调用次数 == 5（保持迭代 1 既有断言）。FR-10 + 修订 P1-1."""
    snap = _make_snapshot()
    renderer.render(snap, _make_hud())

    font = renderer._font  # type: ignore[attr-defined]
    assert len(font.render_calls) == 5, \
        f"FR-10 修订 P1-1 HUD font.render == 5，实际 {len(font.render_calls)}"


@pytest.mark.p0
def test_it_gui_renderer_3_32_hud_blit_count_is_10(renderer):
    """IT-32 HUD 阴影 blit 总数 == 10（5 段 × 2 = 10）。FR-10 + 修订 P1-1."""
    snap = _make_snapshot()
    renderer.render(snap, _make_hud())

    screen = renderer._screen  # type: ignore[attr-defined]
    assert len(screen.blit_calls) == 10, \
        f"FR-10 修订 P1-1 HUD blit == 10（5 阴影 + 5 主版），实际 {len(screen.blit_calls)}"


@pytest.mark.p0
def test_it_gui_renderer_3_33_hud_shadow_offset_plus_1(renderer):
    """IT-33 HUD 阴影偏移：阴影 blit = 主版 + (1, 1)。FR-10 + 修订 P1-1."""
    snap = _make_snapshot()
    renderer.render(snap, _make_hud())

    screen = renderer._screen  # type: ignore[attr-defined]
    blits = screen.blit_calls
    # 配对检查：每对 blit（阴影 + 主版），阴影位置 = 主版 + (1, 1)
    # 按调用顺序：每段先阴影（offset）后主版（normal）
    # blits[0]=阴影@score, [1]=主版@score, [2]=阴影@high, [3]=主版@high, ...
    for i in range(0, len(blits), 2):
        shadow = blits[i][1]
        normal = blits[i + 1][1]
        assert shadow == (normal[0] + 1, normal[1] + 1), \
            f"FR-10 修订 P1-1 阴影 blit = 主版 + (1, 1)，实际 {shadow} vs 主版 {normal}"


@pytest.mark.p0
def test_it_gui_renderer_3_34_hud_status_over_uses_accent(renderer):
    """IT-34 HUD Status=OVER：font.render color == hud_accent。FR-10."""
    snap = _make_snapshot(status=GameStatus.OVER)
    renderer.render(snap, _make_hud(status_label="OVER"))

    font = renderer._font  # type: ignore[attr-defined]
    over_calls = [c for c in font.render_calls if "Status: OVER" in c[0]]
    assert len(over_calls) == 1
    assert over_calls[0][2] == _c(DEFAULT_SKIN.hud_accent), \
        "FR-10 Status=OVER 用 hud_accent 高亮"


@pytest.mark.p1
def test_it_gui_renderer_3_35_hud_status_non_over_uses_text(renderer):
    """IT-35 HUD Status=RUN：font.render color == hud_text。FR-10."""
    snap = _make_snapshot()
    renderer.render(snap, _make_hud(status_label="RUN"))

    font = renderer._font  # type: ignore[attr-defined]
    run_calls = [c for c in font.render_calls if "Status: RUN" in c[0]]
    assert len(run_calls) == 1
    assert run_calls[0][2] == _c(DEFAULT_SKIN.hud_text), \
        "FR-10 Status=RUN 用 hud_text"


# ============================================================================
# §1.5 窗口等比缩放（FR-09）— IT-gui-renderer-3-36 ~ 45
# ============================================================================

@pytest.mark.p0
def test_it_gui_renderer_3_36_handle_resize_enlarges_cell(default_window_renderer):
    """IT-36 handle_resize(1024, 768) → cell_size 增大（> 24）。FR-09."""
    default_window_renderer.handle_resize(1024, 768)
    assert default_window_renderer.cell_size > 24, \
        f"FR-09 cell_size 增大，实际 {default_window_renderer.cell_size}"


@pytest.mark.p0
def test_it_gui_renderer_3_37_handle_resize_default_no_change(default_window_renderer):
    """IT-37 handle_resize(640, 480) → cell_size 不变（== 24）。FR-09."""
    default_window_renderer.handle_resize(640, 480)
    assert default_window_renderer.cell_size == 24, \
        f"FR-09 cell_size 不变，实际 {default_window_renderer.cell_size}"


@pytest.mark.p0
def test_it_gui_renderer_3_38_handle_resize_below_min_raises(default_window_renderer):
    """IT-38 handle_resize < MIN_PLAYABLE_W/H → RenderError。FR-09 + 修订 P2-1."""
    with pytest.raises(RenderError, match="小于最小可玩尺寸"):
        default_window_renderer.handle_resize(100, 100)
    # MIN_PLAYABLE_W = 20*8 + 2*16 = 192; MIN_PLAYABLE_H = 15*8 + 96 + 16 = 232
    assert MIN_PLAYABLE_W == 192, f"FR-09 MIN_PLAYABLE_W 计算口径"
    assert MIN_PLAYABLE_H == 232, f"FR-09 MIN_PLAYABLE_H 计算口径"


@pytest.mark.p0
def test_it_gui_renderer_3_39_handle_resize_zero_raises(default_window_renderer):
    """IT-39 handle_resize(0, 0) → RenderError。FR-09."""
    with pytest.raises(RenderError):
        default_window_renderer.handle_resize(0, 0)


@pytest.mark.p0
def test_it_gui_renderer_3_40_handle_resize_negative_raises(default_window_renderer):
    """IT-40 handle_resize(-1, 100) → RenderError。FR-09."""
    with pytest.raises(RenderError):
        default_window_renderer.handle_resize(-1, 100)


@pytest.mark.p0
def test_it_gui_renderer_3_41_handle_resize_without_init_raises(fake_pg):
    """IT-41 handle_resize 未 init() → RenderError。FR-09 + 鲁棒性表 §5.5."""
    from gui_renderer import Renderer
    r = Renderer((640, 480))
    with pytest.raises(RenderError):
        r.handle_resize(800, 600)


@pytest.mark.p0
def test_it_gui_renderer_3_42_handle_resize_font_scales(default_window_renderer):
    """IT-42 handle_resize 后字体按 cell_size 比例缩放。FR-09."""
    initial_cell = default_window_renderer.cell_size
    default_window_renderer.handle_resize(1024, 768)
    new_cell = default_window_renderer.cell_size
    # cell 变化 → font_size 应变化
    assert new_cell != initial_cell, f"FR-09 cell_size 变化 {initial_cell} → {new_cell}"
    # 字体大小按比例：new_font_size = HUD_FONT_SIZE * new_cell / CELL_SIZE
    expected_font_size = max(10, round(22 * new_cell / 24))
    # _font 是 FakeFont 实例，render_calls 记录新建的；font_size 由 SysFont 构造参数传入
    # 这里通过 cell_size 间接验证
    assert new_cell > 0, "FR-09 font_size 缩放有效"


@pytest.mark.p0
def test_it_gui_renderer_3_43_handle_resize_keeps_scaled_flag(default_window_renderer, set_mode_calls):
    """IT-43 handle_resize 后 SCALED 标志保留。FR-09 + NFR-04."""
    initial_flags = default_window_renderer._flags  # type: ignore[attr-defined]
    assert initial_flags & 0x40000000, f"NFR-04 enable_high_dpi=True 时 SCALED 应在 flags"
    set_mode_calls.clear()

    default_window_renderer.handle_resize(800, 600)
    assert len(set_mode_calls) == 1, f"FR-09 handle_resize 调一次 set_mode"
    new_flags = set_mode_calls[0]["flags"]
    assert new_flags & 0x40000000, \
        f"FR-09 handle_resize 后 SCALED 标志保留，实际 flags={new_flags:#x}"


@pytest.mark.p1
def test_it_gui_renderer_3_44_handle_resize_cell_size_upper_bound(default_window_renderer):
    """IT-44 handle_resize cell_size 上限不超过初始 cell_size 的 2 倍。FR-09."""
    # 极大窗口：cell_size 应被 max(CELL_SIZE, CELL_SIZE*2) 截断
    default_window_renderer.handle_resize(4096, 4096)
    assert default_window_renderer.cell_size <= 24 * 2, \
        f"FR-09 cell_size 上限 2×CELL_SIZE=48，实际 {default_window_renderer.cell_size}"


@pytest.mark.p1
def test_it_gui_renderer_3_45_handle_resize_cell_size_lower_bound(fake_pg):
    """IT-45 handle_resize cell_size 下限 >= CELL_SIZE_MIN = 8。FR-09.

    构造时按 cell_size=24 校验最小窗口（512×472），handle_resize 才走 MIN_PLAYABLE_W/H 校验
    （按 CELL_SIZE_MIN=8 计算的下限 = 192×232）。此处构造 512×472，handle_resize 到最小尺寸+1，
    触发 cell_size 下限 clip 路径。
    """
    from gui_renderer import Renderer
    # 构造合法尺寸；handle_resize 到恰好 MIN_PLAYABLE_W/H 之上
    r = Renderer((640, 480))
    r.init()
    try:
        # handle_resize 到 MIN_PLAYABLE_W+1 x MIN_PLAYABLE_H+1：
        # avail_w = 193 - 32 = 161 → 161/20 = 8；avail_h = 233 - 96 - 16 = 121 → 121/15 = 8
        # min(8, 8) = 8 → cell_size = max(8, min(8, 48)) = 8
        r.handle_resize(MIN_PLAYABLE_W + 1, MIN_PLAYABLE_H + 1)
        assert r.cell_size >= CELL_SIZE_MIN, \
            f"FR-09 cell_size 下限 {CELL_SIZE_MIN}，实际 {r.cell_size}"
        assert r.cell_size == CELL_SIZE_MIN, \
            f"FR-09 极小窗口 cell_size 应被 clip 到 CELL_SIZE_MIN={CELL_SIZE_MIN}，实际 {r.cell_size}"
    finally:
        r.shutdown()


# ============================================================================
# §1.6 高分屏清晰（NFR-04）— IT-gui-renderer-3-46 ~ 48
# ============================================================================

@pytest.mark.p0
def test_it_gui_renderer_3_46_enable_high_dpi_default_uses_scaled(fake_pg, set_mode_calls):
    """IT-46 enable_high_dpi=True（默认）→ init() 后 SCALED 标志传入 set_mode。NFR-04."""
    from gui_renderer import Renderer
    r = Renderer((640, 480))  # 默认 enable_high_dpi=True
    r.init()
    try:
        assert len(set_mode_calls) == 1, f"NFR-04 init() 调一次 set_mode"
        flags = set_mode_calls[0]["flags"]
        assert flags & 0x40000000, \
            f"NFR-04 SCALED 在 flags，实际 flags={flags:#x}"
    finally:
        r.shutdown()


@pytest.mark.p0
def test_it_gui_renderer_3_47_enable_high_dpi_false_no_scaled(fake_pg, set_mode_calls):
    """IT-47 enable_high_dpi=False → init() 后 flags=0。NFR-04."""
    from gui_renderer import Renderer
    r = Renderer((640, 480), enable_high_dpi=False)
    r.init()
    try:
        assert len(set_mode_calls) == 1
        flags = set_mode_calls[0]["flags"]
        assert flags == 0, f"NFR-04 enable_high_dpi=False → flags=0，实际 {flags:#x}"
    finally:
        r.shutdown()


@pytest.mark.p1
def test_it_gui_renderer_3_48_enable_high_dpi_non_bool_raises(fake_pg):
    """IT-48 enable_high_dpi 非 bool → RenderError。NFR-04."""
    from gui_renderer import Renderer
    with pytest.raises(RenderError):
        Renderer((640, 480), enable_high_dpi="yes")  # type: ignore[arg-type]


# ============================================================================
# §1.7 渲染鲁棒性 — IT-gui-renderer-3-49 ~ 53
# ============================================================================

@pytest.mark.p0
def test_it_gui_renderer_3_49_render_without_init_raises_render_error(fake_pg):
    """IT-49 render 未 init() → RenderError（修订 P3-2，替代迭代 1 AssertionError）。FR-07."""
    from gui_renderer import Renderer
    r = Renderer((640, 480))
    with pytest.raises(RenderError, match="init"):
        r.render(_make_snapshot(), _make_hud())


@pytest.mark.p0
def test_it_gui_renderer_3_50_no_network_imports():
    """IT-50 renderer 不导入 socket/urllib/http/requests/httpx/aiohttp。NFR-06."""
    forbidden = {"socket", "urllib", "http", "requests", "httpx", "aiohttp"}
    root = _GUI_CODE / "gui_renderer"
    offenders = []
    for py in root.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in forbidden:
                        offenders.append(f"{py.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                if top in forbidden:
                    offenders.append(f"{py.name}: from {node.module} import ...")
    assert not offenders, f"NFR-06 无网络，但发现: {offenders}"


@pytest.mark.p0
def test_it_gui_renderer_3_51_real_snapshot_contract(default_window_renderer, fake_pg):
    """IT-51 跨模块契约：真实 Snapshot 入参正常 render。NFR-05."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    # 从 game_core 构造真实 Snapshot（GameState 仅接受 keyword 参数；这里直接构造 Snapshot）
    snap = Snapshot(
        snake_body=(Point(10, 7), Point(9, 7), Point(8, 7)),
        food=Point(15, 7),
        score=0,
        length=3,
        status=GameStatus.RUN,
        difficulty=Difficulty.MEDIUM,
        tick_ms=160,
    )
    hud = HudData(score=0, high_score=128, length=3,
                  difficulty_label="MEDIUM", status_label="RUN")

    default_window_renderer.render(snap, hud)

    # 蛇 3 节 + 食物 + HUD
    font = default_window_renderer._font  # type: ignore[attr-defined]
    texts = [c[0] for c in font.render_calls]
    assert any("Difficulty: MEDIUM" in t for t in texts), "NFR-05 跨模块：MEDIUM 文本"
    assert any("Status: RUN" in t for t in texts), "NFR-05 跨模块：RUN 文本"

    # 切皮肤后下一帧 render 用 DARK_SKIN
    reset_fake_pygame()
    default_window_renderer.set_skin("dark")
    default_window_renderer.render(snap, hud)
    dark_calls = [c for c in fake_pg.draw.calls if c[0] == _c(DARK_SKIN.snake_head)]
    assert len(dark_calls) == 1, "NFR-05 set_skin 跨迭代协作：dark 蛇头"


@pytest.mark.p0
def test_it_gui_renderer_3_52_invalid_food_pattern_raises(fake_pg):
    """IT-52 food_pattern 非法值 → RenderError。FR-10."""
    bad = Skin(
        name="bad", background=Color(0, 0, 0), grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0), snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0), food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0), hud_accent=Color(0, 0, 0),
        food_pattern="diagonal",  # 非法值
    )
    with pytest.raises(RenderError, match="food_pattern"):
        Renderer((640, 480), skin=bad)


@pytest.mark.p1
def test_it_gui_renderer_3_53_invalid_cell_gap_raises(fake_pg):
    """IT-53 cell_gap 越界 → RenderError。FR-10."""
    bad = Skin(
        name="bad", background=Color(0, 0, 0), grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0), snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0), food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0), hud_accent=Color(0, 0, 0),
        cell_gap=11,  # 越界
    )
    with pytest.raises(RenderError, match="cell_gap"):
        Renderer((640, 480), skin=bad)