#!/usr/bin/env python3
"""scripts/bench_memory.py — NFR-02 内存实测脚本（iter-4 G4-3）。

用法：
  python3 scripts/bench_memory.py [--duration 60]

输出：
  - 内存峰值（MB）
  - 平均内存占用（MB）
  - 评估：NFR-02 PASS / FAIL

说明：
  - judge_memory() 为纯判定逻辑（可单测）：峰值 ≤ MEMORY_PEAK_MB_MAX → PASS。
  - run_benchmark() 需要真实显示环境；headless 环境跑会以退出码 2 失败。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
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

from game_app.perf import (  # noqa: E402
    MEMORY_PEAK_MB_MAX,
    BENCH_DURATION_SECONDS,
    BENCH_AI_DIRECTION_SWITCH_INTERVAL_S,
)

DEFAULT_DURATION: int = BENCH_DURATION_SECONDS

# MTO-4-01 修复（连带缺陷 NFR-02）：方向切换序列**必须无反向项**。
# game_core.set_direction 对反向输入（蛇长≥2）静默忽略（架构设计，UT #9a 固化），
# 旧序列 ["up","down","left","right"] 中 down 是 up 的反向、right 是 left 的反向，
# 被忽略后蛇只沿 up/left 直行 → HARD 下撞墙 OVER → _tick 入口断言崩溃。
# 改用相邻项均正交（永不反向）的循环：up→left→down→right→up→... 蛇走矩形回路不撞墙。
BENCH_DIRECTION_CYCLE: List[str] = ["up", "left", "down", "right"]


def get_memory_mb() -> float:
    """获取当前进程内存占用（MB，RSS）。"""
    if sys.platform == "win32":
        import psutil  # type: ignore
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    else:
        import resource  # Unix only
        # rusage.ru_maxrss 单位：Linux=KB，macOS=bytes
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return rss / 1024 / 1024
        return rss / 1024


def judge_memory(peak_mb: float) -> str:
    """NFR-02 判定：峰值 ≤ MEMORY_PEAK_MB_MAX（300MB）→ PASS。

    Args:
        peak_mb: 内存峰值（MB）

    Returns:
        "PASS" 或 "FAIL"
    """
    return "PASS" if peak_mb <= MEMORY_PEAK_MB_MAX else "FAIL"


def run_benchmark(duration: int) -> dict:
    """运行 NFR-02 内存基准测试（需真实显示环境）。

    修复 MTO-4-01（影响面 NFR-02）：与 bench_fps 一致，按
    BENCH_AI_DIRECTION_SWITCH_INTERVAL_S 周期切换移动方向，避免 HARD 难度
    下蛇直行撞墙 OVER → _tick 入口断言崩溃（此前颜色崩溃掩盖了该缺陷，
    颜色修复后暴露）。
    """
    from game_app import App, AppConfigV3
    from game_core import Difficulty, Direction

    app = App(AppConfigV3(enable_high_dpi=True))
    app._init_pygame()
    app._difficulty = Difficulty.HARD
    app._new_game(Difficulty.HARD)

    memory_samples: List[float] = []
    start_time = time.perf_counter()
    direction_cycle = 0
    direction_map = {
        "up": Direction.UP,
        "down": Direction.DOWN,
        "left": Direction.LEFT,
        "right": Direction.RIGHT,
    }

    while time.perf_counter() - start_time < duration:
        # 模拟按键（每 0.5 秒切一次方向，防撞墙 OVER）
        if time.perf_counter() - start_time > direction_cycle * BENCH_AI_DIRECTION_SWITCH_INTERVAL_S:
            direction_cycle += 1
            direction = BENCH_DIRECTION_CYCLE[direction_cycle % len(BENCH_DIRECTION_CYCLE)]
            app.game_state = app.game_state.set_direction(direction_map[direction])

        app._tick(16)  # 60 FPS
        app._render()
        memory_samples.append(get_memory_mb())
        time.sleep(0.016)  # 模拟 60 FPS

    peak_mb = max(memory_samples) if memory_samples else 0.0
    avg_mb = sum(memory_samples) / len(memory_samples) if memory_samples else 0.0
    result = judge_memory(peak_mb)

    return {
        "peak_mb": peak_mb,
        "avg_mb": avg_mb,
        "duration_s": duration,
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="NFR-02 内存基准测试")
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    args = parser.parse_args()

    print(f"[bench_memory] 开始内存基准测试（duration={args.duration}s）...")
    result = run_benchmark(args.duration)

    print("\n[bench_memory] 结果:")
    print(f"  内存峰值: {result['peak_mb']:.1f}MB (限值: {MEMORY_PEAK_MB_MAX}MB)")
    print(f"  内存平均: {result['avg_mb']:.1f}MB")
    print(f"  NFR-02 评估: {result['result']}")

    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
