"""Allow ``python -m gomoku`` to launch the CLI (plan §3 / §5.4)."""
from .main import main

raise SystemExit(main())
