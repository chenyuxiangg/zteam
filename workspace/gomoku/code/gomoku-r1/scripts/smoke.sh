#!/usr/bin/env bash
# End-to-end smoke test: drive a complete game with weak AI and
# verify the framework responds correctly to a winning move.

set -euo pipefail

cd "$(dirname "$0")/.."

# Make sure the package is importable
PYTHONPATH=. python3 -c "import gomoku; print('import OK, version', gomoku.__version__)"

# Run the forbidden-cases self-check (24 cases; must all pass)
PYTHONPATH=. python3 -m gomoku.forbidden_cases

# Run the AI self-check (open-four block, live-three response, weak
# legal moves, forbidden prefilter, strong midgame timing)
PYTHONPATH=. python3 -m gomoku.ai_self_check

# CLI smoke: --help / --version
PYTHONPATH=. python3 -m gomoku --help >/dev/null
PYTHONPATH=. python3 -m gomoku --version

# End-to-end: pipe a known winning sequence (H8, I9, J10, K11, L12)
# and assert the game declares a Black win.
output=$(printf 'H8\nI9\nJ10\nK11\nL12\nquit\n' \
    | PYTHONPATH=. python3 -m gomoku --size 13 --difficulty weak 2>&1 || true)
if echo "$output" | grep -q "Black wins"; then
    echo "smoke.sh: end-to-end game completed (Black wins)."
else
    echo "smoke.sh: end-to-end game did not complete as expected." >&2
    echo "$output" >&2
    exit 1
fi

# Invalid-input fuzz: a few malformed inputs must not crash the game.
output=$(printf 'P1\nA0\nxyz\n8 8\nA8\nquit\n' \
    | PYTHONPATH=. python3 -m gomoku --size 13 --difficulty weak 2>&1 || true)
if echo "$output" | grep -qE "(invalid move|illegal)"; then
    echo "smoke.sh: invalid-input fuzz reported errors as expected."
else
    echo "smoke.sh: invalid-input fuzz did not report errors." >&2
    exit 1
fi

echo "smoke.sh: all checks passed."
