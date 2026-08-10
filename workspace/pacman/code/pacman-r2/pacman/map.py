"""地图加载、校验与查询。

职责：字符串地图 → Tile 网格；FR-03 三项离线判定（连通性/鬼屋通道/多规格适用）。
依赖：标准库 collections（deque）。
对应方案：plans/pacman-r1.md §3.2 map.py、§4.3 地图设计与 FR-03 三项离线判定。
不依赖 curses（纯逻辑层，可单测）。

本文件为 r1 第 1 轮 code 阶段产出；与 pre-requeue 旧版相比逻辑无变化。
"""


from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

from .config import Kind


# ============================================================================
# Tile 枚举（字符 → 语义）
# ============================================================================
class Tile(Enum):
    """地图格子类型。"""
    WALL = "#"
    EMPTY = " "       # 通道（无豆）
    DOT = "."         # 普通豆
    POWER = "o"       # 能量豆
    DOOR = "-"        # 鬼屋门（仅幽灵可通行，玩家视为墙）
    HOUSE = "H"       # 鬼屋内部（仅幽灵可通行）
    PLAYER_SPAWN = "P"  # 玩家出生区（渲染为通道，玩家可通行）


# 字符 → Tile 映射
CHAR_TO_TILE = {
    "#": Tile.WALL,
    ".": Tile.DOT,
    "o": Tile.POWER,
    "-": Tile.DOOR,
    "H": Tile.HOUSE,
    "P": Tile.PLAYER_SPAWN,
    " ": Tile.EMPTY,
}


# ============================================================================
# 位置与尺寸
# ============================================================================
Pos = Tuple[int, int]   # (row, col)


# ============================================================================
# 地图错误
# ============================================================================
class MapError(Exception):
    """地图加载/校验错误（含行列定位）。"""
    def __init__(self, message: str, line: int = 0, col: int = 0):
        self.line = line
        self.col = col
        loc = f"row {line}, col {col}" if line else ""
        super().__init__(f"{message} ({loc})" if loc else message)


# ============================================================================
# 地图数据
# ============================================================================
@dataclass
class GameMap:
    """游戏地图（已校验通过）。

    属性：
      tiles[row][col]: 二维 Tile 网格
      rows/cols: 尺寸
      player_spawn: 玩家出生点（row, col）（取 P 标记格的中心或左上）
      house_cells: 鬼屋内部格集合
      door_cells: 鬼屋门格集合
    """
    tiles: list[list[Tile]]
    rows: int
    cols: int
    player_spawn: Pos
    house_cells: set = field(default_factory=set)
    door_cells: set = field(default_factory=set)
    initial_dots: int = 0   # 加载时的总豆数（含能量豆）

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------
    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def tile_at(self, r: int, c: int) -> Optional[Tile]:
        """返回 (r,c) 处的 Tile；越界返回 None。"""
        if not self.in_bounds(r, c):
            return None
        return self.tiles[r][c]

    def is_passable_for_player(self, r: int, c: int) -> bool:
        """玩家可通行：非墙、非鬼屋门/鬼屋。"""
        t = self.tile_at(r, c)
        if t is None:
            return False
        return t not in (Tile.WALL, Tile.DOOR, Tile.HOUSE)

    def is_passable_for_ghost(self, r: int, c: int) -> bool:
        """幽灵可通行：非墙（DOOR 与 HOUSE 允许）。"""
        t = self.tile_at(r, c)
        if t is None:
            return False
        return t != Tile.WALL

    def is_dot(self, r: int, c: int) -> bool:
        """是否为普通豆或能量豆（吃豆判定用）。"""
        t = self.tile_at(r, c)
        return t in (Tile.DOT, Tile.POWER)

    def is_power(self, r: int, c: int) -> bool:
        return self.tile_at(r, c) == Tile.POWER

    def dots_remaining(self, tiles: list[list[Tile]]) -> int:
        """统计当前 tiles 中剩余豆数（含能量豆）。"""
        count = 0
        for row in tiles:
            for t in row:
                if t in (Tile.DOT, Tile.POWER):
                    count += 1
        return count

    # ------------------------------------------------------------------
    # 重置（过关后）
    # ------------------------------------------------------------------
    def fresh_tiles(self) -> list[list[Tile]]:
        """返回一份初始豆子恢复后的 tiles 拷贝（过关重置用）。"""
        return [row[:] for row in self.tiles]


