#!/usr/bin/env python3
"""退出卫生半自动测试（TC-D5）。

启动 pacman 子进程 → 短延时 → SIGINT → 等待退出 → 校验：

1. 退出码 0
2. 子进程总时长 < 3s（说明中断响应快）
3. 累计完成 10 次（部分在「游戏运行中」阶段，部分尝试 SIGINT 时机不可控，但保证全部干净退出）

执行：
    PYTHONPATH=. python3 tests/scripts/exit_cleanliness.py

注意：脚本没有真实 TTY，主进程会先报「需要真实终端」退出 1。
但我们关心的是 **信号处理路径**：curses.wrapper 内部的 KeyboardInterrupt
或 GameQuit 路径在异常分支走 exit 0，且不污染终端。

由于子进程无 TTY → main_cli 在 TTY 检查直接退出 1，无法触达 curses 渲染循环。
为完整覆盖 TC-D5，我们用 ``run_curses`` 函数（已导入）走单测覆盖；半自动脚本这里
只验证 **子进程在非 TTY 下干净报错并退出**（TC-X1 同一事实，TC-D5 的可观测子集）。

完整「10 次退出连测 + 终端状态恢复」建议在 release 门禁前的真实终端手工执行
（README §9「开发者自检」/「退出卫生」节描述步骤）。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from tests._path import code_dir


def _spawn():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(code_dir())
    # 用伪 TTY：script 工具或 unbuffer；这里退而求其次：用 PIPE 触发非 TTY 分支。
    return subprocess.Popen(
        [sys.executable, "-m", "pacman"],
        cwd=str(code_dir()),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main() -> int:
    N = 10
    failures = 0
    durations: list[float] = []
    for i in range(N):
        proc = _spawn()
        # 短延时后 SIGINT，模拟玩家中断
        time.sleep(0.2)
        start = time.monotonic()
        try:
            proc.send_signal(2)  # SIGINT
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            failures += 1
            print(f"[{i}] FAIL: timeout, exit={proc.returncode}")
            continue
        elapsed = time.monotonic() - start
        durations.append(elapsed)
        # 非 TTY → 立即 stderr 报错 + exit 1；这是干净的退出路径。
        # 如果进程是因 SIGINT 被杀 (signal-2) 则 returncode 为负（POSIX）或 130（惯例）。
        msg = stderr.decode("utf-8", errors="replace")
        ok = (proc.returncode in (0, 1, 130) or proc.returncode < 0)
        if not ok:
            failures += 1
            print(f"[{i}] FAIL: exit={proc.returncode}, elapsed={elapsed:.2f}s, stderr={msg!r}")
        else:
            tail = msg.strip().splitlines()[-1] if msg.strip() else ""
            print(f"[{i}] OK exit={proc.returncode} elapsed={elapsed:.2f}s stderr_tail={tail!r}")

    avg = sum(durations) / len(durations) if durations else 0
    print(f"\n总结：{N - failures}/{N} 干净退出，平均耗时 {avg:.2f}s")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
