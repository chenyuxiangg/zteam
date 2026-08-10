"""CLI/交付契约测试：覆盖方案 U-50/U-51/E-02/E-04/E-05/N-06/N-07。"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._path import code_dir


def run_cli(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(code_dir())
    return subprocess.run(
        [sys.executable, "-m", "pacman", *args],
        cwd=code_dir(), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )


class TestCliArguments(unittest.TestCase):
    def test_help(self):
        result = run_cli(["--help"])
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode("utf-8")
        for option in ("--map", "--ghosts", "--lives", "--level", "--speed", "--no-color", "--log-ai"):
            self.assertIn(option, text)

    def test_non_tty_rejected(self):
        result = run_cli([])
        self.assertEqual(result.returncode, 1)
        self.assertIn("需要真实终端", result.stderr.decode("utf-8"))

    def test_invalid_ghosts_exit_2(self):
        for value in ("1", "5", "abc"):
            with self.subTest(value=value):
                self.assertEqual(run_cli(["--ghosts", value]).returncode, 2)

    def test_invalid_lives_exit_2(self):
        for value in ("0", "10"):
            with self.subTest(value=value):
                self.assertEqual(run_cli(["--lives", value]).returncode, 2)

    def test_invalid_speed_exit_2(self):
        for value in ("0.4", "2.1", "abc"):
            with self.subTest(value=value):
                self.assertEqual(run_cli(["--speed", value]).returncode, 2)

    def test_invalid_level_exit_2(self):
        self.assertEqual(run_cli(["--level", "0"]).returncode, 2)


class TestDeliveryContract(unittest.TestCase):
    def test_requirements_has_no_runtime_packages(self):
        req = code_dir() / "requirements.txt"
        self.assertTrue(req.exists())
        active = [line for line in req.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(active, [])

    def test_readme_documents_required_sections_and_options(self):
        text = (code_dir() / "README.md").read_text(encoding="utf-8")
        for phrase in ("运行方式", "键位说明", "AI 策略", "配置选项", "依赖"):
            self.assertIn(phrase, text)
        for option in ("--map", "--ghosts", "--lives", "--level", "--speed", "--no-color", "--log-ai"):
            self.assertIn(option, text)

    def test_logic_layer_does_not_import_curses_or_network(self):
        package = code_dir() / "pacman"
        network = re.compile(r"^\s*(?:from|import)\s+(?:socket|urllib|requests|http\.|ftplib|smtplib)\b", re.M)
        curses_import = re.compile(r"^\s*(?:from\s+curses|import\s+curses)\b", re.M)
        offenders = []
        for name in ("config.py", "map.py", "entities.py", "ghost_ai.py", "game.py", "input.py"):
            src = (package / name).read_text(encoding="utf-8")
            if curses_import.search(src) or network.search(src):
                offenders.append(name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
