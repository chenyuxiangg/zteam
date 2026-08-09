#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
snake.py — Linux 终端贪吃蛇（纯 Python 标准库实现）

文件职责：
    单文件交付，内部按职责分层：参数解析（parse_args）/ 非 TTY 检查（check_terminal）/
    游戏模型（GameState）/ 输入处理（InputHandler）/ 渲染（Renderer）/ 主循环（main）。
    对齐需求分解文档 FR-01~FR-17 与开发方案 plans/snake-linux/snake-linux-r1.md。

依赖：
    仅 Python 标准库：argparse / curses / random / signal / sys / time /
    collections（deque、namedtuple）。运行平台：Linux（Python 3.6+，Q-05）。
    兼容性约束（方案 §5.3）：不使用 dataclass / 海象运算符 / str.removeprefix 等 3.7+ 语法。

对应方案章节：
    parse_args()      -> §3.2 / §4.1 / §5.3   （参数解析与校验，FR-03/FR-16）
    check_terminal()  -> §3.2 / §4.1 / §5.2   （非 TTY 报错，FR-02/NFR-04）
    GameState         -> §3.2 / §4.2 / §5.1   （模型层，刻意不依赖 curses，FR-05~FR-10）
    InputHandler      -> §3.2 / §5.2          （键位映射，FR-06/FR-07/FR-13）
    Renderer          -> §3.2 / §5.2          （ASCII 边框/HUD/结束画面，FR-11/FR-16/FR-17）
    main / run        -> §3.3 / §5.2          （tick 主循环、退出路径，FR-13/FR-14）
