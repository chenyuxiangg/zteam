"""输入映射测试：FR-04 键位 + parse_key + keycode_to_str。

覆盖：
- FR-04：方向键（curses keycode 259/258/260/261）+ WASD → Action.TURN_*
- FR-16：q 键 → Action.QUIT
- Q11：p 键 → Action.PAUSE
- 非法键 → Action.NONE（忽略）
"""
from __future__ import annotations

import unittest

from tests._path import code_dir  # noqa: F401

from pacman.input import (
    parse_key, keycode_to_str, Action,
    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT,
    KEY_W, KEY_A, KEY_S, KEY_D,
    KEY_PAUSE, KEY_QUIT,
)


class TestKeycodeToStr(unittest.TestCase):
    """curses keycode → 字符串（main.py 渲染前先转）。"""

    def test_arrow_key_codes(self):
        self.assertEqual(keycode_to_str(259), KEY_UP)
        self.assertEqual(keycode_to_str(258), KEY_DOWN)
        self.assertEqual(keycode_to_str(260), KEY_LEFT)
        self.assertEqual(keycode_to_str(261), KEY_RIGHT)

    def test_ascii_letters(self):
        """小写字母通过 chr() 直接转换。"""
        self.assertEqual(keycode_to_str(ord('w')), 'w')
        self.assertEqual(keycode_to_str(ord('p')), 'p')

    def test_unknown_returns_empty(self):
        self.assertEqual(keycode_to_str(-1), "")
        # 极大值/无效 keycode
        self.assertEqual(keycode_to_str(0xFFFFFFFF + 1), "")


class TestParseKeyDirectionKeys(unittest.TestCase):
    """FR-04：方向键 → TURN_UP/DOWN/LEFT/RIGHT。"""

    def test_up(self):
        self.assertEqual(parse_key(KEY_UP), Action.TURN_UP)

    def test_down(self):
        self.assertEqual(parse_key(KEY_DOWN), Action.TURN_DOWN)

    def test_left(self):
        self.assertEqual(parse_key(KEY_LEFT), Action.TURN_LEFT)

    def test_right(self):
        self.assertEqual(parse_key(KEY_RIGHT), Action.TURN_RIGHT)


class TestParseKeyWASD(unittest.TestCase):
    """FR-04：WASD 兼容键位。"""

    def test_w_is_up(self):
        self.assertEqual(parse_key(KEY_W), Action.TURN_UP)

    def test_a_is_left(self):
        self.assertEqual(parse_key(KEY_A), Action.TURN_LEFT)

    def test_s_is_down(self):
        self.assertEqual(parse_key(KEY_S), Action.TURN_DOWN)

    def test_d_is_right(self):
        self.assertEqual(parse_key(KEY_D), Action.TURN_RIGHT)


class TestParseKeySpecial(unittest.TestCase):
    """FR-16 / Q11：q 退出 + p 暂停。"""

    def test_q_quits(self):
        self.assertEqual(parse_key(KEY_QUIT), Action.QUIT)

    def test_p_pauses(self):
        self.assertEqual(parse_key(KEY_PAUSE), Action.PAUSE)


class TestParseKeyInvalid(unittest.TestCase):
    """非法键 → Action.NONE（NFR-04 忽略，不中断）。"""

    def test_random_letter_ignored(self):
        self.assertEqual(parse_key("x"), Action.NONE)
        self.assertEqual(parse_key("z"), Action.NONE)

    def test_digit_ignored(self):
        self.assertEqual(parse_key("1"), Action.NONE)
        self.assertEqual(parse_key("9"), Action.NONE)

    def test_symbol_ignored(self):
        self.assertEqual(parse_key("!"), Action.NONE)
        self.assertEqual(parse_key(" "), Action.NONE)

    def test_uppercase_w_ignored(self):
        """input.py 只接受小写 wasd；大写 W 应被忽略。"""
        self.assertEqual(parse_key("W"), Action.NONE)
        self.assertEqual(parse_key("P"), Action.NONE)

    def test_empty_string_ignored(self):
        self.assertEqual(parse_key(""), Action.NONE)


class TestActionEnumExhaustiveness(unittest.TestCase):
    """Action 枚举涵盖所有解析路径。"""

    def test_action_members(self):
        names = {a.name for a in Action}
        self.assertIn("TURN_UP", names)
        self.assertIn("TURN_DOWN", names)
        self.assertIn("TURN_LEFT", names)
        self.assertIn("TURN_RIGHT", names)
        self.assertIn("PAUSE", names)
        self.assertIn("QUIT", names)
        self.assertIn("NONE", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)