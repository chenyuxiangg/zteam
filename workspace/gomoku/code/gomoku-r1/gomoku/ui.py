"""Terminal rendering and input loop for gomoku.

Uses :mod:`rich` for colored output.  On terminals without colour
(``NO_COLOR=1`` or non-TTY) we fall back to plain ASCII characters
(``●`` / ``○`` for the two sides).
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from rich.box import ROUNDED
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from gomoku.board import (
    BLACK,
    EMPTY,
    MoveError,
    REASON_FORMAT,
    REASON_OCCUPIED,
    REASON_OUT_OF_RANGE,
    WHITE,
    Board,
    parse_move,
)


# Minimum acceptable terminal size for 15x15.  When the terminal is
# smaller we print a "please enlarge" hint and wait for the user to
# resize (plan §5.4 / FR-03).
MIN_COLS = 60
MIN_ROWS = 24


@dataclass
class _TimingState:
    """Records per-frame render timings when :data:`debug_timing` is set."""

    enabled: bool
    samples: list  # type: ignore[type-arg]

    def record(self, ms: float) -> None:
        if self.enabled:
            self.samples.append(ms)
            print(f"[gomoku-timing] render {ms*1000:.1f} ms", file=sys.stderr)


# A single shared Console — rich's Console handles width detection and
# TTY vs pipe distinction automatically.
def _make_console() -> Console:
    force_terminal = sys.stdout.isatty()
    no_color = bool(os.environ.get("NO_COLOR")) or os.environ.get("TERM", "") == "dumb"
    return Console(
        force_terminal=force_terminal,
        no_color=no_color,
        highlight=False,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render(
    board: Board,
    *,
    turn: str,
    last_move: Optional[Tuple[int, int]],
    message: str = "",
    over: bool = False,
    winner: Optional[str] = None,
    console: Optional[Console] = None,
    timing: Optional[_TimingState] = None,
) -> None:
    """Render the full game frame: status bar + board + footer.

    When ``timing`` is set and enabled, the per-frame render time is
    appended to ``timing.samples`` and printed to stderr.  The
    rendering itself is unchanged.
    """

    console = console or _make_console()
    t0 = time.monotonic() if (timing and timing.enabled) else 0.0

    title = "Gomoku — Linux Terminal"
    status_line = _status_text(turn, last_move, message, over, winner)
    board_text = _board_to_text(board, last_move=last_move)

    body = Text()
    body.append(status_line + "\n\n")
    body.append(board_text)
    if over:
        body.append("\n")
        body.append(_banner(winner, board))
    panel = Panel(body, title=title, box=ROUNDED, border_style="cyan")
    console.print(panel)

    if timing and timing.enabled:
        timing.record(time.monotonic() - t0)


def _status_text(
    turn: str,
    last_move: Optional[Tuple[int, int]],
    message: str,
    over: bool,
    winner: Optional[str],
) -> str:
    if over:
        if winner is None:
            outcome = "Draw"
        else:
            outcome = f"{'Black' if winner == BLACK else 'White'} wins"
        return f"[{outcome}] {message}".strip()
    side = "Black" if turn == BLACK else "White"
    last = ""
    if last_move is not None:
        x, y = last_move
        last_color = "Black" if (board_color := _cell_at_last_move(turn, last_move)) else ""
        # We don't actually need to look at the cell: we use ``turn``
        # to derive the *previous* side (the one that just moved).
        last = f"  Last: {_format_cell(x, y)}"
    hint = "  Enter move (e.g. A8 or 8,8), or 'quit':"
    return f"Turn: {side}{last}  {message}{hint}".strip()


def _cell_at_last_move(turn: str, last_move: Tuple[int, int]) -> str:
    """Return the colour of the *previous* mover (the one that played
    ``last_move``).  We don't have direct access to the cell here, so
    return the opposite of ``turn``.
    """
    return WHITE if turn == BLACK else BLACK


def _format_cell(x: int, y: int) -> str:
    """Format a (x, y) as either ``A8`` or ``8,8`` based on size."""

    col_letter = chr(ord("A") + x)
    row = y + 1
    return f"{col_letter}{row}"


def _board_to_text(board: Board, last_move: Optional[Tuple[int, int]]) -> Text:
    """Render the board as a :class:`rich.text.Text` grid.

    Top row is the column letters; left column is the row numbers.
    Cells use ASCII when colour is disabled (rich handles that
    automatically).
    """

    text = Text()
    # header
    header = "   " + " ".join(_col_letter(i) for i in range(board.size))
    text.append(header + "\n")
    for y in range(board.size):
        row_label = f"{y+1:2d}"
        text.append(row_label + " ")
        for x in range(board.size):
            c = board.cell(x, y)
            if c == EMPTY:
                text.append("·" if not _is_color_enabled() else "·")
            elif c == BLACK:
                if (x, y) == last_move:
                    text.append("●", style="bold red on white")
                else:
                    text.append("●", style="bold red")
            else:  # WHITE
                if (x, y) == last_move:
                    text.append("○", style="bold blue on white")
                else:
                    text.append("○", style="bold blue")
            if x != board.size - 1:
                text.append(" ")
        text.append("\n")
    return text


def _col_letter(i: int) -> str:
    return chr(ord("A") + i)


def _is_color_enabled() -> bool:
    return not bool(os.environ.get("NO_COLOR")) and os.environ.get("TERM", "") != "dumb"


def _banner(winner: Optional[str], board: Board) -> str:
    if winner is None:
        return "Game drawn — board is full."
    side = "Black" if winner == BLACK else "White"
    return f"*** {side} wins! ***"


# ---------------------------------------------------------------------------
# Input loop
# ---------------------------------------------------------------------------


def get_move(
    board: Board,
    console: Optional[Console] = None,
    prompt: str = "your move > ",
) -> Tuple[int, int]:
    """Prompt the user for a coordinate.  Returns ``(x, y)`` on success.

    Validates three things (plan §5.4 三重校验): format, range, and
    occupied.  Occupied cells are reported with ``REASON_OCCUPIED`` so
    the error message can be specific.

    Recognised "quit" commands (``quit``, ``exit``, ``q``) raise
    :class:`SystemExit(0)` so the caller can exit gracefully.  Any
    other invalid input is reported with a per-reason error and the
    loop continues.

    Raises :class:`EOFError` / :class:`KeyboardInterrupt` on Ctrl+D /
    Ctrl+C; the caller (:mod:`gomoku.main`) is responsible for the
    polite-exit behaviour.
    """

    console = console or _make_console()
    while True:
        try:
            text = console.input(prompt)
        except (EOFError, KeyboardInterrupt):
            raise
        if text is None:
            raise EOFError()
        stripped = text.strip().lower()
        if stripped in ("quit", "exit", "q"):
            raise SystemExit(0)
        try:
            x, y = parse_move(text, board.size)
        except MoveError as exc:
            console.print(f"[red]invalid move ({exc.reason})[/red] — {exc.text!r}")
            continue
        if not board.is_empty(x, y):
            console.print(
                f"[red]invalid move ({REASON_OCCUPIED})[/red] — {text!r} is taken"
            )
            continue
        return x, y


# ---------------------------------------------------------------------------
# Terminal-size check
# ---------------------------------------------------------------------------


def ensure_terminal_size(
    console: Optional[Console] = None,
) -> None:
    """Block until the terminal is at least 60 cols × 24 rows.

    On smaller terminals, prints a hint and waits for the user to press
    Enter.  Used by the main loop on startup.
    """

    console = console or _make_console()
    while True:
        size = console.size
        # rich's Console.size is (width, height) actually returns a
        # simple object; we use a forgiving probe via shutil:
        import shutil
        cols, rows = shutil.get_terminal_size((80, 24))
        if cols >= MIN_COLS and rows >= MIN_ROWS:
            return
        console.print(
            f"[yellow]terminal too small ({cols}×{rows}); need "
            f"{MIN_COLS}×{MIN_ROWS}.  Resize and press Enter to continue, "
            f"or 'q' + Enter to quit.[/yellow]"
        )
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            return
        if line.strip().lower() in ("q", "quit", "exit"):
            raise SystemExit(0)
