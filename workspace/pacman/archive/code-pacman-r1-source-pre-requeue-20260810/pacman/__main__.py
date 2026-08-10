"""python3 -m pacman 入口。

职责：直接调用 pacman.main.main_cli()；对应开发方案 §4.1 入口。
依赖：pacman.main。
"""

import sys

from .main import main_cli


if __name__ == "__main__":
    sys.exit(main_cli())
