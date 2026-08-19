"""Direction 枚举测试：dx/dy/opposite 配对正确。"""
import unittest
from game_core import Direction


class TestDirection(unittest.TestCase):
    def test_up_dx_dy(self):
        self.assertEqual(Direction.UP.dx, 0)
        self.assertEqual(Direction.UP.dy, -1)

    def test_down_dx_dy(self):
        self.assertEqual(Direction.DOWN.dx, 0)
        self.assertEqual(Direction.DOWN.dy, 1)

    def test_left_dx_dy(self):
        self.assertEqual(Direction.LEFT.dx, -1)
        self.assertEqual(Direction.LEFT.dy, 0)

    def test_right_dx_dy(self):
        self.assertEqual(Direction.RIGHT.dx, 1)
        self.assertEqual(Direction.RIGHT.dy, 0)

    def test_opposite_up_down(self):
        self.assertEqual(Direction.UP.opposite(), Direction.DOWN)
        self.assertEqual(Direction.DOWN.opposite(), Direction.UP)

    def test_opposite_left_right(self):
        self.assertEqual(Direction.LEFT.opposite(), Direction.RIGHT)
        self.assertEqual(Direction.RIGHT.opposite(), Direction.LEFT)

    def test_opposite_involutive(self):
        for d in Direction:
            self.assertEqual(d.opposite().opposite(), d)


if __name__ == "__main__":
    unittest.main()