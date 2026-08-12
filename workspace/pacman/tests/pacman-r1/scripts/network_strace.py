#!/usr/bin/env python3
"""NFR-06：用 strace 实证一次 CLI 启动路径没有网络系统调用。

说明：跑 `python3 -m pacman --help`（不走 TTY 渲染，只走 argparse），用 strace 抓
网络相关系统调用。期望 0 次。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODE = ROOT.parents[1] / "code" / "pacman-r1"
CODE = Path(os.environ.get("PACMAN_CODE_DIR", str(DEFAULT_CODE))).resolve()


def main() -> int:
    if not shutil.which("strace"):
        print("SKIP: strace not installed", file=sys.stderr)
        return 77
    with tempfile.NamedTemporaryFile(
        prefix="pacman-net-", suffix=".log", delete=False,
    ) as f:
        log = f.name
    env = {**os.environ, "PYTHONPATH": str(CODE)}
    try:
        result = subprocess.run(
            ["strace", "-f", "-e", "trace=network", "-o", log,
             sys.executable, "-m", "pacman", "--help"],
            cwd=str(CODE), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        )
        text = Path(log).read_text(encoding="utf-8", errors="replace")
    finally:
        Path(log).unlink(missing_ok=True)

    calls = [
        line for line in text.splitlines()
        if any(x in line for x in (
            "socket(", "connect(", "bind(", "listen(", "accept(",
            "sendto(", "recvfrom(",
        ))
    ]
    print(f"rc={result.returncode} network_calls={len(calls)}", flush=True)
    if result.returncode != 0 or calls:
        print("\n".join(calls), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())