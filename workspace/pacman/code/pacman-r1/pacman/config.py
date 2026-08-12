"""游戏配置常量与默认值。

职责：集中存放所有可调参数（Q1~Q12 落定值、难度公式、计分常量、键位）。
依赖：仅标准库（dataclass、enum）。
对应方案：plans/pacman-r1.md §4.2 数据结构、§5.4 难度公式、Q1~Q12 落定见 §8。

本文件为 round 5 / code r1 阶段产物（2026-08-11 启动）。
本轮为 2026-08-10 16:20 人工 requeue 后重跑的第 1 轮 code（按 analysis r5 + plan r1 + testplan r1 全新一轮）；
本轮直接吸收 r2（PASS）修复（玩家通行校验）并继承 r1 清理（SCATTER_CHASE_SCHEDULE 死代码删除）；
行为完整不变。
"""


from dataclasses import dataclass
from enum import Enum


# ============================================================================
# 方向（Dir）与优先级（方案 §5.1 choose_dir 平局规则）
# ============================================================================
class Dir(Enum):
    """四方向枚举。约定 (drow, dcol)：drow 影响 row（行），dcol 影响 col（列）。

    地图坐标：row 向下增大，col 向右增大。
      UP    = row -1（向上）
      DOWN  = row +1（向下）
      LEFT  = col -1（向左）
      RIGHT = col +1（向右）
    """
    UP = (-1, 0)
    LEFT = (0, -1)
    DOWN = (1, 0)
    RIGHT = (0, 1)

    @property
    def drow(self) -> int:
        return self.value[0]

    @property
    def dcol(self) -> int:
        return self.value[1]


# 平局优先级：Dossier 原版规则，UP > LEFT > DOWN > RIGHT
DIR_PRIORITY = {Dir.UP: 4, Dir.LEFT: 3, Dir.DOWN: 2, Dir.RIGHT: 1}

# 反向映射
REVERSE_DIR = {
    Dir.UP: Dir.DOWN,
    Dir.DOWN: Dir.UP,
    Dir.LEFT: Dir.RIGHT,
    Dir.RIGHT: Dir.LEFT,
}

ALL_DIRS = (Dir.UP, Dir.LEFT, Dir.DOWN, Dir.RIGHT)


# ============================================================================
# 幽灵类型（Kind）与模式（Mode）（方案 §3.2 ghost_ai + §4.2 Ghost）
# ============================================================================
class Kind(Enum):
    BLINKY = "blinky"  # 红色，直线追击（含 Elroy）
    PINKY = "pinky"    # 粉色，前方 4 格预判（含原版 up-bug）
    INKY = "inky"      # 青色，向量翻倍协同
    CLYDE = "clyde"    # 橙色，距离感知（<8 格撤退）


class Mode(Enum):
    """幽灵模式状态机。"""
    SCATTER = "scatter"      # 散开（回各自角落）
    CHASE = "chase"          # 追击
    FRIGHTENED = "frightened"  # 脆弱（被吃豆反击）
    EYES = "eyes"            # 眼睛（被吃后返鬼屋）


# ============================================================================
# 计分常量（A2/Q4，原版分值）
# ============================================================================
DOT_SCORE = 10
POWER_SCORE = 50
# 连吃幽灵得分序列（eaten_chain 索引 0..3；>=4 时封顶 1600）
GHOST_CHAIN_SCORES = (200, 400, 800, 1600)


# ============================================================================
# 速度常量（方案 §5.2 Mover，单位：格/tick）
# ============================================================================
PLAYER_SPEED = 1.0
GHOST_BASE_SPEED = 0.9
GHOST_ELROY_SPEED = 1.0        # 追平玩家
GHOST_FRIGHTENED_SPEED = 0.75
GHOST_EYES_SPEED = 1.5


# ============================================================================
# 难度公式（方案 §5.4）
# ============================================================================
def ghost_speed_for_level(level: int) -> float:
    """幽灵基础速度：0.9 + 0.02×(L-1)，上限 0.98，玩家恒 1.0。"""
    return min(0.9 + 0.02 * (level - 1), 0.98)


def power_duration_for_level(level: int) -> float:
    """能量豆时长：max(6.0 - 0.5×(L-1), 1.0) 秒。"""
    return max(6.0 - 0.5 * (level - 1), 1.0)


def scatter_duration_for_level(level: int) -> float:
    """SCATTER 时长：max(7 - (L-1)×2, 1) 秒。"""
    return max(7 - (level - 1) * 2, 1)


def chase_duration_for_level(level: int) -> float:
    """CHASE 时长：固定 20 秒。"""
    return 20.0


def elroy_threshold_for_level(level: int) -> int:
    """Elroy 触发残豆阈值：max(20 - 3×(L-1), 5)。"""
    return max(20 - 3 * (level - 1), 5)


def inky_release_dots_for_level(level: int) -> int:
    """Inky 出场豆数：max(30 - 5×(L-1), 10)。"""
    return max(30 - 5 * (level - 1), 10)


def clyde_release_dots_for_level(level: int) -> int:
    """Clyde 出场豆数：max(60 - 10×(L-1), 20)。"""
    return max(60 - 10 * (level - 1), 20)


# 散开角落（Dossier 规则）
HOME_CORNERS = {
    Kind.BLINKY: (0, 18),    # 右上
    Kind.PINKY: (0, 1),      # 左上
    Kind.INKY: (18, 18),     # 右下
    Kind.CLYDE: (18, 1),     # 左下
}


# ============================================================================
# 计时常量
# ============================================================================
TICK_MS = 100                  # 主循环 tick（10 FPS）

# 模式交替表（方案 §5.4）：phase 0~6 交替 S/C，第 7 段固定 CHASE 不切换
# 实际由 ModeController.phase + PHASE_COUNT 控制：
#   phase % 2 == 0 → SCATTER 散开（时长 = scatter_duration_for_level）
#   phase % 2 == 1 → CHASE 追击（时长 = chase_duration_for_level）
#   phase >= 2 * PHASE_COUNT → 永久 CHASE
PHASE_COUNT = 7  # 0~3 S, 4~6 C, 7 起 CHASE


# ============================================================================
# 保护期
# ============================================================================
PROTECTION_SECONDS = 2.0  # 扣命后 2 秒保护期


# ============================================================================
# 终端尺寸（NFR-04 / FR-14 验收口径）
# ============================================================================
MIN_COLS = 80
MIN_LINES = 24


# ============================================================================
# 幽灵 Clyde 距离感知阈值
# ============================================================================
CLYDE_SHY_DISTANCE = 8  # 距离 < 8 格时撤退


# ============================================================================
# CLI 默认值（方案 §4.1）
# ============================================================================
DEFAULT_LIVES = 3
DEFAULT_GHOSTS = 4
DEFAULT_LEVEL = 1
DEFAULT_SPEED = 1.0
DEFAULT_MAP = "data/map_classic.txt"


# ============================================================================
# Config 数据类（argparse 覆盖用）
# ============================================================================
@dataclass
class Config:
    """运行时配置（CLI 覆盖默认值后冻结）。"""
    map_path: str = DEFAULT_MAP
    ghosts: int = DEFAULT_GHOSTS       # 2/3/4
    lives: int = DEFAULT_LIVES         # 1..9
    level: int = DEFAULT_LEVEL         # >=1
    speed: float = DEFAULT_SPEED       # 0.5..2.0（全局倍率）
    no_color: bool = False
    log_ai: bool = False
