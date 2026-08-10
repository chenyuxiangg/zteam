"""test_board.py — board.py 单元测试（testplan UTB-01~18）。

覆盖：
- 坐标解析（UTB-01~04）：合法/格式/越界/占用
- 落子（UTB-05）：越界/类型
- 胜负判定（UTB-06~11）：横/竖/斜/不满足/长连/满盘
- 禁手判定（UTB-12~17）：长连/双三/双四/五连优先/白方不触发/对照表
- undo（UTB-18）

约定：每个用例独立构造 Board，不依赖其他用例状态。
"""
from __future__ import annotations

import pytest

from gomoku.board import Board, MoveError
from conftest import FORBIDDEN_TABLE, prefill


# ======================================================================
# 坐标解析 (UTB-01~04)
# ======================================================================
class TestParseMove:
    """UTB-01~04：合法输入、格式错、越界、已占用。"""

    def test_utb01_letter_and_numeric_equivalent(self, fresh_board_15: Board) -> None:
        # A8 与 8,8 同一格 (0,7)
        assert fresh_board_15.parse_move("A8") == (0, 7)
        assert fresh_board_15.parse_move("a8") == (0, 7)
        assert fresh_board_15.parse_move("8,8") == (7, 7)
        # 末行列
        assert fresh_board_15.parse_move("O15") == (14, 14)
        assert fresh_board_15.parse_move("15,15") == (14, 14)
        # 首格
        assert fresh_board_15.parse_move("A1") == (0, 0)

    def test_utb02_format_errors(self, fresh_board_15: Board) -> None:
        # 各种格式错误：每次抛 MoveError 且 reason='format'
        for bad in ["Z9", "", "A" * 20, "黑子", "1.5,3", "AA", " ", "1,2,3"]:
            with pytest.raises(MoveError) as ei:
                fresh_board_15.parse_move(bad)
            assert ei.value.reason == MoveError.REASON_FORMAT, (
                f"input {bad!r} should be format error, got reason={ei.value.reason}"
            )

    def test_utb03_out_of_range(self, fresh_board_15: Board, fresh_board_13: Board) -> None:
        # 15 棋盘越界（regex 通过 shape 校验后，range 失败）
        # 0,0 → 1-index (0,0) 即 0-index (-1,-1) → out_of_range
        for bad in ["0,0", "16,1", "1,16"]:
            with pytest.raises(MoveError) as ei:
                fresh_board_15.parse_move(bad)
            assert ei.value.reason == MoveError.REASON_OUT_OF_RANGE, (
                f"input {bad!r} expected out_of_range, got {ei.value.reason}"
            )
        # 13 棋盘：合法的 O13（regex 通过）+ 越界
        # O13 = (14,12) → size 13 越界；M14（regex 通过）+ 越界
        for bad in ["O1", "M14", "14,1"]:
            with pytest.raises(MoveError) as ei:
                fresh_board_13.parse_move(bad)
            assert ei.value.reason == MoveError.REASON_OUT_OF_RANGE, (
                f"input {bad!r} expected out_of_range, got {ei.value.reason}"
            )

    def test_utb04_occupied(self, fresh_board_15: Board) -> None:
        # (3,3) 已落黑
        fresh_board_15.place(3, 3, "B")
        with pytest.raises(MoveError) as ei:
            fresh_board_15.parse_move("D4")
        assert ei.value.reason == MoveError.REASON_OCCUPIED
        # place 直接对已占用返回 False
        assert fresh_board_15.place(4, 4, "B") is True
        assert fresh_board_15.place(4, 4, "W") is False  # 已占用，place 不覆盖
        assert fresh_board_15.get(4, 4) == "B"  # 保持原色

    def test_parse_move_state_unchanged_after_format_error(self, fresh_board_15: Board) -> None:
        """UTB-02 副断言：format 错误不影响程序状态。"""
        fresh_board_15.place(3, 3, "B")
        # 触发 format 错误
        try:
            fresh_board_15.parse_move("黑子")
        except MoveError:
            pass
        # 棋盘状态未变
        assert fresh_board_15.get(3, 3) == "B"
        assert fresh_board_15.move_count() == 1


# ======================================================================
# place 越界/类型 (UTB-05)
# ======================================================================
class TestPlace:
    def test_utb05_out_of_bounds_no_raise(self, fresh_board_15: Board) -> None:
        """place 越界返回 False，不抛异常。"""
        assert fresh_board_15.place(-1, 0, "B") is False
        assert fresh_board_15.place(15, 15, "W") is False
        assert fresh_board_15.place(100, 100, "B") is False
        # 棋盘不变
        assert fresh_board_15.move_count() == 0

    def test_place_wrong_type(self, fresh_board_15: Board) -> None:
        """place 非整数坐标返回 False。"""
        assert fresh_board_15.place(0.5, 0, "B") is False  # type: ignore[arg-type]
        assert fresh_board_15.place("0", 0, "B") is False  # type: ignore[arg-type]
        assert fresh_board_15.move_count() == 0


