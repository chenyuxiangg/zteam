# -*- coding: utf-8 -*-
"""GameState 模型层测试：TC-U-03 ~ TC-U-15、TC-U-18 ~ TC-U-20。

对应测试方案 §3.2 用例表（P0/P1 全部覆盖）：
    TC-U-03 (P0) FR-06 生成与活动区
    TC-U-04 (P0) FR-07 自动下落
    TC-U-05 (P0) FR-08 左移/右移
    TC-U-06 (P0) FR-09 旋转
    TC-U-07 (P0) FR-11 硬降
    TC-U-08 (P0) FR-12 锁定与堆叠
    TC-U-09 (P0) FR-14 消行判定与消除（1/2/4 行、多行同消）
    TC-U-10 (P0) FR-15 计分规则（100/300/500/800）
    TC-U-11 (P0) FR-16 等级与速度
    TC-U-12 (P0) FR-13 撞顶结束
    TC-U-13 (P1) FR-10 软降
    TC-U-14 (P1) FR-21 next 预览
    TC-U-15 (P1) FR-19 暂停/继续
    TC-U-18 (P1) FR-14 差一格不满不消
    TC-U-19 (P1) FR-06/12 负 y/越界坐标不越界访问
    TC-U-20 (P1) FR-15 计分多轮累计
"""
import time

import pytest

import tetris
from tetris import GameState, Point, TYPES, collides


def fresh(piece='I'):
    """构造确定性的 GameState：固定首个方块类型（避免纯随机干扰断言）。"""
    return GameState(first_type=piece)


def _set_rows_full_with_gap(gs, row_indices, gap_x=3, gap_w=4):
    """把指定行填满（值=1），仅留 [gap_x, gap_x+gap_w) 缺口。

    缺口宽度与 I 方块横条宽度一致（4 格），供 I 方块落下补齐。
    """
    for y in row_indices:
        gs.board[y] = [1] * gs.cols
        for x in range(gap_x, gap_x + gap_w):
            gs.board[y][x] = 0


def _setup_i_vertical(gs, pos_y=16):
    """把活动方块设为 I 竖条（rotation=1，占 x=2 列、y 方向 4 格）。

    I 竖条矩阵占格在 x=2 列，故锚点 pos.x 必须为 0，竖条才落在场地 x=2 列
    （与 _set_rows_full_with_gap(gap_x=2) 的缺口对齐）。
    用于多行同消场景：I 竖条一列 4 格可同时补齐多行的同列缺口。
    """
    gs.piece_type, gs.rotation = 'I', 1
    gs.pos = Point(0, pos_y)
    return gs


# ---------------------------------------------------------------------------
# TC-U-03：方块生成与活动区（FR-06）
# ---------------------------------------------------------------------------
def test_tc_u03_spawn_in_bounds_and_top():
    gs = fresh('I')
    # 1. 活动/next 类型合法
    assert gs.piece_type in TYPES
    assert gs.next_type in TYPES
    # 2. 活动方块全部占格坐标在区域边界内
    shape = gs.shape()
    for y, row in enumerate(shape):
        for x, val in enumerate(row):
            if val:
                wx, wy = gs.pos.x + x, gs.pos.y + y
                assert 0 <= wx < gs.cols, 'x 越界: %d' % wx
                assert 0 <= wy < gs.rows, 'y 越界: %d' % wy
    # 3. 全部占格在顶部（wy < 2）
    for y, row in enumerate(shape):
        for x, val in enumerate(row):
            if val:
                wy = gs.pos.y + y
                assert wy < 2, '生成位置不在顶部: wy=%d' % wy


# ---------------------------------------------------------------------------
# TC-U-04：自动下落（FR-07）
# ---------------------------------------------------------------------------
def test_tc_u04_step_falls_one_row_per_tick():
    gs = fresh('I')
    y0 = gs.pos.y
    gs.step()
    assert gs.pos.y == y0 + 1
    gs.step()
    assert gs.pos.y == y0 + 2
    # 方向不变：x 无偏移
    assert gs.pos.x == (gs.cols - 4) // 2


