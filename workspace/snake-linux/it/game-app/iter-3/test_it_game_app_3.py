"""模块 IT 测试：game-app（snake-linux v2.0.0 迭代 3）。

按 `snake-linux/it/game-app/iter-3/测试用例.md` 落地，pytest 9.x。
覆盖 FR-07（平滑插值动画）/FR-09（窗口缩放）/FR-10（皮肤系统）/NFR-04（高分屏清晰）
+ G3-1~G3-5 + r2-1~r2-7 修订项 + 跨迭代回归（iter-1 R3 修订项 + iter-2 G2-1/G2-3 无破坏）。
运行零真实 pygame 副作用（fake_pygame + fake_renderer_iter3 + fake_storage 桩）。

执行：pytest test_it_game_app_3.py -v --tb=short --junitxml=it-report.xml
"""
from __future__ import annotations

import dataclasses
import inspect
import re
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ---- 被测代码路径注入（tests/v2.0.0 与 code/{core,renderer,app}/ 平级） ----
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/game-app/iter-3 -> snake-linux
_CODE_APP = _WORKSPACE / "code" / "game-app" / "iter-3"  # iter-3 实际新建目录（与 modules.json dev_product 一致；G3-7 设计决策"不新建 iter-3 目录"与实现偏离，见 issue MTO-3-02）
_CODE_CORE = _WORKSPACE / "code" / "game-core" / "iter-2"
_CODE_RENDERER = _WORKSPACE / "code" / "gui-renderer" / "iter-3"
_CODE_STORAGE = _WORKSPACE / "code" / "platform-storage" / "iter-2"

for p in (str(_CODE_CORE), str(_CODE_RENDERER), str(_CODE_STORAGE), str(_CODE_APP)):
    sys.path.insert(0, p)


# ---- 顶层导入（参数化装饰器用） ----
from game_app import App, AppConfig, AppScreen, InputAction  # noqa: E402
from game_app.config import AppConfigV3  # G3-4 新增：__init__ 未 re-export（缺陷见 issue MTO-3-01）
from game_app.input import _map_event, _MENU_RESERVED_ACTIONS, _GAME_OVER_RESERVED_ACTIONS  # noqa: E402
from game_app.menu import draw_menu, draw_game_over, draw_pause_overlay  # noqa: E402
import game_app.app as app_mod  # noqa: E402
from game_core import Difficulty, Direction, GameStatus, GameState, InvalidStateError, Point, Snapshot  # noqa: E402
from gui_renderer import HudData, Renderer, InterpolationState, RenderError, SkinNotFoundError, DEFAULT_SKIN  # noqa: E402
from platform_storage import HighScoreStore, StorageError  # noqa: E402


# ---- pytest marker 注册（消 warning） ----
def pytest_configure(config):
    config.addinivalue_line("markers", "p0: 发布阻塞级")
    config.addinivalue_line("markers", "p1: 重要边界")
    config.addinivalue_line("markers", "p2: 体验增强")


# ---- pygame 常量（与 code/game-app/iter-1/tests/test_game_app/conftest.py 对齐） ----
_K_QUIT = 256
_K_KEYDOWN = 768
_K_VIDEORESIZE = 16  # G3-2 新增（SDL_VIDEORESIZE）
_K_w, _K_s, _K_a, _K_d = 119, 115, 97, 100
_K_UP, _K_DOWN, _K_LEFT, _K_RIGHT = 1073741906, 1073741905, 1073741904, 1073741903
_K_q, _K_ESCAPE, _K_p, _K_r = 113, 27, 112, 114
_K_h, _K_BACKSPACE = 104, 8
_K_RETURN, _K_SPACE = 13, 32
_K_1, _K_2, _K_3 = 49, 50, 51


class _FakeEvent:
    """pygame.event.Event 替身。"""

    __slots__ = ("type", "key", "w", "h")

    def __init__(
        self, type_: int, key: Optional[int] = None,
        w: Optional[int] = None, h: Optional[int] = None,
    ) -> None:
        self.type = type_
        self.key = key
        self.w = w
        self.h = h


def _keydown(key: int) -> _FakeEvent:
    return _FakeEvent(_K_KEYDOWN, key)


def _quit_event() -> _FakeEvent:
    return _FakeEvent(_K_QUIT)


def _resize_event(w: int, h: int) -> _FakeEvent:
    """G3-2 新增：构造 VIDEORESIZE 事件。"""
    return _FakeEvent(_K_VIDEORESIZE, w=w, h=h)


def _build_fake_pygame() -> MagicMock:
    """构造可编程 fake pygame（含 iter-3 VIDEORESIZE）。"""
    fake = MagicMock(name="fake_pygame")
    fake.error = RuntimeError
    fake.QUIT = _K_QUIT
    fake.KEYDOWN = _K_KEYDOWN
    fake.VIDEORESIZE = _K_VIDEORESIZE  # G3-2
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


def _build_fake_renderer_iter3() -> MagicMock:
    """G3 新增：fake Renderer 含 iter-3 全部接口。"""
    r = MagicMock(name="fake_renderer")
    r.skin_names.return_value = ("classic", "dark", "colorblind_friendly")
    r.current_skin_name = "classic"
    r.set_skin = MagicMock(name="set_skin")
    r.handle_resize = MagicMock(name="handle_resize")
    r.render = MagicMock(name="render")
    r.fps_metric = MagicMock(name="fps_metric")
    r.cell_size = 24
    r.grid_cols = 20
    r.grid_rows = 15
    return r


# ---------- fixtures ----------

