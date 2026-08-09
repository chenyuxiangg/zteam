# -*- coding: utf-8 -*-
"""InputHandler 键位映射测试：FR-18 键盘控制全集。

对应测试方案 §3.2 用例表（补充单元面，映射 TC-I-06 的逻辑部分）：
    TC-I-06 (P0)  WASD 与方向键双方案均生效；空格硬降；P 暂停；q 退出
    TC-I-07 (P0)  q 触发 QUIT（FR-20）
    无效键/无输入 → None；KEY_RESIZE → RESIZE（FR-04）
"""
import curses

import tetris
from tetris import InputHandler


def test_wasd_map():
    """WASD 四键映射正确（含大小写）。"""
    assert InputHandler.handle(ord('w')) == 'ROTATE'
    assert InputHandler.handle(ord('W')) == 'ROTATE'
    assert InputHandler.handle(ord('a')) == 'LEFT'
    assert InputHandler.handle(ord('A')) == 'LEFT'
    assert InputHandler.handle(ord('s')) == 'SOFT'
    assert InputHandler.handle(ord('S')) == 'SOFT'
    assert InputHandler.handle(ord('d')) == 'RIGHT'
    assert InputHandler.handle(ord('D')) == 'RIGHT'


def test_arrow_keys_map():
    """方向键映射正确（curses KEY_* 常量）。"""
    assert InputHandler.handle(curses.KEY_UP) == 'ROTATE'
    assert InputHandler.handle(curses.KEY_LEFT) == 'LEFT'
    assert InputHandler.handle(curses.KEY_RIGHT) == 'RIGHT'
    assert InputHandler.handle(curses.KEY_DOWN) == 'SOFT'


def test_space_p_q_map():
    """空格硬降、P 暂停、q 退出。"""
    assert InputHandler.handle(ord(' ')) == 'HARD'
    assert InputHandler.handle(ord('p')) == 'PAUSE'
    assert InputHandler.handle(ord('P')) == 'PAUSE'
    assert InputHandler.handle(ord('q')) == 'QUIT'
    assert InputHandler.handle(ord('Q')) == 'QUIT'


def test_invalid_and_no_input():
    """无效键/无输入（-1）→ None。"""
    assert InputHandler.handle(-1) is None
    assert InputHandler.handle(ord('x')) is None
    assert InputHandler.handle(ord('\n')) is None
    assert InputHandler.handle(ord('\t')) is None


def test_resize_event():
    """KEY_RESIZE → RESIZE（FR-04 运行中 resize）。"""
    assert InputHandler.handle(curses.KEY_RESIZE) == 'RESIZE'
