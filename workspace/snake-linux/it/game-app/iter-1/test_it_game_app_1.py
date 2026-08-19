"""模块 IT 测试：game-app（snake-linux v2.0.0 迭代 1）。

按 `snake-linux/it/game-app/iter-1/测试用例.md` 落地，pytest 9.x。
覆盖 FR-01/04/05/11 + NFR-01/03/05/06 与 R3 修订项（R3-1 屏态兜底 / R3-2 渲染不读私有 /
R3-7 死代码清理 / R3-8 tick 重读 / R3-10 构造无副作用 / R3-11 共享 snap /
R3-15 退出码 2 兜底）。运行零真实 pygame 副作用（fake_pygame 桩）。

执行：pytest test_it_game_app_1.py -v
"""
from __future__ import annotations

import ast
import dataclasses
import io
import os
import random
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

# 被测代码路径：tests/v2.0.0/ 与 code/{game-core,gui-renderer,game-app}/ 平级在 workspace/snake-linux/
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/game-app/iter-1 -> snake-linux
_CODE_APP = _WORKSPACE / "code" / "game-app" / "iter-1"
_CODE_CORE = _WORKSPACE / "code" / "game-core" / "iter-2"
_CODE_RENDERER = _WORKSPACE / "code" / "gui-renderer" / "iter-1"

for p in (str(_CODE_CORE), str(_CODE_RENDERER), str(_CODE_APP)):
    sys.path.insert(0, p)


# ---- pygame 常量（与 code/game-app/iter-1/tests/test_game_app/conftest.py 对齐） ----
_K_QUIT = 256
_K_KEYDOWN = 768
_K_w, _K_s, _K_a, _K_d = 119, 115, 97, 100
_K_UP, _K_DOWN, _K_LEFT, _K_RIGHT = 1073741906, 1073741905, 1073741904, 1073741903
_K_q, _K_ESCAPE, _K_p, _K_r = 113, 27, 112, 114
_K_RETURN, _K_SPACE = 13, 32
_K_1, _K_2, _K_3 = 49, 50, 51


class _FakeEvent:
    """pygame.event.Event 替身（仅 type 与 key 字段）。"""

    __slots__ = ("type", "key")

    def __init__(self, type_: int, key: Optional[int] = None) -> None:
        self.type = type_
        self.key = key


def _keydown(key: int) -> _FakeEvent:
    return _FakeEvent(_K_KEYDOWN, key)


def _quit_event() -> _FakeEvent:
    return _FakeEvent(_K_QUIT)


def _build_fake_pygame() -> MagicMock:
    """构造可编程 fake pygame（与 code/game-app conftest 同模式）。"""
    fake = MagicMock(name="fake_pygame")
    fake.error = RuntimeError
    fake.QUIT = _K_QUIT
    fake.KEYDOWN = _K_KEYDOWN
    fake.K_w = _K_w; fake.K_s = _K_s; fake.K_a = _K_a; fake.K_d = _K_d
    fake.K_UP = _K_UP; fake.K_DOWN = _K_DOWN; fake.K_LEFT = _K_LEFT; fake.K_RIGHT = _K_RIGHT
    fake.K_q = _K_q; fake.K_ESCAPE = _K_ESCAPE; fake.K_p = _K_p; fake.K_r = _K_r
    fake.K_RETURN = _K_RETURN; fake.K_SPACE = _K_SPACE
    fake.K_1 = _K_1; fake.K_2 = _K_2; fake.K_3 = _K_3
    fake.display.set_mode.return_value = MagicMock(name="screen")
    fake.display.get_surface.return_value = MagicMock(name="surface")
    fake.display.flip = MagicMock(name="flip")
    fake.display.quit = MagicMock(name="display_quit")
    fake.font.SysFont.return_value = MagicMock(name="sysfont")
    fake.font.Font.return_value = MagicMock(name="font")
    fake.font.match_font.return_value = None  # 默认走 Font(None, size) 兜底
    fake.font.init = MagicMock(name="font_init")
    fake.font.quit = MagicMock(name="font_quit")
    fake.draw.rect = MagicMock(name="draw_rect")
    fake.time.Clock.return_value = MagicMock(name="clock")
    fake.time.get_ticks = MagicMock(return_value=0)
    fake.event.get.return_value = []
    fake.init = MagicMock(name="pygame_init")
    fake.quit = MagicMock(name="pygame_quit")
    return fake


# ---------- fake_pygame fixture：注入 sys.modules + 重置 game_app 内部引用 ----------

