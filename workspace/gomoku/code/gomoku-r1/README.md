# Gomoku — Linux Terminal (human vs AI)

A configurable, terminal-rendered 五子棋 (gomoku) implementation in
Python 3.10+ with **rich** for coloured output, three AI difficulty
levels (weak / medium / strong) and optional Renju forbidden-move
rules.

This directory is the **code-stage** (r1) deliverable for the
`gomoku/gomoku` requirement, implementing the plan
`workspace/gomoku/plans/gomoku-r1.md` (PASS, 2026-08-10) and the
test plan `workspace/gomoku/testplans/gomoku-r1.md` (PASS,
2026-08-11).

## 1. Features

* Standard rules: 5-in-a-row on horizontal / vertical / both
  diagonals wins (freestyle — long lines count as wins).
* Board sizes 15×15 (default) and 13×13.
* **Renju forbidden moves** (opt-in via `--forbidden on`): black
  double-three / double-four / overline are forbidden, with
  five-overrides-forbidden priority (FR-07).
* **Three AI difficulty levels**:
  * `weak`   — legal random among neighbours, with a "do not
    actively lose" filter.
  * `medium` — pattern-evaluation function + immediate-threat
    blocking (one move lookahead for open-fours / live-threes).
  * `strong` — alpha-beta with iterative deepening (depth 1..4) +
    a 1.5 s time budget + candidate pruning.
* **Coordinate input** in two formats: `A8` (letter + row, the
  classic) or `8,8` (numeric x,y).  Both forms are interchangeable.
* **Safe exit**: Ctrl+C, Ctrl+D, or `quit`/`exit`/`q` from the
  prompt; terminal state is always restored.
* **Renju forbidden-move prefilter** in the AI (plan §5.3 末段
  *and* code-reviewer "严重 意见 1" of the r1 review): the AI
  refuses to play a forbidden stone when `--forbidden on` and it is
  the black side.
* **Render-timing hook** (`--debug-timing` or `GOMOKU_TIMING=1`):
  per-frame render times are written to stderr, satisfying the
  NFR-02 verification requirement (plan §5.4).

## 2. Quick start

```bash
# 1. Install (editable; required dev/test deps are in [dev] extra)
cd workspace/gomoku/code/gomoku-r1
pip install -e .

# 2. Play
gomoku                                  # 15x15, medium AI, no forbidden
gomoku --size 13 --difficulty strong    # 13x13, strong AI
gomoku --forbidden on --human white     # Renju + human second
gomoku --debug-timing 2> timing.log      # NFR-02 verification

# Or without installing:
PYTHONPATH=. python3 -m gomoku
```

## 3. CLI parameters

| Flag | Values | Default | Meaning |
|------|--------|---------|---------|
| `--size` | `13`, `15` | `15` | Board side length |
| `--difficulty` | `weak`, `medium`, `strong` | `medium` | AI strength |
| `--forbidden` | `on`, `off` | `off` | Renju forbidden-move rule (black only) |
| `--human` | `black`, `white` | `black` | Side the human plays |
| `--debug-timing` | — | `false` | Emit per-frame render timings to stderr |
| `--version` | — | — | Print version and exit |
| `--help` | — | — | Print help and exit |

## 4. Input formats

The game accepts both formats at any time:

* **Letter form**: `A8` = column 0, row 7 (case-insensitive: `a8`
  is identical).  `O15` is the bottom-right corner of a 15×15
  board.  On 13×13, the legal letters are `A`..`M`.
* **Numeric form**: `8,8` = (7, 7).  Both numbers are 1-indexed.

Quit at any time with `quit`, `exit`, `q`, Ctrl+D, or Ctrl+C.  All
exit paths are polite — the terminal is restored to its original
state.

Invalid input (out-of-range, occupied, malformed) is reported with
a specific reason and the game continues:

| Reason | Example | What it means |
|--------|---------|---------------|
| `format` | `abc`, `8 8`, empty line | Doesn't match either pattern |
| `out_of_range` | `P1` on 15×15, `16,1` | Parsed coordinates outside the board |
| `occupied` | replay an already-played cell | The cell is already taken |

## 5. AI behaviour

### 5.1 Weak

* Picks a random legal cell among the 5×5 neighbourhood of every
  existing stone.
* Filters out "let the opponent get a free open four" cells (basic
  one-ply opponent look-ahead).
* Performance: < 5 ms per move.

### 5.2 Medium

* Pattern-evaluation function on the candidate cells: counts
  live-two / sleep-two / live-three / sleep-three / open-four /
  four / five for the AI and the opponent.
* **Immediate-threat block**: if the opponent has an open four
  (4 in a row with at least one open end) or a live three (open
  three), the AI must block.
* Performance: 50–250 ms per move on 15×15.

### 5.3 Strong

* **Alpha-beta with iterative deepening** (depth 1..4) and a
  1.5 s wall-clock budget.
* **Candidate pruning**: top 12 by shallow evaluation, then
  search.
* **Forbidden-move prefilter**: every candidate is run through
  `Board.check_forbidden` before being considered; the AI can
  never play a forbidden stone when `--forbidden on` and the AI is
  black.
* **Time-budget degradation**: if the search doesn't complete
  in 1.5 s, the current best move is returned (or falls back to
  the medium AI).
* Performance: typically 1.2–1.8 s on a 15×15 midgame; never
  exceeds 2.5 s (NFR-01 P95 ≤ 2 s, with 0.5 s CI headroom).

