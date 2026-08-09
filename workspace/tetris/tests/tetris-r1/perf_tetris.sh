#!/usr/bin/env bash
# tetris r1 性能测试入口（对齐测试方案 §5：bash tests/perf_tetris.sh）
# 依赖：python3 + pexpect/pyte（测试侧依赖）
set -u
cd "$(dirname "$0")"
exec python3 perf_tetris.py
