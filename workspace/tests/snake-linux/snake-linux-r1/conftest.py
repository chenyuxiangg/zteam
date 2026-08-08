# -*- coding: utf-8 -*-
"""pytest 共享配置：定位被测代码目录并加入 sys.path。

测试目录：workspace/tests/snake-linux/snake-linux-r1/
被测代码：workspace/code/snake-linux/snake-linux-r1/（只读，不修改）
"""
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
# tests/snake-linux/snake-linux-r1/ -> 上溯 3 级到达 workspace/
WORKSPACE_DIR = os.path.abspath(os.path.join(TESTS_DIR, '..', '..', '..'))
CODE_DIR = os.path.join(WORKSPACE_DIR, 'code', 'snake-linux', 'snake-linux-r1')
SNAKE_PY = os.path.join(CODE_DIR, 'snake.py')

if not os.path.isfile(SNAKE_PY):
    raise RuntimeError(
        '未找到被测代码 {0}（期望位于 code 阶段产物目录）。'.format(SNAKE_PY))

sys.path.insert(0, CODE_DIR)

# 注册用例优先级 marker（testplan §3.2：P0 关键 / P1 重要 / P2 一般）
def pytest_configure(config):
    config.addinivalue_line('markers', 'p0: P0 关键用例（发布门禁）')
    config.addinivalue_line('markers', 'p1: P1 重要用例')
    config.addinivalue_line('markers', 'p2: P2 一般用例')
