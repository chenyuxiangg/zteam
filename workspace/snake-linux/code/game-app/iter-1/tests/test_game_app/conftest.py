"""game-app 测试 conftest：pygame 桩 + App fixture。

G2 iter-2 增量（P2-1 修订）：
- fake_pygame 同时替换 game_app.input 模块的 pygame 引用
- 新增 fake_storage fixture
- app / app_in_playing 改造为先 _init_pygame 再注入 fake_storage（P1-3）
- 新增 app_in_paused / app_in_game_over / app_with_storage fixtures
"""
from __future__ import annotations

import sys
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest


# pygame key 常量（fake 与 fixture 共用）
_PYGAME_KEYS = {
    "QUIT": 256,
    "KEYDOWN": 768,
    "K_w": 119, "K_s": 115, "K_a": 97, "K_d": 100,
    "K_UP": 1073741906, "K_DOWN": 1073741905,
    "K_LEFT": 1073741904, "K_RIGHT": 1073741903,
    "K_q": 113, "K_ESCAPE": 27, "K_p": 112, "K_r": 114,
    "K_h": 104,                                                # G2-3 新增
    "K_BACKSPACE": 8,                                          # G2-7 新增
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
    fake.font.match_font.return_value = None  # 默认无 CJK → 走 Font(None, size)
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
    # key (G2-4)
    fake.key.get_focused.return_value = True
    # surface for SRCALPHA (G2-5)
    fake.SRCALPHA = 65536
    return fake


@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app 内部所有 pygame 引用为可编程 fake。

    P2-1 iter-2 修订：同时替换 game_app.input 模块的 pygame 引用。
    """
    fake = _build_fake_pygame()
    monkeypatch.setitem(sys.modules, "pygame", fake)
    # 重新加载（或首次 import）时引用 fake
    import game_app.input as input_mod
    import game_app.menu as menu_mod
    import game_app.app as app_mod
    import game_app.fonts as fonts_mod
    monkeypatch.setattr(input_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(menu_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(app_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(fonts_mod, "pygame", fake, raising=False)
    # 同步替换 gui_renderer.renderer 内部的 pygame 引用，
    # 让 Renderer.init()/shutdown()/render() 走 fake（避免真 pygame 副作用）
    try:
        import gui_renderer.renderer as gui_renderer_mod
        monkeypatch.setattr(gui_renderer_mod, "pygame", fake, raising=False)
    except Exception:
        pass
    return fake


@pytest.fixture
def fake_storage():
    """G2-2：fake HighScoreStore，UT 注入 storage.load/save/reset 行为。"""
    storage = MagicMock(name="fake_storage")
    storage.load.return_value = 0
    storage.save = MagicMock(name="fake_save")
    storage.reset = MagicMock(name="fake_reset")
    return storage


@pytest.fixture
def app_uninitialized(fake_pygame):
    """iter-2 新增：构造 App 不调 _init_pygame；_renderer is None，_storage is None。"""
    from game_app import App
    return App()


@pytest.fixture
def app(fake_pygame, fake_storage):
    """构造 App + _init_pygame + 注入 fake_storage（P1-3 注入顺序）。

    P1-3 修订：_init_pygame 内 `if self._storage is None: create_storage()` 此时 _storage
    为 None → 调 create_storage（创建真 HighScoreStore 默认路径）。但 UT fixture 在
    _init_pygame 之后注入 fake_storage 覆盖。
    """
    from game_app import App
    a = App()
    a._init_pygame()
    a._storage = fake_storage                                   # P1-3：覆盖
    a._high_score = fake_storage.load.return_value
    return a


@pytest.fixture
def app_with_mock_renderer(fake_pygame, fake_storage):
    """App 已 _init_pygame（用 mock renderer）+ 进入 PLAYING 态。

    与 app_in_playing 不同：renderer 整个被替换为 MagicMock，避免真渲染副作用。
    用于 _render 分发测试。
    """
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._difficulty = Difficulty.HARD
    # 用 mock renderer 替掉 _init_pygame 内部的真构造
    mock_renderer = MagicMock(name="mock_renderer")
    a._renderer = mock_renderer
    a._menu_title_font = MagicMock(name="title_font")
    a._menu_body_font = MagicMock(name="body_font")
    a.clock = MagicMock(name="clock")
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    # 创建 game_state
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_playing(fake_pygame, fake_storage):
    """App 已 _init_pygame + 注入 fake + 进入 PLAYING 态。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_paused(fake_pygame, fake_storage):
    """G2-1：PLAYING 态触发 toggle_pause 后进入 PAUSED（P0-1 屏态同步方案 A 验证）。"""
    from game_app import App, InputAction, AppScreen
    from game_core import Difficulty
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)              # P0-1：dispatch 内同步切屏
    assert a.screen == AppScreen.PAUSED                        # INV-10/11 验证
    return a


@pytest.fixture
def app_in_game_over(fake_pygame, fake_storage):
    """G2-7 / P2-2：构造 GAME_OVER 态应用（手动把 status 置 OVER）。"""
    import dataclasses
    from game_app import App, AppScreen
    from game_core import Difficulty, GameStatus
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    # 手动把 status 置 OVER（绕开真实 step 撞墙）
    a.game_state = dataclasses.replace(
        a.game_state, status=GameStatus.OVER
    )
    a.screen = AppScreen.GAME_OVER
    return a


@pytest.fixture
def app_with_storage(tmp_path, fake_pygame):
    """G2-2：用 tmp_path 注入真实 HighScoreStore（替代 fake），测真实 IO 路径。"""
    from game_app import App
    from platform_storage import HighScoreStore
    a = App()
    a._init_pygame()
    a._storage = HighScoreStore(tmp_path / "highscore.json")
    a._high_score = a._storage.load()
    return a


class FakeEvent:
    """pygame.event.Event 替身，fake_pygame.event.get 注入用。"""

    __slots__ = ("type", "key")

    def __init__(self, type_: int, key: Optional[int] = None) -> None:
        self.type = type_
        self.key = key


def make_keydown(key: int) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], key)


def make_quit_event() -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["QUIT"])