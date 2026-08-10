#!/usr/bin/env python3
"""真实 PTY 冒烟：启动 curses、检测完整渲染、q 退出并校验退出码。"""
from __future__ import annotations

import argparse
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import fcntl
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = Path(os.environ.get("PACMAN_CODE_DIR", ROOT.parents[1] / "code" / "pacman-r2")).resolve()


def run_once(timeout: float = 5.0, explicit_map: bool = False) -> tuple[int, bytes, float]:
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(CODE)
        os.environ["PYTHONPATH"] = str(CODE)
        os.environ.setdefault("TERM", "xterm-256color")
        argv = [sys.executable, "-m", "pacman", "--no-color"]
        if explicit_map:
            argv += ["--map", "pacman/data/map_classic.txt"]
        os.execv(sys.executable, argv)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    started = time.monotonic()
    data = bytearray()
    deadline = started + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                try: data.extend(os.read(fd, 65536))
                except OSError: break
            # HUD Chinese bytes or maze-sized output means renderer reached a frame.
            if "分数:".encode() in data or data.count(b"#") >= 20:
                break
        startup = time.monotonic() - started
        os.write(fd, b"q")
        wait_deadline = time.monotonic() + 3
        while time.monotonic() < wait_deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status), bytes(data), startup
            time.sleep(0.05)
        os.kill(pid, signal.SIGTERM)
        _, status = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(status), bytes(data), startup
    finally:
        try: os.close(fd)
        except OSError: pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    args = ap.parse_args()
    for i in range(args.repeat):
        # S-01 首先验证 README 默认启动命令；失败即报告，不用显式地图掩盖缺陷。
        rc, data, startup = run_once()
        rendered = "分数:".encode() in data or data.count(b"#") >= 20
        print(f"run={i+1} mode=default rc={rc} startup={startup:.3f}s rendered={rendered}")
        if rc != 0 or not rendered or startup > 3.0:
            print(data[-2000:].decode("utf-8", "replace"), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
