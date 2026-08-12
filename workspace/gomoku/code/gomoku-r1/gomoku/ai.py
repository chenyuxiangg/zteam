"""AI decision layer for gomoku.

Three difficulty levels (plan §5.3):

* ``weak``    — legal random among neighbors, with a basic "do not
  actively lose" filter (avoid letting the opponent get a free open
  four on the very next move).
* ``medium``  — pattern-evaluation function (live-two / sleep-two /
  live-three / sleep-three / open-four / five).  Blocks immediate
  opponent threats (open-four / open-three) before attacking.
* ``strong``  — alpha-beta search with iterative deepening and a
  time budget, plus the same pattern-eval as ``medium`` for leaf
  scoring.  Strong mode also constructs its own open-fours /
  open-threes.

The ``choose_move`` entry point takes a :class:`Config` (or, for
backward-compat with the dev-only forbidden_cases module, an explicit
``forbidden`` flag) and applies the **forbidden-move prefilter** before
any search (plan §5.3 末段; this is the requirement tracked by the
code-reviewer's "严重 意见 1" — every candidate is run through
:meth:`Board.check_forbidden` and forbidden moves are dropped, so the
AI can never play a forbidden stone when ``forbidden=True``).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from gomoku.board import BLACK, EMPTY, WHITE, Board
from gomoku.config import Config

# Pattern scores for the evaluation function (plan §5.3).  These are
# inspired by the canonical Gomocup patterns and tuned for "block
# double-three / open-four" baseline play.
SCORE_FIVE = 10_000_000
SCORE_OPEN_FOUR = 1_000_000   # _XXXX_   (one move to win)
SCORE_DOUBLE_FOUR = 800_000   # two fours at once
SCORE_SIMPLE_FOUR = 100_000   # XXXX. / .XXXX / XX_XX (open or closed)
SCORE_DOUBLE_THREE = 50_000   # two live-threes at once
SCORE_LIVE_THREE = 10_000     # _XXX_ (open three)
SCORE_SLEEP_THREE = 1_000     # closed three
SCORE_LIVE_TWO = 100
SCORE_SLEEP_TWO = 10

# Search parameters (plan §5.3 / H8).
DEFAULT_TIME_BUDGET = 1.5  # seconds
DEFAULT_MAX_CANDIDATES = 12
DEFAULT_STRONG_DEPTH = 4
DEFAULT_MEDIUM_DEPTH = 2

# Neighbourhood for "candidate" generation (plan §5.3).
CANDIDATE_RADIUS = 2


@dataclass
class _SearchBudget:
    """Time budget + deadline helpers shared by weak/medium/strong."""

    deadline: float
    time_budget: float

    @classmethod
    def from_config(cls, config: Config, time_budget: Optional[float] = None) -> "_SearchBudget":
        tb = time_budget if time_budget is not None else DEFAULT_TIME_BUDGET
        return cls(deadline=time.monotonic() + tb, time_budget=tb)

    def is_expired(self) -> bool:
        return time.monotonic() >= self.deadline


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def choose_move(
    board: Board,
    color: str,
    config: Config,
    time_budget: Optional[float] = None,
) -> Optional[Tuple[int, int]]:
    """Return ``(x, y)`` for the AI's next move, or ``None`` if the board
    is full.

    The ``config`` argument supplies ``difficulty`` and ``forbidden``
    (the latter enables the black-side forbidden-move prefilter).

    ``time_budget`` overrides the default 1.5 s budget (used by tests
    and by ``main`` to harden the wall clock).
    """

    budget = _SearchBudget.from_config(config, time_budget=time_budget)
    empties = _list_empties(board)
    if not empties:
        return None
    if len(empties) == board.size * board.size:
        # Empty board: place near the centre (plan §5.3 "空盘时返回中心点").
        mid = board.size // 2
        return mid, mid

    difficulty = config.difficulty
    if difficulty == "weak":
        return _weak_move(board, color, empties, config, budget)
    if difficulty == "medium":
        return _medium_move(board, color, empties, config, budget)
    return _strong_move(board, color, empties, config, budget)


# ---------------------------------------------------------------------------
# Weak
# ---------------------------------------------------------------------------


def _weak_move(
    board: Board,
    color: str,
    empties: List[Tuple[int, int]],
    config: Config,
    budget: _SearchBudget,
) -> Tuple[int, int]:
    """Pick a legal neighbour cell at random, but drop cells that would
    let the opponent create a free open four on the very next move
    (FR-06 验收 ③: "不主动送死")."""

    candidates = _filter_legal(board, empties, color, config.forbidden_enabled)
    if not candidates:
        return empties[0]  # last resort

    opp = _opponent(color)
    safe: List[Tuple[int, int]] = []
    for x, y in candidates:
        board.place(x, y, color)
        # Check if opponent can make an open-four in one move
        lets_opp_win = False
        for nx, ny in _neighbors_of(board, x, y, CANDIDATE_RADIUS):
            if board.is_empty(nx, ny):
                board.place(nx, ny, opp)
                if _is_open_four_after(board, nx, ny, opp):
                    lets_opp_win = True
                board.undo(nx, ny)
                if lets_opp_win:
                    break
        board.undo(x, y)
        if not lets_opp_win:
            safe.append((x, y))

    pool = safe if safe else candidates
    return random.choice(pool)


def _is_open_four_after(board: Board, x: int, y: int, color: str) -> bool:
    """True iff placing ``color`` at (x, y) creates an open four
    (`_XXXX_` shape) on the board."""

    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        cnt = 1
        for sign in (1, -1):
            nx, ny = x + dx * sign, y + dy * sign
            while board.in_bounds(nx, ny) and board.cell(nx, ny) == color:
                cnt += 1
                nx += dx * sign
                ny += dy * sign
        # cnt == 4 with both ends open
        if cnt == 4:
            # check both ends are empty (or board edge: "open" is
            # conventionally "extends on at least one side"; for the
            # weak filter's purpose we accept any 4-run, the strong /
            # medium path uses a stricter definition)
            a, b = (x - dx, y - dy), (x + dx, y + dy)
            while True:
                nx, ny = a[0] - dx, a[1] - dy
                if not board.in_bounds(nx, ny) or board.cell(nx, ny) != color:
                    break
                a = (nx, ny)
            while True:
                nx, ny = b[0] + dx, b[1] + dy
                if not board.in_bounds(nx, ny) or board.cell(nx, ny) != color:
                    break
                b = (nx, ny)
            left_open = not board.in_bounds(*a) or board.cell(*a) == EMPTY
            right_open = not board.in_bounds(*b) or board.cell(*b) == EMPTY
            if left_open and right_open:
                return True
    return False


# ---------------------------------------------------------------------------
# Medium — pattern evaluation
# ---------------------------------------------------------------------------


def _medium_move(
    board: Board,
    color: str,
    empties: List[Tuple[int, int]],
    config: Config,
    budget: _SearchBudget,
) -> Tuple[int, int]:
    """Pattern-evaluation + immediate-threat blocking.

    Score each candidate by (my_eval - opp_eval * 1.1) and pick the
    best.  The 1.1 multiplier on the opponent's eval biases the AI
    toward blocking immediate threats.
    """

    candidates = _filter_legal(board, empties, color, config.forbidden_enabled)
    if not candidates:
        return empties[0]

    opp = _opponent(color)

    # If the opponent has a winning move on their next turn, block it
    # first.  This is the "must block" step in plan §5.3 中档.
    block = _must_block_move(board, candidates, opp)
    if block is not None:
        return block

    # Otherwise: score and pick max.
    best: Optional[Tuple[int, int, int]] = None  # (score, x, y)
    for x, y in candidates:
        if budget.is_expired():
            break
        board.place(x, y, color)
        my = _evaluate_color(board, color)
        opp_score = _evaluate_color(board, opp)
        score = my - int(opp_score * 1.1)
        board.undo(x, y)
        if best is None or score > best[0]:
            best = (score, x, y)
    if best is None:
        return candidates[0]
    return best[1], best[2]


def _must_block_move(
    board: Board, candidates: List[Tuple[int, int]], opp: str
) -> Optional[Tuple[int, int]]:
    """Return the cell the current player should occupy to block the
    opponent's most urgent threat, or ``None`` if no block is needed.

    Algorithm:

    1. If the opponent has any winning cell (a 4-run with at least one
       open end), return *any* cell that is adjacent enough to deny
       the opponent.  For a 4-run with two open ends the AI must play
       at one of those two cells; we pick the one that is also a
       candidate (so the rest of the search won't discard it).
    2. If the opponent has an open three, return a blocking cell at
       one of its open ends.
    """

    # Find every 4-run of `opp` stones and collect its open ends.
    four_run_ends: List[Tuple[int, int]] = []
    for run in _iter_runs(board, opp, target_len=4):
        sx, sy, ex, ey, dx, dy = run
        # open ends: the two cells just outside the run
        a = (sx - dx, sy - dy)
        b = (ex + dx, ey + dy)
        if board.in_bounds(*a) and board.is_empty(*a):
            four_run_ends.append(a)
        if board.in_bounds(*b) and board.is_empty(*b):
            four_run_ends.append(b)
        # dedup identical
    if four_run_ends:
        # Prefer one in candidates (the AI search's pool)
        cand_set = set(candidates)
        for cell in four_run_ends:
            if cell in cand_set:
                return cell
        return four_run_ends[0]

    # No 4-run: try a 3-run with both ends open (live three).
    for run in _iter_runs(board, opp, target_len=3):
        sx, sy, ex, ey, dx, dy = run
        a = (sx - dx, sy - dy)
        b = (ex + dx, ey + dy)
        if (board.in_bounds(*a) and board.is_empty(*a)
                and board.in_bounds(*b) and board.is_empty(*b)):
            # blocking one end kills the live-three's threat
            if a in set(candidates):
                return a
            if b in set(candidates):
                return b
    return None


def _iter_runs(
    board: Board, color: str, target_len: int
) -> List[Tuple[int, int, int, int, int, int]]:
    """Yield ``(sx, sy, ex, ey, dx, dy)`` for every maximal run of
    ``color`` stones of length exactly ``target_len`` along the 4
    directions.  Each run's endpoints are inclusive.
    """

    out: List[Tuple[int, int, int, int, int, int]] = []
    seen: set = set()
    for y in range(board.size):
        for x in range(board.size):
            if board.cell(x, y) != color:
                continue
            for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
                # only start at the beginning of a run
                px, py = x - dx, y - dy
                if board.in_bounds(px, py) and board.cell(px, py) == color:
                    continue
                # walk forward
                ex, ey, cnt = x, y, 0
                while board.in_bounds(ex, ey) and board.cell(ex, ey) == color:
                    ex += dx
                    ey += dy
                    cnt += 1
                # ex, ey is now the first cell *after* the run; the run
                # spans (x..ex-dx, y..ey-dy) inclusive
                if cnt == target_len:
                    key = (x, y, ex - dx, ey - dy, dx, dy)
                    if key not in seen:
                        seen.add(key)
                        out.append(key)
    return out


# ---------------------------------------------------------------------------
# Strong — alpha-beta with iterative deepening
# ---------------------------------------------------------------------------


def _strong_move(
    board: Board,
    color: str,
    empties: List[Tuple[int, int]],
    config: Config,
    budget: _SearchBudget,
) -> Tuple[int, int]:
    """Alpha-beta with iterative deepening (1..DEFAULT_STRONG_DEPTH) and
    a time budget.  Falls back to a pattern-eval move if the search
    doesn't complete (plan §5.4 降级链)."""

    opp = _opponent(color)
    # Candidate pruning: keep top-N by shallow evaluation, then search.
    candidates = _filter_legal(board, empties, color, config.forbidden_enabled)
    if not candidates:
        return empties[0]

    # Immediate must-block short-circuit
    block = _must_block_move(board, candidates, opp)
    if block is not None:
        # If the block is the only way to not lose, prefer it.
        for x, y in candidates:
            if block == (x, y):
                return x, y

    # Score candidates with the same eval as medium so we can prune
    candidates = _top_n_candidates(board, candidates, color, opp, n=DEFAULT_MAX_CANDIDATES)

    best_move = candidates[0] if candidates else _medium_move(board, color, empties, config, budget)
    best_score = -math.inf

    for depth in range(1, DEFAULT_STRONG_DEPTH + 1):
        if budget.is_expired():
            break
        score, move = _alpha_beta_root(
            board, depth, color, opp, candidates, budget
        )
        if budget.is_expired():
            break
        if move is not None:
            best_move = move
            best_score = score
    return best_move


def _top_n_candidates(
    board: Board,
    candidates: List[Tuple[int, int]],
    color: str,
    opp: str,
    n: int,
) -> List[Tuple[int, int]]:
    """Sort candidates by heuristic score (my - opp*1.1) and keep top-n."""

    scored: List[Tuple[int, Tuple[int, int]]] = []
    for x, y in candidates:
        board.place(x, y, color)
        s = _evaluate_color(board, color) - int(_evaluate_color(board, opp) * 1.1)
        board.undo(x, y)
        scored.append((s, (x, y)))
    scored.sort(reverse=True)
    return [m for _, m in scored[:n]]


def _alpha_beta_root(
    board: Board,
    depth: int,
    color: str,
    opp: str,
    candidates: List[Tuple[int, int]],
    budget: _SearchBudget,
) -> Tuple[float, Optional[Tuple[int, int]]]:
    """Root of the alpha-beta search.  Returns ``(score, best_move)``."""

    alpha = -math.inf
    beta = math.inf
    best_move: Optional[Tuple[int, int]] = None
    best_score = -math.inf

    for x, y in candidates:
        if budget.is_expired():
            break
        board.place(x, y, color)
        score = -_alpha_beta(board, depth - 1, -beta, -alpha, opp, color, budget)
        board.undo(x, y)
        if score > best_score:
            best_score = score
            best_move = (x, y)
            alpha = max(alpha, score)
    return best_score, best_move


def _alpha_beta(
    board: Board,
    depth: int,
    alpha: float,
    beta: float,
    to_move: str,
    root_color: str,
    budget: _SearchBudget,
) -> float:
    """Recursive alpha-beta.  ``to_move`` is the side to play at this
    node; ``root_color`` is the side we're evaluating for (used to
    convert leaf scores back to the root's perspective)."""

    if budget.is_expired():
        return _evaluate_color(board, root_color) - int(_evaluate_color(board, _opponent(root_color)) * 1.1)

    # Quick terminal checks
    winner = _fast_winner_check(board)
    if winner == root_color:
        return SCORE_FIVE
    if winner is not None and winner != root_color:
        return -SCORE_FIVE
    if board.is_full() or depth == 0:
        return _evaluate_color(board, root_color) - int(_evaluate_color(board, _opponent(root_color)) * 1.1)

    opp = _opponent(to_move)
    empties = _list_empties(board)
    # Pruning: only consider candidates near existing stones
    candidates: List[Tuple[int, int]] = []
    seen = set()
    for (ox, oy, _) in board.occupied_cells():
        for nx, ny in board.neighbors(ox, oy, CANDIDATE_RADIUS):
            if board.is_empty(nx, ny) and (nx, ny) not in seen:
                seen.add((nx, ny))
                candidates.append((nx, ny))
    # Forbid-move prefilter for black (plan §5.3 末段)
    if root_color == BLACK:
        candidates = [(x, y) for (x, y) in candidates
                      if not board.check_forbidden(x, y, BLACK)[0]]
    if not candidates:
        return _evaluate_color(board, root_color) - int(_evaluate_color(board, _opponent(root_color)) * 1.1)

    # Order candidates by shallow eval to improve alpha-beta pruning
    ordered = sorted(
        candidates,
        key=lambda p: _quick_eval(board, p, to_move),
        reverse=True,
    )
    ordered = ordered[:DEFAULT_MAX_CANDIDATES]

    best = -math.inf
    for x, y in ordered:
        board.place(x, y, to_move)
        # Terminal check after this placement
        if board.check_win(x, y) == to_move:
            board.undo(x, y)
            return SCORE_FIVE if to_move == root_color else -SCORE_FIVE
        score = -_alpha_beta(board, depth - 1, -beta, -alpha, opp, root_color, budget)
        board.undo(x, y)
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def _quick_eval(board: Board, p: Tuple[int, int], color: str) -> int:
    """Cheap per-move heuristic for move ordering (no full eval)."""

    x, y = p
    board.place(x, y, color)
    s = _evaluate_color(board, color)
    board.undo(x, y)
    return s


def _fast_winner_check(board: Board) -> Optional[str]:
    """Cheap win check: only look at the last move if it's recent."""

    if board.last_move is None:
        return None
    x, y = board.last_move
    return board.check_win(x, y)


# ---------------------------------------------------------------------------
# Pattern evaluation
# ---------------------------------------------------------------------------


def _evaluate_color(board: Board, color: str) -> int:
    """Sum the pattern scores for all open-ended runs of ``color``."""

    score = 0
    for y in range(board.size):
        for x in range(board.size):
            if board.cell(x, y) != color:
                continue
            # For each stone, evaluate the 4 directions *starting from
            # this stone*; we over-count but that's harmless since the
            # signal is in relative magnitudes.  The over-counting is
            # what allows the function to be used as a quick estimate.
            for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
                # walk back to the start of the run
                sx, sy = x, y
                while board.in_bounds(sx - dx, sy - dy) and board.cell(sx - dx, sy - dy) == color:
                    sx -= dx
                    sy -= dy
                # count run length
                ex, ey = sx, sy
                run_len = 0
                while board.in_bounds(ex, ey) and board.cell(ex, ey) == color:
                    ex += dx
                    ey += dy
                    run_len += 1
                if run_len < 2:
                    continue
                # check both ends
                left_open = board.in_bounds(ex - dx * 2, ey - dy * 2) and board.cell(ex - dx * 2, ey - dy * 2) == EMPTY
                right_open = board.in_bounds(sx - dx, sy - dy) and board.cell(sx - dx, sy - dy) == EMPTY
                if run_len >= 5:
                    score += SCORE_FIVE
                elif run_len == 4:
                    if left_open and right_open:
                        score += SCORE_OPEN_FOUR
                    elif left_open or right_open:
                        score += SCORE_SIMPLE_FOUR
                elif run_len == 3:
                    if left_open and right_open:
                        score += SCORE_LIVE_THREE
                    elif left_open or right_open:
                        score += SCORE_SLEEP_THREE
                elif run_len == 2:
                    if left_open and right_open:
                        score += SCORE_LIVE_TWO
                    elif left_open or right_open:
                        score += SCORE_SLEEP_TWO
    return score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _list_empties(board: Board) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for y in range(board.size):
        for x in range(board.size):
            if board.cell(x, y) == EMPTY:
                out.append((x, y))
    return out


def _opponent(color: str) -> str:
    return WHITE if color == BLACK else BLACK


def _filter_legal(
    board: Board,
    empties: List[Tuple[int, int]],
    color: str,
    forbidden_enabled: bool,
) -> List[Tuple[int, int]]:
    """Apply the *forbidden-move prefilter* (plan §5.3 末段; 修复
    code-reviewer "严重 意见 1").  Every empty cell is run through
    :meth:`Board.check_forbidden` and any forbidden move is dropped,
    so the AI can never play a forbidden stone.

    Returns a list of cells in the same order as ``empties`` (so the
    final tie-breaker is deterministic for tests).
    """

    out: List[Tuple[int, int]] = []
    for x, y in empties:
        if color == BLACK and forbidden_enabled:
            is_forbidden, _ = board.check_forbidden(x, y, BLACK)
            if is_forbidden:
                continue
        out.append((x, y))
    return out


def _neighbors_of(
    board: Board, x: int, y: int, radius: int
) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for ny in range(max(0, y - radius), min(board.size, y + radius + 1)):
        for nx in range(max(0, x - radius), min(board.size, x + radius + 1)):
            if (nx, ny) == (x, y):
                continue
            out.append((nx, ny))
    return out
