"""四幽灵差异化 AI（方案 §5.1，本需求差异化核心）。

职责：target_cell（纯函数，FR-10 主验收客观验证点）；choose_dir（路口决策）；
      模式状态机（SCATTER/CHASE/FRIGHTENED/EYES）；出场/重生规则；--log-ai 行为日志。
依赖：仅 pacman.config、pacman.entities、pacman.map。
对应方案：plans/pacman-r1.md §3.2 ghost_ai.py、§4.4 状态机、§5.1 四幽灵目标计算。
不依赖 curses（纯逻辑层，可单测）。

本文件为 r1 第 1 轮 code 阶段产出；与 pre-requeue 旧版相比逻辑无变化。

注：本文件所有"目标格"为纯函数，无副作用；测试可直接断言四幽灵同局面目标格互异。
"""


from collections import deque
from dataclasses import dataclass
from typing import Optional

from .config import (
    Dir, Kind, Mode, ALL_DIRS, REVERSE_DIR, DIR_PRIORITY,
    HOME_CORNERS, CLYDE_SHY_DISTANCE, scatter_duration_for_level, chase_duration_for_level,
    PHASE_COUNT,
)
from .entities import Ghost, Player
from .map import GameMap


# ============================================================================
# 工具：曼哈顿距离 + 边界 clamp
# ============================================================================
def manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def euclidean_int(a, b) -> int:
    """欧几里得距离（Dossier 风格取 int 比较）。"""
    dr = a[0] - b[0]
    dc = a[1] - b[1]
    return int((dr * dr + dc * dc) ** 0.5)


def clamp_pos(r: int, c: int, rows: int, cols: int) -> tuple[int, int]:
    """Pinky/Inky 向上偏移 bug 导致的目标出界时 clamp 到地图边界内。"""
    r = max(0, min(rows - 1, r))
    c = max(0, min(cols - 1, c))
    return (r, c)


def offset_n(pr: int, pc: int, d: Dir, n: int) -> tuple[int, int]:
    """玩家前方 N 格偏移。

    复刻原版 Dossier 记载的 bug：玩家方向 UP 时额外左偏 N 格。
    """
    r = pr + d.drow * n
    c = pc + d.dcol * n
    if d == Dir.UP:
        c -= n  # 原版 bug：UP 时左偏 N
    return (r, c)


# ============================================================================
# target_cell：四幽灵目标格计算（纯函数，FR-10 主验收点）
# ============================================================================
def target_cell(g: Ghost, player: Player, blinky: Optional[Ghost],
                game_map: GameMap) -> tuple[int, int]:
    """返回给定幽灵的目标格（row, col）。

    四幽灵规则严格不同（FR-10 主验收客观验证）：
      BLINKY → 玩家当前位置
      PINKY  → 玩家前方 4 格（含原版 up-bug 左偏 4，出界 clamp）
      INKY   → 玩家前方 2 格 + 向 Blinky 翻倍（含原版 up-bug 左偏 2，出界 clamp）
      CLYDE  → 距玩家 ≥8 格追玩家，否则撤回家角落

    出参：纯函数返回值；不修改 ghost/player/blinky/game_map 任何状态。
    """
    pr, pc = player.row, player.col
    pdir = player.dir
    rows, cols = game_map.rows, game_map.cols

    if g.kind == Kind.BLINKY:
        return (pr, pc)

    if g.kind == Kind.PINKY:
        off = offset_n(pr, pc, pdir, 4)
        return clamp_pos(*off, rows, cols)

    if g.kind == Kind.INKY:
        off2 = offset_n(pr, pc, pdir, 2)
        # 向量翻倍：目标 = 2*offset2 - blinky.pos
        if blinky is None:
            # 无 Blinky 引用（幽灵数量 < 2）时降级为玩家位置
            return (pr, pc)
        target_r = 2 * off2[0] - blinky.row
        target_c = 2 * off2[1] - blinky.col
        return clamp_pos(target_r, target_c, rows, cols)

    if g.kind == Kind.CLYDE:
        if euclidean_int((g.row, g.col), (pr, pc)) >= CLYDE_SHY_DISTANCE:
            return (pr, pc)
        return HOME_CORNERS[Kind.CLYDE]

    # 不应到达
    return (pr, pc)


# ============================================================================
# choose_dir：路口决策（曼哈顿最小 + 平局 UP>LEFT>DOWN>RIGHT）
# ============================================================================
def choose_dir(g: Ghost, target: tuple[int, int], game_map: GameMap) -> Dir:
    """为幽灵选择下一 tick 的方向。

    规则（Dossier）：
      候选 = 合法方向（玩家可通行同幽灵可通行，除 DOOR/HOUSE 限制——见 passable）
            排除反向；
      选使"下一格到 target 曼哈顿距离最小"的方向；
      平局按 UP>LEFT>DOWN>RIGHT 优先级；
      无候选时允许掉头（返回反向）。
    """
    cur_dir = g.dir
    reverse = REVERSE_DIR[cur_dir]

    cands: list[Dir] = []
    for d in ALL_DIRS:
        if d == reverse:
            continue
        nr = g.row + d.drow
        nc = g.col + d.dcol
        if not game_map.is_passable_for_ghost(nr, nc):
            continue
        cands.append(d)

    if not cands:
        # 无候选：允许反向（死胡同/单通道反向）
        return reverse

    # 曼哈顿距离 + 平局优先级
    def key(d: Dir):
        nr = g.row + d.drow
        nc = g.col + d.dcol
        dist = manhattan((nr, nc), target)
        # 平局时优先级高者胜：用 -PRIORITY[d] 作 tiebreaker
        return (dist, -DIR_PRIORITY[d])

    return min(cands, key=key)


