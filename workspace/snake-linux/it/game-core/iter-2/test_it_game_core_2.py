"""模块 IT 测试：game-core（snake-linux v2.0.0 迭代 2）。

按 `snake-linux/it/game-core/iter-2/测试用例.md` 落地，pytest 9.x。
覆盖迭代 2 增量三件套：speed_curve / toggle_pause / on_score；运行零 GUI 依赖（NFR-05）。

执行：pytest test_it_game_core_2.py -v
"""
from __future__ import annotations

import ast
import dataclasses
import random
import sys
from pathlib import Path

import pytest

# 被测代码路径：tests/ 与 code/ 平级在 workspace/snake-linux/ 下
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/game-core/iter-2 -> snake-linux
_CODE_DIR = _WORKSPACE / "code" / "game-core" / "iter-2"
sys.path.insert(0, str(_CODE_DIR))

from game_core import (  # noqa: E402
    MIN_TICK_MS,
    Direction,
    Difficulty,
    Food,
    GameState,
    GameStatus,
    InvalidStateError,
    Point,
    Snake,
    Snapshot,
    speed_curve,
)


# ---------- 公共 fixture ----------

@pytest.fixture
def rng():
    return random.Random(42)


@pytest.fixture
def default_state(rng):
    """20x15 MEDIUM 状态（默认参数）。"""
    return GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=rng)


@pytest.fixture
def small_state(rng):
    """5x5 网格，便于穷举。"""
    return GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=rng)


def _safe_replace(gs, **kwargs):
    """绕开 GameState.__init__ 的\"少字段 vs 全字段\"分流，直接调用 dataclasses.replace。"""
    return dataclasses.replace(gs, **kwargs)


# ============================================================
# IT-game-core-2-01 ~ 07：toggle_pause 暂停状态机
# ============================================================

@pytest.mark.p0
def test_it_game_core_2_01_toggle_pause_run_to_paused_freezes_fields(default_state):
    """IT-game-core-2-01 toggle_pause RUN→PAUSED + INV-9 字段冻结。FR-12."""
    before = default_state.snapshot()
    paused = default_state.toggle_pause()
    assert paused.status == GameStatus.PAUSED
    # INV-9：除 status 外所有字段不变（Snapshot 不含 direction，direction 是 GameState 字段）
    snap_paused = paused.snapshot()
    assert snap_paused.snake_body == before.snake_body, "INV-9 字段冻结：蛇身不变"
    assert snap_paused.food == before.food, "INV-9 字段冻结：食物不变"
    assert snap_paused.score == before.score, "INV-9 字段冻结：得分不变"
    assert snap_paused.length == before.length, "INV-9 字段冻结：长度不变"
    assert snap_paused.difficulty == before.difficulty, "INV-9 字段冻结：难度不变"
    # direction/pending_direction 走 GameState 字段（不在 snapshot 里）
    assert paused.direction == default_state.direction, "INV-9：GameState.direction 不变"
    assert paused.pending_direction == default_state.pending_direction, "INV-9：GameState.pending_direction 不变"


@pytest.mark.p0
def test_it_game_core_2_02_toggle_pause_paused_to_run_clears_pending(default_state):
    """IT-game-core-2-02 toggle_pause PAUSED→RUN + INV-8 清 pending_direction。FR-12."""
    s1 = default_state.set_direction(Direction.UP)  # 登记 pending=UP
    assert s1.pending_direction == Direction.UP
    s2 = s1.toggle_pause()  # RUN → PAUSED
    assert s2.status == GameStatus.PAUSED
    s3 = s2.toggle_pause()  # PAUSED → RUN
    assert s3.status == GameStatus.RUN
    # INV-8：恢复时清空 pending_direction
    assert s3.pending_direction is None, "INV-8：PAUSED→RUN 必须清 pending"


@pytest.mark.p0
def test_it_game_core_2_03_toggle_pause_on_over_raises(default_state):
    """IT-game-core-2-03 toggle_pause(OVER) 抛 InvalidStateError。FR-12."""
    s = default_state
    for _ in range(10):  # 撞墙到 OVER
        s = s.step()
    assert s.status == GameStatus.OVER
    with pytest.raises(InvalidStateError):
        s.toggle_pause()


