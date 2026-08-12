"""Helpers for building gomoku board positions in tests.

These utilities wrap :class:`gomoku.board.Board` so that tests can
express a setup declaratively (e.g. ``place_seq([(7, 7, "B"), ...])``)
or by drawing a 9-cell window pattern around a candidate point
(``window_set``).  The same helpers are reused by the data-driven
forbidden-move table and the AI blocking-case fixtures.

All functions return a fresh :class:`Board`; nothing is mutated in
place other than the returned object.
"""

from __future__ import annotations

import random
from typing import Iterable, List, Optional, Sequence, Tuple

from gomoku.board import BLACK, EMPTY, WHITE, Board  # noqa: F401 (some helpers use these)


# 4-line direction vectors; reused by callers that need to walk a line.
DIRECTIONS: Tuple[Tuple[int, int], ...] = (
    (1, 0),
    (0, 1),
    (1, 1),
    (1, -1),
)


def make_board(size: int = 15) -> Board:
    """Return a fresh empty board of the given size."""
    return Board(size)


def place_seq(board: Board, moves: Iterable[Tuple[int, int, str]]) -> Board:
    """Apply a list of ``(x, y, color)`` tuples to ``board`` in order.

    The placements should all succeed; if any ``Board.place`` returns
    ``False`` (out of range, occupied, bad colour) the assertion will
    fail loudly — that's almost always a typo in the fixture.
    """
    for x, y, color in moves:
        ok = board.place(x, y, color)
        assert ok, f"place failed for {(x, y, color)} on board size={board.size}"
    return board


def window_set(
    board: Board,
    center: Tuple[int, int],
    pattern: str,
    color: str,
    dx: int = 1,
    dy: int = 0,
    width: int = 9,
    candidate_idx: Optional[int] = None,
) -> Board:
    """Place a 9-cell window pattern around ``center``.

    ``pattern`` is a string of length ``width`` (default 9) containing
    exactly one ``X`` (or whatever matches ``color``'s marker) and the
    rest ``_``.  The ``X`` character must be present in the string and
    its position determines the candidate point that *would be* placed
    by the move we're testing.

    Direction ``(dx, dy)`` defaults to the horizontal axis.  Cells off
    the board are silently ignored — handy for edge-line cases (A14).

    If ``candidate_idx`` is given, the character at that index of
    ``pattern`` is interpreted as the candidate regardless of what
    marker it carries (useful when the candidate is an existing stone
    in the window, see plan A1 / A3).

    Returns the board for chaining.
    """

    cx, cy = center
    # The marker characters we recognise.
    char_to_color = {"X": color, "_": EMPTY, ".": EMPTY, "O": _opponent(color)}
    if len(pattern) != width:
        raise ValueError(
            f"pattern must be exactly {width} chars, got {len(pattern)}: {pattern!r}"
        )

    # Place from left to right along the window.
    for i, ch in enumerate(pattern):
        # The cell index *i* runs from 0 to width-1.  Its absolute
        # coordinates are (cx + (i - mid)*dx, cy + (i - mid)*dy).
        mid = (width - 1) // 2
        x = cx + (i - mid) * dx
        y = cy + (i - mid) * dy
        if not board.in_bounds(x, y):
            continue
        if ch in ("_", "."):
            continue  # leave empty
        if ch not in char_to_color:
            raise ValueError(f"unknown pattern char {ch!r} in {pattern!r}")
        target_color = char_to_color[ch]
        # Skip if the candidate_idx points to a position that should
        # remain empty (the "what-if" cell).
        if candidate_idx is not None and i == candidate_idx:
            continue
        ok = board.place(x, y, target_color)
        assert ok, f"window_set: place failed at {(x, y)} for {ch!r} in {pattern!r}"
    return board


def gen_midgame(
    size: int,
    target_moves: int,
    seed: int,
    forbid_double: bool = True,
) -> Board:
    """Generate a randomly-filled midgame board of ~``target_moves`` stones.

    Used by ``TC-AI-07`` (NFR-01 timing).  We fill alternating B/W
    stones on random empty cells until we hit ``target_moves`` or the
    board is full.  ``forbid_double=True`` (default) rejects any move
    that would create a five-in-a-row — that prevents the AI from
    short-circuiting on a won midgame.
    """

    rng = random.Random(seed)
    board = Board(size)
    color = BLACK
    moves = 0
    attempts = 0
    while moves < target_moves and attempts < target_moves * 8:
        attempts += 1
        x = rng.randint(0, size - 1)
        y = rng.randint(0, size - 1)
        if not board.is_empty(x, y):
            continue
        if not board.place(x, y, color):
            continue
        if forbid_double and board.check_win(x, y) == color:
            board.undo(x, y)
            continue
        moves += 1
        color = WHITE if color == BLACK else BLACK
        if board.is_full():
            break
    return board


def setup_from_moves(board: Board, moves: Sequence[Tuple[int, int, str]]) -> Board:
    """Convenience wrapper matching the testplan's vocabulary.

    Equivalent to :func:`place_seq`; kept as a separate name so the
    tests read naturally (``setup_from_moves(b, [(7, 7, "B")])``).
    """
    return place_seq(board, moves)


def _opponent(color: str) -> str:
    return WHITE if color == BLACK else BLACK
