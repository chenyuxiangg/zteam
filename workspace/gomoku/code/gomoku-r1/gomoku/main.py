"""CLI entry point and game loop for gomoku.

This module wires the :mod:`gomoku.board`, :mod:`gomoku.ai`,
:mod:`gomoku.ui`, and :mod:`gomoku.config` modules together and
implements:

* CLI argument parsing (size / difficulty / forbidden / human color /
  debug-timing);
* the main turn loop with proper move validation, win detection, and
  forbidden-move handling (FR-07 priority: five wins over a
  forbidden move);
* replay / restart on game end (FR-10);
* Ctrl+C / EOFError / "quit" command polite exit (FR-11);
* terminal-size check (FR-03 / NFR-03);
* the safety-net check (post-AI move): if a forbidden move slipped
  through, the safety net declares black lost and the game ends.

The forbidden-move prefilter lives in :mod:`gomoku.ai` (see
``_filter_legal``) so the safety-net here is a *secondary* check (it
can fire if the AI ever returns a forbidden cell because of a bug,
which would surface as an immediate loss in tests).
"""

from __future__ import annotations

import sys
from typing import Optional, Tuple

from gomoku.ai import choose_move
from gomoku.board import (
    BLACK,
    EMPTY,
    MoveError,
    REASON_OCCUPIED,
    REASON_OUT_OF_RANGE,
    WHITE,
    Board,
)
from gomoku.config import (
    ALLOWED_FORBIDDEN,
    build_arg_parser,
    config_from_args,
)
from gomoku.ui import (
    _TimingState,
    ensure_terminal_size,
    get_move,
    render,
)


def main(argv: Optional[list] = None) -> int:
    """Console-script entry point.  Returns a process exit code."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)

    try:
        return _run(config)
    except KeyboardInterrupt:
        print("\nInterrupted — bye.", file=sys.stderr)
        return 0


def _run(config) -> int:
    """Game loop.  Returns 0 on polite exit, non-zero on argparse error."""

    ensure_terminal_size()
    board = Board(config.size)
    state = {
        "turn": BLACK if config.human_color == "black" else WHITE,
        "over": False,
        "winner": None,
        "message": "Game started.",
    }
    timing = _TimingState(enabled=config.debug_timing, samples=[])

    while True:
        try:
            _step(board, state, config, timing)
        except (EOFError, KeyboardInterrupt):
            # Polite exit on Ctrl+D / Ctrl+C
            return 0
        except SystemExit as exc:
            # ui.get_move raises SystemExit(0) for "quit" / "exit" / "q"
            return int(exc.code) if isinstance(exc.code, int) else 0
        if state["over"]:
            try:
                again = _ask_replay(config)
            except (EOFError, KeyboardInterrupt):
                return 0
            if again:
                board.reset()
                state.update(
                    {
                        "turn": BLACK if config.human_color == "black" else WHITE,
                        "over": False,
                        "winner": None,
                        "message": "Game restarted.",
                    }
                )
                continue
            return 0


def _step(board: Board, state: dict, config, timing: _TimingState) -> None:
    """Render, get/apply a move, check for win/forbidden/draw, switch turn."""

    render(
        board,
        turn=state["turn"],
        last_move=board.last_move,
        message=state.get("message", ""),
        over=state["over"],
        winner=state.get("winner"),
        timing=timing,
    )
    state["message"] = ""

    if state["over"]:
        return

    color = state["turn"]
    if color == _human_color(config):
        move = get_move(board)
    else:
        move = choose_move(board, color, config)
        if move is None:
            state["over"] = True
            state["winner"] = None
            state["message"] = "draw (no empty cells)"
            render(board, turn=color, last_move=board.last_move,
                   message=state["message"], over=True, winner=None,
                   timing=timing)
            return

    # Place the stone.
    x, y = move
    if not board.place(x, y, color):
        # This can only happen for a *human* move (the AI filters its
        # own candidates).  Treat as illegal input.
        state["message"] = f"illegal move at {(x, y)} (occupied or out of range)"
        return  # re-render next loop

    # Renju safety-net for black: if the human played a forbidden move,
    # declare the human lost (FR-07).
    if color == BLACK and config.forbidden_enabled:
        is_forbidden, reason = board.check_forbidden(x, y, color)
        # After placing, check_forbidden(x, y, B) still returns the
        # status of the move that *would* be made at (x, y).  Since the
        # stone is already there, check_forbidden treats it as
        # occupied and returns (False, None).  So we compute forbidden
        # *before* placing, or via undo.  We do a quick recompute:
        is_forbidden, reason = _recheck_forbidden(board, x, y, color)
        if is_forbidden:
            state["over"] = True
            state["winner"] = WHITE
            state["message"] = f"Black played a forbidden move ({reason}) — White wins."
            render(board, turn=color, last_move=(x, y),
                   message=state["message"], over=True, winner=WHITE,
                   timing=timing)
            return

    # Win?
    if board.check_win(x, y) == color:
        state["over"] = True
        state["winner"] = color
        state["message"] = f"{'Black' if color == BLACK else 'White'} wins!"
        render(board, turn=color, last_move=(x, y),
               message=state["message"], over=True, winner=color,
               timing=timing)
        return

    # Draw?
    if board.is_full():
        state["over"] = True
        state["winner"] = None
        state["message"] = "draw"
        render(board, turn=color, last_move=(x, y),
               message=state["message"], over=True, winner=None,
               timing=timing)
        return

    # Switch turn
    state["turn"] = WHITE if color == BLACK else BLACK


def _recheck_forbidden(
    board: Board, x: int, y: int, color: str
) -> Tuple[bool, Optional[str]]:
    """Undo the just-placed stone, run ``check_forbidden`` on the now
    empty cell, then re-place the stone.  Used to detect forbidden moves
    *after* the move has been recorded on the board.
    """

    if color != BLACK:
        return False, None
    board.undo(x, y)
    is_forbidden, reason = board.check_forbidden(x, y, BLACK)
    board.place(x, y, BLACK)
    return is_forbidden, reason


def _human_color(config) -> str:
    return BLACK if config.human_color == "black" else WHITE


def _ask_replay(config) -> bool:
    """Prompt the user for replay / quit.  Returns True to restart."""

    try:
        line = input("Play again? [y/N] > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return line in ("y", "yes")


if __name__ == "__main__":
    sys.exit(main())
