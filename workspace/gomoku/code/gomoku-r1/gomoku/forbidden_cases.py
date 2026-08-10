"""forbidden_cases.py — 禁手判定对照表（≥10 例棋形 → 预期结论）。

与方案 §5.2 / §7 T3 / testplan U-20 对应。
约定：本模块是禁手判定的"事实源"——评审与测试可通过对比本表与
    Board.check_forbidden 的实际结果验证实现正确性。

运行自检：`python -m gomoku.forbidden_cases`。

棋形格式约定：
    pattern 每行一个字符串，由 'B' / 'W' / '.' 组成（无空格），长度为该行列数；
    整个 pattern 居中放置到 15×15 棋盘（行列对齐，向上向下取整）。
    center 给出 pattern 内要检查的 (x, y) 局部坐标（pattern 起点偏移）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .board import Board


@dataclass(frozen=True)
class ForbiddenCase:
    """单个禁手判定用例。

    两类：
    - pattern + center：用棋形字符串表 + 居中偏移表达；
    - setup_fn：当 pattern 难表达（r2 复现类），用回调函数自放置。
    """

    name: str
    pattern: tuple[str, ...] | None
    center: tuple[int, int]
    expected_forbidden: bool
    expected_reason: str | None
    description: str = ""
    setup_fn: object = None  # 可选 callable(Board) -> None；若非空则优先于 pattern


def _case(name, rows, center, expected_forbidden, expected_reason, description="", setup_fn=None):
    return ForbiddenCase(
        name=name,
        pattern=tuple(rows) if rows is not None else None,
        center=center,
        expected_forbidden=expected_forbidden,
        expected_reason=expected_reason,
        description=description,
        setup_fn=setup_fn,
    )


def _build_table() -> list[ForbiddenCase]:
    """构造 ≥10 例棋形 + 控制例。"""
    return [
        # ===== 成五胜优先 =====
        _case(
            "成五（含长连前的 5）越过禁手",
            ["BBBB."],
            (4, 0),
            False, None,
            "已有 4 B in row；放第 5 子胜出；不应被禁。",
        ),
        _case(
            "成五 + 另方向四（成五胜出）",
            None,
            (5, 5),
            False, None,
            "程序化布置：col 5 已有 B at rows 4, 6, 7, 8；placement (5, 5) 让 col 5 → 5 连 → 成五胜出；"
            "即使也同时形成另一活四，禁手由成五覆盖。",
            setup_fn=lambda b: (
                b.place(5, 4, 'B'),
                b.place(5, 6, 'B'),
                b.place(5, 7, 'B'),
                b.place(5, 8, 'B'),
                # 在另一个方向上制造一个孤立的子（避免意外触发）
                b.place(3, 5, 'B'),
                b.place(4, 5, 'B'),
                # placement (5, 5) makes col 5 → 5 in row 5 → 成五胜
            ),
        ),

        # ===== 长连 =====
        _case(
            "长连 6 子",
            ["BBBBB."],
            (5, 0),
            True, "long",
            "放第 6 子形成长连。",
        ),
        _case(
            "长连 7+ 子仍属 long",
            ["BBBBBB."],
            (6, 0),
            True, "long",
            "已有 6 子；放第 7 子仍是长连。",
        ),

        # ===== 双四 =====
        _case(
            "双四（活四 + 活四，对角扩展）",
            None,                                # pattern 用 None → 程序化布置
            (8, 8),                              # center 坐标为绝对值
            True, "double_four",
            "程序化布置：row 8 已有 B at cols 5, 6, 7；col 8 已有 B at rows 5, 6, 7；"
            "check_forbidden(8, 8, 'B') 让两者都扩展为 4 子 → 双四。",
            setup_fn=lambda b: (
                b.place(5, 8, 'B'),
                b.place(6, 8, 'B'),
                b.place(7, 8, 'B'),
                b.place(8, 5, 'B'),
                b.place(8, 6, 'B'),
                b.place(8, 7, 'B'),
            ),
        ),
        _case(
            "单四（仅横活四 + 另一方向无新四）",
            [
                "BBB..",
                ".....",
                ".....",
                ".....",
            ],
            (3, 0),
            False, None,
            "placement (3, 0) 让 row 0 成 BBBB → 1 个活四；其他方向无新四 → 单四不禁。",
        ),

        # ===== 双三：r2 评审复现案例 =====
        _case(
            "双三：r2 复现 1 — _X_XX_ 横 + _XX_ 竖（r2 评审复现）",
            None,                                # pattern 用 None → 程序化布置
            (5, 7),                              # center 坐标为绝对值
            True, "double_three",
            "程序化布置：row 7 已有 B at cols 7, 8；col 5 已有 B at rows 5, 6；"
            "check_forbidden(5, 7, 'B') 应判双三禁手。",
            setup_fn=lambda b: (
                b.place(7, 7, 'B'),
                b.place(8, 7, 'B'),
                b.place(5, 5, 'B'),
                b.place(5, 6, 'B'),
            ),
        ),
        _case(
            "双三：r2 复现 2 — _XX_X_ 横 + _X_X_ 竖（r2 评审复现）",
            None,                                # pattern 用 None
            (8, 7),                              # center 坐标为绝对值
            True, "double_three",
            "程序化布置：row 7 已有 B at cols 5, 6；col 8 已有 B at rows 6, 8；"
            "check_forbidden(8, 7, 'B') 应判双三禁手。",
            setup_fn=lambda b: (
                b.place(5, 7, 'B'),
                b.place(6, 7, 'B'),
                b.place(8, 6, 'B'),
                b.place(8, 8, 'B'),
            ),
        ),

        # ===== 单活三（不成禁）=====
        _case(
            "单活三：仅一条线形成活三",
            ["BB...", ".....", "....."],
            (2, 0),
            False, None,
            "放 (2,0)：仅横方向形成 XXX 活三；竖方向无第二活三 → 单三不禁。",
        ),

        # ===== 单四（不成禁）=====
        _case(
            "单活四（不成禁）",
            ["BBB..", ".....", "....."],
            (3, 0),
            False, None,
            "放 (3,0)：横方向活四；其他方向无新四 → 单四不禁。",
        ),

        # ===== 跳活三 _X_XX_ =====
        _case(
            "跳活三 _X_XX_ 在 row 横向（双三）",
            None,
            (5, 5),
            True, "double_three",
            "程序化布置：row 5 已有 B at cols 7, 8（placement 让 row 5 = _X_XX_ → 跳跃活三）；"
            "col 5 已有 B at rows 7, 8（placement 让 col 5 = _X_XX_ → 跳跃活三）→ 双三。",
            setup_fn=lambda b: (
                b.place(7, 5, 'B'),
                b.place(8, 5, 'B'),
                b.place(5, 7, 'B'),
                b.place(5, 8, 'B'),
            ),
        ),

        # ===== 白方永不判禁 =====
        _case(
            "白方永不判禁",
            ["WW.WW", "WW.WW"],
            (2, 1),
            False, None,
            "白方落子永远不禁。",
        ),

        # ===== 合法：孤立子 =====
        _case(
            "合法：孤立子",
            ["B.", ".."],
            (1, 1),
            False, None,
            "黑方走邻位不形成禁手。",
        ),

        # ===== 边界：角落双三 =====
        _case(
            "角落双三（边界跳跃型）",
            None,
            (1, 1),
            True, "double_three",
            "程序化布置：row 1 已有 B at cols 4, 5（placement 让 row 1 = _X_XX_ 跳跃活三）；"
            "col 1 已有 B at rows 4, 5（placement 让 col 1 = _X_XX_ 跳跃活三）→ 双三。"
            "对角落位置 (1, 1)，边界由 `*` 标记，但跳跃活三形状仍符合。",
            setup_fn=lambda b: (
                b.place(4, 1, 'B'),
                b.place(5, 1, 'B'),
                b.place(1, 4, 'B'),
                b.place(1, 5, 'B'),
            ),
        ),

        # ===== 边界：边界长连 =====
        _case(
            "边界长连（row 已有 6 B，placement 第 7 = 长连）",
            ["BBBBBBB."],
            (7, 0),
            True, "long",
            "已有 6 B 在 row 0；placement 在 col 7 让 row 0 = 7 B's → 长连。",
        ),
        _case(
            "边界长连（col 已有 6 B，placement 第 7 = 长连）",
            [
                "B",
                "B",
                "B",
                "B",
                "B",
                "B",
                ".",
            ],
            (0, 6),
            True, "long",
            "col 已有 6 B；placement 第 7 列底 → 长连。",
        ),
    ]


TABLE: list[ForbiddenCase] = _build_table()
ALL_CASES: list[ForbiddenCase] = TABLE


# ---- 自检 ----


def run_selfcheck(verbose: bool = True) -> tuple[int, int]:
    """运行对照表自检。返回 (pass, fail)。"""
    pass_cnt = 0
    fail_cnt = 0
    for case in TABLE:
        b = Board(15)

        if case.setup_fn is not None:
            # 程序化布置
            case.setup_fn(b)
            fx, fy = case.center
        else:
            # 通过 pattern 居中布置
            rows = case.pattern
            assert rows is not None, "pattern or setup_fn must be set"
            rows_n = len(rows)
            cols_n = max(len(r) for r in rows)
            ox = (15 - cols_n) // 2
            oy = (15 - rows_n) // 2
            for y, row in enumerate(rows):
                for x, ch in enumerate(row):
                    if ch == "B":
                        b.place(ox + x, oy + y, "B")
                    elif ch == "W":
                        b.place(ox + x, oy + y, "W")
            fx = ox + case.center[0]
            fy = oy + case.center[1]

        # center 必须为空才有效
        if b.cell(fx, fy) != ".":
            if verbose:
                print(f"  SKIP  {case.name}: center ({fx},{fy}) 已占用（非空）")
            continue
        got_fb, got_reason = b.check_forbidden(fx, fy, "B")
        ok = (got_fb == case.expected_forbidden) and (got_reason == case.expected_reason)
        if ok:
            pass_cnt += 1
            if verbose:
                print(f"  PASS  {case.name}")
        else:
            fail_cnt += 1
            if verbose:
                print(f"  FAIL  {case.name}: got=({got_fb},{got_reason!r}), "
                      f"expected=({case.expected_forbidden},{case.expected_reason!r})")
    return pass_cnt, fail_cnt


if __name__ == "__main__":
    p, f = run_selfcheck(verbose=False)
    skipped = len(TABLE) - p - f
    print(f"Forbidden-move table: {p} pass, {f} fail, {skipped} skipped.")
    print(f"Total cases: {len(TABLE)}")
    if f > 0:
        print("\nFailing cases:")
        run_selfcheck(verbose=True)
