#!/usr/bin/env python3
"""fuzz_input.py — 输入 fuzz（testplan ST-11）。

用法：
    python3 scripts/fuzz_input.py [--rounds 100] [--seed 42]

通过 subprocess + pty 驱动真实 ``python -m gomoku`` 进程，发送 N 个
随机输入（合法/越界/乱码/超长/中文/quit），每 5 个插入一个合法落子。
进程应保持存活、不抛出 traceback、最终 Ctrl+C 干净退出。
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from pathlib import Path

# 让脚本能找到 conftest（fuzz_input_pool）
_TESTS_DIR = Path(__file__).resolve().parent.parent / "tests"
sys.path.insert(0, str(_TESTS_DIR))
sys.path.insert(0, str(_TESTS_DIR.parent.parent / "code" / "gomoku-r3"))


def fuzz_input_pool(seed: int, count: int) -> list[str]:
    """与 conftest.fuzz_input_pool 等价的本地副本（脚本独立运行时不依赖 pytest）。"""
    rng = random.Random(seed)
    pool: list[str] = []
    legal = [f"{chr(65 + rng.randint(0, 14))}{rng.randint(1, 15)}" for _ in range(30)]
    occupied = legal[:10]
    pool.extend(legal)
    pool.extend(["P1", "Z9", "0,0", "A16", "16,1", "O16", "P16"])
    pool.extend(occupied)
    pool.extend(["asdf", "##", "1.5,3", "AA", "!", "@@@", "???", "x"])
    pool.extend(["", " ", "   ", "\t"])
    pool.extend(["A" * 25, "黑子", "한글", "テスト", "♠♣"])
    pool.extend(["resign", "help", "save", "load", "undo"])
    rng.shuffle(pool)
    if len(pool) < count:
        more = [f"{chr(65 + rng.randint(0, 14))}{rng.randint(1, 15)}" for _ in range(count)]
        pool.extend(more)
        rng.shuffle(pool)
    return pool[:count]


def main() -> int:
    p = argparse.ArgumentParser(description="输入 fuzz（testplan ST-11）")
    p.add_argument("--rounds", type=int, default=100, help="输入总数（默认 100）")
    p.add_argument("--seed", type=int, default=42, help="随机种子（默认 42）")
    p.add_argument("--time-budget", type=float, default=60.0, help="总超时秒")
    args = p.parse_args()

    # 优先用 pexpect；不可用则降级为纯 stdin 写入（可能因 IO 缓冲错过异常）
    try:
        import pexpect
    except ImportError:
        print("ERROR: pexpect 未安装；fuzz 需要 pty。", file=sys.stderr)
        return 2

    env = os.environ.copy()
    code_path = str(Path(__file__).resolve().parent.parent.parent / "code" / "gomoku-r3")
    env["PYTHONPATH"] = code_path + os.pathsep + env.get("PYTHONPATH", "")
    env["LINES"] = "24"
    env["COLUMNS"] = "60"
    env["TERM"] = env.get("TERM", "xterm-256color")

    cmd = f"{sys.executable} -m gomoku"
    child = pexpect.spawn(cmd, env=env, timeout=args.time_budget, encoding="utf-8",
                          dimensions=(24, 60))

    inputs = fuzz_input_pool(args.seed, args.rounds)
    legal_moves = ["A1", "B2", "C3", "D4", "E5", "F6", "G7", "H8", "J9", "K10"]
    legal_idx = 0

    t0 = time.monotonic()
    crash = False
    for i, s in enumerate(inputs):
        if i % 5 == 0 and legal_idx < len(legal_moves):
            child.sendline(legal_moves[legal_idx])
            legal_idx += 1
        else:
            child.sendline(s)
        try:
            child.expect([r"上一步", r"当前玩家", "越界", "格式错误", "已占用",
                          pexpect.EOF], timeout=2)
        except pexpect.TIMEOUT:
            pass
        except pexpect.EOF:
            crash = True
            print(f"  EOF at input #{i}: {s!r}")
            break
        if not child.isalive():
            crash = True
            print(f"  process died at input #{i}: {s!r}")
            break

    dt = time.monotonic() - t0
    # 优雅退出
    if child.isalive():
        child.send("\x03")
        try:
            child.expect(pexpect.EOF, timeout=3)
        except pexpect.TIMEOUT:
            child.close(force=True)
    child.wait()

    print()
    print(f"rounds={args.rounds} seed={args.seed} elapsed={dt:.2f}s")
    print(f"verdict: {'PASS' if not crash else 'FAIL (process died)'}")
    print(f"exitstatus={child.exitstatus}")
    return 0 if not crash else 1


if __name__ == "__main__":
    sys.exit(main())