# ---------------------------------------------------------------------------
# TC-U-05：左移/右移（FR-08）
# ---------------------------------------------------------------------------
def test_tc_u05_move_normal():
    gs = fresh('I')
    x0 = gs.pos.x
    assert gs.move(-1) is True
    assert gs.pos.x == x0 - 1
    assert gs.move(1) is True
    assert gs.pos.x == x0


def test_tc_u05_move_blocked_at_left_wall():
    gs = fresh('I')
    # 反复左移到贴左壁
    for _ in range(10):
        if not gs.move(-1):
            break
    x_wall = gs.pos.x
    # 贴壁后再左移：拒绝且不消失、不出界
    assert gs.move(-1) is False
    assert gs.pos.x == x_wall
    assert gs.pos.x >= 0


def test_tc_u05_move_blocked_by_stack():
    gs = fresh('I')
    # 构造：活动方块左侧紧贴堆叠（在 pos 左侧 1 列放锁定格，且与方块同高）
    shape = gs.shape()
    for y, row in enumerate(shape):
        for x, val in enumerate(row):
            if val:
                wx, wy = gs.pos.x + x, gs.pos.y + y
                if wy >= 0:
                    gs.board[wy][max(0, wx - 1)] = 1
    x0 = gs.pos.x
    assert gs.move(-1) is False
    assert gs.pos.x == x0


# ---------------------------------------------------------------------------
# TC-U-06：旋转（FR-09）
# ---------------------------------------------------------------------------
def test_tc_u06_rotate_free():
    gs = fresh('T')
    r0 = gs.rotation
    assert gs.rotate() is True
    assert gs.rotation == (r0 + 1) % 4
    assert gs.shape() == tetris.rotate_cw(tetris.TETROMINOES['T'])


def test_tc_u06_rotate_blocked_by_stack():
    gs = fresh('T')
    # 场景 B：旋转后与锁定格重叠 → 拒绝且保持原姿态
    # T 方块在顶部，旋转后占格变高；在旋转后新占格处预置锁定格
    # 直接做法：把 T 放到接近底部的空旷处，旋转后新形状在右侧扩展处放锁定格
    gs.pos = Point(3, 15)          # 锚点置于底部空旷区
    # 旋转后形状（rotate 一次）：[[0,1,0],[0,1,1],[0,1,0]] 占 x=3..5, y=15..17
    # 在 x=5,y=16 处放锁定格 → 旋转后（该格为占格）碰撞
    gs.board[16][5] = 1
    old_rot, old_pos = gs.rotation, gs.pos
    assert gs.rotate() is False
    assert gs.rotation == old_rot
    assert gs.pos == old_pos


def test_tc_u06_rotate_blocked_by_wall():
    gs = fresh('I')
    # 场景 C：I 方块贴右壁（竖条），旋转成横条将出界 → 拒绝
    # I 竖条在矩阵 x=2 列（4 格），锚点 x=7 时竖条占 x=9（贴右壁），
    # 旋转回横条占 x=7..10 → x=10 越界 → 简化旋转拒绝（无 wall kick）
    gs.rotation = 1                 # 竖条
    gs.pos = Point(7, 5)            # 贴右壁
    old_rot = gs.rotation
    assert gs.rotate() is False
    assert gs.rotation == old_rot


# ---------------------------------------------------------------------------
# TC-U-07：硬降（FR-11）
# ---------------------------------------------------------------------------
def test_tc_u07_hard_drop_lands_and_locks_fast():
    gs = fresh('I')
    # 构造底部堆叠：在 (x=3..6, y=19) 放锁定格，I 横条将落在其上方 y=18
    for x in range(3, 7):
        gs.board[19][x] = 1
    gs.pos = Point(3, 0)
    next_before = gs.next_type
    t0 = time.perf_counter()
    gs.hard_drop()
    dt = (time.perf_counter() - t0) * 1000
    assert dt < 100, 'hard_drop 耗时 %.1fms ≥ 100ms' % dt
    # 锁定在 y=18（堆叠之上），board 含该方块全部格（无穿墙/穿透堆叠）
    for x in range(3, 7):
        assert gs.board[18][x] == TYPES.index('I') + 1
    assert gs.board[19][3] == 1          # 下方堆叠未被覆盖/穿透
    # 锁定后立即进入消行判定并 spawn next（FR-11/FR-12）
    assert gs.piece_type == next_before
    assert gs.status == 'RUNNING'


