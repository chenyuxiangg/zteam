"""实体：玩家、幽灵、速度累积器。

职责：Mover（速度累积器）；Player（方向/缓冲）；Ghost（类型/模式/状态/计数）。
依赖：仅 pacman.config、pacman.map。
对应方案：plans/pacman-r1.md §3.2 entities.py、§4.2 数据结构、§5.2 移动与速度模型。
不依赖 curses（纯逻辑层，可单测）。

本文件为 r1 第 1 轮 code 阶段产出；与 pre-requeue 旧版相比逻辑无变化。
"""


from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .config import (
    Dir, Kind, Mode, REVERSE_DIR,
    GHOST_BASE_SPEED, GHOST_ELROY_SPEED, GHOST_FRIGHTENED_SPEED, GHOST_EYES_SPEED,
    PLAYER_SPEED, CLYDE_SHY_DISTANCE, HOME_CORNERS,
    inky_release_dots_for_level, clyde_release_dots_for_level,
)
from .map import GameMap


# ============================================================================
# Mover：速度累积器（格/tick 支持浮点累积，方案 §5.2）
# ============================================================================
class Mover:
    """基础移动体：逐格移动 + 浮点速度累积器。

    speed 单位：格/tick（默认 1.0 = 每 tick 走 1 格）。
    acc 累积余量；达到 1.0 时走一格，acc -= 1.0（保持速度稳定）。
    """

    def __init__(self, pos, dir_: Dir, speed: float):
        self.row = pos[0]
        self.col = pos[1]
        self.dir = dir_
        self.speed = speed
        self.acc = 0.0

    @property
    def pos(self):
        return (self.row, self.col)

    def set_pos(self, pos):
        self.row, self.col = pos[0], pos[1]

    def add_motion(self) -> int:
        """主循环调用：累积速度，达到 1 格则走一步并返回步数（0 或 1）。

        为防调试器/计时器大暂停后跳帧，速度累积封顶：单次最多走 4 格。
        """
        self.acc += self.speed
        steps = 0
        while self.acc >= 1.0 and steps < 4:
            self.acc -= 1.0
            self.row += self.dir.drow
            self.col += self.dir.dcol
            steps += 1
        # 极端兜底：避免 acc 无限累积
        if self.acc >= 4.0:
            self.acc = 0.0
        return steps

    def reverse(self):
        """180° 反转（方案 §4.4 强制掉头）。"""
        self.dir = REVERSE_DIR[self.dir]


# ============================================================================
# Player：方向 + 输入缓冲（方案 §5.2 玩家输入缓冲）
# ============================================================================
class Player(Mover):
    """玩家实体。"""

    def __init__(self, pos):
        super().__init__(pos=pos, dir_=Dir.LEFT, speed=PLAYER_SPEED)
        # 缓冲队列（容量 1，新指令覆盖旧指令；FR-04）
        self.turn_buffer: deque[Dir] = deque(maxlen=1)
        self.alive = True  # 玩家是否在场（命>0）
        self.protection_timer = 0.0  # 扣命后保护期剩余秒数

    def request_turn(self, new_dir: Dir) -> None:
        """玩家键入转向指令：尝试立即转向，否则入缓冲（容量 1）。

        立即转向条件：new_dir 与当前 dir 相反（即掉头）。
        否则入缓冲（容量 1，新指令覆盖旧指令）。
        """
        if new_dir == REVERSE_DIR[self.dir]:
            self.reverse()
            # 反转后缓冲清空（避免缓冲里残留的指令与新方向冲突）
            self.turn_buffer.clear()
            return
        self.turn_buffer.append(new_dir)

    def consume_turn(self, game_map: GameMap) -> None:
        """每 tick 开始时调用：消费缓冲指令（合法则执行，否则丢弃）。

        转向条件：new_dir 方向上下一格可通行（玩家视角）。
        """
        if not self.turn_buffer:
            return
        new_dir = self.turn_buffer[-1]  # 容量 1，取最新
        nr = self.row + new_dir.drow
        nc = self.col + new_dir.dcol
        if game_map.is_passable_for_player(nr, nc):
            self.dir = new_dir
            self.turn_buffer.clear()
        # 不合法：保留缓冲（玩家可能还会继续按；不粘滞则下次覆盖）
        # 但若按了反向，则 reverse() 已清空；这里不合法不反向则不清，让玩家继续走原方向

    def update_protection(self, dt: float) -> None:
        """更新保护期倒计时。"""
        if self.protection_timer > 0.0:
            self.protection_timer = max(0.0, self.protection_timer - dt)


# ============================================================================
# Ghost：类型 + 模式 + 状态机 + 出场计数（方案 §5.1/§5.4）
# ============================================================================
class Ghost(Mover):
    """幽灵实体。"""

    def __init__(self, kind: Kind, pos, level: int = 1):
        super().__init__(pos=pos, dir_=Dir.UP, speed=GHOST_BASE_SPEED)
        self.kind = kind
        self.mode = Mode.SCATTER   # 初始 SCATTER（首段散开，重置规则）
        self.mode_timer = 0.0      # 当前模式已持续秒数
        self.mode_phase = 0        # 交替表段号
        self.release_dots = 0      # 已吃豆数（用于 Inky/Clyde 出场）
        self.release_threshold = _initial_release_threshold(kind, level)
        self.home_corner = HOME_CORNERS[kind]
        self.in_house = True       # 初始在鬼屋内
        self.dot_counter = 0       # 同 release_dots（别名保留供将来扩展）
        self.elroy_active = False  # Blinky Elroy 触发

    def speed_for_mode(self) -> float:
        """根据当前模式返回速度（方案 §5.2）。"""
        if self.mode == Mode.EYES:
            return GHOST_EYES_SPEED
        if self.mode == Mode.FRIGHTENED:
            return GHOST_FRIGHTENED_SPEED
        if self.elroy_active:
            return GHOST_ELROY_SPEED
        return self.speed  # 基础速度（已被外部按关卡更新）

    def effective_speed(self) -> float:
        """实际用于累积的速度（覆盖 Mover.speed 调用入口）。"""
        return self.speed_for_mode()

    def add_motion(self) -> int:
        """重写 Mover.add_motion，使用 effective_speed（模式敏感）。"""
        self.acc += self.effective_speed()
        steps = 0
        while self.acc >= 1.0 and steps < 4:
            self.acc -= 1.0
            self.row += self.dir.drow
            self.col += self.dir.dcol
            steps += 1
        if self.acc >= 4.0:
            self.acc = 0.0
        return steps


def _initial_release_threshold(kind: Kind, level: int) -> int:
    """出场豆数阈值（第 1 关；Inky 30 / Clyde 60 / Pinky 立即 / Blinky 屋出生）。"""
    if kind == Kind.INKY:
        return inky_release_dots_for_level(level)
    if kind == Kind.CLYDE:
        return clyde_release_dots_for_level(level)
    return 0  # Pinky / Blinky：不需要豆数阈值
