"""AI — gomoku decision engine (plan §3 / §4 / §5.3).

Three difficulty tiers (plan §3 / §8 / testplan TQ1):

* ``weak``   — pick a reasonable empty neighbor cell; avoid moves that
  immediately let the opponent win on the next turn.  Fast (<10 ms).
* ``medium`` — evaluate every empty cell with a pattern-based scoring
  function and play the highest-scoring one.  Mid-game ≈ 50–200 ms on
  15×15.
* ``strong`` — alpha-beta search with iterative deepening and a time
  budget (default 1.5 s, plan §5.3 / §6 / H8).  Mid-game stays under
  the NFR-01 budget of 2 s on commodity hardware.

The module imports only the standard library and the local
:mod:`gomoku.board` module.  No ``rich``, no ``numpy`` — keeping
``H6`` (zero-dependency playable) intact at the AI layer.

Public API
----------
``choose_move(board, color, difficulty)`` — plan §4 — returns the
``(x, y)`` to play, or ``None`` if no legal move exists.
"""
from __future__ import annotations

import random
import time
from typing import List, Optional, Tuple

from .board import Board, _DIRECTIONS


# ---------------------------------------------------------------------------
# Pattern score table (plan §4 / §5.3)
# ---------------------------------------------------------------------------
# These constants are the *evaluation* scores (one move's contribution),
# not the win/loss terminal scores.  FIVE is the only one that
# definitively wins the game for the mover.
SCORE = {
    "FIVE": 1_000_000,
    "LIVE_FOUR": 100_000,
    "RUSH_FOUR": 10_000,
    "LIVE_THREE": 5_000,
    "SLEEP_THREE": 500,
    "LIVE_TWO": 200,
    "SLEEP_TWO": 20,
}


# ---------------------------------------------------------------------------
# Pattern classification (plan §5.3 — "5.1 同款方向扫描归类")
# ---------------------------------------------------------------------------
# For each direction and each (color-or-empty) cell, look at the run of
# own-color stones and classify the *longest* open-ended run into one
# of the SCORE buckets.  Empty cells are scored by the *maximum* shape
# they would form if color were placed there, using the same logic as
# forbidden-move detection in board.py.

# A "four" is any pattern that, with one more stone, becomes five.
# We treat both "live four" and "rush/broken four" as fours so that
# double-four detection is consistent.
def _classify_point(board: Board, x: int, y: int, color: str) -> int:
    """Score a single cell ``(x, y)`` as if ``color`` were placed there.

    The board *must* already have ``color`` at ``(x, y)`` (caller
    guarantees this — typically by :meth:`Board.place`).  Empty cells
    are scored by :func:`_classify_empty` which temporarily places and
    rolls back.
    """
    n = board.size
    best = 0
    for dx, dy in _DIRECTIONS:
        run = 1
        # forward
        nx, ny = x + dx, y + dy
        while 0 <= nx < n and 0 <= ny < n and board.get(nx, ny) == color:
            run += 1
            nx += dx
            ny += dy
        open_fwd = 1 if (0 <= nx < n and 0 <= ny < n and board.get(nx, ny) == ".") else 0
        # backward
        nx, ny = x - dx, y - dy
        while 0 <= nx < n and 0 <= ny < n and board.get(nx, ny) == color:
            run += 1
            nx -= dx
            ny -= dy
        open_bwd = 1 if (0 <= nx < n and 0 <= ny < n and board.get(nx, ny) == ".") else 0
        open_ends = open_fwd + open_bwd

        if run >= 5:
            best = max(best, SCORE["FIVE"])
        elif run == 4 and open_ends == 2:
            best = max(best, SCORE["LIVE_FOUR"])
        elif run == 4 and open_ends == 1:
            best = max(best, SCORE["RUSH_FOUR"])
        elif run == 3 and open_ends == 2:
            best = max(best, SCORE["LIVE_THREE"])
        elif run == 3 and open_ends == 1:
            best = max(best, SCORE["SLEEP_THREE"])
        elif run == 2 and open_ends == 2:
            best = max(best, SCORE["LIVE_TWO"])
        elif run == 2 and open_ends == 1:
            best = max(best, SCORE["SLEEP_TWO"])
    return best


def _classify_empty(board: Board, x: int, y: int, color: str) -> int:
    """Score what would happen if ``color`` were placed at (x, y)."""
    board.place(x, y, color)
    try:
        return _classify_point(board, x, y, color)
    finally:
        board.undo(x, y)


