"""渲染纯函数/桩测试：覆盖方案 E-01/S-02/S-03/S-06/S-08/S-10/N-03。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests._path import code_dir  # noqa: F401

from pacman.config import Kind, Mode
from pacman.game import Status
from pacman.map import Tile
from pacman.renderer import (
    COLOR_BLINKY, COLOR_CLYDE, COLOR_FRIGHT, COLOR_FRIGHT_FLASH,
    COLOR_INKY, COLOR_PINKY, Renderer, _ghost_char_color, _tile_char_color,
)
from tests.fixtures import build_game, make_ghost


class ScreenStub:
    def __init__(self, lines=24, cols=80):
        self.lines, self.cols = lines, cols
        self.writes = []
        self.erased = self.refreshed = False
    def erase(self): self.erased = True
    def refresh(self): self.refreshed = True
    def getmaxyx(self): return self.lines, self.cols
    def addstr(self, y, x, text, *attrs): self.writes.append((y, x, str(text)))
    def nodelay(self, value): pass
    def keypad(self, value): pass
    def timeout(self, value): pass
    def getch(self): return ord("q")
    @property
    def text(self): return "\n".join(x[2] for x in self.writes)


def renderer(screen):
    with patch("pacman.renderer.curses.curs_set"), patch("pacman.renderer._init_colors", return_value=False):
        return Renderer(screen, no_color=True)


class TestTileAndGhostRendering(unittest.TestCase):
    def test_no_color_tiles_are_distinct(self):
        chars = [_tile_char_color(t, False)[0] for t in (Tile.WALL, Tile.DOT, Tile.POWER, Tile.DOOR, Tile.HOUSE)]
        self.assertEqual(chars, ["#", ".", "o", "-", "H"])

    def test_four_ghost_colors_are_distinct(self):
        colors = []
        for kind in Kind:
            ghost = make_ghost(kind)
            ghost.mode = Mode.CHASE
            ch, color = _ghost_char_color(ghost, 0.0, True)
            self.assertEqual(ch, "G")
            colors.append(color)
        self.assertEqual(set(colors), {COLOR_BLINKY, COLOR_PINKY, COLOR_INKY, COLOR_CLYDE})

    def test_frightened_flash_last_two_seconds(self):
        ghost = make_ghost(Kind.BLINKY)
        ghost.mode = Mode.FRIGHTENED
        self.assertEqual(_ghost_char_color(ghost, 4.0, True), ("F", COLOR_FRIGHT))
        observed = {_ghost_char_color(ghost, t, True)[1] for t in (1.8, 1.6, 1.4, 1.2)}
        self.assertEqual(observed, {COLOR_FRIGHT, COLOR_FRIGHT_FLASH})


class TestRendererPanels(unittest.TestCase):
    def test_small_terminal_shows_size_hint(self):
        screen = ScreenStub(20, 60)
        renderer(screen).draw(build_game())
        self.assertIn("需要 ≥80×24", screen.text)
        self.assertIn("当前 60×20", screen.text)

    def test_hud_contains_score_lives_level_and_power(self):
        screen = ScreenStub()
        game = build_game()
        game.score, game.lives, game.level, game.power_timer = 123, 2, 4, 3.2
        renderer(screen).draw(game)
        for text in ("分数: 123", "命: 2", "关: 4", "能量: 3.2s"):
            self.assertIn(text, screen.text)

    def test_pause_panel(self):
        screen = ScreenStub()
        game = build_game()
        game.status = Status.PAUSED
        renderer(screen).draw(game)
        self.assertIn("已暂停", screen.text)

    def test_game_over_panel(self):
        screen = ScreenStub()
        game = build_game()
        game.score, game.level, game.ghosts_eaten_total = 999, 7, 3
        game.status = Status.GAME_OVER
        renderer(screen).draw(game)
        for text in ("游戏结束", "最终得分: 999", "到达关卡: 7", "吃幽灵数: 3"):
            self.assertIn(text, screen.text)


if __name__ == "__main__":
    unittest.main()
