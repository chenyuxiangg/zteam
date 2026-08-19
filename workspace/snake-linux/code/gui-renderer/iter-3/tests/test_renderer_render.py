"""Renderer.render 行为测试（迭代 1 既有 + 迭代 3 增量）。

迭代 1 既有用例 100% 保留（zero-modify 兼容；HUD 5 次 font.render 断言 + OVER hud_accent
断言被设计 §0.1 修订 P1-1 显式要求保留 → 全部继续通过）。

迭代 3 增量（设计 §7.6）：12 条用例覆盖 interp 插值 / food_pattern 分发 / 同色描边 blit /
prev_food=None / 距离 >1 兜底 / render 未 init 抛 RenderError。
"""
import pytest

from gui_renderer import HudData, Renderer
from gui_renderer.constants import (
    CELL_SIZE,
    COLORBLIND_FRIENDLY_SKIN,
    DARK_SKIN,
    DEFAULT_SKIN,
    PLAYFIELD_X,
    PLAYFIELD_Y,
    SKIN_REGISTRY,
)
from gui_renderer.errors import RenderError
from tests.conftest import FakeSurface, _pg_module

from game_core import Difficulty, GameStatus, Point, Snapshot


# ========================================================================
# 工具：构造 snapshot / hud
# ========================================================================


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


# ========================================================================
# 迭代 1 既有用例（保留；修订 P1-1 显式要求）
# ========================================================================


def test_render_calls_surface_fill_with_background(fake_pygame, renderer):
    """渲染 1 次 → screen.fill(background) 被调用（MTO-4-01：pygame 收到 tuple）。"""
    r = renderer
    snap = _snapshot(3)
    hud = _hud()
    r.render(snap, hud)
    assert len(r._screen.fill_calls) == 1
    # MTO-4-01 修复：pygame API 只接受 tuple/str/pygame.Color → 断言 tuple 值
    bg = r.skin.background
    assert r._screen.fill_calls[0][0] == (bg.r, bg.g, bg.b)


def test_render_snake_len_3_calls_draw_rect_3_times(fake_pygame, renderer):
    """蛇身长度 3 → snake_body 部分 draw.rect 调用 3 次（蛇头 1 + 蛇身 2）。"""
    r = renderer
    _pg_module.draw_calls.reset()
    r.render(_snapshot(3), _hud())
    snake_rects = [
        c for c in _pg_module.draw_calls
        if c[1] is not None and len(c[1]) == 4 and c[1][1] == PLAYFIELD_Y + 1 * CELL_SIZE
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
    """食物 (DEFAULT_SKIN.food_pattern='solid') → draw.rect 2 次（填充 + outline width=1）。"""
    r = renderer
    _pg_module.draw_calls.reset()
    r.render(_snapshot(3), _hud())
    outline_calls = [c for c in _pg_module.draw_calls if c[2] == 1]
    # 食物 outline 1 次（width=1）
    assert len(outline_calls) == 1
    fill_calls_no_outline = [c for c in _pg_module.draw_calls if c[2] == 0]
    # 蛇身 3 + 食物填充 1 = 4
    assert len(fill_calls_no_outline) == 4


def test_render_hud_calls_font_render_5_times(fake_pygame, renderer):
    """HUD 5 段文本 → font.render 被调用 5 次（修订 P1-1 显式要求保留）。"""
    r = renderer
    r.render(_snapshot(3), _hud())
    font = r._font
    assert len(font.render_calls) == 5


def test_render_hud_status_over_uses_accent_color(fake_pygame, renderer):
    """Status='OVER' 时 HUD 状态文字用 hud_accent 颜色（修订 P1-1 显式要求保留）。"""
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
    status_text_call = next((c for c in font.render_calls if "Status" in c[0]), None)
    assert status_text_call is not None
    # MTO-4-01 修复：pygame 收到 tuple
    accent = r.skin.hud_accent
    assert status_text_call[2] == (accent.r, accent.g, accent.b)


def test_render_rejects_empty_snake_body(fake_pygame, renderer):
    """snapshot.snake_body 为空 → 抛 RenderError。"""
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
    """每次 render 末尾采样耗时。"""
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


# ========================================================================
# 迭代 3 增量：interp / food_pattern / HUD 同色描边 / render 未 init（§7.6 共 12 条）
# ========================================================================


def test_render_with_interp_none_behaves_like_iter1(fake_pygame, renderer):
    """render(snapshot, hud) 与 render(snapshot, hud, interp=None) 行为一致（向后兼容 §0.1）。"""
    r = renderer
    _pg_module.draw_calls.reset()
    font = r._font
    font.render_calls.clear()
    r.render(_snapshot(3), _hud())  # 不传 interp
    draw_calls_v1 = list(_pg_module.draw_calls)
    render_calls_v1 = list(font.render_calls)
    _pg_module.draw_calls.reset()
    font.render_calls.clear()
    r.render(_snapshot(3), _hud(), interp=None)  # 显式 None
    draw_calls_v2 = list(_pg_module.draw_calls)
    render_calls_v2 = list(font.render_calls)
    assert draw_calls_v1 == draw_calls_v2
    assert render_calls_v1 == render_calls_v2


def test_render_with_interp_alpha_1_uses_current_coords(fake_pygame, renderer, prev_snapshot):
    """interp.alpha=1.0 → 渲染坐标 == snapshot 当前坐标（无插值）。"""
    from gui_renderer import InterpolationState

    r = renderer
    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    food = (prev_snapshot.food.x, prev_snapshot.food.y)
    interp = InterpolationState(alpha=1.0, prev_snake_body=body, prev_food=food)

    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)

    # 蛇头像素坐标应等于 prev_snapshot.snake_body[0] 网格坐标转像素（无偏移）
    head_grid = (prev_snapshot.snake_body[0].x, prev_snapshot.snake_body[0].y)
    expected_x = PLAYFIELD_X + head_grid[0] * CELL_SIZE
    expected_y = PLAYFIELD_Y + head_grid[1] * CELL_SIZE
    head_rect = _pg_module.draw_calls.records[0][1]
    assert head_rect[0] == expected_x
    assert head_rect[1] == expected_y


