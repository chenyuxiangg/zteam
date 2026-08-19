"""Point 值对象测试：相等性、哈希、可哈希。"""
import unittest
from game_core import Point


class TestPoint(unittest.TestCase):
    def test_equal_same_coords(self):
        self.assertEqual(Point(1, 2), Point(1, 2))

    def test_not_equal_diff_coords(self):
        self.assertNotEqual(Point(1, 2), Point(2, 1))

    def test_hashable(self):
        s = {Point(0, 0), Point(0, 1), Point(0, 0)}
        self.assertEqual(len(s), 2)

    def test_frozen(self):
        p = Point(3, 4)
        with self.assertRaises(Exception):
            p.x = 5  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()