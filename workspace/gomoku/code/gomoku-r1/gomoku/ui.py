"""UI — terminal rendering and input loop (plan §3 / §4 / §5.4 / §5.5).

This module owns the only third-party dependency of the project
(``rich``) and is the only layer that touches the terminal.  It
provides:

* :func:`render` — paints the board, the last-move marker, and the
  status bar.  Detects color capability and falls back to plain
  characters when ``NO_COLOR`` is set or the terminal is dumb.
* :func:`get_move` — coordinate input loop with friendly error
  messages; catches ``MoveError`` and ``KeyboardInterrupt``.
* :func:`announce_winner` — terminal banner on game over.
* :func:`check_terminal_size` — refuses to start a game in a window
  that cannot hold the board cleanly (NFR-03).
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .board import Board, MoveError


# Minimum terminal size required to render the 15×15 board without
# truncating.  Plan §5.4 specifies 24 rows × 60 columns.
MIN_TERMINAL_ROWS = 24
MIN_TERMINAL_COLS = 60


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
_NO_COLOR = bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()


def _stone_glyph(color: str) -> str:
    """Return the human-friendly glyph for a stone.

    Black -> filled circle, white -> hollow circle (Unicode).  Falls
    back to ASCII letters when the terminal is not UTF-8 (best-effort).
    """
    if color == "B":
        return "●"
    if color == "W":
        return "○"
    return "."


def _stone_style(color: str) -> str:
    """Return the rich style for a stone; respects NO_COLOR/dumb terminal."""
    if _NO_COLOR:
        return ""
    if color == "B":
        return "bold black on white"
    if color == "W":
        return "bold white on grey23"
    return ""


# ---------------------------------------------------------------------------
# Terminal size check (plan §5.4)
# ---------------------------------------------------------------------------
class TerminalTooSmall(RuntimeError):
    """Raised when the terminal is too small to render the board."""


def check_terminal_size(min_rows: int = MIN_TERMINAL_ROWS,
                        min_cols: int = MIN_TERMINAL_COLS) -> Tuple[int, int]:
    """Return current (rows, cols) and raise if below the minimums.

    Plan §5.4: "启动时检查 shutil.get_terminal_size()，< 24×60 时
    提示"终端过小"并等待放大" — this function raises so the caller
    can decide how to wait.  The main loop in main.py implements the
    "wait until resized" behavior.
    """
    cols, rows = shutil.get_terminal_size((min_cols, min_rows))
    if rows < min_rows or cols < min_cols:
        raise TerminalTooSmall(
            f"terminal is {cols}x{rows}; need at least {min_cols}x{min_rows}"
        )
    return rows, cols


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
# A single shared Console.  ``soft_wrap=False`` so the board grid
# renders as a fixed block; ``force_terminal`` not set so we honor
# the user's actual terminal.
_console: Console = Console(soft_wrap=False)


def get_console() -> Console:
    """Return the shared rich :class:`Console` for advanced callers (tests)."""
    return _console


def render(
    board: Board,
    *,
    turn: Optional[str] = None,
    last_move: Optional[Tuple[int, int]] = None,
    message: str = "",
    human_color: str = "B",
    difficulty: str = "medium",
    forbidden: bool = False,
) -> None:
    """Render the board, last-move marker, and status bar.

    Parameters
    ----------
    board : Board
        Board state to draw.
    turn : str, optional
        The color whose turn it is next ("B" or "W").  Drives the
        "current player" line of the status bar.
    last_move : (x, y), optional
        Coordinates of the most recent stone; rendered with a
        different style (plan §3 / FR-08).
    message : str
        Extra status-bar text (e.g. "AI 思考中…" while computing).
    human_color : str
        Color the human plays — used to label "You" / "AI" in the bar.
    difficulty : str
        Current difficulty, for display.
    forbidden : bool
        Whether forbidden-move rules are on — for display.
    """
    n = board.size

    # Column header line: spaces for the row-number column, then A B C ...
    header = Text()
    header.append("   ")  # room for the row-number label column
    for x in range(n):
        # Padding: single-letter column + space.  Two cells per column
        # so the grid below lines up.
        col_letter = chr(ord("A") + x)
        header.append(f" {col_letter}")
    _console.print(header)

    grid = Table.grid(padding=(0, 0))
    # Each row of the grid: row number, then n stone cells.
    rows: list = []
    for y in range(n):
        row_cells: list = []
        # Row number label — 1-indexed, right-aligned to two chars.
        row_cells.append(Text(f"{y + 1:2d} ", style="dim"))
        for x in range(n):
            cell = board.get(x, y)
            if cell == ".":
                t = Text(" ·", style="dim")
            else:
                glyph = _stone_glyph(cell)
                style = _stone_style(cell)
                t = Text(f" {glyph}", style=style)
            if last_move is not None and (x, y) == last_move:
                # Last-move marker: underline the glyph (rich style).
                t.stylize("underline", 0, len(t))
            row_cells.append(t)
        rows.append(row_cells)
    grid.add_row(*[c for row in rows for c in row])
    _console.print(grid)

    # Status bar
    status = Text()
    status.append("当前玩家: ", style="bold")
    if turn is None:
        status.append("—")
    elif turn == human_color:
        status.append("你 ", style="green")
        status.append(f"({turn})")
    else:
        status.append("AI ", style="red")
        status.append(f"({turn})")
    status.append("   难度: ")
    status.append(difficulty, style="cyan")
    status.append("   禁手: ")
    status.append("开" if forbidden else "关", style=("yellow" if forbidden else "dim"))
    if last_move is not None:
        lx, ly = last_move
        status.append(
            f"   上一步: {chr(ord('A') + lx)}{ly + 1} "
            f"({board.get(lx, ly)})"
        )
    if message:
        status.append("   ")
        status.append(message, style="italic")
    _console.print(status)


def announce_winner(winner: Optional[str], forbidden_reason: Optional[str] = None) -> None:
    """Print a banner for the end of a game.

    ``winner`` is ``"B"`` / ``"W"`` for a win, ``None`` for a draw.
    ``forbidden_reason`` (when set) is appended to the black-loss
    banner — UI surface for FR-07.
    """
    if winner is None:
        text = Text("平局！", style="bold yellow", justify="center")
    elif winner == "B":
        text = Text("黑方胜！", style="bold green", justify="center")
    else:
        text = Text("白方胜！", style="bold red", justify="center")
        if forbidden_reason:
            text.append(f"  (黑方禁手：{forbidden_reason})", style="yellow")
    panel = Panel(text, border_style="bright_blue", expand=False)
    _console.print(panel)


# ---------------------------------------------------------------------------
# Input loop
# ---------------------------------------------------------------------------
def get_move(board: Board, human_color: str) -> Optional[Tuple[int, int]]:
    """Prompt the human for a coordinate; return ``(x, y)`` or ``None`` to quit.

    Handles three failure modes (plan §5.4):
      * format / range / occupied errors — print specific reason, re-prompt;
      * ``KeyboardInterrupt`` — re-raise so main.py can exit cleanly
        (FR-11 / plan §3 "中断" branch);
      * the literal string ``"quit"`` / ``"exit"`` — return ``None``
        to signal a polite exit (FR-11).
    """
    while True:
        try:
            raw = input("请输入落子坐标 (例: A8 / 8,8)，或 quit 退出: ")
        except EOFError:
            # Ctrl+D — treat as polite exit.
            _console.print("[dim]已收到 EOF，退出。[/dim]")
            return None
        except KeyboardInterrupt:
            # Re-raise so main.py can perform terminal cleanup centrally.
            raise

        s = raw.strip()
        if not s:
            continue
        if s.lower() in ("quit", "exit", "q"):
            return None

        try:
            return board.parse_move(s)
        except MoveError as e:
            if e.reason == MoveError.REASON_FORMAT:
                _console.print(f"[red]格式错误[/red]：{e}")
            elif e.reason == MoveError.REASON_OUT_OF_RANGE:
                _console.print(f"[red]越界[/red]：{e}")
            elif e.reason == MoveError.REASON_OCCUPIED:
                _console.print(f"[red]该位置已有棋子[/red]：{e}")
            else:  # pragma: no cover - defensive
                _console.print(f"[red]输入错误[/red]：{e}")
            # loop and re-prompt