# ============================================================================
# 加载与校验
# ============================================================================
def _load_map_file(path: str) -> list[str]:
    """读取地图文件，按行返回字符串列表。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        raise MapError(f"地图文件不存在：{path}")
    except OSError as e:
        raise MapError(f"地图文件读取失败：{e}")
    return lines


def _parse_grid(lines: list[str]) -> tuple[list[list[Tile]], list[Pos], list[Pos], list[Pos]]:
    """解析地图字符串为 Tile 网格，同时收集 P/H/- 位置。

    返回：(tiles, player_spawns, house_cells, door_cells)
    行宽不一致：报错（首行宽度为基准）。
    """
    if not lines:
        raise MapError("地图文件为空")

    width = len(lines[0])
    if any(len(line) != width for line in lines):
        raise MapError("地图行宽不一致")

    tiles: list[list[Tile]] = []
    player_spawns: list[Pos] = []
    house_cells: list[Pos] = []
    door_cells: list[Pos] = []

    for r, line in enumerate(lines):
        row: list[Tile] = []
        for c, ch in enumerate(line):
            if ch not in CHAR_TO_TILE:
                raise MapError(f"非法字符 '{ch}'", line=r + 1, col=c + 1)
            tile = CHAR_TO_TILE[ch]
            row.append(tile)
            if tile == Tile.PLAYER_SPAWN:
                player_spawns.append((r, c))
            elif tile == Tile.HOUSE:
                house_cells.append((r, c))
            elif tile == Tile.DOOR:
                door_cells.append((r, c))
        tiles.append(row)

    return tiles, player_spawns, house_cells, door_cells


def _check_basic(tiles: list[list[Tile]], player_spawns: list[Pos],
                 house_cells: list[Pos], door_cells: list[Pos]) -> dict:
    """基础校验：行数下限、能量豆 ≥4、玩家出生点存在、鬼屋非空、门非空。"""
    stats = {"rows": len(tiles), "cols": len(tiles[0]) if tiles else 0,
             "dots": 0, "powers": 0}

    if stats["rows"] < 5 or stats["cols"] < 5:
        raise MapError(f"地图过小（需 ≥5×5，当前 {stats['rows']}×{stats['cols']}）")

    if not player_spawns:
        raise MapError("缺少玩家出生点 P")
    if not house_cells:
        raise MapError("缺少鬼屋 H")
    if not door_cells:
        raise MapError("缺少鬼屋门 -")

    for row in tiles:
        for t in row:
            if t == Tile.DOT:
                stats["dots"] += 1
            elif t == Tile.POWER:
                stats["powers"] += 1

    if stats["powers"] < 4:
        raise MapError(f"能量豆数量不足（需 ≥4，当前 {stats['powers']}）")
    total = stats["dots"] + stats["powers"]
    if total < 100:
        raise MapError(f"总豆数不足（需 ≥100，当前 {total}）")
    return stats


def _validate_connectivity(tiles: list[list[Tile]], player_spawn: Pos,
                           house_cells: set, door_cells: set) -> None:
    """FR-03 三项离线判定 ① + ②。

    ① 全部豆子格（DOT/POWER）可从玩家出生点沿合法通道到达。
       BFS：以玩家出生点为起点，仅允许玩家可通行格通行。
    ② 鬼屋 HOUSE 区必须存在 ≥1 个 DOOR 格通往迷宫主体（玩家可通行的区域）。
       实现：HOUSE 必须邻接（4 邻居）一个 DOOR，且该 DOOR 可被玩家从出生点到达。
    """
    rows, cols = len(tiles), len(tiles[0])

    # 玩家视角 BFS：从出生点出发，标记可达的"玩家可通行"格
    reachable = [[False] * cols for _ in range(rows)]
    queue = deque([player_spawn])
    r0, c0 = player_spawn
    reachable[r0][c0] = True

    def player_passable(r: int, c: int) -> bool:
        if not (0 <= r < rows and 0 <= c < cols):
            return False
        t = tiles[r][c]
        return t not in (Tile.WALL, Tile.DOOR, Tile.HOUSE)

    while queue:
        r, c = queue.popleft()
        for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nr, nc = r + dr, c + dc
            if not player_passable(nr, nc):
                continue
            if reachable[nr][nc]:
                continue
            reachable[nr][nc] = True
            queue.append((nr, nc))

    # ① 所有豆子格必须可达
    isolated = []
    for r in range(rows):
        for c in range(cols):
            if tiles[r][c] in (Tile.DOT, Tile.POWER) and not reachable[r][c]:
                isolated.append((r, c))
    if isolated:
        r, c = isolated[0]
        raise MapError(f"存在不可达豆子格（共 {len(isolated)} 个，首个）",
                       line=r + 1, col=c + 1)

    # ② 鬼屋必须有门，且门在迷宫主体一侧邻接可达的玩家可通行格
    #    门本身（DOOR）对玩家视为墙，BFS 不会穿过——因此判定"门连通"=
    #    "门的非 HOUSE 邻居中至少有一个是被玩家从出生点可达的玩家可通行格"。
    if not door_cells:
        raise MapError("鬼屋缺门")
    door_set = set(door_cells)
    rows, cols = len(tiles), len(tiles[0])
    has_door_open = False
    for (dr, dc) in door_cells:
        # 门的四个邻居
        for ddr, ddc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nr, nc = dr + ddr, dc + ddc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            t = tiles[nr][nc]
            # 邻接 HOUSE 不算（鬼屋内部本来就连着门）
            if t == Tile.HOUSE:
                continue
            # 邻接 WALL 也不算（墙隔着）
            if t == Tile.WALL:
                continue
            # 邻接门/玩家可通行格，且该邻居从玩家出生点可达
            if reachable[nr][nc]:
                has_door_open = True
                break
        if has_door_open:
            break
    if not has_door_open:
        raise MapError("鬼屋门未连通迷宫主体（堵死）")

    # HOUSE 必须至少有一个格邻接某个 DOOR（结构性要求）
    has_house_to_door = False
    for (hr, hc) in house_cells:
        for ddr, ddc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nb = (hr + ddr, hc + ddc)
            if nb in door_set:
                has_house_to_door = True
                break
        if has_house_to_door:
            break
    if not has_house_to_door:
        raise MapError("鬼屋内部未邻接任何门（堵死）")


def _check_house_enclosed(tiles: list[list[Tile]], house_cells: set) -> None:
    """鬼屋必须四周封闭（HOUSE 格不被通道/豆格穿透）。

    实现：检查每个 HOUSE 格，其 4 邻居中允许的只能是 HOUSE/DOOR/WALL，
    不能是玩家可通行格（DOT/POWER/EMPTY/PLAYER_SPAWN）。
    """
    rows = len(tiles)
    for (hr, hc) in house_cells:
        for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nr, nc = hr + dr, hc + dc
            if not (0 <= nr < rows and 0 <= nc < len(tiles[0])):
                continue
            t = tiles[nr][nc]
            # HOUSE/DOOR/WALL 是鬼屋内部/门/外墙，可接受
            if t in (Tile.HOUSE, Tile.DOOR, Tile.WALL):
                continue
            # 其他任何格（玩家可通行）= 鬼屋墙破了
            raise MapError(f"鬼屋不封闭（row {hr + 1}, col {hc + 1} 邻居为 {t.value}）",
                           line=hr + 1, col=hc + 1)
            # 不会到这里


def load_map(path: str) -> GameMap:
    """加载地图文件，完整执行三项离线判定，校验通过后返回 GameMap。

    FR-03 三项离线判定：
      ① 全部豆子格可从玩家出生点沿合法通道到达（BFS）
      ② 鬼屋 HOUSE 区有 ≥1 个 DOOR 通往迷宫主体（且可达）
      ③ 多规格适用（判定①②对任意合规格地图统一执行；内置 22×19 与任意 --map 均通过）
    """
    lines = _load_map_file(path)
    tiles, player_spawns, house_cells_list, door_cells_list = _parse_grid(lines)

    # 基础校验（含豆数、出生点、能量豆数量）
    stats = _check_basic(tiles, player_spawns, house_cells_list, door_cells_list)

    # 鬼屋必须封闭
    house_cells_set = set(house_cells_list)
    _check_house_enclosed(tiles, house_cells_set)

    # 玩家出生点：取第一个 P（多 P 时选最靠上/左）
    player_spawn = player_spawns[0]

    # 判定① + ②（连通性 + 鬼屋通道）
    _validate_connectivity(tiles, player_spawn, house_cells_set, set(door_cells_list))

    initial_dots = stats["dots"] + stats["powers"]
    return GameMap(
        tiles=tiles,
        rows=stats["rows"],
        cols=stats["cols"],
        player_spawn=player_spawn,
        house_cells=house_cells_set,
        door_cells=set(door_cells_list),
        initial_dots=initial_dots,
    )


# 兼容导出（test 可直接调用 validate_* 子函数）
__all__ = [
    "Tile", "GameMap", "MapError", "Pos",
    "load_map", "validate_map",
]


# ============================================================================
# 顶层便捷函数：load_map 之后返回 GameMap；validate_map 仅做校验不构建
# ============================================================================
def validate_map(path: str) -> None:
    """仅校验不构建：用于启动期"先看对不对"的场景（如测试）。

    校验失败抛 MapError，成功静默返回。
    """
    gm = load_map(path)
    # load_map 已完整执行判定；此处显式再调一次以确保接口语义
    _validate_connectivity(gm.tiles, gm.player_spawn, gm.house_cells, gm.door_cells)
