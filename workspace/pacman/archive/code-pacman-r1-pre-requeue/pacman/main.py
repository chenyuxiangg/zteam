"""程序入口与实时游戏循环。

职责：CLI/TTY 检查、curses wrapper、非阻塞输入、单调时钟推进和资源清理；对应开发方案 §3.3、§4.1、§5.3。
依赖：Python 标准库 curses/time/sys；pacman 配置、地图、游戏、输入、渲染模块。
"""

from __future__ import annotations

import curses
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

# 同时支持推荐入口 ``python -m pacman`` 与方案约定的
# ``python pacman/main.py``。后者没有包上下文，需先加入产物根目录。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from pacman.config import Config, TICK_SECONDS, parse_args
    from pacman.game import Game, GameStatus
    from pacman.input import Command, map_key
    from pacman.map import GameMap, MapError
    from pacman.renderer import Renderer, TerminalTooSmall
else:
    from .config import Config, TICK_SECONDS, parse_args
    from .game import Game, GameStatus
    from .input import Command, map_key
    from .map import GameMap, MapError
    from .renderer import Renderer, TerminalTooSmall


class GameQuit(Exception):
    pass


def run_curses(screen, config: Config, game_map: GameMap) -> int:
    curses.curs_set(0)
    screen.keypad(True)
    screen.nodelay(True)
    screen.timeout(20)
    renderer = Renderer(screen, config.no_color)
    game = Game(config, game_map)
    previous = time.monotonic()

    try:
        while True:
            now = time.monotonic()
            dt = now - previous
            previous = now

            while True:
                key = screen.getch()
                if key == -1:
                    break
                if game.status is GameStatus.GAME_OVER:
                    return 0
                action = map_key(
                    key,
                    key_up=curses.KEY_UP,
                    key_left=curses.KEY_LEFT,
                    key_down=curses.KEY_DOWN,
                    key_right=curses.KEY_RIGHT,
                )
                if action is None:
                    continue
                if action.command is Command.QUIT:
                    raise GameQuit
                if action.command is Command.PAUSE:
                    game.toggle_pause()
                elif action.direction is not None:
                    game.queue_player_direction(action.direction)

            game.update(dt)
            renderer.draw(game, now)
            remaining = TICK_SECONDS - (time.monotonic() - now)
            if remaining > 0:
                time.sleep(min(remaining, 0.02))
    except TerminalTooSmall as exc:
        screen.nodelay(False)
        screen.timeout(-1)
        renderer.draw_error(str(exc))
        screen.getch()
        return 1
    except (KeyboardInterrupt, GameQuit):
        return 0


def main_cli(argv: Optional[Sequence[str]] = None) -> int:
    config = parse_args(argv)
    try:
        game_map = GameMap.load(config.map_path)
    except MapError as exc:
        print(f"pacman: {exc}", file=sys.stderr)
        return 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("pacman: 需要真实终端（TTY）运行", file=sys.stderr)
        return 1
    try:
        return int(curses.wrapper(run_curses, config, game_map))
    except KeyboardInterrupt:
        return 0
    except curses.error as exc:
        print(f"pacman: 终端初始化失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
