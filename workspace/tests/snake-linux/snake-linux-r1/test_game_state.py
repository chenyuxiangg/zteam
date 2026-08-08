# -*- coding: utf-8 -*-
"""GameState 单元测试：对应测试方案 TC-U-01 ~ TC-U-10。

覆盖 FR-05 移动 / FR-06 方向控制 / FR-07 反向禁止 / FR-08 食物生成 /
FR-09 吃食增长得分 / FR-10 碰撞判定 / FR-16 画布边界（逻辑面）。
"""
import pytest

import snake
from snake import GameState, Point

RIGHT, LEFT, UP, DOWN = snake.RIGHT, snake.LEFT, snake.UP, snake.DOWN


def make_state(snake_body, direction=RIGHT, width=40, height=20, food=None):
    """构造确定性 GameState：显式指定蛇身/方向/食物，避免随机食物干扰断言。

    food 默认置于 (width-1, height-1) 且不与蛇身重叠的角落（远离蛇路径）。
    """
    if food is None:
        food = Point(width - 1, height - 1)
    return GameState(width=width, height=height,
                     snake=list(snake_body), direction=direction, food=food)


# ---------------------------------------------------------------------------
# TC-U-01（P0，FR-05）：蛇的移动——不操作输入时每 tick 前进 1 格，方向不变，
# 不吃食时长度不变（头进尾出）
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u01_snake_moves_forward():
    s = make_state([Point(18, 10), Point(19, 10), Point(20, 10)])
    s.step()
    assert s.snake[-1] == Point(21, 10), '第一次 step 后蛇头应前进 1 格'
    assert len(s.snake) == 3, '不吃食时长度应保持 3'
    assert s.direction == RIGHT, '方向应保持不变'
    s.step()
    assert s.snake[-1] == Point(22, 10), '第二次 step 后蛇头应再前进 1 格'
    assert len(s.snake) == 3
    assert s.status == GameState.RUNNING


# ---------------------------------------------------------------------------
# TC-U-02（P0，FR-06）：方向控制——WASD 与方向键均正确改变方向，1 次 step 内生效
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u02_wasd_and_arrow_keys():
    # 注：初始方向须与目标方向不相反（否则按 FR-07 反向禁止正确拒绝，
    # 那属于 TC-U-03 的验证范围）。'a'/'d' 用例改用向下/向上起始。
    cases = [
        (ord('w'), UP, RIGHT), (ord('W'), UP, RIGHT),
        (ord('s'), DOWN, RIGHT), (ord('S'), DOWN, RIGHT),
        (ord('a'), LEFT, DOWN), (ord('A'), LEFT, DOWN),
        (ord('d'), RIGHT, UP), (ord('D'), RIGHT, UP),
    ]
    for key, want, start in cases:
        s = make_state([Point(18, 10), Point(19, 10), Point(20, 10)],
                       direction=start)
        d = snake.InputHandler.direction_for(key)
        assert d == want, '键 {0!r} 映射错误'.format(key)
        s.turn(d)
        s.step()
        assert s.direction == want, '键 {0!r} 应在 1 次 step 内生效'.format(key)


@pytest.mark.p0
def test_tc_u02_curses_arrow_keys():
    """方向键（curses.KEY_UP/DOWN/LEFT/RIGHT）与 WASD 等效。"""
    import curses
    cases = [
        (curses.KEY_UP, UP, RIGHT),
        (curses.KEY_DOWN, DOWN, RIGHT),
        (curses.KEY_LEFT, LEFT, DOWN),
        (curses.KEY_RIGHT, RIGHT, UP),
    ]
    for key, want, start in cases:
        s = make_state([Point(18, 10), Point(19, 10), Point(20, 10)],
                       direction=start)
        d = snake.InputHandler.direction_for(key)
        assert d == want, '方向键 {0!r} 映射错误'.format(key)
        s.turn(d)
        s.step()
        assert s.direction == want, '方向键 {0!r} 应在 1 次 step 内生效'.format(key)


# ---------------------------------------------------------------------------
# TC-U-03（P0，FR-07）：反向移动禁止——向右时按左被忽略，蛇不死
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u03_direct_reverse_ignored():
    s = make_state([Point(18, 10), Point(19, 10), Point(20, 10)], direction=RIGHT)
    assert s.turn(LEFT) is False, '与当前方向相反（180°）的转向应被拒绝'
    s.step()
    assert s.direction == RIGHT, '方向应仍为右'
    assert s.status == GameState.RUNNING, '不应因反向输入死亡'


# ---------------------------------------------------------------------------
# TC-U-04（P0，FR-07）：同一 tick 内连按两键——pending 单槽：后按转向与当前
# 方向或待定方向相反时被忽略（方案 §5.2 双重反向校验）
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u04_double_press_current_opposite():
    s = make_state([Point(18, 10), Point(19, 10), Point(20, 10)], direction=RIGHT)
    assert s.turn(UP) is True, '第一次转向（上）应被接受'
    assert s.turn(LEFT) is False, '第二次转向（左）与当前方向相反应被忽略'
    s.step()
    assert s.direction == UP, '蛇最终方向应向上'
    assert s.status == GameState.RUNNING


@pytest.mark.p0
def test_tc_u04_double_press_pending_opposite():
    s = make_state([Point(18, 10), Point(19, 10), Point(20, 10)], direction=RIGHT)
    assert s.turn(UP) is True
    assert s.turn(DOWN) is False, '第二次转向（下）与待定方向（上）相反应被忽略'
    s.step()
    assert s.direction == UP


