#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tetris.py — Linux 终端俄罗斯方块（Python 标准库从零实现）

文件职责：
    本文件是需求 tetris/tetris 的唯一交付源码（Q-06 默认单文件）。
    内部按职责分层（对齐 NFR-05，方案 §3.2 模块划分）：
      - parse_args()          配置解析（--tick / --no-color）        [方案 §3.2 / §4.1]
      - check_terminal()      非 TTY 检查                             [FR-02]
      - TETROMINOES + rotate_cw()  7 种方块定义与顺时针旋转           [FR-05/FR-09]
      - Point / GameState     游戏逻辑模型（纯逻辑，不依赖 curses）   [FR-06~FR-16/FR-19]
      - InputHandler          键位 → 动作映射                        [FR-18~FR-20]
      - Renderer              curses 渲染（边框/场地/next/HUD/颜色）  [FR-21/22/24/26]
      - main()                初始化 + tick 主循环 + 退出收尾         [FR-04/07/19/20]
      - 顶层 wrapper()        终端状态保存与恢复（干净退出）          [FR-23/NFR-03]

依赖：仅 Python 3.6+ 标准库（argparse/curses/random/signal/sys/time）。
     Python 3.6 兼容：不使用 dataclass（3.7+）、海象运算符（3.8+）、
     str.removeprefix（3.9+）、f-string 调试格式（3.8+）。（方案 §5.3）

与方案章节映射：
    方案 §3.2 模块表        → 本文件各函数/类（见上）
    方案 §4.1 对外接口      → parse_args / check_terminal / 主循环键位
    方案 §4.2 数据结构      → Point / TETROMINOES / GameState 字段
    方案 §5.1 核心算法      → collides / clear_lines / hard_drop / 暂停相位补偿
    方案 §5.2 边界与异常    → 非 TTY / 尺寸检查 / 旋转拒绝 / 撞顶 / 信号处理