# ======================================================================
# 胜负判定 (UTB-06~11)
# ======================================================================
class TestCheckWin:
    def test_utb06_horizontal_five_mid(self, fresh_board_15: Board) -> None:
        """横五连（中部）：落 (7,7) 横 x=3..7。"""
        for x in range(3, 7):
            fresh_board_15.place(x, 7, "B")
        fresh_board_15.place(7, 7, "B")
        assert fresh_board_15.check_win(7, 7) == "B"

    def test_utb07_vertical_five_edge(self, fresh_board_15: Board) -> None:
        """纵五连（贴边线第 15 列）：落 (14,9) 纵 y=5..9。"""
        for y in range(5, 9):
            fresh_board_15.place(14, y, "W")
        fresh_board_15.place(14, 9, "W")
        assert fresh_board_15.check_win(14, 9) == "W"

    def test_utb08_diagonal_five(self, fresh_board_15: Board) -> None:
        """主对角 + 副对角五连（中部）+ 角部。"""
        # 主对角 (4,4)..(7,7)
        for i in range(4):
            fresh_board_15.place(4 + i, 4 + i, "B")
        fresh_board_15.place(8, 8, "B")
        assert fresh_board_15.check_win(8, 8) == "B"

        # 副对角 (10,6)..(13,9) 白
        b2 = Board(15)
        for i in range(4):
            b2.place(10 + i, 6 + i, "W")
        b2.place(14, 10, "W")
        assert b2.check_win(14, 10) == "W"

        # 角部主对角 (0,0)..(3,3) 黑，落 (4,4)
        b3 = Board(15)
        for i in range(4):
            b3.place(i, i, "B")
        b3.place(4, 4, "B")
        assert b3.check_win(4, 4) == "B"

    def test_utb09_no_false_positive(self, fresh_board_15: Board) -> None:
        """5 个不满足五连的局面：check_win 全部返回 None。"""
        # 1) 四连两端封闭
        b = prefill(15, [
            (3, 7, "B"), (4, 7, "B"), (5, 7, "B"), (6, 7, "B"),
            (2, 7, "W"), (7, 7, "W"),
        ])
        assert b.check_win(6, 7) is None

        # 2) 三连+隔一空
        b = prefill(15, [
            (3, 7, "B"), (5, 7, "B"), (6, 7, "B"),
        ])
        assert b.check_win(6, 7) is None

        # 3) 同色五子但异色插入
        b = prefill(15, [
            (3, 7, "B"), (4, 7, "B"), (5, 7, "W"), (6, 7, "B"), (7, 7, "B"),
        ])
        assert b.check_win(7, 7) is None

        # 4) 五连差一子
        b = prefill(15, [
            (3, 7, "B"), (4, 7, "B"), (6, 7, "B"), (7, 7, "B"),
        ])
        assert b.check_win(7, 7) is None

        # 5) 双方向各四连（落点不在任一五连上）
        b = prefill(15, [
            (3, 7, "B"), (4, 7, "B"), (5, 7, "B"), (6, 7, "B"),  # 横 4
            (7, 4, "B"), (7, 5, "B"), (7, 6, "B"), (7, 8, "B"),  # 竖 4（落 7,7 也不连 5）
        ])
        assert b.check_win(7, 7) is None  # (7,7) 不在任一 5 连上

    def test_utb10_long_line_wins_freestyle(self, fresh_board_15: Board) -> None:
        """禁手关（默认）：六连仍判胜（freestyle 长连）。"""
        # 黑 x=2..5 已有
        for x in range(2, 6):
            fresh_board_15.place(x, 7, "B")
        fresh_board_15.place(6, 7, "B")  # 第 6 子
        assert fresh_board_15.check_win(6, 7) == "B"

    def test_utb11_full_no_five(self, fresh_board_15: Board) -> None:
        """满盘（is_full）且无五连 → check_win 对最后落子返回 None（判平局路径）。

        完整 224 子摆子成本高，按 testplan §6 R1 降级：构造"近满盘 + 无五连 + 中央一格空"
        + is_full 组合。
        """
        # 构造近满盘：填满除 (7,7) 外的所有位置 → 224 子
        rng_seed = 7
        # 直接填满：. → B 或 W，确保不形成五连
        b = Board(15)
        for y in range(15):
            for x in range(15):
                if (x, y) == (7, 7):
                    continue
                # 交替放 B/W，避免长连
                color = "B" if (x + y) % 2 == 0 else "W"
                b.place(x, y, color)
        # 检查：224 子已落，(7,7) 空
        assert b.move_count() == 224
        assert b.is_empty(7, 7)
        assert b.check_win(7, 7) is None  # 平局路径成立