@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app / game-core / gui-renderer / platform-storage 内部 pygame 引用。"""
    fake = _build_fake_pygame()
    monkeypatch.setitem(sys.modules, "pygame", fake)
    import game_app.input as input_mod
    import game_app.menu as menu_mod
    import game_app.app as app_module
    import game_app.fonts as fonts_mod
    import game_app.config as config_mod  # iter-3 config.py 也用 pygame
    monkeypatch.setattr(input_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(menu_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(app_module, "pygame", fake, raising=False)
    monkeypatch.setattr(fonts_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(config_mod, "pygame", fake, raising=False)
    # gui_renderer 内部 pygame 也需替换（_init_pygame 构造 Renderer 时调用 pygame.display.set_mode）
    try:
        import gui_renderer.renderer as gui_renderer_mod
        monkeypatch.setattr(gui_renderer_mod, "pygame", fake, raising=False)
    except Exception:
        pass
    return fake


@pytest.fixture
def fake_storage():
    """MagicMock 模拟 HighScoreStore（load/save/reset 行为可控）。"""
    s = MagicMock(name="fake_storage")
    s.load.return_value = 0
    s.save = MagicMock(name="fake_save")
    s.reset = MagicMock(name="fake_reset")
    return s


@pytest.fixture
def fake_renderer_iter3():
    """G3 新增：fake Renderer 含 iter-3 全部接口。"""
    return _build_fake_renderer_iter3()


@pytest.fixture
def app(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """构造 App + _init_pygame（fake Renderer + fake_storage 注入）。"""
    # monkeypatch app_mod.create_storage（app.py 直接 import 绑定，storage_mod 无效）
    monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    return a


@pytest.fixture
def app_in_playing(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """App 已 _init_pygame + 进入 PLAYING（HARD 难度）。"""
    monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_paused(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """App 已 PLAYING，按 P 进入 PAUSED。"""
    monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PAUSED
    return a


@pytest.fixture
def app_in_game_over(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """App 已 PLAYING，强制 status=OVER + screen=GAME_OVER。"""
    monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
    a.screen = AppScreen.GAME_OVER
    return a


def _set_events(app, events):
    """直接给 fake_pygame.event.get 返回值打补丁。"""
    fake = app_mod.pygame
    fake.event.get.return_value = events


def _mk_snap(snake_body, food=Point(10, 10), tick_ms=160,
             score=0, status=GameStatus.RUN, difficulty=Difficulty.MEDIUM) -> Snapshot:
    return Snapshot(
        snake_body=tuple(Point(*p) if isinstance(p, tuple) else p for p in snake_body),
        food=food,
        score=score,
        length=len(snake_body),
        status=status,
        difficulty=difficulty,
        tick_ms=tick_ms,
    )


# ============================================================
# IT-game-app-3-01：皮肤切换 UI（G3-1）
# ============================================================

class TestSkinSwitchUI:
    """G3-1：MENU 态 ←/→ 切皮肤（_drain_events 同步处理）。"""

    @pytest.mark.p0
    def test_skin_next_in_menu_calls_set_skin(self, app, fake_renderer_iter3):
        """IT-01：MENU 态 → 键 → set_skin("dark") 调 1 次 + _skin_index==1 + 不入 actions。"""
        _set_events(app, [_keydown(_K_RIGHT)])
        actions = app._drain_events()
        assert InputAction.SET_SKIN_NEXT not in actions
        fake_renderer_iter3.set_skin.assert_called_once_with("dark")
        assert app._skin_index == 1


# ============================================================
# IT-game-app-3-02：皮肤循环边界（G3-1 INV-16）
# ============================================================

class TestSkinSwitchCycle:
    """G3-1 INV-16：_skin_index 在 [0, len(skin_names)) 内循环。"""

    @pytest.mark.p0
    def test_skin_right_cycle(self, app, fake_renderer_iter3):
        """IT-02：连续 4 次 → 键 → _skin_index 序列 [1, 2, 0, 1]；调用序列 [dark, colorblind_friendly, classic, dark]。"""
        for _ in range(4):
            _set_events(app, [_keydown(_K_RIGHT)])
            app._drain_events()
        assert app._skin_index == 1
        calls = [c.args[0] for c in fake_renderer_iter3.set_skin.call_args_list]
        assert calls == ["dark", "colorblind_friendly", "classic", "dark"]

    @pytest.mark.p0
    def test_skin_left_wraps_from_zero(self, app, fake_renderer_iter3):
        """IT-02 辅：初始 0 + ← → (0-1)%3==2 → colorblind_friendly。"""
        _set_events(app, [_keydown(_K_LEFT)])
        app._drain_events()
        fake_renderer_iter3.set_skin.assert_called_once_with("colorblind_friendly")
        assert app._skin_index == 2


# ============================================================
# IT-game-app-3-03：SkinNotFoundError 兜底（G3-1）
# ============================================================

class TestSkinNotFoundFallback:
    """G3-1：_switch_skin 防御性兜底（INV-16）。"""

    @pytest.mark.p1
    def test_set_skin_raises_keeps_index_and_stderr(
        self, app, fake_renderer_iter3, capsys
    ):
        """IT-03：set_skin.side_effect=SkinNotFoundError → _skin_index 不变 + stderr 写入 + 不抛。"""
        fake_renderer_iter3.set_skin.side_effect = SkinNotFoundError(
            name="bad", available=("classic",)
        )
        app._switch_skin(InputAction.SET_SKIN_NEXT)
        assert app._skin_index == 0
        captured = capsys.readouterr()
        assert "[警告]" in captured.err
        assert "切换皮肤失败" in captured.err


# ============================================================
# IT-game-app-3-04：屏态透传（G3-1 FR-10 对局不中断）
# ============================================================

class TestSkinKeysOtherScreens:
    """G3-1：PLAYING/PAUSED/GAME_OVER 态 ←/→ 透传为 MOVE_LEFT/MOVE_RIGHT。"""

    @pytest.mark.p0
    def test_playing_skin_prev_becomes_move_left(self, app_in_playing, fake_renderer_iter3):
        """IT-04 PLAYING：← 键 → 透传 MOVE_LEFT；set_skin 未调；_skin_index 不变。"""
        _set_events(app_in_playing, [_keydown(_K_LEFT)])
        actions = app_in_playing._drain_events()
        assert InputAction.MOVE_LEFT in actions
        assert InputAction.SET_SKIN_PREV not in actions
        fake_renderer_iter3.set_skin.assert_not_called()
        assert app_in_playing._skin_index == 0

    @pytest.mark.p0
    def test_playing_skin_next_becomes_move_right(self, app_in_playing, fake_renderer_iter3):
        """IT-04 PLAYING：→ 键 → 透传 MOVE_RIGHT。"""
        _set_events(app_in_playing, [_keydown(_K_RIGHT)])
        actions = app_in_playing._drain_events()
        assert InputAction.MOVE_RIGHT in actions
        fake_renderer_iter3.set_skin.assert_not_called()

    @pytest.mark.p0
    def test_paused_skin_prev_becomes_move_left(self, app_in_paused, fake_renderer_iter3):
        """IT-04 PAUSED：← 键 → 透传 MOVE_LEFT。"""
        _set_events(app_in_paused, [_keydown(_K_LEFT)])
        actions = app_in_paused._drain_events()
        assert InputAction.MOVE_LEFT in actions
        fake_renderer_iter3.set_skin.assert_not_called()

    @pytest.mark.p0
    def test_game_over_skin_prev_becomes_move_left(self, app_in_game_over, fake_renderer_iter3):
        """IT-04 GAME_OVER：← 键 → 透传 MOVE_LEFT（不影响对局）。"""
        _set_events(app_in_game_over, [_keydown(_K_LEFT)])
        actions = app_in_game_over._drain_events()
        assert InputAction.MOVE_LEFT in actions
        fake_renderer_iter3.set_skin.assert_not_called()


# ============================================================
# IT-game-app-3-05：窗口缩放（G3-2 / r2-2 契约前置）
# ============================================================

class TestResizeEventHandling:
    """G3-2：VIDEORESIZE 在 _drain_events 内同步处理（不入 actions）。"""

    @pytest.mark.p0
    def test_resize_event_calls_handle_resize(self, app, fake_renderer_iter3):
        """IT-05：注入 [VIDEORESIZE(1024,768)] → handle_resize(1024,768) 调 1 次 + actions 不含 RESIZE。"""
        _set_events(app, [_resize_event(1024, 768)])
        actions = app._drain_events()
        fake_renderer_iter3.handle_resize.assert_called_once_with(1024, 768)
        assert InputAction.RESIZE not in actions


# ============================================================
# IT-game-app-3-06：缩放兜底（INV-15 G3-2）
# ============================================================

class TestResizeFallback:
    """G3-2 INV-15：RenderError 兜底（不抛、不中断）。"""

    @pytest.mark.p0
    def test_render_error_in_handle_resize(self, app, fake_renderer_iter3, capsys):
        """IT-06：handle_resize.side_effect=RenderError → stderr + 不抛 + actions 为空。"""
        fake_renderer_iter3.handle_resize.side_effect = RenderError("尺寸过小")
        _set_events(app, [_resize_event(100, 100)])
        actions = app._drain_events()
        captured = capsys.readouterr()
        assert "[警告]" in captured.err
        assert "窗口缩放失败" in captured.err
        assert actions == []


# ============================================================
# IT-game-app-3-07：同帧多事件（G3-2 / R3-1）
# ============================================================

class TestResizeWithOtherEvents:
    """G3-2：同帧多事件混排。"""

    @pytest.mark.p1
    def test_resize_plus_quit(self, app, fake_renderer_iter3):
        """IT-07：注入 [VIDEORESIZE, KEYDOWN K_q] → handle_resize 调 + actions 含 QUIT。"""
        _set_events(app, [_resize_event(1024, 768), _keydown(_K_q)])
        actions = app._drain_events()
        fake_renderer_iter3.handle_resize.assert_called_once_with(1024, 768)
        assert InputAction.QUIT in actions
        assert InputAction.RESIZE not in actions


# ============================================================
# IT-game-app-3-08：_tick step 前保存 _prev_snap（r2-1 修订）
# ============================================================

class TestTickPrevSnap:
    """r2-1 修订：_tick step 前保存 _prev_snap（不是 step 后）。"""

    @pytest.mark.p0
    def test_tick_saves_prev_snap_before_step(self, app_in_playing):
        """IT-08：调 _tick(160) → _prev_snap.snake_body[0] 是 step 前蛇头（与 step 后位置不同）。"""
        a = app_in_playing
        pre_head = a.game_state.snake.body[0]
        a._tick(160)
        assert a._prev_snap is not None
        # _prev_snap 是 step 前的快照
        assert a._prev_snap.snake_body[0] == pre_head
        # 步进后蛇头已变（向右移动 1 格）
        assert a.game_state.snake.body[0] != pre_head


# ============================================================
# IT-game-app-3-09：插值渲染调用（G3-3 r2-1 alpha 公式）
# ============================================================

class TestInterpolationRenderCall:
    """G3-3 r2-1：PLAYING 路径 _render → render(snap, hud, interp=InterpolationState(...))。"""

    @pytest.mark.p0
    def test_render_passes_interpolation_state(self, app_in_playing, fake_renderer_iter3):
        """IT-09：_tick(100) 一次（建立 _prev_snap）+ 设 _tick_accumulator_ms=50（HARD tick_ms=100 半程）+ _render() → render(..., interp=...)；interp.alpha==0.5。"""
        a = app_in_playing
        # HARD tick_ms=100：调 _tick(100) 推一拍，_tick_accumulator_ms=0
        a._tick(100)
        assert a._prev_snap is not None
        # 设 _tick_accumulator_ms = 50（半程）
        a._tick_accumulator_ms = 50
        a._render()
        fake_renderer_iter3.render.assert_called_once()
        # kwargs.interp 应为 InterpolationState 实例
        interp = fake_renderer_iter3.render.call_args.kwargs.get("interp")
        assert isinstance(interp, InterpolationState)
        assert interp.alpha == 0.5  # r2-1 修订：elapsed/tick_ms = 50/100


# ============================================================
# IT-game-app-3-10：插值防御（r2-3 / r2-6 / r2-7）
# ============================================================

class TestInterpolationGuards:
    """r2-3 / r2-6 / r2-7：插值防御（None snap / 长度变化 / Chebyshev 距离>1）。"""

    @pytest.mark.p0
    def test_interp_none_when_no_prev_snap(self, app):
        """IT-10 r2-3 子例 1：_prev_snap=None → _interpolation_state(snap) 返 None。"""
        assert app._prev_snap is None
        snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        assert app._interpolation_state(snap) is None

    @pytest.mark.p0
    def test_interp_none_when_snap_is_none(self, app):
        """IT-10 r2-6：snap=None 防御 → 返 None。"""
        assert app._interpolation_state(None) is None

    @pytest.mark.p0
    def test_interp_none_when_length_differs(self, app):
        """IT-10 r2-7：prev_body 长度 != cur_body 长度（吃食增长）→ 返 None。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])  # 长度 3
        snap = _mk_snap([(5, 5), (5, 6), (5, 7), (5, 8)])  # 长度 4（吃食）
        assert app._interpolation_state(snap) is None

    @pytest.mark.p0
    def test_interp_none_when_chebyshev_distance_gt_one(self, app):
        """IT-10 r2-3 子例 2：prev[0]=(5,5) → cur[0]=(10,10) Chebyshev 距离=5 > 1 → 返 None。"""
        app._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        snap = _mk_snap([(10, 10), (5, 6), (5, 7)])
        assert app._interpolation_state(snap) is None


