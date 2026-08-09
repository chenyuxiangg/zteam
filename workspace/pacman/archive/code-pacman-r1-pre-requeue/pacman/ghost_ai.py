"""幽灵差异化 AI 与模式节奏。

职责：计算四幽灵目标格、路口选向、散开/追逐切换参数；对应开发方案 §4.4、§5.1、§5.4。
依赖：pacman.entities、pacman.map；不依赖 curses。
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence

from .entities import Dir, Ghost, GhostKind, GhostMode, Player
from .map import GameMap, Pos


DIR_PRIORITY: Sequence[Dir] = (Dir.UP, Dir.LEFT, Dir.DOWN, Dir.RIGHT)
SCATTER_PHASES = (True, False, True, False, True, False, True, False)


def offset_ahead(pos: Pos, direction: Dir, cells: int, original_up_bug: bool = True) -> Pos:
    """计算玩家前方格；朝上时忠实复刻原版额外左偏。"""
    dr, dc = direction.delta
    target = Pos(pos.row + dr * cells, pos.col + dc * cells)
    if original_up_bug and direction is Dir.UP:
        target = Pos(target.row, target.col - cells)
    return target


def target_cell(
    ghost: Ghost,
    player: Player,
    blinky: Ghost,
    game_map: GameMap,
) -> Pos:
    """返回 Dossier 规则下的追逐目标，且夹取到地图边界内。"""
    if ghost.kind is GhostKind.BLINKY:
        raw = player.pos
    elif ghost.kind is GhostKind.PINKY:
        raw = offset_ahead(player.pos, player.direction, 4)
    elif ghost.kind is GhostKind.INKY:
        pivot = offset_ahead(player.pos, player.direction, 2)
        raw = Pos(2 * pivot.row - blinky.pos.row, 2 * pivot.col - blinky.pos.col)
    else:
        distance = math.hypot(ghost.pos.row - player.pos.row, ghost.pos.col - player.pos.col)
        raw = player.pos if distance >= 8.0 else ghost.home_corner
    return game_map.clamp(raw)


def choose_direction(
    ghost: Ghost,
    game_map: GameMap,
    target: Pos,
    rng: Optional[random.Random] = None,
) -> Dir:
    """在合法候选中选到目标曼哈顿距离最小方向；平局 UP>LEFT>DOWN>RIGHT。"""
    legal: List[Dir] = [
        direction
        for direction in DIR_PRIORITY
        if game_map.passable(ghost.pos.moved(direction.delta), for_ghost=True)
    ]
    if not legal:
        return ghost.direction.reverse
    if ghost.force_reverse and ghost.direction.reverse in legal:
        ghost.force_reverse = False
        return ghost.direction.reverse

    non_reverse = [direction for direction in legal if direction is not ghost.direction.reverse]
    candidates = non_reverse or legal
    if ghost.mode is GhostMode.FRIGHTENED:
        return (rng or random).choice(candidates)

    def key(direction: Dir):
        nxt = ghost.pos.moved(direction.delta)
        distance = abs(nxt.row - target.row) + abs(nxt.col - target.col)
        return distance, DIR_PRIORITY.index(direction)

    return min(candidates, key=key)


def scatter_duration(level: int) -> float:
    return max(7.0 - 2.0 * (level - 1), 1.0)


def phase_duration(level: int, phase_index: int) -> float:
    if phase_index >= len(SCATTER_PHASES) - 1:
        return math.inf
    return scatter_duration(level) if SCATTER_PHASES[phase_index] else 20.0


def phase_mode(phase_index: int) -> GhostMode:
    index = min(phase_index, len(SCATTER_PHASES) - 1)
    return GhostMode.SCATTER if SCATTER_PHASES[index] else GhostMode.CHASE


def elroy_threshold(level: int) -> int:
    return max(20 - 3 * (level - 1), 5)


def release_threshold(kind: GhostKind, level: int) -> int:
    if kind in (GhostKind.BLINKY, GhostKind.PINKY):
        return 0
    if kind is GhostKind.INKY:
        return max(30 - 5 * (level - 1), 10)
    return max(60 - 10 * (level - 1), 20)


def scatter_targets(game_map: GameMap) -> Dict[GhostKind, Pos]:
    return {
        GhostKind.BLINKY: Pos(0, game_map.width - 1),
        GhostKind.PINKY: Pos(0, 0),
        GhostKind.INKY: Pos(game_map.height - 1, game_map.width - 1),
        GhostKind.CLYDE: Pos(game_map.height - 1, 0),
    }