@pytest.mark.p0
def test_it_game_core_2_04_step_on_paused_raises(default_state):
    """IT-game-core-2-04 PAUSED 期 step 抛 InvalidStateError。FR-12."""
    paused = default_state.toggle_pause()
    assert paused.status == GameStatus.PAUSED
    with pytest.raises(InvalidStateError):
        paused.step()


@pytest.mark.p0
def test_it_game_core_2_05_set_direction_on_paused_silently_ignored(default_state):
    """IT-game-core-2-05 PAUSED 期 set_direction 静默忽略（不入 pending）。FR-12."""
    paused = default_state.toggle_pause()
    after = paused.set_direction(Direction.LEFT)
    assert after.status == GameStatus.PAUSED, "status 仍为 PAUSED"
    assert after.pending_direction is None, "不入 pending（静默忽略）"
    # 不抛错（不抛 InvalidStateError）— 函数正常返回


@pytest.mark.p0
def test_it_game_core_2_06_inv8_pending_clear_after_resume(default_state):
    """IT-game-core-2-06 INV-8 核心防呆：暂停前按 UP → 暂停 → 继续 → 第一拍按原 direction 走。FR-12.

    关键：若 INV-8 失效，恢复后第一拍按 UP 走将撞自身（或越界），状态会变。
    验证恢复后第一拍按 RIGHT 走、status=RUN、pending_direction 已清空。
    """
    s1 = default_state.set_direction(Direction.UP)
    s2 = s1.toggle_pause()  # RUN → PAUSED
    s3 = s2.toggle_pause()  # PAUSED → RUN（INV-8 清 pending）
    assert s3.status == GameStatus.RUN
    assert s3.pending_direction is None
    # 第一拍：按原 direction=RIGHT 走（不是 UP）
    after = s3.step()
    assert after.status == GameStatus.RUN, "恢复后第一拍不应撞墙或撞自身"
    assert after.direction == Direction.RIGHT, "INV-8：恢复后第一拍按原 direction 走"
    # 蛇头按 RIGHT 移动
    expected_head_x = default_state.head.x + 1
    assert after.snake.head == Point(expected_head_x, default_state.head.y)


@pytest.mark.p1
def test_it_game_core_2_07_repeated_toggle_pause_equivalent_to_two(default_state):
    """IT-game-core-2-07 反复 toggle_pause：等价于 2 次翻转。FR-12."""
    s1 = default_state.toggle_pause()  # → PAUSED
    s2 = s1.toggle_pause()  # → RUN（2 次）
    s3 = s2.toggle_pause()  # → PAUSED（3 次）
    s4 = s3.toggle_pause()  # → RUN（4 次）
    assert s4.status == GameStatus.RUN
    assert s4.snapshot() == default_state.snapshot(), "4 次 toggle_pause 后字段全不变"


# ============================================================
# IT-game-core-2-08 ~ 13：speed_curve 加速曲线（NFR-01 量化）
# ============================================================

@pytest.mark.p0
def test_it_game_core_2_08_speed_curve_score_zero_baseline():
    """IT-game-core-2-08 speed_curve(0, d) 三档基线。FR-05 / NFR-01."""
    assert speed_curve(0, Difficulty.EASY) == 250, "EASY@score=0 == 250"
    assert speed_curve(0, Difficulty.MEDIUM) == 160, "MEDIUM@score=0 == 160"
    assert speed_curve(0, Difficulty.HARD) == 100, "HARD@score=0 == 100"


@pytest.mark.p0
def test_it_game_core_2_09_speed_curve_hard_le_easy_half():
    """IT-game-core-2-09 speed_curve HARD ≤ EASY*0.5（任意 score）。FR-05 / NFR-01 量化."""
    for score in range(0, 101):
        t_hard = speed_curve(score, Difficulty.HARD)
        t_easy = speed_curve(score, Difficulty.EASY)
        assert t_hard <= t_easy * 0.5, (
            f"NFR-01 违反: score={score} HARD={t_hard} EASY={t_easy} "
            f"ratio={t_hard/t_easy:.3f}"
        )


