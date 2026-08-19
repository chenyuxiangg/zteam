"""pytest 全局配置 + gui-renderer iter-3 IT 专用 fake_pygame 注入。

迭代 3 增量：
- fake_pygame 增加 blit 调用记录（修订 P1-1：HUD 每段 1 阴影 blit + 1 主版 blit）
- fake_pygame 增加 set_mode flags 记录（NFR-04 高分屏验证）
- pygame 注入 SCALED 标志（getattr(pygame, "SCALED", 0) 路径）

执行：pytest -v
"""
import os
import sys
import types
from pathlib import Path

import pytest

# ---- 路径注入（被测代码定位） ----
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/gui-renderer/iter-3 -> snake-linux
_GUI_CODE = _WORKSPACE / "code" / "gui-renderer" / "iter-3"
_GAMECORE_CODE = _WORKSPACE / "code" / "game-core" / "iter-1"
for p in (str(_GUI_CODE), str(_GAMECORE_CODE)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


# ---- fake_pygame 模块（迭代 1 模式 + 迭代 3 增量：blit/flags 记录） ----

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
        self.blit_calls: list = []  # 迭代 3 增量：HUD 阴影 blit 断言

    def fill(self, color):
        self.fill_calls.append((color,))

    def get_size(self):
        return self.size

    def blit(self, surface, dest):
        # 记录 (surface_id, dest_tuple)
        self.blit_calls.append((id(surface), dest))


class FakeFont:
    def __init__(self, *args, **kwargs):
        self.render_calls: list = []

    def render(self, text, aa, color):
        self.render_calls.append((text, aa, color))
        return FakeSurface((len(str(text)) * 8, 16))


_draw_calls = _DrawCalls()
_pg_module = types.ModuleType("fake_pygame")
_pg_module.draw_calls = _draw_calls

# 迭代 3 增量：set_mode 记录 flags（NFR-04 高分屏验证）
_set_mode_calls: list = []


def _set_mode(size, *args, **kwargs):
    flags = args[0] if args else kwargs.get("flags", 0)
    _set_mode_calls.append({"size": size, "flags": flags})
    return FakeSurface(size)


# 迭代 3 增量：模拟 pygame.SCALED（pygame 2.x = 0x40000000）
_pg_module.SCALED = 0x40000000

_pg_module.display = types.SimpleNamespace(
    set_mode=_set_mode,
    flip=lambda: None,
    quit=lambda: None,
)
_pg_module.draw = types.SimpleNamespace(
    rect=lambda s, c, r, width=0, w=0: _draw_calls.append((c, r, width or w))
)
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
    _set_mode_calls.clear()


# ---- pytest fixtures ----

@pytest.fixture
def fake_pg(monkeypatch):
    import gui_renderer.renderer as rmod
    monkeypatch.setattr(rmod, "pygame", _pg_module)
    reset_fake_pygame()
    return _pg_module


@pytest.fixture
def renderer(fake_pg):
    """已 init() 的 Renderer（最小可玩尺寸 512x472）。"""
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
    """默认窗口尺寸 (640, 480) 的 Renderer。"""
    from gui_renderer import Renderer, WINDOW_WIDTH, WINDOW_HEIGHT
    r = Renderer((WINDOW_WIDTH, WINDOW_HEIGHT))
    r.init()
    yield r
    try:
        r.shutdown()
    except Exception:
        pass


@pytest.fixture
def set_mode_calls():
    return _set_mode_calls


def pytest_configure(config):
    config.addinivalue_line("markers", "p0: P0 用例（核心功能/发布阻塞）")
    config.addinivalue_line("markers", "p1: P1 用例（重要功能边界）")
    config.addinivalue_line("markers", "p2: P2 用例（体验细节）")