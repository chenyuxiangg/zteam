"""G4-3 性能指标常量 UT（UT PERF-1）。

迭代 4 增量：性能常量值正确性（与设计 §1.2 对齐）：
- TARGET_FPS = 60
- P95_FRAME_TIME_MS_MAX = 25.0
- INPUT_LATENCY_TICKS_MAX = 1
- TICK_MS_HARD_MAX_RATIO = 0.5
- MEMORY_PEAK_MB_MAX = 300
- CPU_IDLE_PERCENT_MAX = 10.0
- BENCH_DURATION_SECONDS = 60
- BENCH_AI_DIRECTION_SWITCH_INTERVAL_S = 0.5
"""
from __future__ import annotations


class TestPerfConstantsValues:
    """PERF-1：性能常量值正确性。"""

    def test_target_fps(self) -> None:
        from game_app.perf import TARGET_FPS
        assert TARGET_FPS == 60

    def test_p95_frame_time_ms_max(self) -> None:
        from game_app.perf import P95_FRAME_TIME_MS_MAX
        assert P95_FRAME_TIME_MS_MAX == 25.0

    def test_input_latency_ticks_max(self) -> None:
        from game_app.perf import INPUT_LATENCY_TICKS_MAX
        assert INPUT_LATENCY_TICKS_MAX == 1

    def test_tick_ms_hard_max_ratio(self) -> None:
        from game_app.perf import TICK_MS_HARD_MAX_RATIO
        assert TICK_MS_HARD_MAX_RATIO == 0.5

    def test_memory_peak_mb_max(self) -> None:
        from game_app.perf import MEMORY_PEAK_MB_MAX
        assert MEMORY_PEAK_MB_MAX == 300

    def test_cpu_idle_percent_max(self) -> None:
        from game_app.perf import CPU_IDLE_PERCENT_MAX
        assert CPU_IDLE_PERCENT_MAX == 10.0

    def test_bench_duration_seconds(self) -> None:
        from game_app.perf import BENCH_DURATION_SECONDS
        assert BENCH_DURATION_SECONDS == 60

    def test_bench_ai_direction_switch_interval(self) -> None:
        from game_app.perf import BENCH_AI_DIRECTION_SWITCH_INTERVAL_S
        assert BENCH_AI_DIRECTION_SWITCH_INTERVAL_S == 0.5

    def test_all_constants_are_int_or_float(self) -> None:
        """常量类型约束：TARGET_FPS/MEMORY_PEAK_MB_MAX 等应为 int 或 float（避免 None）。"""
        from game_app import perf
        for name in ["TARGET_FPS", "P95_FRAME_TIME_MS_MAX", "MEMORY_PEAK_MB_MAX",
                     "BENCH_DURATION_SECONDS", "TICK_MS_HARD_MAX_RATIO",
                     "CPU_IDLE_PERCENT_MAX", "BENCH_AI_DIRECTION_SWITCH_INTERVAL_S",
                     "INPUT_LATENCY_TICKS_MAX"]:
            v = getattr(perf, name)
            assert isinstance(v, (int, float)), f"{name} 应为数值类型，得到 {type(v)}"
            assert v > 0, f"{name} 应 > 0，得到 {v}"


class TestPerfConstantsInvariants:
    """不变量：TARGET_FPS * P95_FRAME_TIME_MS_MAX / 1000 应 ≥ 1（确保 P95 上限合理）。"""

    def test_p95_threshold_consistent_with_target_fps(self) -> None:
        """NFR-01：60 FPS → 每帧 16.67ms；P95 上限 25ms 留有缓冲（合理）。"""
        from game_app.perf import TARGET_FPS, P95_FRAME_TIME_MS_MAX
        frame_budget = 1000.0 / TARGET_FPS  # ≈ 16.67ms
        # P95 上限应 ≥ 单帧预算（否则不可能达成 60FPS）
        assert P95_FRAME_TIME_MS_MAX >= frame_budget