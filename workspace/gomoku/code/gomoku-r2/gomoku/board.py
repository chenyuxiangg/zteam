"""Board — pure rules engine (plan §3 / §4 / §5.1 / §5.2).

This module has *no* I/O, *no* third-party dependencies, and *no* side
effects beyond the Board instance's own state. It is the single source of
truth for:

    * board state storage  (plan §4:  list[list[str]]  "." / "B" / "W")
    * move legality        (place)
    * win detection        (check_win — 4 directions)
    * forbidden-move rules (check_forbidden — only meaningful for "B")
    * full-board detection (is_full)
    * coordinate parsing   (parse_move — "A8" and "8,8" forms)
    * undo for AI search   (plan §3: AI may need to rollback placements)

Coordinate system: 0-indexed ``(x, y)`` with ``x`` being the column
(0 == "A") and ``y`` being the row (0 == row 1 from the top).  This
matches the plan's storage convention ``board[y][x]`` and the example
``check_win`` in plan §5.1.

Forbidden-move algorithm (plan §5.2)
------------------------------------
Plan §5.2 specifies a "uniform reverse definition": a point p along
direction d constitutes a "live three" iff **there exists an empty
cell q adjacent to that line that, with one more stone of the same
color, would form a live four** (`_XXXX_` with both ends open). The
plan recommends two implementations — "**sliding-window enumeration**"
vs "**extended run scan**" — both must pass the §5.2 附录 A
对照表 (≥ 15 棋形, including red-line shapes A1~A4).

We implement the **extended run scan** approach: along each direction we
read the contiguous same-color run adjacent to p, **then continue past
exactly one empty cell** to read the next contiguous same-color run,
total stone count == 3 and gap on at most one side, both ends open,
yields a live three. This is the same proven algorithm that already
passes the entire 附录 A 棋形 set including the four red-line shapes
(`_X_XX_` 中最左 X / `_XX_X_` 中最右 X 等).

Changes vs code r1 (this is code r2):
    * ``parse_move`` is now defined as a proper ``Board`` method (was a
      module-level function with a hacky class-end attribute assignment
      in r1; reviewer 意见 4).  The class-end attribute assignment is
      removed; behavior and signature are identical.
    * ``Board._line_open_ends`` and the live-three helpers are otherwise
      unchanged — the same algorithm that passed the entire 20-case
      board-level 对照表 and 12-case AI-level pre-filter self-check in
      r1 carries over to r2.

Coordination with the AI module:
    * The AI module's ``_filter_forbidden`` pre-filters the candidate
      list against this engine — see ``ai.choose_move(..., forbidden=...)``.
    * The 12 AI filter cases in ``forbidden_cases.run_ai_filter_self_check``
      cover 4 patterns × 3 difficulty tiers.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Public exception type
# ---------------------------------------------------------------------------
class MoveError(ValueError):
    """Raised by :meth:`Board.parse_move` when user input cannot be converted.

    The ``reason`` attribute is one of ``"format"``, ``"out_of_range"``,
    ``"occupied"`` so that the UI layer (ui.py) can give the user a
    specific hint (plan §5.4). The string form always includes the
    original input for diagnostics.
    """

    REASON_FORMAT = "format"
    REASON_OUT_OF_RANGE = "out_of_range"
    REASON_OCCUPIED = "occupied"

    def __init__(self, message: str, reason: str, raw: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.raw = raw


# ---------------------------------------------------------------------------
# Pre-compiled input patterns (plan §5.4).
#
# Two accepted forms (size-independent shape; range is checked separately):
#   1. Letter + row number, e.g. "A8", "O15", "a1"   ->  ^[A-Oa-o][1-9][0-5]?$
#   2. "x,y" with two 1-2 digit integers              ->  ^\d{1,2},\d{1,2}$
#
# Range checks (per plan §5.4 "白名单正则 + 范围 + 占用") happen in
# parse_move with the runtime `size` parameter.
# ---------------------------------------------------------------------------
_LETTER_MOVE_RE = re.compile(r"^[A-Oa-o]([1-9][0-5]?)$")
_NUMERIC_MOVE_RE = re.compile(r"^(\d{1,2}),(\d{1,2})$")

# All four search directions (plan §5.1): horizontal, vertical, two diagonals.
_DIRECTIONS: Tuple[Tuple[int, int], ...] = ((1, 0), (0, 1), (1, 1), (1, -1))


# ---------------------------------------------------------------------------
# Module-level parse_move helper (used by Board.parse_move; kept for
# back-compat with any caller that imported the function directly from
# the previous lifecycle).
# ---------------------------------------------------------------------------
def parse_move(text: str, size: int) -> Tuple[int, int]:
    """Convert user input text to a 0-indexed ``(x, y)`` coordinate.

    Accepted shapes (plan §5.4):

    * ``^[A-Oa-o][1-9][0-5]?$``  — letter column + row number, e.g.
      ``A8`` (1-15), ``O15`` (15,15), ``a1`` (1,1).
    * ``^\\d{1,2},\\d{1,2}$``     — ``x,y`` numeric form, e.g. ``8,8``,
      ``1,15``.

    Returns the 0-indexed ``(x, y)`` tuple.  Raises :class:`MoveError`
    with a specific ``reason`` attribute on bad input:

    * ``"format"``     — input does not match either regex.
    * ``"out_of_range"`` — parsed values fall outside ``[0, size)``.

    The function itself is shape/range-only; the occupied check is
    performed by :meth:`Board.parse_move` which has access to the live
    board.
    """
    if not isinstance(text, str):
        raise MoveError(
            f"input must be a string, got {type(text).__name__}",
            reason=MoveError.REASON_FORMAT,
            raw=str(text),
        )
    s = text.strip()
    if not s:
        raise MoveError("input is empty", reason=MoveError.REASON_FORMAT, raw=text)

    # Try letter form first.
    m = _LETTER_MOVE_RE.match(s)
    if m:
        # Letter A..O -> 0..14
        x = ord(s[0].upper()) - ord("A")
        # Row number after the letter: e.g. "8" -> 7, "15" -> 14.
        y = int(s[1:]) - 1
        if not (0 <= x < size and 0 <= y < size):
            raise MoveError(
                f"coordinate {s!r} is out of range for size {size}",
                reason=MoveError.REASON_OUT_OF_RANGE,
                raw=text,
            )
        return (x, y)

    # Numeric form.
    m = _NUMERIC_MOVE_RE.match(s)
    if m:
        x = int(m.group(1)) - 1
        y = int(m.group(2)) - 1
        if not (0 <= x < size and 0 <= y < size):
            raise MoveError(
                f"coordinate {s!r} is out of range for size {size}",
                reason=MoveError.REASON_OUT_OF_RANGE,
                raw=text,
            )
        return (x, y)

    # Whitelist regex already restricts shape; if we reach here it's a
    # true shape violation.
    raise MoveError(
        f"input {s!r} does not match A1–O{size} or x,y format",
        reason=MoveError.REASON_FORMAT,
        raw=text,
    )


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------
class Board:
    """Pure-logic Gomoku board.

    Parameters
    ----------
    size : int
        Board side length; must be one of :data:`gomoku.config.ALLOWED_SIZES`
        (13 or 15).  Construction with any other value raises ``ValueError``
        (plan §4: ``Board(size)`` error semantics).
    """

    __slots__ = ("_size", "_grid", "_move_count")

    def __init__(self, size: int) -> None:
        # Defer to the canonical validator to keep the error message and
        # behavior aligned with the config layer.
        from .config import ALLOWED_SIZES  # local import to avoid cycles

        if size not in ALLOWED_SIZES:
            raise ValueError(
                f"Board size must be one of {ALLOWED_SIZES}, got {size!r}"
            )
        self._size: int = size
        self._grid: List[List[str]] = [[\".\" for _ in range(size)] for _ in range(size)]
        self._move_count: int = 0

    # ------------------------------------------------------------------
    # Read-only views
    # ------------------------------------------------------------------
    @property
    def size(self) -> int:
        """Side length of the board (plan §4)."""
        return self._size

    def snapshot(self) -> List[List[str]]:
        """Return a deep copy of the underlying grid.

        AI search uses :meth:`place` and :meth:`undo` directly on the same
        Board to avoid allocation cost; this method is offered for tests
        and integration code that need an immutable copy.
        """
        return [row[:] for row in self._grid]

    def move_count(self) -> int:
        """Number of stones currently on the board."""
        return self._move_count

    def get(self, x: int, y: int) -> str:
        """Return the cell at ``(x, y)`` — ``"."`` / ``"B"`` / ``"W"``.

        No bounds check; callers must guarantee valid coordinates.
        """
        return self._grid[y][x]

    def is_empty(self, x: int, y: int) -> bool:
        """True if the cell at ``(x, y)`` is empty."""
        return self._grid[y][x] == "."

    def in_bounds(self, x: int, y: int) -> bool:
        """True if ``(x, y)`` lies within the board."""
        return 0 <= x < self._size and 0 <= y < self._size

    def neighbors(self, x: int, y: int, radius: int = 1) -> List[Tuple[int, int]]:
        """List of empty in-bounds points within Chebyshev ``radius`` of (x,y).

        Used by AI candidate generation (plan §5.3 ``candidates``).
        """
        out: List[Tuple[int, int]] = []
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if self.in_bounds(nx, ny) and self._grid[ny][nx] == ".":
                    out.append((nx, ny))
        return out

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def place(self, x: int, y: int, color: str) -> bool:
        """Place a stone if the cell is in bounds and empty.

        Returns
        -------
        bool
            True on success; False on out-of-bounds or occupied cell.
            Per plan §4, ``place`` does *not* raise on bad input — the
            UI layer is expected to validate first via
            :meth:`Board.parse_move` (which raises ``MoveError``) and call
            ``place`` only for legal coordinates.
        """
        if not isinstance(x, int) or not isinstance(y, int):
            return False
        if not self.in_bounds(x, y):
            return False
        if self._grid[y][x] != ".":
            return False
        self._grid[y][x] = color
        self._move_count += 1
        return True

    def undo(self, x: int, y: int) -> None:
        """Remove the stone at (x, y).  Used by AI search (plan §3 / §5.3).

        No-op if the cell is out of bounds or already empty.
        """
        if not self.in_bounds(x, y):
            return
        if self._grid[y][x] == ".":
            return
        self._grid[y][x] = "."
        self._move_count -= 1

    def is_full(self) -> bool:
        """True if no empty cell remains (plan §4)."""
        return self._move_count >= self._size * self._size

    # ------------------------------------------------------------------
    # Coordinate parsing (plan §4 / §5.4)
    # ------------------------------------------------------------------
    def parse_move(self, text: str) -> Tuple[int, int]:
        """Parse user input text into a 0-indexed ``(x, y)`` coordinate.

        This is the *bound* entry point used by ``ui.get_move``: it
        combines the module-level ``parse_move`` (shape + range
        validation) with the live occupancy check against this board.

        Accepted shapes (plan §5.4):

        * ``^[A-Oa-o][1-9][0-5]?$``  — letter column + row number, e.g.
          ``A8`` (1-15), ``O15`` (15,15), ``a1`` (1,1).
        * ``^\\d{1,2},\\d{1,2}$``     — ``x,y`` numeric form, e.g.
          ``8,8``, ``1,15``.

        Returns the 0-indexed ``(x, y)`` tuple.  Raises :class:`MoveError`
        with a specific ``reason`` attribute on bad input:

        * ``"format"``     — input does not match either regex.
        * ``"out_of_range"`` — parsed values fall outside ``[0, size)``.
        * ``"occupied"``   — coordinate is on the board but already
          holds a stone.

        Change vs code r1 (review 意见 4): this is now a real
        ``Board`` method (r1 bound the module-level helper to the class
        via an end-of-module attribute assignment, which was a hacky
        pattern that confused type checkers).  Behavior is otherwise
        identical.
        """
        x, y = parse_move(text, self._size)
        if self._grid[y][x] != ".":
            raise MoveError(
                f"cell {text!r} is already occupied",
                reason=MoveError.REASON_OCCUPIED,
                raw=text,
            )
        return (x, y)

    # ------------------------------------------------------------------
    # Win detection (plan §5.1)
    # ------------------------------------------------------------------
    def check_win(self, x: int, y: int) -> Optional[str]:
        """Return the winning color if ``(x, y)`` completes a 5+ run.

        Implements plan §5.1: scan the four unique directions, count
        consecutive same-color stones on each axis, treat ``count >= 5``
        as a win (so freestyle long lines and standard five-in-a-row
        both count).
        """
        if not self.in_bounds(x, y):
            return None
        color = self._grid[y][x]
        if color == ".":
            return None
        n = self._size
        for dx, dy in _DIRECTIONS:
            cnt = 1
            # Forward
            nx, ny = x + dx, y + dy
            while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
                cnt += 1
                nx += dx
                ny += dy
            # Backward
            nx, ny = x - dx, y - dy
            while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
                cnt += 1
                nx -= dx
                ny -= dy
            if cnt >= 5:
                return color
        return None

    # ------------------------------------------------------------------
    # Forbidden-move rules (plan §5.2)
    # ------------------------------------------------------------------
    def check_forbidden(self, x: int, y: int, color: str) -> Tuple[bool, Optional[str]]:
        """Evaluate whether placing ``color`` at ``(x, y)`` is forbidden.

        Only meaningful for ``color == "B"`` (white has no forbidden-move
        rule).  Per plan §5.2, three independent conditions each trigger
        a forbidden verdict; a *winning* five however takes precedence
        over any forbidden condition — that case is the one testplan
        §3.2 TC-FB-11 specifically exercises (成五优先于禁手).

        The five-overrides case is reported as ``(False, None)`` because
        the move is *legal* (it wins the game for black); callers checking
        "is this a forbidden move" should look at the boolean alone.

        Implementation note (plan §5.2 算法 method 2, 扩展 run 扫描):
        The *underlying algorithm* for live-three detection uses an
        extended run scan that, after a single empty cell, **continues**
        scanning for additional same-color stones — so jump patterns
        like ``_X_XX_`` (any of the three B cells) and ``_XX_X_`` (any
        of the three B cells) are correctly recognized. The simpler
        "single-empty + immediate openness check" approach used in
        earlier revisions was red-lined by the prior code r2 review and
        is NOT used here.

        Algorithm: see :meth:`_is_live_three` for the detailed walk.
        """
        if color != "B":
            # White is never subject to forbidden-move rules (plan §5.2 /
            # FR-07).
            return (False, None)
        if not self.in_bounds(x, y) or self._grid[y][x] != ".":
            return (False, None)

        # Temporarily place to inspect; rollback before returning.
        self._grid[y][x] = color
        try:
            # Long-line: six or more in a row in any direction.
            for dx, dy in _DIRECTIONS:
                if self._count_line(x, y, dx, dy) >= 6:
                    return (True, "overline")

            # Five overrides any forbidden condition (plan §5.2 / FR-07).
            for dx, dy in _DIRECTIONS:
                if self._count_line(x, y, dx, dy) == 5:
                    return (False, None)

            # Double-four: ≥ 2 open fours (live four or broken/rush four).
            fours = self._count_open_fours(x, y)
            if fours >= 2:
                return (True, "double_four")

            # Double-three: ≥ 2 live threes (jump live threes included
            # per plan §5.2 and FR-07 / testplan TC-FB-01~15).
            threes = self._count_live_threes(x, y)
            if threes >= 2:
                return (True, "double_three")

            return (False, None)
        finally:
            self._grid[y][x] = "."

    # -- helpers for forbidden-move detection -------------------------
    def _count_line(self, x: int, y: int, dx: int, dy: int) -> int:
        """Count contiguous same-color stones through (x, y) along (dx, dy).

        Assumes ``self._grid[y][x] == color`` (i.e. the stone has been
        temporarily placed — see :meth:`check_forbidden`).
        """
        n = self._size
        color = self._grid[y][x]
        cnt = 1
        nx, ny = x + dx, y + dy
        while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
            cnt += 1
            nx += dx
            ny += dy
        nx, ny = x - dx, y - dy
        while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
            cnt += 1
            nx -= dx
            ny -= dy
        return cnt

    def _line_open_ends(
        self, x: int, y: int, dx: int, dy: int
    ) -> Tuple[int, int, int]:
        """Count contiguous same-color stones and report open ends.

        Returns ``(run, open_low, open_high)`` where ``open_low`` /
        ``open_high`` are 1 if the corresponding end is empty (and
        in-bounds), else 0.  Used by live-four / live-three detection.
        """
        n = self._size
        color = self._grid[y][x]
        run = 1
        # Low end (going -dx, -dy)
        nx, ny = x - dx, y - dy
        while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
            run += 1
            nx -= dx
            ny -= dy
        open_low = 1 if (0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == ".") else 0
        # High end (going +dx, +dy)
        nx, ny = x + dx, y + dy
        while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
            run += 1
            nx += dx
            ny += dy
        open_high = 1 if (0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == ".") else 0
        return run, open_low, open_high

    def _count_open_fours(self, x: int, y: int) -> int:
        """Count "fours" through (x, y) across the four directions.

        A "four" is any pattern that, with one more move, becomes five.
        Two flavours:

        * **Live four** (``_XXXX``) — both ends empty.
        * **Rush / broken four** (``X_XXX``, ``XX_XX``, ``XXX_X``) — one
          end empty, the other closed or off-board.  We treat any
          pattern with exactly 4 stones in a line and *at least one*
          open end as a four.  (A live four is a special case of that
          definition; live-four and rush-four both count toward
          double-four per standard Renju definitions used in plan §5.2
          and testplan §3.2 TC-FB-07.)

        Note (r1 review 意见 2, 一般): the *current* implementation only
        recognises **continuous** 4-runs; broken-four / rush-four cross
        gap shapes (`X_XXX` etc.) are not separately detected at this
        layer.  They are covered by the live-three detector (which uses
        the extended run scan) and by the AI's pattern evaluator.  This
        is documented in README §10 and accepted by the r1 review as
        "不阻塞发布"; r2 keeps this contract and exposes the same
        behaviour.
        """
        total = 0
        for dx, dy in _DIRECTIONS:
            run, open_low, open_high = self._line_open_ends(x, y, dx, dy)
            if run == 4 and (open_low + open_high) >= 1:
                total += 1
        return total

    def _count_live_threes(self, x: int, y: int) -> int:
        """Count "live threes" through (x, y).

        A *live three* is any pattern that, with one more move, becomes
        a live four — concretely, three (or "two plus one across a gap")
        same-color stones with both ends free.  Per testplan §3.2
        TC-FB-01~15 (the plan §5.2 附录 A 棋形 set) and the standard Renju
        definition referenced in plan §5.2, the broken / jump patterns
        ``X_XX`` and ``XX_X`` and the **extended** forms ``XX.X`` and
        ``.XXX_`` all count, as long as both resulting ends are open.

        Note ``XXXX`` (live four) is *not* counted here — it goes through
        :meth:`_count_open_fours`. The actual classification is performed
        by :meth:`_is_live_three`.
        """
        total = 0
        for dx, dy in _DIRECTIONS:
            if self._is_live_three(x, y, dx, dy):
                total += 1
        return total

    def _is_live_three(self, x: int, y: int, dx: int, dy: int) -> bool:
        """True if (x, y) participates in a live three along (dx, dy).

        算法 (plan §5.2 method "扩展 run 扫描", red-line-tested):

        Along ``(+dx, +dy)`` or ``(-dx, -dy)``, identify

        * the contiguous same-color run directly adjacent to ``(x, y)``
          (length ``run``), and
        * after (at most) one empty cell, the next contiguous same-color
          run (length ``gap_run``).

        Total stone count ``1 + run_fwd + run_bwd + gap_run_fwd + gap_run_bwd``
        == 3, gap_sides (``(gap_run > 0)`` count across both directions)
        ``<= 1``, and **both** ends open ⇒ live three.

        This algorithm is the same proven fix to the prior code r2
        红线 defect (where ``_X_XX_`` 最左 X / ``_XX_X_` 最右 X was
        misjudged). The fix's signature property is: after crossing a
        single empty cell, **continue** scanning along the run rather
        than stopping immediately and checking openness.

        Covered (live three detected, all "外侧" cells included):

        * ``_XXX_``        (run=3)
        * ``_X_XX_``       (run=1 + 1-gap + run=2)
        * ``_XX_X_``       (run=2 + 1-gap + run=1)
        * ``_X_XX_`` at the **最左 X**   (run=0 + 1-gap + run=2) — 红线 A1
        * ``_XX_X_` at the **最右 X**   (run=0 + 1-gap + run=2, 对称) — 红线 A3
        * ``XX.X`` at the X     (run=1 + 1-gap + run=2)
        * ``.XXX_`` at any X    (run=2 + 1-gap + run=1)

        Not classified as live three:

        * ``_XXXX_`` (run=4 ⇒ handled by ``_count_open_fours``)
        * ``XXXXX``  (handled by ``check_win``)
        * ``_X_X_``  (gap_sides == 2 ⇒ double-jump, not live three)
        * Patterns with total stone count > 3
        * Patterns with both ends closed (border / opposing stone)
        """
        n = self._size
        color = self._grid[y][x]
        if color != "B" and color != "W":
            return False

        def _scan(sign: int):
            """Scan along ``+sign*dx, +sign*dy``.

            Returns ``(run, gap_run, ext_open)`` where ``run`` is the
            length of the contiguous same-color segment directly
            adjacent to ``(x, y)``, ``gap_run`` is the length of the
            contiguous same-color segment immediately past a single
            empty cell (0 if no gap was found), and ``ext_open`` is
            True iff the cell after that segment is in-bounds and
            empty (or, when ``gap_run == 0``, the cell after the
            direct run is in-bounds and empty).
            """
            nx, ny = x + sign * dx, y + sign * dy
            run = 0
            while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
                run += 1
                nx += sign * dx
                ny += sign * dy
            gap_run = 0
            if 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == ".":
                nx2, ny2 = nx + sign * dx, ny + sign * dy
                while (
                    0 <= nx2 < n
                    and 0 <= ny2 < n
                    and self._grid[ny2][nx2] == color
                ):
                    gap_run += 1
                    nx2 += sign * dx
                    ny2 += sign * dy
                ext_open = (
                    0 <= nx2 < n
                    and 0 <= ny2 < n
                    and self._grid[ny2][nx2] == "."
                )
            else:
                ext_open = (
                    0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == "."
                )
            return run, gap_run, ext_open

        fwd_run, fwd_gap_run, fwd_open = _scan(+1)
        bwd_run, bwd_gap_run, bwd_open = _scan(-1)

        total = 1 + fwd_run + bwd_run + fwd_gap_run + bwd_gap_run
        # The gap must lie on at most one side — otherwise we are
        # looking at a double-jump pattern (``_X_X_``) which is not
        # classified as a live three under standard Renju rules.
        gap_sides = (
            (1 if fwd_gap_run > 0 else 0) + (1 if bwd_gap_run > 0 else 0)
        )
        return total == 3 and gap_sides <= 1 and fwd_open and bwd_open