# ============================================================
# IT-game-app-3-11：_new_game 重置 _prev_snap（r2-3 修订）
# ============================================================

class TestNewGameResetsPrevSnap:
    """r2-3 修订：_new_game 重置 _prev_snap = None（新局首帧瞬移）。"""

    @pytest.mark.p0
    def test_new_game_resets_prev_snap(self, app_in_playing):
        """IT-11：手动设 _prev_snap 非 None + 调 _new_game → _prev_snap is None。"""
        a = app_in_playing
        a._prev_snap = _mk_snap([(99, 99)])  # 模拟旧局残留
        assert a._prev_snap is not None
        a._new_game(Difficulty.MEDIUM)
        assert a._prev_snap is None


# ============================================================
# IT-game-app-3-12：OVER→GAME_OVER 切换帧 _prev_snap=None
# ============================================================

class TestOverClearsPrevSnap:
    """G3-3：OVER 切换帧 _prev_snap = None。"""

    @pytest.mark.p1
    def test_over_clears_prev_snap(self, app_in_playing, monkeypatch):
        """IT-12：手动设 _prev_snap 非 None + monkeypatch GameState.step 返 OVER + _tick(160) → _prev_snap is None。"""
        from game_core.state import GameState
        a = app_in_playing
        a._prev_snap = _mk_snap([(99, 99)])
        # monkeypatch GameState 类方法（frozen dataclass 实例不能 monkeypatch）
        monkeypatch.setattr(
            GameState, "step",
            lambda self: dataclasses.replace(self, status=GameStatus.OVER),
        )
        a._tick(160)
        assert a.screen == AppScreen.GAME_OVER
        assert a._prev_snap is None  # OVER 后清空


