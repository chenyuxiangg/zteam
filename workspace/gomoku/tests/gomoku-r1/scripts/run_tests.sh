#!/usr/bin/env bash
# Test-suite smoke runner.  Equivalent to running pytest but with a
# more discoverable name so the orchestrator scripts can call it.
#
# Usage:
#   bash scripts/run_tests.sh           # full suite
#   bash scripts/run_tests.sh forbidden # only forbidden cases
#   bash scripts/run_tests.sh ai        # only AI tests
set -euo pipefail

cd "$(dirname "$0")/.."

# Default code path: ../code/gomoku-r1
export PYTHONPATH="${PYTHONPATH:-$(cd ../.. && pwd)/code/gomoku-r1}"
export GOMOKU_CODE_DIR="${GOMOKU_CODE_DIR:-$PYTHONPATH}"

echo "=== test suite smoke ==="
echo "code dir: $PYTHONPATH"

if [ "$#" -eq 0 ]; then
    exec python3 -m pytest -v
else
    exec python3 -m pytest -v -k "$1"
fi