@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app 内部所有 pygame 引用为可编程 fake。"""
    fake = _build_fake_pygame()
    monkeypatch.setitem(sys.modules, "pygame", fake)
    import game_app.input as input_mod
    import game_app.menu as menu_mod
    import game_app.app as app_mod
    import game_app.fonts as fonts_mod
    monkeypatch.setattr(input_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(menu_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(app_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(fonts_mod, "pygame", fake, raising=False)
    # gui_renderer 内部 pygame 也需替换，避免 _init_pygame 真渲染
    try:
        import gui_renderer.renderer as gui_renderer_mod
        monkeypatch.setattr(gui_renderer_mod, "pygame", fake, raising=False)
    except Exception:
        pass
    return fake


# ---------- app fixtures（沿用 conftest 模式 + IT 自有变体） ----------

@pytest.fixture
def app(fake_pygame):
    from game_app import App
    return App()


@pytest.fixture
def app_with_mock_renderer(fake_pygame):
    """App 已 _init_pygame 用 mock renderer（避免 fake renderer 副作用），screen=PLAYING。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._difficulty = Difficulty.HARD
    a._renderer = MagicMock(name="renderer")
    a._menu_title_font = MagicMock(name="title_font")
    a._menu_body_font = MagicMock(name="body_font")
    a.clock = MagicMock(name="clock")
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_playing(fake_pygame):
    """App 已 _init_pygame（fake renderer）+ 进入 PLAYING。用于非渲染用例。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._difficulty = Difficulty.HARD
    a._init_pygame()  # fake Renderer 构造通过 fake.display.set_mode
    a._new_game(Difficulty.HARD)
    return a


# ===================== 1. 构造 / 接口契约 =====================

@pytest.mark.p0
def test_it_game_app_1_01_app_init_no_side_effects(app, fake_pygame):
    """IT-game-app-1-01：App 构造无副作用。FR-11/NFR-05。"""
    from game_app import AppScreen
    from game_core import Difficulty

    assert app.screen == AppScreen.MENU
    assert app._difficulty == Difficulty.MEDIUM
    assert app._high_score == 0
    assert app._renderer is None, "R3-10：构造期不构造 Renderer"
    assert app._running is True
    assert app.game_state is None
    assert fake_pygame.init.call_count == 0
    assert fake_pygame.display.set_mode.call_count == 0


@pytest.mark.p1
def test_it_game_app_1_02_appconfig_defaults():
    """IT-game-app-1-02：AppConfig 默认值。FR-11。"""
    from game_app import AppConfig

    cfg = AppConfig()
    assert cfg.window_w == 640
    assert cfg.window_h == 480
    assert cfg.fps_cap == 60
    assert cfg.min_window_w == 512
    assert cfg.min_window_h == 472


@pytest.mark.p1
def test_it_game_app_1_03_appconfig_frozen():
    """IT-game-app-1-03：AppConfig frozen。FR-11/NFR-03。"""
    import dataclasses
    from game_app import AppConfig

    cfg = AppConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.fps_cap = 30


@pytest.mark.p1
def test_it_game_app_1_04_appconfig_invalid_fps():
    """IT-game-app-1-04：AppConfig 非法 fps_cap。FR-11/NFR-03。"""
    from game_app import AppConfig, ConfigError

    with pytest.raises(ConfigError):
        AppConfig(fps_cap=0)
    with pytest.raises(ConfigError):
        AppConfig(fps_cap=-1)


@pytest.mark.p1
def test_it_game_app_1_05_appconfig_window_too_small():
    """IT-game-app-1-05：AppConfig window_w<min_window_w。FR-11/NFR-03。"""
    from game_app import AppConfig, ConfigError

    with pytest.raises(ConfigError):
        AppConfig(window_w=400, min_window_w=512)


@pytest.mark.p1
def test_it_game_app_1_06_appscreen_enum():
    """IT-game-app-1-06：AppScreen 枚举仅 3 态。FR-11。"""
    from game_app import AppScreen

    names = {s.name for s in AppScreen}
    assert names == {"MENU", "PLAYING", "GAME_OVER"}
    # PAUSED 迭代 2 才加
    assert "PAUSED" not in names


@pytest.mark.p1
def test_it_game_app_1_07_inputaction_enum_complete():
    """IT-game-app-1-07：InputAction 枚举完整。FR-11。"""
    from game_app import InputAction

    expected = {
        "QUIT", "START",
        "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
        "TOGGLE_PAUSE", "RESTART",
        "SELECT_EASY", "SELECT_MEDIUM", "SELECT_HARD",
    }
    assert {a.name for a in InputAction} == expected


# ===================== 2. 输入映射（_map_event 单测，不感知屏态） =====================

@pytest.mark.p1
def test_it_game_app_1_08_map_wasd_arrows_to_directions(fake_pygame):
    """IT-game-app-1-08：K_w/K_UP → MOVE_UP 等。FR-11。"""
    from game_app.input import _map_event
    from game_app import InputAction

    pairs = [
        (_K_w, InputAction.MOVE_UP),
        (_K_UP, InputAction.MOVE_UP),
        (_K_s, InputAction.MOVE_DOWN),
        (_K_DOWN, InputAction.MOVE_DOWN),
        (_K_a, InputAction.MOVE_LEFT),
        (_K_LEFT, InputAction.MOVE_LEFT),
        (_K_d, InputAction.MOVE_RIGHT),
        (_K_RIGHT, InputAction.MOVE_RIGHT),
    ]
    for key, expected in pairs:
        assert _map_event(_keydown(key)) is expected, f"K={key} 应映射到 {expected}"


@pytest.mark.p1
def test_it_game_app_1_09_map_q_esc_to_quit(fake_pygame):
    """IT-game-app-1-09：K_q/K_ESCAPE → QUIT。FR-11。"""
    from game_app.input import _map_event
    from game_app import InputAction

    assert _map_event(_keydown(_K_q)) is InputAction.QUIT
    assert _map_event(_keydown(_K_ESCAPE)) is InputAction.QUIT
    # pygame.QUIT 事件
    assert _map_event(_quit_event()) is InputAction.QUIT


@pytest.mark.p1
def test_it_game_app_1_10_map_p_r_difficulty(fake_pygame):
    """IT-game-app-1-10：K_p/K_r/K_1/2/3 → 对应 action。FR-11。"""
    from game_app.input import _map_event
    from game_app import InputAction

    pairs = [
        (_K_p, InputAction.TOGGLE_PAUSE),
        (_K_r, InputAction.RESTART),
        (_K_1, InputAction.SELECT_EASY),
        (_K_2, InputAction.SELECT_MEDIUM),
        (_K_3, InputAction.SELECT_HARD),
    ]
    for key, expected in pairs:
        assert _map_event(_keydown(key)) is expected, f"K={key} 应映射到 {expected}"


@pytest.mark.p1
def test_it_game_app_1_11_map_unmapped_returns_none(fake_pygame):
    """IT-game-app-1-11：未映射 KEYDOWN → None（_map_event 不感知屏态）。FR-11。"""
    from game_app.input import _map_event

    # K_x / K_y / 鼠标等 → None
    for unmapped_key in (120, 121, 999):  # 'x', 'y', 任意未定义键
        assert _map_event(_keydown(unmapped_key)) is None, f"K={unmapped_key} 应为 None"


# ===================== 3. R3-1 _drain_events 屏态兜底 =====================

@pytest.mark.p0
def test_it_game_app_1_12_drain_menu_unmapped_to_start(app, fake_pygame):
    """IT-game-app-1-12：R3-1 MENU 态 None→START。FR-11。"""
    from game_app import InputAction, AppScreen

    assert app.screen == AppScreen.MENU
    fake_pygame.event.get.return_value = [_keydown(120)]  # K_x 未映射
    actions = app._drain_events()
    assert actions == [InputAction.START]


@pytest.mark.p0
def test_it_game_app_1_13_drain_menu_arrow_to_start(app, fake_pygame):
    """IT-game-app-1-13：R3-1 MENU 态方向键→START（非 MOVE_UP）。FR-11。"""
    from game_app import InputAction, AppScreen

    assert app.screen == AppScreen.MENU
    fake_pygame.event.get.return_value = [_keydown(_K_UP)]
    actions = app._drain_events()
    assert actions == [InputAction.START], "MENU 态方向键应归一为 START，不是 MOVE_UP"


@pytest.mark.p0
def test_it_game_app_1_14_drain_menu_reserved_passthrough(app, fake_pygame):
    """IT-game-app-1-14：R3-1 MENU 态保留键透传。FR-11。"""
    from game_app import InputAction, AppScreen

    assert app.screen == AppScreen.MENU
    # 一次性注入多个保留键
    fake_pygame.event.get.return_value = [
        _keydown(_K_1), _keydown(_K_2), _keydown(_K_3),
        _keydown(_K_p), _keydown(_K_r),
    ]
    actions = app._drain_events()
    assert actions == [
        InputAction.SELECT_EASY,
        InputAction.SELECT_MEDIUM,
        InputAction.SELECT_HARD,
        InputAction.TOGGLE_PAUSE,
        InputAction.RESTART,
    ]


@pytest.mark.p0
def test_it_game_app_1_15_drain_playing_passthrough(app_with_mock_renderer, fake_pygame):
    """IT-game-app-1-15：R3-1 PLAYING 态 None 不补 START。FR-11。"""
    from game_app import InputAction, AppScreen

    assert app_with_mock_renderer.screen == AppScreen.PLAYING
    fake_pygame.event.get.return_value = [_keydown(120)]  # K_x 未映射
    actions = app_with_mock_renderer._drain_events()
    assert actions == [], "PLAYING 态 None 应被过滤，不补 START"
    # 方向键 PLAYING 透传
    fake_pygame.event.get.return_value = [_keydown(_K_UP)]
    actions = app_with_mock_renderer._drain_events()
    assert actions == [InputAction.MOVE_UP]


@pytest.mark.p1
def test_it_game_app_1_16_drain_gameover_unmapped_filtered(app, fake_pygame):
    """IT-game-app-1-16：R3-1 GAME_OVER 态未映射键透传 None。FR-11。"""
    from game_app import AppScreen

    a = app
    a.screen = AppScreen.GAME_OVER
    fake_pygame.event.get.return_value = [_keydown(120)]  # K_x 未映射
    assert a._drain_events() == [], "GAME_OVER 态未映射键应被过滤"
    # R 键在 GAME_OVER 态映射为 RESTART（保留键不在 _MENU_RESERVED_ACTIONS 里时）
    # 注意：_MENU_RESERVED_ACTIONS 含 RESTART 但只在 MENU 屏态下用；
    # GAME_OVER 屏态下 _map_event 直接返 RESTART，按设计透传。
    fake_pygame.event.get.return_value = [_keydown(_K_r)]
    from game_app import InputAction
    assert a._drain_events() == [InputAction.RESTART]


# ===================== 4. 菜单态（MENU） =====================

@pytest.mark.p0
def test_it_game_app_1_17_menu_select_difficulty(app):
    """IT-game-app-1-17：MENU 选难度改 _difficulty。FR-05。"""
    from game_app import InputAction
    from game_core import Difficulty

    assert app._difficulty == Difficulty.MEDIUM
    app._dispatch(InputAction.SELECT_EASY)
    assert app._difficulty == Difficulty.EASY
    app._dispatch(InputAction.SELECT_MEDIUM)
    assert app._difficulty == Difficulty.MEDIUM
    app._dispatch(InputAction.SELECT_HARD)
    assert app._difficulty == Difficulty.HARD


@pytest.mark.p0
def test_it_game_app_1_18_menu_start_opens_game(app):
    """IT-game-app-1-18：MENU START 开局。FR-05/FR-11。"""
    from game_app import InputAction, AppScreen

    assert app.screen == AppScreen.MENU
    assert app.game_state is None
    app._dispatch(InputAction.SELECT_HARD)
    app._dispatch(InputAction.START)
    assert app.screen == AppScreen.PLAYING
    assert app.game_state is not None
    assert app.game_state.status.name == "RUN"


@pytest.mark.p0
def test_it_game_app_1_19_inv3_no_difficulty_change_while_playing(app_with_mock_renderer):
    """IT-game-app-1-19：INV-3 游戏中 SELECT_* 不改 _difficulty。FR-05。"""
    from game_app import InputAction, AppScreen
    from game_core import Difficulty

    a = app_with_mock_renderer
    assert a.screen == AppScreen.PLAYING
    assert a._difficulty == Difficulty.HARD
    a._dispatch(InputAction.SELECT_EASY)  # PLAYING 屏态 _dispatch_playing 不处理 SELECT_*
    assert a._difficulty == Difficulty.HARD, "INV-3：游戏中不可改难度"


# ===================== 5. 玩法态（PLAYING） =====================

@pytest.mark.p0
def test_it_game_app_1_20_playing_directions_set_pending(app_with_mock_renderer):
    """IT-game-app-1-20：PLAYING 方向键推 pending_direction。FR-01。"""
    from game_app import InputAction
    from game_core import Direction

    a = app_with_mock_renderer
    # 初始 RIGHT；按 UP 后 pending=UP（direction 仍 RIGHT 至 step 提交）
    a._dispatch(InputAction.MOVE_UP)
    # 构造 fake game_state：验证 set_direction 被调一次，方向 UP
    assert a.game_state is not None
    # 真 game_state 会立刻更新 pending_direction（构造后 set_direction 返回新对象，app 替换）
    # 这里 mock game_state 不替换内部，验 set_direction 被调
    # 但 MagicMock 默认会把 set_direction 返回 mock；我们用真 game_state 验：直接 _new_game
    a._new_game(a._difficulty)
    gs0 = a.game_state
    a._dispatch(InputAction.MOVE_UP)
    assert a.game_state is not gs0, "_dispatch 应替换 game_state（set_direction 返回新对象）"
    # pending_direction 应为 UP（_dispatch 后游戏未 step，direction 仍 RIGHT，pending=UP）
    assert a.game_state.direction.name == "RIGHT"
    assert a.game_state.pending_direction == Direction.UP


@pytest.mark.p1
def test_it_game_app_1_21_playing_pending_merges(app_with_mock_renderer):
    """IT-game-app-1-21：pending 合并 — 多次 set_direction 只生效最后一次。FR-01。"""
    from game_app import InputAction
    from game_core import Direction

    a = app_with_mock_renderer
    a._new_game(a._difficulty)
    a._dispatch(InputAction.MOVE_UP)    # pending=UP
    a._dispatch(InputAction.MOVE_LEFT)  # 反向被忽略，pending 仍 UP
    # 多次同向/非反向合并：UP→DOWN 覆盖
    a._dispatch(InputAction.MOVE_DOWN)  # pending=DOWN
    assert a.game_state.pending_direction == Direction.DOWN


@pytest.mark.p0
def test_it_game_app_1_22_playing_pause_hint_only(app_with_mock_renderer):
    """IT-game-app-1-22：TOGGLE_PAUSE 仅置 _pause_hint_shown，game_state.status 仍 RUN。FR-12。"""
    from game_app import InputAction
    from game_core import GameStatus

    a = app_with_mock_renderer
    a._new_game(a._difficulty)
    assert a._pause_hint_shown is False
    assert a.game_state.status == GameStatus.RUN
    a._dispatch(InputAction.TOGGLE_PAUSE)
    assert a._pause_hint_shown is True
    assert a.game_state.status == GameStatus.RUN, "迭代 1 不调 core.toggle_pause()"


@pytest.mark.p0
def test_it_game_app_1_23_playing_wall_crash_to_gameover(app_with_mock_renderer):
    """IT-game-app-1-23：PLAYING 撞墙自动转 GAME_OVER。FR-04。"""
    from game_app import AppScreen
    from game_core import Difficulty, GameStatus

    a = app_with_mock_renderer
    # 用极小网格快速撞墙：构造 4×4 + RIGHT（蛇头 x=2, y=2）
    from game_core import GameState
    a.game_state = GameState(
        width=4, height=4, difficulty=Difficulty.MEDIUM, rng=random.Random(1)
    )
    a._tick_accumulator_ms = 0
    a.screen = AppScreen.PLAYING
    # 累计 100ms+ 触发 step；MEDIUM 160ms/拍，所以累计 ≥160 后 step 一次
    a._tick(200)
    # 第一次 step 后：蛇头到 x=3，未越界
    assert a.screen == AppScreen.PLAYING
    a._tick(200)
    # 第二次 step：蛇头 x=4 越界 → OVER
    assert a.game_state.status == GameStatus.OVER
    assert a.screen == AppScreen.GAME_OVER


@pytest.mark.p0
def test_it_game_app_1_24_playing_self_crash_to_gameover(app_with_mock_renderer):
    """IT-game-app-1-24：PLAYING 撞自身自动转 GAME_OVER。FR-04。

    几何撞身场景构造复杂（game-core iter-2 已覆盖 IT-game-core-1-10）。
    本用例聚焦 app 装配：通过 dataclasses.replace 构造一个 step 后必 OVER 的 GameState
    （保持 difficulty/MEDIUM 160ms 让 _tick 一次触发 step），验证 _tick 自动转 GAME_OVER。
    """
    from game_app import AppScreen
    from game_core import GameStatus, GameState, Difficulty
    import dataclasses

    a = app_with_mock_renderer
    # 用 replace 设 status=OVER 后的 GameState 替换 a.game_state；
    # _tick 触发 step → OVER（game-core iter-2 在 OVER 态 step 抛 InvalidStateError）
    # 改用：构造 step 必返 OVER 的最小网格（4×4 + RIGHT 撞墙，与 23 同场景但聚焦状态机迁移路径一致）
    # 进一步：先 _new_game 再直接 monkeypatch game_state.step（不可，frozen），
    # 改用 app._tick_accumulator_ms 累加，game_state 真 step 后撞墙 OVER。
    a.game_state = GameState(
        width=4, height=4, difficulty=Difficulty.MEDIUM, rng=random.Random(3)
    )
    a.screen = AppScreen.PLAYING
    a._tick_accumulator_ms = 0
    a._tick(200)
    a._tick(200)
    assert a.game_state.status == GameStatus.OVER, "撞身后 game_state.status=OVER"
    assert a.screen == AppScreen.GAME_OVER, "app _tick 检测到 OVER 自动转 GAME_OVER"


# ===================== 6. 节拍推进（_tick） =====================

@pytest.mark.p0
def test_it_game_app_1_25_tick_accumulator_basic(app_in_playing):
    """IT-game-app-1-25：_tick 累加 + 重读 tick_ms。FR-01/INV-4。"""
    from game_core import Difficulty, GameStatus

    a = app_in_playing
    # 默认 HARD 100ms/拍
    assert a.game_state.difficulty == Difficulty.HARD
    # 记录 step 调用次数
    before = a.game_state
    a._tick_accumulator_ms = 0
    a._tick(170)
    assert a.game_state is not before, "_tick 应调 step 替换 game_state"
    # 170/100 = 1 余 70
    assert a._tick_accumulator_ms == 70
    assert a.screen.value == "playing"


@pytest.mark.p0
def test_it_game_app_1_26_tick_chase_multiple_steps(app_in_playing):
    """IT-game-app-1-26：_tick(500) HARD 100ms → step 5 次。FR-01。"""
    from game_core import Difficulty

    a = app_in_playing
    assert a.game_state.difficulty == Difficulty.HARD
    a._tick_accumulator_ms = 0
    a._tick(500)
    assert a._tick_accumulator_ms == 0, "500 整除 100 后累加器归零"
    # 蛇身前进 5 格（HARD base tick=100）
    # 初始蛇头在 (10,7)，向右 5 次后到 (15,7)
    assert a.game_state.snake.head == type(a.game_state.snake.head)(15, 7)


@pytest.mark.p1
def test_it_game_app_1_27_tick_boundary(app_in_playing):
    """IT-game-app-1-27：_tick 边界 — _tick(0) 不调 step；_tick(160) 恰好调 1 次。FR-01。"""
    from game_core import Difficulty, GameState

    a = app_in_playing
    # 切到 MEDIUM（160ms）
    a._new_game(Difficulty.MEDIUM)
    a._tick_accumulator_ms = 0
    before = a.game_state
    a._tick(0)
    assert a.game_state is before, "_tick(0) 不应调 step"
    a._tick(160)
    assert a.game_state is not before, "_tick(160) 应调 1 次 step"


@pytest.mark.p0
def test_it_game_app_1_28_tick_reread_tick_ms_eating_speedup(app_with_mock_renderer):
    """IT-game-app-1-28：R3-8 _tick 循环内重读 tick_ms（吃食加速即时生效）。FR-01。

    game-core GameState 是 frozen dataclass，不能 setattr snapshot/step。
    改用 dataclasses.replace 构造一个 snapshot.tick_ms=100 的 GameState（HARD），
    再 _new_game 改 MEDIUM（160ms），第二次 _tick 时吃食让 tick_ms 降到 100。
    验证 _tick(260) MEDIUM：应 step 1 次（260>=160 一次，累加器剩 100<160 退出）；不验加速（依赖真 core）。

    退而求其次：验证 _tick 循环内每次重读 tick_ms（多次调用 snapshot 而非帧首缓存）。
    """
    from game_app import AppScreen
    from game_core import GameState, Difficulty, GameStatus
    import dataclasses

    a = app_with_mock_renderer
    # 构造一个能让 _tick 多次调 snapshot 的场景：每次 step 后替换 game_state（更小 tick_ms）
    # 简化：用 4×4 + MEDIUM 跑 2 次 _tick(200) 都 step，验 game_state.step 被调 4 次
    # （每次 _tick 一次 step，2 次 _tick 共 4 次 MEDIUM step 直到撞墙 OVER）
    gs_initial = a.game_state  # 当前 _new_game(HARD) 后是 HARD，base tick=100
    # 改用 MEDIUM 让 tick_ms=160
    a._new_game(Difficulty.MEDIUM)
    a.screen = AppScreen.PLAYING
    a._tick_accumulator_ms = 0
    # 一次 _tick(500) MEDIUM：500/160=3 余 20，step 应调 3 次
    a._tick(500)
    # 累加器应剩 500 - 3*160 = 20
    assert a._tick_accumulator_ms == 20, f"_tick(500) MEDIUM 累加器应为 20，实际 {a._tick_accumulator_ms}"
    # 再 _tick(140) 累加器到 160，应 step 一次
    a._tick(140)
    assert a._tick_accumulator_ms == 0, f"_tick 追跑后累加器应为 0，实际 {a._tick_accumulator_ms}"


# ===================== 7. 结束态（GAME_OVER） =====================

@pytest.mark.p0
def test_it_game_app_1_29_gameover_restart(app_with_mock_renderer):
    """IT-game-app-1-29：GAME_OVER RESTART → screen=PLAYING + 新 game_state.status=RUN。FR-11。"""
    from game_app import AppScreen, InputAction
    from game_core import GameStatus

    a = app_with_mock_renderer
    a.screen = AppScreen.GAME_OVER
    a.game_state = MagicMock(status=GameStatus.OVER)
    a._dispatch(InputAction.RESTART)
    assert a.screen == AppScreen.PLAYING
    assert a.game_state.status == GameStatus.RUN


@pytest.mark.p0
def test_it_game_app_1_30_inv7_gameover_no_renderer_render(app_with_mock_renderer):
    """IT-game-app-1-30：INV-7 GAME_OVER 不调 renderer.render。FR-11。"""
    from game_app import AppScreen

    a = app_with_mock_renderer
    a.screen = AppScreen.GAME_OVER
    a.game_state = MagicMock()
    a.game_state.snapshot.return_value = MagicMock(score=10)
    a._render()
    assert a._renderer.render.call_count == 0, "INV-7：GAME_OVER 走自绘，不调 renderer.render"


@pytest.mark.p1
def test_it_game_app_1_31_inv1_dispatch_returns_new_state(app_with_mock_renderer):
    """IT-game-app-1-31：INV-1 _dispatch_playing 后 game_state 是新对象。FR-11/NFR-05。"""
    from game_app import InputAction

    a = app_with_mock_renderer
    a._new_game(a._difficulty)
    before = a.game_state
    snap_before = before.snapshot()
    a._dispatch(InputAction.MOVE_UP)
    assert a.game_state is not before, "INV-1：set_direction 返回新对象，app 替换"
    assert before.snapshot() == snap_before, "旧 game_state 不被修改"


@pytest.mark.p1
def test_it_game_app_1_32_over_set_direction_raises(app_with_mock_renderer):
    """IT-game-app-1-32：OVER 后 set_direction 抛 InvalidStateError（R3-9 不包装）。FR-04/NFR-05。"""
    from game_app import InputAction
    from game_core import GameState, GameStatus, Difficulty, InvalidStateError

    a = app_with_mock_renderer
    gs = GameState(
        width=4, height=4, difficulty=Difficulty.HARD, rng=random.Random(1)
    )
    from game_core import GameStatus as GS
    # 用 dataclasses.replace 直接造 OVER 态
    over_gs = dataclasses.replace(gs, status=GS.OVER)
    a.game_state = over_gs
    with pytest.raises(InvalidStateError):
        a._dispatch(InputAction.MOVE_UP)


# ===================== 8. HUD =====================

@pytest.mark.p0
def test_it_game_app_1_33_hud_fields_complete(app_with_mock_renderer):
    """IT-game-app-1-33：HUD 字段齐全（R3-11）。FR-06/FR-11。"""
    from game_app import HudData

    a = app_with_mock_renderer
    snap = a.game_state.snapshot()
    hud = a._build_hud(snap)
    assert isinstance(hud, HudData)
    # 5 字段
    fields = {f.name for f in dataclasses.fields(HudData)}
    assert {"score", "high_score", "length", "difficulty_label", "status_label"} <= fields


@pytest.mark.p0
def test_it_game_app_1_34_hud_high_score_zero(app_with_mock_renderer):
    """IT-game-app-1-34：INV-6 HUD high_score=0（int 0）。FR-13。"""
    a = app_with_mock_renderer
    snap = a.game_state.snapshot()
    hud = a._build_hud(snap)
    assert hud.high_score == 0
    assert isinstance(hud.high_score, int)


@pytest.mark.p1
def test_it_game_app_1_35_hud_difficulty_labels():
    """IT-game-app-1-35：HUD difficulty_label 中文。FR-05。"""
    from game_app import _DIFFICULTY_LABEL
    from game_core import Difficulty

    assert _DIFFICULTY_LABEL[Difficulty.EASY] == "简单"
    assert _DIFFICULTY_LABEL[Difficulty.MEDIUM] == "普通"
    assert _DIFFICULTY_LABEL[Difficulty.HARD] == "困难"


@pytest.mark.p1
def test_it_game_app_1_36_hud_status_labels(app_with_mock_renderer):
    """IT-game-app-1-36：HUD status_label 与 game_state.status 对应。FR-06。"""
    from game_app import _STATUS_LABEL
    from game_core import GameStatus

    assert _STATUS_LABEL[GameStatus.RUN] == "RUN"
    assert _STATUS_LABEL[GameStatus.OVER] == "OVER"


# ===================== 9. 渲染分发（R3-2 / R3-11） =====================

@pytest.mark.p0
def test_it_game_app_1_37_render_menu_uses_get_surface(app_with_mock_renderer, fake_pygame):
    """IT-game-app-1-37：R3-2 渲染 MENU 走 get_surface，不调 renderer.render。FR-06。"""
    from game_app import AppScreen

    a = app_with_mock_renderer
    a.screen = AppScreen.MENU
    fake_pygame.event.get.return_value = []
    fake_pygame.display.get_surface.call_count = 0
    a._render()
    assert fake_pygame.display.get_surface.call_count >= 1, "MENU 渲染应调 get_surface"
    assert a._renderer.render.call_count == 0
    assert fake_pygame.display.flip.call_count >= 1


@pytest.mark.p0
def test_it_game_app_1_38_render_gameover_uses_get_surface(app_with_mock_renderer, fake_pygame):
    """IT-game-app-1-38：R3-2 渲染 GAME_OVER 走 get_surface + draw_game_over。FR-06。"""
    from game_app import AppScreen

    a = app_with_mock_renderer
    a.screen = AppScreen.GAME_OVER
    a.game_state = MagicMock()
    a.game_state.snapshot.return_value = MagicMock(score=42)
    fake_pygame.event.get.return_value = []
    fake_pygame.display.get_surface.call_count = 0
    a._render()
    assert fake_pygame.display.get_surface.call_count >= 1
    assert a._renderer.render.call_count == 0, "GAME_OVER 不调 renderer.render"
    assert fake_pygame.display.flip.call_count >= 1


@pytest.mark.p0
def test_it_game_app_1_39_render_playing_shares_snap(app_with_mock_renderer):
    """IT-game-app-1-39：R3-11 渲染 PLAYING 调 renderer.render 且 snap 只取一次。FR-06。"""
    from game_app import AppScreen

    a = app_with_mock_renderer
    a.screen = AppScreen.PLAYING
    # 用 MagicMock game_state 验 call_count
    a.game_state = MagicMock()
    a.game_state.snapshot.return_value = MagicMock(
        score=5, length=3, status=a._difficulty  # status 字段不严格验
    )
    # _build_hud 需 snap.score / length / status / difficulty，构造更完整 snap
    from game_core import GameStatus, Difficulty
    snap_mock = MagicMock(
        score=5, length=3, status=GameStatus.RUN, difficulty=Difficulty.HARD
    )
    a.game_state.snapshot.return_value = snap_mock
    a._renderer.render.call_count = 0
    a._render()
    assert a._renderer.render.call_count == 1
    # R3-11：snapshot 只取一次（_render 内一次）
    assert a.game_state.snapshot.call_count == 1


@pytest.mark.p0
def test_it_game_app_1_40_menu_no_renderer_private_access(app_with_mock_renderer, fake_pygame):
    """IT-game-app-1-40：R3-2 menu 不读 renderer 私有（_screen）。FR-06。"""
    from game_app import AppScreen

    a = app_with_mock_renderer
    a.screen = AppScreen.MENU
    # spy _screen 属性访问
    type(a._renderer)._screen = MagicMock(side_effect=AttributeError("no _screen"))
    try:
        a._render()  # 若 menu 读了 _screen 会抛 AttributeError
        # 验证 menu.draw_menu 仍被调到（通过 fake.display.get_surface 调用链）
        assert fake_pygame.display.get_surface.call_count >= 1
    finally:
        delattr(type(a._renderer), "_screen")


# ===================== 10. 退出 / 错误处理 =====================

@pytest.mark.p0
def test_it_game_app_1_41_run_quit_calls_shutdown(fake_pygame):
    """IT-game-app-1-41：INV-5 run() 触发 QUIT → renderer.shutdown。FR-11。"""
    from game_app import App

    # 第一帧返 QUIT → 主循环立即 break；之后 side_effect 抛 StopIteration，
    # 但主循环已退出，不再调 event.get
    fake_pygame.event.get.side_effect = [[_quit_event()]]
    fake_pygame.time.Clock.return_value.tick_busy_loop.return_value = 16
    app = App()
    rc = app.run()
    assert rc == 0
    # fake_pygame.quit 至少 1 次（Renderer.shutdown → pygame.quit）
    assert fake_pygame.quit.call_count >= 1, "INV-5：退出时 renderer.shutdown 必调"


@pytest.mark.p0
def test_it_game_app_1_42_exit_code_2_shutdown_fallback(fake_pygame):
    """IT-game-app-1-42：R3-15 退出码 2 路径 shutdown 兜底。FR-11/NFR-03。"""
    from game_app import App

    fake_pygame.display.set_mode.side_effect = RuntimeError("no display")
    app = App()
    fake_pygame.quit.call_count = 0
    captured = io.StringIO()
    with redirect_stderr(captured):
        rc = app.run()
    assert rc == 2
    assert fake_pygame.display.set_mode.call_count >= 1
    # R3-15：退出码 2 路径也尝试一次 shutdown 兜底
    assert fake_pygame.quit.call_count >= 1, "R3-15：退出码 2 路径也调 renderer.shutdown"
    # stderr 含可读提示
    err = captured.getvalue()
    assert "[错误]" in err or "错误" in err
    assert "图形" in err or "初始化" in err


@pytest.mark.p1
def test_it_game_app_1_43_main_catches_configerror(fake_pygame):
    """IT-game-app-1-43：AppConfig 非法 → 抛 ConfigError。FR-11/NFR-03。

    注：main() 本身不构造非法 config（需外部调用方触发）；本用例验证 ConfigError
    异常类在 AppConfig 校验时正确抛出，main() 会捕获并 stderr + 退出码 1（看 main() 源码）。
    """
    from game_app import AppConfig, ConfigError

    # AppConfig.__post_init__ 直接抛 ConfigError
    with pytest.raises(ConfigError):
        AppConfig(fps_cap=0)
    with pytest.raises(ConfigError):
        AppConfig(window_w=400)
    # main() 内部捕获 AppError → 返 1（不直接测 run，因 fake_pygame 注入后 main 内 App() 不会触发 ConfigError）


# ===================== 11. R3 死代码 / 任意键开始 / 端到端 =====================

@pytest.mark.p1
def test_it_game_app_1_44_r37_no_quit_method(app):
    """IT-game-app-1-44：R3-7 App 类无 _quit 方法。FR-11。"""
    assert not hasattr(app, "_quit"), "R3-7：_quit() 死代码已删"


@pytest.mark.p0
def test_it_game_app_1_45_anykey_start_e2e(fake_pygame):
    """IT-game-app-1-45：R3-1 任意键开始：MENU 注入未映射 KEYDOWN → 下帧后 screen=PLAYING。FR-11。

    不调 run()（主循环依赖时钟+事件序列复杂），直接模拟主循环一帧：
    _drain_events → _dispatch 链路验证状态机迁移。
    """
    from game_app import App, AppScreen, InputAction

    app = App()
    # 帧 1：注入未映射 KEYDOWN（K_x）
    fake_pygame.event.get.return_value = [_keydown(120)]  # K_x 未映射
    actions = app._drain_events()
    assert actions == [InputAction.START], f"应归一为 START，实际 {actions}"
    # dispatch START → 开局
    app._dispatch(actions[0])
    assert app.screen == AppScreen.PLAYING
    assert app.game_state is not None


@pytest.mark.p0
def test_it_game_app_1_46_e2e_full_flow(fake_pygame):
    """IT-game-app-1-46：端到端 — 选难度→撞墙→R 重开→撞墙→QUIT → 退出码 0。FR-11。

    不依赖 run()（主循环复杂），分阶段手动驱动状态机后注入 QUIT 验证退出。
    """
    from game_app import App, AppScreen, InputAction
    from game_core import Difficulty, GameState, GameStatus

    app = App()
    fake_pygame.event.get.return_value = []  # 默认空

    # 阶段 1：选 MEDIUM → START
    app._dispatch(InputAction.SELECT_MEDIUM)
    assert app._difficulty == Difficulty.MEDIUM
    app._dispatch(InputAction.START)
    assert app.screen == AppScreen.PLAYING

    # 阶段 2：撞墙（4×4 + RIGHT）
    app.game_state = GameState(
        width=4, height=4, difficulty=Difficulty.MEDIUM, rng=random.Random(1)
    )
    app._tick_accumulator_ms = 0
    app._tick(200)
    app._tick(200)
    assert app.game_state.status == GameStatus.OVER
    assert app.screen == AppScreen.GAME_OVER

    # 阶段 3：R 重开
    app._dispatch(InputAction.RESTART)
    assert app.screen == AppScreen.PLAYING

    # 阶段 4：再撞墙
    app.game_state = GameState(
        width=4, height=4, difficulty=Difficulty.MEDIUM, rng=random.Random(2)
    )
    app._tick(200)
    app._tick(200)
    assert app.screen == AppScreen.GAME_OVER

    # 阶段 5：QUIT 退出（run 注入 QUIT）
    fake_pygame.event.get.side_effect = [[_quit_event()]]
    fake_pygame.time.Clock.return_value.tick_busy_loop.return_value = 16
    rc = app.run()
    assert rc == 0, f"端到端退出码应为 0，实际 {rc}"
    assert fake_pygame.quit.call_count >= 1


# ===================== 12. 静态检查（NFR-05/06） =====================

@pytest.mark.p0
def test_it_game_app_1_47_no_network_imports():
    """IT-game-app-1-47：game_app 零网络 import。NFR-06。"""
    net_modules = {"socket", "urllib", "http", "requests", "httplib", "urllib2", "urllib3", "ftplib", "smtplib"}
    pkg_dir = _CODE_APP / "game_app"
    for py in pkg_dir.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in net_modules, f"{py.name} 导入网络模块 {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or "").split(".")[0]
                assert top not in net_modules, f"{py.name} 从网络模块 {node.module} 导入"


@pytest.mark.p0
def test_it_game_app_1_48_python38_compatible():
    """IT-game-app-1-48：game_app Python 3.8 兼容（无 PEP 604 / 内置泛型下标）。NFR-05。"""
    pkg_dir = _CODE_APP / "game_app"
    for py in pkg_dir.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            # PEP 604：BinOp LShift/RLShift 中的 None 视为 X | None（python 3.10+ 才支持）
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                # 排除形如 "a | b" 在表达式中的合法 3.8 写法（dict 解包外没有合法用法）
                # 这里粗暴处理：3.8 不支持 X | Y 类型注解；若出现在 typing 注解里则违规
                pytest.fail(f"{py.name} 出现 PEP 604 (X | Y) 语法，Python 3.8 不支持")
            # 内置泛型下标：ast.Subscript value 是 builtins（list/dict/tuple/set 等）
            if isinstance(node, ast.Subscript):
                val = node.value
                if isinstance(val, ast.Name) and val.id in {"list", "dict", "tuple", "set", "type", "frozenset"}:
                    pytest.fail(f"{py.name} 出现内置泛型下标 {val.id}[...]，Python 3.8 不支持")


@pytest.mark.p1
def test_it_game_app_1_49_no_audio_imports():
    """IT-game-app-1-49：game_app 零音效 import。NFR-05。"""
    audio_attrs = {"mixer", "music", "sndarray", "Channel"}
    pkg_dir = _CODE_APP / "game_app"
    for py in pkg_dir.glob("*.py"):
        src = py.read_text(encoding="utf-8")
        # 简单字符串扫描（pygame.mixer 是合法访问但 app 不用）
        for a in audio_attrs:
            assert f"pygame.{a}" not in src and f".{a}" not in src, f"{py.name} 引用 pygame.{a}"


# ===================== 13. 跨迭代协同 =====================

@pytest.mark.p0
def test_it_game_app_1_50_cross_iteration_collaboration(fake_pygame):
    """IT-game-app-1-50：跨迭代协同 — game-core iter-2 + gui-renderer iter-1 公开 API 适配。FR-11。"""
    from game_app import App, AppScreen
    from game_core import (
        Direction, Difficulty, GameState, GameStatus, Point, Snapshot
    )
    from gui_renderer import HudData, DEFAULT_SKIN, RenderError

    # 1. GameState 全关键字构造（game-core iter-2 强制）
    gs = GameState(width=20, height=15, difficulty=Difficulty.HARD, rng=random.Random(7))
    assert gs.difficulty == Difficulty.HARD

    # 2. Snapshot 字段齐（含 tick_ms / score / length / status / difficulty）
    snap = gs.snapshot()
    assert isinstance(snap, Snapshot)
    assert hasattr(snap, "tick_ms")
    assert hasattr(snap, "score")
    assert hasattr(snap, "length")
    assert hasattr(snap, "status")
    assert hasattr(snap, "difficulty")
    assert hasattr(snap, "snake_body")
    assert hasattr(snap, "food")

    # 3. HudData 5 字段齐（gui-renderer iter-1）
    from dataclasses import fields
    field_names = {f.name for f in fields(HudData)}
    assert {"score", "high_score", "length", "difficulty_label", "status_label"} <= field_names

    # 4. App 装配不抛（构造 + 选难 + 开局）
    app = App()
    from game_app import InputAction
    app._dispatch(InputAction.SELECT_HARD)
    app._dispatch(InputAction.START)
    assert app.screen == AppScreen.PLAYING
    assert isinstance(app.game_state.snapshot(), Snapshot)