# ============================================================
# IT-game-app-3-13：PAUSED 态不走插值
# ============================================================

class TestPausedNoInterpolation:
    """G3-3：PAUSED 态 _render 不传 interp（保持定格感）。"""

    @pytest.mark.p1
    def test_paused_render_no_interp(self, app_in_paused, fake_renderer_iter3):
        """IT-13：手动设 _prev_snap + _render() → render 调用 kwargs.interp 为 None（或未传）。"""
        a = app_in_paused
        a._prev_snap = _mk_snap([(5, 5), (5, 6), (5, 7)])
        a._render()
        fake_renderer_iter3.render.assert_called_once()
        kwargs = fake_renderer_iter3.render.call_args.kwargs
        # PAUSED 不走插值：interp 关键字未传或为 None
        assert kwargs.get("interp") is None


# ============================================================
# IT-game-app-3-14~16：AppConfigV3 isinstance 判定 + 透传 + 兜底（G3-4）
# ============================================================

class TestAppConfigV3EnableHighDpi:
    """G3-4：App.__init__ 用 isinstance(config, AppConfigV3) 判定传给 Renderer。"""

    @pytest.mark.p0
    def test_appconfig_v3_true_passes_to_renderer(
        self, fake_pygame, fake_storage, monkeypatch
    ):
        """IT-14：AppConfigV3(enable_high_dpi=True) → Renderer(enable_high_dpi=True)。"""
        # monkeypatch app_mod.create_storage（app.py 直接 import 绑定）
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
        captured = []

        def capture_renderer(size, **kw):
            captured.append(kw)
            return _build_fake_renderer_iter3()

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfigV3(enable_high_dpi=True))
        a._init_pygame()
        assert len(captured) == 1
        assert captured[0].get("enable_high_dpi") is True

    @pytest.mark.p0
    def test_appconfig_v3_false_passes_to_renderer(
        self, fake_pygame, fake_storage, monkeypatch
    ):
        """IT-15：AppConfigV3(enable_high_dpi=False) → Renderer(enable_high_dpi=False)。"""
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
        captured = []

        def capture_renderer(size, **kw):
            captured.append(kw)
            return _build_fake_renderer_iter3()

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfigV3(enable_high_dpi=False))
        a._init_pygame()
        assert len(captured) == 1
        assert captured[0].get("enable_high_dpi") is False

    @pytest.mark.p0
    def test_appconfig_old_instance_backward_compatible_true(
        self, fake_pygame, fake_storage, monkeypatch
    ):
        """IT-16：AppConfig() 旧实例 → 兜底 enable_high_dpi=True（向后兼容）。"""
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
        captured = []

        def capture_renderer(size, **kw):
            captured.append(kw)
            return _build_fake_renderer_iter3()

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfig())
        a._init_pygame()
        assert len(captured) == 1
        assert captured[0].get("enable_high_dpi") is True


