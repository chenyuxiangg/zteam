"""Allow ``python -m gomoku`` to launch the CLI (plan §3 / §5.4)."""
from .main import main
import sys

raise SystemExit(main(sys.argv[1:]))
