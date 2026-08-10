#!/usr/bin/env python3
"""bench_ai.py — AI 性能基准（testplan UTA-08 + §4）。

用法：
    python3 scripts/bench_ai.py [--games N] [--size 15] [--difficulty strong]

对 N 个中盘局面（双方各 20 子）跑 strong 档 AI，记录：
- 每局耗时
- P50 / P95 / max
- 机器规格（CPU 核数、Python 版本）

输出格式：可读文本 + 一行 machine-spec 供 testplan NFR-01 对照。
"""
from __future__ import annotations

import argparse
import os
import platform
import statistics
import sys
import time
from pathlib import Path

# 让脚本能 import gomoku
_CODE_DIR = Path(__file__).resolve().parent.parent.parent / "code" / "gomoku-r3"
sys.path.insert(0, str(_CODE_DIR))

from gomoku.ai import choose_move  # noqa: E402
from gomoku.board import Board  # noqa: E402


def make_midgame(size: int, stones_each: int, seed: int) -> Board:
    """生成中盘局面：双方各 stones_each 子，黑先。"""
    import random
    rng = random.Random(seed)
    b = Board(size)
    color = "B"
    placed = {"B": 0, "W": 0}
    attempts = 0
    target = stones_each
    while placed["B"] < target or placed["W"] < target:
        x = rng.randint(0, size - 1)
        y = rng.randint(0, size - 1)
        if b.place(x, y, color):
            placed[color] += 1
            color = "W" if color == "B" else "B"
        attempts += 1
        if attempts > size * size * 4:
            raise RuntimeError("seed too tight")
    return b


def machine_spec() -> str:
    """返回一行机器规格描述。"""
    py_ver = platform.python_version()
    impl = platform.python_implementation()
    try:
        import multiprocessing
        cpu = multiprocessing.cpu_count()
    except Exception:
        cpu = "?"
    return f"{impl} {py_ver} / {cpu} CPU"


def main() -> int:
    p = argparse.ArgumentParser(description="AI 性能基准（testplan UTA-08）")
    p.add_argument("--games", type=int, default=5, help="中盘局面数（默认 5）")
    p.add_argument("--size", type=int, default=15, help="棋盘大小（默认 15）")
    p.add_argument("--difficulty", choices=("weak", "medium", "strong"),
                   default="strong", help="AI 难度（默认 strong）")
    p.add_argument("--time-budget", type=float, default=1.5,
                   help="strong 档时间预算（默认 1.5s）")
    args = p.parse_args()

    print(f"== bench_ai ==")
    print(f"games={args.games} size={args.size} difficulty={args.difficulty} "
          f"time_budget={args.time_budget}s")
    print(f"machine: {machine_spec()}")
    print()

    times: list[float] = []
    for i in range(args.games):
        b = make_midgame(args.size, stones_each=20, seed=10001 + i)
        t0 = time.monotonic()
        mv = choose_move(b, "B", args.difficulty, time_budget=args.time_budget)
        dt = time.monotonic() - t0
        times.append(dt)
        print(f"game {i+1}: {dt*1000:.1f} ms (move={mv})")

    times.sort()
    p50 = times[len(times) // 2]
    p95 = times[-1] if len(times) <= 5 else times[int(len(times) * 0.95)]
    mx = max(times)
    avg = statistics.mean(times)
    print()
    print(f"avg: {avg*1000:.1f} ms")
    print(f"P50: {p50*1000:.1f} ms")
    print(f"P95: {p95*1000:.1f} ms")
    print(f"max: {mx*1000:.1f} ms")
    print()
    # 与 NFR-01 对照：strong 中盘 ≤ 2s (CI 宽限 0.5s)
    nfr_budget = 2.0
    ci_budget = 2.5
    if p95 <= nfr_budget:
        verdict = "PASS (≤2s)"
    elif p95 <= ci_budget:
        verdict = "PASS-CI (≤2.5s)"
    else:
        verdict = "FAIL (>2.5s)"
    print(f"NFR-01 verdict: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())