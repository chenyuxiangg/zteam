# -*- coding: utf-8 -*-
"""TC-U-01 / TC-U-02：七种标准方块定义与旋转（FR-05 / FR-09）。

对应测试方案 §3.2 用例表：
    TC-U-01 (P0)  TETROMINOES 键集/格数/标准形状
    TC-U-02 (P0)  rotate_cw 连续旋转 4 次还原；I 横竖翻转；O 旋转不变
"""
import pytest

import tetris


# ---------------------------------------------------------------------------
# TC-U-01：七种标准方块（FR-05）
# ---------------------------------------------------------------------------
def test_tc_u01_keys_complete():
    """7 键齐全：{I,O,T,S,Z,J,L}，无缺失、无多余。"""
    assert set(tetris.TETROMINOES.keys()) == {'I', 'O', 'T', 'S', 'Z', 'J', 'L'}


@pytest.mark.parametrize('ptype', ['I', 'O', 'T', 'S', 'Z', 'J', 'L'])
def test_tc_u01_each_piece_has_4_cells(ptype):
    """每方块恰 4 格（标准俄罗斯方块），且矩阵为 4×4。"""
    m = tetris.TETROMINOES[ptype]
    assert len(m) == 4 and all(len(row) == 4 for row in m)
    cells = sum(sum(row) for row in m)
    assert cells == 4, '%s 应有 4 格，实得 %d' % (ptype, cells)


def test_tc_u01_shapes_match_standard():
    """形状与标准定义一致（I=横四连、O=2×2 田字、T/S/Z=三连拐、J/L=L 形）。"""
    # I：恰一行 4 连
    assert tetris.TETROMINOES['I'] == [
        [0, 0, 0, 0],
        [1, 1, 1, 1],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    # O：2×2 田字
    assert tetris.TETROMINOES['O'] == [
        [0, 0, 0, 0],
        [0, 1, 1, 0],
        [0, 1, 1, 0],
        [0, 0, 0, 0],
    ]
    # T：上 1 下 3
    assert tetris.TETROMINOES['T'] == [
        [0, 0, 0, 0],
        [0, 1, 0, 0],
        [1, 1, 1, 0],
        [0, 0, 0, 0],
    ]
    # S：下 2 左对齐 + 上 2 右对齐
    assert tetris.TETROMINOES['S'] == [
        [0, 0, 0, 0],
        [0, 1, 1, 0],
        [1, 1, 0, 0],
        [0, 0, 0, 0],
    ]
    # Z：上 2 左对齐 + 下 2 右对齐
    assert tetris.TETROMINOES['Z'] == [
        [0, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 0, 0],
    ]
    # J：左竖 2 + 下横 3
    assert tetris.TETROMINOES['J'] == [
        [0, 0, 0, 0],
        [1, 0, 0, 0],
        [1, 1, 1, 0],
        [0, 0, 0, 0],
    ]
    # L：右竖 2 + 下横 3
    assert tetris.TETROMINOES['L'] == [
        [0, 0, 0, 0],
        [0, 0, 1, 0],
        [1, 1, 1, 0],
        [0, 0, 0, 0],
    ]


# ---------------------------------------------------------------------------
# TC-U-02：旋转（FR-09）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('ptype', ['I', 'O', 'T', 'S', 'Z', 'J', 'L'])
def test_tc_u02_rotate_4_times_restores(ptype):
    """任意方块连续顺时针旋转 4 次后回到原矩阵。"""
    m = tetris.TETROMINOES[ptype]
    cur = [list(row) for row in m]
    for _ in range(4):
        cur = tetris.rotate_cw(cur)
    assert cur == m


def test_tc_u02_i_rotates_horizontal_to_vertical():
    """I 方块旋转 1 次：横条变竖条。"""
    m = tetris.rotate_cw(tetris.TETROMINOES['I'])
    assert m == [
        [0, 0, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 0],
        [0, 0, 1, 0],
    ]


def test_tc_u02_o_rotation_invariant():
    """O 方块旋转后矩阵不变（标准表现）。"""
    m = tetris.TETROMINOES['O']
    assert tetris.rotate_cw(m) == m


def test_tc_u02_t_rotation_is_90deg_cw():
    """T 方块旋转 1 次为顺时针 90°（尖端朝右）。"""
    m = tetris.rotate_cw(tetris.TETROMINOES['T'])
    assert m == [
        [0, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 0],
    ]