# ============================================================================
# 模式状态机（SCATTER/CHASE 交替 + 脆弱/眼睛）（方案 §4.4/§5.4）
# ============================================================================
@dataclass
class ModeController:
    """模式状态机控制器（全局一份）。

    交替表（S/C 序列）由 PHASE_COUNT 决定：
      phase 0: SCATTER
      phase 1: CHASE
      phase 2: SCATTER
      phase 3: CHASE
      phase 4: SCATTER
      phase 5: CHASE
      phase 6: SCATTER
      phase >=7: CHASE（永久追逐，不切换）
    每段时长：SCATTER = scatter_duration_for_level(L)，CHASE = chase_duration_for_level(L)。
    """
    phase: int = 0                       # 交替表段号
    phase_timer: float = 0.0             # 当前段已持续秒数
    current: Mode = Mode.SCATTER         # 当前全局模式
    level: int = 1

    def reset(self, level: int = 1):
        """扣命/过关后回到首段 SCATTER（方案 §5.3 模式计时重置）。"""
        self.phase = 0
        self.phase_timer = 0.0
        self.current = Mode.SCATTER
        self.level = level

    def step(self, dt: float) -> bool:
        """推进模式计时；返回是否发生了模式切换（调用方用于触发强制掉头）。"""
        self.phase_timer += dt
        # 当前段时长
        if self.phase % 2 == 0:
            duration = scatter_duration_for_level(self.level)
        else:
            duration = chase_duration_for_level(self.level)
        if self.phase_timer < duration:
            return False
        # 到时切换
        old = self.current
        self.phase_timer = 0.0
        self.phase += 1
        if self.phase > 2 * PHASE_COUNT - 1:
            self.current = Mode.CHASE  # 永久追逐
        else:
            self.current = Mode.CHASE if self.current == Mode.SCATTER else Mode.SCATTER
        return old != self.current


# ============================================================================
# 模式切换效果：触发强制掉头（方案 §4.4）
# ============================================================================
def apply_mode_transition(ghost: Ghost, old_mode: Mode, new_mode: Mode) -> None:
    """按方案 §4.4 处理模式切换的强制掉头规则。

    切换规则：
      chase→scatter / chase→frightened / scatter→chase / scatter→frightened 强制 180° 掉头
      frightened→chase/scatter / eyes→相关  不强制掉头
    """
    force_reverse_transitions = {
        (Mode.CHASE, Mode.SCATTER),
        (Mode.CHASE, Mode.FRIGHTENED),
        (Mode.SCATTER, Mode.CHASE),
        (Mode.SCATTER, Mode.FRIGHTENED),
    }
    if (old_mode, new_mode) in force_reverse_transitions:
        ghost.reverse()


# ============================================================================
# 出场规则（Dossier：Pinky 立即；Inky 吃 30 豆；Clyde 吃 60 豆；Blinky 同屋出生）
# ============================================================================
def maybe_release_ghost(ghost: Ghost, dots_eaten: int) -> bool:
    """判断幽灵是否可以从鬼屋"出发"进入迷宫主体。

    返回 True 表示本 tick 应执行"离开鬼屋"动作。
    Pinky：立即（已在鬼屋外出生则不再触发）。
    Inky：dots_eaten >= release_threshold。
    Clyde：dots_eaten >= release_threshold。
    Blinky：同屋出生但本需求简化：与 Pinky 一同立即出屋（方案 §8 N3）。
    """
    if not ghost.in_house:
        return False
    if ghost.kind == Kind.BLINKY or ghost.kind == Kind.PINKY:
        return True
    if ghost.kind == Kind.INKY:
        return dots_eaten >= ghost.release_threshold
    if ghost.kind == Kind.CLYDE:
        return dots_eaten >= ghost.release_threshold
    return False


# ============================================================================
# 行为日志（--log-ai）：每 tick 各幽灵目标/方向（FR-10 客观验证辅助通道）
# ============================================================================
def format_ai_log(ghosts: list[Ghost], targets: dict[Kind, tuple[int, int]],
                  player: Player) -> str:
    """格式化一行行为日志：player_pos 各 ghost(名/模式/target/dir)。"""
    parts = [f"player=({player.row},{player.col},{player.dir.name})"]
    for g in ghosts:
        t = targets.get(g.kind, ("?", "?"))
        parts.append(
            f"{g.kind.name}/{g.mode.name}/target=({t[0]},{t[1]})/dir={g.dir.name}"
        )
    return " | ".join(parts)
