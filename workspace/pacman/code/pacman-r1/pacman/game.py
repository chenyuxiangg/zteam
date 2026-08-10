"""对局状态机：吃豆/能量豆/碰撞/过关/扣命/结算/难度参数。

职责：Game 类持有 GameState，推进游戏循环；处理所有规则表；
      提供 clock 注入点（test 计时用例 T-GAME-05/13/17/18 自动化）。
依赖：pacman.config / pacman.entities / pacman.ghost_ai / pacman.map。
对应方案：plans/pacman-r1.md §3.2 game.py、§3.3 主循环时序、§5.3 边界处理、§5.4 难度公式。
不依赖 curses（纯逻辑层，可单测）。

本文件为 r1 第 1 轮 code 阶段产出；与 pre-requeue 旧版相比逻辑无变化。
"""


from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .config import (
    Dir, Kind, Mode,
    DOT_SCORE, POWER_SCORE, GHOST_CHAIN_SCORES,
    PROTECTION_SECONDS,
    HOME_CORNERS, PLAYER_SPEED,
    ghost_speed_for_level, power_duration_for_level,
    elroy_threshold_for_level,
)
from .entities import Ghost, Player
from .ghost_ai import (
    ModeController, target_cell, choose_dir, maybe_release_ghost,
    apply_mode_transition,
)
from .map import GameMap, Tile


# ============================================================================
# 对局状态枚举
# ============================================================================
class Status(Enum):
    """对局顶层状态（方案 §4.4）。"""
    PLAYING = "playing"
    PAUSED = "paused"
    LEVEL_CLEAR = "level_clear"
    GAME_OVER = "game_over"


# ============================================================================
# 结算数据
# ============================================================================
@dataclass
class FinalScore:
    """结算画面信息。"""
    score: int
    level: int
    ghosts_eaten: int


# ============================================================================
# Clock 注入（test 计时用例可替换 time.monotonic）
# ============================================================================
Clock = Callable[[], float]


def _real_clock() -> float:
    import time
    return time.monotonic()


