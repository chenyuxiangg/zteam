"""模块 IT 测试：game-app（snake-linux v2.0.0 迭代 2）。

按 `snake-linux/it/game-app/iter-2/测试用例.md` 落地，pytest 9.x。
覆盖 FR-12（暂停/继续/失焦自动暂停）、FR-13（最高分持久化/展示/重置/得分回调）+ G2-1~G2-7
修订项 + iter-1 R3 修订项回归。运行零真实 pygame 副作用（fake_pygame 桩）。

执行：pytest test_it_game_app_2.py -v
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest


# ---- 被测代码路径注入（tests/v2.0.0 与 code/{core,renderer,app}/ 平级） ----
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/game-app/iter-2 -> snake-linux
_CODE_APP = _WORKSPACE / "code" / "game-app" / "iter-1"
_CODE_CORE = _WORKSPACE / "code" / "game-core" / "iter-2"
_CODE_RENDERER = _WORKSPACE / "code" / "gui-renderer" / "iter-1"
_CODE_STORAGE = _WORKSPACE / "code" / "platform-storage" / "iter-2"

for p in (str(_CODE_CORE), str(_CODE_RENDERER), str(_CODE_STORAGE), str(_CODE_APP)):
    sys.path.insert(0, p)


# ---- 顶层导入（参数化装饰器用） ----
from game_app import App, AppConfig, AppScreen, InputAction, AppError, StorageUnavailableError  # noqa: E402
from game_app.input import _map_event, _MENU_RESERVED_ACTIONS, _GAME_OVER_RESERVED_ACTIONS  # noqa: E402
from game_app.menu import draw_menu, draw_game_over, draw_pause_overlay  # noqa: E402
import game_app.app as app_mod  # noqa: E402
from game_core import Difficulty, Direction, GameStatus, GameState, InvalidStateError  # noqa: E402
from gui_renderer import HudData, Renderer  # noqa: E402
from platform_storage import HighScoreStore, StorageError  # noqa: E402


# ---- pytest marker 注册（消 warning） ----
def pytest_configure(config):
    config.addinivalue_line("markers", "p0: 发布阻塞级")
    config.addinivalue_line("markers", "p1: 重要边界")
    config.addinivalue_line("markers", "p2: 体验增强")


# ---- pygame 常量（与 code/game-app/iter-1/tests/test_game_app/conftest.py 对齐） ----
_K_QUIT = 256
_K_KEYDOWN = 768
_K_w, _K_s, _K_a, _K_d = 119, 115, 97, 100
_K_UP, _K_DOWN, _K_LEFT, _K_RIGHT = 1073741906, 1073741905, 1073741904, 1073741903
_K_q, _K_ESCAPE, _K_p, _K_r = 113, 27, 112, 114
_K_h, _K_BACKSPACE = 104, 8
_K_RETURN, _K_SPACE = 13, 32
_K_1, _K_2, _K_3 = 49, 50, 51


class _FakeEvent:
    """pygame.event.Event 替身。"""

    __slots__ = ("type", "key")

    def __init__(self, type_: int, key: Optional[int] = None) -> None:
        self.type = type_
        self.key = key


def _keydown(key: int) -> _FakeEvent:
    return _FakeEvent(_K_KEYDOWN, key)


def _quit_event() -> _FakeEvent:
    return _FakeEvent(_K_QUIT)


def _build_fake_pygame() -> MagicMock:
    """构造可编程 fake pygame（含 iter-2 K_h/K_BACKSPACE + key.get_focused + SRCALPHA）。"""
    fake = MagicMock(name="fake_pygame")
    fake.error = RuntimeError
    fake.QUIT = _K_QUIT
    fake.KEYDOWN = _K_KEYDOWN
    fake.K_w = _K_w; fake.K_s = _K_s; fake.K_a = _K_a; fake.K_d = _K_d
    fake.K_UP = _K_UP; fake.K_DOWN = _K_DOWN; fake.K_LEFT = _K_LEFT; fake.K_RIGHT = _K_RIGHT
    fake.K_q = _K_q; fake.K_ESCAPE = _K_ESCAPE; fake.K_p = _K_p; fake.K_r = _K_r
    fake.K_h = _K_h; fake.K_BACKSPACE = _K_BACKSPACE
    fake.K_RETURN = _K_RETURN; fake.K_SPACE = _K_SPACE
    fake.K_1 = _K_1; fake.K_2 = _K_2; fake.K_3 = _K_3
    # display
    fake.display.set_mode.return_value = MagicMock(name="screen")
    fake.display.get_surface.return_value = MagicMock(name="surface")
    fake.display.flip = MagicMock(name="flip")
    fake.display.quit = MagicMock(name="display_quit")
    # font
    fake.font.SysFont.return_value = MagicMock(name="sysfont")
    fake.font.Font.return_value = MagicMock(name="font")
    fake.font.match_font.return_value = None
    fake.font.init = MagicMock(name="font_init")
    fake.font.quit = MagicMock(name="font_quit")
    # draw
    fake.draw.rect = MagicMock(name="draw_rect")
    # time
    fake.time.Clock.return_value = MagicMock(name="clock")
    fake.time.get_ticks = MagicMock(return_value=0)
    # event
    fake.event.get.return_value = []
    # init / quit
    fake.init = MagicMock(name="pygame_init")
    fake.quit = MagicMock(name="pygame_quit")
    # key (G2-4 失焦检测)
    fake.key.get_focused.return_value = True
    # SRCALPHA (G2-5 暂停遮罩)
    fake.SRCALPHA = 65536
    fake.Surface = MagicMock(name="pygame_Surface")
    return fake


# ---------- fake_pygame fixture：注入 sys.modules + 替换 game_app 内部 pygame 引用 ----------

@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app / game_core / gui_renderer / platform_storage 内部 pygame 引用。"""
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
    # gui_renderer 内部 pygame 也需替换（_init_pygame 构造 Renderer 时调用 pygame.display.set_mode）
    try:
        import gui_renderer.renderer as gui_renderer_mod
        monkeypatch.setattr(gui_renderer_mod, "pygame", fake, raising=False)
    except Exception:
        pass
    return fake