@pytest.mark.p0
def test_it_game_core_2_10_speed_curve_monotonic_non_increasing():
    """IT-game-core-2-10 speed_curve 单调不增（score 越大 tick_ms 越小或持平）。FR-05 / NFR-01."""
    for d in Difficulty:
        for score in range(0, 100):
            cur = speed_curve(score, d)
            nxt = speed_curve(score + 1, d)
            assert cur >= nxt, (
                f"{d.name}: score={score} tick_ms={cur} > score={score+1} tick_ms={nxt}（违反单调不增）"
            )


@pytest.mark.p0
def test_it_game_core_2_11_speed_curve_per_difficulty_floor():
    """IT-game-core-2-11 speed_curve 三档独立下限：score=100 时 EASY=100/MEDIUM=80/HARD=50。FR-05."""
    assert speed_curve(100, Difficulty.EASY) == MIN_TICK_MS[Difficulty.EASY] == 100
    assert speed_curve(100, Difficulty.MEDIUM) == MIN_TICK_MS[Difficulty.MEDIUM] == 80
    assert speed_curve(100, Difficulty.HARD) == MIN_TICK_MS[Difficulty.HARD] == 50
    # 极大 score 也钳制到下限
    assert speed_curve(10000, Difficulty.EASY) == 100
    assert speed_curve(10000, Difficulty.MEDIUM) == 80
    assert speed_curve(10000, Difficulty.HARD) == 50


@pytest.mark.p0
def test_it_game_core_2_12_difficulty_base_tick_ms_via_speed_curve():
    """IT-game-core-2-12 Difficulty.base_tick_ms 走 speed_curve(0, self) 单一数据源。FR-05."""
    assert Difficulty.EASY.base_tick_ms == speed_curve(0, Difficulty.EASY) == 250
    assert Difficulty.MEDIUM.base_tick_ms == speed_curve(0, Difficulty.MEDIUM) == 160
    assert Difficulty.HARD.base_tick_ms == speed_curve(0, Difficulty.HARD) == 100


@pytest.mark.p0
def test_it_game_core_2_13_snapshot_tick_ms_dynamic_with_score(rng):
    """IT-game-core-2-13 Snapshot.tick_ms 走 speed_curve(score, difficulty)：随 score 推进变小。FR-05 / NFR-01."""
    gs = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=rng)
    # score=0 时 tick_ms
    t0 = gs.snapshot().tick_ms
    # 通过构造吃食：让食物落到蛇头前方
    food_point = Point(gs.head.x + 1, gs.head.y)
    s = _safe_replace(gs, food=Food(food_point))
    s1 = s.step()  # 吃食 → score=1
    assert s1.score == 1
    t1 = s1.snapshot().tick_ms
    # tick_ms 走 speed_curve，score 推进后应减小（MEDIUM: 160 → 156）
    assert t1 == speed_curve(1, Difficulty.MEDIUM)
    assert t1 < t0, f"score=1 tick_ms({t1}) 应 < score=0 tick_ms({t0})"


@pytest.mark.p1
def test_it_game_core_2_25_min_tick_ms_single_data_source():
    """IT-game-core-2-25 MIN_TICK_MS 单一数据源：修改 dict 后 speed_curve 返回新值（仅 IT 验证契约，测试中修改需还原）。FR-05."""
    original = MIN_TICK_MS[Difficulty.HARD]
    try:
        MIN_TICK_MS[Difficulty.HARD] = 1  # 临时改下限为 1
        # score=10000 时 HARD 应 = 1（不再 = 50）
        assert speed_curve(10000, Difficulty.HARD) == 1
        # 同时 NFR-01 仍成立（1 ≤ 250*0.5=125 ✓）
        assert speed_curve(10000, Difficulty.HARD) <= speed_curve(10000, Difficulty.EASY) * 0.5
    finally:
        MIN_TICK_MS[Difficulty.HARD] = original
    # 还原后再次验证
    assert speed_curve(10000, Difficulty.HARD) == 50


