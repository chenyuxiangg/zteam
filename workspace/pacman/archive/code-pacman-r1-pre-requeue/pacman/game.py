"""对局领域状态机。

职责：推进玩家/幽灵移动，处理豆子、能量状态、碰撞、过关、扣命和结算；对应开发方案 §3.3、§4.4、§5.2、§5.4。
依赖：pacman.map/entities/ghost_ai/config；不依赖 curses。
"""

from __future__ import annotations

import random
from enum import Enum
from typing import List, Optional

from .config import Config, TICK_SECONDS
from .entities import Dir, Ghost, GhostKind, GhostMode, Player
from .ghost_ai import (
    choose_direction,
    elroy_threshold,
    phase_duration,
    phase_mode,
    release_threshold,
    scatter_targets,
    target_cell,
)
from .map import GameMap, Pos, Tile


class GameStatus(Enum):
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    GAME_OVER = "GAME_OVER"


GHOST_KINDS = (
    GhostKind.BLINKY,
    GhostKind.PINKY,
    GhostKind.INKY,
    GhostKind.CLYDE,
)
GHOST_POINTS = (200, 400, 800, 1600)


class Game:
    """不依赖终端的完整 Pac-Man 对局模型。"""

    def __init__(self, config: Config, game_map: GameMap, seed: Optional[int] = None) -> None:
        self.config = config
        self.map = game_map
        self.rng = random.Random(seed)
        self.level = config.start_level
        self.lives = config.lives
        self.score = 0
        self.ghosts_eaten = 0
        self.power_timer = 0.0
        self.mode_timer = 0.0
        self.mode_phase = 0
        self.eaten_chain = 0
        self.protection_timer = 2.0
        self.status = GameStatus.PLAYING
        self.dots_eaten_level = 0
        self.message = "准备！"
        self.message_timer = 1.0
        self.player = Player(self.map.player_start, self.map.player_start, Dir.LEFT)
        homes = scatter_targets(self.map)
        self.ghosts: List[Ghost] = []
        for index, kind in enumerate(GHOST_KINDS[: config.ghost_count]):
            spawn = self.map.spawn_for_ghost(index)
            self.ghosts.append(
                Ghost(
                    pos=spawn,
                    spawn=spawn,
                    direction=Dir.UP,
                    kind=kind,
                    home_corner=homes[kind],
                )
            )
        self._reset_entities()

    @property
    def dots_left(self) -> int:
        return self.map.dots_left()

    @property
    def current_mode(self) -> GhostMode:
        return phase_mode(self.mode_phase)

    @property
    def power_duration(self) -> float:
        return max(6.0 - 0.5 * (self.level - 1), 1.0)

    @property
    def ghost_base_speed(self) -> float:
        return min(0.9 + 0.02 * (self.level - 1), 0.98)

    def toggle_pause(self) -> None:
        if self.status is GameStatus.GAME_OVER:
            return
        self.status = (
            GameStatus.PLAYING if self.status is GameStatus.PAUSED else GameStatus.PAUSED
        )

    def queue_player_direction(self, direction: Dir) -> None:
        self.player.queue_direction(direction)

    def update(self, dt: float) -> None:
        if self.status is not GameStatus.PLAYING or dt <= 0:
            return
        # 限制一次 update 的时间跨度，避免挂起恢复后跳变。
        dt = min(dt, 0.25)
        self.message_timer = max(0.0, self.message_timer - dt)
        if self.protection_timer > 0:
            self.protection_timer = max(0.0, self.protection_timer - dt)
        self._advance_modes(dt)
        self._release_ghosts()

        player_steps = self.player.add_motion(1.0 * self.config.speed, dt, TICK_SECONDS)
        for _ in range(player_steps):
            self._move_player_one()
            if self._resolve_collisions():
                return
            self._consume_player_tile()
            if self.status is not GameStatus.PLAYING:
                return

        for ghost in self.ghosts:
            speed = self._ghost_speed(ghost) * self.config.speed
            for _ in range(ghost.add_motion(speed, dt, TICK_SECONDS)):
                self._move_ghost_one(ghost)
                if self._resolve_collisions():
                    return
        # 玩家静止或本 tick 尚未积累到一步时，幽灵碰撞仍须生效。
        self._resolve_collisions()

    def _move_player_one(self) -> None:
        buffered = self.player.buffered_direction
        if buffered is not None and self.map.passable(
            self.player.pos.moved(buffered.delta), for_ghost=False
        ):
            self.player.direction = buffered
            self.player.buffered_direction = None
        target = self.player.pos.moved(self.player.direction.delta)
        if self.map.passable(target, for_ghost=False):
            self.player.pos = target

    def _move_ghost_one(self, ghost: Ghost) -> None:
        if not ghost.released:
            return
        if ghost.mode is GhostMode.EYES:
            target = self.map.ghost_home
        elif ghost.mode is GhostMode.SCATTER:
            if ghost.kind is GhostKind.BLINKY and self.dots_left <= elroy_threshold(self.level):
                target = self.player.pos
            else:
                target = ghost.home_corner
        else:
            target = target_cell(ghost, self.player, self.ghosts[0], self.map)
        ghost.direction = choose_direction(ghost, self.map, target, self.rng)
        nxt = ghost.pos.moved(ghost.direction.delta)
        if self.map.passable(nxt, for_ghost=True):
            ghost.pos = nxt
        if ghost.mode is GhostMode.EYES and ghost.pos in self.map.house_cells:
            ghost.mode = self.current_mode
            ghost.released = True

    def _consume_player_tile(self) -> None:
        tile = self.map.consume(self.player.pos)
        if tile is Tile.DOT:
            self.score += 10
            self.dots_eaten_level += 1
        elif tile is Tile.POWER:
            self.score += 50
            self.dots_eaten_level += 1
            self._start_power_mode()
        else:
            return
        if self.map.dots_left() == 0:
            self._next_level()

    def _start_power_mode(self) -> None:
        self.power_timer = self.power_duration
        self.eaten_chain = 0
        for ghost in self.ghosts:
            if ghost.mode is not GhostMode.EYES:
                if ghost.released:
                    ghost.force_reverse = True
                ghost.mode = GhostMode.FRIGHTENED

    def _advance_modes(self, dt: float) -> None:
        if self.power_timer > 0:
            self.power_timer = max(0.0, self.power_timer - dt)
            if self.power_timer == 0:
                for ghost in self.ghosts:
                    if ghost.mode is GhostMode.FRIGHTENED:
                        ghost.mode = self.current_mode
            return

        self.mode_timer += dt
        duration = phase_duration(self.level, self.mode_phase)
        if self.mode_timer >= duration:
            self.mode_timer -= duration
            self.mode_phase = min(self.mode_phase + 1, 7)
            mode = self.current_mode
            for ghost in self.ghosts:
                if ghost.mode not in (GhostMode.EYES, GhostMode.FRIGHTENED):
                    ghost.mode = mode
                    if ghost.released:
                        ghost.force_reverse = True

    def _release_ghosts(self) -> None:
        for ghost in self.ghosts:
            if not ghost.released and self.dots_eaten_level >= ghost.release_dots:
                ghost.released = True

    def _resolve_collisions(self) -> bool:
        if self.protection_timer > 0:
            return False
        for ghost in self.ghosts:
            if not ghost.released or ghost.pos != self.player.pos:
                continue
            if ghost.mode is GhostMode.FRIGHTENED:
                points = GHOST_POINTS[min(self.eaten_chain, len(GHOST_POINTS) - 1)]
                self.score += points
                self.eaten_chain += 1
                self.ghosts_eaten += 1
                ghost.mode = GhostMode.EYES
                ghost.force_reverse = False
                self.message = f"幽灵 +{points}"
                self.message_timer = 0.8
                continue
            if ghost.mode is not GhostMode.EYES:
                self._lose_life()
                return True
        return False

    def _lose_life(self) -> None:
        self.lives -= 1
        self.power_timer = 0.0
        self.eaten_chain = 0
        if self.lives <= 0:
            self.status = GameStatus.GAME_OVER
            self.message = "游戏结束"
            self.message_timer = 0.0
            return
        self.message = "损失一命"
        self.message_timer = 1.0
        self._reset_entities()

    def _next_level(self) -> None:
        self.level += 1
        self.map.reset()
        self.dots_eaten_level = 0
        self.power_timer = 0.0
        self.eaten_chain = 0
        self.message = f"第 {self.level} 关"
        self.message_timer = 1.0
        self._reset_entities()

    def _reset_entities(self) -> None:
        self.player.reset_position(Dir.LEFT)
        self.mode_phase = 0
        self.mode_timer = 0.0
        self.protection_timer = 2.0
        for ghost in self.ghosts:
            threshold = release_threshold(ghost.kind, self.level)
            ghost.reset_for_round(released=(threshold == 0), release_dots=threshold)

    def _ghost_speed(self, ghost: Ghost) -> float:
        if ghost.mode is GhostMode.EYES:
            return 1.5
        if ghost.mode is GhostMode.FRIGHTENED:
            return 0.75
        if ghost.kind is GhostKind.BLINKY and self.dots_left <= elroy_threshold(self.level):
            return 1.0
        return self.ghost_base_speed
