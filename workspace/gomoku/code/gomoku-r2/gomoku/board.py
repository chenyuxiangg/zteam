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
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Public exception type
# ---------------------------------------------------------------------------
class MoveError(ValueError):
    """Raised by :func:`parse_move` when user input cannot be converted.

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
# Two accepted forms:
#   1. Letter + row number, e.g. "A8", "O15", "a1"   ->  ^[A-Oa-o][1-9][0-5]?$
#   2. "x,y" with two 1-2 digit integers              ->  ^\d{1,2},\d{1,2}$
#
# Range checks happen separately in parse_move (size is a runtime
# parameter), so the regex only constrains the *shape*.
# ---------------------------------------------------------------------------
_LETTER_MOVE_RE = re.compile(r"^[A-Oa-o]([1-9][0-5]?)$")
_NUMERIC_MOVE_RE = re.compile(r"^(\d{1,2}),(\d{1,2})$")

# All four search directions (plan §5.1): horizontal, vertical, two diagonals.
_DIRECTIONS: Tuple[Tuple[int, int], ...] = ((1, 0), (0, 1), (1, 1), (1, -1))


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
        self._grid: List[List[str]] = [["." for _ in range(size)] for _ in range(size)]
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
            :meth:`parse_move` (which raises ``MoveError``) and call
            ``place`` only for legal coordinates.  Robustness test
            ``UTB-27`` requires no exception on out-of-range input.
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
    # Win detection (plan §5.1)
    # ------------------------------------------------------------------
    def check_win(self, x: int, y: int) -> Optional[str]:
        """Return the winning color if ``(x, y)`` completes a 5+ run.

        Implements plan §5.1: scan the four unique directions, count
        consecutive same-color stones on each axis, treat ``count >= 5``
        as a win (so freestyle long lines and standard five-in-a-row
        both count — see UTB-23 / plan §8 "freestyle" mode).

        Returns ``None`` when the last move does not win.  ``x``/``y``
        must reference the *just-played* cell; the function does not
        verify a stone is present there.
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
        over any forbidden condition (``reason="five_overrides"``) — that
        case is the one UTB-13 specifically exercises.

        The "five-overrides" return value is reported as
        ``(False, None)`` because the move is *legal* (it wins the game
        for black); callers checking "is this a forbidden move" should
        look at the boolean alone.
        """
        if color != "B":
            # White is never subject to forbidden-move rules (plan §5.2,
            # UTB-14).
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

            # Five overrides any forbidden condition (plan §5.2 / UTB-13).
            for dx, dy in _DIRECTIONS:
                if self._count_line(x, y, dx, dy) == 5:
                    return (False, None)

            # Double-four: ≥ 2 open fours (live four or broken/rush four).
            fours = self._count_open_fours(x, y)
            if fours >= 2:
                return (True, "double_four")

            # Double-three: ≥ 2 live threes (including "jump" live three
            # patterns per plan §5.2 and UTB-15).
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
          and UTB-11.)
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
        same-color stones with both ends free.  Per UTB-15 and the
        standard Renju definition referenced in plan §5.2, the broken /
        jump patterns ``X_XX`` and ``XX_X`` and the **extended** forms
        ``XX.X`` and ``.XXX_`` all count, as long as both resulting
        ends are open.  The actual classification is performed by
        :meth:`_is_live_three` (r2 rewrite — see its docstring for the
        full algorithm and r1 vs r2 difference).
        """
        total = 0
        for dx, dy in _DIRECTIONS:
            if self._is_live_three(x, y, dx, dy):
                total += 1
        return total

    def _is_live_three(self, x: int, y: int, dx: int, dy: int) -> bool:
        """True if (x, y) participates in a live three along (dx, dy).

        **r2 修复**（code-reviewer 评审 r1 意见 1）：r1 使用固定 5 窗模式
        匹配 `[0,1,1,1,0] / [1,0,1,1,0] / [0,1,1,0,1]`，漏算"前方已
        延伸"的活三形态（如 `..XXX_`、`XX.X` 落在 X 处等）。新算法改
        为**沿 (dx,dy) 方向识别"连续段 + 单空延伸"**：先沿方向延伸
        找连续同色 run，再允许越过 1 个空位继续延伸 1 个同色 stone，
        只要总 stone 数 == 3 且两端均开放即判为活三（与 `_line_open_ends`
        和 `_count_open_fours` 的语义对齐——参考 plan §5.2 的方向扫描
        归类）。

        覆盖所有标准 Renju 活三形态：

        * `_XXX_`（run=3，两端开）
        * `_X_XX_`（run=1+1+1，含跳延伸）
        * `_XX_X_`（run=2+1，含跳延伸）
        * `XX.X`（落 X 处，run=1+2 含单空延伸）—— r1 漏判
        * `.XXX_` 落在 X 处（run=2+1 含单空延伸）—— r1 漏判

        不算活三的形态（r2 同步纠正）：

        * `_XXXX_`（run=4 → 活四，归双四判定）
        * `XX.X.`（一端被堵 → 冲三）
        * `XXXXX`（run=5 → 已成五，由 check_win 处理）
        """
        n = self._size
        color = self._grid[y][x]
        if color != "B" and color != "W":
            return False

        # Forward (along +dx, +dy)
        forward_run = 0
        nx, ny = x + dx, y + dy
        while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
            forward_run += 1
            nx += dx
            ny += dy
        # nx, ny now points to the cell just after the run (empty/opp/oob)
        forward_ext = 0
        if 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == ".":
            # Skip one empty cell, look for one more same-color stone.
            nx2, ny2 = nx + dx, ny + dy
            if 0 <= nx2 < n and 0 <= ny2 < n and self._grid[ny2][nx2] == color:
                forward_ext = 1
                nx, ny = nx2, ny2
        # forward end open?
        if forward_ext == 1:
            nx2, ny2 = nx + dx, ny + dy
            fwd_open = (0 <= nx2 < n and 0 <= ny2 < n and self._grid[ny2][nx2] == ".")
        else:
            fwd_open = (0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == ".")

        # Backward (along -dx, -dy)
        backward_run = 0
        nx, ny = x - dx, y - dy
        while 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == color:
            backward_run += 1
            nx -= dx
            ny -= dy
        backward_ext = 0
        if 0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == ".":
            nx2, ny2 = nx - dx, ny - dy
            if 0 <= nx2 < n and 0 <= ny2 < n and self._grid[ny2][nx2] == color:
                backward_ext = 1
                nx, ny = nx2, ny2
        if backward_ext == 1:
            nx2, ny2 = nx - dx, ny - dy
            bwd_open = (0 <= nx2 < n and 0 <= ny2 < n and self._grid[ny2][nx2] == ".")
        else:
            bwd_open = (0 <= nx < n and 0 <= ny < n and self._grid[ny][nx] == ".")

        total = 1 + forward_run + backward_run + forward_ext + backward_ext
        return total == 3 and fwd_open and bwd_open


# ---------------------------------------------------------------------------
# Coordinate parsing (plan §4 / §5.4)
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
    * ``"occupied"``   — coordinate is on the board but already holds a
      stone (caller passes the live board; for shape/range checks alone,
      pass any board and the shape/RangeError will fire first).

    The function itself is shape/range-only; the occupied check is
    performed by :meth:`Board.parse_move` (see below) which has access
    to the live board.
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


# Bound method that combines shape/range parsing with occupancy check.
def _board_parse_move(self: "Board", text: str) -> Tuple[int, int]:
    """Bound method on Board — adds the occupied check to parse_move."""
    x, y = parse_move(text, self._size)
    if self._grid[y][x] != ".":
        raise MoveError(
            f"cell {text!r} is already occupied",
            reason=MoveError.REASON_OCCUPIED,
            raw=text,
        )
    return (x, y)


# Attach the bound method to the class (keeps Board single-source).
Board.parse_move = _board_parse_move  # type: ignore[attr-defined]
