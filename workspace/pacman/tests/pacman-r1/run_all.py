#!/usr/bin/env python3
"""tests/run_all.py —— 全量回归入口。

调用方式（在 workspace/pacman/tests/pacman-r1/ 目录下）::

    python3 run_all.py                 # 仅跑 unit + 集成（不需真终端）
    python3 run_all.py --with-system   # 追加跑系统层 PTY 冒烟（需真终端）
    python3 run_all.py --with-network  # 追加跑 N-01 strace 验证（需 strace）
    python3 run_all.py --no-system     # 显式排除系统层

实现说明：
- 单元 + 集成走 ``unittest discover``，自动发现 ``tests/test_*.py``；
- 系统层调用 ``scripts/e2e_pty.py``；
- N-01 走 ``scripts/network_strace.py``；
- 退出码：任一阶段 FAIL → 退出码 1；全部 PASS → 退出码 0；
  N-01/S-层 不可跑（缺工具/无 TTY）→ 返回 77（参考 autotools 跳过约定）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS_DIR = ROOT / "tests"
SCRIPTS_DIR = ROOT / "scripts"


def _run_unittest() -> int:
    """运行单元 + 集成测试（无需真终端）。"""
    print("=" * 60)
    print("[1/3] 单元 + 集成测试（unittest discover）")
    print("=" * 60)
    loader = unittest.TestLoader()
    # 自动发现 tests/test_*.py
    suite = loader.discover(
        start_dir=str(TESTS_DIR),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )
    runner = unittest.TextTestRunner(verbosity=1, buffer=True)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def _run_system() -> int:
    """运行系统层 PTY 冒烟（需真终端）。"""
    print()
    print("=" * 60)
    print("[2/3] 系统层 PTY 冒烟（e2e_pty.py --repeat=3）")
    print("=" * 60)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("SKIP: 非 TTY 环境，跳过系统层测试（用真终端重跑）", file=sys.stderr)
        return 77
    rc = subprocess.call(
        [sys.executable, str(SCRIPTS_DIR / "e2e_pty.py"), "--repeat", "3"],
    )
    return rc


def _run_network() -> int:
    """运行 N-01 零网络验证（需 strace）。"""
    print()
    print("=" * 60)
    print("[3/3] N-01 零网络验证（strace -e trace=network）")
    print("=" * 60)
    rc = subprocess.call(
        [sys.executable, str(SCRIPTS_DIR / "network_strace.py")],
    )
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description="pacman 全量回归入口")
    ap.add_argument("--with-system", action="store_true",
                    help="追加系统层 PTY 冒烟（需真终端）")
    ap.add_argument("--with-network", action="store_true",
                    help="追加 N-01 strace 验证（需 strace）")
    ap.add_argument("--no-system", action="store_true",
                    help="显式排除系统层")
    args = ap.parse_args()

    # 确保 PACMAN_CODE_DIR 已设置（run_all.py 在任何 test_* 之前运行，
    # tests/_path.py 会读此环境变量）。
    if "PACMAN_CODE_DIR" not in os.environ:
        default_code = ROOT.parents[1] / "code" / "pacman-r1"
        os.environ["PACMAN_CODE_DIR"] = str(default_code)
        print(f"[env] PACMAN_CODE_DIR={default_code}")

    rc = _run_unittest()
    if rc != 0:
        print(f"\n单元/集成层 FAIL（rc={rc}），停止后续阶段。")
        return rc

    if not args.no_system and args.with_system:
        rc_system = _run_system()
        if rc_system not in (0, 77):
            return rc_system

    if args.with_network:
        rc_network = _run_network()
        if rc_network not in (0, 77):
            return rc_network

    print("\n全部阶段通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