"""

import argparse
import curses
import random
import signal
import sys
import time
from collections import deque, namedtuple

# ---------------------------------------------------------------------------
# 常量（方案 §4.1/§5.3）
# ---------------------------------------------------------------------------
MIN_DIM = 10            # 画布最小边长（最小可玩画布 10x10）
DEFAULT_TICK_MS = 200   # 默认帧间隔（FR-03）
MIN_TICK_MS = 50        # tick 下限
MAX_TICK_MS = 1000      # tick 上限
FRAME_SLICE_MS = 50     # getch 最大阻塞粒度（方案 §5.1，兼顾 50ms 最小 tick 与低 CPU）

# 方向向量（y 向下，0,0 为画布左上角）
UP = (0, -1)
DOWN = (0, 1)
LEFT = (-1, 0)
RIGHT = (1, 0)

Point = namedtuple('Point', 'x y')   # 画布内坐标，0 <= x < width, 0 <= y < height


# ---------------------------------------------------------------------------
# 模型层：GameState（纯逻辑，不依赖 curses）—— 方案 §3.2/§4.2/§5.1
# ---------------------------------------------------------------------------
class GameState(object):
    """游戏模型。

    蛇身 deque 头在右端（snake[-1] 为蛇头）；step() 每 tick 推进一次，执行
    移动/吃食/碰撞/胜利判定（FR-05/FR-08/FR-09/FR-10）。本类不 import curses，
    可脱离终端做确定性单元验证（对齐 NFR-05 职责分离与方案 §2 选型结论）。
    """

    RUNNING = 'RUNNING'
    OVER = 'OVER'
    WIN = 'WIN'

    def __init__(self, width=40, height=20, tick_ms=DEFAULT_TICK_MS,
                 snake=None, direction=None, food=None, score=0, status=None):
        self.width = width
        self.height = height
        self.tick_ms = tick_ms
        self.score = score
        self.direction = direction if direction is not None else RIGHT
        self.pending = None                  # 本 tick 内未消费的转向（单槽，防快速连按）
        if snake is None:
            # 初始蛇身 3 节向右，蛇头位于画布中央偏左区域（方案 §1 A-03）
            cx, cy = width // 2, height // 2
            snake = [Point(cx - 2, cy), Point(cx - 1, cy), Point(cx, cy)]
        self.snake = deque(snake)
        self.status = status if status is not None else self.RUNNING
        self.food = food
        if self.food is None:
            self._spawn_food()               # 画布已占满时置 WIN（理论边界）

    # ---- 转向（FR-06/FR-07）----
    def turn(self, direction):
        """请求转向。

        反向禁止（FR-07）：与当前方向或待定方向相反的直接忽略；pending 单槽：
        新转向覆盖未消费转向，杜绝快速连按导致的「反向自杀」（方案 §5.2）。
        返回 True 表示接受（写入 pending），False 表示忽略。
        """
        if direction == self.direction:
            return False
        if self._is_opposite(direction, self.direction):
            return False
        if self.pending is not None and self._is_opposite(direction, self.pending):
            return False
        self.pending = direction
        return True

    @staticmethod
    def _is_opposite(a, b):
        return a[0] + b[0] == 0 and a[1] + b[1] == 0

    # ---- 推进（FR-05/FR-08/FR-09/FR-10）----
    def step(self):
        """推进一个 tick：消费 pending 转向，移动蛇头，判定碰撞/吃食/胜利（方案 §5.1）。"""
        if self.status != self.RUNNING:
            return
        self._apply_pending()
        head = self.snake[-1]
        nh = Point(head.x + self.direction[0], head.y + self.direction[1])
        # 撞墙（FR-10）：蛇头越出画布边界即结束
        if not (0 <= nh.x < self.width and 0 <= nh.y < self.height):
            self.status = self.OVER
            return
        body = set(self.snake)
        eating = (nh == self.food)
        # 撞自身（FR-10）：仅当「新头 == 旧尾 且 本 tick 不吃食（旧尾将移走）」时允许让行
        if nh in body and not (nh == self.snake[0] and not eating):
            self.status = self.OVER
            return
        self.snake.append(nh)
        if eating:
            self.score += 1                  # 每食 +1（Q-01）
            self._spawn_food()               # 吃食后 1 tick 内重新生成（FR-08）
        else:
            self.snake.popleft()             # 头进尾出，长度不变（FR-05）

    def _apply_pending(self):
        if self.pending is not None:
            self.direction = self.pending
            self.pending = None

    # ---- 食物生成（FR-08）----
    def _spawn_food(self):
        """空闲格列表选点，避免随机重试在蛇占满时死循环；空闲为空置 WIN（方案 §5.1）。"""
        occupied = set(self.snake)
        free = []
        for y in range(self.height):
            for x in range(self.width):
                p = Point(x, y)
                if p not in occupied:
                    free.append(p)
        if not free:
            self.status = self.WIN
            return
        self.food = random.choice(free)


# ---------------------------------------------------------------------------
# 输入层：InputHandler（键位映射）—— 方案 §3.2/§5.2
# ---------------------------------------------------------------------------
class InputHandler(object):
    """键位映射：WASD/方向键 -> 方向向量，q/Q -> 退出，其余键忽略。"""

    _KEYS = {
        ord('w'): UP, ord('W'): UP, curses.KEY_UP: UP,
        ord('s'): DOWN, ord('S'): DOWN, curses.KEY_DOWN: DOWN,
        ord('a'): LEFT, ord('A'): LEFT, curses.KEY_LEFT: LEFT,
        ord('d'): RIGHT, ord('D'): RIGHT, curses.KEY_RIGHT: RIGHT,
    }

    @staticmethod
    def direction_for(ch):
        """返回 ch 对应的方向向量；非方向键返回 None。"""
        return InputHandler._KEYS.get(ch)

    @staticmethod
    def is_quit(ch):
        """q/Q 为退出键（FR-13）。"""
        return ch in (ord('q'), ord('Q'))


# ---------------------------------------------------------------------------
# 渲染层：Renderer（curses 封装）—— 方案 §3.2/§5.2，FR-11/FR-16/FR-17
# ---------------------------------------------------------------------------
class Renderer(object):
    """终端渲染。

    全量重绘（erase + 绘制 + refresh），无残影（方案 §5.2）；边框用纯 ASCII
    （+ - |），不依赖 Unicode 制表符与 256 色，利于终端兼容性（NFR-06，方案 §6）。
    布局：第 0 行 HUD，第 1..H+2 行边框与画布，第 H+3 行操作提示，共 H+4 行。
    """

    FOOD_CH = '*'
    HEAD_CH = 'O'
    BODY_CH = 'o'

    def __init__(self, stdscr):
        self.stdscr = stdscr

    def draw(self, state):
        """绘制进行中画面：HUD + ASCII 边框 + 蛇/食物 + 底部操作提示。"""
        scr = self.stdscr
        scr.erase()
        w, h = state.width, state.height
        # HUD（FR-17）：顶部固定行，持续显示得分（含 tick 间隔）
        hud = 'Score: {0}    tick: {1}ms'.format(state.score, state.tick_ms)
        self._safe_add(0, 0, hud)
        # 边框（FR-16）：纯 ASCII，宽 w+2、高 h+2
        border = '+' + '-' * w + '+'
        self._safe_add(1, 0, border)
        for y in range(h):
            self._safe_add(2 + y, 0, '|')
            self._safe_add(2 + y, w + 1, '|')
        self._safe_add(h + 2, 0, border)
        # 画布内容：食物 + 蛇（食物恒不与蛇身重叠，FR-08）
        self._safe_add(2 + state.food.y, 1 + state.food.x, self.FOOD_CH)
        head_idx = len(state.snake) - 1
        for i, seg in enumerate(state.snake):
            ch = self.HEAD_CH if i == head_idx else self.BODY_CH
            self._safe_add(2 + seg.y, 1 + seg.x, ch)
        # 底部操作提示
        self._safe_add(h + 3, 0, 'WASD/方向键移动   q 退出')

    def draw_game_over(self, state):
        """结束画面（FR-11）：居中显示结果、最终得分与「按任意键退出」提示。"""
        scr = self.stdscr
        scr.erase()
        h, w = scr.getmaxyx()
        title = 'YOU WIN!' if state.status == state.WIN else 'GAME OVER'
        lines = [title, '', '最终得分: {0}'.format(state.score), '', '按任意键退出']
        start_y = max(h // 2 - len(lines) // 2, 0)
        for i, line in enumerate(lines):
            y = start_y + i
            if 0 <= y < h:
                x = max((w - len(line)) // 2, 0)
                self._safe_add(y, x, line)

    def _safe_add(self, y, x, text):
        """addstr 越界防护（终端 resize 竞态下不崩溃，NFR-04 友好失败）。"""
        try:
            self.stdscr.addstr(y, x, text)
        except curses.error:
            pass


# ---------------------------------------------------------------------------
# 配置层：parse_args / check_terminal —— 方案 §3.2/§4.1/§5.3
# ---------------------------------------------------------------------------
def _tick_type(value):
    """--tick 校验（FR-03）：50-1000ms 整数，越界给出可读中文错误（无裸 traceback）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            'tick 必须是 {0}-{1} 之间的整数（毫秒），收到: {2!r}'.format(
                MIN_TICK_MS, MAX_TICK_MS, value))
    if not MIN_TICK_MS <= n <= MAX_TICK_MS:
        raise argparse.ArgumentTypeError(
            'tick 必须在 {0}-{1}ms 范围内，收到: {2}'.format(MIN_TICK_MS, MAX_TICK_MS, n))
    return n