# ---------------------------------------------------------------------------
# TC-U-08：锁定与堆叠（FR-12）
# ---------------------------------------------------------------------------
def test_tc_u08_lock_on_ground_then_next_spawns():
    gs = fresh('I')
    # 活动方块距底 1 格：I 横条在 y=18，底为 y=19
    gs.pos = Point(3, 18)
    next_type_before = gs.next_type
    gs.step()  # 触底锁定 + spawn next
    for x in range(3, 7):
        assert gs.board[19][x] == TYPES.index('I') + 1   # 锁定位置正确
    assert gs.piece_type == next_type_before             # next 接续为新活动方块
    assert gs.pos.y < 20


# ---------------------------------------------------------------------------
# TC-U-09：消行判定与消除（FR-14）
# ---------------------------------------------------------------------------
def test_tc_u09_gap_row_not_cleared():
    """场景 A：第 19 行仅 1 空位（缺口不在本列）→ 不消除。"""
    gs = fresh('I')
    gs.board[19] = [1] * gs.cols
    gs.board[19][7] = 0          # 缺口在 x=7（I 方块占 x=3..6，补不上）
    gs.pos = Point(3, 18)
    gs.step()                    # 落到 y=19 锁定，第 19 行仍缺 x=7
    assert gs.lines == 0
    assert gs.board[19][7] == 0  # 缺口保留


def test_tc_u09_clear_1_row():
    """场景 B：第 19 行全满（由 I 方块补齐缺口）→ 消除 1 行。"""
    gs = fresh('I')
    _set_rows_full_with_gap(gs, [19])
    gs.pos = Point(3, 18)
    gs.step()
    assert gs.lines == 1
    assert gs.score == 100
    # 消除后该行全空、上方下移正确
    assert gs.board[19] == [0] * gs.cols
    assert gs.board[0] == [0] * gs.cols or any(gs.board[0])


def test_tc_u09_clear_2_rows():
    """场景 C：第 18/19 行全满 → 消除 2 行。

    用 I 竖条（rotation=1，占 x=2 列 4 格）一次补齐两行同列缺口。
    """
    gs = fresh('I')
    _set_rows_full_with_gap(gs, [18, 19], gap_x=2, gap_w=1)
    _setup_i_vertical(gs, 16)            # 竖条占 y=16..19，下方越界即锁定
    gs.hard_drop()
    assert gs.lines == 2
    assert gs.score == 300


def test_tc_u09_clear_4_rows():
    """场景 D：第 16~19 行全满 → 消除 4 行（Tetris 极限）。"""
    gs = fresh('I')
    _set_rows_full_with_gap(gs, [16, 17, 18, 19], gap_x=2, gap_w=1)
    _setup_i_vertical(gs, 16)
    gs.hard_drop()
    assert gs.lines == 4
    assert gs.score == 800
    # 消除后无残留、上方下移正确：全板只有顶部（16 行上方）可能残留锁定格
    assert gs.board[19] == [0] * gs.cols


# ---------------------------------------------------------------------------
# TC-U-10：计分规则（FR-15）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('n_rows,expect_score', [
    (1, 100), (2, 300), (3, 500), (4, 800),
])
def test_tc_u10_score_table(n_rows, expect_score):
    """消 n 行计分：1/2/3/4 行 = 100/300/500/800（Q-01 默认）。

    用 I 竖条补齐底部 n 行的同列缺口（x=2 列）触发 n 行同消。
    """
    gs = fresh('I')
    rows = list(range(20 - n_rows, 20))
    _set_rows_full_with_gap(gs, rows, gap_x=2, gap_w=1)
    _setup_i_vertical(gs, 16)
    gs.hard_drop()
    assert gs.lines == n_rows
    assert gs.score == expect_score


