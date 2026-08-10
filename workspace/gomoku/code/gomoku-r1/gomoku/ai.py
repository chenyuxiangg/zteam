"""ai.py — AI 决策层。

对应方案 §5.3（评估函数 + 候选点生成 + Alpha-Beta + 三档难度）/ §5.4（边界与异常）。

模块要素：
    SCORE:                模式 → 分值（方案 §5.3 / README §5.2）
    evaluate(board, c):   全盘静态评估（差值 = c_score - opp_score）
    evaluate_point(board, x, y, c): 单点评估（落子后）
    classify_point(board, x, y, c): 给出单点最关键模式
    candidates(board, color, ...):  邻域剪枝候选
    choose_move(board, color, diff, ...): 三档调度入口
    _alpha_beta(...):              迭代加深搜索

依赖：仅 board（标准库）；无第三方依赖，零依赖可玩（H6 / 退化基线）。
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, Iterable

from .board import Board


# ---- 评分表（方案 §5.3）----
#
# 分值档次按指数级拉开，避免双重 0.0 的相互抵消；具体数值是经验值。

SCORE: dict[str, int] = {
    "FIVE":       1_000_000,   # 5 连 = 胜
    "LIVE_FOUR":    100_000,   # 活四：下一步必成五
    "RUSH_FOUR":     10_000,   # 冲四
    "LIVE_THREE":     5_000,   # 活三
    "SLEEP_THREE":      500,
    "LIVE_TWO":         200,
    "SLEEP_TWO":         20,
    "ONE":                1,
}


# ---- 评估函数（方案 §5.3）----
#
# 实现：单点评估 evaluate_point；全盘评估 evaluate（按"局面已有棋子位置"做 4 方向扫描）。
# 模式归类：以 (x, y) 为中心，对 4 方向各取一段 9 窗口，按包含的 B-stone 数 + 两端开放
# 情况归类为 FIVE / LIVE_FOUR / RUSH_FOUR / LIVE_THREE / SLEEP_THREE / LIVE_TWO / SLEEP_TWO / ONE。

_DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


def _line_through_b(board: Board, x: int, y: int, dx: int, dy: int) -> str:
    """以 (x, y) 为中心，沿 (dx, dy) 取 9 字符，按 B 视角：
        B → 'B'; . → '.'; W or 越界 → '*' （阻挡）。
    """
    chars = []
    for k in range(-4, 5):
        nx, ny = x + dx * k, y + dy * k
        chars.append(_polar_cell_b(board, nx, ny))
    return "".join(chars)


def _polar_cell_b(board: Board, x: int, y: int) -> str:
    """B 视角的格子字符（仅用于评估模式识别，不修改棋盘）。"""
    if not (0 <= x < board.size and 0 <= y < board.size):
        return "*"
    c = board.cell(x, y)
    if c == "B":
        return "B"
    if c == ".":
        return "."
    return "*"


def _classify_line(line: str) -> str:
    """对 9 字符 line（含中心 B），返回最关键模式。

    中心 B 是 line 模拟的"我方刚下的子"或"棋盘已有 B"。
    模式归类按"全局最强者"：FIVE > LIVE_FOUR > RUSH_FOUR > LIVE_THREE > SLEEP_THREE > LIVE_TWO > SLEEP_TWO > ONE
    """
    # FIVE: 5+ B
    if line.count("B") >= 5:
        return "FIVE"
    # 找 LIVE_FOUR: 中心 B + 4 子（5 子含 B）span 5 且两端开放 → _XXXX_
    # 简化：枚举所有长度 5/6 包含中心的窗口
    best = "ONE"
    best_score = SCORE["ONE"]
    n = len(line)
    center = n // 2
    for win_len in (3, 4, 5, 6):
        s_lo = max(0, center - (win_len - 1))
        s_hi = min(n - win_len + 1, center + 1)
        for s in range(s_lo, s_hi):
            e = s + win_len
            w = line[s:e]
            if center not in range(s, e):
                continue
            if "*" in w:
                continue
            cat = _classify_window(w, line, s, e, n)
            if cat is None:
                continue
            score = SCORE.get(cat, 0)
            if score > best_score:
                best_score = score
                best = cat
    return best


def _classify_window(w: str, line: str, s: int, e: int, n: int) -> str | None:
    """对 line[s:e] 窗口分类。

    返回：
        None            窗口不足以归类
        'FIVE'/'LIVE_FOUR'/...  最强模式
    """
    b_count = w.count("B")
    if b_count == 0:
        return None
    if b_count >= 5:
        return "FIVE"
    if b_count == 4:
        # 4 B 含中心 → check 开放
        # 找最左 B 与最右 B 的下标
        first_b = w.index("B")
        last_b = len(w) - 1 - w[::-1].index("B")
        left = line[s - 1] if s - 1 >= 0 else "*"
        right = line[e] if e < n else "*"
        if left == "." and right == ".":
            return "LIVE_FOUR"
        if left == "." or right == ".":
            return "RUSH_FOUR"
        # 两端都被封（含边界）
        return "RUSH_FOUR"  # 4 子即使两端都封闭，威胁对方也能挡住一次，仍按 RUSH_FOUR 简化
    if b_count == 3:
        first_b = w.index("B")
        last_b = len(w) - 1 - w[::-1].index("B")
        # 两端开放
        left = line[s - 1] if s - 1 >= 0 else "*"
        right = line[e] if e < n else "*"
        if left == "." and right == ".":
            return "LIVE_THREE"
        # 一端开放一端封闭
        if left == "." or right == ".":
            return "SLEEP_THREE"
        # 都封闭 → 也按 SLEEP_THREE 简化
        return "SLEEP_THREE"
    if b_count == 2:
        first_b = w.index("B")
        last_b = len(w) - 1 - w[::-1].index("B")
        left = line[s - 1] if s - 1 >= 0 else "*"
        right = line[e] if e < n else "*"
        if left == "." and right == ".":
            return "LIVE_TWO"
        if left == "." or right == ".":
            return "SLEEP_TWO"
        return "SLEEP_TWO"
    if b_count == 1:
        return "ONE"
    return None


def evaluate_point(board: Board, x: int, y: int, color: str) -> int:
    """单点评估：模拟落 color 在 (x, y) 后，4 方向最关键模式之和。

    返回该点的分值（我方 - 对手 视角的差值，已等于该点本身的分值）。
    实际调用方通常对"我方落这点的得分"使用。
    """
    if not (0 <= x < board.size and 0 <= y < board.size):
        return 0
    if board.cell(x, y) != ".":
        return 0
    score = 0
    opp = "W" if color == "B" else "B"
    for dx, dy in _DIRECTIONS:
        my_line = _line_through_color(board, x, y, dx, dy, color)
        cat = _classify_line(my_line)
        score += SCORE.get(cat, 0)
    return score


def _line_through_color(board: Board, x: int, y: int, dx: int, dy: int, color: str) -> str:
    """以 color 视角构造 line（中心为 color）。"""
    chars = []
    for k in range(-4, 5):
        nx, ny = x + dx * k, y + dy * k
        chars.append(_polar_cell_color(board, nx, ny, color))
    s = "".join(chars)
    return s[:4] + color + s[5:]


def _polar_cell_color(board: Board, x: int, y: int, color: str) -> str:
    if not (0 <= x < board.size and 0 <= y < board.size):
        return "*"
    c = board.cell(x, y)
    if c == color:
        return color
    if c == ".":
        return "."
    return "*"


def evaluate(board: Board, color: str) -> int:
    """全盘静态评估：color_score - opp_score 的差值。

    对棋盘上每个 B / W 各做一次单点评估（对"该点已存在的子"扩展为 line 的中心）累加。
    简化实现：对所有非空格，沿 4 方向 each_dir 取 line，对该点视角做 _classify_line 累加。
    """
    opp = "W" if color == "B" else "B"
    my_score = 0
    opp_score = 0
    for y in range(board.size):
        for x in range(board.size):
            c = board.cell(x, y)
            if c == ".":
                continue
            for dx, dy in _DIRECTIONS:
                line = _line_through_color_at(board, x, y, dx, dy, c)
                cat = _classify_line(line)
                s = SCORE.get(cat, 0)
                # 因为同一模式被 4 个方向各识别一次，权重求和；为降低重复，
                # 实际方案中用单点中心扫描；此处采用简化双倍累加（性能影响小）。
                if c == color:
                    my_score += s // 2
                else:
                    opp_score += s // 2
    return my_score - opp_score


def _line_through_color_at(board: Board, x: int, y: int, dx: int, dy: int, color: str) -> str:
    """沿 (dx, dy) 取以 (x, y) 为中心的 9-line，center 已是 color。"""
    chars = []
    for k in range(-4, 5):
        nx, ny = x + dx * k, y + dy * k
        chars.append(_polar_cell_color(board, nx, ny, color))
    return "".join(chars)


# ---- 候选点生成（方案 §5.3）----


def candidates(board: Board, color: str, *, radius: int = 2, limit: int = 20, forbidden_check: bool = True) -> list[tuple[int, int]]:
    """邻域剪枝候选点。

    - 取所有已有棋子周围 radius 格内的空点；
    - 若全空（开局），返回中心点 (size/2, size/2)；
    - 按 (邻接 B 计数启发 + 单点最大模式分) 排序取前 limit；
    - 默认去除禁手点（forbidden_check=True）。

    返回候选点列表（按分数降序）。
    """
    empties = _empty_neighbors_of(board, color, radius)
    if not empties:
        # 全空：返回中心
        cx, cy = board.size // 2, board.size // 2
        return [(cx, cy)]
    scored = []
    opp = "W" if color == "B" else "B"
    for x, y in empties:
        if forbidden_check and color == "B" and board.check_forbidden(x, y, "B")[0]:
            continue
        # 启发：邻接 B 的数量 + 单点最大威胁分
        adj = _count_adjacent(board, x, y, color)
        my_score = evaluate_point(board, x, y, color)
        opp_score = evaluate_point(board, x, y, opp)
        # 简单加权：邻接数（最多 4） + 自身最佳分 + 对手最大威胁（防止对方活四等）
        heuristic = adj * 10 + my_score + int(opp_score * 1.1)
        scored.append((heuristic, x, y))
    scored.sort(reverse=True)
    return [(x, y) for _, x, y in scored[:limit]]


def _empty_neighbors_of(board: Board, color: str, radius: int) -> list[tuple[int, int]]:
    """收集所有非空格周围 radius 格内的空点。"""
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for y in range(board.size):
        for x in range(board.size):
            if board.cell(x, y) == ".":
                continue
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < board.size and 0 <= ny < board.size):
                        continue
                    if board.cell(nx, ny) != ".":
                        continue
                    if (nx, ny) in seen:
                        continue
                    seen.add((nx, ny))
                    out.append((nx, ny))
    return out


def _count_adjacent(board: Board, x: int, y: int, color: str) -> int:
    """统计 (x, y) 邻近 8 格中 color 的数量（最多 8）。"""
    cnt = 0
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if not (0 <= nx < board.size and 0 <= ny < board.size):
                continue
            if board.cell(nx, ny) == color:
                cnt += 1
    return cnt


# ---- 三档难度调度（方案 §5.3）----


def choose_move(
    board: Board,
    color: str,
    difficulty: str = "medium",
    *,
    time_budget: float | None = None,
    rng: random.Random | None = None,
) -> tuple[int, int] | None:
    """AI 落子入口。

    difficulty ∈ {"weak", "medium", "strong"}：
        weak    — 邻域候选 + 评估函数；不主动破坏己方进攻形（已通过 candidates 启发处理）
        medium  — 1 层威胁封堵 + 评估函数（先挡对手"下一步成五/冲四"再选最大）
        strong  — Alpha-Beta 迭代加深 + 候选剪枝 + 时间预算

    time_budget（秒）：仅 strong 档生效；超过则降级（按 SCORE 选当前最佳并返回）。
    rng：注入用于可复现（UTA-01）。

    返回落点 (x, y) 或 None（无合法点，如满盘）。
    """
    if rng is None:
        rng = random.Random()

    # 空盘回退
    has_stone = any(board.cell(x, y) != "." for y in range(board.size) for x in range(board.size))
    if not has_stone:
        cx, cy = board.size // 2, board.size // 2
        return (cx, cy)

    if difficulty == "weak":
        return _choose_weak(board, color, rng)
    if difficulty == "medium":
        return _choose_medium(board, color, rng)
    if difficulty == "strong":
        return _choose_strong(board, color, time_budget=time_budget, rng=rng)
    raise ValueError(f"Unknown difficulty: {difficulty!r}")


def _choose_weak(board: Board, color: str, rng: random.Random) -> tuple[int, int] | None:
    """弱档：候选剪枝 + 单点评估最大。"""
    cands = candidates(board, color, radius=2, limit=20)
    if not cands:
        return None
    return cands[0]  # candidates 已按启发分排序


def _choose_medium(board: Board, color: str, rng: random.Random) -> tuple[int, int] | None:
    """中档：先识别对手关键威胁，必堵；否则按评估函数最大。

    对手"下一步可成五/活四/冲四"的威胁点若有候选，必堵其一；其他情况同 weak。
    """
    opp = "W" if color == "B" else "B"
    opp_threat = _find_immediate_threat(board, opp)
    if opp_threat:
        # 我方候选里有这些点的，先选评分最高的一个
        cands = candidates(board, color, radius=2, limit=20)
        # 把威胁点全部放进候选并优先排序
        scored = []
        for x, y in cands:
            if (x, y) in opp_threat:
                scored.append((10_000_000, x, y))
            else:
                s = evaluate_point(board, x, y, color) + int(evaluate_point(board, x, y, opp) * 1.1)
                scored.append((s, x, y))
        scored.sort(reverse=True)
        return (scored[0][1], scored[0][2])
    # 默认 weak 路径
    return _choose_weak(board, color, rng)


def _find_immediate_threat(board: Board, color: str) -> set[tuple[int, int]]:
    """识别对手"下一步可成五/活四/冲四"的威胁点集合。"""
    threats: set[tuple[int, int]] = set()
    for y in range(board.size):
        for x in range(board.size):
            if board.cell(x, y) != ".":
                continue
            # 模拟放置后看是否产生 LIVE_FOUR / FIVE
            # 简化：调用 evaluate_point 但只看最大模式
            best = _best_pattern_at(board, x, y, color)
            if best in ("FIVE", "LIVE_FOUR", "RUSH_FOUR"):
                threats.add((x, y))
    return threats


def _best_pattern_at(board: Board, x: int, y: int, color: str) -> str:
    """模拟放置 color 在 (x,y) 后，4 方向最强的模式。"""
    best = "ONE"
    best_score = SCORE["ONE"]
    for dx, dy in _DIRECTIONS:
        line = _line_through_color(board, x, y, dx, dy, color)
        cat = _classify_line(line)
        s = SCORE.get(cat, 0)
        if s > best_score:
            best_score = s
            best = cat
    return best


# ---- 强档：Alpha-Beta 迭代加深 ----


def _choose_strong(
    board: Board,
    color: str,
    *,
    time_budget: float | None,
    rng: random.Random,
) -> tuple[int, int] | None:
    """强档：Alpha-Beta + 迭代加深 + 时间预算降级。"""
    deadline = None
    if time_budget is not None:
        deadline = time.monotonic() + time_budget
    best_move = None
    best_score = -math.inf
    # 迭代加深：depth 2 -> 4（与 README §5.3 / 方案 §5.3 一致）
    for depth in (2, 4):
        move, score = _alpha_beta_root(
            board, color, depth=depth, deadline=deadline, rng=rng,
        )
        if move is None:
            # 时间不够，返回当前最佳
            break
        if score > best_score:
            best_score = score
            best_move = move
        if deadline is not None and time.monotonic() > deadline:
            break
    return best_move


def _alpha_beta_root(
    board: Board,
    color: str,
    *,
    depth: int,
    deadline: float | None,
    rng: random.Random,
) -> tuple[tuple[int, int] | None, float]:
    """Alpha-Beta 根节点。返回 (best_move, best_score)。"""
    best_move: tuple[int, int] | None = None
    best_score = -math.inf
    alpha = -math.inf
    beta = math.inf

    opp = "W" if color == "B" else "B"
    cands = candidates(board, color, radius=2, limit=20)

    for x, y in cands:
        if deadline is not None and time.monotonic() > deadline:
            return (best_move, best_score)
        # 模拟落子
        board.place(x, y, color)
        score = -_alpha_beta(
            board, opp, depth=depth - 1, alpha=-beta, beta=-alpha,
            orig_color=color, deadline=deadline, rng=rng,
        )
        board.undo(x, y)
        if score > best_score:
            best_score = score
            best_move = (x, y)
            alpha = max(alpha, score)
    return (best_move, best_score)


def _alpha_beta(
    board: Board,
    color: str,
    *,
    depth: int,
    alpha: float,
    beta: float,
    orig_color: str,
    deadline: float | None,
    rng: random.Random,
) -> float:
    """Alpha-Beta 内部递归（negamax）。"""
    if deadline is not None and time.monotonic() > deadline:
        return 0.0  # 超时回退

    # 终止：depth == 0 → 评估
    if depth <= 0:
        return evaluate(board, orig_color)

    opp = "W" if color == "B" else "B"
    cands = candidates(board, color, radius=2, limit=20)
    if not cands:
        # 无候选 = 满盘
        return 0.0

    score_max = -math.inf
    for x, y in cands:
        if deadline is not None and time.monotonic() > deadline:
            break
        board.place(x, y, color)
        score = -_alpha_beta(
            board, opp, depth=depth - 1,
            alpha=-beta, beta=-alpha,
            orig_color=orig_color, deadline=deadline, rng=rng,
        )
        board.undo(x, y)
        if score > score_max:
            score_max = score
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    return score_max
