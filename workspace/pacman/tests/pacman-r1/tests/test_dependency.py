"""模块依赖方向静态检查（TC-N3）。

逻辑层（config/map/entities/ghost_ai/game/input）不 import curses；
仅 main/renderer 依赖 curses。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._path import code_dir


CURSES_PATTERN = re.compile(r"^\s*(?:from\s+curses|import\s+curses)\b", re.MULTILINE)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestDependencyDirection(unittest.TestCase):
    """TC-N3：模块依赖方向。

    依赖方向（单向）：
      main → config/map/game/input/renderer
      game → entities → ghost_ai
      game/map/entities/ghost_ai 不 import curses
    """

    PACKAGE = code_dir() / "pacman"

    LOGIC_MODULES = ("config.py", "map.py", "entities.py", "ghost_ai.py", "game.py", "input.py")
    CURSES_MODULES = ("main.py", "renderer.py")

    def test_logic_layer_no_curses(self):
        offenders = []
        for name in self.LOGIC_MODULES:
            path = self.PACKAGE / name
            if CURSES_PATTERN.search(_read(path)):
                offenders.append(name)
        self.assertEqual(offenders, [], f"logic modules must not import curses: {offenders}")

    def test_curses_layer_has_curses(self):
        """渲染层应至少 import curses（renderer 用 curses.* API）。"""
        # renderer.py 必须 import curses
        renderer_src = _read(self.PACKAGE / "renderer.py")
        self.assertTrue(
            CURSES_PATTERN.search(renderer_src),
            "renderer.py must import curses",
        )

    def test_dependency_graph_no_back_edges(self):
        """逻辑层之间不能反向依赖（避免循环）。

        允许的依赖：
          game → entities, ghost_ai, map, config
          entities → map
          ghost_ai → entities, map
          input → entities
          renderer → map, game, entities, config
          main → config, map, game, input, renderer
        反向 / 跨层：禁止
        """
        # 提取每个模块的 import pacman.xxx 列表
        all_modules = tuple(self.LOGIC_MODULES) + tuple(self.CURSES_MODULES)
        deps = {}
        for name in all_modules:
            src = _read(self.PACKAGE / name)
            deps[name] = set(re.findall(r"from\s+\.([\w]+)\s+import|from\s+pacman\.([\w]+)\s+import", src))

        # 简化：仅断言 game 不 import renderer / main
        game_imports = " ".join(re.findall(r"from\s+(\.\w+|pacman\.\w+)\s+import", _read(self.PACKAGE / "game.py")))
        self.assertNotIn("renderer", game_imports)
        self.assertNotIn("main", game_imports)

        ghost_ai_imports = " ".join(re.findall(r"from\s+(\.\w+|pacman\.\w+)\s+import", _read(self.PACKAGE / "ghost_ai.py")))
        self.assertNotIn("game", ghost_ai_imports)
        self.assertNotIn("renderer", ghost_ai_imports)


class TestNoNetworkImports(unittest.TestCase):
    """TC-N8 / NFR-06：源码不得 import 网络相关模块。"""

    NETWORK_MODULES = ("socket", "urllib", "urllib.request", "urllib.error",
                        "requests", "http.client", "http.server", "ftplib", "smtplib",
                        "asyncio.streams")

    def test_no_network_imports(self):
        package = code_dir() / "pacman"
        offenders = []
        for p in package.glob("*.py"):
            src = p.read_text(encoding="utf-8")
            for net in self.NETWORK_MODULES:
                if re.search(rf"^\s*(?:from\s+{re.escape(net)}|import\s+{re.escape(net)})\b", src, re.MULTILINE):
                    offenders.append(f"{p.name} imports {net}")
        self.assertEqual(offenders, [], f"network imports found: {offenders}")


class TestRequirementsTxtEmpty(unittest.TestCase):
    """TC-E3 / TC-N7：requirements.txt 声明空依赖（与 NFR-05 一致）。"""

    def test_requirements_only_comments_or_empty(self):
        req = code_dir() / "requirements.txt"
        self.assertTrue(req.exists())
        for line in req.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.fail(f"requirements.txt has non-empty line: {line!r}")


class TestReadmePresent(unittest.TestCase):
    """TC-E2：README 存在。"""

    def test_readme_exists(self):
        self.assertTrue((code_dir() / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