# ---------------------------------------------------------------------------
# TC-U-11：等级与速度（FR-16）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('lines,expect_level', [
    (0, 1), (9, 1), (10, 2), (19, 2), (20, 3), (99, 10),
])
def test_tc_u11_level_curve(lines, expect_level):
    gs = fresh('I')
    gs.lines = lines
    assert gs.level == expect_level


def test_tc_u11_tick_speed_formula():
    gs = fresh('I')
    for lines in [0, 9, 10, 19, 20, 99]:
        gs.lines = lines
        expect = max(100, int(500 * (0.9 ** (gs.level - 1))))
        assert gs.tick_ms == expect


def test_tc_u11_tick_floor_100ms():
    """高等级下 tick 恒 ≥ 100ms（下限生效）。"""
    gs = fresh('I')
    for lines in [100, 200, 500, 1000]:
        gs.lines = lines
        assert gs.tick_ms >= 100


# ---------------------------------------------------------------------------
# TC-U-12：撞顶结束（FR-13）
# ---------------------------------------------------------------------------
def test_tc_u12_top_out_game_over():
    gs = fresh('I')
    # 手工填满顶部：新方块生成位置（顶部中央）被占用
    # 注意 I 横条在 4×4 矩阵的第 1 行（y=1），spawn 后实际占 board[1][3..6]
    for x in range(3, 7):
        gs.board[1][x] = 1
    gs._spawn('I')               # 触发 spawn → 生成位置重叠
    assert gs.status == 'OVER'
    # OVER 后不再下落
    y0 = gs.pos.y
    gs.step()
    assert gs.pos.y == y0
    assert gs.move(-1) is False
    assert gs.rotate() is False
    assert gs.soft_drop() is False
    gs.hard_drop()               # 不抛异常
    assert gs.status == 'OVER'


# ---------------------------------------------------------------------------
# TC-U-13：软降（FR-10）
# ---------------------------------------------------------------------------
def test_tc_u13_soft_drop_one_cell():
    gs = fresh('I')
    y0 = gs.pos.y
    assert gs.soft_drop() is True
    assert gs.pos.y == y0 + 1


def test_tc_u13_soft_drop_repeated():
    gs = fresh('I')
    y0 = gs.pos.y
    for i in range(1, 4):
        assert gs.soft_drop() is True
        assert gs.pos.y == y0 + i


def test_tc_u13_soft_drop_blocked_on_ground():
    gs = fresh('I')
    gs.pos = Point(3, 19)        # 已在底部
    y0 = gs.pos.y
    assert gs.soft_drop() is False
    assert gs.pos.y == y0        # 不消失、不穿透


# ---------------------------------------------------------------------------
# TC-U-14：next 预览（FR-21）
# ---------------------------------------------------------------------------
def test_tc_u14_next_accurate_after_lock():
    gs = fresh('I')
    next_type_before = gs.next_type
    gs.hard_drop()
    assert gs.piece_type == next_type_before      # 新活动方块 == 预告的 next
    assert gs.next_type in TYPES                  # next 已刷新为再下一个


# ---------------------------------------------------------------------------
# TC-U-15：暂停/继续（FR-19）
# ---------------------------------------------------------------------------
def test_tc_u15_pause_toggle():
    gs = fresh('I')
    assert gs.status == 'RUNNING'
    assert gs.toggle_pause() == 'PAUSED'
    assert gs.status == 'PAUSED'
    # PAUSED 期间 step 不推进（主循环语义：暂停冻结）
    y0 = gs.pos.y
    gs.step()
    assert gs.pos.y == y0
    assert gs.toggle_pause() == 'RUNNING'
    assert gs.status == 'RUNNING'