# ============================================================
# IT-game-app-3-17：MENU 自绘新增 current_skin_name（G3-5）
# ============================================================

class TestRenderMenuCurrentSkinName:
    """G3-5：MENU 自绘加 current_skin_name 形参。"""

    @pytest.mark.p1
    def test_render_menu_passes_current_skin_name(self, app, fake_renderer_iter3):
        """IT-17：_render MENU → spy draw_menu kwargs.current_skin_name == current_skin_name。"""
        fake_renderer_iter3.current_skin_name = "dark"
        with patch.object(app_mod, "draw_menu") as mock_draw:
            app.screen = AppScreen.MENU
            app._render()
            mock_draw.assert_called_once()
            assert mock_draw.call_args.kwargs.get("current_skin_name") == "dark"


# ============================================================
# IT-game-app-3-18：端到端 MENU→PLAYING 切皮肤 + 插值
# ============================================================

class TestE2EMenuSkinInterpolation:
    """端到端：MENU 切皮肤 → START → PLAYING 走插值 → 游戏中 ←/→ 透传 MOVE。"""

    @pytest.mark.p0
    def test_menu_skin_then_playing_interpolation(
        self, app, fake_renderer_iter3
    ):
        """IT-18：MENU 切 dark → START → PLAYING 调 _tick → _render 走 interp；PLAYING ← 透传 MOVE_LEFT 不切皮肤。"""
        a = app
        # 1. MENU 切皮肤（_drain_events 同步处理）
        _set_events(a, [_keydown(_K_RIGHT)])
        a._drain_events()
        fake_renderer_iter3.set_skin.assert_called_once_with("dark")
        assert a._skin_index == 1
        # 2. START（_drain_events 返回 [START] → 手动 dispatch 触发 _new_game）
        _set_events(a, [_keydown(_K_RETURN)])
        actions = a._drain_events()
        for act in actions:
            a._dispatch(act)
        assert a.screen == AppScreen.PLAYING
        assert a.game_state is not None
        # 3. _tick 推进一拍（MEDIUM tick_ms=160）
        a._tick(160)
        assert a._prev_snap is not None
        # 4. _render 走 interp（MEDIUM tick_ms=160 → elapsed/tick = 80/160 = 0.5）
        a._tick_accumulator_ms = 80
        a._render()
        interp = fake_renderer_iter3.render.call_args.kwargs.get("interp")
        assert isinstance(interp, InterpolationState)
        # 5. PLAYING 中按 ← 透传 MOVE_LEFT
        fake_renderer_iter3.set_skin.reset_mock()
        _set_events(a, [_keydown(_K_LEFT)])
        actions = a._drain_events()
        assert InputAction.MOVE_LEFT in actions
        fake_renderer_iter3.set_skin.assert_not_called()


# ============================================================
# IT-game-app-3-19：端到端 PLAYING 中 VIDEORESIZE 不中断插值
# ============================================================

class TestE2EPlayingResize:
    """端到端：PLAYING 中 VIDEORESIZE → handle_resize → _render 继续走 interp。"""

    @pytest.mark.p0
    def test_playing_resize_does_not_break_interpolation(
        self, app_in_playing, fake_renderer_iter3
    ):
        """IT-19：PLAYING 缩放 → handle_resize 调 + 屏态不变 + _render 继续走 interp。"""
        a = app_in_playing
        a._tick(160)  # 建立 _prev_snap
        baseline_render = fake_renderer_iter3.render.call_count
        # 注入 RESIZE 事件
        _set_events(a, [_resize_event(900, 700)])
        a._drain_events()
        fake_renderer_iter3.handle_resize.assert_called_once_with(900, 700)
        assert a.screen == AppScreen.PLAYING  # INV-15 屏态不变
        # _render 继续走 interp
        a._tick_accumulator_ms = 80
        a._render()
        interp = fake_renderer_iter3.render.call_args.kwargs.get("interp")
        assert isinstance(interp, InterpolationState)


# ============================================================
# IT-game-app-3-20：端到端 MENU→PLAYING→PAUSED→缩放→GAME_OVER→MENU
# ============================================================

