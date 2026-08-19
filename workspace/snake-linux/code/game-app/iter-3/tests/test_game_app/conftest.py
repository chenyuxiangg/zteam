"""game-app 迭代 3 测试 conftest：pygame 桩 + App fixture。

迭代 3 增量（G3-R-P1-A/B/C/G3-R-P2-6/G3-R-P2-7）：
- fake_pygame 同时替换 game_app.input/menu/app/fonts/config 模块的 pygame 引用
- 新增 fake_renderer_iter3 fixture（set_skin/handle_resize/skin_names/current_skin_name/render(interp=)）
- 新增 FakeEvent.make_resize_event 工厂（VIDEORESIZE 事件）
- app / app_in_playing 改造为"先 monkeypatch create_storage + Renderer 桩 + 注入 fake_storage 再 _init_pygame"——真实 IO 彻底断绝（G3-R-P1-A）
- app_with_storage 改造为 monkeypatch create_storage 返 tmp_path 实例（G3-R-P1-B）
- app_in_game_over fixture 头部显式 from game_core import GameStatus（G3-R-P1-C）
- 新增 app_with_config_v3 fixture（G3-4 验证）
"""
from __future__ import annotations

import sys
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest


# pygame key/type 常量（fake 与 fixture 共用；G3-2 新增 VIDEORESIZE）
_PYGAME_KEYS = {
    "QUIT": 256,
    "KEYDOWN": 768,
    "VIDEORESIZE": 16,  # G3-2 新增：SDL_VIDEORESIZE 常量值
    "K_w": 119, "K_s": 115, "K_a": 97, "K_d": 100,
    "K_UP": 1073741906, "K_DOWN": 1073741905,
    "K_LEFT": 1073741904, "K_RIGHT": 1073741903,
    "K_q": 113, "K_ESCAPE": 27, "K_p": 112, "K_r": 114,
    "K_h": 104,
    "K_BACKSPACE": 8,
    "K_RETURN": 13, "K_SPACE": 32,
    "K_1": 49, "K_2": 50, "K_3": 51,
}


def _build_fake_pygame() -> MagicMock:
    fake = MagicMock(name="fake_pygame")
    fake.error = RuntimeError
    for k, v in _PYGAME_KEYS.items():
        setattr(fake, k, v)
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
    # key
    fake.key.get_focused.return_value = True
    # surface for SRCALPHA
    fake.SRCALPHA = 65536
    return fake


@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app 内部所有 pygame 引用为可编程 fake。

    G3-R-P2-6 修订：替换列表补 config 模块。
    """
    fake = _build_fake_pygame()
    monkeypatch.setitem(sys.modules, "pygame", fake)
    import game_app.input as input_mod
    import game_app.menu as menu_mod
    import game_app.app as app_mod
    import game_app.fonts as fonts_mod
    import game_app.config as config_mod  # G3-R-P2-6 补 config 模块
    monkeypatch.setattr(input_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(menu_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(app_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(fonts_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(config_mod, "pygame", fake, raising=False)
    try:
        import gui_renderer.renderer as gui_renderer_mod
        monkeypatch.setattr(gui_renderer_mod, "pygame", fake, raising=False)
    except Exception:
        pass
    return fake


@pytest.fixture
def fake_storage():
    """iter-2 G2-2 沿用：fake HighScoreStore。"""
    storage = MagicMock(name="fake_storage")
    storage.load.return_value = 0
    storage.save = MagicMock(name="fake_save")
    storage.reset = MagicMock(name="fake_reset")
    return storage


@pytest.fixture
def fake_renderer_iter3():
    """G3 新增：fake Renderer 含 iter-3 接口。

    接口契约（见 gui_renderer iter-3 it_passed 契约）：
    - set_skin(name) -> None
    - handle_resize(w, h) -> None
    - skin_names() -> tuple[str, ...]
    - current_skin_name: str（属性）
    - render(snap, hud, *, interp=None) -> None
    - fps_metric() -> FpsMetric
    """
    renderer = MagicMock(name="fake_renderer")
    renderer.skin_names.return_value = ("classic", "dark", "colorblind_friendly")
    renderer.current_skin_name = "classic"
    renderer.set_skin = MagicMock(name="set_skin")
    renderer.handle_resize = MagicMock(name="handle_resize")
    renderer.render = MagicMock(name="render")
    renderer.fps_metric = MagicMock(name="fps_metric")
    renderer.cell_size = 24
    renderer.grid_cols = 20
    renderer.grid_rows = 15
    return renderer


@pytest.fixture
def app_uninitialized(fake_pygame):
    """iter-2 沿用：构造 App 不调 _init_pygame；_renderer is None，_storage is None。"""
    from game_app import App
    return App()


@pytest.fixture
def app(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """G3-R-P1-A 修订：先注入 fake_storage + monkeypatch create_storage/Renderer，再 _init_pygame。

    注入顺序：
    1. monkeypatch create_storage 返 fake_storage（避免真实 IO）
    2. monkeypatch Renderer 构造返 fake_renderer_iter3（避免真实 pygame init）
    3. _init_pygame() 内部：
       - self._renderer = fake_renderer_iter3
       - if self._storage is None: create_storage() → 返 fake_storage（已被 monkeypatch）
       - self._high_score = fake_storage.load() == 0
    """
    from game_app import App
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    return a


@pytest.fixture
def app_in_playing(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """G3-R-P1-A 修订：先注入 fake + monkeypatch，再 _init_pygame + _new_game。

    r2-3 修订：_new_game 内重置 _prev_snap = None（新局首帧瞬移渲染）。
    """
    from game_app import App
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from game_core import Difficulty
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_paused(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """iter-2 沿用 + G3-R-P1-A 修订。"""
    from game_app import App, InputAction, AppScreen
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from game_core import Difficulty
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
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
    """G3-R-P1-C 修订：fixture 头部显式 from game_core import GameStatus。"""
    import dataclasses
    from game_app import App, AppScreen
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from game_core import Difficulty, GameStatus  # G3-R-P1-C 修订
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
    a.screen = AppScreen.GAME_OVER
    return a


@pytest.fixture
def app_with_storage(tmp_path, fake_pygame, fake_renderer_iter3, monkeypatch):
    """G3-R-P1-B 修订：monkeypatch create_storage 返 tmp_path 实例（替代 fake）。"""
    from game_app import App
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from platform_storage import HighScoreStore
    real_storage = HighScoreStore(tmp_path / "highscore.json")
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: real_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    return a


@pytest.fixture
def app_with_config_v3(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """G3-4 新增：使用 AppConfigV3(enable_high_dpi=True) 构造 App。"""
    from game_app import App, AppConfigV3
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App(AppConfigV3(enable_high_dpi=True))
    a._init_pygame()
    return a


class FakeEvent:
    """pygame.event.Event 替身，fake_pygame.event.get 注入用。

    G3-2 修订：构造签名支持 w/h（VIDEORESIZE 事件用）。
    """

    __slots__ = ("type", "key", "w", "h")

    def __init__(
        self, type_: int, key: Optional[int] = None,
        w: Optional[int] = None, h: Optional[int] = None,
    ) -> None:
        self.type = type_
        self.key = key
        self.w = w
        self.h = h


def make_keydown(key: int) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], key)


def make_quit_event() -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["QUIT"])


def make_resize_event(w: int, h: int) -> FakeEvent:
    """G3-2 新增：构造 VIDEORESIZE 事件。"""
    return FakeEvent(_PYGAME_KEYS["VIDEORESIZE"], w=w, h=h)
