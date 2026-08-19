"""pytest 全局配置 + gui-renderer IT 专用 fake_pygame 注入。

不依赖 `snake-linux/code/gui-renderer/iter-1/tests/conftest.py`，IT 目录独立运行。
注入方式与模块代码 conftest.py 一致（monkeypatch `gui_renderer.renderer.pygame`）。

执行：pytest -v
"""
import os
import sys
import types
from pathlib import Path

import pytest

# ---- 路径注入（被测代码定位） ----
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/gui-renderer/iter-1 -> snake-linux
_GUI_CODE = _WORKSPACE / "code" / "gui-renderer" / "iter-1"
_GAMECORE_CODE = _WORKSPACE / "code" / "game-core" / "iter-1"
for p in (str(_GUI_CODE), str(_GAMECORE_CODE)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


# ---- fake_pygame 模块（与模块代码 conftest.py 行为等价） ----

class _DrawCalls:
    def __init__(self) -> None:
        self.records: list = []

    def append(self, record):
        self.records.append(record)

    def reset(self):
        self.records.clear()

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, idx):
        return self.records[idx]


class FakeSurface:
    def __init__(self, size):
        self.size = size
        self.fill_calls: list = []
        self.blit_calls: list = []

    def fill(self, color):
        self.fill_calls.append((color,))

    def get_size(self):
        return self.size

    def blit(self, surface, dest):
        self.blit_calls.append((surface, dest))


class FakeFont:
    def __init__(self, *args, **kwargs):
        self.render_calls: list = []

    def render(self, text, aa, color):
        self.render_calls.append((text, aa, color))
        return FakeSurface((len(str(text)) * 8, 16))


_draw_calls = _DrawCalls()
_pg_module = types.ModuleType("fake_pygame")
_pg_module.draw_calls = _draw_calls


def _set_mode(size, *args, **kwargs):
    return FakeSurface(size)


_pg_module.display = types.SimpleNamespace(
    set_mode=_set_mode,
    flip=lambda: None,
    quit=lambda: None,
)
_pg_module.draw = types.SimpleNamespace(rect=lambda s, c, r, width=0, w=0: _draw_calls.append((c, r, width or w)))
_pg_module.draw.calls = _draw_calls
_pg_module.font = types.SimpleNamespace(
    init=lambda: None,
    quit=lambda: None,
    SysFont=FakeFont,
    Font=FakeFont,
)


class _Time:
    ticks: list = [0]
    tick_increment: int = 16

    @staticmethod
    def get_ticks():
        _Time.ticks[0] += _Time.tick_increment
        return _Time.ticks[0]


_pg_module.time = _Time()
_pg_module.init = lambda: None
_pg_module.quit = lambda: None


def reset_fake_pygame() -> None:
    _draw_calls.reset()
    _Time.ticks[0] = 0
    _Time.tick_increment = 16


# ---- pytest fixtures ----

@pytest.fixture
def fake_pg(monkeypatch):
    import gui_renderer.renderer as rmod
    monkeypatch.setattr(rmod, "pygame", _pg_module)
    reset_fake_pygame()
    return _pg_module


@pytest.fixture
def renderer(fake_pg):
    from gui_renderer import Renderer
    r = Renderer((512, 472))
    r.init()
    yield r
    try:
        r.shutdown()
    except Exception:
        pass


@pytest.fixture
def default_window_renderer(fake_pg):
    from gui_renderer import Renderer, WINDOW_WIDTH, WINDOW_HEIGHT
    r = Renderer((WINDOW_WIDTH, WINDOW_HEIGHT))
    r.init()
    yield r
    try:
        r.shutdown()
    except Exception:
        pass


def pytest_configure(config):
    config.addinivalue_line("markers", "p0: P0 用例（核心功能/发布阻塞）")
    config.addinivalue_line("markers", "p1: P1 用例（重要功能边界）")
    config.addinivalue_line("markers", "p2: P2 用例（体验细节）")
