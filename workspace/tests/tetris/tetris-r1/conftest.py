# -*- coding: utf-8 -*-
"""pytest 配置：把被测代码目录注入 sys.path，供各测试模块 import tetris。

被测代码：workspace/code/tetris/tetris-r2/tetris.py（code 阶段终版 r2，只读）。
本文件使单元测试可在任意 cwd 下运行：
    pytest tests/tetris/tetris-r1/ -v
"""
import os
import sys

CODE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 '..', '..', '..', 'code', 'tetris', 'tetris-r2'))

if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)