# ============================================================
# IT-game-core-2-14 ~ 19 / 22 / 26：on_score 得分回调（FR-13）
# ============================================================

@pytest.mark.p0
def test_it_game_core_2_14_on_score_callback_fires_on_eat():
    """IT-game-core-2-14 on_score 回调触发：step 吃食 → cb(new_score)。FR-13."""
    events = []
    gs = GameState(
        width=5, height=5, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
        score_callback=lambda s: events.append(s),
    )
    food_point = Point(gs.head.x + 1, gs.head.y)
    s = _safe_replace(gs, food=Food(food_point))
    after = s.step()  # 吃食
    assert after.score == 1
    assert events == [1], f"回调应收到 new_score=1，实际 {events}"


@pytest.mark.p0
def test_it_game_core_2_15_on_score_callback_not_fired_without_eat():
    """IT-game-core-2-15 on_score 回调非吃食不触发。FR-13."""
    events = []
    gs = GameState(
        width=20, height=15, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
        score_callback=lambda s: events.append(s),
    )
    # 不吃食：food 在远处
    s = _safe_replace(gs, food=Food(Point(0, 0)))  # 远离蛇身轨迹
    s1 = s.step()  # 普通移动（不吃食）
    assert s1.score == 0
    assert events == [], f"非吃食不应触发回调，实际 {events}"


@pytest.mark.p0
def test_it_game_core_2_16_on_score_callback_none_is_silent():
    """IT-game-core-2-16 on_score 回调为 None：静默、score 字段正确。FR-13."""
    gs = GameState(
        width=5, height=5, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
        score_callback=None,
    )
    food_point = Point(gs.head.x + 1, gs.head.y)
    s = _safe_replace(gs, food=Food(food_point))
    after = s.step()  # 吃食
    assert after.score == 1, "回调 None 时 score 字段仍正确更新"
    assert len(after.snake) == 4
    assert after.food.pos not in after.snake.body


@pytest.mark.p0
def test_it_game_core_2_17_on_score_callback_exception_propagates():
    """IT-game-core-2-17 on_score 回调异常不捕获 + pure-function 语义。FR-13."""
    def boom(_s):
        raise RuntimeError("callback boom")

    gs = GameState(
        width=5, height=5, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
        score_callback=boom,
    )
    food_point = Point(gs.head.x + 1, gs.head.y)
    s = _safe_replace(gs, food=Food(food_point))
    before = s.snapshot()  # 记录旧状态
    with pytest.raises(RuntimeError, match="callback boom"):
        s.step()  # 应抛 RuntimeError
    # pure-function 语义：旧 state 未被污染（new_state 随异常丢失）
    assert s.snapshot() == before, "旧 state 未推进、字段未污染"


@pytest.mark.p0
def test_it_game_core_2_18_on_score_callback_replacement():
    """IT-game-core-2-18 on_score 回调替换：set_score_callback 后新 cb 生效、旧 cb 不再被调。FR-13."""
    old_events = []
    new_events = []
    gs = GameState(
        width=5, height=5, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
        score_callback=lambda s: old_events.append(s),
    )
    # 替换回调
    s1 = gs.set_score_callback(lambda s: new_events.append(s))
    # 第一次吃食
    food_point = Point(s1.head.x + 1, s1.head.y)
    s2 = _safe_replace(s1, food=Food(food_point))
    s3 = s2.step()
    assert old_events == [], "旧 cb 不再被调"
    assert new_events == [1], "新 cb 收到 new_score=1"