# ============================================================================
# Game 状态机
# ============================================================================
class Game:
    """游戏对局状态机。

    持有 GameState（level/lives/score/dots_left/power_timer/mode 等），
    推进 tick（dt 由调用方提供，便于测试注入）。
    """

    def __init__(self, game_map: GameMap, config, clock: Optional[Clock] = None):
        self.gm = game_map
        self.config = config
        self._clock = clock or _real_clock

        # 实体
        self.player = Player(game_map.player_spawn)
        self.ghosts: list[Ghost] = []
        self._init_ghosts()

        # 状态
        self.status = Status.PLAYING
        self.level = config.level
        self.lives = config.lives
        self.score = 0
        self.dots_left = game_map.initial_dots
        self.power_timer = 0.0
        self.eaten_chain = 0
        self.ghosts_eaten_total = 0

        # 模式控制器（全局一份；每只幽灵 mode 与全局同步 + 自身状态）
        self.mode_ctrl = ModeController(level=self.level)
        self.mode_ctrl.reset(self.level)

        # 豆子状态：保存一份 tiles 的"剩余豆"视图（吃豆会清掉）
        self.tiles = game_map.fresh_tiles()

        # Elroy 状态：Blinky 在残豆 ≤ 阈值时进入 Elroy 速度 1.0
        self._init_elroy()

        # 暂停相位补偿
        self._pause_accum = 0.0  # 累计暂停时长（用于扣除）

        # 关卡开始时间（用于暂停相位扣除）
        self._tick_phase_start = self._clock()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _init_ghosts(self):
        """按 config.ghosts 创建幽灵（保留 Blinky + Pinky/Inky/Clyde 前 N-1 只）。"""
        # 出生点：鬼屋内某一格（按 kind 顺序分配）
        spawn = sorted(self.gm.house_cells)
        if not spawn:
            # 极端：地图无鬼屋（不应发生，validate_map 已拦截）
            return
        # 中间优先作为 Blinky 出生位
        center_idx = len(spawn) // 2
        blinky_pos = spawn[center_idx]
        # 其他依次偏移
        n = max(2, min(4, self.config.ghosts))
        # Blinky 必有
        self.ghosts = [Ghost(Kind.BLINKY, blinky_pos, level=self.config.level)]
        # 其他按顺序
        other_kinds = [Kind.PINKY, Kind.INKY, Kind.CLYDE]
        idx = 1
        for k in other_kinds[: n - 1]:
            # 选取 spawn 中另一格（与 Blinky 不同）
            pos = spawn[(center_idx + idx) % len(spawn)]
            self.ghosts.append(Ghost(k, pos, level=self.config.level))
            idx += 1

    def _init_elroy(self):
        """Elroy 阈值按关卡计算；初始不激活。"""
        self.elroy_threshold = elroy_threshold_for_level(self.level)

    # ------------------------------------------------------------------
    # 主循环 tick
    # ------------------------------------------------------------------
    def tick(self) -> None:
        """推进一 tick（方案 §3.3 主循环时序）。

        dt 取自时钟；暂停时不推进。
        """
        if self.status != Status.PLAYING:
            return
        now = self._clock()
        # 暂停相位补偿：扣除 _pause_accum
        dt_raw = now - self._tick_phase_start
        dt = max(0.0, dt_raw - self._pause_accum)
        self._pause_accum = 0.0
        self._tick_phase_start = now

        # 1. 玩家转向缓冲消费（每 tick 开始）
        self.player.consume_turn(self.gm)

        # 2. 玩家移动（按当前方向走；玩家恒 1.0 速度）
        self.player.add_motion()

        # 3. 幽灵决策 + 移动
        self._step_ghosts(dt)

        # 4. 碰撞判定
        self._handle_collisions()

        # 5. 吃豆判定
        self._handle_dot_eating()

        # 6. 能量豆倒计时
        if self.power_timer > 0.0:
            self.power_timer = max(0.0, self.power_timer - dt)
            if self.power_timer == 0.0:
                # 限时结束：恢复全部幽灵为全局模式
                for g in self.ghosts:
                    if g.mode == Mode.FRIGHTENED:
                        g.mode = self.mode_ctrl.current

        # 7. 关卡推进
        if self.dots_left <= 0:
            self._next_level()

        # 8. Elroy 检查（每 tick 看残豆）
        self._update_elroy()

        # 9. 玩家保护期倒计时
        self.player.update_protection(dt)

    # ------------------------------------------------------------------
    # 幽灵推进
    # ------------------------------------------------------------------
    def _step_ghosts(self, dt: float):
        """所有幽灵：模式同步 + 决策 + 移动 + 出场规则。"""
        # 3a. 模式计时（仅非 FRIGHTENED/EYES 的全局模式影响其他幽灵）
        if self.power_timer <= 0.0:
            switched = self.mode_ctrl.step(dt)
            if switched:
                # 全局模式切换：除 FRIGHTENED/EYES 外同步到所有幽灵，强制掉头
                for g in self.ghosts:
                    if g.mode in (Mode.FRIGHTENED, Mode.EYES):
                        continue
                    old_mode = g.mode
                    g.mode = self.mode_ctrl.current
                    apply_mode_transition(g, old_mode, g.mode)

        # 3b. 吃豆计数（用于 Inky/Clyde 出场）
        dots_eaten = (self.gm.initial_dots - self.dots_left) if self.gm.initial_dots else 0

        # 3c. 出场规则：在鬼屋的幽灵依条件放出
        for g in self.ghosts:
            if maybe_release_ghost(g, dots_eaten):
                g.in_house = False
                # 移出鬼屋到门外（door 中点）
                g.row, g.col = _house_door_mid(self.gm)

        # 3d. 决策 + 移动
        blinky = next((g for g in self.ghosts if g.kind == Kind.BLINKY), None)
        for g in self.ghosts:
            if g.in_house:
                # 鬼屋内的幽灵：不出屋则原地等待（不做寻路）
                continue
            if g.mode == Mode.EYES:
                # 眼睛：直奔鬼屋门
                eye_target = _house_door_mid(self.gm)
                g.dir = choose_dir(g, eye_target, self.gm)
                g.add_motion()
                # 到门后立即重置
                if (g.row, g.col) == eye_target:
                    g.mode = self.mode_ctrl.current
                    g.in_house = True
                continue
            if g.mode == Mode.FRIGHTENED:
                # 脆弱：随机游走（每 tick 随机选合法方向）
                g.dir = _random_ghost_dir(g, self.gm)
                g.add_motion()
                continue
            # CHASE/SCATTER：计算目标格并寻路
            tgt = target_cell(g, self.player, blinky, self.gm)
            g.dir = choose_dir(g, tgt, self.gm)
            g.add_motion()

    # ------------------------------------------------------------------
    # 碰撞判定
    # ------------------------------------------------------------------
    def _handle_collisions(self):
        """玩家与幽灵同格：按幽灵状态分支处理。"""
        for g in self.ghosts:
            if (g.row, g.col) != (self.player.row, self.player.col):
                continue
            if self.player.protection_timer > 0.0:
                # 保护期不判定（FR-13）
                continue
            if g.mode == Mode.FRIGHTENED:
                # 吃幽灵
                self._eat_ghost(g)
            elif g.mode in (Mode.CHASE, Mode.SCATTER):
                # 扣命
                self._lose_life()
                return  # 一次 tick 只处理一次扣命
            # EYES 状态不冲突（视为通过）

    def _eat_ghost(self, g: Ghost):
        """吃幽灵：得分（递增链）+ 变 EYES + 返鬼屋。"""
        idx = min(self.eaten_chain, len(GHOST_CHAIN_SCORES) - 1)
        points = GHOST_CHAIN_SCORES[idx]
        self.score += points
        self.eaten_chain += 1
        self.ghosts_eaten_total += 1
        g.mode = Mode.EYES
        g.in_house = False
        # EYES 状态会由 _step_ghots 自动返鬼屋门

    def _lose_life(self):
        """扣命流程（方案 §3.3）。"""
        self.lives -= 1
        if self.lives <= 0:
            self.status = Status.GAME_OVER
            return
        # 重置玩家与全部幽灵
        self.player.set_pos(self.gm.player_spawn)
        self.player.dir = Dir.LEFT
        self.player.turn_buffer.clear()
        self.player.protection_timer = PROTECTION_SECONDS
        for g in self.ghosts:
            g.in_house = True
            # 回到鬼屋内的初始位（简化：复用原位）
            # 由 _init_ghosts 决定位置；这里直接 reset 到 ghost 出生点
            # 这里简单处理：把幽灵放回鬼屋中心
            spawn = sorted(self.gm.house_cells)
            if spawn:
                g.row, g.col = spawn[len(spawn) // 2]
            g.mode = Mode.SCATTER
        # 模式重置
        self.mode_ctrl.reset(self.level)
        # 能量豆计时清零
        self.power_timer = 0.0

    # ------------------------------------------------------------------
    # 吃豆判定
    # ------------------------------------------------------------------
    def _handle_dot_eating(self):
        """玩家所在格有豆：加分 + 触发能量豆。"""
        r, c = self.player.row, self.player.col
        if not self.gm.in_bounds(r, c):
            return
        t = self.tiles[r][c]
        if t == Tile.DOT:
            self.tiles[r][c] = Tile.EMPTY
            self.score += DOT_SCORE
            self.dots_left -= 1
        elif t == Tile.POWER:
            self.tiles[r][c] = Tile.EMPTY
            self.score += POWER_SCORE
            self.dots_left -= 1
            self._trigger_power_pellet()

    def _trigger_power_pellet(self):
        """吃能量豆：全部幽灵进入 FRIGHTENED（重置计时 + eaten_chain）。"""
        self.power_timer = power_duration_for_level(self.level)
        self.eaten_chain = 0
        for g in self.ghosts:
            if g.mode == Mode.EYES:
                continue  # 眼睛不受影响
            old_mode = g.mode
            g.mode = Mode.FRIGHTENED
            apply_mode_transition(g, old_mode, g.mode)

    # ------------------------------------------------------------------
    # 过关 / Elroy
    # ------------------------------------------------------------------
    def _next_level(self):
        """过关：level+1 + 地图豆子恢复 + 全实体重置 + 难度参数更新。"""
        self.level += 1
        self.tiles = self.gm.fresh_tiles()
        self.dots_left = self.gm.initial_dots
        self.power_timer = 0.0
        self.eaten_chain = 0
        # 玩家与幽灵重置
        self.player.set_pos(self.gm.player_spawn)
        self.player.dir = Dir.LEFT
        self.player.turn_buffer.clear()
        self.player.protection_timer = 0.0
        for g in self.ghosts:
            g.in_house = True
            spawn = sorted(self.gm.house_cells)
            if spawn:
                g.row, g.col = spawn[len(spawn) // 2]
            g.mode = Mode.SCATTER
            # 出场阈值按新关卡更新
            from .config import inky_release_dots_for_level, clyde_release_dots_for_level
            if g.kind == Kind.INKY:
                g.release_threshold = inky_release_dots_for_level(self.level)
            elif g.kind == Kind.CLYDE:
                g.release_threshold = clyde_release_dots_for_level(self.level)
        # 速度按关卡更新（基础速度）
        for g in self.ghosts:
            if g.mode not in (Mode.EYES, Mode.FRIGHTENED):
                g.speed = ghost_speed_for_level(self.level)
        self.mode_ctrl.reset(self.level)
        # Elroy 阈值按关卡更新
        self.elroy_threshold = elroy_threshold_for_level(self.level)
        # 状态保持 PLAYING（Q12 默认连续闯关）
        self.status = Status.PLAYING

    def _update_elroy(self):
        """Blinky Elroy：残豆 ≤ 阈值 → 速度 1.0（追平玩家）。"""
        for g in self.ghosts:
            if g.kind != Kind.BLINKY:
                continue
            if self.dots_left <= self.elroy_threshold:
                if not g.elroy_active:
                    g.elroy_active = True
                    g.speed = ghost_speed_for_level(self.level)  # 不变，effective_speed 切换
            else:
                if g.elroy_active:
                    g.elroy_active = False

    # ------------------------------------------------------------------
    # 暂停
    # ------------------------------------------------------------------
    def pause(self):
        if self.status == Status.PLAYING:
            self.status = Status.PAUSED
            self._pause_start = self._clock()

    def resume(self):
        if self.status == Status.PAUSED:
            self.status = Status.PLAYING
            # 把暂停时长累积到 _pause_accum，tick 时扣除
            paused_for = self._clock() - self._pause_start
            self._pause_accum += paused_for

    # ------------------------------------------------------------------
    # 注入接口（测试用）
    # ------------------------------------------------------------------
    def force_power_timer(self, value: float):
        """注入能量豆倒计时（测试用）。"""
        self.power_timer = value

    def force_dots_left(self, value: int):
        """注入剩余豆数（测试用）。"""
        self.dots_left = value

    def final_score(self) -> FinalScore:
        """结算数据（用于 GAME_OVER 画面）。"""
        return FinalScore(
            score=self.score,
            level=self.level,
            ghosts_eaten=self.ghosts_eaten_total,
        )


# ============================================================================
# 辅助：鬼屋门中点 + 随机方向
# ============================================================================
def _house_door_mid(gm: GameMap) -> tuple[int, int]:
    """鬼屋门集合的中点（行/列分别取中位数）。"""
    if not gm.door_cells:
        # 无门（不应发生）；返回鬼屋中心
        cells = sorted(gm.house_cells)
        return cells[len(cells) // 2] if cells else (0, 0)
    rs = sorted(r for r, _ in gm.door_cells)
    cs = sorted(c for _, c in gm.door_cells)
    return (rs[len(rs) // 2], cs[len(cs) // 2])


def _random_ghost_dir(g: Ghost, gm: GameMap) -> Dir:
    """FRIGHTENED 状态随机选合法方向（排除反向）。"""
    import random
    reverse_map = {Dir.UP: Dir.DOWN, Dir.DOWN: Dir.UP, Dir.LEFT: Dir.RIGHT, Dir.RIGHT: Dir.LEFT}
    candidates = []
    for d in (Dir.UP, Dir.LEFT, Dir.DOWN, Dir.RIGHT):
        if d == reverse_map[g.dir]:
            continue
        nr = g.row + d.drow
        nc = g.col + d.dcol
        if gm.is_passable_for_ghost(nr, nc):
            candidates.append(d)
    if not candidates:
        return reverse_map[g.dir]
    return random.choice(candidates)