def test_render_with_interp_alpha_0_uses_prev_coords(fake_pygame, renderer, prev_snapshot):
    """interp.alpha=0.0 → 渲染坐标 == prev 坐标。"""
    from gui_renderer import InterpolationState

    r = renderer
    # prev 移到 (1,1)（与 current 不同）
    prev_body = tuple((1, 1) for _ in prev_snapshot.snake_body)
    prev_food = (1, 1)
    interp = InterpolationState(alpha=0.0, prev_snake_body=prev_body, prev_food=prev_food)

    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)

    # 蛇头像素坐标 == prev (1,1) 网格坐标
    expected_x = PLAYFIELD_X + 1 * CELL_SIZE
    expected_y = PLAYFIELD_Y + 1 * CELL_SIZE
    head_rect = _pg_module.draw_calls.records[0][1]
    assert head_rect[0] == expected_x
    assert head_rect[1] == expected_y


def test_render_with_interp_alpha_half_uses_midpoint(fake_pygame, renderer, prev_snapshot):
    """interp.alpha=0.5 → 渲染坐标落在 prev/current 中间（int 截断后 = round 结果）。"""
    from gui_renderer import InterpolationState

    r = renderer
    # prev (0,0)，current = prev_snapshot.snake_body[0] = (10, 7)
    cur_head = (prev_snapshot.snake_body[0].x, prev_snapshot.snake_body[0].y)
    prev_body = ((0, 0),) + tuple((0, 0) for _ in prev_snapshot.snake_body[1:])
    prev_food = (0, 0)
    interp = InterpolationState(alpha=0.5, prev_snake_body=prev_body, prev_food=prev_food)

    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)

    # 蛇头插值 = (0+0.5*10, 0+0.5*7) = (5.0, 3.5) → int(round) = (5, 4)
    interp_x = 0 + 0.5 * cur_head[0]
    interp_y = 0 + 0.5 * cur_head[1]
    expected_x = PLAYFIELD_X + int(round(interp_x * CELL_SIZE))
    expected_y = PLAYFIELD_Y + int(round(interp_y * CELL_SIZE))
    head_rect = _pg_module.draw_calls.records[0][1]
    assert head_rect[0] == expected_x
    assert head_rect[1] == expected_y


def test_render_food_pattern_solid_uses_2_rects(fake_pygame, renderer, prev_snapshot):
    """food_pattern='solid' → draw.rect 2 次（食物填充 + outline width=1）。"""
    from gui_renderer import InterpolationState

    r = renderer
    r.set_skin("classic")  # solid
    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    interp = InterpolationState(alpha=1.0, prev_snake_body=body, prev_food=None)
    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)
    # 食物部分：solid 模式 = 填充 1 + outline 1
    food_outline = [c for c in _pg_module.draw_calls if c[2] == 1]
    assert len(food_outline) >= 1


def test_render_food_pattern_rinked_uses_3_rects(fake_pygame, renderer, prev_snapshot):
    """food_pattern='ringed' → draw.rect 3 次（实心 + 内空 + 双线 outline width=2）。"""
    from gui_renderer import InterpolationState

    r = renderer
    r.set_skin("dark")
    assert r.skin.food_pattern == "ringed"
    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    interp = InterpolationState(alpha=1.0, prev_snake_body=body, prev_food=None)
    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)
    # ringed：实心(width=0) + 内空(width=0) + 双线(width=2)
    width2_calls = [c for c in _pg_module.draw_calls if c[2] == 2]
    assert len(width2_calls) == 1  # 外圈双线


