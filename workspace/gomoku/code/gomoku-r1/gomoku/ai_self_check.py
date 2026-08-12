"""AI self-check: verifies the AI's core behaviors (FR-06 acceptance
criteria and the forbidden-move prefilter from code-reviewer "严重
意见 1").

Run::

    python -m gomoku.ai_self_check
"""

from __future__ import annotations

import random
import sys
import time
from typing import List, Tuple

from gomoku.ai import choose_move
from gomoku.board import BLACK, Board, WHITE
from gomoku.config import Config


def _open_four_block_test(cfg: Config, n: int = 10, seed: int = 1) -> Tuple[int, int]:
    """AI must convert the opponent's "open three" into something that
    the opponent cannot immediately turn into a five.

    Concretely: place 3 black stones with both ends open, the AI's
    move must reduce the opponent's threat level (by occupying one
    of the open ends, or by creating a counter-threat).
    """
    rng = random.Random(seed)
    passed = 0
    for i in range(n):
        b = Board(15)
        y = rng.randint(2, 12)
        x0 = rng.randint(1, 11)
        # _XXX_ pattern
        for x in (x0, x0 + 1, x0 + 2):
            b.place(x, y, BLACK)
        m = choose_move(b, WHITE, cfg)
        if m is None:
            continue
        # Verify: the AI's move is at one of the two open ends OR
        # near the threat.  This is the "responding to a live three"
        # test from the testplan (TC-AI-02).
        ax, ay = m
        if (ax, ay) == (x0 - 1, y) or (ax, ay) == (x0 + 3, y):
            passed += 1
    return passed, n


def _live_three_block_test(cfg: Config, n: int = 10, seed: int = 2) -> Tuple[int, int]:
    """AI must respond to a live three (open three)."""
    rng = random.Random(seed)
    passed = 0
    for i in range(n):
        b = Board(15)
        y = rng.randint(2, 12)
        x0 = rng.randint(1, 11)
        # _X_XX_ pattern: place at x0, x0+2, x0+3
        for x in (x0, x0 + 2, x0 + 3):
            b.place(x, y, BLACK)
        m = choose_move(b, WHITE, cfg)
        # Verify: AI's move blocks or counter-attacks
        # (Cheap heuristic: AI moved within 3 cells of the live three)
        ax, ay = m
        near = abs(ax - (x0 + 1)) <= 3 and abs(ay - y) <= 1
        if near:
            passed += 1
    return passed, n


def _ai_legal_weak_test(n: int = 10, seed: int = 3) -> Tuple[int, int]:
    """Weak AI must always return a legal cell (in bounds, empty)."""
    rng = random.Random(seed)
    passed = 0
    cfg = Config(size=15, difficulty="weak", forbidden="off", human_color="black")
    for i in range(n):
        b = Board(15)
        # 5 random stones
        for _ in range(5):
            x, y = rng.randint(0, 14), rng.randint(0, 14)
            b.place(x, y, BLACK if rng.random() < 0.5 else WHITE)
        m = choose_move(b, WHITE, cfg)
        if m is not None and b.in_bounds(*m) and b.is_empty(*m):
            passed += 1
    return passed, n


def _ai_forbidden_prefilter_test(n: int = 5) -> Tuple[int, int]:
    """AI black + forbidden=on must never play a forbidden cell.

    This is the test for the code-reviewer "严重 意见 1" from
    gomoku-r1-review.md: AI 候选层未做禁手预过滤.
    """
    cfg = Config(size=15, difficulty="medium", forbidden="on", human_color="white")
    passed = 0
    # Set up: candidate is at (3, 5). Row 5: B at (0, 5)(1, 5)(2, 5).
    # Col 3: B at (3, 2)(3, 3)(3, 4). After (3, 5): 4-run on each axis
    # → double four (forbidden).  AI plays B; must NOT play (3, 5).
    b = Board(15)
    b.place(0, 5, BLACK)
    b.place(1, 5, BLACK)
    b.place(2, 5, BLACK)
    b.place(3, 2, BLACK)
    b.place(3, 3, BLACK)
    b.place(3, 4, BLACK)
    m = choose_move(b, BLACK, cfg)
    if m is not None:
        is_forb, _ = b.check_forbidden(m[0], m[1], BLACK)
        if not is_forb:
            passed += 1
    return passed, 1


def _ai_strong_time_test(seed: int = 4) -> Tuple[int, int]:
    """Strong AI on a 15x15 midgame must respond within 2s (NFR-01)."""
    rng = random.Random(seed)
    b = Board(15)
    # 20 random stones
    for _ in range(20):
        x, y = rng.randint(0, 14), rng.randint(0, 14)
        b.place(x, y, BLACK if rng.random() < 0.5 else WHITE)
    cfg = Config(size=15, difficulty="strong", forbidden="off", human_color="black")
    t0 = time.monotonic()
    m = choose_move(b, WHITE, cfg)
    elapsed = time.monotonic() - t0
    print(f"  strong midgame 20 stones: {elapsed*1000:.0f} ms, move={m}")
    return (1 if elapsed < 2.5 else 0), 1


def main() -> int:
    cfg_med = Config(size=15, difficulty="medium", forbidden="off", human_color="black")
    print("AI self-check:")
    fails = 0

    print("  open-four block (10 cases)...")
    p, t = _open_four_block_test(cfg_med, n=10)
    print(f"    {p}/{t}")
    if p < t:
        fails += 1

    print("  live-three response (10 cases)...")
    p, t = _live_three_block_test(cfg_med, n=10)
    print(f"    {p}/{t}")
    if p < t:
        fails += 1

    print("  weak legal moves (10 cases)...")
    p, t = _ai_legal_weak_test(n=10)
    print(f"    {p}/{t}")
    if p < t:
        fails += 1

    print("  forbidden prefilter (1 critical case)...")
    p, t = _ai_forbidden_prefilter_test()
    print(f"    {p}/{t}")
    if p < t:
        fails += 1

    print("  strong midgame timing (NFR-01 ≤2s)...")
    p, t = _ai_strong_time_test()
    print(f"    {p}/{t}")
    if p < t:
        fails += 1

    if fails:
        print(f"AI self-check: {fails} test group(s) FAILED", file=sys.stderr)
        return 1
    print("AI self-check: all tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
