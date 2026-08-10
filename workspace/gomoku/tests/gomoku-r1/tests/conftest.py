"""pytest conftest for gomoku test suite (testplan §4 数据准备).

提供：
- 摆子函数 prefill：构造固定棋局
- 禁手判定对照表（≥10 例）
- 封堵棋局 10 组（横/竖/斜/边/角/中盘，覆盖多样性）
- fuzz 输入池（固定 seed）
- 中盘随机生成器（固定 seed）

约定：
- 所有坐标为 0-indexed ``(x, y)``，与 board.py 一致；
- 颜色字符 ``"B"`` / ``"W"``；
- ``Board`` 实例由 fixture 复用，避免重复构造。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import pytest

# ----------------------------------------------------------------------
# 让 import 能找到被测代码（test-developer 在 tests/ 子目录下，gomoku/
# 与代码仓平级）
# ----------------------------------------------------------------------
_CODE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "code" / "gomoku-r3"
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

from gomoku.board import Board, MoveError  # noqa: E402


# ----------------------------------------------------------------------
# 通用：摆子函数
# ----------------------------------------------------------------------
def prefill(
    size: int,
    placements: Iterable[Tuple[int, int, str]],
) -> Board:
    """构造一个 Board 并按 ``(x, y, color)`` 列表摆子。

    跳过已被占用的格子（返回 False）—— 用例构造通常保证不冲突。
    """
    b = Board(size)
    for x, y, c in placements:
        b.place(x, y, c)
    return b


# ----------------------------------------------------------------------
# 禁手判定对照表（testplan UTB-17；testplan §4）
# ----------------------------------------------------------------------
# 每例：(name, size, placements, target_xy, target_color, expected_forbidden, expected_reason, comment)
FORBIDDEN_TABLE: List[Tuple] = [
    # 1. 标准长连（六连）→ overline
    (
        "overline-horizontal",
        15,
        [(1, 7, "B"), (2, 7, "B"), (3, 7, "B"), (4, 7, "B"), (5, 7, "B")],
        (6, 7),
        "B",
        True,
        "overline",
        "横向已 5 子，落第 6 子成六连 → overline",
    ),
    # 2. 标准长连（竖直七连）→ overline
    (
        "overline-vertical",
        15,
        [(7, 1), (7, 2), (7, 3), (7, 4), (7, 5), (7, 6)],  # 占位 placeholder，下方覆盖
        (7, 7),
        "B",
        True,
        "overline",
        "竖直 6 子后落第 7 子 → overline",
    ),
    # 3. 双三（testplan 棋形 1）
    (
        "double-three-standard",
        15,
        [
            (5, 7, "B"), (6, 7, "B"),
            (7, 5, "B"), (7, 6, "B"),
        ],
        (7, 7),
        "B",
        True,
        "double_three",
        "testplan 棋形 1：横竖各成活三 → double-three",
    ),
    # 4. 双四（落 (7,7) 后横/竖各成 4 连延伸 1 但两侧有空 → 实际是冲四或活四的"双四"）
    (
        "double-four-rush",
        15,
        [
            (4, 7, "B"), (5, 7, "B"), (6, 7, "B"),  # 横 3 子
            (7, 4, "B"), (7, 5, "B"), (7, 6, "B"),  # 竖 3 子
        ],
        (7, 7),
        "B",
        True,
        "double_four",
        "落 (7,7) 后横/竖各 4 子（一端空一端边界）→ double-four",
    ),
    # 5. 五连优先于禁手（落 (7,7) 后横成五 + 竖成活三）
    (
        "five-overrides-forbidden",
        15,
        [
            (3, 7, "B"), (4, 7, "B"), (5, 7, "B"), (6, 7, "B"),
            (7, 5, "B"), (7, 6, "B"),
        ],
        (7, 7),
        "B",
        False,
        None,
        "成五优先于禁手；check_forbidden 返回合法（check_win 单独判定为 B 胜）",
    ),
    # 6. 白方永不触发禁手
    (
        "white-never-forbidden",
        15,
        [(5, 7, "W"), (6, 7, "W"), (7, 5, "W"), (7, 6, "W")],
        (7, 7),
        "W",
        False,
        None,
        "白方无禁手约束；同样棋形不触发",
    ),
    # 7. 跳活三 XX_X（不触发禁手——算法把 XX_X 视为冲四，单一四不构成双四）
    (
        "jump-three-no-forbidden",
        15,
        [(5, 7, "B"), (6, 7, "B"), (8, 7, "B")],
        (7, 7),
        "B",
        False,
        None,
        "横 XX_X 模式（3 子跳空），落 (7,7) 成 4 连（冲四/活四）+ 无另一四 → 不触发禁手",
    ),
    # 8. 单三 / 单四不触发禁手
    (
        "single-three-only",
        15,
        [(5, 7, "B"), (6, 7, "B")],  # 仅横活三
        (7, 7),
        "B",
        False,
        None,
        "仅横成活三（不含竖活三），非双三，合法",
    ),
    # 9. 普通活四（仅横活四、竖三）→ 非双四
    (
        "single-four-only",
        15,
        [(4, 7, "B"), (5, 7, "B"), (6, 7, "B"), (7, 6, "B")],
        (7, 7),
        "B",
        False,
        None,
        "落 (7,7) 后横活四、竖仅 3 子 → 单活四，非双四，合法",
    ),
    # 10. 双三异位（不在中心）：横 (5,9)(6,9) + 竖 (7,8)(7,10) → 落 (7,9) 同时横/竖活三
    (
        "double-three-off-mid",
        15,
        [
            (5, 9, "B"), (6, 9, "B"),  # 横 y=9 行
            (7, 8, "B"), (7, 10, "B"),  # 竖 x=7 列
        ],
        (7, 9),
        "B",
        True,
        "double_three",
        "横 (5,9)(6,9)(7,9) + 竖 (7,8)(7,9)(7,10) → 异位双三（不在中央）",
    ),
]

# 修正表 2 的占位 placeholder
FORBIDDEN_TABLE[1] = (
    "overline-vertical",
    15,
    [(7, 1, "B"), (7, 2, "B"), (7, 3, "B"), (7, 4, "B"), (7, 5, "B"), (7, 6, "B")],
    (7, 7),
    "B",
    True,
    "overline",
    "竖直 6 子后落第 7 子 → overline",
)


# ----------------------------------------------------------------------
# 封堵棋局 10 组（testplan UTA-03/04 + §4 多样性要求）
# ----------------------------------------------------------------------
# 每例：(name, placements, expected_block_xy, comment)
# 玩家执 W，"下一步可成冲四"或"已有活三"——AI（执 B）应封堵 expected_block_xy。
# 多样性覆盖：横/竖/斜各 ≥1、贴边线 ≥1、贴角部 ≥1、中盘异位若干。
BLOCK_RUSH_FOUR_CASES: List[Tuple[str, List[Tuple[int, int, str]], Tuple[int, int], str]] = [
    # 1. 横冲四（中盘）
    (
        "horizontal-rush-mid",
        [(3, 7, "W"), (4, 7, "W"), (5, 7, "W"), (2, 7, "B"), (6, 7, ".")],
        (6, 7),
        "横冲四：白 (3,7)(4,7)(5,7)，(2,7) 已被黑堵 → 落 (6,7) 即冲四，AI 应封 (6,7)",
    ),
    # 2. 竖冲四（中盘）
    (
        "vertical-rush-mid",
        [(7, 3, "W"), (7, 4, "W"), (7, 5, "W"), (7, 2, "B"), (7, 6, ".")],
        (7, 6),
        "竖冲四：白 (7,3)(7,4)(7,5)，(7,2) 黑堵 → 落 (7,6) 即冲四",
    ),
    # 3. 主对角线冲四
    (
        "diag1-rush",
        [(3, 3, "W"), (4, 4, "W"), (5, 5, "W"), (2, 2, "B"), (6, 6, ".")],
        (6, 6),
        "主对角线冲四：白 (3,3)(4,4)(5,5)，(2,2) 堵 → 落 (6,6) 即冲四",
    ),
    # 4. 副对角线冲四
    (
        "diag2-rush",
        [(5, 3, "W"), (6, 4, "W"), (7, 5, "W"), (4, 2, "B"), (8, 6, ".")],
        (8, 6),
        "副对角线冲四：白 (5,3)(6,4)(7,5)，(4,2) 堵 → 落 (8,6) 即冲四",
    ),
    # 5. 横冲四（贴边线）
    (
        "horizontal-rush-edge",
        [(0, 7, "W"), (1, 7, "W"), (2, 7, "W"), (3, 7, "B"), (4, 7, ".")],
        (4, 7),
        "横冲四贴边：白 (0,7)(1,7)(2,7)，(3,7) 黑堵 → 落 (4,7) 即冲四",
    ),
    # 6. 竖冲四（贴角部）
    (
        "vertical-rush-corner",
        [(0, 0, "W"), (0, 1, "W"), (0, 2, "W"), (0, 3, "B"), (0, 4, ".")],
        (0, 4),
        "竖冲四贴角：白 (0,0)(0,1)(0,2)，(0,3) 黑堵 → 落 (0,4) 即冲四",
    ),
    # 7. 主对角线冲四（贴边线）
    (
        "diag-rush-edge",
        [(0, 0, "W"), (1, 1, "W"), (2, 2, "W"), (3, 3, "B"), (4, 4, ".")],
        (4, 4),
        "主对角冲四贴边：白 (0,0)(1,1)(2,2)，(3,3) 黑堵 → 落 (4,4) 即冲四",
    ),
    # 8. 横冲四（异位 1）
    (
        "horizontal-rush-off-1",
        [(5, 5, "W"), (6, 5, "W"), (7, 5, "W"), (4, 5, "B"), (8, 5, ".")],
        (8, 5),
        "横冲四异位 1：白 (5,5)(6,5)(7,5)，(4,5) 黑堵 → 落 (8,5) 即冲四",
    ),
    # 9. 横冲四（异位 2）
    (
        "horizontal-rush-off-2",
        [(1, 10, "W"), (2, 10, "W"), (3, 10, "W"), (0, 10, "B"), (4, 10, ".")],
        (4, 10),
        "横冲四异位 2：白 (1,10)(2,10)(3,10)，(0,10) 黑堵 → 落 (4,10) 即冲四",
    ),
    # 10. 副对角线冲四（中盘异位）
    (
        "diag2-rush-off",
        [(2, 5, "W"), (3, 6, "W"), (4, 7, "W"), (1, 4, "B"), (5, 8, ".")],
        (5, 8),
        "副对角冲四中盘：白 (2,5)(3,6)(4,7)，(1,4) 黑堵 → 落 (5,8) 即冲四",
    ),
]

# 活三 10 组（AI 执 B 应封其一端或形成对玩家更大威胁）
BLOCK_LIVE_THREE_CASES: List[Tuple[str, List[Tuple[int, int, str]], str]] = [
    # 每例仅校验 AI 落点 ∈ 阻断关键点集（活三两端之一）或形成对 W 的活四/冲四
    # 关键点集：(x, y) ∈ 阻断候选
    # 1. 横活三（中盘）
    (
        "horizontal-live-mid",
        [(3, 7, "W"), (4, 7, "W"), (5, 7, "W")],
        "白横活三 (3,7)(4,7)(5,7)，两端 (2,7)(6,7) 空；AI 必封其一端",
    ),
    # 2. 竖活三（中盘）
    (
        "vertical-live-mid",
        [(7, 3, "W"), (7, 4, "W"), (7, 5, "W")],
        "白竖活三 (7,3)(7,4)(7,5)，两端 (7,2)(7,6) 空",
    ),
    # 3. 主对角活三
    (
        "diag1-live",
        [(3, 3, "W"), (4, 4, "W"), (5, 5, "W")],
        "主对角活三，两端 (2,2)(6,6) 空",
    ),
    # 4. 副对角活三
    (
        "diag2-live",
        [(5, 3, "W"), (6, 4, "W"), (7, 5, "W")],
        "副对角活三，两端 (4,2)(8,6) 空",
    ),
    # 5. 横活三（贴边）
    (
        "horizontal-live-edge",
        [(0, 7, "W"), (1, 7, "W"), (2, 7, "W")],
        "横活三贴边 (0,7)(1,7)(2,7)，一端越界，仅 (3,7) 可封",
    ),
    # 6. 横活三（贴角）
    (
        "horizontal-live-corner",
        [(0, 0, "W"), (1, 0, "W"), (2, 0, "W")],
        "横活三贴角 (0,0)(1,0)(2,0)，一端越界，仅 (3,0) 可封",
    ),
    # 7. 主对角活三（贴边）
    (
        "diag-live-edge",
        [(0, 0, "W"), (1, 1, "W"), (2, 2, "W")],
        "主对角活三贴边，仅 (3,3) 可封",
    ),
    # 8. 竖活三（异位 1）
    (
        "vertical-live-off-1",
        [(7, 5, "W"), (7, 6, "W"), (7, 7, "W")],
        "竖活三异位 (7,5)(7,6)(7,7)，两端 (7,4)(7,8) 空",
    ),
    # 9. 横活三（异位 2）
    (
        "horizontal-live-off-2",
        [(5, 9, "W"), (6, 9, "W"), (7, 9, "W")],
        "横活三异位 (5,9)(6,9)(7,9)，两端 (4,9)(8,9) 空",
    ),
    # 10. 副对角活三（中盘异位）
    (
        "diag2-live-off",
        [(2, 5, "W"), (3, 6, "W"), (4, 7, "W")],
        "副对角活三中盘 (2,5)(3,6)(4,7)，两端 (1,4)(5,8) 空",
    ),
]


# ----------------------------------------------------------------------
# fuzz 输入池（testplan §4；ST-11 用）
# ----------------------------------------------------------------------
def fuzz_input_pool(seed: int = 42, count: int = 100) -> List[str]:
    """生成固定 seed 的随机输入序列，覆盖合法/越界/占用/乱码/空/超长/中文/quit。

    为保证 ``count`` 条目，先按类别构造足够多的候选，再 shuffle + 截到 ``count``。
    """
    rng = random.Random(seed)
    pool: List[str] = []
    # 合法坐标（候选池：30 个）
    legal = [f"{chr(65 + rng.randint(0, 14))}{rng.randint(1, 15)}" for _ in range(30)]
    occupied = legal[:10]  # 用前 10 个表示已占
    pool.extend(legal)
    pool.extend(["P1", "Z9", "0,0", "A16", "16,1", "O16", "P16"])  # 越界（多）
    pool.extend(occupied)  # 占用（基于空盘 → 不真占，需后续注入）
    pool.extend(["asdf", "##", "1.5,3", "AA", "!", "@@@", "???", "x"])  # 格式错
    pool.extend(["", " ", "   ", "\t"])  # 空
    pool.extend(["A" * 25, "黑子", "한글", "テスト", "♠♣"])  # 超长/中文/韩文/日文
    pool.extend(["resign", "help", "save", "load", "undo"])  # 非 quit 命令字
    rng.shuffle(pool)
    # 截到 count（如果不足则再生成一次补充——理论上不会触发）
    if len(pool) < count:
        more_legal = [f"{chr(65 + rng.randint(0, 14))}{rng.randint(1, 15)}" for _ in range(count)]
        pool.extend(more_legal)
        rng.shuffle(pool)
    return pool[:count]


# ----------------------------------------------------------------------
# 中盘随机局面生成器（testplan §4；UTA-01/08 用）
# ----------------------------------------------------------------------
def random_midgame(
    size: int = 15,
    stones_each: int = 10,
    seed: int = 12345,
) -> Tuple[Board, List[Tuple[int, int]]]:
    """生成双方各 ``stones_each`` 子（黑先）的中盘局面，返回 board + 落子序列。

    保证不冲突、双方交替（黑先）、严格 ``stones_each`` × 2 子。
    """
    rng = random.Random(seed)
    b = Board(size)
    moves: List[Tuple[int, int]] = []
    color = "B"
    placed_each = {"B": 0, "W": 0}
    attempts = 0
    while placed_each["B"] < stones_each or placed_each["W"] < stones_each:
        x, y = rng.randint(0, size - 1), rng.randint(0, size - 1)
        if b.place(x, y, color):
            moves.append((x, y))
            placed_each[color] += 1
            color = "W" if color == "B" else "B"
        attempts += 1
        if attempts > size * size * 4:
            raise RuntimeError("random_midgame: too many collisions, seed too tight")
    return b, moves


# ----------------------------------------------------------------------
# pytest fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def fresh_board_15() -> Board:
    return Board(15)


@pytest.fixture
def fresh_board_13() -> Board:
    return Board(13)


@pytest.fixture
def forbidden_table():
    return FORBIDDEN_TABLE


@pytest.fixture
def block_rush_four_cases():
    return BLOCK_RUSH_FOUR_CASES


@pytest.fixture
def block_live_three_cases():
    return BLOCK_LIVE_THREE_CASES


@pytest.fixture
def fuzz_pool():
    return fuzz_input_pool()


@pytest.fixture
def midgame_board():
    b, _ = random_midgame(size=15, stones_each=10, seed=12345)
    return b


@pytest.fixture
def midgame_boards_5():
    """UTA-08 用：5 个中盘局面（双方各 20 子），固定 seed。"""
    return [random_midgame(size=15, stones_each=20, seed=seed)[0]
            for seed in (10001, 10002, 10003, 10004, 10005)]