class TestE2EFullChain:
    """端到端：完整跨迭代回归 + 缩放在 PAUSED 也不中断 + BACK_TO_MENU 重置 INV-7。"""

    @pytest.mark.p0
    def test_full_chain(self, app, fake_renderer_iter3, monkeypatch):
        """IT-20：MENU 选 HARD → START → PLAYING → ← 透传 MOVE_LEFT → _tick 推进 → P→PAUSED → 缩放 → P→PLAYING → OVER→GAME_OVER → BACKSPACE→MENU。"""
        a = app
        # 1. MENU 选 HARD（_drain_events 返 actions；手动 dispatch）
        _set_events(a, [_keydown(_K_3)])
        for act in a._drain_events():
            a._dispatch(act)
        assert a._difficulty == Difficulty.HARD
        # 2. START
        _set_events(a, [_keydown(_K_RETURN)])
        for act in a._drain_events():
            a._dispatch(act)
        assert a.screen == AppScreen.PLAYING
        assert a.game_state is not None
        # 3. PLAYING 中按 ← 透传 MOVE_LEFT（手动 dispatch 触发 set_direction）
        _set_events(a, [_keydown(_K_LEFT)])
        actions = a._drain_events()
        assert InputAction.MOVE_LEFT in actions
        for act in actions:
            a._dispatch(act)
        fake_renderer_iter3.set_skin.assert_not_called()
        # 4. _tick 推进一拍（HARD tick_ms=100）
        a._tick(100)
        assert a._prev_snap is not None
        # 5. PAUSED（手动 dispatch P → toggle_pause + 屏态同步）
        _set_events(a, [_keydown(_K_p)])
        for act in a._drain_events():
            a._dispatch(act)
        assert a.screen == AppScreen.PAUSED
        assert a.game_state.status == GameStatus.PAUSED
        # 6. PAUSED 态缩放（INV-15：_drain_events 同步处理）
        _set_events(a, [_resize_event(800, 600)])
        a._drain_events()
        fake_renderer_iter3.handle_resize.assert_called_once_with(800, 600)
        assert a.screen == AppScreen.PAUSED
        # 7. P 恢复
        _set_events(a, [_keydown(_K_p)])
        for act in a._drain_events():
            a._dispatch(act)
        assert a.screen == AppScreen.PLAYING
        assert a.game_state.status == GameStatus.RUN
        # 8. 强制 OVER（monkeypatch frozen dataclass 类方法）
        from game_core.state import GameState
        monkeypatch.setattr(
            GameState, "step",
            lambda self: dataclasses.replace(self, status=GameStatus.OVER),
        )
        a._tick(100)
        assert a.screen == AppScreen.GAME_OVER
        assert a._prev_snap is None  # OVER 后清空
        # 9. BACKSPACE → MENU（手动 dispatch）
        _set_events(a, [_keydown(_K_BACKSPACE)])
        for act in a._drain_events():
            a._dispatch(act)
        assert a.screen == AppScreen.MENU
        assert a.game_state is None  # INV-7 重置


# ============================================================
# IT-game-app-3-21：fixture 注入顺序（G3-R-P1-A/B）
# ============================================================

class TestFixtureInjectionOrder:
    """G3-R-P1-A/B：fake_storage 先于 _init_pygame 注入，真实 create_storage 仍被调但不触发真实 IO。"""

    @pytest.mark.p0
    def test_init_pygame_calls_create_storage_with_monkeypatch(
        self, fake_pygame, fake_storage, monkeypatch
    ):
        """IT-21：_init_pygame 内部调 create_storage 1 次（monkeypatch 已接管，真实 IO 断绝）。"""
        spy_storage_calls = []
        monkeypatch.setattr(
            app_mod, "create_storage",
            lambda path=None: (spy_storage_calls.append(path) or fake_storage),
        )
        # 同时 monkeypatch Renderer 防止 _init_pygame 走真实路径
        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: _build_fake_renderer_iter3())
        a = App()
        a._init_pygame()
        assert len(spy_storage_calls) == 1  # _storage is None 守卫路径
        assert a._storage is fake_storage  # monkeypatch 接管
        assert a._high_score == fake_storage.load.return_value  # 0


# ============================================================
# IT-game-app-3-22：回归 iter-2 G2-1 状态机
# ============================================================

class TestRegressionIter2G2_1:
    """回归：iter-2 G2-1（PAUSED 状态机 + 屏态同步方案 A）+ G2-4（失焦自动暂停）。"""

    @pytest.mark.p0
    def test_paused_state_machine(self, app_in_playing):
        """IT-22 PLAYING：P 键 → screen=PAUSED + status=PAUSED；MOVE_LEFT 忽略；P 恢复。"""
        a = app_in_playing
        # TOGGLE_PAUSE → PAUSED
        a._dispatch_playing(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PAUSED
        assert a.game_state.status == GameStatus.PAUSED
        # MOVE_LEFT 忽略（pending_direction 不变）
        prev_pd = a.game_state.pending_direction
        a._dispatch_paused(InputAction.MOVE_LEFT)
        assert a.game_state.pending_direction == prev_pd
        # P 恢复
        a._dispatch_paused(InputAction.TOGGLE_PAUSE)
        assert a.screen == AppScreen.PLAYING
        assert a.game_state.status == GameStatus.RUN

    @pytest.mark.p0
    def test_unfocus_auto_pause(self, app_in_playing, fake_pygame):
        """IT-22 G2-4：PLAYING 态失焦 → 追加 UNFOCUS → 自动 PAUSED。"""
        a = app_in_playing
        fake_pygame.key.get_focused.return_value = False
        _set_events(a, [])  # 空事件（仅 UNFOCUS 内部信号）
        actions = a._drain_events()
        assert InputAction.UNFOCUS in actions
        a._dispatch_playing(InputAction.UNFOCUS)
        assert a.screen == AppScreen.PAUSED


# ============================================================
# IT-game-app-3-23：回归 iter-2 G2-3 得分回调
# ============================================================

class TestRegressionIter2G2_3:
    """回归：iter-2 G2-3 得分回调 INV-13 P0-2 + HighScoreStore.save 链路。"""

    @pytest.mark.p0
    def test_score_callback_updates_storage(self, fake_pygame, fake_storage, monkeypatch):
        """IT-23：_init_pygame + _new_game 注册回调 → cb(50) → _high_score=50 + save(50)；cb(30) max 不降；cb(100) save(100)。"""
        fake_storage.load.return_value = 42
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: _build_fake_renderer_iter3())
        a = App()
        a._init_pygame()
        assert a._high_score == 42  # storage.load 覆盖
        a._new_game(Difficulty.MEDIUM)
        assert a.game_state._score_callback is not None
        # cb(50)
        a.game_state._score_callback(50)
        assert a._high_score == 50
        assert fake_storage.save.call_args.args == (50,)  # save(50) 单参
        # cb(30) max 不降
        a.game_state._score_callback(30)
        assert a._high_score == 50
        # cb(100)
        a.game_state._score_callback(100)
        assert a._high_score == 100
        assert fake_storage.save.call_args_list[-1].args == (100,)


