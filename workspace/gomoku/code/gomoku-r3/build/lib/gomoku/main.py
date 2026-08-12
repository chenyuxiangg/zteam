"""main — CLI entry point and main game loop (plan §3 / §4 / §5.4).

* Parses CLI arguments via :mod:`argparse` (plan §4).
* Builds a :class:`Config` from the arguments.
* Drives the turn loop:

    1. render the board
    2. if it is the human's turn, call ``ui.get_move``; otherwise
       call ``ai.choose_move``
    3. validate the move (range, occupancy, forbidden-move)
    4. check for a five-in-a-row or a full board
    5. swap turns

* Handles the three exit paths: ``quit`` command, ``Ctrl+C`` (clean
  restore, exit 0), and the post-game "play again" prompt.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import List, Optional, Tuple

from . import __version__
from .ai import choose_move as ai_choose_move
from .board import Board, MoveError
from .config import Config
from .ui import (
    TerminalTooSmall,
    announce_winner,
    check_terminal_size,
    get_console,
    get_move as ui_get_move,
    render,
)


# ---------------------------------------------------------------------------
# CLI (plan §4)
# ---------------------------------------------------------------------------
def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the gomoku CLI."""
    p = argparse.ArgumentParser(
        prog="gomoku",
        description=(
            "Linux terminal gomoku (human vs AI).  Pass --help for "
            "options; see README.md for the full guide."
        ),
    )
    p.add_argument(
        "--size",
        type=int,
        choices=(13, 15),
        default=15,
        help="board side length (default: 15)",
    )
    p.add_argument(
        "--difficulty",
        type=str,
        choices=("weak", "medium", "strong"),
        default="medium",
        help="AI difficulty tier (default: medium)",
    )
    p.add_argument(
        "--forbidden",
        type=str,
        choices=("on", "off"),
        default="off",
        help="enable Renju forbidden-move rules for black (default: off)",
    )
    p.add_argument(
        "--human",
        type=str,
        choices=("black", "white"),
        default="black",
        help="color the human plays (default: black)",
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"gomoku {__version__}",
    )
    return p


def parse_args(argv: Optional[List[str]] = None) -> Config:
    """Parse ``argv`` (default: ``sys.argv[1:]``) and return a :class:`Config`."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    return Config(
        size=args.size,
        difficulty=args.difficulty,
        forbidden=(args.forbidden == "on"),
        human_color="B" if args.human == "black" else "W",
    )


# ---------------------------------------------------------------------------
# Game-state container
# ---------------------------------------------------------------------------
class GameState:
    """Mutable per-game state shared by the main loop.

    Kept tiny on purpose — the main loop only needs to know whose
    turn it is, what the last move was, and whether the game is
    already over.  The board itself is the source of truth.
    """

    __slots__ = ("turn", "last_move", "over", "winner", "forbidden_reason")

    def __init__(self, human_color: str) -> None:
        # Black always moves first in gomoku (plan §1 / §5.4 / H3).
        # If the human is white, the AI plays first as black.
        self.turn: str = "B"
        self.last_move: Optional[Tuple[int, int]] = None
        self.over: bool = False
        self.winner: Optional[str] = None
        # When the game ends on a forbidden-move call, this captures
        # the reason for the end-of-game banner.
        self.forbidden_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Signal handling (FR-11 / plan §3)
# ---------------------------------------------------------------------------
# A single SIGINT handler: raise KeyboardInterrupt from the main
# thread so the top-level try/except in main() can perform the
# unified cleanup path.  We install it lazily (only on first call)
# to avoid surprising the test-suite.
_SIGINT_INSTALLED = False


def _install_sigint_handler() -> None:
    global _SIGINT_INSTALLED
    if _SIGINT_INSTALLED:
        return
    def _raise_kbi(_signum, _frame):  # pragma: no cover - signal path
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, _raise_kbi)
    _SIGINT_INSTALLED = True


# ---------------------------------------------------------------------------
# Per-move handling
# ---------------------------------------------------------------------------
def _apply_human_move(
    board: Board, x: int, y: int, config: Config, state: GameState
) -> None:
    """Place the human's move and update game state.

    Performs the FR-07 forbidden-move check (when the human is black
    and forbidden rules are on).  In that case the human loses
    immediately — no re-prompt.
    """
    if config.forbidden and config.human_color == "B":
        is_forbidden, reason = board.check_forbidden(x, y, "B")
        if is_forbidden:
            state.winner = "W"
            state.over = True
            state.forbidden_reason = reason
            # We still record the move on the board so the user can
            # *see* the offending placement before the banner appears.
            board.place(x, y, "B")
            state.last_move = (x, y)
            return

    board.place(x, y, config.human_color)
    state.last_move = (x, y)
    if board.check_win(x, y):
        state.winner = config.human_color
        state.over = True
        return
    if board.is_full():
        state.winner = None  # draw
        state.over = True
        return
    state.turn = "W" if config.human_color == "B" else "B"


def _apply_ai_move(
    board: Board, x: int, y: int, config: Config, state: GameState
) -> None:
    """Place the AI's move and update game state (mirrors _apply_human_move)."""
    ai_color = config.ai_color
    if config.forbidden and ai_color == "B":
        # The AI is expected to avoid forbidden moves; this is a
        # safety net.  If we somehow landed on one, treat it as a
        # self-forfeit.
        is_forbidden, reason = board.check_forbidden(x, y, "B")
        if is_forbidden:
            state.winner = "W"  # i.e. the human wins by default
            state.over = True
            state.forbidden_reason = reason
            board.place(x, y, "B")
            state.last_move = (x, y)
            return

    board.place(x, y, ai_color)
    state.last_move = (x, y)
    if board.check_win(x, y):
        state.winner = ai_color
        state.over = True
        return
    if board.is_full():
        state.winner = None
        state.over = True
        return
    state.turn = "W" if ai_color == "B" else "B"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def _wait_for_terminal_resize() -> None:
    """Block until the terminal is at least 60×24 (plan §5.4 / ST-18)."""
    console = get_console()
    while True:
        try:
            check_terminal_size()
            return
        except TerminalTooSmall as e:
            console.print(
                f"[yellow]终端过小（{e}）。请放大窗口后按 Enter 继续…[/yellow]",
                end="",
            )
            try:
                input()
            except EOFError:
                # EOF before resize — give up and proceed; render may
                # still partially succeed.
                return
            except KeyboardInterrupt:
                raise