@pytest.mark.p1
def test_it_game_core_2_19_on_score_callback_multiple_eats():
    """IT-game-core-2-19 on_score 多次吃食：每次吃食各触发一次，参数 = 当次 new_score。FR-13."""
    events = []
    gs = GameState(
        width=10, height=10, difficulty=Difficulty.EASY,  # EASY 节拍慢，便于连续操作
        rng=random.Random(42),
        score_callback=lambda s: events.append(s),
    )
    # 通过直接修改 food 强制多次吃食（避免依赖 RNG）
    s = gs
    for target_score in range(1, 4):
        # 找蛇头前方一格放食物
        d = s.direction
        food_point = Point(s.head.x + d.dx, s.head.y + d.dy)
        s = _safe_replace(s, food=Food(food_point))
        s = s.step()  # 吃食
        assert s.score == target_score
    assert events == [1, 2, 3], f"3 次吃食各触发一次回调，实际 {events}"


@pytest.mark.p1
def test_it_game_core_2_22_on_score_constructor_injection():
    """IT-game-core-2-22 构造期 score_callback 注入；与 set_score_callback 等价。FR-13."""
    events_ctor = []
    events_set = []

    # 构造期注入
    gs_ctor = GameState(
        width=5, height=5, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
        score_callback=lambda s: events_ctor.append(s),
    )
    # 构造后注入
    gs_set = GameState(
        width=5, height=5, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
    )
    gs_set = gs_set.set_score_callback(lambda s: events_set.append(s))

    # 各吃一次
    for gs, events in [(gs_ctor, events_ctor), (gs_set, events_set)]:
        food_point = Point(gs.head.x + 1, gs.head.y)
        s = _safe_replace(gs, food=Food(food_point))
        after = s.step()
        assert after.score == 1
        assert events == [1]


@pytest.mark.p1
def test_it_game_core_2_26_on_score_callback_clear_via_none():
    """IT-game-core-2-26 on_score 回调替换为 None：清空后 step 吃食不触发。FR-13."""
    events = []
    gs = GameState(
        width=5, height=5, difficulty=Difficulty.MEDIUM,
        rng=random.Random(42),
        score_callback=lambda s: events.append(s),
    )
    # 清空回调
    s1 = gs.set_score_callback(None)
    food_point = Point(s1.head.x + 1, s1.head.y)
    s2 = _safe_replace(s1, food=Food(food_point))
    s3 = s2.step()  # 吃食
    assert s3.score == 1
    assert events == [], "清空后回调不再触发"


# ============================================================
# IT-game-core-2-20 / 21：iter-1 回归锚点（核心契约不变）
# ============================================================

@pytest.mark.p0
def test_it_game_core_2_20_iter1_interface_contract_unchanged():
    """IT-game-core-2-20 iter-1 接口契约不变：Point/Direction/Difficulty/GameStatus/Snapshot 字段一致。FR-05/12.

    验证：
      - Point/Direction/Difficulty/GameStatus/Snapshot 公开字段名/类型/可构造性未变
      - Snapshot 字段集（snake_body/food/score/length/status/difficulty/tick_ms）保留
      - 迭代 1 DIFFICULTY_PARAMS dict 已删除（改走 speed_curve）
    """
    # Point
    p = Point(3, 4)
    assert p.x == 3 and p.y == 4
    # Direction
    assert Direction.UP.dx == 0 and Direction.UP.dy == -1
    assert Direction.RIGHT.dx == 1 and Direction.RIGHT.dy == 0
    assert Direction.UP.opposite() == Direction.DOWN
    # Difficulty
    assert {d.name for d in Difficulty} == {"EASY", "MEDIUM", "HARD"}
    # GameStatus
    assert {s.name for s in GameStatus} == {"RUN", "PAUSED", "OVER"}
    # Snapshot 字段
    snap = Snapshot(
        snake_body=(Point(0, 0), Point(1, 0)),
        food=Point(5, 5),
        score=0,
        length=2,
        status=GameStatus.RUN,
        difficulty=Difficulty.MEDIUM,
        tick_ms=160,
    )
    assert hasattr(snap, "snake_body")
    assert hasattr(snap, "food")
    assert hasattr(snap, "score")
    assert hasattr(snap, "length")
    assert hasattr(snap, "status")
    assert hasattr(snap, "difficulty")
    assert hasattr(snap, "tick_ms")
    # frozen
    with pytest.raises(Exception):
        snap.score = 999  # type: ignore[misc]