# ============================================================
# IT-game-app-3-24：回归 iter-1 R3 修订项
# ============================================================

class TestRegressionIter1R3:
    """回归：iter-1 R3 修订项（屏态兜底 / 死代码清理 / 构造无副作用 / 共享 snap / 退出码 2 兜底）。"""

    @pytest.mark.p1
    def test_r3_1_menu_state_fallback(self, app):
        """IT-24 R3-1：MENU 态注入 [K_x] 未映射 → actions 含 START。"""
        _set_events(app, [_keydown(ord("x"))])  # K_x 未映射
        actions = app._drain_events()
        assert InputAction.START in actions

    @pytest.mark.p1
    def test_r3_7_dead_code_cleaned(self, app):
        """IT-24 R3-7：App 类无 _quit 方法。"""
        assert not hasattr(app, "_quit")

    @pytest.mark.p1
    def test_r3_10_init_no_side_effects(self, fake_pygame):
        """IT-24 R3-10：App() 构造无副作用（_renderer/_storage/game_state=None + pygame.init 未调）。"""
        a = App()
        assert a._renderer is None
        assert a._storage is None
        assert a.game_state is None
        assert fake_pygame.init.call_count == 0
        assert fake_pygame.display.set_mode.call_count == 0

    @pytest.mark.p1
    def test_r3_11_render_shares_snap(self, app_in_playing, monkeypatch):
        """IT-24 R3-11：PLAYING 路径 _render → game_state.snapshot() 仅调 1 次。

        GameState 是 frozen dataclass，不能 monkeypatch 实例字段；monkeypatch GameState 类方法。
        """
        from game_core.state import GameState
        original_snapshot = GameState.snapshot
        snap_call_count = [0]
        def spy_snapshot(self):
            snap_call_count[0] += 1
            return original_snapshot(self)
        monkeypatch.setattr(GameState, "snapshot", spy_snapshot)
        a = app_in_playing
        a._render()
        # PLAYING 路径：取一次 snap（给 _build_hud + _interpolation_state + renderer.render）
        assert snap_call_count[0] == 1

    @pytest.mark.p0
    def test_r3_15_exit_code_2_shutdown_fallback(self, fake_pygame, fake_storage, monkeypatch):
        """IT-24 R3-15：display.set_mode 抛错 → run() 返 2 + _renderer.shutdown ≥1（finally 兜底）。

        让 Renderer 构造成功（_renderer 被赋值）→ init() 调 set_mode 失败 → 退出码 2 + finally 尝试 shutdown。
        """
        # monkeypatch app_mod.create_storage（app.py 直接 import 绑定）
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
        # Renderer 构造成功；init 失败（set_mode 抛错）
        renderer_spy = MagicMock(name="renderer_spy")
        renderer_spy.init.side_effect = RuntimeError("no display")
        renderer_spy.shutdown = MagicMock()
        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: renderer_spy)
        a = App()
        rc = a.run()
        assert rc == 2
        # finally 兜底调 renderer.shutdown
        assert renderer_spy.shutdown.call_count >= 1


# ============================================================
# IT-game-app-3-25/26/27：静态检查
# ============================================================

class TestStaticChecks:
    """静态检查：NFR-05（无音效 + Python 3.8）+ NFR-06（无网络）。"""

    @pytest.mark.p2
    def test_no_network_imports(self):
        """IT-25 NFR-06：game_app 包零网络 import。"""
        root = _CODE_APP / "game_app"
        for fp in root.glob("*.py"):
            content = fp.read_text(encoding="utf-8")
            assert not re.search(r"^\s*import\s+socket\b", content, re.M), \
                f"{fp.name} 含 socket import"
            assert not re.search(r"^\s*import\s+urllib\b", content, re.M), \
                f"{fp.name} 含 urllib import"
            assert not re.search(r"^\s*import\s+http\b", content, re.M), \
                f"{fp.name} 含 http import"
            assert not re.search(r"^\s*import\s+requests\b", content, re.M), \
                f"{fp.name} 含 requests import"

    @pytest.mark.p2
    def test_no_audio_imports(self):
        """IT-26 NFR-05：game_app 包零音效 import。"""
        root = _CODE_APP / "game_app"
        for fp in root.glob("*.py"):
            content = fp.read_text(encoding="utf-8")
            assert "pygame.mixer" not in content, f"{fp.name} 含 pygame.mixer"
            assert "pygame.music" not in content, f"{fp.name} 含 pygame.music"
            assert not re.search(r"^\s*import\s+sound\b", content, re.M), \
                f"{fp.name} 含 sound import"

    @pytest.mark.p2
    def test_python_38_compatible(self):
        """IT-27 NFR-05：game_app 包 Python 3.8 兼容（无 PEP 604 / 内置泛型下标）。"""
        root = _CODE_APP / "game_app"
        for fp in root.glob("*.py"):
            content = fp.read_text(encoding="utf-8")
            # PEP 604 Union syntax: X | Y（仅在赋值/形参位置，排除字符串内）
            # 简单启发式：排除注释和字符串
            stripped = "\n".join(
                line for line in content.splitlines()
                if not line.lstrip().startswith("#")
            )
            # 检查 `int | None`、`str | None` 等 PEP 604 union
            assert not re.search(r":\s*\w+\s*\|\s*\w+\s*=", stripped), \
                f"{fp.name} 疑似 PEP 604 union 语法（Python 3.10+）"
            # 检查 `list[int]`、`dict[str, int]` 等内置泛型下标（参数化泛型 PEP 585）
            assert not re.search(r":\s*(list|dict|tuple|set)\[", stripped), \
                f"{fp.name} 疑似 PEP 585 内置泛型下标（Python 3.9+）"


