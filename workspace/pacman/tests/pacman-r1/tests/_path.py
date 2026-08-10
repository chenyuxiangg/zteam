"""让 `tests/` 下的模块无需 pip install 即可 `import pacman.*`。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _workspace_root() -> Path:
    """tests/pacman-r1/tests/_path.py → tests/pacman-r1/ → tests/ → <project>/ → workspace/"""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if ancestor.name == "workspace":
            return ancestor
    return Path.cwd()


def code_dir() -> Path:
    env = os.environ.get("PACMAN_CODE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return _workspace_root() / "pacman" / "code" / "pacman-r1"


# 把 code 阶段产物根目录加入 sys.path，使 `import pacman` 工作
_DIR = code_dir()
if str(_DIR) not in sys.path:
    sys.path.insert(0, str(_DIR))


__all__ = ["code_dir"]
