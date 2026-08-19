"""types 模块测试：迭代 1 既有 + 迭代 3 增量（Skin 新字段 / InterpolationState）。

修订 P2-1：hud_shadow 字段已删除 → 不校验 hud_shadow。
修订 P2-2：InterpolatedCell 已删除 → 不测 InterpolatedCell。
"""
import pytest

from gui_renderer.types import (
    Color,
    FpsMetric,
    HudData,
    InterpolationState,
    Rect,
    Skin,
)


# ========================================================================
# 迭代 1 既有测试（保留）
# ========================================================================


def test_color_is_frozen():
    """Color 是 frozen dataclass。"""
    c = Color(10, 20, 30)
    with pytest.raises(Exception):
        c.r = 100  # type: ignore[misc]


def test_rect_is_frozen():
    """Rect 是 frozen dataclass。"""
    r = Rect(1, 2, 3, 4)
    with pytest.raises(Exception):
        r.x = 99  # type: ignore[misc]


def test_skin_is_frozen():
    """Skin 是 frozen dataclass。"""
    s = Skin(
        name="x",
        background=Color(0, 0, 0),
        grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0),
        snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0),
        food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0),
        hud_accent=Color(0, 0, 0),
    )
    with pytest.raises(Exception):
        s.name = "y"  # type: ignore[misc]


def test_huddata_field_access():
    """HudData 字段可访问。"""
    h = HudData(score=1, high_score=2, length=3, difficulty_label="EASY", status_label="RUN")
    assert h.score == 1 and h.high_score == 2 and h.length == 3
    assert h.difficulty_label == "EASY" and h.status_label == "RUN"


def test_huddata_is_frozen():
    """HudData 是 frozen dataclass。"""
    h = HudData(0, 0, 0, "EASY", "RUN")
    with pytest.raises(Exception):
        h.score = 99  # type: ignore[misc]


def test_fpsmetric_construct_with_samples():
    """FpsMetric 构造后可访问 samples。"""
    m = FpsMetric()
    assert m.samples.maxlen == 120


def test_fpsmetric_p95_uses_quantiles_when_samples_ge_20():
    """样本数 >= 20 时 P95 = statistics.quantiles(...)[-1]。"""
    import statistics

    m = FpsMetric()
    for v in range(10, 30):
        m.samples.append(float(v))
    expected = statistics.quantiles(list(range(10, 30)), n=20)[-1]
    assert m.p95_frame_ms == pytest.approx(expected, abs=1e-6)


def test_fpsmetric_p95_downgrades_to_mean_when_samples_lt_20():
    """样本数 < 20 时 P95 降级为 mean。"""
    m = FpsMetric()
    for v in [10.0, 20.0, 30.0]:
        m.samples.append(v)
    assert m.p95_frame_ms == pytest.approx(20.0, abs=1e-6)


def test_fpsmetric_fps_equals_1000_over_mean():
    """fps = 1000 / mean(samples)。"""
    m = FpsMetric()
    for v in [10.0, 20.0, 30.0]:
        m.samples.append(v)
    assert m.fps == pytest.approx(1000.0 / 20.0, abs=1e-6)


# ========================================================================
# 迭代 3 增量：Skin 新字段
# ========================================================================


def test_skin_new_fields_have_defaults_compat_with_iter1():
    """Skin 新增字段（cell_gap/food_pattern/snake_pattern）全部有默认值 → 迭代 1 字面量构造兼容。"""
    s = Skin(
        name="legacy",
        background=Color(0, 0, 0),
        grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0),
        snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0),
        food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0),
        hud_accent=Color(0, 0, 0),
    )
    # 字段默认值（r2 P3-3 统一 default_factory 写法）
    assert s.cell_gap == 1
    assert s.food_pattern == "solid"
    assert s.snake_pattern == "solid"


def test_skin_new_fields_explicit_overrides_work():
    """Skin 新增字段显式赋值生效。"""
    s = Skin(
        name="explicit",
        background=Color(0, 0, 0),
        grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0),
        snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0),
        food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0),
        hud_accent=Color(0, 0, 0),
        cell_gap=2,
        food_pattern="ringed",
        snake_pattern="striped",
    )
    assert s.cell_gap == 2
    assert s.food_pattern == "ringed"
    assert s.snake_pattern == "striped"


def test_skin_does_not_have_hud_shadow_field():
    """修订 P2-1：hud_shadow 字段已删除（无消费点）。"""
    s = Skin(
        name="x",
        background=Color(0, 0, 0),
        grid_line=Color(0, 0, 0),
        snake_head=Color(0, 0, 0),
        snake_body=Color(0, 0, 0),
        food=Color(0, 0, 0),
        food_outline=Color(0, 0, 0),
        hud_text=Color(0, 0, 0),
        hud_accent=Color(0, 0, 0),
    )
    assert not hasattr(s, "hud_shadow")


# ========================================================================
# 迭代 3 增量：InterpolationState
# ========================================================================


def test_interpolationstate_constructs_with_all_fields():
    """InterpolationState 显式构造所有字段。"""
    state = InterpolationState(
        alpha=0.5,
        prev_snake_body=((1, 1), (1, 2), (1, 3)),
        prev_food=(5, 5),
    )
    assert state.alpha == 0.5
    assert state.prev_snake_body == ((1, 1), (1, 2), (1, 3))
    assert state.prev_food == (5, 5)


def test_interpolationstate_is_frozen():
    """InterpolationState 是 frozen（设计 §1.5）。"""
    state = InterpolationState(
        alpha=0.5,
        prev_snake_body=((1, 1),),
        prev_food=(5, 5),
    )
    with pytest.raises(Exception):
        state.alpha = 0.9  # type: ignore[misc]


def test_interpolationstate_prev_food_optional_default_none():
    """prev_food 字段默认 None（修订 P2-1：吃食节拍语义）。"""
    state = InterpolationState(
        alpha=0.0,
        prev_snake_body=((1, 1),),
    )
    assert state.prev_food is None


def test_interpolationstate_alpha_1_means_no_interp():
    """alpha=1.0 表示完全插值到 current（无视觉插值效果）。"""
    state = InterpolationState(
        alpha=1.0,
        prev_snake_body=((0, 0),),
        prev_food=None,
    )
    assert state.alpha == 1.0


def test_interpolationstate_alpha_0_means_full_prev():
    """alpha=0.0 表示完全上一节拍。"""
    state = InterpolationState(
        alpha=0.0,
        prev_snake_body=((2, 2), (2, 3)),
        prev_food=(4, 4),
    )
    assert state.alpha == 0.0


# ========================================================================
# Rect 类型（迭代 1 公共类型保留；迭代 3 无新增消费点 — 设计 §1.4 修订 P2-2）
# ========================================================================


def test_rect_basic_construction():
    """Rect 可构造（迭代 1 公共类型；迭代 3 无新增消费点，仅保留）。"""
    r = Rect(x=10, y=20, w=100, h=200)
    assert r.x == 10 and r.y == 20
    assert r.w == 100 and r.h == 200
