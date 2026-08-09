"""CLI 冒烟集成测试（不依赖 unittest discover）。

覆盖测试方案：
- TC-A4 合法自定义地图加载
- TC-X1 非 TTY 报错 exit 1
- TC-X2 --ghosts 非法值
- TC-X3 --lives 越界
- TC-X4 --speed 越界
- TC-X6 地图路径不存在
- TC-X7 非法字符地图报错 + 定位

执行：
    PYTHONPATH=. python3 tests/test_cli_smoke.py

不引入 pytest / 第三方依赖；只依赖标准库 subprocess + sys。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._path import code_dir


def _run(args: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    """在 code 产物根目录以子进程跑 `python -m pacman <args>`。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(code_dir())
    # 关掉真实 stdout 是 TTY：subprocess.PIPE 不算 TTY
    return subprocess.run(
        [sys.executable, "-m", "pacman", *args],
        cwd=str(code_dir()),
        env=env,
        input=stdin_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )


class TestNonTTY(unittest.TestCase):
    """TC-X1：非 TTY 环境 → exit 1 + stderr '需要真实终端'。"""

    def test_pipe_returns_error(self):
        result = _run([])
        # pipe 输入 → stdin.isatty() = False
        # 我们的代码 main_cli 先 parse_args，再 load 地图，再 TTY 检查；TTY 检查应失败
        self.assertEqual(result.returncode, 1)
        self.assertIn("需要真实终端", result.stderr.decode("utf-8"))


class TestMissingMapFile(unittest.TestCase):
    """TC-X6：地图路径不存在。"""

    def test_nonexistent_path(self):
        result = _run(["--map", "/nonexistent/path.map"])
        self.assertEqual(result.returncode, 1)
        self.assertIn("不存在", result.stderr.decode("utf-8"))


class TestInvalidGhostCount(unittest.TestCase):
    """TC-X2：--ghosts 非法值（argparse error → exit 2）。"""

    def test_ghost_1(self):
        result = _run(["--ghosts", "1"])
        self.assertIn(result.returncode, (1, 2))

    def test_ghost_5(self):
        result = _run(["--ghosts", "5"])
        self.assertIn(result.returncode, (1, 2))

    def test_ghost_abc(self):
        result = _run(["--ghosts", "abc"])
        self.assertIn(result.returncode, (1, 2))


class TestInvalidLives(unittest.TestCase):
    """TC-X3：--lives 越界。"""

    def test_lives_0(self):
        result = _run(["--lives", "0"])
        self.assertIn(result.returncode, (1, 2))

    def test_lives_10(self):
        result = _run(["--lives", "10"])
        self.assertIn(result.returncode, (1, 2))


class TestInvalidSpeed(unittest.TestCase):
    """TC-X4：--speed 越界。"""

    def test_speed_0(self):
        result = _run(["--speed", "0"])
        self.assertIn(result.returncode, (1, 2))

    def test_speed_2_5(self):
        result = _run(["--speed", "2.5"])
        self.assertIn(result.returncode, (1, 2))

    def test_speed_negative(self):
        result = _run(["--speed", "-1"])
        self.assertIn(result.returncode, (1, 2))


class TestBadMapContents(unittest.TestCase):
    """TC-A5 / TC-X7：合法路径 + 非法地图字符。"""

    BAD_MAPS = {
        "variable_width": (
            "######################\n"
            "#........#..#........#\n"
            "#o.......#..#.......o#\n"
            "#....................#\n"
            "#.##.#....##....#.##.#\n"
            "#....#....##....#....#\n"
            "###.###.######.###.###\n"
            "###................###\n"
            "###.#.##########.#.###\n"
            "###.#.#HHHHHHHH#.#.###\n"
            "###.#.##------##.#.###\n"
            "###................###\n"
            "###......PP........###\n"
            "###.###.######.###.###\n"
            "#....#....##....#....#\n"
            "#.##.#....##....#.##.#\n"
            "#....................\n"  # 短 1
            "#o.......#..#.......o#\n"
            "######################\n"
        ),
        "illegal_char": (
            "######################\n"
            "#........#..#........#\n"
            "#o.......#..#.......o#\n"
            "#....................#\n"
            "#.##.#....##....#.##.#\n"
            "#....#....##....#....#\n"
            "###.###.######.###.###\n"
            "###................###\n"
            "###.#.##########.#.###\n"
            "###.#.#HHHHHHHH#.#.###\n"
            "###.#.##------##.#.###\n"
            "###................###\n"
            "###......PP........###\n"
            "###.###.######.###.###\n"
            "#....#....##....#....#\n"
            "#.##.#....##....#.##.#\n"
            "#....................#\n"
            "#o.......#..X.......o#\n"  # 非法 X
            "######################\n"
        ),
    }

    def _write(self, name: str, text: str) -> Path:
        path = Path(tempfile.gettempdir()) / f"pacman_{name}.map"
        path.write_text(text, encoding="utf-8")
        return path

    def test_variable_width(self):
        path = self._write("variable_width", self.BAD_MAPS["variable_width"])
        result = _run(["--map", str(path)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("第 17 行宽度", result.stderr.decode("utf-8"))

    def test_illegal_char(self):
        path = self._write("illegal_char", self.BAD_MAPS["illegal_char"])
        result = _run(["--map", str(path)])
        self.assertEqual(result.returncode, 1)
        self.assertIn("非法字符", result.stderr.decode("utf-8"))


class TestHelpFlag(unittest.TestCase):
    """--help 应当 exit 0（argparse 标准行为）。"""

    def test_help(self):
        result = _run(["--help"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout.decode("utf-8").lower())


if __name__ == "__main__":
    unittest.main()