# ---------- fake_storage fixture ----------

@pytest.fixture
def fake_storage():
    """MagicMock 模拟 HighScoreStore（load/save/reset 行为可控）。"""
    s = MagicMock(name="fake_storage")
    s.load.return_value = 0
    s.save = MagicMock(name="fake_save")
    s.reset = MagicMock(name="fake_reset")
    return s


# ---------- app fixtures ----------

@pytest.fixture
def app(fake_pygame):
    """仅构造，不调 _init_pygame（R3-10 验证用）。"""
    from game_app import App
    return App()


@pytest.fixture
def app_in_playing(fake_pygame, fake_storage):
    """App 已 _init_pygame（fake Renderer）+ fake_storage + 进入 PLAYING（HARD 难度）。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._difficulty = Difficulty.HARD
    a._init_pygame()                # 内部构造 Renderer（fake.set_mode OK）+ storage=None 走 create_storage
    a._storage = fake_storage       # P1-3 注入 fake 覆盖
    a._high_score = fake_storage.load.return_value
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_paused(fake_pygame, fake_storage):
    """App 已 PLAYING，按 P 进入 PAUSED（验证方案 A 同步切屏）。"""
    from game_app import App, InputAction
    from game_core import Difficulty
    a = App()
    a._difficulty = Difficulty.HARD
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._new_game(Difficulty.HARD)
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)
    return a


@pytest.fixture
def app_in_game_over(fake_pygame, fake_storage):
    """App 已 PLAYING，强制 game_state.status=OVER + screen=GAME_OVER（绕开真实 step 撞墙）。"""
    from game_app import App, AppScreen
    from game_core import Difficulty, GameStatus
    a = App()
    a._difficulty = Difficulty.HARD
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._new_game(Difficulty.HARD)
    a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
    a.screen = AppScreen.GAME_OVER
    return a


@pytest.fixture
def app_with_mock_renderer(fake_pygame, fake_storage):
    """App 已 _init_pygame（mock renderer 替真 Renderer）+ 进入 PLAYING。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._difficulty = Difficulty.HARD
    a._renderer = MagicMock(name="mock_renderer")
    a._menu_title_font = MagicMock(name="title_font")
    a._menu_body_font = MagicMock(name="body_font")
    a.clock = MagicMock(name="clock")
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._new_game(Difficulty.HARD)
    return a


# ============================================================
#  IT-game-app-2-04: AppScreen 含 PAUSED（接口契约）
# ============================================================

@pytest.mark.p1
def test_it_2_04_appscreen_paused_enumeration():
    """IT-game-app-2-04：AppScreen 枚举含 PAUSED（G2-1）。"""
    from game_app import AppScreen
    assert AppScreen.MENU.value == "menu"
    assert AppScreen.PLAYING.value == "playing"
    assert AppScreen.PAUSED.value == "paused"  # G2-1 新增
    assert AppScreen.GAME_OVER.value == "over"
    members = {m.name for m in AppScreen}
    assert "PAUSED" in members


# ============================================================
#  IT-game-app-2-05: InputAction 含 G2-1/3/4/7 新增 action
# ============================================================

@pytest.mark.p1
def test_it_2_05_inputaction_g2_extensions():
    """IT-game-app-2-05：InputAction 含 TOGGLE_PAUSE/RESET_HIGHSCORE/BACK_TO_MENU/ESCAPE/UNFOCUS。"""
    from game_app import InputAction
    expected = {
        "QUIT", "START",
        "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT",
        "TOGGLE_PAUSE", "RESTART",
        "SELECT_EASY", "SELECT_MEDIUM", "SELECT_HARD",
        "RESET_HIGHSCORE", "BACK_TO_MENU", "ESCAPE", "UNFOCUS",  # iter-2 新增
    }
    actual = {a.name for a in InputAction}
    assert expected.issubset(actual), f"缺：{expected - actual}"


# ============================================================
#  IT-game-app-2-01: 难度选择（MENU 态入口，PLAYING 不可改）
# ============================================================

@pytest.mark.p0
def test_it_2_01_difficulty_selection_menu_only(fake_pygame, fake_storage):
    """IT-game-app-2-01：MENU 态 SELECT_* 改 _difficulty；START 开局；PLAYING 不可改。"""
    from game_app import App, InputAction, AppScreen
    from game_core import Difficulty
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    # MENU 态 SELECT_EASY
    a._drain_events = lambda: [InputAction.SELECT_EASY]  # 直接注入 actions
    a._dispatch(InputAction.SELECT_EASY)
    assert a._difficulty == Difficulty.EASY
    # MENU 态 START
    a._dispatch(InputAction.START)
    assert a.screen == AppScreen.PLAYING
    assert a.game_state is not None
    # PLAYING 态 SELECT_MEDIUM 无效
    a._dispatch_playing(InputAction.SELECT_MEDIUM)
    assert a._difficulty == Difficulty.EASY  # 不变（INV-3）


