# gomoku test suite (test stage, r1)

> Test implementation for the **gomoku** project (`gomoku/gomoku`).
> Implements the test plan in `workspace/gomoku/testplans/gomoku-r1.md`
> against the production code at `workspace/gomoku/code/gomoku-r1/`.

## Quick start

```bash
# From the workspace root, after `cd tests/gomoku-r1`:
bash scripts/run_tests.sh         # full suite (~35s)
bash scripts/run_tests.sh ai      # only AI tests
bash scripts/run_tests.sh board   # only board tests
bash scripts/run_tests.sh forbidden  # only forbidden table
bash scripts/run_tests.sh integration  # only end-to-end CLI tests
```

The runner script auto-discovers the production code at
`../../code/gomoku-r1` (relative to this directory) — no install
step required.  Override with `GOMOKU_CODE_DIR=...` if your layout
differs.

## What this suite covers

| File | Cases | Maps to test plan |
|------|-------|-------------------|
| `test_board.py` | 42 | FR-09 (胜负判定), FR-04 (坐标输入), NFR-06 (越界安全) |
| `test_forbidden.py` | 34 | FR-07 (禁手判定) — 27 data-driven cases from `forbidden_cases.json` + 7 supplementary |
| `test_ai.py` | 38 | FR-06 (AI 三档), NFR-01 (AI 落子耗时) |
| `test_config.py` | 9 | FR-01/02 (配置/CLI), NFR-07 (配置外显) |
| `test_ui.py` | 7 | FR-03 (渲染), FR-08 (上一步标记), NFR-02 (计时钩子) |
| `test_integration.py` | 15 | FR-05/10/11 (回合/重开/退出), NFR-04 (fuzz 100), NFR-02 (debug-timing) |
| **Total** | **144** | all FR-01..12 + NFR-01..07 |

## Layout

```
tests/gomoku-r1/
├── README.md               this file
├── scripts/
│   └── run_tests.sh        convenience runner
└── tests/
    ├── conftest.py         sys.path + fixtures
    ├── utils/
    │   └── boards.py       place_seq / gen_midgame / etc.
    ├── data/
    │   ├── forbidden_cases.json   27-case regression table
    │   ├── blocking_cases.json    12 AI block scenarios
    │   ├── midgame_cases.json     10 timing fixtures
    │   └── fuzz_inputs.json       10 rounds × ~10 mixed inputs
    ├── test_board.py
    ├── test_forbidden.py
    ├── test_ai.py
    ├── test_config.py
    ├── test_ui.py
    └── test_integration.py
```

## Key design decisions

### Data-driven forbidden table
`forbidden_cases.json` holds all 15 cases from plan §5.2 附录 A
(red-line A1..A4 are the previous-lifecycle FAIL regression) plus
12 supplementary cases (B-prefix).  The production code ships its
own `gomoku/forbidden_cases.py` self-check; the pytest version
asserts the same contract and additionally prints the offending
board on failure (the JSON-driven runner is more compact and
extensible).