# ============================================================
# IT-game-app-3-28：InputAction 新增成员（r2-5 修订计数 18）
# ============================================================

class TestInputActionContract:
    """iter-3 新增 3 个 action 成员；总数 18（r2-5 修订）。"""

    @pytest.mark.p1
    def test_iter3_added_action_members(self):
        """IT-28：SET_SKIN_PREV/NEXT/RESIZE 新增；总成员数 18。"""
        assert InputAction.SET_SKIN_PREV.value == "skin_prev"
        assert InputAction.SET_SKIN_NEXT.value == "skin_next"
        assert InputAction.RESIZE.value == "resize"
        # r2-5 修订计数：iter-2 15 + iter-3 3 = 18
        assert len(InputAction) == 18


# ============================================================
# IT-game-app-3-29：AppConfigV3 子类公开契约
# ============================================================

class TestAppConfigV3Contract:
    """G3-4 公开契约：子类化扩展 enable_high_dpi 字段，向后兼容。"""

    @pytest.mark.p1
    def test_appconfig_v3_is_subclass_and_inherits(self):
        """IT-29：AppConfigV3 ⊂ AppConfig + 默认 enable_high_dpi=True + 字段继承。"""
        assert issubclass(AppConfigV3, AppConfig)
        cfg = AppConfigV3()
        assert cfg.enable_high_dpi is True
        # 继承父类字段
        assert cfg.window_w == 640
        assert cfg.window_h == 480
        assert cfg.fps_cap == 60
        assert cfg.min_window_w == 512
        assert cfg.min_window_h == 472
        # 可设 False
        cfg2 = AppConfigV3(enable_high_dpi=False)
        assert cfg2.enable_high_dpi is False


# ============================================================
# IT-game-app-3-30：_init_pygame 跨 IT 集成 enable_high_dpi 透传
# ============================================================

class TestInitPygameEnableHighDpiIntegration:
    """G3-4 _init_pygame 集成跨 IT 验证：enable_high_dpi 透传 + HighScoreStore 接入 + Renderer.init 生命周期。"""

    @pytest.mark.p0
    def test_init_pygame_full_path_enable_high_dpi_true(
        self, fake_pygame, fake_storage, monkeypatch
    ):
        """IT-30 True：_init_pygame 完整路径 → create_storage 调 + Renderer 构造 enable_high_dpi=True + Renderer.init 调。"""
        create_calls = []
        # monkeypatch game_app.app.create_storage（app.py 直接 import 绑定，需 monkeypatch 此处）
        monkeypatch.setattr(
            app_mod, "create_storage",
            lambda path=None: (create_calls.append(1) or fake_storage),
        )
        captured = []
        renderer_spy = _build_fake_renderer_iter3()

        def capture_renderer(size, **kw):
            captured.append(kw)
            return renderer_spy

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfigV3(enable_high_dpi=True))
        a._init_pygame()
        # create_storage 被调（_storage 默认 None 走 G2-2 路径）
        assert len(create_calls) == 1
        # Renderer 构造 enable_high_dpi=True
        assert captured[0].get("enable_high_dpi") is True
        # Renderer.init 被调
        assert renderer_spy.init.call_count == 1
        assert a._renderer is renderer_spy
        assert a._storage is fake_storage

    @pytest.mark.p0
    def test_init_pygame_full_path_appconfig_backward(self, fake_pygame, fake_storage, monkeypatch):
        """IT-30 兜底：AppConfig 旧实例 → enable_high_dpi 兜底 True + create_storage + Renderer.init。"""
        monkeypatch.setattr(app_mod, "create_storage", lambda path=None: fake_storage)
        captured = []
        renderer_spy = _build_fake_renderer_iter3()

        def capture_renderer(size, **kw):
            captured.append(kw)
            return renderer_spy

        monkeypatch.setattr(app_mod, "Renderer", capture_renderer)
        a = App(AppConfig())  # 旧实例
        a._init_pygame()
        assert captured[0].get("enable_high_dpi") is True  # 兜底 True
        assert renderer_spy.init.call_count == 1
        assert a._storage is fake_storage


# ============================================================
# 模块级集成（自检）：每个 IT 用例 ID 在用例文档中至少出现一次
# ============================================================

class TestCaseDocumentCrossReference:
    """自检：所有 IT-NN 用例 ID 已在测试用例.md §1 矩阵列出。"""

    @pytest.mark.p2
    def test_all_case_ids_in_doc(self):
        """验证 30 条用例 ID 已落盘到测试用例.md（防止遗漏）。"""
        doc_path = _HERE / "测试用例.md"
        doc = doc_path.read_text(encoding="utf-8")
        missing = []
        for n in range(1, 31):
            cid = f"IT-game-app-3-{n:02d}"
            if cid not in doc:
                missing.append(cid)
        assert missing == [], f"测试用例.md 缺少 ID：{missing}"