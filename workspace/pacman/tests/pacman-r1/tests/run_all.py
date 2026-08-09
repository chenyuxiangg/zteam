#!/usr/bin/env python3
"""测试总入口。

执行顺序：
  1. 单元层（unittest discover tests/test_*.py）
  2. 集成层（CLI 冒烟 test_cli_smoke.py）
  3. 退出卫生半自动（scripts/exit_cleanliness.py）

退出码 = 失败用例数（0 = 全绿）。

执行：
    PYTHONPATH=. python3 tests/run_all.py
    # 或
    cd workspace/pacman/tests/pacman-r1 && python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    print("=" * 60)
    print("Step 1: 单元层（unittest discover）")
    print("=" * 60)
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(ROOT), pattern="test_*.py", top_level_dir=str(ROOT))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        print(f"\n单元层失败：{len(result.failures)} errors, {len(result.failures)} failures")
        return 1

    print()
    print("=" * 60)
    print("Step 2: 集成层（CLI 冒烟）")
    print("=" * 60)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "test_cli_smoke.py")],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        print(f"\n集成层失败（exit={proc.returncode}）")
        return proc.returncode

    print()
    print("=" * 60)
    print("Step 3: 退出卫生半自动（scripts/exit_cleanliness.py）")
    print("=" * 60)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "exit_cleanliness.py")],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        cwd=str(ROOT),
    )
    # exit_cleanliness 返回 0/1；失败也仅记录，不阻塞（与 §6 风险表 TC-D5 等级一致）
    if proc.returncode != 0:
        print(f"\n退出卫生检查非 0 退出码（{proc.returncode}），不视为阻断，但请检查输出")

    print()
    print("=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"单元层：runs={result.testsRun}, failures={len(result.failures)}, errors={len(result.errors)}, skipped={len(result.skipped)}")
    print("集成层 / 退出卫生：见上")
    return 0


if __name__ == "__main__":
    sys.exit(main())