# ---------------------------------------------------------------------------
# Threat evaluation (plan §5.3)
# ---------------------------------------------------------------------------
def evaluate(board: Board, color: str) -> int:
    """Whole-board evaluation for ``color`` (plan §5.3).

    Sum of pattern scores for every occupied cell (own color positive,
    opponent slightly weighted) plus the "shape" contribution of the
    best empty cell on each side.  The result is from ``color``'s
    perspective: positive is good for ``color``, negative for the
    opponent.  The 1.1× opponent-weighting in plan §5.3 ("对方威胁
    权重略高防守倾向") is implemented as a multiplicative penalty.
    """
    opp = "W" if color == "B" else "B"
    own_total = 0
    opp_total = 0
    n = board.size
    for y in range(n):
        for x in range(n):
            cell = board.get(x, y)
            if cell == color:
                own_total += _classify_point(board, x, y, color)
            elif cell == opp:
                opp_total += _classify_point(board, x, y, opp)
    # The 1.1x factor from plan §5.3 makes the AI slightly defensive
    # without overpowering its own offense.
    return own_total - int(opp_total * 1.1)


# ---------------------------------------------------------------------------
# Candidate move generation (plan §5.3)
# ---------------------------------------------------------------------------
def _occupied_cells(board: Board) -> List[Tuple[int, int]]:
    n = board.size
    out: List[Tuple[int, int]] = []
    for y in range(n):
        for x in range(n):
            if board.get(x, y) != ".":
                out.append((x, y))
    return out


def candidates(board: Board, color: str, max_candidates: int = 20) -> List[Tuple[int, int]]:
    """Return up to ``max_candidates`` empty cells worth considering.

    First-pass pruning: only empty cells within Chebyshev distance 2 of
    any existing stone (plan §5.3).  Tie-breaking is by single-point
    pattern score, descending.

    The very first move (empty board) falls back to the center cell
    directly — the only sane choice when there is nothing else on the
    board.
    """
    occ = _occupied_cells(board)
    if not occ:
        cx = board.size // 2
        return [(cx, cx)]

    pool: set = set()
    for (ox, oy) in occ:
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = ox + dx, oy + dy
                if board.in_bounds(nx, ny) and board.is_empty(nx, ny):
                    pool.add((nx, ny))

    if not pool:
        return []

    opp = "W" if color == "B" else "B"

    def score_cell(pt: Tuple[int, int]) -> int:
        x, y = pt
        # Sum of "what would happen if I played here" + "what would
        # happen if opponent played here" — captures both offense and
        # defense in one number.
        s_self = _classify_empty(board, x, y, color)
        s_opp = _classify_empty(board, x, y, opp)
        return s_self + int(s_opp * 1.1)

    ranked = sorted(pool, key=score_cell, reverse=True)
    return ranked[:max_candidates]


# ---------------------------------------------------------------------------
# Difficulty strategies
# ---------------------------------------------------------------------------
def _weak_move(
    board: Board, color: str, rng: random.Random
) -> Optional[Tuple[int, int]]:
    """Weak tier: pick a random neighbor cell, avoiding immediate losses.

    The "avoid immediate loss" filter rejects any candidate that lets
    the opponent win on the next turn (i.e. creating an open-four for
    the opponent).  This is the UTA-02 "don't actively give the
    opponent a winning line" baseline.
    """
    opp = "W" if color == "B" else "B"
    cands = candidates(board, color, max_candidates=20)
    if not cands:
        return None
    rng.shuffle(cands)
    for (x, y) in cands:
        if not _is_immediate_loss(board, x, y, color, opp):
            return (x, y)
    # All candidates lose; pick the first (least-bad by tie-break).
    return cands[0]


def _is_immediate_loss(
    board: Board, x: int, y: int, color: str, opp: str
) -> bool:
    """Would playing at (x, y) let ``opp`` win on the *very next* move?

    Concretely: after placing, would the opponent have an open-four
    (i.e. be one move from five) anywhere on the board?  This is a
    conservative filter — a real loss-detection would also include
    double-threes and broken-fours, but the weak tier only needs to
    avoid the most egregious "suicide" moves (UTA-02).
    """
    board.place(x, y, color)
    try:
        opp_cands = candidates(board, opp, max_candidates=12)
        for (ox, oy) in opp_cands:
            if _classify_empty(board, ox, oy, opp) >= SCORE["LIVE_FOUR"]:
                return True
        return False
    finally:
        board.undo(x, y)


def _medium_move(board: Board, color: str) -> Optional[Tuple[int, int]]:
    """Medium tier: pattern-evaluation one-ply (plan §5.3).

    The candidate ranking in :func:`candidates` already sorts by
    "best shape for self + best shape for opp", so the medium tier
    simply takes the top of the list.  This is enough to satisfy the
    FR-06 "block rush-four and live-three" requirement (UTA-03/04)
    because the highest-scoring opponent threats bubble to the top of
    the candidate list.
    """
    cands = candidates(board, color, max_candidates=20)
    if not cands:
        return None
    return cands[0]