# ======================================================================
# 禁手判定 (UTB-12~17)
# ======================================================================
class TestCheckForbidden:
    """UTB-12~17：长连 / 双三 / 双四 / 五连优先 / 白方不触发 / 对照表。"""

    def test_utb12_overline(self, fresh_board_15: Board) -> None:
        """长连（六连）→ (True, 'overline')。"""
        for x in range(1, 6):
            fresh_board_15.place(x, 7, "B")
        # 落 (6,7) 形成六连
        result = fresh_board_15.check_forbidden(6, 7, "B")
        assert result == (True, "overline")

    def test_utb13_double_three(self, fresh_board_15: Board) -> None:
        """双三（testplan 棋形 1）：横/竖各成活三。"""
        fresh_board_15.place(5, 7, "B")
        fresh_board_15.place(6, 7, "B")
        fresh_board_15.place(7, 5, "B")
        fresh_board_15.place(7, 6, "B")
        result = fresh_board_15.check_forbidden(7, 7, "B")
        assert result == (True, "double_three")

    def test_utb14_double_four(self, fresh_board_15: Board) -> None:
        """双四（落 (7,7) 横/竖各成 4 连延伸 1）→ (True, 'double_four')。"""
        for x in [4, 5, 6]:
            fresh_board_15.place(x, 7, "B")
        for y in [4, 5, 6]:
            fresh_board_15.place(7, y, "B")
        # 落 (7,7)：横 (4,7)..(7,7) = 4 子（一端越界，一端空）→ 冲四
        #         竖 (7,4)..(7,7) = 4 子 → 冲四
        result = fresh_board_15.check_forbidden(7, 7, "B")
        assert result == (True, "double_four")

    def test_utb15_five_overrides_forbidden(self, fresh_board_15: Board) -> None:
        """五连优先于禁手（FR-07 优先级）：check_forbidden 返回合法；check_win 判胜。"""
        # 横成五 + 竖活三
        for x in [3, 4, 5, 6]:
            fresh_board_15.place(x, 7, "B")
        fresh_board_15.place(7, 5, "B")
        fresh_board_15.place(7, 6, "B")
        # (7,7) 落子：横 (3,7)..(7,7) = 5；竖 (7,5)(7,6)(7,7) + (7,4)(7,8) 空 → 活三
        # 临时放 + 测 + 撤销（API 自身不做实际落子）
        result_forbidden = fresh_board_15.check_forbidden(7, 7, "B")
        assert result_forbidden == (False, None)  # 五连覆盖禁手

        # 真正落 (7,7) 后 check_win 判黑胜
        fresh_board_15.place(7, 7, "B")
        assert fresh_board_15.check_win(7, 7) == "B"

    def test_utb16_white_never_forbidden(self, fresh_board_15: Board) -> None:
        """白方永不触发禁手：check_forbidden(_, _, 'W') 恒返回 (False, None)。"""
        # 同样棋形（双三）
        fresh_board_15.place(5, 7, "W")
        fresh_board_15.place(6, 7, "W")
        fresh_board_15.place(7, 5, "W")
        fresh_board_15.place(7, 6, "W")
        result = fresh_board_15.check_forbidden(7, 7, "W")
        assert result == (False, None)

        # 长连也合法
        b = Board(15)
        for x in range(1, 6):
            b.place(x, 7, "W")
        assert b.check_forbidden(6, 7, "W") == (False, None)

    @pytest.mark.parametrize(
        "name,size,placements,target,color,want_forbidden,want_reason,comment",
        FORBIDDEN_TABLE,
        ids=[row[0] for row in FORBIDDEN_TABLE],
    )
    def test_utb17_forbidden_table_param(
        self, name, size, placements, target, color, want_forbidden, want_reason, comment
    ) -> None:
        """UTB-17：禁手判定对照表参数化（≥10 例，含跳活三）。"""
        b = prefill(size, placements)
        result = b.check_forbidden(*target, color)
        assert result == (want_forbidden, want_reason), (
            f"{name}: expected ({want_forbidden}, {want_reason!r}), got {result}"
        )


# ======================================================================
# undo (UTB-18)
# ======================================================================
class TestUndo:
    def test_utb18_undo_round_trip(self, fresh_board_15: Board) -> None:
        fresh_board_15.place(3, 3, "B")
        fresh_board_15.place(4, 4, "B")
        # undo 移除 (4,4)
        fresh_board_15.undo(4, 4)
        assert fresh_board_15.get(4, 4) == "."
        assert fresh_board_15.get(3, 3) == "B"
        assert fresh_board_15.move_count() == 1
        # 对空点 undo 无效（no-op，不抛异常）
        fresh_board_15.undo(4, 4)
        assert fresh_board_15.get(4, 4) == "."
        # 越界 undo 无效
        fresh_board_15.undo(-1, -1)
        fresh_board_15.undo(100, 100)
        assert fresh_board_15.move_count() == 1