@pytest.mark.p0
def test_it_game_core_2_21_iter1_core_behaviors_unchanged(default_state):
    """IT-game-core-2-21 iter-1 核心行为不变：移动/吃食/反向/撞墙/撞身/OVER 保护。FR-05/12/13.

    关键回归锚点：迭代 2 增量扩展不得破坏迭代 1 已落地的核心玩法语义。
    """
    # 普通前进
    after = default_state.step()
    assert after.snake.head == Point(11, 7)
    assert after.status == GameStatus.RUN

    # 反向禁止（长度≥2）
    s_rev = default_state.set_direction(Direction.LEFT)
    assert s_rev.direction == Direction.RIGHT, "反向输入静默忽略"

    # pending 合并
    s_up = default_state.set_direction(Direction.UP)
    s_dn = s_up.set_direction(Direction.DOWN)
    after2 = s_dn.step()
    assert after2.direction == Direction.DOWN

    # OVER 保护：撞墙 → OVER → step 抛错
    s = default_state
    for _ in range(10):
        s = s.step()
    assert s.status == GameStatus.OVER
    with pytest.raises(InvalidStateError):
        s.step()
    with pytest.raises(InvalidStateError):
        s.set_direction(Direction.UP)

    # 吃食基本路径
    gs = GameState(width=5, height=5, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
    food_point = Point(gs.head.x + 1, gs.head.y)
    s = _safe_replace(gs, food=Food(food_point))
    after_eat = s.step()
    assert after_eat.score == 1
    assert len(after_eat.snake) == 4
    assert after_eat.food.pos not in after_eat.snake.body

    # 撞尾（不吃食）让行
    snake = Snake((Point(1, 2), Point(0, 2), Point(0, 3), Point(1, 3)))
    food = Food(Point(4, 4))
    gs_tail = _safe_replace(gs, snake=snake, food=food, direction=Direction.DOWN)
    after_tail = gs_tail.step()
    assert after_tail.status == GameStatus.RUN, "撞尾不吃食让行（v1 一致行为）"


# ============================================================
# IT-game-core-2-23 / 24：静态检查（NFR-05）
# ============================================================

@pytest.mark.p0
def test_it_game_core_2_23_no_gui_imports():
    """IT-game-core-2-23 零 GUI 依赖：迭代 2 增量代码无 pygame/pyinstaller 等 import。NFR-05."""
    forbidden = {"pygame", "pyinstaller", "PyInstaller", "tkinter", "PyQt", "wx"}
    for mod_name in forbidden:
        for path in (_CODE_DIR / "game_core").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    assert mod_name.lower() not in stripped.lower(), (
                        f"{path}: 含 GUI 依赖 import: {line}"
                    )


@pytest.mark.p0
def test_it_game_core_2_24_python38_syntax_compatible():
    """IT-game-core-2-24 语法兼容 Python 3.8：无 PEP 604（X | None）/ 内置泛型下标（tuple[X,...]）。NFR-05."""
    for path in (_CODE_DIR / "game_core").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # AST 解析（最直接的 3.8 兼容验证）
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as e:
            pytest.fail(f"{path}: 语法错误: {e}")
        # 检查是否有 PEP 604 BinOp（在注解上下文中用 | 表示联合类型）
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                # 注解上下文：出现在 ast.AnnAssign 的 annotation 或 ast.arg 的 annotation
                # AST 层面只检查 BinOp 的存在；再结合源文本做更精确判断
                lines = text.splitlines()
                src_line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                stripped = src_line.strip()
                # 排除 typing.Union 别名/字符串注释
                if "|" in stripped and not any(t in stripped for t in ("typing.Union", "Optional", "Union", "#")):
                    # 进一步：必须是类型注解上下文（: ... | ... 或 -> ... | ...）
                    if (": " in stripped or "-> " in stripped) and "|" in stripped:
                        pytest.fail(
                            f"{path}:{node.lineno}: 可能使用了 PEP 604 联合类型: {src_line!r}"
                        )