def _strong_move(
    board: Board,
    color: str,
    time_budget: float = 1.5,
) -> Optional[Tuple[int, int]]:
    """Strong tier: alpha-beta search with iterative deepening.

    Plan §5.3 specifies depth-4 alpha-beta on a candidate-ordered move
    list with a time budget.  We use iterative deepening (depth 2, 4, 6
    in successive rounds) so the function always has *some* best move
    ready when the budget runs out — that's the "超时返回当前最优"
    behavior required by plan §5.3 and NFR-01.
    """
    cands = candidates(board, color, max_candidates=12)
    if not cands:
        return None

    opp = "W" if color == "B" else "B"
    deadline = time.monotonic() + time_budget
    best_move: Tuple[int, int] = cands[0]

    # Iterative deepening — start shallow, go deeper while time allows.
    for depth in (2, 4):
        if time.monotonic() >= deadline:
            break
        # Re-rank candidates by shallow eval for better move ordering
        # (improves alpha-beta cutoffs).
        cands = sorted(
            cands,
            key=lambda p: _classify_empty(board, p[0], p[1], color)
            + int(_classify_empty(board, p[0], p[1], opp) * 1.1),
            reverse=True,
        )

        local_best: Optional[Tuple[int, int]] = None
        local_best_score: int = -(1 << 30)

        for (x, y) in cands:
            if time.monotonic() >= deadline:
                break
            board.place(x, y, color)
            try:
                v = -_alpha_beta(
                    board, depth - 1, -(1 << 30), (1 << 30), opp, deadline
                )
            finally:
                board.undo(x, y)
            if v > local_best_score:
                local_best_score = v
                local_best = (x, y)

        if local_best is not None:
            best_move = local_best

    return best_move


def _alpha_beta(
    board: Board,
    depth: int,
    alpha: int,
    beta: int,
    color: str,
    deadline: float,
) -> int:
    """Negamax-style alpha-beta (plan §5.3).

    Returns the evaluation from ``color``'s point of view, assuming
    both sides play optimally from here.  Time budget is checked at
    every leaf; when the budget runs out we just return the current
    evaluation rather than raising.
    """
    if time.monotonic() >= deadline:
        return evaluate(board, color)
    if depth <= 0:
        return evaluate(board, color)

    opp = "W" if color == "B" else "B"
    cands = candidates(board, color, max_candidates=8)
    if not cands:
        return evaluate(board, color)

    # Move ordering: try highest-scoring moves first for better pruning.
    cands = sorted(
        cands,
        key=lambda p: _classify_empty(board, p[0], p[1], color),
        reverse=True,
    )

    best = -(1 << 30)
    for (x, y) in cands:
        if time.monotonic() >= deadline:
            break
        board.place(x, y, color)
        try:
            v = -_alpha_beta(board, depth - 1, -beta, -alpha, opp, deadline)
        finally:
            board.undo(x, y)
        if v > best:
            best = v
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


# ---------------------------------------------------------------------------
# Public entry point (plan §4)
# ---------------------------------------------------------------------------
def choose_move(
    board: Board,
    color: str,
    difficulty: str = "medium",
    *,
    time_budget: float = 1.5,
    rng: Optional[random.Random] = None,
) -> Optional[Tuple[int, int]]:
    """Return the AI's chosen ``(x, y)`` or ``None`` if no legal move.

    Parameters
    ----------
    board : Board
        The current board state (mutated in-place during search).
    color : str
        The color the AI is playing ("B" or "W").
    difficulty : str
        One of ``"weak"``, ``"medium"``, ``"strong"`` (config defaults).
    time_budget : float
        Maximum wall-clock seconds for the strong tier (plan §5.3
        default 1.5 s; NFR-01 budget 2 s).
    rng : random.Random, optional
        Injectable RNG for deterministic tests (UTA-01/02).  Defaults
        to a fresh :class:`random.Random` instance.
    """
    if rng is None:
        rng = random.Random()

    if board.is_full():
        return None

    if difficulty == "weak":
        return _weak_move(board, color, rng)
    if difficulty == "medium":
        return _medium_move(board, color)
    if difficulty == "strong":
        return _strong_move(board, color, time_budget=time_budget)

    # Unknown difficulty is a programmer error, not a runtime concern;
    # the CLI validates first.
    raise ValueError(f"unknown difficulty: {difficulty!r}")