"""

import argparse
import curses
import os
import random
import signal
import sys
import time
from collections import namedtuple


# ---------------------------------------------------------------------------
# 常量：7 种标准方块（FR-05，方案 §4.2）
# 每个方块为 4×4 基础矩阵（1=占格，0=空），O 方块为 2×2 田字置于 4×4 中部。
# 形状与 Tetris Guideline 标准一致。
# ---------------------------------------------------------------------------
TETROMINOES = {
    'I': [
        [0, 0, 0, 0],
        [1, 1, 1, 1],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ],
    'O': [
        [0, 0, 0, 0],
        [0, 1, 1, 0],
        [0, 1, 1, 0],
        [0, 0, 0, 0],
    ],
    'T': [
        [0, 0, 0, 0],
        [0, 1, 0, 0],
        [1, 1, 1, 0],
        [0, 0, 0, 0],
    ],
    'S': [
        [0, 0, 0, 0],
        [0, 1, 1, 0],
        [1, 1, 0, 0],
        [0, 0, 0, 0],
    ],
    'Z': [
        [0, 0, 0, 0],
        [1, 1, 0, 0],
        [0, 1, 1, 0],
        [0, 0, 0, 0],
    ],
    'J': [
        [0, 0, 0, 0],
        [1, 0, 0, 0],
        [1, 1, 1, 0],
        [0, 0, 0, 0],
    ],
    'L': [
        [0, 0, 0, 0],
        [0, 0, 1, 0],
        [1, 1, 1, 0],
        [0, 0, 0, 0],
    ],
}

# 方块类型顺序（用于 board 值编码与渲染颜色映射；索引 0..6）
TYPES = ['I', 'O', 'T', 'S', 'Z', 'J', 'L']

# 消行计分表（FR-15，Q-01 默认：1/2/3/4 行 = 100/300/500/800；软硬降不加分 → FR-17 作废）
SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}

# 场地规格（FR-06/FR-20，Q-10 默认：固定 10 列 × 20 行，不含边框）
COLS = 10
ROWS = 20

# 最小终端尺寸（方案 §3.1：场地 22 列宽 + 侧栏 + 间距 = 42 列；场地 21 行 + 信息区 = 26 行）
MIN_COLS = 42
MIN_LINES = 26

# 等级速度参数（FR-16，Q-04 默认：每消 10 行升 1 级；每级 tick × 0.9；下限 100ms）
LINES_PER_LEVEL = 10
DEFAULT_TICK_MS = 500
MIN_TICK_MS = 100
TICK_FACTOR = 0.9

# 退出码约定（方案 §4.1 / FR-02 / FR-04）
EXIT_OK = 0
EXIT_NOT_TTY = 1
EXIT_BAD_ARGS = 2
EXIT_TOO_SMALL = 3
EXIT_INTERRUPTED = 130


Point = namedtuple('Point', 'x y')  # 场地坐标，x 向右、y 向下（方案 §4.2）


def _write_stderr(text):
    """向 stderr 写 UTF-8 文本，避免 C locale 下中文 print 抛 UnicodeEncodeError（NFR-04）。"""
    try:
        os.write(2, text.encode('utf-8'))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 配置解析（FR-03 / FR-26，方案 §3.2 parse_args / §4.1 对外接口）
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    """解析命令行参数。

    返回 argparse.Namespace，含字段：
        tick: int     下落间隔毫秒，[50, 2000]，默认 500（FR-03，Q-04）
        no_color: bool 是否关闭颜色，默认 False（FR-26，Q-11 默认纳入）
    参数非法（越界/非数字/负数）→ 输出可读错误并 exit 2（FR-03 边界，NFR-04）。
    """
    parser = argparse.ArgumentParser(
        prog='tetris',
        description='Linux 终端俄罗斯方块（Python 标准库从零实现）',
    )
    parser.add_argument(
        '--tick', type=int, default=DEFAULT_TICK_MS, metavar='MS',
        help='方块自动下落间隔，毫秒，取值 50-2000（默认 500）',
    )
    parser.add_argument(
        '--no-color', action='store_true',
        help='关闭颜色（单色终端以形状辨识方块，FR-26）',
    )
    args = parser.parse_args(argv)
    if not (50 <= args.tick <= 2000):
        parser.error('--tick 取值必须在 50-2000 毫秒之间，当前值: %d' % args.tick)
    return args


# ---------------------------------------------------------------------------
# 非 TTY 检查（FR-02，方案 §5.2）
# ---------------------------------------------------------------------------
def check_terminal():
    """检查终端运行环境（FR-02 / NFR-04）。

    - stdin/stdout 任一非 TTY：输出明确提示并以退出码 1 结束；
    - TERM 环境变量缺失（如 cron/CI/清空环境）：curses 无法初始化，
      属可预见失败，输出可读错误而非裸 traceback。
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        _write_stderr('错误：本游戏必须在终端（TTY）中运行，请直接执行: python3 tetris.py\n')
        sys.exit(EXIT_NOT_TTY)
    if not os.environ.get('TERM'):
        _write_stderr('错误：未检测到 TERM 环境变量（curses 无法初始化）。'
                      '请在终端中运行，或先 export TERM=xterm-256color\n')
        sys.exit(EXIT_NOT_TTY)


# ---------------------------------------------------------------------------
# 方块旋转（FR-09，方案 §5.1）
# ---------------------------------------------------------------------------
def rotate_cw(matrix):
    """顺时针旋转 90°：matrix 每行逆序后按列取（方案 §4.2 公式）。

    对 4×4 矩阵旋转 4 次后回到原矩阵；O 方块（2×2 田字）旋转后不变。
    """
    return [list(row) for row in zip(*matrix[::-1])]


