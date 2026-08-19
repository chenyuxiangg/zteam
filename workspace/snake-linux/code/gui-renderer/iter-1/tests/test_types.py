"""types 模块：Color/Rect/Skin/HudData/FpsMetric 的不可变与派生属性测试。"""
from collections import deque

import pytest

from gui_renderer.types import Color, FpsMetric, HudData, Rect, Skin


# ----- Color / Rect -----

def test_color_is_frozen():
    """Color 是 frozen dataclass，字段赋值应抛 FrozenInstanceError。"""
    c = Color(10, 20, 30)
    with pytest.raises(Exception):
        c.r = 99  # type: ignore[misc]


def test_rect_is_frozen():
    """Rect 是 frozen dataclass。"""
    r = Rect(0, 0, 100, 50)
    with pytest.raises(Exception):
        r.x = 10  # type: ignore[misc]


# ----- Skin -----

def test_skin_is_frozen():
    """Skin 是 frozen dataclass。"""
    s = Skin(
        name="t",
        background=Color(0, 0, 0),
        grid_line=Color(1, 1, 1),
        snake_head=Color(2, 2, 2),
        snake_body=Color(3, 3, 3),
        food=Color(4, 4, 4),
        food_outline=Color(5, 5, 5),
        hud_text=Color(6, 6, 6),
        hud_accent=Color(7, 7, 7),
    )
    with pytest.raises(Exception):
        s.name = "x"  # type: ignore[misc]


# ----- HudData -----

def test_huddata_field_access():
    """HudData 字段读取正常。"""
    hud = HudData(
        score=42,
        high_score=128,
        length=15,
        difficulty_label="MEDIUM",
        status_label="RUN",
    )
    assert hud.score == 42
    assert hud.high_score == 128
    assert hud.length == 15
    assert hud.difficulty_label == "MEDIUM"
    assert hud.status_label == "RUN"


def test_huddata_is_frozen():
    """HudData 不可变。"""
    hud = HudData(0, 0, 0, "EASY", "RUN")
    with pytest.raises(Exception):
        hud.score = 1  # type: ignore[misc]


# ----- FpsMetric -----

def test_fpsmetric_construct_with_samples():
    """FpsMetric 构造后 samples 是 deque，初始为空，p95/fps=0。"""
    m = FpsMetric()
    assert isinstance(m.samples, deque)
    assert len(m.samples) == 0
    assert m.p95_frame_ms == 0.0
    assert m.fps == 0.0


def test_fpsmetric_p95_downgrades_to_mean_when_samples_lt_20():
    """样本数 < 20 时 P95 降级为 mean（避免 statistics.quantiles 抛错）。"""
    m = FpsMetric()
    for v in [10.0, 20.0, 30.0]:
        m.samples.append(v)
    # mean = 20, samples < 20 → p95_frame_ms 应等于 mean
    assert m.p95_frame_ms == pytest.approx(20.0, abs=1e-6)
    # fps = 1000 / mean
    assert m.fps == pytest.approx(1000.0 / 20.0, abs=1e-6)


def test_fpsmetric_fps_equals_1000_over_mean():
    """fps = 1000 / mean(samples)（样本充足也按同样规则）。"""
    m = FpsMetric()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
        m.samples.append(v)
    mean = 30.0
    assert m.fps == pytest.approx(1000.0 / mean, abs=1e-6)


def test_fpsmetric_p95_uses_quantiles_when_samples_ge_20():
    """样本数 >= 20 时 P95 走 statistics.quantiles 路径。"""
    import statistics
    m = FpsMetric()
    # 20 个样本，10..29 ms
    values = list(range(10, 30))
    for v in values:
        m.samples.append(float(v))
    expected = statistics.quantiles(values, n=20)[-1]  # 第 95 分位
    assert m.p95_frame_ms == pytest.approx(expected, abs=1e-6)