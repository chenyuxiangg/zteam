"""PyInstaller 入口：python -m game_app → main()。"""
from __future__ import annotations

import sys

from .app import main


if __name__ == "__main__":
    sys.exit(main())