# ---------------------------------------------------------------------------
# 模型层：碰撞检测与消行（方案 §5.1 核心算法，纯逻辑不依赖 curses）
# ---------------------------------------------------------------------------
def collides(gs, shape, pos):
    """检测 shape 置于 pos 处是否与场地边界或已锁定方块重叠。

    - 越界（x<0 / x>=cols / y>=rows）视为碰撞；
    - y < 0（生成区上方，未进入场地）视为可通行，且不访问 board（防 IndexError）；
    - 与锁定格（board 非 0）重叠视为碰撞。
    """
    for y, row in enumerate(shape):
        for x, val in enumerate(row):
            if not val:
                continue
            wx, wy = pos.x + x, pos.y + y
            if wx < 0 or wx >= gs.cols or wy >= gs.rows:
                return True
            if wy >= 0 and gs.board[wy][wx]:
                return True
    return False


def clear_lines(gs):
    """消除所有被完全填满的行，上方方块整体下移一行（FR-14）。

    返回消除行数（0/1/2/3/4）。多行同消时全部消除。
    实现要点：先逆序删除满行，再统一在顶部补空行——保证上方行整体下移
    （方案 §5.1 片段的正确性落实：满行列表须从下往上删，否则行号会错位）。
    """
    full = [y for y in range(gs.rows) if all(gs.board[y])]
    for y in reversed(full):
        del gs.board[y]
    for _ in full:
        gs.board.insert(0, [0] * gs.cols)
    return len(full)