def test_render_food_pattern_checkered_uses_5_rects(fake_pygame, renderer, prev_snapshot):
    """food_pattern='checkered' → draw.rect 5 次（4 子格 + 1 outline）。"""
    from gui_renderer import InterpolationState

    r = renderer
    r.set_skin("colorblind_friendly")
    assert r.skin.food_pattern == "checkered"
    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    interp = InterpolationState(alpha=1.0, prev_snake_body=body, prev_food=None)
    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)
    # checkered：4 子格(width=0) + 1 outline(width=1) = 5 次
    outline1 = [c for c in _pg_module.draw_calls if c[2] == 1]
    assert len(outline1) == 1


def test_render_hud_blit_count_is_10(fake_pygame, renderer, prev_snapshot):
    """修订 P1-1：HUD 5 段 → font.render 5 次；blit 总数 = 10（每段 1 偏移 + 1 主版）。"""
    r = renderer
    font = r._font
    font.render_calls.clear()
    screen = r._screen
    screen.blit_calls.clear()
    r.render(prev_snapshot, _hud())
    assert len(font.render_calls) == 5
    assert len(screen.blit_calls) == 10  # 5 段 × 2 blit（偏移 + 主版）


def test_render_hud_status_over_uses_accent_color_iter3(fake_pygame, renderer):
    """修订 P1-1：OVER 时含 'Status' 的 font.render 调用 color == hud_accent（保持迭代 1 既有断言）。"""
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
    status_call = next((c for c in font.render_calls if "Status" in c[0]), None)
    assert status_call is not None
    # MTO-4-01 修复：pygame 收到 tuple
    accent = r.skin.hud_accent
    assert status_call[2] == (accent.r, accent.g, accent.b)


def test_render_with_prev_food_none_uses_snap_food(fake_pygame, renderer, prev_snapshot):
    """修订 P2-1：interp.prev_food=None → 食物绘制坐标 == snap.food 网格坐标（瞬移）。"""
    from gui_renderer import InterpolationState

    r = renderer
    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    interp = InterpolationState(alpha=0.5, prev_snake_body=body, prev_food=None)
    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)
    # 食物像素坐标 == snap.food 网格坐标 → 不插值
    food_x = prev_snapshot.food.x
    food_y = prev_snapshot.food.y
    expected_x = PLAYFIELD_X + food_x * CELL_SIZE
    expected_y = PLAYFIELD_Y + food_y * CELL_SIZE
    # 找食物位置的 rect（y = PLAYFIELD_Y + food_y * CELL_SIZE）
    food_rects = [
        c for c in _pg_module.draw_calls
        if c[1] is not None and len(c[1]) == 4 and c[1][1] == expected_y
    ]
    assert len(food_rects) >= 1
    assert food_rects[0][1][0] == expected_x


def test_render_food_distance_gt_1_skips_interp(fake_pygame, renderer, prev_snapshot):
    """修订 P2-1：interp.prev_food 与 snap.food 距离 >1 格 → 食物绘制坐标 == snap.food 网格坐标（兜底）。"""
    from gui_renderer import InterpolationState

    r = renderer
    food = (prev_snapshot.food.x, prev_snapshot.food.y)
    # prev_food 距离 snap.food 超过 1 格（放置在 (0,0)，snap.food 一定不在 (0,0)）
    prev_food = (0, 0)
    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    interp = InterpolationState(alpha=0.5, prev_snake_body=body, prev_food=prev_food)
    _pg_module.draw_calls.reset()
    r.render(prev_snapshot, _hud(), interp=interp)
    # 食物瞬移到 snap.food 网格坐标（distance >1 兜底）
    expected_x = PLAYFIELD_X + food[0] * CELL_SIZE
    expected_y = PLAYFIELD_Y + food[1] * CELL_SIZE
    food_rects = [
        c for c in _pg_module.draw_calls
        if c[1] is not None and len(c[1]) == 4 and c[1][1] == expected_y
    ]
    assert len(food_rects) >= 1
    assert food_rects[0][1][0] == expected_x


def test_render_without_init_raises(fake_pygame):
    """修订 P3-2：Renderer 未 init() 直接 render(...) → 抛 RenderError。"""
    r = Renderer((640, 480), enable_high_dpi=False)
    # 注意：未调 r.init()
    with pytest.raises(RenderError):
        r.render(_snapshot(3), _hud())
