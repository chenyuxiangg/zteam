# -*- coding: utf-8 -*-
"""InputHandler 单元测试：键位映射完整性（配合 TC-U-02 的输入侧）。

覆盖 FR-06（WASD/方向键 -> 方向）、FR-07（反向输入在输入层即被映射，
反向判定在 GameState.turn）、FR-13（q/Q 退出键）。

r2 说明：本文件自 r1 原样保留（r1 评审单元层全绿，无修改意见）。
"""
import curses

import pytest

import snake
from snake import InputHandler

RIGHT, LEFT, UP, DOWN = snake.RIGHT, snake.LEFT, snake.UP, snake.DOWN


@pytest.mark.p0
def test_direction_map_complete():
    """WASD（含大写）与四个方向键全部映射到正确方向向量。"""
    expect = {
        ord('w'): UP, ord('W'): UP, curses.KEY_UP: UP,
        ord('s'): DOWN, ord('S'): DOWN, curses.KEY_DOWN: DOWN,
        ord('a'): LEFT, ord('A'): LEFT, curses.KEY_LEFT: LEFT,
        ord('d'): RIGHT, ord('D'): RIGHT, curses.KEY_RIGHT: RIGHT,
    }
    for key, want in expect.items():
        assert InputHandler.direction_for(key) == want, \
            '键 {0!r} 应映射到 {1!r}'.format(key, want)


@pytest.mark.p0
def test_quit_keys():
    assert InputHandler.is_quit(ord('q'))
    assert InputHandler.is_quit(ord('Q'))
    assert not InputHandler.is_quit(ord('w'))
    assert not InputHandler.is_quit(ord('x'))


@pytest.mark.p1
def test_unknown_keys_ignored():
    """非方向/退出键（数字、符号、无输入 -1）应返回 None（被忽略）。"""
    for key in [ord('1'), ord(' '), ord('\t'), -1, ord('z'), ord('[')]:
        assert InputHandler.direction_for(key) is None
        assert not InputHandler.is_quit(key)