# ---------------------------------------------------------------------------
# TC-U-05（P0，FR-10）：尾部让行——新头 == 旧尾且本 tick 不吃食时允许通过
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u05_tail_follow_through():
    body = [Point(0, 0), Point(1, 0), Point(1, 1), Point(0, 1)]
    s = make_state(body, direction=UP, food=Point(30, 19))
    s.step()
    assert s.status == GameState.RUNNING, '新头(0,0)==旧尾且不吃食，应允许让行'
    assert list(s.snake) == [Point(1, 0), Point(1, 1), Point(0, 1), Point(0, 0)]
    assert len(s.snake) == 4, '长度不变（头进尾出）'


# ---------------------------------------------------------------------------
# TC-U-06（P0，FR-10）：撞墙——蛇头越出画布边界（x=40）即 OVER
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u06_wall_collision():
    s = make_state([Point(0, 0), Point(1, 0), Point(2, 0)], direction=RIGHT)
    # 走到 x=39（贴右边界）
    while s.snake[-1].x < 39:
        s.step()
    assert s.snake[-1].x == 39
    assert s.status == GameState.RUNNING, '贴边时仍应运行'
    s.step()  # 下一步越出边界 x=40
    assert s.status == GameState.OVER, '蛇头越出边界应结束'
    # 结束后不再移动
    before = list(s.snake)
    s.step()
    assert list(s.snake) == before, '结束后蛇不再移动'


# ---------------------------------------------------------------------------
# TC-U-07（P0，FR-10）：撞自身——新头与身体中间节重叠（非旧尾）即 OVER
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u07_self_collision():
    body = [Point(0, 0), Point(1, 0), Point(1, 1)]
    s = make_state(body, direction=UP, food=Point(30, 19))
    s.step()
    assert s.status == GameState.OVER, '新头(1,0)与身体第二节重叠应结束'


# ---------------------------------------------------------------------------
# TC-U-08（P0，FR-09）：吃食增长与得分——每食长度 +1、得分 +1、蛇头==原食物
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u08_eat_grow_score():
    s = make_state([Point(0, 0), Point(1, 0), Point(2, 0)], direction=RIGHT,
                   food=Point(3, 0))
    s.step()
    assert s.score == 1, '吃食后得分应为 1'
    assert len(s.snake) == 4, '吃食后长度应为 3+1'
    assert s.snake[-1] == Point(3, 0), '蛇头应到达原食物坐标'
    # 连续吃 N 个：每步后把食物重置到蛇头正前方
    for i in range(1, 5):
        head = s.snake[-1]
        s.food = Point(head.x + 1, head.y)
        s.step()
        assert s.score == 1 + i, '连续吃 {0} 个后得分应为 {1}'.format(i + 1, i + 1)
        assert len(s.snake) == 4 + i
        assert s.snake[-1] == Point(3 + i, 0)


# ---------------------------------------------------------------------------
# TC-U-09（P0，FR-08）：食物生成——吃掉后新食物与蛇身全部坐标不同（重复 20 次）；
# 蛇身占满画布时置 WIN 且不抛异常（无死循环）
# ---------------------------------------------------------------------------
@pytest.mark.p0
def test_tc_u09_food_never_overlaps_snake():
    s = make_state([Point(5, 10), Point(6, 10), Point(7, 10)], direction=RIGHT,
                   food=Point(8, 10))
    for i in range(20):
        s.step()  # 吃掉 (8+i, 10) 处食物，内部立即重新生成
        assert s.food not in set(s.snake), \
            '第 {0} 次吃食后新食物不应与蛇身重叠'.format(i + 1)
        assert s.status == GameState.RUNNING
        head = s.snake[-1]
        s.food = Point(head.x + 1, head.y)  # 准备下一次吃食


@pytest.mark.p0
def test_tc_u09_full_board_win_no_hang():
    # 4x5=20 格画布，蛇身占满全部格子
    all_cells = [Point(x, y) for y in range(5) for x in range(4)]
    s = GameState(width=4, height=5, snake=all_cells, food=None)
    assert s.status == GameState.WIN, '画布占满应置 WIN'
    assert s.food is None


# ---------------------------------------------------------------------------
# TC-U-10（P1，FR-10）：4x5 画布占满后 step() 不抛异常、状态保持 WIN
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_tc_u10_full_board_step_safe():
    all_cells = [Point(x, y) for y in range(5) for x in range(4)]
    s = GameState(width=4, height=5, snake=all_cells, food=None)
    assert s.status == GameState.WIN
    s.step()  # 不应抛异常
    assert s.status == GameState.WIN
    assert len(s.snake) == 20


# ---------------------------------------------------------------------------
# 补充：FR-16 画布边界——任意合法状态下蛇与食物坐标恒在 [0, W)x[0, H) 内
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_u_extra_invariants_inside_canvas():
    s = make_state([Point(18, 10), Point(19, 10), Point(20, 10)])
    for _ in range(30):
        s.step()
        for seg in s.snake:
            assert 0 <= seg.x < s.width and 0 <= seg.y < s.height
        assert 0 <= s.food.x < s.width and 0 <= s.food.y < s.height
        if s.status != GameState.RUNNING:
            break
