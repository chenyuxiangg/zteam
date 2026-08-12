#!/usr/bin/env python3
"""真实 PTY 冒烟：启动 curses、检测完整渲染、q 退出并校验退出码。

覆盖：S-01 / S-06 / S-07 / S-10 / S-12 / S-13。

注意：
- 必须有真终端才能跑（用 pty.fork）。
- 默认地图路径问题（D-01）已在 r1 修复（code 阶段改默认值为绝对路径或基于 __file__），
  本脚本的 PACMAN_CODE_DIR 路径已指向 code/pacman-r1。
- 如 S-01 失败会输出最后 2KB stderr 便于排查。
"""
from __future__ import annotations

import argparse
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODE = ROOT.parents[1] / "code" / "pacman-r1"
CODE = Path(os.environ.get("PACMAN_CODE_DIR", str(DEFAULT_CODE))).resolve()


def _resize(fd: int, rows: int = 24, cols: int = 80) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def run_once(timeout: float = 5.0,
             extra_args: list[str] | None = None,
             rows: int = 24, cols: int = 80) -> tuple[int, bytes, float]:
    """启动一次 pacman，等待渲染完成（≤3s）后 q 退出。"""
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.chdir(CODE)
            os.environ["PYTHONPATH"] = str(CODE)
            os.environ.setdefault("TERM", "xterm-256color")
            argv = [sys.executable, "-m", "pacman", "--no-color"]
            if extra_args:
                argv += list(extra_args)
            os.execv(sys.executable, argv)
        except Exception as e:
            sys.stderr.write(f"execv 失败: {e}\n")
            os._exit(127)
    _resize(fd, rows=rows, cols=cols)
    started = time.monotonic()
    data = bytearray()
    deadline = started + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                try:
                    data.extend(os.read(fd, 65536))
                except OSError:
                    break
            # HUD 中文 "分数:" 或 ≥20 个 # 表示渲染已就位
            if "分数:".encode() in data or data.count(b"#") >= 20:
                break
        startup = time.monotonic() - started
        # 发送 q 退出
        try:
            os.write(fd, b"q")
        except OSError:
            pass
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
        try:
            os.close(fd)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--ghosts", type=int, default=None,
                    help="S-12: --ghosts N 启动")
    ap.add_argument("--map", type=str, default=None,
                    help="S-13: 指定地图路径")
    ap.add_argument("--rows", type=int, default=24)
    ap.add_argument("--cols", type=int, default=80)
    args = ap.parse_args()

    extra = []
    if args.ghosts:
        extra += ["--ghosts", str(args.ghosts)]
    if args.map:
        extra += ["--map", args.map]

    failed = 0
    for i in range(args.repeat):
        rc, data, startup = run_once(
            extra_args=extra or None,
            rows=args.rows,
            cols=args.cols,
        )
        rendered = "分数:".encode() in data or data.count(b"#") >= 20
        print(
            f"run={i + 1} rc={rc} startup={startup:.3f}s "
            f"rendered={rendered} bytes={len(data)}",
            flush=True,
        )
        if rc != 0 or not rendered or startup > 3.0:
            failed += 1
            print(data[-2000:].decode("utf-8", "replace"), file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())