"""pytest fixtures：fake_pygame 让 UT 在 headless 环境跑（CI 无显示器）。

所有 pygame 调用通过模块顶层 import，UT 用 monkeypatch 替换为 fake_pygame 模块。
"""
import os
import sys
import types

import pytest

# 把 game-core iter-1 的包目录加入 sys.path（gui-renderer 依赖 game-core.Snapshot 类型）
_GAMECORE_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),  # .../gui-renderer/iter-1/tests
        "..", "..", "..", "..", "code", "game-core", "iter-1",
    )
)
if _GAMECORE_ROOT not in sys.path:
    sys.path.insert(0, _GAMECORE_ROOT)

# 模块级 fake pygame（命名 _pg_module 避免与同名 fixture 函数冲突）
class FakePygameModule(types.ModuleType):
    """允许动态属性挂载（setattr init/quit/display/draw/...）以模拟真实 pygame 模块。"""

    init: object
    quit: object
    display: object
    draw: object
    font: object
    time: object
    draw_calls: object


_pg_module = FakePygameModule("fake_pygame")


class _DrawCalls:
    """记录 pygame.draw.rect 调用列表（list of (color, rect, width)）。

    每次 render 不会自动清空——UT 自行在断言前 reset 或记录调用前的长度。
    """

    def __init__(self) -> None:
        self.records: list[tuple] = []

    def append(self, record: tuple) -> None:
        self.records.append(record)

    def reset(self) -> None:
        self.records.clear()

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, idx):
        return self.records[idx]


class FakeSurface:
    """pygame.Surface 的桩实现。"""

    def __init__(self, size: tuple[int, int]) -> None:
        self.size = size
        self.fill_calls: list = []
        self.blit_calls: list = []

    def fill(self, color) -> None:
        self.fill_calls.append((color,))

    def get_size(self) -> tuple[int, int]:
        return self.size

    def blit(self, surface, dest) -> None:
        self.blit_calls.append((surface, dest))


class FakeFont:
    """pygame.font.Font / SysFont 的桩实现。"""

    def __init__(self, *args, **kwargs) -> None:
        self.render_calls: list = []

    def render(self, text: str, aa, color):
        self.render_calls.append((text, aa, color))
        return FakeSurface((len(str(text)) * 8, 16))


# ---- 构造 fake_pygame 模块（fake_pygame.display / draw / font / time 全部存在）----

_draw_calls = _DrawCalls()
_pg_module.draw_calls = _draw_calls


def _set_mode(size, *args, **kwargs):
    return FakeSurface(size)


def _flip():
    pass


def _display_quit():
    pass


def _draw_rect(surface, color, rect, width: int = 0):
    _draw_calls.append((color, rect, width))


def _font_init():
    pass


def _font_quit():
    pass


class _Time:
    ticks: list[int] = [0]
    tick_increment: int = 16

    @staticmethod
    def get_ticks() -> int:
        _Time.ticks[0] += _Time.tick_increment
        return _Time.ticks[0]


def _pygame_init():
    pass


def _pygame_quit():
    pass


# 命名空间属性挂载（避免在类内做属性赋值）
_pg_module.init = _pygame_init
_pg_module.quit = _pygame_quit

display_mod = types.SimpleNamespace(
    set_mode=_set_mode,
    flip=_flip,
    quit=_display_quit,
)
_pg_module.display = display_mod

draw_mod = types.SimpleNamespace(rect=_draw_rect)
draw_mod.calls = _draw_calls  # 暴露给 UT 读取（_pg_module.draw.calls 风格）
_pg_module.draw = draw_mod

font_mod = types.SimpleNamespace(
    init=_font_init,
    quit=_font_quit,
    SysFont=FakeFont,
    Font=FakeFont,
)
_pg_module.font = font_mod

_pg_module.time = _Time()


def reset_fake_pygame() -> None:
    """UT 入口调用：清空所有调用记录，ticks 归零。"""
    _draw_calls.reset()
    _Time.ticks[0] = 0
    _Time.tick_increment = 16


# ---- pytest fixtures ----

@pytest.fixture
def fake_pygame(monkeypatch):
    """把 gui_renderer.renderer 模块顶层的 pygame 替换为 fake_pygame 模块。

    用法：
        def test_x(fake_pygame, renderer):
            _pg_module.draw.calls.reset()  # 如需清空
            ...
    """
    import gui_renderer.renderer as rmod
    monkeypatch.setattr(rmod, "pygame", _pg_module)
    reset_fake_pygame()
    return _pg_module


@pytest.fixture
def renderer(fake_pygame):
    """构造已 init() 的 Renderer（最小窗口尺寸）。"""
    from gui_renderer import Renderer

    r = Renderer((512, 472))
    r.init()
    yield r
    try:
        r.shutdown()
    except Exception:
        pass


@pytest.fixture
def minimal_window_size():
    """满足最小可玩尺寸的窗口尺寸（512 × 472）。"""
    return (512, 472)