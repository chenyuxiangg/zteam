"""模块入口。

职责：支持 ``python3 -m pacman``；对应开发方案 §4.1。
依赖：pacman.main。
"""

from .main import main_cli


if __name__ == "__main__":
    raise SystemExit(main_cli())
