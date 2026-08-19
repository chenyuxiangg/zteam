#!/usr/bin/env python3
"""scripts/bench_fps.py — NFR-01 帧率实测脚本（iter-4 G4-3）。

用法：
  python3 scripts/bench_fps.py [--duration 60] [--difficulty hard]

输出：
  - 平均 FPS
  - P50 / P95 / P99 帧时间
  - 输入延迟（按键到 step 间隔）
  - 评估：NFR-01 PASS / FAIL

说明：
  - judge_fps() 为纯判定逻辑（可单测）：P95 帧时间 ≤ P95_FRAME_TIME_MS_MAX
    且平均 FPS ≥ TARGET_FPS → PASS，否则 FAIL。
  - run_benchmark() 需要真实显示环境（构造 App + Renderer）；headless
    环境直接跑会以退出码 2（图形环境不可用）失败——判定逻辑已抽离可单测。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import deque
from typing import List

# 添加项目代码目录到 sys.path（优先 iter-4 交付目录，回退 iter-3）
# 布局兼容：资产层（snake-linux/code/...）与数据层（workspace/snake-linux/code/...）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
_WORKSPACE_ROOT = os.path.abspath(os.path.join(_PROJECT_ROOT, "..", "workspace"))
_CANDIDATES = [
    os.path.join(_PROJECT_ROOT, "code", "game-app", "iter-4"),
    os.path.join(_PROJECT_ROOT, "code", "game-app", "iter-3"),
    os.path.join(_WORKSPACE_ROOT, "snake-linux", "code", "game-app", "iter-4"),
    os.path.join(_WORKSPACE_ROOT, "snake-linux", "code", "game-app", "iter-3"),
]
for _p in _CANDIDATES:
    if os.path.isfile(os.path.join(_p, "game_app", "__init__.py")):
        sys.path.insert(0, _p)
        # 依赖模块（game-core / gui-renderer / platform-storage）同项目 code/ 树下
        _code_root = os.path.dirname(os.path.dirname(_p))
        for _dep in ("game-core", "gui-renderer", "platform-storage"):
            _pkg = _dep.replace("-", "_")
            _dep_dir = os.path.join(_code_root, _dep)
            if os.path.isdir(_dep_dir):
                for _dn in sorted(os.listdir(_dep_dir)):
                    _dp = os.path.join(_dep_dir, _dn)
                    if os.path.isfile(os.path.join(_dp, _pkg, "__init__.py")):
                        sys.path.insert(0, _dp)
        break

from game_app import App, AppConfigV3  # noqa: E402
from game_app.perf import (  # noqa: E402
    TARGET_FPS,
    P95_FRAME_TIME_MS_MAX,
    BENCH_DURATION_SECONDS,
    BENCH_AI_DIRECTION_SWITCH_INTERVAL_S,
)
from game_core import Difficulty, Direction  # noqa: E402

DEFAULT_DURATION: int = BENCH_DURATION_SECONDS
DIFFICULTY_CHOICES: List[str] = ["easy", "medium", "hard"]

# MTO-4-01 修复（连带缺陷 NFR-01，与 bench_memory 同根因）：方向切换序列**必须无反向项**。
# game_core.set_direction 对反向输入（蛇长≥2）静默忽略（架构设计，UT #9a 固化），
# 旧序列 ["up","down","left","right"] 中 down 是 up 的反向、right 是 left 的反向，
# 被忽略后蛇只沿 up/left 直行 → HARD 下撞墙 OVER → _tick 入口断言崩溃。
# 改用相邻项均正交（永不反向）的循环：up→left→down→right→up→... 蛇走矩形回路不撞墙。
BENCH_DIRECTION_CYCLE: List[str] = ["up", "left", "down", "right"]


def judge_fps(avg_fps: float, p95_frame_ms: float) -> str:
    """NFR-01 判定：P95 帧时间 ≤ 限值 且 平均 FPS ≥ 60 → PASS。

    Args:
        avg_fps: 平均帧率（FPS）
        p95_frame_ms: P95 帧时间（毫秒）

    Returns:
        "PASS" 或 "FAIL"
    """
    if p95_frame_ms <= P95_FRAME_TIME_MS_MAX and avg_fps >= TARGET_FPS:
        return "PASS"
    return "FAIL"


def run_benchmark(duration: int, difficulty: Difficulty) -> dict:
    """运行 NFR-01 帧率基准测试（需真实显示环境）。

    Returns:
        dict: {
            "avg_fps": float,
            "p50_frame_ms": float,
            "p95_frame_ms": float,
            "p99_frame_ms": float,
            "input_latency_ms": float,
            "duration_s": int,
            "result": "PASS" | "FAIL",
        }
    """
    config = AppConfigV3(enable_high_dpi=True)
    app = App(config)

    app._init_pygame()
    app._difficulty = difficulty
    app._new_game(difficulty)

    frame_times: deque = deque(maxlen=10000)
    input_latencies: deque = deque(maxlen=1000)

    start_time = time.perf_counter()
    last_frame_time = start_time
    direction_cycle = 0
    direction_map = {
        "up": Direction.UP,
        "down": Direction.DOWN,
        "left": Direction.LEFT,
        "right": Direction.RIGHT,
    }

    while time.perf_counter() - start_time < duration:
        # 模拟按键（每 0.5 秒切一次方向）
        if time.perf_counter() - start_time > direction_cycle * BENCH_AI_DIRECTION_SWITCH_INTERVAL_S:
            direction_cycle += 1
            direction = BENCH_DIRECTION_CYCLE[direction_cycle % len(BENCH_DIRECTION_CYCLE)]
            input_time = time.perf_counter()
            app.game_state = app.game_state.set_direction(direction_map[direction])
            input_latency = (time.perf_counter() - input_time) * 1000
            input_latencies.append(input_latency)

        # 模拟主循环
        dt_ms = (time.perf_counter() - last_frame_time) * 1000
        last_frame_time = time.perf_counter()

        app._tick(int(dt_ms))
        snap = app.game_state.snapshot()
        app._render()

        frame_times.append(dt_ms)

    # 统计
    sorted_frames = sorted(frame_times)
    n = len(sorted_frames)
    avg_fps = 1000.0 / (sum(frame_times) / n) if n > 0 else 0.0
    p50 = sorted_frames[n // 2]
    p95 = sorted_frames[int(n * 0.95)]
    p99 = sorted_frames[int(n * 0.99)]
    avg_latency = sum(input_latencies) / len(input_latencies) if input_latencies else 0.0

    result = judge_fps(avg_fps, p95)

    return {
        "avg_fps": avg_fps,
        "p50_frame_ms": p50,
        "p95_frame_ms": p95,
        "p99_frame_ms": p99,
        "input_latency_ms": avg_latency,
        "duration_s": duration,
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="NFR-01 帧率基准测试")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION, help="基准时长（秒）")
    parser.add_argument("--difficulty", type=str, default="hard", choices=DIFFICULTY_CHOICES)
    args = parser.parse_args()

    difficulty_map = {"easy": Difficulty.EASY, "medium": Difficulty.MEDIUM, "hard": Difficulty.HARD}
    difficulty = difficulty_map[args.difficulty]

    print(f"[bench_fps] 开始基准测试（duration={args.duration}s, difficulty={args.difficulty}）...")
    result = run_benchmark(args.duration, difficulty)

    print("\n[bench_fps] 结果:")
    print(f"  平均 FPS: {result['avg_fps']:.1f}")
    print(f"  P50 帧时间: {result['p50_frame_ms']:.2f}ms")
    print(f"  P95 帧时间: {result['p95_frame_ms']:.2f}ms (限值: {P95_FRAME_TIME_MS_MAX}ms)")
    print(f"  P99 帧时间: {result['p99_frame_ms']:.2f}ms")
    print(f"  平均输入延迟: {result['input_latency_ms']:.2f}ms")
    print(f"  NFR-01 评估: {result['result']}")

    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
