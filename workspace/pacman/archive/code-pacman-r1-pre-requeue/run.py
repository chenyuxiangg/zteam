#!/usr/bin/env python3
"""便捷启动器。

职责：从产物根目录启动 pacman 包；对应开发方案 §4.1 入口。
依赖：pacman.main。
"""

from pacman.main import main_cli


if __name__ == "__main__":
    raise SystemExit(main_cli())
