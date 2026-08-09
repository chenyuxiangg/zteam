#!/usr/bin/env bash
# tetris r1 集成测试入口（对齐测试方案 §5：bash tests/e2e_tetris.sh）
# 依赖：python3 + pytest/pexpect/pyte（测试侧依赖，不影响交付物运行时零依赖）
set -u
cd "$(dirname "$0")"
exec python3 e2e_tetris.py
