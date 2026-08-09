"""测试路径辅助。

让 `tests/` 下任意模块都能 `import pacman.*`，不依赖运行环境已 `pip install`。
两种发现路径都尝试：

- ``workspace/pacman/code/pacman-r1``  ← code 阶段产物（默认，单测应跑这条）
- ``$PACMAN_CODE_DIR`` ← 用户覆盖（便于 release 阶段或不同布局）

工作区根路径向上搜索到 ``workspace/`` 即停。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _this_file() -> Path:
    return Path(__file__).resolve()


def _workspace_root() -> Path:
    """tests/pacman-r1/tests/_path.py → tests/pacman-r1/ → tests/ → <project>/ → workspace/"""
    here = _this_file()
    for ancestor in here.parents:
        if ancestor.name == "workspace":
            return ancestor
    # 兜底：相对 CWD 搜索一次
    return Path.cwd()


def code_dir() -> Path:
    env = os.environ.get("PACMAN_CODE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _workspace_root() / "pacman" / "code" / "pacman-r1"


# 关键：把 code 阶段产物根目录加入 sys.path，使 ``import pacman`` 工作。
_CODE_DIR = code_dir()
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))


__all__ = ["code_dir"]
