"""Renderer fps_metric 测试：P95 / FPS 计算 + deque 容量。"""
import pytest

from gui_renderer.types import FpsMetric


def test_fpsmetric_default_capacity_is_120():
    """samples 容量 = 120（设计 §1.5 / §4.7）。"""
    m = FpsMetric()
    assert m.samples.maxlen == 120


def test_fpsmetric_default_p95_and_fps_are_zero():
    """空 samples 时 p95_frame_ms = 0、fps = 0。"""
    m = FpsMetric()
    assert m.p95_frame_ms == 0.0
    assert m.fps == 0.0


def test_fpsmetric_overflow_keeps_only_last_120():
    """samples 容量上限 = 120（追加超过自动 deque 丢弃最旧）。"""
    m = FpsMetric()
    for v in range(200):
        m.samples.append(float(v))
    assert len(m.samples) == 120
    # 最旧应是 80（0..199 加入，保留最后 120 = 80..199）
    assert m.samples[0] == 80.0
    assert m.samples[-1] == 199.0


def test_fpsmetric_p95_quantiles_path():
    """样本数 >= 20 时 P95 = statistics.quantiles(...)[-1]。"""
    import statistics

    m = FpsMetric()
    values = list(range(10, 30))  # 20 个：10..29
    for v in values:
        m.samples.append(float(v))
    expected = statistics.quantiles(values, n=20)[-1]
    assert m.p95_frame_ms == pytest.approx(expected, abs=1e-6)


def test_fpsmetric_fps_calculation():
    """fps = 1000 / mean(samples)。"""
    m = FpsMetric()
    for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
        m.samples.append(v)
    assert m.fps == pytest.approx(1000.0 / 30.0, abs=1e-6)


def test_fpsmetric_p95_degrades_to_mean_for_lt_20():
    """样本数 < 20 时 P95 降级为 mean。"""
    m = FpsMetric()
    for v in [10.0, 20.0, 30.0]:
        m.samples.append(v)
    assert m.p95_frame_ms == pytest.approx(20.0, abs=1e-6)


def test_fpsmetric_fps_zero_when_mean_zero():
    """samples 全为 0 时 fps 仍为 0（mean=0 保护，避免除零）。"""
    m = FpsMetric()
    for _ in range(5):
        m.samples.append(0.0)
    assert m.fps == 0.0


def test_fpsmetric_via_renderer(renderer):
    """Renderer.fps_metric() 返回 FpsMetric 实例且与内部 _fps 一致。"""
    r = renderer
    metric = r.fps_metric()
    assert isinstance(metric, FpsMetric)
    assert metric is r._fps