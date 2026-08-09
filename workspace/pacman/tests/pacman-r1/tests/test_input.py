"""input.py 单测：键位映射（WASD / 方向键 / P / q / 非法键）。

覆盖测试方案：
- TC-B1 方向键 + WASD 均映射为 DIRECTION
- TC-D4 P 暂停
- TC-D6 q 退出
- TC-N6 非法键被忽略（map_key 返回 None）
"""
from __future__ import annotations

import unittest

from pacman.entities import Dir
from pacman.input import Command, InputAction, map_key


KEY_UP = 259  # curses.KEY_UP
KEY_LEFT = 260
KEY_DOWN = 258
KEY_RIGHT = 261


class TestWasdMapping(unittest.TestCase):
    """WASD 大小写均映射为方向。"""

    def test_w(self):
        a = map_key(ord("w"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.DIRECTION, Dir.UP))

    def test_capital_w(self):
        a = map_key(ord("W"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.DIRECTION, Dir.UP))

    def test_a(self):
        a = map_key(ord("a"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.DIRECTION, Dir.LEFT))

    def test_s(self):
        a = map_key(ord("s"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.DIRECTION, Dir.DOWN))

    def test_d(self):
        a = map_key(ord("d"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.DIRECTION, Dir.RIGHT))


class TestArrowKeys(unittest.TestCase):
    """方向键经 key_up/left/down/right 注入后映射为方向。"""

    def test_arrows(self):
        cases = {
            KEY_UP: Dir.UP,
            KEY_LEFT: Dir.LEFT,
            KEY_DOWN: Dir.DOWN,
            KEY_RIGHT: Dir.RIGHT,
        }
        for key, expected_dir in cases.items():
            a = map_key(key, key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
            self.assertEqual(a, InputAction(Command.DIRECTION, expected_dir))


class TestPauseAndQuit(unittest.TestCase):
    def test_p(self):
        a = map_key(ord("p"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.PAUSE))

    def test_capital_p(self):
        a = map_key(ord("P"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.PAUSE))

    def test_q(self):
        a = map_key(ord("q"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.QUIT))

    def test_capital_q(self):
        a = map_key(ord("Q"), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT)
        self.assertEqual(a, InputAction(Command.QUIT))


class TestUnknownKeysIgnored(unittest.TestCase):
    """TC-N6：非法键返回 None，由 main 忽略。"""

    def test_esc(self):
        self.assertIsNone(map_key(27, key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT))

    def test_random_letters(self):
        for ch in "xyzmn":
            self.assertIsNone(map_key(ord(ch), key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT))

    def test_function_keys(self):
        # 277 = KEY_F2 等。任意大整数应被忽略
        self.assertIsNone(map_key(277, key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT))

    def test_zero(self):
        self.assertIsNone(map_key(0, key_up=KEY_UP, key_left=KEY_LEFT, key_down=KEY_DOWN, key_right=KEY_RIGHT))


if __name__ == "__main__":
    unittest.main()
