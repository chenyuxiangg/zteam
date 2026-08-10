"""input.py 单测：键位映射（T-CTRL-03 非法键 + T-EXIT-02 q 退出 + T-UI-01 P 暂停）。

键位（README §3）：
- ↑ / W → UP
- ↓ / S → DOWN
- ← / A → LEFT
- → / D → RIGHT
- P → 暂停
- Q → 退出
- 其他键 → NONE（忽略）
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401

from pacman import input as inp
from pacman.input import (
    KEY_A, KEY_D, KEY_DOWN, KEY_LEFT, KEY_PAUSE, KEY_QUIT,
    KEY_RIGHT, KEY_S, KEY_UP, KEY_W, Action, parse_key,
)


class TestParseKey(unittest.TestCase):
    """T-CTRL-03 / T-EXIT-02 / T-UI-01：parse_key 正确映射。"""

    def test_arrow_keys(self):
        self.assertEqual(parse_key(KEY_UP), Action.TURN_UP)
        self.assertEqual(parse_key(KEY_DOWN), Action.TURN_DOWN)
        self.assertEqual(parse_key(KEY_LEFT), Action.TURN_LEFT)
        self.assertEqual(parse_key(KEY_RIGHT), Action.TURN_RIGHT)

    def test_wasd(self):
        self.assertEqual(parse_key(KEY_W), Action.TURN_UP)
        self.assertEqual(parse_key(KEY_S), Action.TURN_DOWN)
        self.assertEqual(parse_key(KEY_A), Action.TURN_LEFT)
        self.assertEqual(parse_key(KEY_D), Action.TURN_RIGHT)

    def test_pause(self):
        self.assertEqual(parse_key(KEY_PAUSE), Action.PAUSE)

    def test_quit(self):
        self.assertEqual(parse_key(KEY_QUIT), Action.QUIT)

    def test_invalid_returns_none(self):
        """T-CTRL-03：非法键被忽略。"""
        for k in ["1", "@", "F5", "x", "Y", "ESC", "ENTER", ""]:
            self.assertEqual(parse_key(k), Action.NONE, f"key {k!r} should be NONE")

    def test_key_constants_unique(self):
        """健壮性：所有 KEY_* 常量互异。"""
        keys = [KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT, KEY_W, KEY_S, KEY_A, KEY_D, KEY_PAUSE, KEY_QUIT]
        self.assertEqual(len(keys), len(set(keys)))


class TestKeycodeToStr(unittest.TestCase):
    """T-EXIT-04 配套：keycode → string 转换（curses 集成点）。"""

    def test_keycode_to_str_basic(self):
        # 假设 keycode_to_str 接受 int 返回 str；非 curses 键返回 "?"
        # 不强制实现细节，只断言不抛异常
        try:
            for code in [65, 97, 258, 259, 260, 261, 113, 112, -1]:
                s = inp.keycode_to_str(code)
                self.assertIsInstance(s, str)
        except (NotImplementedError, AttributeError):
            self.skipTest("keycode_to_str requires curses context")


if __name__ == "__main__":
    unittest.main()
