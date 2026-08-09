"""curses 终端渲染器。

职责：渲染迷宫、实体、HUD、暂停与结算画面，并处理颜色降级；对应开发方案 §3.2、§5.3。
依赖：Python 标准库 curses、pacman.game/map/entities/config。
"""

from __future__ import annotations

import curses
from typing import Dict

from .config import MIN_TERM_COLS, MIN_TERM_LINES
from .entities import GhostKind, GhostMode
from .game import Game, GameStatus
from .map import Pos, Tile


class TerminalTooSmall(RuntimeError):
    pass


class Renderer:
    MAP_OFFSET_Y = 3
    MAP_OFFSET_X = 2

    def __init__(self, screen, no_color: bool = False) -> None:
        self.screen = screen
        self.use_color = False
        self.colors: Dict[str, int] = {}
        if not no_color and curses.has_colors():
            try:
                curses.start_color()
                curses.use_default_colors()
                specs = {
                    "wall": curses.COLOR_BLUE,
                    "dot": curses.COLOR_WHITE,
                    "player": curses.COLOR_YELLOW,
                    "blinky": curses.COLOR_RED,
                    "pinky": curses.COLOR_MAGENTA,
                    "inky": curses.COLOR_CYAN,
                    "clyde": curses.COLOR_YELLOW,
                    "fright": curses.COLOR_BLUE,
                    "white": curses.COLOR_WHITE,
                }
                for index, (name, foreground) in enumerate(specs.items(), 1):
                    curses.init_pair(index, foreground, -1)
                    self.colors[name] = curses.color_pair(index)
                self.use_color = True
            except curses.error:
                self.use_color = False
                self.colors.clear()

    @staticmethod
    def size_ok(lines: int, cols: int) -> bool:
        return lines >= MIN_TERM_LINES and cols >= MIN_TERM_COLS

    def draw(self, game: Game, now: float) -> None:
        lines, cols = self.screen.getmaxyx()
        if not self.size_ok(lines, cols):
            raise TerminalTooSmall(f"需要 ≥{MIN_TERM_COLS}×{MIN_TERM_LINES} 终端，当前 {cols}×{lines}")
        self.screen.erase()
        status = game.status.value
        if game.power_timer > 0:
            status = f"能量暴走 {game.power_timer:0.1f}s"
        self._safe_add(0, 2, f"PAC-MAN  分数 {game.score:06d}  命数 {game.lives}  关卡 {game.level}  状态 {status}", curses.A_BOLD)
        self._safe_add(1, 2, "方向键/WASD 移动  P 暂停  q 退出", curses.A_DIM)
        self._draw_map(game)
        self._draw_entities(game, now)
        if game.message_timer > 0:
            self._safe_add(self.MAP_OFFSET_Y + game.map.height, 2, game.message, curses.A_BOLD)
        if game.status is GameStatus.GAME_OVER:
            self._draw_game_over(game)
        elif game.status is GameStatus.PAUSED:
            self._draw_center("已暂停 — 按 P 继续")
        self.screen.refresh()

    def draw_error(self, message: str) -> None:
        self.screen.erase()
        self._draw_center(message)
        lines, _ = self.screen.getmaxyx()
        if lines >= 3:
            self._safe_add(lines // 2 + 1, 1, "调整终端后按任意键退出", curses.A_DIM)
        self.screen.refresh()

    def _draw_map(self, game: Game) -> None:
        glyphs = {
            Tile.WALL: "██",
            Tile.EMPTY: "  ",
            Tile.DOT: " ·",
            Tile.POWER: " ●",
            Tile.DOOR: "──",
            Tile.HOUSE: "  ",
        }
        attrs = {
            Tile.WALL: self._attr("wall", curses.A_BOLD),
            Tile.DOT: self._attr("dot", curses.A_DIM),
            Tile.POWER: self._attr("dot", curses.A_BOLD),
            Tile.DOOR: self._attr("pinky", curses.A_DIM),
        }
        for row in range(game.map.height):
            for col in range(game.map.width):
                tile = game.map.grid[row][col]
                self._safe_add(
                    self.MAP_OFFSET_Y + row,
                    self.MAP_OFFSET_X + col * 2,
                    glyphs[tile],
                    attrs.get(tile, 0),
                )

    def _draw_entities(self, game: Game, now: float) -> None:
        player_attr = self._attr("player", curses.A_BOLD)
        if game.protection_timer <= 0 or int(now * 8) % 2 == 0:
            self._draw_pos(game.player.pos, "ᗧ ", player_attr)

        chars = {
            GhostKind.BLINKY: "B ",
            GhostKind.PINKY: "P ",
            GhostKind.INKY: "I ",
            GhostKind.CLYDE: "C ",
        }
        colors = {
            GhostKind.BLINKY: "blinky",
            GhostKind.PINKY: "pinky",
            GhostKind.INKY: "inky",
            GhostKind.CLYDE: "clyde",
        }
        for ghost in game.ghosts:
            if ghost.mode is GhostMode.EYES:
                glyph, attr = "◉ ", self._attr("white", curses.A_BOLD)
            elif ghost.mode is GhostMode.FRIGHTENED:
                flashing = game.power_timer <= 2.0 and int(now / 0.2) % 2 == 0
                glyph = "w " if flashing else "f "
                attr = self._attr("white" if flashing else "fright", curses.A_BOLD)
            else:
                glyph = chars[ghost.kind]
                attr = self._attr(colors[ghost.kind], curses.A_BOLD)
            self._draw_pos(ghost.pos, glyph, attr)

    def _draw_pos(self, pos: Pos, glyph: str, attr: int) -> None:
        self._safe_add(
            self.MAP_OFFSET_Y + pos.row,
            self.MAP_OFFSET_X + pos.col * 2,
            glyph,
            attr,
        )

    def _draw_game_over(self, game: Game) -> None:
        """用多行短文本显示结算，兼容 Unicode 双宽终端。"""
        lines, cols = self.screen.getmaxyx()
        box_width = min(42, max(cols - 4, 1))
        start_col = max((cols - box_width) // 2, 0)
        start_row = max(lines // 2 - 2, 0)
        entries = (
            "游戏结束",
            f"最终分数：{game.score}",
            f"到达关卡：{game.level}    吃幽灵：{game.ghosts_eaten}",
            "按任意键退出",
        )
        for offset, text in enumerate(entries):
            self._safe_add(
                start_row + offset,
                start_col,
                text.center(box_width),
                curses.A_REVERSE | (curses.A_BOLD if offset == 0 else 0),
            )

    def _draw_center(self, text: str) -> None:
        lines, cols = self.screen.getmaxyx()
        clipped = text[: max(cols - 2, 1)]
        row = max(lines // 2, 0)
        col = max((cols - len(clipped)) // 2, 0)
        self._safe_add(row, col, clipped, curses.A_REVERSE | curses.A_BOLD)

    def _attr(self, name: str, fallback: int = 0) -> int:
        return self.colors.get(name, 0) | fallback

    def _safe_add(self, row: int, col: int, text: str, attr: int = 0) -> None:
        try:
            lines, cols = self.screen.getmaxyx()
            if 0 <= row < lines and col < cols:
                self.screen.addnstr(row, max(col, 0), text, max(cols - max(col, 0) - 1, 0), attr)
        except curses.error:
            pass
