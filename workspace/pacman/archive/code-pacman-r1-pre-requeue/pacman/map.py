"""迷宫加载、校验与查询。

职责：解析字符地图、维护可消费豆子、提供通行与连通性查询；对应开发方案 §3.2、§4.2、§4.3。
依赖：Python 标准库 dataclasses/enum/pathlib/collections。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple


class MapError(ValueError):
    """地图格式或拓扑无效。"""


class Tile(Enum):
    WALL = "#"
    EMPTY = " "
    DOT = "."
    POWER = "o"
    DOOR = "-"
    HOUSE = "H"


@dataclass(frozen=True, order=True)
class Pos:
    row: int
    col: int

    def moved(self, delta: Tuple[int, int]) -> "Pos":
        return Pos(self.row + delta[0], self.col + delta[1])


_ALLOWED = set("#.o-HPBIKC ")
_GHOST_MARKERS = set("BIKC")


class GameMap:
    """可重置的矩形迷宫；模板数据与当前豆子状态分离。"""

    def __init__(
        self,
        template: Sequence[Sequence[Tile]],
        player_spawns: Sequence[Pos],
        ghost_spawns: Sequence[Pos],
        source: str = "<memory>",
    ) -> None:
        self._template = tuple(tuple(row) for row in template)
        self.height = len(self._template)
        self.width = len(self._template[0])
        self.player_spawns = tuple(player_spawns)
        self.ghost_spawns = tuple(ghost_spawns)
        self.source = source
        self.house_cells = tuple(
            Pos(r, c)
            for r, row in enumerate(self._template)
            for c, tile in enumerate(row)
            if tile is Tile.HOUSE
        )
        self.door_cells = tuple(
            Pos(r, c)
            for r, row in enumerate(self._template)
            for c, tile in enumerate(row)
            if tile is Tile.DOOR
        )
        self.reset()

    @classmethod
    def load(cls, path: Path) -> "GameMap":
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError as exc:
            raise MapError(f"地图文件不存在：{path}") from exc
        except (OSError, UnicodeError) as exc:
            raise MapError(f"无法读取地图文件 {path}：{exc}") from exc
        return cls.from_text(text, str(path))

    @classmethod
    def from_text(cls, text: str, source: str = "<memory>") -> "GameMap":
        lines = text.splitlines()
        if not lines:
            raise MapError(f"{source}: 地图为空")
        width = len(lines[0])
        if width < 5 or len(lines) < 5:
            raise MapError(f"{source}: 地图至少需要 5x5")
        if any(len(line) != width for line in lines):
            bad = next(i for i, line in enumerate(lines, 1) if len(line) != width)
            raise MapError(
                f"{source}: 第 {bad} 行宽度为 {len(lines[bad - 1])}，应为 {width}"
            )

        player_spawns: List[Pos] = []
        explicit_ghosts: List[Pos] = []
        raw = [list(line) for line in lines]
        for r, row in enumerate(raw):
            for c, char in enumerate(row):
                if char not in _ALLOWED:
                    raise MapError(
                        f"{source}: 第 {r + 1} 行第 {c + 1} 列含非法字符 {char!r}"
                    )
                if char == "P":
                    player_spawns.append(Pos(r, c))
                elif char in _GHOST_MARKERS:
                    explicit_ghosts.append(Pos(r, c))

        if not player_spawns:
            raise MapError(f"{source}: 缺少玩家出生标记 P")
        power_count = sum(line.count("o") for line in lines)
        if power_count < 4:
            raise MapError(f"{source}: 能量豆至少需要 4 个，当前 {power_count} 个")
        if not any("H" in line for line in lines):
            raise MapError(f"{source}: 缺少鬼屋 H")
        if not any("-" in line for line in lines):
            raise MapError(f"{source}: 缺少鬼屋门 -")

        tiles: List[List[Tile]] = []
        for row in raw:
            converted: List[Tile] = []
            for char in row:
                if char == "#":
                    converted.append(Tile.WALL)
                elif char == ".":
                    converted.append(Tile.DOT)
                elif char == "o":
                    converted.append(Tile.POWER)
                elif char == "-":
                    converted.append(Tile.DOOR)
                elif char == "H":
                    converted.append(Tile.HOUSE)
                elif char in _GHOST_MARKERS:
                    converted.append(Tile.HOUSE)
                else:  # P 或普通空格
                    converted.append(Tile.EMPTY)
            tiles.append(converted)

        game_map = cls(tiles, player_spawns, explicit_ghosts, source)
        game_map._validate_house_enclosure()
        game_map._validate_connectivity()
        if game_map.initial_dots < 100:
            raise MapError(f"{source}: 豆子总数至少需要 100，当前 {game_map.initial_dots}")
        return game_map

    @property
    def initial_dots(self) -> int:
        return sum(tile in (Tile.DOT, Tile.POWER) for row in self._template for tile in row)

    @property
    def player_start(self) -> Pos:
        return self.player_spawns[len(self.player_spawns) // 2]

    @property
    def ghost_home(self) -> Pos:
        if self.house_cells:
            ordered = sorted(self.house_cells)
            return ordered[len(ordered) // 2]
        return self.door_cells[0]

    @property
    def ghost_door(self) -> Pos:
        ordered = sorted(self.door_cells)
        return ordered[len(ordered) // 2]

    def spawn_for_ghost(self, index: int) -> Pos:
        candidates = self.ghost_spawns or self.house_cells
        return candidates[index % len(candidates)]

    def reset(self) -> None:
        self.grid = [list(row) for row in self._template]

    def in_bounds(self, pos: Pos) -> bool:
        return 0 <= pos.row < self.height and 0 <= pos.col < self.width

    def clamp(self, pos: Pos) -> Pos:
        return Pos(
            min(max(pos.row, 0), self.height - 1),
            min(max(pos.col, 0), self.width - 1),
        )

    def tile_at(self, pos: Pos) -> Tile:
        if not self.in_bounds(pos):
            return Tile.WALL
        return self.grid[pos.row][pos.col]

    def consume(self, pos: Pos) -> Tile:
        tile = self.tile_at(pos)
        if tile in (Tile.DOT, Tile.POWER):
            self.grid[pos.row][pos.col] = Tile.EMPTY
        return tile

    def dots_left(self) -> int:
        return sum(tile in (Tile.DOT, Tile.POWER) for row in self.grid for tile in row)

    def passable(self, pos: Pos, for_ghost: bool = False) -> bool:
        tile = self.tile_at(pos)
        if tile is Tile.WALL:
            return False
        if not for_ghost and tile in (Tile.DOOR, Tile.HOUSE):
            return False
        return True

    def _neighbors(self, pos: Pos) -> Iterable[Pos]:
        for dr, dc in ((-1, 0), (0, -1), (1, 0), (0, 1)):
            nxt = Pos(pos.row + dr, pos.col + dc)
            if self.in_bounds(nxt):
                yield nxt

    def _reachable(self, start: Pos, for_ghost: bool) -> Set[Pos]:
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for nxt in self._neighbors(current):
                if nxt not in seen and self.passable(nxt, for_ghost):
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    def _validate_connectivity(self) -> None:
        player_reachable = self._reachable(self.player_start, False)
        required_player = {
            Pos(r, c)
            for r, row in enumerate(self._template)
            for c, tile in enumerate(row)
            if tile in (Tile.EMPTY, Tile.DOT, Tile.POWER)
        }
        missing = required_player - player_reachable
        if missing:
            first = min(missing)
            raise MapError(
                f"{self.source}: 玩家通道不连通，首个不可达格在第 {first.row + 1} 行第 {first.col + 1} 列"
            )

        ghost_reachable = self._reachable(self.house_cells[0], True)
        required_ghost = {
            Pos(r, c)
            for r, row in enumerate(self._template)
            for c, tile in enumerate(row)
            if tile is not Tile.WALL
        }
        missing_ghost = required_ghost - ghost_reachable
        if missing_ghost:
            first = min(missing_ghost)
            raise MapError(
                f"{self.source}: 幽灵通道不连通，首个不可达格在第 {first.row + 1} 行第 {first.col + 1} 列"
            )

    def _validate_house_enclosure(self) -> None:
        adjacent_doors = set()
        for house in self.house_cells:
            for nxt in self._neighbors(house):
                tile = self._template[nxt.row][nxt.col]
                if tile is Tile.DOOR:
                    adjacent_doors.add(nxt)
                elif tile not in (Tile.HOUSE, Tile.WALL):
                    raise MapError(
                        f"{self.source}: 鬼屋未封闭，第 {nxt.row + 1} 行第 {nxt.col + 1} 列应为墙或门"
                    )
        if not adjacent_doors:
            raise MapError(f"{self.source}: 鬼屋没有相邻的门")