def _dim_type(value):
    """--width/--height 校验（方案 §5.3）：正整数且不小于最小可玩边长 10。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('尺寸必须是正整数，收到: {0!r}'.format(value))
    if n < MIN_DIM:
        raise argparse.ArgumentTypeError(
            '尺寸必须不小于 {0}（最小可玩画布 {0}x{0}），收到: {1}'.format(MIN_DIM, n))
    return n


def parse_args(argv=None):
    """命令行参数解析（方案 §4.1）。参数错误：argparse 输出可读提示并以退出码 2 结束。"""
    parser = argparse.ArgumentParser(
        prog='snake.py',
        description='Linux 终端贪吃蛇（纯 Python 标准库实现）',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--tick', type=_tick_type, default=DEFAULT_TICK_MS, metavar='MS',
                        help='游戏帧间隔（毫秒），范围 {0}-{1}'.format(MIN_TICK_MS, MAX_TICK_MS))
    parser.add_argument('--width', type=_dim_type, default=40, metavar='N',
                        help='画布宽度（格），不小于 {0}'.format(MIN_DIM))
    parser.add_argument('--height', type=_dim_type, default=20, metavar='N',
                        help='画布高度（格），不小于 {0}'.format(MIN_DIM))
    return parser.parse_args(argv)


def check_terminal():
    """非 TTY 检查（FR-02/NFR-04）：stdin/stdout 任一非终端即输出明确中文提示并以退出码 1 结束。"""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write('错误：本游戏需要在 Linux 终端（TTY）中运行。\n')
        sys.stderr.write('请在终端模拟器（GNOME Terminal / Konsole / xterm / SSH）中执行: python3 snake.py\n')
        sys.exit(1)


# ---------------------------------------------------------------------------
# 输入与主循环 —— 方案 §3.3/§5.2
# ---------------------------------------------------------------------------
def _handle_input(ch, state):
    """处理单个按键。返回 False 表示请求退出（q/Q，FR-13）。"""
    if ch == -1:
        return True
    if InputHandler.is_quit(ch):
        return False
    d = InputHandler.direction_for(ch)
    if d is not None:
        state.turn(d)
    return True


def _handle_resize(stdscr, state):
    """KEY_RESIZE -> resizeterm + 尺寸重查（FR-04/方案 §5.2）。

    尺寸不足时暂停游戏（tick 不推进）并显示提示，等待窗口恢复；
    返回 False 表示用户在该状态下按 q 请求退出。
    """
    curses.resizeterm()
    while True:
        lines, cols = stdscr.getmaxyx()
        if lines >= state.height + 4 and cols >= state.width + 2:
            return True
        stdscr.erase()
        msg = '终端太小: 需要至少 {0}x{1}，当前 {2}x{3}；请放大窗口后继续'.format(
            state.width + 2, state.height + 4, cols, lines)
        try:
            stdscr.addstr(0, 0, msg)
        except curses.error:
            pass
        stdscr.refresh()
        c = stdscr.getch()
        if c == curses.KEY_RESIZE:
            curses.resizeterm()
            continue
        if InputHandler.is_quit(c):
            return False


def _sigterm_handler(signum, frame):
    """SIGTERM 走与 Ctrl+C 相同的恢复路径（方案 §5.2，防 systemd/kill 场景终端残留）。"""
    raise KeyboardInterrupt


def main(stdscr, args):
    """主流程（方案 §3.3）：初始化序列 -> 尺寸检查 -> tick 驱动主循环 -> 结束收尾。"""
    signal.signal(signal.SIGTERM, _sigterm_handler)
    stdscr.keypad(True)                # 方向键转义序列 -> KEY_UP/DOWN/LEFT/RIGHT
    try:
        curses.curs_set(0)             # 隐藏光标
    except curses.error:
        pass
    lines, cols = stdscr.getmaxyx()
    # 尺寸检查（FR-04）：COLS >= W+2 且 LINES >= H+4（边框 2 行 + HUD 1 行 + 提示 1 行）
    if lines < args.height + 4 or cols < args.width + 2:
        curses.endwin()                # 先恢复终端再输出提示，避免破坏屏幕
        sys.stderr.write('终端尺寸不足: 需要至少 {0}x{1}，当前 {2}x{3}\n'.format(
            args.width + 2, args.height + 4, cols, lines))
        return 3
    state = GameState(width=args.width, height=args.height, tick_ms=args.tick)
    renderer = Renderer(stdscr)
    stdscr.timeout(FRAME_SLICE_MS)     # getch 最多阻塞 50ms，非忙等（NFR-02）
    last = time.monotonic()            # 单调时钟，tick 精度稳定（NFR-01，方案 §2）
    while state.status == state.RUNNING:
        ch = stdscr.getch()
        if ch == curses.KEY_RESIZE:
            if not _handle_resize(stdscr, state):
                break                  # 尺寸不足提示中用户按 q 退出
        elif not _handle_input(ch, state):
            break                      # q/Q 退出（FR-13）
        now = time.monotonic()
        if now - last >= state.tick_ms / 1000.0:
            state.step()
            last = now
        renderer.draw(state)
    # 结束画面（FR-11）：稳定显示最终得分，按任意键退出（Q-08 默认）
    if state.status != state.RUNNING:
        renderer.draw_game_over(state)
        stdscr.timeout(-1)             # 阻塞等待任意键
        stdscr.getch()
    return 0


def run():
    """顶层入口：参数 -> 非 TTY 检查 -> wrapper 包裹主循环（FR-14/NFR-03 终端恢复）。"""
    args = parse_args()
    check_terminal()
    try:
        code = curses.wrapper(main, args)
    except KeyboardInterrupt:
        # curses.wrapper 的 finally 已恢复终端原始状态（FR-14）；此处输出友好退出信息
        sys.stderr.write('已退出（Ctrl+C/SIGTERM）。终端状态已恢复。\n')
        code = 130
    except Exception as exc:           # 兜底：curses 初始化等异常，避免裸 traceback（NFR-04）
        sys.stderr.write('启动失败: {0}\n'.format(exc))
        code = 1
    sys.exit(code)


if __name__ == '__main__':
    run()
