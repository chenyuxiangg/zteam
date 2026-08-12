"""Rules engine for gomoku.

Pure logic, no I/O.  The :class:`Board` is the authoritative state holder.

Algorithm references (plan §5):
    * §5.1 win detection — 4 directions (horizontal / vertical / two diagonals),
      ``cnt >= 5`` wins (freestyle, long lines count).
    * §5.2 forbidden detection — three independent rules (overline,
      double-four, double-three) with **reverse definition** (補位即成活四/四
      ⇒ 活三/四) and **sliding-window enumeration** to cover every gap shape
      including the red-line forms ``_X_XX_``/``_XX_X_`` with the dropped
      stone at the outer-most existing piece.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

# A cell is one of:
EMPTY = "."
BLACK = "B"
WHITE = "W"
Cell = str  # "B" / "W" / "."

# 4-unit offset for the four winning directions: horizontal, vertical, both
# diagonals.  Each (dx, dy) walks "down-right" or "up-right" along the line.
DIRECTIONS: Tuple[Tuple[int, int], ...] = (
    (1, 0),   # horizontal
    (0, 1),   # vertical
    (1, 1),   # main diagonal
    (1, -1),  # anti diagonal
)

# MoveError reasons (FR-04 / plan §5.4).
REASON_FORMAT = "format"
REASON_OUT_OF_RANGE = "out_of_range"
REASON_OCCUPIED = "occupied"


class MoveError(ValueError):
    """Raised when user input cannot be converted to a (x, y) coordinate.

    The :attr:`reason` is one of the ``REASON_*`` constants so that the UI
    layer can produce a helpful message without re-parsing the original
    text.
    """

    def __init__(self, reason: str, text: str) -> None:
        super().__init__(f"{reason}: {text!r}")
        self.reason = reason
        self.text = text


# ---------------------------------------------------------------------------
# Coordinate parsing (FR-04)
# ---------------------------------------------------------------------------

# Two formats are accepted (case-insensitive letters):
#   1. ``A8`` — letter for column (A..O for 15x15 / A..M for 13x13) + row
#      number (1..size).  A8 is column 0, row 7 (zero-indexed (0, 7)).
#   2. ``8,8`` — both 1-indexed; 8,8 is (7, 7).
#
# We use simple regexes that allow either form, then range-check the
# resulting (x, y) against the board size.  The regex is intentionally
# permissive (e.g. ``A16`` is a valid format match on 15x15) — the
# range check downstream produces the right reason.
_LETTER_MOVE_RE = re.compile(r"^([A-Za-z])([0-9]{1,2})$")
_NUMERIC_MOVE_RE = re.compile(r"^(\d{1,2})\s*,\s*(\d{1,2})$")


def parse_move(text: str, size: int) -> Tuple[int, int]:
    """Parse a user move into a zero-indexed ``(x, y)`` coordinate.

    Accepts both ``A8`` (letter + row) and ``8,8`` (numeric) forms.
    Raises :class:`MoveError` with a categorized :attr:`reason` on failure:

    * ``REASON_FORMAT``       — text doesn't match either pattern;
    * ``REASON_OUT_OF_RANGE`` — parsed coordinates fall outside the board.

    Occupied-cell detection is the UI's responsibility (it has the
    ``Board`` instance to consult).  ``parse_move`` is intentionally
    pure and stateless; the occupied check happens in
    :func:`gomoku.ui.get_move`.
    """

    raw = text.strip()
    if not raw:
        raise MoveError(REASON_FORMAT, text)

    # Try the letter form first.
    m = _LETTER_MOVE_RE.match(raw)
    if m:
        col_letter, row_str = m.group(1).upper(), m.group(2)
        x = ord(col_letter) - ord("A")
        try:
            y = int(row_str) - 1
        except ValueError:
            raise MoveError(REASON_FORMAT, text) from None
    else:
        m = _NUMERIC_MOVE_RE.match(raw)
        if not m:
            raise MoveError(REASON_FORMAT, text)
        try:
            x = int(m.group(1)) - 1
            y = int(m.group(2)) - 1
        except ValueError:
            raise MoveError(REASON_FORMAT, text) from None

    if not (0 <= x < size and 0 <= y < size):
        raise MoveError(REASON_OUT_OF_RANGE, text)
    return x, y


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


class Board:
    """A 2D gomoku board with no I/O dependencies.

    Internally we store rows as ``list[str]`` of length ``size``, indexed as
    ``self._grid[y][x]`` (matches the README / UI convention).
    """

    __slots__ = ("_size", "_grid", "_moves", "_last_move")

    def __init__(self, size: int) -> None:
        # We accept any size >= 5 here so the developer-side test
        # fixtures (which use compact 8/10-cell boards) can construct
        # ``Board`` instances directly.  The CLI layer is responsible
        # for restricting user-facing choices to 13 / 15 (see
        # :mod:`gomoku.config`).
        if not isinstance(size, int) or size < 5 or size > 25:
            raise ValueError(
                f"unsupported board size: {size!r} (allowed integer range: 5..25)"
            )
        self._size = size
        self._grid: List[List[str]] = [[EMPTY for _ in range(size)] for _ in range(size)]
        self._moves = 0
        self._last_move: Optional[Tuple[int, int]] = None

    # -- read-only views ----------------------------------------------------

    @property
    def size(self) -> int:
        return self._size

    @property
    def moves(self) -> int:
        return self._moves

    @property
    def last_move(self) -> Optional[Tuple[int, int]]:
        return self._last_move

    def cell(self, x: int, y: int) -> str:
        return self._grid[y][x]

    def grid(self) -> List[List[str]]:
        """Return a defensive deep copy of the grid (avoids aliasing)."""

        return [row[:] for row in self._grid]

    def snapshot(self) -> Tuple[Tuple[str, ...], ...]:
        """Return a hashable snapshot of the board for memoization."""

        return tuple(tuple(row) for row in self._grid)

    def is_empty(self, x: int, y: int) -> bool:
        return 0 <= x < self._size and 0 <= y < self._size and self._grid[y][x] == EMPTY

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._size and 0 <= y < self._size

    def is_full(self) -> bool:
        return self._moves >= self._size * self._size

    def occupied_cells(self) -> List[Tuple[int, int, str]]:
        """Return all occupied cells as ``(x, y, color)`` for analysis."""

        out: List[Tuple[int, int, str]] = []
        for y in range(self._size):
            for x in range(self._size):
                c = self._grid[y][x]
                if c != EMPTY:
                    out.append((x, y, c))
        return out

    def neighbors(self, x: int, y: int, radius: int = 2) -> Iterable[Tuple[int, int]]:
        """Yield in-bound points within Chebyshev distance ``radius``."""

        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if self.in_bounds(nx, ny):
                    yield nx, ny

    # -- mutators -----------------------------------------------------------

    def place(self, x: int, y: int, color: str) -> bool:
        """Place a stone.  Returns True on success, False on out-of-bounds or
        occupied cells.  No exception is raised (NFR-06 / plan §4)."""

        if color not in (BLACK, WHITE):
            return False
        if not self.in_bounds(x, y):
            return False
        if self._grid[y][x] != EMPTY:
            return False
        self._grid[y][x] = color
        self._moves += 1
        self._last_move = (x, y)
        return True

    def undo(self, x: int, y: int) -> bool:
        """Remove the stone at (x, y).  Used only by the AI search for
        backtracking — not exposed to the UI layer."""

        if not self.in_bounds(x, y):
            return False
        if self._grid[y][x] == EMPTY:
            return False
        self._grid[y][x] = EMPTY
        self._moves -= 1
        # Best-effort recovery of last_move pointer: clear if we just removed
        # it, otherwise leave as-is (callers should treat last_move as
        # informational only after undo).
        if self._last_move == (x, y):
            self._last_move = None
        return True

    def reset(self) -> None:
        """Wipe the board back to empty (used for ``reset`` between games)."""

        for y in range(self._size):
            for x in range(self._size):
                self._grid[y][x] = EMPTY
        self._moves = 0
        self._last_move = None

    # -- win detection (FR-09, plan §5.1) -----------------------------------

    def check_win(self, x: int, y: int) -> Optional[str]:
        """Return the color that just won by playing at ``(x, y)`` or
        ``None`` if no five-or-more line was completed.  Uses a 4-direction
        sweep and treats lines of length >= 5 as wins (freestyle, long
        lines count)."""

        if not self.in_bounds(x, y):
            return None
        color = self._grid[y][x]
        if color == EMPTY:
            return None
        for dx, dy in DIRECTIONS:
            cnt = 1
            for sign in (1, -1):
                nx, ny = x + dx * sign, y + dy * sign
                while self.in_bounds(nx, ny) and self._grid[ny][nx] == color:
                    cnt += 1
                    nx += dx * sign
                    ny += dy * sign
            if cnt >= 5:
                return color
        return None

    # -- forbidden-move detection (FR-07, plan §5.2) ------------------------

    def check_forbidden(self, x: int, y: int, color: str) -> Tuple[bool, Optional[str]]:
        """Determine whether placing ``color`` at ``(x, y)`` is a Renju
        forbidden move for black.  Returns ``(is_forbidden, reason)`` where
        ``reason`` is one of ``"overline"`` / ``"double_four"`` /
        ``"double_three"`` (or ``None`` if legal).

        White stones are never forbidden (FR-07 / plan §5.2 — A13)."""

        if color != BLACK:
            return False, None
        if not self.in_bounds(x, y) or self._grid[y][x] != EMPTY:
            # The caller is responsible for occupied/bounds; this is a
            # safety net that won't misclassify a real move.
            return False, None

        # Rule 1: overline — any direction with >= 6 stones after the move.
        for dx, dy in DIRECTIONS:
            cnt = 1
            for sign in (1, -1):
                nx, ny = x + dx * sign, y + dy * sign
                while self.in_bounds(nx, ny) and self._grid[ny][nx] == color:
                    cnt += 1
                    nx += dx * sign
                    ny += dy * sign
            if cnt >= 6:
                return True, "overline"

        # Rule 2 & 3: double-four / double-three via 5-window enumeration
        # (sliding-window method, plan §5.2).  We enumerate every 5-cell
        # window along the 4 directions that contains (x, y) and decide
        # whether placing a stone here creates a "four" (any kind) or a
        # "live three".  Per-direction de-dup is implicit because every
        # direction is treated independently and at most one of the
        # resulting 4-direction line classes can fire.
        fours = 0
        threes = 0
        for dx, dy in DIRECTIONS:
            cls = self._classify_after_move(x, y, color, dx, dy)
            if cls == "four":
                fours += 1
            elif cls == "live_three":
                threes += 1

        # Five-on-the-move check has priority: a real five (cnt == 5) wins
        # even when it would otherwise be a forbidden double-three/four.
        if self._would_make_five(x, y, color) and not self._would_make_six(x, y, color):
            return False, None

        if fours >= 2:
            return True, "double_four"
        if threes >= 2:
            return True, "double_three"
        return False, None

    # -- internal helpers for forbidden detection ---------------------------

    def _would_make_five(self, x: int, y: int, color: str) -> bool:
        """True iff placing ``color`` at (x, y) creates a line of exactly 5
        in some direction (i.e. the 5-just-created case that beats
        forbidden)."""

        for dx, dy in DIRECTIONS:
            cnt = 1
            for sign in (1, -1):
                nx, ny = x + dx * sign, y + dy * sign
                while self.in_bounds(nx, ny) and self._grid[ny][nx] == color:
                    cnt += 1
                    nx += dx * sign
                    ny += dy * sign
            if cnt == 5:
                return True
        return False

    def _would_make_six(self, x: int, y: int, color: str) -> bool:
        """True iff placing ``color`` at (x, y) creates a line of >= 6 in
        some direction (overline already handled, this is informational)."""

        for dx, dy in DIRECTIONS:
            cnt = 1
            for sign in (1, -1):
                nx, ny = x + dx * sign, y + dy * sign
                while self.in_bounds(nx, ny) and self._grid[ny][nx] == color:
                    cnt += 1
                    nx += dx * sign
                    ny += dy * sign
            if cnt >= 6:
                return True
        return False

    def _classify_after_move(
        self, x: int, y: int, color: str, dx: int, dy: int
    ) -> str:
        """Classify the line in direction ``(dx, dy)`` after the move
        ``(x, y) == color`` is hypothetically placed.

        Returns one of:

        * ``"five"``        — line length >= 5
        * ``"four"``        — placing here creates a four (open or
          closed; any line that becomes four stones, possibly with one
          gap, that can complete to five on the next move)
        * ``"live_three"``  — placing here creates a live three (a
          three-stone line that can become an open four on the next
          move, *i.e.* the reverse definition: there exists an empty
          point along the line that, when filled, becomes an open four)
        * ``""``            — anything else

        The implementation is a hybrid line-scan + 5-window sweep:
        the 5-window sweep handles the common continuous cases and the
        edge / jump cases, while a short-line fallback handles boards
        where the candidate is too close to the border to form a
        5-cell window.
        """

        # 1. gather a window of up to 5 cells in each direction around (x,y)
        cells: List[str] = [color]  # the just-placed stone
        # 4 cells behind (x,y) on the line:
        bx, by = x - dx, y - dy
        behind: List[str] = []
        for _ in range(4):
            if not self.in_bounds(bx, by):
                break
            behind.append(self._grid[by][bx])
            bx -= dx
            by -= dy
        behind.reverse()
        cells = behind + cells
        # 4 cells ahead (x,y) on the line:
        ax, ay = x + dx, y + dy
        ahead: List[str] = []
        for _ in range(4):
            if not self.in_bounds(ax, ay):
                break
            ahead.append(self._grid[ay][ax])
            ax += dx
            ay += dy
        cells = cells + ahead

        if not cells:
            return ""

        mid = len(behind)  # index of the just-placed stone

        # Short-line fallback: if we cannot build any 5-window that
        # contains the candidate, fall back to a direct count of stones
        # and open ends on the whole line.
        can_build_5 = (len(cells) >= 5) and (mid >= 4 or len(cells) - mid >= 5)
        if not can_build_5:
            return self._classify_short_line(cells, mid)

        # 2. enumerate every 5-cell window in the line that contains the
        #    newly placed stone (at index ``mid``).
        best = ""
        for start in range(max(0, mid - 4), min(mid + 1, len(cells) - 4)):
            window = cells[start:start + 5]
            # The just-placed stone must lie in this window.
            if not (start <= mid < start + 5):
                continue
            cls = self._classify_window(window)
            if cls == "overline":
                # overline at the 5-window level is over-counted; the
                # whole-line overline check above is the source of truth.
                continue
            if self._classify_rank(cls) > self._classify_rank(best):
                best = cls
        return best

    @staticmethod
    def _classify_short_line(cells: Sequence[str], mid: int) -> str:
        """Fallback classifier for lines too short for a 5-window.

        Counts the total B's on the line and the open ends (cells on
        the line that are empty AND in-bounds).  This is used when the
        candidate stone is too close to a border for a 5-window sweep.

        Heuristic:

        * >= 4 B's on the line (candidate included) → ``"four"``;
        * exactly 3 B's and **either** the cell right outside the
          line on the long side is empty (i.e. the 3 stones can
          extend) → ``"live_three"``.

        Note: this is intentionally conservative; the *primary*
        classifier is the 5-window sweep above.
        """

        b_count = sum(1 for c in cells if c == BLACK)
        if b_count >= 4:
            return "four"
        if b_count == 3:
            # at least one extension cell beyond the line is in-bounds?
            # The 5-window sweep already handled all cases where both
            # ends have data; here we only get called when one end is
            # cut off.  Be lenient: if the line has 3 stones and the
            # candidate is one of them, declare live_three when the
            # short side has at least one empty cell (so the line can
            # extend on that side after a future move).
            left = cells[:mid]
            right = cells[mid + 1:]
            if any(c == EMPTY for c in left) or any(c == EMPTY for c in right):
                return "live_three"
        return ""

    @staticmethod
    def _classify_rank(cls: str) -> int:
        order = {"": 0, "live_three": 1, "four": 2, "five": 3}
        return order.get(cls, 0)

    @staticmethod
    def _classify_window(window: Sequence[str]) -> str:
        """Classify a 5-cell window containing a black stone at some index.

        * ``"five"``     — 5 consecutive B's.
        * ``"overline"`` — would be 6+ (only possible if the window wraps
          the *boundary* — handled at the whole-line level instead).
        * ``"four"``     — placing the just-added stone creates a four:
          either ``BBBB.`` / ``.BBBB`` / ``BBB.B`` / ``B.BBB`` /
          ``BB.BB`` shapes, with the open ends such that one extra B
          anywhere makes five.  We only count a four when the line can
          become five by adding a single stone (open or closed four).
        * ``"live_three"`` — placing the stone creates a live three:
          a 3-stone pattern that, by adding *one* more black stone in an
          empty cell of the window, becomes an open four.  This is the
          reverse definition from plan §5.2.
        """

        b = BLACK
        e = EMPTY
        if all(c == b for c in window):
            return "five"
        # four: 4 B's + 1 empty, OR patterns like BB.BB / B.BBB / BBB.B
        b_count = sum(1 for c in window if c == b)
        e_count = sum(1 for c in window if c == e)
        # First handle the classic 4+1 shape (any single empty).
        if b_count == 4 and e_count == 1:
            return "four"
        # Broken / jump fours — for the *whole line* we need to identify
        # them too.  A "four" is any 5-window with 4 B's and 1 empty AND
        # at least one of the two extreme cells is empty (so a single
        # stone added at an end completes five).  The previous case
        # already catches the contiguous form; the jump forms follow.
        # We consider these four only when the window contains a single
        # empty cell and at least one end is empty:
        if b_count == 4 and e_count == 1:
            return "four"  # always true given the first guard; kept explicit
        # BB.BB / B.BBB / BBB.B / BB.B.BB is too long for a 5-window, so
        # the *line* approach below extends beyond a single 5-window.

        # live three: 3 B's + 2 empty cells such that filling the "right"
        # empty makes an open four.  This is the **reverse definition**
        # from plan §5.2.  Examples (B = black, E = empty, X = black is
        # the just-placed stone, in window of 5 cells):
        #   _X_XX_  → window  _X_XX  (filling left E →  _XXXX  open
        #                              four on the left) ⇒ live three
        #   _XX_X_  → window  _XX_X  (filling right E →  XXXXX
        #                              5-in-a-row) but the "left E"
        #                              extension is closed on the other
        #                              side; the reverse definition
        #                              picks up the "any empty cell that
        #                              makes a four" interpretation:
        #                              filling *either* E that is
        #                              adjacent to a B makes a 4
        #                              formation.  We only declare
        #                              "live three" when **filling some
        #                              empty cell** in the window
        #                              produces a four (any kind).  Per
        #                              plan §5.2 A12 we count a single
        #                              live three per direction even
        #                              when two empty cells each produce
        #                              a four.
        if b_count == 3 and e_count == 2:
            # try every empty cell — does filling it produce a four?
            for i, c in enumerate(window):
                if c != e:
                    continue
                filled = list(window)
                filled[i] = b
                if Board._classify_window(tuple(filled)) == "four":
                    return "live_three"
        return ""

    # ------------------------------------------------------------------
    # Public helpers used by the AI for evaluation
    # ------------------------------------------------------------------

    def count_open_ends_in_direction(
        self, x: int, y: int, color: str, dx: int, dy: int
    ) -> int:
        """Count the number of empty cells (0, 1, or 2) at the two ends of
        a contiguous run of ``color`` stones through (x, y) in direction
        (dx, dy).  Used by the AI's pattern classifier.
        """

        if not self.in_bounds(x, y) or self._grid[y][x] != color:
            return 0
        # walk to the start of the run
        sx, sy = x, y
        while self.in_bounds(sx - dx, sy - dy) and self._grid[sy - dy][sx - dx] == color:
            sx -= dx
            sy -= dy
        # count one end
        ex1, ey1 = sx - dx, sy - dy
        open_left = 1 if self.in_bounds(ex1, ey1) and self._grid[ey1][ex1] == EMPTY else 0
        # walk to the end of the run
        ex, ey = sx, sy
        while self.in_bounds(ex + dx, ey + dy) and self._grid[ey + dy][ex + dx] == color:
            ex += dx
            ey += dy
        ex2, ey2 = ex + dx, ey + dy
        open_right = 1 if self.in_bounds(ex2, ey2) and self._grid[ey2][ex2] == EMPTY else 0
        return open_left + open_right