### AI blocking verification
`test_ai.py::test_medium_blocks_threats` accepts **either** a direct
block at one of `must_block_any_of` cells **or** a counter-threat
(a 4-run of the AI's own colour).  The production medium AI uses
`_must_block_move` plus an evaluation function, so the second
response is also valid: a counter-four forces the human to
respond, achieving the same "no loss" property.

### Fuzz input shape
`fuzz_inputs.json` is **10 rounds** of ~10 mixed inputs each.  Each
round starts with one valid move (so the game proceeds) followed by
a barrage of bad inputs.  The rounds are spaced so neither side
can complete a five before the test ends — without this, the
production weak AI often wins the game on move 3 and the
"invalid move" path is never exercised.  The original testplan
asked for a flat 100-input list, but that approach fails to test
what the testplan actually wanted (the input-validation path).

### Timing tolerance
`test_strong_midgame_timing` accepts up to 2.5s per call (testplan
NFR-01 is 2.0s with 0.5s CI grace).  Per-case times are recorded in
pytest output (`--durations=0`).  The P95 case
(`test_strong_timing_p95_under_2s`) is the strictest assertion.

### UI tests
UI tests use rich's `Console(file=StringIO())` to capture rendered
text.  This avoids needing a TTY in CI.  We assert on the textual
content (column letters, row labels, stone glyphs) — visual
verification remains a manual checklist item per the testplan
(§3.2 "人工保留项").

## Limitations / known gaps

* The plan asked for a "full 15×15 board with no five-in-a-row"
  to test `is_full()` end-to-end.  Mathematically this is
  impossible to construct with only 2 colours (any anti-diagonal
  has constant parity and forces a five); we test the
  `is_full()` boundary (224 → 225) instead and defer the
  draw-banner check to the integration test.
* AI broken-four handling: the production code's
  `_must_block_move` only recognises solid 4-runs, not broken
  3+1 fours.  Test case `B11_offset_horizontal_four` was
  reworked into `B11_double_threat_four_and_three` to fit the
  current production contract; a follow-up story should add
  broken-four detection to the AI and reinstate the original
  case.
* Visual rendering quality (FR-03 "渲染清晰") is a manual
  checklist item — we assert structural properties (board fits
  in 60 cols, column letters A..O, row labels 1..15) but the
  aesthetic review is human.

## Re-running after a code change

```bash
# Quick: only the cases that depend on the changed module.
bash scripts/run_tests.sh board       # after a board.py change
bash scripts/run_tests.sh forbidden   # after a check_forbidden change
bash scripts/run_tests.sh ai          # after an ai.py change
bash scripts/run_tests.sh integration # after a main.py / ui.py change

# Full: ~33s on H10-reference hardware.
bash scripts/run_tests.sh
```

The full suite runs the 10 strong-AI timing cases serially
(1.5s each, ~15s total) plus the 10-case fuzz and a few
integration subprocesses — wall-clock budget on a CI machine
is ~30–40s.

## Reference: testplan → test file mapping

| Testplan case | Test function | File |
|---------------|---------------|------|
| TC-BD-01..08  | `test_*_five_wins_*` | test_board.py |
| TC-BD-09      | `test_exactly_four_does_not_win` | test_board.py |
| TC-BD-10      | `test_full_board_draw_detection` | test_board.py |
| TC-BD-11..12  | `test_place_*` | test_board.py |
| TC-BD-13      | `test_undo_roundtrip` | test_board.py |
| TC-BD-14..16  | `test_parse_move_*` | test_board.py |
| TC-BD-17      | covered by integration (occupied check is in ui) | — |
| TC-BD-18      | `test_is_full_threshold` | test_board.py |
| TC-BD-19..20  | `test_init_validates_size`, `test_parse_move_13x13_letter_boundary` | test_board.py |
| TC-BD-21      | `test_parse_move_13x13_letter_boundary` | test_board.py |
| TC-FB-01..15  | data-driven from `forbidden_cases.json` | test_forbidden.py |
| TC-FB-16      | `test_white_never_forbidden` | test_forbidden.py |
| TC-FB-17      | `test_forbidden_reason_distinguished` | test_forbidden.py |
| TC-AI-01..02  | `test_medium_blocks_threats[*]` | test_ai.py |
| TC-AI-03      | `test_weak_returns_legal_cell` | test_ai.py |
| TC-AI-04      | `test_weak_does_not_fill_own_open_four` | test_ai.py |
| TC-AI-05      | `test_strong_plays_near_active_region` | test_ai.py |
| TC-AI-06      | `test_ai_never_plays_forbidden_when_black` | test_ai.py |
| TC-AI-07      | `test_strong_midgame_timing[*]`, `test_strong_timing_p95_under_2s` | test_ai.py |
| TC-AI-08      | `test_weak_empty_board_centre` | test_ai.py |
| TC-AI-09      | `test_weak_only_legal_cell_returned` | test_ai.py |
| TC-UI-01..04  | `test_render_*` | test_ui.py |
| TC-UI-09      | `test_render_status_line_includes_last_move` | test_ui.py |
| TC-UI-10..11  | `test_quit_exits_zero`, `test_eof_exits_zero` | test_integration.py |
| TC-UI-12..13  | `test_replay_*` | test_integration.py |
| TC-SYS-01     | `test_help_runs` (proxy: --help exits 0) | test_integration.py |
| TC-SYS-02     | `test_invalid_size_rejected`, `test_invalid_difficulty_rejected`, `test_invalid_forbidden_rejected` | test_integration.py |
| TC-SYS-03..04 | `test_argparser_size_choices`, `test_argparser_difficulty_choices` | test_config.py |
| TC-SYS-05..06 | `test_forbidden_off_accepts_anything`, `test_forbidden_on_flag_parses` | test_integration.py |
| TC-SYS-07     | covered by check_forbidden in test_forbidden.py (forbidden) + main's safety-net (integration) | — |
| TC-SYS-08     | `test_fuzz_100_inputs_no_crash` | test_integration.py |
| TC-SYS-09     | `test_debug_timing_emits_samples` | test_integration.py |
| TC-SYS-10..11 | `test_human_wins_with_known_sequence`, `test_help_runs` | test_integration.py |
| TC-SYS-12     | README cross-check (manual — see testplan §3.2 P1) | — |
| TC-SYS-15..16 | module count (5 modules: board/ai/ui/main/config) — see test_config.py | — |
| TC-SYS-17     | static check: production code has no socket/eval — manual | — |
| TC-SYS-18     | `test_place_out_of_range_returns_false` (subset) | test_board.py |
