"""Data-driven tests for :py:meth:`Board.check_forbidden` (FR-07).

The fixture table lives in ``tests/data/forbidden_cases.json`` and
mirrors ``plan/gomoku-r1.md §5.2 附录 A`` (A1..A15) plus the
"B-prefix" extras the code developer added in
``gomoku/forbidden_cases.py``.  Every case is a single test; failures
print the full board so the regressing shape is obvious.

These cases are the red-line regression set for the previous
lifecycle's code r2 FAIL ("禁手活三/四形态遗漏"); in particular A1
and A3 ("_X_XX_ 落子最左 X" / "_XX_X_ 落子最右 X") were the
specific shapes that broke before.  Don't drop or rename them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gomoku.board import BLACK, Board


DATA_PATH = Path(__file__).parent / "data" / "forbidden_cases.json"


def _load_cases():
    with DATA_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["cases"]


def _format_board(b: Board) -> str:
    lines = []
    for y in range(b.size):
        lines.append(" ".join(b.cell(x, y) for x in range(b.size)))
    return "\n".join(lines)


def _id_to_param(case):
    return case["id"], case["label"]


def _setup_board(case) -> Board:
    b = Board(15)
    for cell in case["setup"]:
        if len(cell) == 3:
            x, y, color = cell
        else:
            x, y = cell
            color = BLACK
        ok = b.place(x, y, color)
        assert ok, (
            f"setup failed for case {case['id']} at {(x, y, color)}"
        )
    return b


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["id"])
def test_forbidden_case(case):
    b = _setup_board(case)
    cx, cy = case["candidate"]
    got = b.check_forbidden(cx, cy, BLACK)
    want = (case["expected"]["is_forbidden"], case["expected"]["reason"])
    assert got == want, (
        f"\n  case:   {case['id']} {case['label']!r}"
        f"\n  point:  {(cx, cy)}"
        f"\n  want:   {want}"
        f"\n  got:    {got}"
        f"\n  board:\n{_format_board(b)}"
    )


# ---------------------------------------------------------------------------
# Reason classification (TC-FB-17)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "setup,point,expected_reason",
    [
        # double_three
        ([[1, 5], [3, 5], [2, 1], [2, 3]], (2, 5), "double_three"),
        # double_four
        ([[0, 3], [1, 3], [2, 3], [3, 0], [3, 1], [3, 2]], (3, 3), "double_four"),
        # overline
        ([[0, 5], [1, 5], [2, 5], [3, 5], [4, 5]], (5, 5), "overline"),
    ],
)
def test_forbidden_reason_distinguished(setup, point, expected_reason):
    """TC-FB-17: ``reason`` string distinguishes the three rule classes.

    The UI uses the reason to produce a specific error message — the
    three values must be different (and stable across releases).
    """
    b = Board(15)
    for cell in setup:
        x, y = cell[0], cell[1]
        color = cell[2] if len(cell) == 3 else BLACK
        b.place(x, y, color)
    is_forbidden, reason = b.check_forbidden(*point, BLACK)
    assert is_forbidden
    assert reason == expected_reason


# ---------------------------------------------------------------------------
# White stones are never forbidden (TC-FB-13 / TC-FB-16)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "setup",
    [
        # white double three
        [[0, 0, "W"], [1, 0, "W"], [3, 0, "W"], [2, 0, "B"]],
        # white double four
        [[0, 0, "W"], [1, 0, "W"], [2, 0, "W"], [3, 0, "W"]],
        # white overline
        [[0, 0, "W"], [1, 0, "W"], [2, 0, "W"], [3, 0, "W"], [4, 0, "W"]],
    ],
)
def test_white_never_forbidden(setup):
    """TC-FB-13 / TC-FB-16: forbidden-move rules only apply to black.

    Even when white stones form a shape that would be forbidden for
    black (double three, double four, overline) the move is still
    legal for white.
    """
    b = Board(15)
    for cell in setup:
        x, y = cell[0], cell[1]
        color = cell[2]
        b.place(x, y, color)
    # Pick a point on the line (any of the white stones).
    is_forbidden, reason = b.check_forbidden(0, 0, "W")
    assert is_forbidden is False
    assert reason is None


# ---------------------------------------------------------------------------
# Five-on-the-move priority (TC-FB-11)
# ---------------------------------------------------------------------------


def test_five_wins_over_double_three():
    """TC-FB-11: a move that completes a five AND creates a double-three
    is legal (five wins, FR-07).  We set up: 4 black stones on row 4
    + 3 black stones on col 4 → candidate (4, 4) makes five on row 4
    AND a four on col 4 (not two fours, so no double-four).  Expected:
    legal.
    """
    b = Board(15)
    for x in range(4):
        b.place(x, 4, BLACK)
    for y in range(3):
        b.place(4, y, BLACK)
    is_forbidden, reason = b.check_forbidden(4, 4, BLACK)
    assert is_forbidden is False
    assert reason is None
    # And the move should be a winning move:
    b.place(4, 4, BLACK)
    assert b.check_win(4, 4) == BLACK