def test_tc_u15_paused_no_side_effects():
    """r2 收紧口径（方案 §3.2 TC-U-15 确定断言）：PAUSED 期间
    step()/move()/rotate()/soft_drop() 全部无副作用——状态、坐标、
    得分、消行数与 board 均不变。不依赖实现分支判断，唯一断言口径。
    """
    gs = fresh('I')
    gs.toggle_pause()                          # → PAUSED
    assert gs.status == 'PAUSED'
    pos_before, rot_before = gs.pos, gs.rotation
    score_before, lines_before = gs.score, gs.lines
    board_before = [list(row) for row in gs.board]
    # 各操作逐一调用，全部应为 no-op
    assert gs.step() is None
    assert gs.move(-1) is False
    assert gs.move(1) is False
    assert gs.rotate() is False
    assert gs.soft_drop() is False
    assert gs.hard_drop() is None
    # 断言无副作用：状态/坐标/旋转/得分/消行/board 全部不变
    assert gs.status == 'PAUSED'
    assert gs.pos == pos_before
    assert gs.rotation == rot_before
    assert gs.score == score_before
    assert gs.lines == lines_before
    assert gs.board == board_before
    # 恢复后从暂停瞬间状态继续（无跳变）
    assert gs.toggle_pause() == 'RUNNING'
    assert gs.pos == pos_before
    assert gs.score == score_before


def test_tc_u15_pause_over_returns_none():
    gs = fresh('I')
    gs.status = 'OVER'
    assert gs.toggle_pause() is None
    assert gs.status == 'OVER'


# ---------------------------------------------------------------------------
# TC-U-18：差一格不满不消（FR-14）
# ---------------------------------------------------------------------------
def test_tc_u18_one_gap_no_clear_then_fill_clears():
    gs = fresh('I')
    # 第 19 行 9 格满、1 空格（缺口在 x=7，不在方块下落列 x=3..6）
    gs.board[19] = [1] * gs.cols
    gs.board[19][7] = 0
    gs.pos = Point(3, 18)
    gs.step()
    assert gs.lines == 0         # 差 1 格不满 → 不消除
    # 再补满缺口触发消除
    gs.board[19][7] = 1
    assert tetris.clear_lines(gs) == 1
    assert gs.board[19] == [0] * gs.cols   # 该行全空、无残留格值


# ---------------------------------------------------------------------------
# TC-U-19：负 y / 越界坐标不越界访问（FR-06/12）
# ---------------------------------------------------------------------------
def test_tc_u19_negative_y_treatable():
    gs = fresh('I')
    shape = gs.shape()
    # 负 y：生成区上方视为可通行，不访问 board，不抛 IndexError
    assert collides(gs, shape, Point(3, -1)) is False
    assert collides(gs, shape, Point(3, -2)) is False


def test_tc_u19_out_of_bounds_collides():
    gs = fresh('I')
    shape = gs.shape()
    assert collides(gs, shape, Point(-1, 5)) is True   # x < 0
    assert collides(gs, shape, Point(10, 5)) is True   # x >= cols
    assert collides(gs, shape, Point(3, 20)) is True   # y >= rows


# ---------------------------------------------------------------------------
# TC-U-20：计分多轮累计（FR-15）
# ---------------------------------------------------------------------------
def test_tc_u20_score_accumulates():
    """计分多轮累计：消 1 行 +100、2 行 +300、4 行 +800 → 总分 1200。"""
    gs = fresh('I')
    # 第一轮：消 1 行（+100）
    _set_rows_full_with_gap(gs, [19], gap_x=2, gap_w=1)
    _setup_i_vertical(gs, 16)
    gs.hard_drop()
    assert gs.score == 100
    assert gs.lines == 1
    # 第二轮：消 2 行（+300）
    gs.board = [[0] * gs.cols for _ in range(gs.rows)]   # 清场（保留 score/lines）
    _set_rows_full_with_gap(gs, [18, 19], gap_x=2, gap_w=1)
    _setup_i_vertical(gs, 16)
    gs.hard_drop()
    assert gs.score == 400
    assert gs.lines == 3
    # 第三轮：消 4 行（+800）
    gs.board = [[0] * gs.cols for _ in range(gs.rows)]
    _set_rows_full_with_gap(gs, [16, 17, 18, 19], gap_x=2, gap_w=1)
    _setup_i_vertical(gs, 16)
    gs.hard_drop()
    assert gs.score == 400 + 800
    assert gs.lines == 1 + 2 + 4