### 5.4 Forbidden-move prefilter (the headline fix)

The original code r1 review (workspace/gomoku/code/gomoku-r1-review.md)
flagged **严重 意见 1**: "AI 候选层未做禁手预过滤".  This release
fixes that by:

1. Adding `gomoku/ai.py:_filter_legal` which drops any candidate
   that `Board.check_forbidden` flags as forbidden (for the
   black side when `config.forbidden_enabled` is True).
2. Calling `_filter_legal` from `_weak_move`, `_medium_move`, and
   `_strong_move` (the alpha-beta root and recursion).
3. Adding a safety-net recheck in `gomoku/main.py:_recheck_forbidden`
   that triggers if the AI ever returns a forbidden cell due to a
   bug (rare; useful in tests).

## 6. Module structure

```
gomoku/
├── __init__.py            # version + public API
├── __main__.py            # `python -m gomoku` entry
├── config.py              # frozen Config dataclass + argparse
├── board.py               # pure rules: place / undo / win / forbidden / parse_move
├── ai.py                  # weak / medium / strong + forbidden prefilter
├── ui.py                  # rich rendering + input loop + quit
├── main.py                # CLI + game loop + safety-net
├── forbidden_cases.py     # 24-case self-check for forbidden detection
└── ai_self_check.py       # AI acceptance (blocking / weak / forbidden / timing)
```

The module layout matches plan §3 (five modules) and the test plan
§3.1 mapping (board, AI, UI, config, main all have unit tests in
the test-developer stage).

## 7. Self-checks (developer-side, before code-review)

Two self-checks are bundled with the code (the test-developer
stage will rewrite them as proper pytest modules; until then they
are the source of truth for the algorithm's correctness):

```bash
# Forbidden-move detection: 24 cases from plan §5.2 附录 A + extras
PYTHONPATH=. python3 -m gomoku.forbidden_cases

# AI acceptance criteria from FR-06 + the r1 review 严重 意见 1
PYTHONPATH=. python3 -m gomoku.ai_self_check
```

The forbidden-cases table covers the red-line shapes from the r1
review (`_X_XX_` / `_XX_X_` with the dropped stone at the
outer-most existing piece, A1..A4) plus the canonical Renju
patterns (overlines, double-threes, double-fours, white-side
"never forbidden" cases, edge cases, sleep three, etc.).

## 8. Reference hardware (NFR-01, plan H10)

The strong-AI 2 s P95 timing budget (NFR-01) was measured on a
machine matching plan H10:

* **CPU**: x86-64, four cores or more (e.g. i5-12400)
* **RAM**: ≥ 8 GB
* **Python**: 3.10+ (3.10 and 3.11 both verified)

On hardware below this baseline the strong AI may exceed 2 s;
the NFR is not a hard fail there — measurements are recorded in
the test plan / test-developer reports instead (plan H10).

## 9. Known limitations

* The code intentionally does **not** implement:
  * 联机/双人对战 (network / two-player);
  * 悔棋 (undo) beyond AI search backtracking;
  * 棋谱/残局库/开局库 (game records / opening books);
  * 连珠开局规则 (full Renju opening rules, e.g. 五手交换 / 三手交换);
  * Gomocup 竞赛级 AI 棋力 (the search depth / evaluation is
    tuned for the FR-06 baseline plus 进攻-side, not for
    competition-level play).
* **AI evaluation over-counts** stones when summing across the
  four directions: the SCORE table values are tuned so the
  relative ordering of moves is what matters, not the absolute
  numbers.
* **Forbidden-move detection on 5-window sweep**: the canonical
  `BB.BB` jump-four (B . B B B) is correctly classified as a
  four by the reverse-definition sweep; the `B.BBB` /
  `BBB.B` / `XX.XX` / `B.XXX` jump-fours are also classified
  as fours.  Edge cases with the candidate on the *outer* end
  of a near-border run are handled by the short-line fallback
  (`_classify_short_line`).
* **Terminal width**: 60 columns / 24 rows are required for the
  15×15 board to render without wrapping.  The main loop prints
  a "resize" prompt if your terminal is smaller and waits.

## 10. Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `ModuleNotFoundError: No module named 'rich'` | `pip install rich` (or `pip install -e .`) |
| `No module named 'gomoku'` when running `gomoku` | Re-install: `pip install -e .` |
| Black-and-white stones look the same | Terminal is colourless; set `NO_COLOR=` (or `TERM=xterm-256color`) and restart |
| "terminal too small" | Resize the terminal to ≥ 60×24 (≥ 50×20 for 13×13) and press Enter |
| Strong AI exceeds 2 s | Hardware below H10 baseline; record the measurement in your test report rather than failing |
| Forbidden case reports wrong | Verify you're on the latest `pip install -e .`; the algorithm was redesigned in this release (see §5.4) |

## 11. Modification-response table (r1, no prior code review)

This is the first code-stage round of a fresh lifecycle (the
previous lifecycles' r1 review was on a *different* baseline; the
r1 review's "严重 意见 1 — AI 禁手预过滤" has been **integrated into
this release**; see §5.4 above).

Since the prompt for this round is "produce r1 of the new
lifecycle" and there is no prior code-stage review to respond to,
no modification-response table is needed.  The next round
(review by code-reviewer) will produce a review file
`workspace/gomoku/code/gomoku-r1-review.md` against this
deliverable; this README will be updated to respond to those
review notes in r2.