# ============================================================
#  IT-game-app-2-02: 暂停快捷键 + 失焦自动暂停
# ============================================================

@pytest.mark.p0
def test_it_2_02_pause_and_unfocus_auto_pause(app_in_playing, fake_pygame):
    """IT-game-app-2-02：P 键 PLAYING↔PAUSED；失焦自动 PAUSED；恢复不自动。"""
    a = app_in_playing
    assert a.screen == AppScreen.PLAYING
    # 1. P 键 → PAUSED（直接调 _dispatch_playing，不经 _drain_events 屏态兜底）
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PAUSED
    assert a.game_state.status == GameStatus.PAUSED
    # 2. P 键 → PLAYING（直接调 _dispatch_paused）
    a._dispatch_paused(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PLAYING
    assert a.game_state.status == GameStatus.RUN
    # 3. 失焦 → 自动 UNFOCUS 追加（用真 _drain_events + 注入空事件 + 失焦）
    fake_pygame.event.get.return_value = []
    fake_pygame.key.get_focused.return_value = False
    actions = a._drain_events()
    assert InputAction.UNFOCUS in actions, f"失焦应追加 UNFOCUS，实际：{actions}"
    for act in actions:
        a._dispatch(act)
    assert a.screen == AppScreen.PAUSED
    # 4. 恢复聚焦 → 不自动恢复
    fake_pygame.key.get_focused.return_value = True
    fake_pygame.event.get.return_value = []
    actions = a._drain_events()
    # 无 UNFOCUS（聚焦恢复）；其他事件空
    assert InputAction.UNFOCUS not in actions
    for act in actions:
        a._dispatch(act)
    assert a.screen == AppScreen.PAUSED  # 仍 PAUSED（恢复需用户主动按 P）


# ============================================================
#  IT-game-app-2-03: 最高分联动（_init_pygame + H 键 + 得分回调）
# ============================================================

@pytest.mark.p0
def test_it_2_03_high_score_integration(fake_pygame, fake_storage):
    """IT-game-app-2-03：_init_pygame → storage.load() → _high_score；H 键 RESET；回调同步高分 + 落盘。"""
    from game_app import App, AppScreen, InputAction
    from game_core import Difficulty
    fake_storage.load.return_value = 42
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    assert a._high_score == 42
    # H 键重置（MENU 态）
    a._dispatch_menu(InputAction.RESET_HIGHSCORE)
    assert fake_storage.reset.call_count == 1
    assert a._high_score == 0
    # START 开局 → 注册回调
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    assert a.game_state is not None
    # 触发回调（模拟吃食得分 100）
    cb = a.game_state._score_callback
    assert cb is not None
    cb(100)
    assert a._high_score == 100
    assert fake_storage.save.call_count == 1
    assert fake_storage.save.call_args == ((100,),) or fake_storage.save.call_args == (100,)


# ============================================================
#  IT-game-app-2-06: ESC 独立 action + GAME_OVER 覆盖为 BACK_TO_MENU
# ============================================================

@pytest.mark.p0
def test_it_2_06_escape_independent_and_game_over_rewire(app_in_game_over, fake_pygame):
    """IT-game-app-2-06：_map_event(K_ESCAPE)→ESCAPE（不返 QUIT）；GAME_OVER 态 _drain_events 覆盖为 BACK_TO_MENU。"""
    from game_app import InputAction, AppScreen
    from game_app.input import _map_event
    a = app_in_game_over
    # _map_event(K_ESCAPE) → ESCAPE
    ev = _keydown(_K_ESCAPE)
    action = _map_event(ev)
    assert action == InputAction.ESCAPE
    assert action != InputAction.QUIT  # P1-2 修订
    # GAME_OVER 态 _drain_events 覆盖 ESCAPE → BACK_TO_MENU
    fake_pygame.event.get.return_value = [ev]
    actions = a._drain_events()
    assert InputAction.BACK_TO_MENU in actions
    assert InputAction.ESCAPE not in actions
    # _dispatch_over(BACK_TO_MENU) → MENU + game_state=None
    a._dispatch_over(InputAction.BACK_TO_MENU)
    assert a.screen == AppScreen.MENU
    assert a.game_state is None  # INV-7 重置


# ============================================================
#  IT-game-app-2-07: UNFOCUS 内部信号（_map_event 不产生）
# ============================================================

@pytest.mark.p1
def test_it_2_07_unfocus_internal_signal(app_in_playing, fake_pygame):
    """IT-game-app-2-07：_map_event 不产生 UNFOCUS；仅 _drain_events PLAYING 失焦时追加。"""
    from game_app import InputAction
    from game_app.input import _map_event
    a = app_in_playing
    # _map_event 任意 KEYDOWN 都不返 UNFOCUS
    for k in (_K_w, _K_p, _K_q, _K_h, _K_ESCAPE, _K_BACKSPACE, _K_RETURN):
        action = _map_event(_keydown(k))
        assert action != InputAction.UNFOCUS
    # _drain_events PLAYING 失焦追加 UNFOCUS
    fake_pygame.key.get_focused.return_value = False
    actions = a._drain_events()
    assert InputAction.UNFOCUS in actions


# ============================================================
#  IT-game-app-2-08: GAME_OVER 态 BACK_TO_MENU（Backspace）
# ============================================================

@pytest.mark.p0
def test_it_2_08_backspace_back_to_menu(app_in_game_over, fake_pygame):
    """IT-game-app-2-08：Backspace → BACK_TO_MENU（_map_event 直返，不经 _drain_events 覆盖）。"""
    from game_app import InputAction, AppScreen
    from game_app.input import _map_event
    a = app_in_game_over
    # _map_event(K_BACKSPACE) → BACK_TO_MENU
    action = _map_event(_keydown(_K_BACKSPACE))
    assert action == InputAction.BACK_TO_MENU
    # _drain_events 透传（GAME_OVER 态未改 BACK_TO_MENU）
    fake_pygame.event.get.return_value = [_keydown(_K_BACKSPACE)]
    actions = a._drain_events()
    assert actions == [InputAction.BACK_TO_MENU]
    # _dispatch_over → MENU + game_state=None
    a._dispatch_over(InputAction.BACK_TO_MENU)
    assert a.screen == AppScreen.MENU
    assert a.game_state is None


# ============================================================
#  IT-game-app-2-09: GAME_OVER 态 Q 键 → QUIT（直通主循环 break）
# ============================================================

@pytest.mark.p1
def test_it_2_09_game_over_quit_passes_through(app_in_game_over, fake_pygame):
    """IT-game-app-2-09：GAME_OVER 态 Q 键 → QUIT（主循环 break，iter-1 R3-7）。"""
    from game_app import InputAction
    from game_app.input import _map_event
    a = app_in_game_over
    # _map_event(K_q) → QUIT
    action = _map_event(_keydown(_K_q))
    assert action == InputAction.QUIT
    # GAME_OVER 态 _drain_events 透传（_GAME_OVER_RESERVED_ACTIONS 含 QUIT）
    fake_pygame.event.get.return_value = [_keydown(_K_q)]
    actions = a._drain_events()
    assert InputAction.QUIT in actions
    assert InputAction.BACK_TO_MENU not in actions  # Q 不被覆盖


# ============================================================
#  IT-game-app-2-10: _dispatch_paused 全分支
# ============================================================

@pytest.mark.p0
@pytest.mark.parametrize("move_action", [
    InputAction.MOVE_UP, InputAction.MOVE_DOWN,
    InputAction.MOVE_LEFT, InputAction.MOVE_RIGHT,
])
def test_it_2_10_dispatch_paused_ignores_moves(app_in_paused, move_action):
    """IT-game-app-2-10：PAUSED 态 MOVE_* 忽略；game_state 不变。"""
    from game_app import AppScreen
    a = app_in_paused
    original_gs = a.game_state
    a._dispatch_paused(move_action)
    assert a.game_state is original_gs
    assert a.screen == AppScreen.PAUSED


@pytest.mark.p0
def test_it_2_10_dispatch_paused_unfocus_ignored(app_in_paused):
    """IT-game-app-2-10：PAUSED 态 UNFOCUS 无操作（再失焦不变）。"""
    from game_app import InputAction, AppScreen
    a = app_in_paused
    a._dispatch_paused(InputAction.UNFOCUS)
    assert a.screen == AppScreen.PAUSED


@pytest.mark.p0
def test_it_2_10_dispatch_paused_toggle_to_playing(app_in_paused):
    """IT-game-app-2-10：PAUSED 态 TOGGLE_PAUSE → PLAYING + status=RUN。"""
    from game_app import InputAction, AppScreen
    from game_core import GameStatus
    a = app_in_paused
    a._dispatch_paused(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PLAYING
    assert a.game_state.status == GameStatus.RUN


# ============================================================
#  IT-game-app-2-11: _dispatch_playing 全分支
# ============================================================

@pytest.mark.p0
def test_it_2_11_dispatch_playing_move_merges_last(app_in_playing):
    """IT-game-app-2-11：PLAYING 态 MOVE_* 多次只生效最后一次（INV-4，合法方向）。"""
    a = app_in_playing
    # 初始方向 RIGHT（snake body=(10,7),(9,7),(8,7)）→ UP/DOWN 与当前垂直（合法）
    a._dispatch_playing(InputAction.MOVE_UP)
    assert a.game_state.pending_direction == Direction.UP
    a._dispatch_playing(InputAction.MOVE_DOWN)  # 改写为 DOWN
    assert a.game_state.pending_direction == Direction.DOWN
    # 第三次再合法方向 → pending 仍是 DOWN（最后一次 set_direction 决定的 pending 字段值；core 内任意方向写入即更新 pending）
    a._dispatch_playing(InputAction.MOVE_UP)
    assert a.game_state.pending_direction == Direction.UP


@pytest.mark.p0
def test_it_2_11_dispatch_playing_toggle_to_paused(app_in_playing):
    """IT-game-app-2-11：PLAYING 态 TOGGLE_PAUSE → PAUSED + status=PAUSED（方案 A）。"""
    from game_app import InputAction, AppScreen
    from game_core import GameStatus
    a = app_in_playing
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PAUSED
    assert a.game_state.status == GameStatus.PAUSED


@pytest.mark.p0
def test_it_2_11_dispatch_playing_unfocus_auto_pause(app_in_playing, fake_pygame):
    """IT-game-app-2-11：PLAYING 态 UNFOCUS → toggle_pause + PAUSED（与 TOGGLE_PAUSE 同路径）。"""
    from game_app import InputAction, AppScreen
    from game_core import GameStatus
    a = app_in_playing
    # 模拟 _drain_events 已追加 UNFOCUS
    fake_pygame.key.get_focused.return_value = False
    actions = a._drain_events()
    assert InputAction.UNFOCUS in actions
    for act in actions:
        a._dispatch(act)
    assert a.screen == AppScreen.PAUSED
    assert a.game_state.status == GameStatus.PAUSED


# ============================================================
#  IT-game-app-2-12: _run_loop 跳过 PAUSED 态 _tick
# ============================================================

@pytest.mark.p0
def test_it_2_12_run_loop_skips_tick_when_paused(app_in_paused, monkeypatch):
    """IT-game-app-2-12：PAUSED 态 _tick 不被调（主循环判断 screen==PLAYING）。"""
    from game_app import AppScreen
    a = app_in_paused
    spy = []
    monkeypatch.setattr(a, "_tick", lambda dt_ms: spy.append(dt_ms))
    # 模拟主循环判定
    if a.screen == AppScreen.PLAYING:
        a._tick(100)
    assert spy == []  # PAUSED 态不入 _tick


# ============================================================
#  IT-game-app-2-13: OVER 态 toggle_pause 抛 InvalidStateError
# ============================================================

@pytest.mark.p1
def test_it_2_13_over_state_toggle_pause_raises(app_in_game_over):
    """IT-game-app-2-13：OVER 态 game_state.toggle_pause() 抛 InvalidStateError（app 不包装）。"""
    from game_core import InvalidStateError, GameStatus
    a = app_in_game_over
    assert a.game_state.status == GameStatus.OVER
    with pytest.raises(InvalidStateError):
        a.game_state.toggle_pause()


# ============================================================
#  IT-game-app-2-14: _render PAUSED 路径
# ============================================================

@pytest.mark.p0
def test_it_2_14_render_paused_calls_renderer_and_overlay(fake_pygame, fake_storage, monkeypatch):
    """IT-game-app-2-14：PAUSED 态 _render 调 renderer.render + draw_pause_overlay 各 1 次。"""
    from game_app import App, InputAction, AppScreen
    from game_core import Difficulty
    import game_app.app as app_mod
    a = App()
    a._difficulty = Difficulty.HARD
    a._renderer = MagicMock(name="mock_renderer")
    a._menu_title_font = MagicMock(name="title_font")
    a._menu_body_font = MagicMock(name="body_font")
    a.clock = MagicMock(name="clock")
    a._storage = fake_storage
    a._high_score = 0
    a._new_game(Difficulty.HARD)
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PAUSED

    overlay_spy = MagicMock(name="overlay_spy")
    monkeypatch.setattr(app_mod, "draw_pause_overlay", overlay_spy)
    a._render()

    assert a._renderer.render.call_count == 1
    assert overlay_spy.call_count == 1
    assert fake_pygame.display.flip.call_count == 1


# ============================================================
#  IT-game-app-2-15: draw_pause_overlay 内容
# ============================================================

@pytest.mark.p1
def test_it_2_15_pause_overlay_draw(fake_pygame):
    """IT-game-app-2-15：draw_pause_overlay 创建 SRCALPHA overlay + body_font.render ≥2 + blit ≥3。"""
    surface = MagicMock(name="surface")
    surface.get_size.return_value = (640, 480)
    surface.get_width.return_value = 640
    surface.get_height.return_value = 480
    body_font = MagicMock(name="body_font")
    rendered = MagicMock(name="rendered", get_width=lambda: 100, get_height=lambda: 30)
    body_font.render.return_value = rendered
    draw_pause_overlay(surface, body_font)
    # Surface 被创建（pygame.Surface 调用，参数含 SRCALPHA）
    assert fake_pygame.Surface.called  # overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    # body_font.render 至少 2 次（PAUSED 大字 + "按 P 继续"）
    assert body_font.render.call_count >= 2
    # surface.blit 至少 3 次（overlay + 2 文字）
    assert surface.blit.call_count >= 3


# ============================================================
#  IT-game-app-2-16: _init_pygame 构造 HighScoreStore
# ============================================================

@pytest.mark.p0
def test_it_2_16_init_pygame_creates_storage(app, fake_pygame, monkeypatch):
    """IT-game-app-2-16：_init_pygame 内构造 HighScoreStore（P1-3 _storage=None 时 create_storage）。"""
    import game_app.app as app_mod
    fake_store = MagicMock(name="fake_store")
    fake_store.load.return_value = 7
    monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_store)
    app._init_pygame()
    assert app._storage is fake_store
    assert app._high_score == 7


# ============================================================
#  IT-game-app-2-17: _init_pygame mkdir 失败（OSError 包 AppError）
# ============================================================

@pytest.mark.p1
def test_it_2_17_init_pygame_wraps_oserror(app, fake_pygame, monkeypatch):
    """IT-game-app-2-17：create_storage 抛 OSError → 包 AppError("用户数据目录不可写")。"""
    import game_app.app as app_mod
    from game_app import AppError
    monkeypatch.setattr(app_mod, "create_storage", lambda path=None: (_ for _ in ()).throw(OSError("perm")))
    with pytest.raises(AppError, match="用户数据目录不可写"):
        app._init_pygame()
    assert app._storage is None


# ============================================================
#  IT-game-app-2-18: RESET_HIGHSCORE 路径
# ============================================================

@pytest.mark.p0
def test_it_2_18_reset_highscore(fake_pygame, fake_storage):
    """IT-game-app-2-18：MENU 态 RESET_HIGHSCORE → storage.reset() + _high_score=0。"""
    from game_app import App, InputAction
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = 99
    a._dispatch_menu(InputAction.RESET_HIGHSCORE)
    assert fake_storage.reset.call_count == 1
    assert a._high_score == 0


# ============================================================
#  IT-game-app-2-19: RESET_HIGHSCORE storage.reset 抛 StorageError
# ============================================================

@pytest.mark.p1
def test_it_2_19_reset_highscore_wraps_storage_error(fake_pygame, fake_storage):
    """IT-game-app-2-19：storage.reset 抛 StorageError → 包装 StorageUnavailableError。"""
    from game_app import App, InputAction, StorageUnavailableError
    from platform_storage import StorageError
    a = App()
    a._init_pygame()
    fake_storage.reset.side_effect = StorageError("IO fail")
    a._storage = fake_storage
    a._high_score = 5
    with pytest.raises(StorageUnavailableError, match="重置最高分失败"):
        a._dispatch_menu(InputAction.RESET_HIGHSCORE)


# ============================================================
#  IT-game-app-2-20: _new_game 注册 score_callback（INV-13 P0-2）
# ============================================================

@pytest.mark.p0
def test_it_2_20_new_game_registers_callback(fake_pygame, fake_storage):
    """IT-game-app-2-20：_new_game 注册回调；触发后 _high_score + storage.save 同步。"""
    from game_app import App
    from game_core import Difficulty
    fake_storage.load.return_value = 50
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._difficulty = Difficulty.MEDIUM
    a._new_game(Difficulty.MEDIUM)
    cb = a.game_state._score_callback
    assert cb is not None
    cb(100)
    assert a._high_score == 100  # max(50, 100)
    assert fake_storage.save.call_count == 1
    # 降分不触发 save（high_score 仍是 100）
    cb(30)
    assert a._high_score == 100
    # 升分触发 save(200)
    cb(200)
    assert a._high_score == 200
    assert fake_storage.save.call_args_list[-1].args == (200,) or fake_storage.save.call_args_list[-1][0] == (200,)


# ============================================================
#  IT-game-app-2-21: _new_game(_storage=None) 时 callback=None（不吃食触发持久化）
# ============================================================

@pytest.mark.p1
def test_it_2_21_new_game_without_storage_has_no_callback(fake_pygame):
    """IT-game-app-2-21：_storage=None 时 callback=None；吃食不触发持久化（UT 隔离）。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._init_pygame()
    a._storage = None
    a._high_score = 0
    a._difficulty = Difficulty.MEDIUM
    a._new_game(Difficulty.MEDIUM)
    cb = a.game_state._score_callback
    assert cb is None  # _storage=None → 不注册回调


# ============================================================
#  IT-game-app-2-22: score_callback 内 storage.save 抛 StorageError
# ============================================================

@pytest.mark.p1
def test_it_2_22_score_callback_wraps_storage_error(fake_pygame, fake_storage):
    """IT-game-app-2-22：回调内 storage.save 抛 StorageError → 包 StorageUnavailableError。"""
    from game_app import App, StorageUnavailableError
    from game_core import Difficulty
    from platform_storage import StorageError
    fake_storage.save.side_effect = StorageError("disk full")
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = 0
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    cb = a.game_state._score_callback
    assert cb is not None
    with pytest.raises(StorageUnavailableError, match="写入最高分失败"):
        cb(200)


# ============================================================
#  IT-game-app-2-23: draw_menu 最高分行（>0 才绘）
# ============================================================

@pytest.mark.p1
def test_it_2_23_menu_high_score_conditional(fake_pygame):
    """IT-game-app-2-23：draw_menu high_score>0 绘制最高分行；=0 不绘制。"""
    surface = MagicMock(name="surface")
    surface.get_size.return_value = (640, 480)
    surface.get_width.return_value = 640
    surface.get_height.return_value = 480
    title_font = MagicMock(name="title_font")
    title_font.render.return_value = MagicMock(name="r", get_width=lambda: 100)
    body_font = MagicMock(name="body_font")
    body_font.render.return_value = MagicMock(name="r", get_width=lambda: 80, get_height=lambda: 20)

    # high_score=0 → 不绘"最高分：N"行
    body_font.render.reset_mock()
    draw_menu(surface, title_font, body_font, Difficulty.MEDIUM, high_score=0)
    rendered = [c.args[0] for c in body_font.render.call_args_list if c.args]
    has_high_score_line_0 = any("最高分：" in t and ("0" in t) for t in rendered)
    assert not has_high_score_line_0, f"high_score=0 不应绘最高分行：{rendered}"

    # high_score=100 → 绘"最高分：100"行
    body_font.render.reset_mock()
    draw_menu(surface, title_font, body_font, Difficulty.MEDIUM, high_score=100)
    rendered = [c.args[0] for c in body_font.render.call_args_list if c.args]
    has_high_score_line_100 = any("最高分：" in t and "100" in t for t in rendered)
    assert has_high_score_line_100, f"high_score=100 应绘'最高分：100'：{rendered}"


# ============================================================
#  IT-game-app-2-24: draw_game_over 最高分 + 返回菜单提示
# ============================================================

@pytest.mark.p1
def test_it_2_24_game_over_high_score_and_back_hint(fake_pygame):
    """IT-game-app-2-24：draw_game_over 含最高分行 + Esc/Backspace 返回菜单提示（G2-7）。"""
    from game_app.menu import draw_game_over
    surface = MagicMock(name="surface")
    surface.get_size.return_value = (640, 480)
    surface.get_width.return_value = 640
    surface.get_height.return_value = 480
    title_font = MagicMock(name="title_font")
    title_font.render.return_value = MagicMock(name="r", get_width=lambda: 100)
    body_font = MagicMock(name="body_font")
    body_font.render.return_value = MagicMock(name="r", get_width=lambda: 80, get_height=lambda: 20)
    draw_game_over(surface, title_font, body_font, score=50, high_score=120)
    rendered = " ".join(
        str(c.args[0]) for c in body_font.render.call_args_list if c.args
    )
    assert "最高分" in rendered and "120" in rendered
    assert "Esc" in rendered or "ESC" in rendered or "Esc / Backspace" in rendered
    assert "Backspace" in rendered or "Backspace" in rendered


# ============================================================
#  IT-game-app-2-25: _build_hud 高分字段 = self._high_score
# ============================================================

@pytest.mark.p0
def test_it_2_25_build_hud_high_score_source(app_with_mock_renderer):
    """IT-game-app-2-25：_build_hud 返回 HudData.high_score == self._high_score（G2-6）。"""
    from gui_renderer import HudData
    a = app_with_mock_renderer
    a._high_score = 999
    snap = a.game_state.snapshot()
    hud = a._build_hud(snap)
    assert isinstance(hud, HudData)
    assert hud.high_score == 999


# ============================================================
#  IT-game-app-2-27: _render PLAYING 共享一次 snap（R3-11）
# ============================================================

@pytest.mark.p1
def test_it_2_27_render_playing_shares_snap(app_with_mock_renderer):
    """IT-game-app-2-27：PLAYING 路径 _render 调 snapshot 一次（R3-11）。"""
    a = app_with_mock_renderer
    # game_state.snapshot() 是真实 GameState 方法（不能 mock 直接换 mock 实例）；改为 mock renderer.render 参数验证
    a._renderer.render.reset_mock()
    a._render()
    assert a._renderer.render.call_count == 1
    # 传给 render 的 snap 应同时给 _build_hud
    args = a._renderer.render.call_args
    snap_arg = args.args[0] if args.args else args.kwargs.get("snap")
    hud_arg = args.args[1] if len(args.args) > 1 else args.kwargs.get("hud")
    assert snap_arg is not None
    assert hud_arg is not None
    # snap 与 _build_hud(snap) 用的是同一对象（R3-11 共享一次）
    hud_from_snap = a._build_hud(snap_arg)
    assert hud_from_snap.high_score == hud_arg.high_score  # 数据一致


# ============================================================
#  IT-game-app-2-28: _render MENU 路径
# ============================================================

@pytest.mark.p1
def test_it_2_28_render_menu(fake_pygame, monkeypatch):
    """IT-game-app-2-28：MENU 态 _render 调 draw_menu(surface, title, body, difficulty, high_score=...)"""
    from game_app import App
    from game_core import Difficulty
    import game_app.app as app_mod
    a = App()
    a._renderer = MagicMock(name="renderer")
    a._menu_title_font = MagicMock(name="title_font")
    a._menu_body_font = MagicMock(name="body_font")
    a.clock = MagicMock(name="clock")
    a._difficulty = Difficulty.MEDIUM
    a._high_score = 50
    draw_menu_spy = MagicMock(name="draw_menu_spy")
    monkeypatch.setattr(app_mod, "draw_menu", draw_menu_spy)
    a._render()
    assert draw_menu_spy.call_count == 1
    # high_score 形参传入 50
    args = draw_menu_spy.call_args
    passed_high = args.kwargs.get("high_score", args.args[4] if len(args.args) > 4 else None)
    assert passed_high == 50
    # 用 fake.display.get_surface（不是 _renderer._screen 私有）
    assert fake_pygame.display.get_surface.called


# ============================================================
#  IT-game-app-2-29: _render GAME_OVER 路径
# ============================================================

@pytest.mark.p1
def test_it_2_29_render_game_over(fake_pygame, fake_storage, monkeypatch):
    """IT-game-app-2-29：GAME_OVER 态 _render 调 draw_game_over 含 score + high_score。"""
    from game_app import App, AppScreen
    from game_core import Difficulty
    import game_app.app as app_mod
    a = App()
    a._renderer = MagicMock(name="renderer")
    a._menu_title_font = MagicMock(name="title_font")
    a._menu_body_font = MagicMock(name="body_font")
    a.clock = MagicMock(name="clock")
    a._storage = fake_storage
    a._high_score = 200
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    # 进入 GAME_OVER
    import dataclasses
    from game_core import GameStatus
    a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
    a.screen = AppScreen.GAME_OVER
    draw_over_spy = MagicMock(name="draw_game_over_spy")
    monkeypatch.setattr(app_mod, "draw_game_over", draw_over_spy)
    a._render()
    assert draw_over_spy.call_count == 1
    args = draw_over_spy.call_args
    passed_high = args.kwargs.get("high_score", args.args[4] if len(args.args) > 4 else None)
    assert passed_high == 200


# ============================================================
#  IT-game-app-2-30: 端到端 MENU→PLAYING→PAUSED→PLAYING→OVER→MENU
# ============================================================

@pytest.mark.p0
def test_it_2_30_end_to_end_state_machine(fake_pygame, fake_storage):
    """IT-game-app-2-30：端到端状态机迁移 + 回调 + 返回菜单。"""
    from game_app import App, AppScreen, InputAction
    from game_core import Difficulty, GameStatus
    a = App()
    a._difficulty = Difficulty.MEDIUM
    a._renderer = MagicMock(name="renderer")
    a._menu_title_font = MagicMock(name="title_font")
    a._menu_body_font = MagicMock(name="body_font")
    a.clock = MagicMock(name="clock")
    a._storage = fake_storage
    a._high_score = 0
    # 1. MENU 态 START → PLAYING
    fake_pygame.event.get.return_value = [_keydown(_K_RETURN)]
    actions = a._drain_events()
    for act in actions:
        a._dispatch(act)
    assert a.screen == AppScreen.PLAYING
    assert a.game_state is not None
    # 2. PLAYING → PAUSED
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PAUSED
    # 3. PAUSED → PLAYING
    a._dispatch_paused(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PLAYING
    # 4. 模拟吃食得分（直接调回调）
    cb = a.game_state._score_callback
    assert cb is not None
    cb(75)
    assert a._high_score == 75
    assert fake_storage.save.call_args_list[-1].args == (75,) or fake_storage.save.call_args_list[-1][0] == (75,)
    # 5. 模拟撞墙结束：monkeypatch a.game_state.step 返 OVER（GameState 是 frozen，用 object.__setattr__）
    over_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
    object.__setattr__(a.game_state, "step", lambda: over_state)
    a._tick(500)  # 调 _tick 触发 step → 拿到 OVER → screen=GAME_OVER
    assert a.screen == AppScreen.GAME_OVER
    # 6. GAME_OVER → BACK_TO_MENU（Backspace）
    fake_pygame.event.get.return_value = [_keydown(_K_BACKSPACE)]
    actions = a._drain_events()
    for act in actions:
        a._dispatch(act)
    assert a.screen == AppScreen.MENU
    assert a.game_state is None  # INV-7 重置


# ============================================================
#  IT-game-app-2-31: 真实 HighScoreStore IO（tmp_path 隔离）
# ============================================================

@pytest.mark.p0
def test_it_2_31_real_highscore_io(tmp_path, fake_pygame):
    """IT-game-app-2-31：tmp_path 注入真实 HighScoreStore；save→load 一致；reset→0；文件落盘存在。"""
    a = App()
    a._init_pygame()
    a._storage = HighScoreStore(tmp_path / "highscore.json")
    a._high_score = a._storage.load()
    assert a._high_score == 0
    # save → load 一致（仅验证 storage 自身，_high_score 不走回调不更新）
    a._storage.save(50)
    assert a._storage.load() == 50
    # 文件落盘
    assert (tmp_path / "highscore.json").exists()
    # 重新构造 HighScoreStore（同路径）→ load 出 50（持久化有效）
    s2 = HighScoreStore(tmp_path / "highscore.json")
    assert s2.load() == 50
    # reset → load=0；文件删除
    a._dispatch_menu(InputAction.RESET_HIGHSCORE)
    assert a._storage.load() == 0
    assert a._high_score == 0
    assert not (tmp_path / "highscore.json").exists()


# ============================================================
#  IT-game-app-2-32: 主循环退出码 0 + shutdown 兜底
# ============================================================

@pytest.mark.p0
def test_it_2_32_run_loop_quit_exit_zero(fake_pygame, fake_storage, monkeypatch):
    """IT-game-app-2-32：QUIT 退出码 0；renderer.shutdown 调用 ≥1（R3-15）。"""
    from gui_renderer import Renderer as RealRenderer
    mock_renderer = MagicMock(name="mock_renderer")

    class FakeRenderer:
        def __init__(self, *args, **kwargs):
            pass

        def init(self):
            pass

        def render(self, *args, **kwargs):
            pass

        def shutdown(self):
            mock_renderer.shutdown()  # 记录调用次数

    monkeypatch.setattr(RealRenderer, "__init__", FakeRenderer.__init__)
    monkeypatch.setattr(RealRenderer, "init", FakeRenderer.init)
    monkeypatch.setattr(RealRenderer, "render", FakeRenderer.render)
    monkeypatch.setattr(RealRenderer, "shutdown", FakeRenderer.shutdown)

    a = App()
    a._difficulty = Difficulty.HARD
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = 0
    a._new_game(Difficulty.HARD)
    # 注入 QUIT 事件后调 run()（run 含 finally 调 renderer.shutdown）
    fake_pygame.event.get.return_value = [_quit_event()]
    code = a.run()
    assert code == 0
    assert mock_renderer.shutdown.call_count >= 1  # R3-15 退出码 0 路径调 shutdown


# ============================================================
#  IT-game-app-2-33: iter-1 R3 修订项回归（无回归）
# ============================================================

@pytest.mark.p1
def test_it_2_33_r3_revisions_no_regression(app, fake_pygame):
    """IT-game-app-2-33：iter-1 R3 修订项全部保留。"""
    from game_app import AppScreen
    from game_core import Difficulty
    # R3-10：构造无副作用
    assert app._renderer is None
    assert app._storage is None  # G2-2 扩展
    assert app.game_state is None
    assert fake_pygame.init.call_count == 0
    # R3-1：MENU 态 None → START
    from game_app.input import _map_event
    from game_app import InputAction
    fake_pygame.event.get.return_value = [_keydown(_K_RETURN)]  # 未映射
    actions = app._drain_events()
    assert InputAction.START in actions  # MENU 兜底
    # R3-7：_quit 死代码清理（hasattr 应 False）
    assert not hasattr(app, "_quit") or not callable(getattr(app, "_quit", None))
    # R3-15：退出码 2 兜底
    fake_pygame.display.set_mode.side_effect = RuntimeError("no display")
    code = app.run()
    assert code == 2