"""让 tests/ 下的模块无需 pip install 即可 import pacman.*。

路径解析策略：
  1) 优先使用 PACMAN_CODE_DIR 环境变量（推荐用于跨目录测试）；
  2) 否则向上溯源直到定位到名为 workspace 的目录，然后拼接
     workspace/pacman/code/pacman-r1/。

注意：此模块在任何 ``pacman.*`` 之前被加载。它同时向 ``sys.modules``
注入一个 curses 桩，让 ``pacman.renderer`` 在没有真终端的测试环境
也能被 import（避免真实 _curses.curs_set 等调用抛 initscr error）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType


def _workspace_root() -> Path:
    """tests/pacman-r1/tests/_path.py → ... → workspace/"""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if ancestor.name == "workspace":
            return ancestor
    return Path.cwd()


def code_dir() -> Path:
    """返回 code 阶段产物根目录（包含 pacman/ 子包）。"""
    env = os.environ.get("PACMAN_CODE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _workspace_root() / "pacman" / "code" / "pacman-r1"


def _install_curses_stub() -> ModuleType:
    """在 tests/_path.py 加载时（最早阶段）注入 curses 桩。

    pacman.main / pacman.renderer 都做 ``try: import curses``，
    在没有真终端的环境（CI/headless/sandbox）真实 curses 模块的
    ``curs_set`` 等调用会抛 ``_curses.error``。这里提供一个极简
    ModuleType 桩，覆盖 renderer 必需的所有调用。
    """
    fake = ModuleType("curses")

    # ---- 能力探测 ----
    fake.has_colors = lambda: False
    fake.start_color = lambda: None
    fake.use_default_colors = lambda: None
    fake.init_pair = lambda *a, **k: None
    fake.color_pair = lambda n: n
    fake.curs_set = lambda v: 0
    fake.nodelay = lambda *a, **k: None
    fake.noecho = lambda: None
    fake.cbreak = lambda: None
    fake.echo = lambda: None
    fake.endwin = lambda: None
    fake.wrapper = lambda fn, *a, **k: fn(None, *a, **k)
    fake.getch = lambda *a, **k: -1

    # ---- 颜色常量（Renderer 不读，但 curses.error 类继承需要存在） ----
    fake.COLOR_BLACK = 0
    fake.COLOR_RED = 1
    fake.COLOR_GREEN = 2
    fake.COLOR_YELLOW = 3
    fake.COLOR_BLUE = 4
    fake.COLOR_MAGENTA = 5
    fake.COLOR_CYAN = 6
    fake.COLOR_WHITE = 7

    # ---- 错误类型 ----
    fake.error = type("error", (Exception,), {})

    # ---- 强制覆盖 ----
    sys.modules["curses"] = fake
    return fake


_DIR = code_dir()
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))

# 必须在任何 pacman.* import 之前注入；test_renderer.py 等会依赖此桩
_curses_stub = _install_curses_stub()


__all__ = ["code_dir"]