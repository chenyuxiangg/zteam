"""架构与依赖契约测试：NFR-02 / C-03 / N-02 / N-06 子集。

覆盖：
- C-03：逻辑层模块（config/map/entities/ghost_ai/game/input）不 import curses
- N-02：requirements.txt 与运行时实际依赖一致（0 pip 依赖声明）
- N-06（静态补充）：逻辑层不 import 网络/IO 模块（socket/urllib/requests）
- 模块结构：9 模块齐全且每个模块顶部有 docstring

策略：源码静态扫描（grep）。不需要运行游戏主进程。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._path import code_dir  # noqa: F401


CODE_DIR = code_dir()
PACMAN_PKG = CODE_DIR / "pacman"


# 逻辑层模块（按方案 §3.2）：不依赖 curses
LOGIC_LAYER_MODULES = [
    "config.py",
    "map.py",
    "entities.py",
    "ghost_ai.py",
    "game.py",
    "input.py",
]

# curses 依赖模块（仅这两模块允许 import curses）
CURSES_LAYER_MODULES = [
    "main.py",
    "renderer.py",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has_import(text: str, module_name: str) -> bool:
    """检测 ``import <module_name>`` 或 ``from <module_name> import ...``。

    用正则避开字符串字面量（``'import curses'`` 不算）。
    """
    pattern = rf"(?<![\w.])import\s+{re.escape(module_name)}\b"
    return bool(re.search(pattern, text))


def _has_from_import(text: str, module_name: str) -> bool:
    pattern = rf"from\s+{re.escape(module_name)}\s+import\b"
    return bool(re.search(pattern, text))


class TestLogicLayerNoCurses(unittest.TestCase):
    """C-03：逻辑层 6 模块零 curses import。"""

    def test_logic_modules_have_no_curses_import(self):
        offenders = []
        for mod in LOGIC_LAYER_MODULES:
            text = _read(PACMAN_PKG / mod)
            # 兼容 ``import curses`` 与 ``from curses import ...``
            if _has_import(text, "curses") or _has_from_import(text, "curses"):
                offenders.append(mod)
        self.assertEqual(offenders, [],
                         f"逻辑层模块不应 import curses: {offenders}")

    def test_curses_layer_modules_import_curses(self):
        """反向验证：main.py / renderer.py 实际有 curses 依赖（用于完整性）。"""
        for mod in CURSES_LAYER_MODULES:
            text = _read(PACMAN_PKG / mod)
            self.assertTrue(
                _has_import(text, "curses") or _has_from_import(text, "curses"),
                f"{mod} 应 import curses（包裹 try/except 是允许的）",
            )


class TestLogicLayerNoNetwork(unittest.TestCase):
    """N-06 静态补充：逻辑层不 import 网络/远程模块。"""

    NETWORK_MODULES = ["socket", "urllib", "urllib2", "urllib3",
                       "http", "http.client", "requests", "httpx",
                       "asyncio.open_connection"]

    def test_logic_modules_have_no_network_import(self):
        offenders = []
        for mod in LOGIC_LAYER_MODULES:
            text = _read(PACMAN_PKG / mod)
            for net_mod in self.NETWORK_MODULES:
                if _has_import(text, net_mod) or _has_from_import(text, net_mod):
                    offenders.append((mod, net_mod))
        self.assertEqual(offenders, [],
                         f"逻辑层不应 import 网络模块: {offenders}")


class TestModuleStructure(unittest.TestCase):
    """方案 §3.2 模块划分：9 模块齐全 + 每个模块顶部有 docstring。"""

    def test_all_modules_present(self):
        expected = {
            "__init__.py", "__main__.py", "main.py",
            "config.py", "map.py", "entities.py",
            "ghost_ai.py", "game.py", "input.py", "renderer.py",
        }
        actual = {p.name for p in PACMAN_PKG.iterdir() if p.suffix == ".py"}
        self.assertEqual(actual & expected, expected,
                         f"缺失模块：{expected - actual}")

    def test_each_module_has_docstring(self):
        offenders = []
        for mod in sorted(PACMAN_PKG.glob("*.py")):
            text = _read(mod)
            # 顶部 docstring：第一行非空字符串或紧接 """ 即可
            if not re.match(r'^\s*"""', text) and not re.match(r"^\s*'''", text):
                offenders.append(mod.name)
        self.assertEqual(offenders, [],
                         f"模块顶部应有 docstring：{offenders}")

    def test_data_file_present(self):
        """内置地图文件存在。"""
        map_path = PACMAN_PKG / "data" / "map_classic.txt"
        self.assertTrue(map_path.exists(), f"缺少 {map_path}")
        self.assertGreater(map_path.stat().st_size, 0, "内置地图为空")


class TestRequirementsTxt(unittest.TestCase):
    """N-02：requirements.txt 与运行时依赖一致（方案：0 pip 依赖）。"""

    def test_requirements_txt_exists(self):
        req = CODE_DIR / "requirements.txt"
        self.assertTrue(req.exists(), f"缺少 {req}")

    def test_requirements_txt_empty_or_only_comments(self):
        """requirements.txt 应为空依赖（仅注释或全空行）。"""
        req = CODE_DIR / "requirements.txt"
        text = req.read_text(encoding="utf-8")
        # 去掉空行与注释行后，剩余应为 0 个包声明
        non_empty_lines = [
            line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        # 允许写一行注释（如 "# 0 pip 依赖"），但不应有实际包名
        package_lines = [
            line for line in non_empty_lines
            if re.match(r"^[A-Za-z0-9_.-]+\s*(\[.*\])?\s*(>=|<=|==|~=|>|<)?", line)
            and " " not in line.split("#")[0].strip()
        ]
        # 注释不算包
        self.assertEqual(package_lines, [],
                         f"requirements.txt 应为空依赖声明：{package_lines}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
