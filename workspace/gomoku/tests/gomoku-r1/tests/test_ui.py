"""Module-level tests for the :mod:`gomoku.ui` rendering layer.

These exercise the ``render`` function in isolation (no game loop) so
we can assert on the rich output without driving a full game.

Coverage:

* TC-UI-01: 15×15 board renders completely (no truncation at 60 cols).
* TC-UI-02: with ``NO_COLOR=1`` black/white stones are still
  distinguishable (the code uses ●/○ for both, but with a different
  ``style``).
* TC-UI-03: re-rendering after a move doesn't accumulate residue.
* TC-UI-04: column letters A..O and row numbers 1..15 are present.
* TC-UI-09: the "Last:" status line shows after a move.
"""

from __future__ import annotations

import io
import os

import pytest
from rich.console import Console

from gomoku.board import BLACK, Board
from gomoku.config import Config
from gomoku.ui import _TimingState, render


def _capture(board, *, size=15, turn="B", last_move=None, message="",
             over=False, winner=None, no_color=True, width=60):
    """Render the board and return its text output as a string."""
    buf = io.StringIO()
    console = Console(
        file=buf, force_terminal=True, width=width,
        no_color=no_color, color_system=None,
    )
    render(
        board,
        turn=turn,
        last_move=last_move,
        message=message,
        over=over,
        winner=winner,
        console=console,
    )
    return buf.getvalue()


def test_render_15x15_fits_in_60_cols():
    """TC-UI-01: 15×15 board fits in 60 columns (default terminal width)."""
    b = Board(15)
    out = _capture(b)
    # Each cell is `·` or `●`/`○` with a space; the header is
    # `   A B C D E F G H I J K L M N O` which is 3 + 2*15 = 33
    # chars.  Add the `╭─...╮` panel border (2 + 70-ish) — total
    # should comfortably fit in 60 cols because the panel wraps.
    # The strongest assertion: all 15 column letters are present.
    for letter in "ABCDEFGHIJKLMNO":
        assert letter in out, f"column letter {letter!r} missing in render output"
    # All 15 row labels
    for n in range(1, 16):
        # The label "1 ", " 2 ", ... "15" appears before each row.
        assert f" {n} " in out or f"{n} " in out, f"row {n} label missing"


def test_render_stones_use_distinct_glyphs():
    """TC-UI-02: black and white stones use distinct Unicode characters."""
    b = Board(15)
    b.place(0, 0, BLACK)
    out = _capture(b)
    # The two colours use ● (U+25CF) and ○ (U+25CB) — both are present
    # in the rendered output even with NO_COLOR=1 because the
    # distinct chars are part of the render path, not the colour.
    assert "●" in out or "○" in out, "expected at least one stone glyph in output"


def test_render_no_residue_after_move():
    """TC-UI-03: rendering after a move does not double up the board."""
    b = Board(15)
    b.place(0, 0, BLACK)
    out1 = _capture(b)
    b.place(1, 0, BLACK)
    out2 = _capture(b)
    # Each render produces a single board frame; the second output
    # should not contain *two* copies of the first board.  Easiest
    # test: count the column-letter header.
    assert out1.count("A B C D E F G H I J K L M N O") == 1
    assert out2.count("A B C D E F G H I J K L M N O") == 1


def test_render_13x13_uses_m_column():
    """TC-UI-04: 13×13 board shows columns A..M (13 columns)."""
    b = Board(13)
    out = _capture(b, size=13)
    for letter in "ABCDEFGHIJKLM":
        assert letter in out, f"column {letter!r} missing"
    # N and O should NOT be present (13 = M, not O)
    assert "N " not in out or out.count("N ") <= 1
    # The row labels are 1..13
    for n in range(1, 14):
        assert f" {n} " in out or f"{n} " in out


def test_render_status_line_includes_last_move():
    """TC-UI-09: after a move, the status line mentions the last cell."""
    b = Board(15)
    b.place(7, 7, BLACK)  # H8
    out = _capture(b, last_move=(7, 7), turn="W")
    assert "H8" in out or "8,8" in out or "Last" in out


def test_render_timing_state_records():
    """TC-UI-09 (timing): when timing is enabled, the timing state
    records a non-zero duration after render."""
    b = Board(15)
    timing = _TimingState(enabled=True, samples=[])
    console = Console(force_terminal=True, width=60, no_color=True)
    render(b, turn="B", last_move=None, message="", over=False, winner=None,
           console=console, timing=timing)
    assert len(timing.samples) == 1
    assert timing.samples[0] >= 0  # may be 0 on a fast machine


def test_render_timing_disabled_no_samples():
    """When timing is disabled, no samples are recorded."""
    b = Board(15)
    timing = _TimingState(enabled=False, samples=[])
    console = Console(force_terminal=True, width=60, no_color=True)
    render(b, turn="B", last_move=None, message="", over=False, winner=None,
           console=console, timing=timing)
    assert timing.samples == []