# ---------------------------------------------------------------------------
# 模型层：游戏状态（FR-06~FR-16，方案 §4.2 / §4.3）
# ---------------------------------------------------------------------------
class GameState(object):
    """游戏逻辑模型。纯 Python 数据结构，不依赖 curses（方案 §2 选型结论）。

    字段（对齐方案 §4.2）：
        cols/rows: int                 场地尺寸（10×20）
        board: List[List[int]]         锁定格；0=空，1..7=锁定方块类型（TYPES 索引+1）
        piece_type: str                活动方块类型（I/O/T/S/Z/J/L）
        rotation: int                  0~3 旋转次数
        pos: Point                     活动方块锚点（形状矩阵左上角对应场地坐标）
        next_type: str                 next 预览方块（FR-21）
        score/lines: int               得分/累计消行数
        status: str                    'RUNNING' | 'PAUSED' | 'OVER'
    派生属性：
        level: int                     lines // 10 + 1（FR-16，Q-04）
        tick_ms: int                   max(100, base * 0.9 ** (level-1))（FR-16，Q-04）
    """

    def __init__(self, cols=COLS, rows=ROWS, base_tick_ms=DEFAULT_TICK_MS,
                 first_type=None):
        self.cols = cols
        self.rows = rows
        self.base_tick_ms = base_tick_ms          # 用户配置的初始下落间隔（FR-03）
        self.board = [[0] * cols for _ in range(rows)]
        self.score = 0
        self.lines = 0
        self.status = 'RUNNING'
        self.next_type = random.choice(TYPES)
        # 首个活动方块：支持测试注入 first_type（默认纯随机，Q-03）
        self._spawn(first_type if first_type is not None else random.choice(TYPES))
        self.next_type = random.choice(TYPES)     # 首个方块生成后刷新 next

    # ---- 派生属性（FR-16，Q-04 默认曲线） ----
    @property
    def level(self):
        return self.lines // LINES_PER_LEVEL + 1

    @property
    def tick_ms(self):
        return max(MIN_TICK_MS, int(self.base_tick_ms * (TICK_FACTOR ** (self.level - 1))))

    # ---- 形状 ----
    def shape(self):
        """返回活动方块按当前 rotation 旋转后的形状矩阵。"""
        m = TETROMINOES[self.piece_type]
        for _ in range(self.rotation % 4):
            m = rotate_cw(m)
        return m

    # ---- 生成（FR-06/FR-12/FR-13） ----
    def _spawn(self, piece_type):
        """在场地顶部中央生成新方块；生成位置被占用 → 撞顶结束（FR-13）。"""
        self.piece_type = piece_type
        self.rotation = 0
        self.pos = Point((self.cols - 4) // 2, 0)
        if collides(self, self.shape(), self.pos):
            self.status = 'OVER'                  # 撞顶（FR-13）

    # ---- 自动下落（FR-07） ----
    def step(self):
        """tick 推进一格；无法下落则锁定并生成新方块（FR-12）。"""
        if self.status != 'RUNNING':
            return
        below = Point(self.pos.x, self.pos.y + 1)
        if not collides(self, self.shape(), below):
            self.pos = below
        else:
            self._lock_and_spawn()

    # ---- 左右移（FR-08） ----
    def move(self, dx):
        """水平移动 dx（-1/1）。被边界/堆叠阻挡时拒绝，返回是否移动成功。"""
        if self.status != 'RUNNING':
            return False
        new_pos = Point(self.pos.x + dx, self.pos.y)
        if collides(self, self.shape(), new_pos):
            return False
        self.pos = new_pos
        return True

    # ---- 旋转（FR-09，Q-02 简化旋转：碰撞即拒绝，无 wall kick） ----
    def rotate(self):
        """顺时针旋转 90°；旋转后与边界/堆叠重叠则拒绝并保持原姿态。"""
        if self.status != 'RUNNING':
            return False
        new_rotation = (self.rotation + 1) % 4
        old_rotation = self.rotation
        self.rotation = new_rotation
        if collides(self, self.shape(), self.pos):
            self.rotation = old_rotation
            return False
        return True

    # ---- 软降（FR-10，Q-01 默认不加分；事件式下移，松开即恢复自动下落） ----
    def soft_drop(self):
        """立即下移一格；触底/碰撞时拒绝且不消失（锁定由下一个自动 tick 完成）。"""
        if self.status != 'RUNNING':
            return False
        below = Point(self.pos.x, self.pos.y + 1)
        if collides(self, self.shape(), below):
            return False
        self.pos = below
        return True

    # ---- 硬降（FR-11，Q-01 默认不加分） ----
    def hard_drop(self):
        """方块瞬间下落到底并锁定（纯计算，耗时 < 100ms），随即进入消行判定。"""
        if self.status != 'RUNNING':
            return
        while not collides(self, self.shape(), Point(self.pos.x, self.pos.y + 1)):
            self.pos = Point(self.pos.x, self.pos.y + 1)
        self._lock_and_spawn()

    # ---- 锁定 / 消行 / 计分 / 生成 next（FR-12/FR-14/FR-15/FR-16/FR-21） ----
    def _lock_and_spawn(self):
        """把活动方块写入 board，消行计分，然后生成 next 方块。"""
        shape = self.shape()
        for y, row in enumerate(shape):
            for x, val in enumerate(row):
                if not val:
                    continue
                wx, wy = self.pos.x + x, self.pos.y + y
                if 0 <= wx < self.cols and 0 <= wy < self.rows:
                    self.board[wy][wx] = TYPES.index(self.piece_type) + 1
        cleared = clear_lines(self)               # FR-14
        self.score += SCORE_TABLE.get(cleared, 0)  # FR-15
        self.lines += cleared                      # FR-16（level 为派生属性自动更新）
        self._spawn(self.next_type)               # next 预告准确（FR-21）
        self.next_type = random.choice(TYPES)

    # ---- 暂停/继续（FR-19；tick 相位补偿由主循环处理，见 main()） ----
    def toggle_pause(self):
        """RUNNING ↔ PAUSED。返回切换后的状态，OVER 时返回 None。"""
        if self.status == 'RUNNING':
            self.status = 'PAUSED'
            return self.status
        elif self.status == 'PAUSED':
            self.status = 'RUNNING'
            return self.status
        return None


# ---------------------------------------------------------------------------
# 输入层：键位映射（FR-18~FR-20，方案 §3.2 InputHandler）
# ---------------------------------------------------------------------------
class InputHandler(object):
    """键位 → 动作映射。WASD 与方向键双方案（FR-18）。

    动作：ROTATE / LEFT / RIGHT / SOFT / HARD / PAUSE / QUIT / RESIZE
    """

    KEYMAP = {
        ord('w'): 'ROTATE', ord('W'): 'ROTATE', curses.KEY_UP: 'ROTATE',
        ord('a'): 'LEFT',   ord('A'): 'LEFT',   curses.KEY_LEFT: 'LEFT',
        ord('d'): 'RIGHT',  ord('D'): 'RIGHT',  curses.KEY_RIGHT: 'RIGHT',
        ord('s'): 'SOFT',   ord('S'): 'SOFT',   curses.KEY_DOWN: 'SOFT',
        ord(' '): 'HARD',
        ord('p'): 'PAUSE',  ord('P'): 'PAUSE',
        ord('q'): 'QUIT',   ord('Q'): 'QUIT',
    }

    @staticmethod
    def handle(ch):
        """把 curses.getch() 返回的键码映射为动作；无效键/无输入返回 None。"""
        if ch == curses.KEY_RESIZE:
            return 'RESIZE'
        return InputHandler.KEYMAP.get(ch)


# ---------------------------------------------------------------------------
# 渲染层：curses 封装（FR-21/22/24/26，方案 §3.2 Renderer）
# ---------------------------------------------------------------------------
class Renderer(object):
    """curses 渲染。全量重绘（每帧 erase 后重画，方案 §5.2 防残影）。

    界面布局（方案 §3.1）：
        左侧：10×20 场地边框（每格 2 字符宽，'[]'）
        右侧 x=24 起：NEXT 预览区 + SCORE/LEVEL/LINES HUD
    边框与方块全部使用 ASCII 字符（风险对策，方案 §6：兼容老旧终端）。
    """

    # 7 方块 → curses 基础色对编号（FR-26；has_colors 时启用）
    COLOR_PAIRS = {
        'I': 1, 'O': 2, 'T': 3, 'S': 4, 'Z': 5, 'J': 6, 'L': 7,
    }
    COLOR_ATTRS = {
        'I': curses.COLOR_CYAN, 'O': curses.COLOR_YELLOW, 'T': curses.COLOR_MAGENTA,
        'S': curses.COLOR_GREEN, 'Z': curses.COLOR_RED, 'J': curses.COLOR_BLUE,
        'L': curses.COLOR_WHITE,
    }

    # 场地边框相对窗口偏移：内容格 (gx,gy) → 屏幕 (gy+1, gx*2+1)
    BOARD_TOP = 1          # 场地内容首行（边框内）
    BOARD_LEFT = 1         # 场地内容首列（边框内，每格占 2 列）
    SIDEBAR_X = 24         # 侧栏起始列

    def __init__(self, stdscr, no_color=False):
        self.stdscr = stdscr
        self.no_color = no_color
        self.colors_on = False
        if not no_color and curses.has_colors():
            try:
                curses.start_color()
                for t, idx in self.COLOR_PAIRS.items():
                    curses.init_pair(idx, self.COLOR_ATTRS[t], curses.COLOR_BLACK)
                self.colors_on = True
            except curses.error:
                self.colors_on = False            # 异常时自动降级单色（方案 §6）

    def _attr(self, piece_type):
        """返回方块对应的 curses 属性（颜色开启时着色，否则 0=默认色）。"""
        if self.colors_on:
            return curses.color_pair(self.COLOR_PAIRS[piece_type])
        return 0

    @staticmethod
    def size_ok(stdscr):
        """检查终端尺寸是否满足最小可玩要求（FR-04，方案 §3.1：42×26）。"""
        h, w = stdscr.getmaxyx()
        return w >= MIN_COLS and h >= MIN_LINES

    def draw_size_error(self):
        """在过小终端中输出可读提示（FR-04，NFR-04）。"""
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()
        msg = 'Terminal too small: need at least %dx%d, got %dx%d. Please enlarge the window and retry.' % (
            MIN_COLS, MIN_LINES, w, h)
        try:
            self.stdscr.addstr(0, 0, msg)
        except curses.error:
            pass
        self.stdscr.refresh()

    def _put_cell(self, y, x, text, attr=0):
        """安全地在屏幕 (y,x) 写文本，越界静默忽略（防 resize 竞态崩溃）。"""
        try:
            self.stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def _draw_piece_matrix(self, top, left, piece_type, matrix):
        """在屏幕 (top,left) 起绘制形状矩阵（按 bounding box 紧缩）。"""
        rows_used = [i for i, row in enumerate(matrix) if any(row)]
        cols_used = [j for j in range(len(matrix[0]))
                     if any(matrix[i][j] for i in range(len(matrix)))]
        if not rows_used or not cols_used:
            return
        min_y, min_x = rows_used[0], cols_used[0]
        attr = self._attr(piece_type)
        for i in rows_used:
            for j in cols_used:
                if matrix[i][j]:
                    self._put_cell(top + i - min_y, left + (j - min_x) * 2, '[]', attr)

    def draw(self, state):
        """全量重绘当前游戏画面（场地/活动方块/next/HUD/PAUSED/结束画面）。"""
        scr = self.stdscr
        scr.erase()

        # 场地边框（纯 ASCII，方案 §6 风险对策：兼容老旧终端/SSH，不用 ACS 线框）
        border_w = state.cols * 2 + 2          # 10 格 × 2 字符 + 左右边框
        border_h = state.rows + 2              # 20 行 + 上下边框
        self._put_cell(0, 0, '+' + '-' * (border_w - 2) + '+')
        for i in range(1, border_h - 1):
            self._put_cell(i, 0, '|')
            self._put_cell(i, border_w - 1, '|')
        self._put_cell(border_h - 1, 0, '+' + '-' * (border_w - 2) + '+')

        # 场地内容：先清空，再画锁定格与活动方块
        for gy in range(state.rows):
            for gx in range(state.cols):
                self._put_cell(self.BOARD_TOP + gy, self.BOARD_LEFT + gx * 2, '  ')
        for gy in range(state.rows):
            for gx in range(state.cols):
                val = state.board[gy][gx]
                if val:
                    piece_type = TYPES[val - 1]
                    self._put_cell(self.BOARD_TOP + gy, self.BOARD_LEFT + gx * 2,
                                   '[]', self._attr(piece_type))
        if state.status != 'OVER':
            self._draw_piece_matrix(self.BOARD_TOP + state.pos.y,
                                    self.BOARD_LEFT + state.pos.x,
                                    state.piece_type, state.shape())

        # 侧栏：next 预览（FR-21）
        sx = self.SIDEBAR_X
        self._put_cell(0, sx, 'NEXT:')
        self._draw_piece_matrix(1, sx, state.next_type, TETROMINOES[state.next_type])

        # 侧栏：HUD 得分/等级/消行（FR-22）
        self._put_cell(7, sx, 'SCORE')
        self._put_cell(8, sx, str(state.score))
        self._put_cell(10, sx, 'LEVEL')
        self._put_cell(11, sx, str(state.level))
        self._put_cell(13, sx, 'LINES')
        self._put_cell(14, sx, str(state.lines))

        # 暂停提示（FR-19）
        if state.status == 'PAUSED':
            self._put_cell(16, sx, 'PAUSED', curses.A_BOLD)

        # 结束画面（FR-24）
        if state.status == 'OVER':
            self._put_cell(state.rows // 2 + self.BOARD_TOP - 1,
                           self.BOARD_LEFT + 3, 'GAME OVER', curses.A_BOLD)
            self._put_cell(state.rows // 2 + self.BOARD_TOP + 1,
                           self.BOARD_LEFT + 2, 'Score: %d' % state.score)
            self._put_cell(state.rows // 2 + self.BOARD_TOP + 3,
                           self.BOARD_LEFT + 1, 'Press any key to exit')

        scr.refresh()


# ---------------------------------------------------------------------------
# SIGTERM 处理（方案 §5.2：与 Ctrl+C 走同一恢复路径，防 systemd/kill 场景残留）
# ---------------------------------------------------------------------------
def _sigterm_handler(signum, frame):
    raise KeyboardInterrupt


# ---------------------------------------------------------------------------
# 主循环（FR-04/07/19/20，方案 §3.3 时序）
# ---------------------------------------------------------------------------
def main(stdscr, args):
    """curses 主函数（由 wrapper 调用）。返回进程退出码。"""
    curses.curs_set(0)          # 隐藏光标
    stdscr.nodelay(True)        # getch 非阻塞（配合 timeout 轮询）
    stdscr.keypad(True)         # 方向键转义序列 → KEY_*（方案 §2 选型理由③）
    stdscr.timeout(25)          # 每 25ms 轮询一次（输入响应 ≤ 1 tick，NFR-01）

    renderer = Renderer(stdscr, no_color=args.no_color)

    # 启动尺寸检查（FR-04）
    if not Renderer.size_ok(stdscr):
        renderer.draw_size_error()
        time.sleep(2)
        return EXIT_TOO_SMALL

    state = GameState(base_tick_ms=args.tick)
    last_tick = time.monotonic()
    paused_at = None            # 暂停时刻（相位补偿用，FR-19）
    size_ok = True

    while True:
        ch = stdscr.getch()
        action = InputHandler.handle(ch) if ch != -1 else None

        # 退出（FR-20）：q / Ctrl+C（KeyboardInterrupt 冒泡）/ SIGTERM（同路径）
        if action == 'QUIT':
            break

        # 终端 resize（FR-04）：重查尺寸，不足则暂停显示提示
        if action == 'RESIZE':
            try:
                curses.resizeterm(*stdscr.getmaxyx())
            except curses.error:
                pass
            size_ok = Renderer.size_ok(stdscr)
            if not size_ok:
                renderer.draw_size_error()
            continue

        # 结束画面（FR-24）：任意键退出
        if state.status == 'OVER':
            renderer.draw(state)
            if ch != -1:
                break
            continue

        # 暂停切换（FR-19）：恢复时补偿 tick 相位，暂停期间不吞时间、恢复无跳变
        if action == 'PAUSE':
            now = time.monotonic()
            if state.status == 'PAUSED':
                if paused_at is not None:
                    last_tick += now - paused_at
                paused_at = None
            else:
                paused_at = now
            state.toggle_pause()
            continue

        # 尺寸不足：冻结画面并提示，等待 resize 恢复（FR-04）
        if not size_ok:
            renderer.draw_size_error()
            continue

        # 输入动作（仅 RUNNING 状态生效；无效键忽略）
        if state.status == 'RUNNING':
            if action == 'ROTATE':
                state.rotate()
            elif action == 'LEFT':
                state.move(-1)
            elif action == 'RIGHT':
                state.move(1)
            elif action == 'SOFT':
                state.soft_drop()
            elif action == 'HARD':
                state.hard_drop()

        # tick 推进（FR-07）：按当前等级间隔自动下落
        now = time.monotonic()
        if state.status == 'RUNNING' and (now - last_tick) >= state.tick_ms / 1000.0:
            state.step()
            last_tick = now

        renderer.draw(state)

    return EXIT_OK


# ---------------------------------------------------------------------------
# 入口：check_terminal → 信号处理 → wrapper（终端状态保存/恢复）
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    args = parse_args()
    check_terminal()
    signal.signal(signal.SIGTERM, _sigterm_handler)   # 方案 §5.2 增强项
    try:
        # wrapper 负责保存/恢复终端原始状态（noecho/cbreak/光标/颜色），
        # 正常返回与异常（含 KeyboardInterrupt）均恢复 —— FR-23/NFR-03
        exit_code = curses.wrapper(main, args)
    except KeyboardInterrupt:
        _write_stderr('\n游戏已退出（Ctrl+C）\n')
        exit_code = EXIT_INTERRUPTED
    except curses.error as exc:
        # 启动失败兜底（如 TERM 无效/终端能力异常）：可读错误而非裸 traceback（NFR-04）
        _write_stderr('错误：终端初始化失败（%s）。请在支持的终端（GNOME Terminal/Konsole/xterm/SSH）中运行\n'
                      % exc)
        exit_code = EXIT_NOT_TTY
    sys.exit(exit_code)