def _post_game_prompt() -> bool:
    """Ask the user whether to play again.  Returns True on "yes"."""
    console = get_console()
    while True:
        try:
            raw = input("再来一局？(y/n): ")
        except EOFError:
            return False
        except KeyboardInterrupt:
            raise
        s = raw.strip().lower()
        if s in ("y", "yes"):
            return True
        if s in ("n", "no", ""):
            return False
        console.print("[yellow]请输入 y 或 n。[/yellow]")


def play_one_game(config: Config) -> bool:
    """Run a single game.  Returns True if the user wants another game.

    Encapsulates the inner game loop so ``main()`` can call it for the
    "play again" path.  All state is local; the board is created here
    so the second game is truly a fresh board (FR-10).
    """
    board = Board(config.size)
    state = GameState(config.human_color)

    # If the AI is black, make its first move before the first render.
    while not state.over:
        render(
            board,
            turn=state.turn,
            last_move=state.last_move,
            human_color=config.human_color,
            difficulty=config.difficulty,
            forbidden=config.forbidden,
        )
        if state.turn == config.human_color:
            mv = ui_get_move(board, config.human_color)
            if mv is None:
                # Polite quit (typed "quit"/"exit"/"q" or hit EOF).
                get_console().print("[dim]已退出。[/dim]")
                return False
            x, y = mv
            _apply_human_move(board, x, y, config, state)
        else:
            t0 = time.monotonic()
            mv = ai_choose_move(board, state.turn, config.difficulty)
            dt = time.monotonic() - t0
            if mv is None:
                # AI has no legal move — treat as a draw.
                state.winner = None
                state.over = True
                break
            get_console().print(
                f"[dim]AI 思考耗时 {dt * 1000:.0f} ms[/dim]"
            )
            _apply_ai_move(board, mv[0], mv[1], config, state)

    # Final render + banner.
    render(
        board,
        turn=None,
        last_move=state.last_move,
        human_color=config.human_color,
        difficulty=config.difficulty,
        forbidden=config.forbidden,
    )
    announce_winner(state.winner, forbidden_reason=state.forbidden_reason)
    return _post_game_prompt()


def main(argv: Optional[List[str]] = None) -> int:
    """Top-level entry point.  Returns an integer exit code."""
    _install_sigint_handler()
    try:
        config = parse_args(argv)
    except SystemExit:
        # argparse already printed a usage message.
        return 2

    console = get_console()
    console.print(
        f"[bold bright_blue]Gomoku[/bold bright_blue]  v{__version__}"
        f"  ·  {config.size}×{config.size}  ·  难度 {config.difficulty}"
        f"  ·  禁手 {'开' if config.forbidden else '关'}"
    )

    try:
        _wait_for_terminal_resize()
    except (EOFError, KeyboardInterrupt):
        console.print("[dim]已取消启动。[/dim]")
        return 0

    try:
        while True:
            again = play_one_game(config)
            if not again:
                break
            # Re-check terminal size on restart — the user may have
            # resized during play.
            try:
                _wait_for_terminal_resize()
            except (EOFError, KeyboardInterrupt):
                break
    except KeyboardInterrupt:
        console.print("\n[dim]Ctrl+C 收到，已退出。[/dim]")
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry
    sys.exit(main())
