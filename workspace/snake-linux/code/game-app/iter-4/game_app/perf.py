"""perf 模块：G4-3 性能指标常量（FR-14 + NFR-01/02）。

迭代 4 增量（设计 §1.2）：
- TARGET_FPS：目标帧率（NFR-01）
- P95_FRAME_TIME_MS_MAX：P95 帧时间上限（确保 60FPS 体验）
- INPUT_LATENCY_TICKS_MAX：输入延迟上限（节拍数）
- TICK_MS_HARD_MAX_RATIO：困难档节拍上限比例（确保档位间可感知差异）
- MEMORY_PEAK_MB_MAX：运行时内存峰值上限（NFR-02）
- CPU_IDLE_PERCENT_MAX：空闲画面 CPU 上限
- BENCH_DURATION_SECONDS：性能脚本基准时长
- BENCH_AI_DIRECTION_SWITCH_INTERVAL_S：基准中方向切换间隔

不变量（INV 派生）：
- TARGET_FPS * P95_FRAME_TIME_MS_MAX / 1000 ≥ 1（P95 上限合理）
- TICK_MS_HARD_MAX_RATIO ≤ 1.0（困难档不应慢于简单档）
"""
from __future__ import annotations

from typing import Final


# NFR-01 帧率 / 帧时间
TARGET_FPS: Final[int] = 60
P95_FRAME_TIME_MS_MAX: Final[float] = 25.0
INPUT_LATENCY_TICKS_MAX: Final[int] = 1

# 各档位节拍比例上限（确保档位间可感知差异——困难档 ≤ 简单档 50%）
TICK_MS_HARD_MAX_RATIO: Final[float] = 0.5

# NFR-02 内存 / CPU
MEMORY_PEAK_MB_MAX: Final[int] = 300
CPU_IDLE_PERCENT_MAX: Final[float] = 10.0

# 性能脚本基准参数
BENCH_DURATION_SECONDS: Final[int] = 60
BENCH_AI_DIRECTION_SWITCH_INTERVAL_S: Final[float] = 0.5


__all__ = [
    "TARGET_FPS",
    "P95_FRAME_TIME_MS_MAX",
    "INPUT_LATENCY_TICKS_MAX",
    "TICK_MS_HARD_MAX_RATIO",
    "MEMORY_PEAK_MB_MAX",
    "CPU_IDLE_PERCENT_MAX",
    "BENCH_DURATION_SECONDS",
    "BENCH_AI_DIRECTION_SWITCH_INTERVAL_S",
]