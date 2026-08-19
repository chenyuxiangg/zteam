"""pytest fixtures：fake_pygame 让 UT 在 headless 环境跑（CI 无显示器）。

所有 pygame 调用通过模块顶层 import，UT 用 monkeypatch 替换为 fake_pygame 模块。

迭代 3 增量（设计 §7.3 + §7.4）：
  - fake_pygame 必须提供 SCALED 常量（修订 P1-1 方案①）
  - FakeSurface 记录 blit 调用（修订 P1-1 断言 HUD 同色描边）
  - fake.display.set_mode 记录调用（size/flags）→ 供 hidpi/resize 断言
  - 增量 fixtures：renderer（enable_high_dpi=False）、renderer_high_dpi、prev_snapshot、
    interp_half、interp_no_food
"""
import os
import sys
import types

import pytest

# 把 game-core iter-1 的包目录加入 sys.path（gui-renderer 依赖 game-core 类型）
_GAMECORE_ROOT = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),  # .../gui-renderer/iter-3/tests
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
    # 修订 P1-1 方案①：fake_pygame 必须提供 SCALED 常量
    SCALED: int


_pg_module = FakePygameModule("fake_pygame")
# 修订 P1-1 方案①：SCALED 常量（与 pygame 2.x 一致 0x40000000）
_pg_module.SCALED = 0x40000000


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
    """pygame.Surface 的桩实现。

    迭代 3 增量：记录 blit 调用（修订 P1-1 断言 HUD 同色描边）。
    """

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
    """pygame.display.set_mode 桩。

    迭代 3 增量：记录调用（size/flags）→ 供 hidpi/resize 断言。
    返回 FakeSurface(size)。
    """
    flags = kwargs.get("flags", args[0] if args else 0)
    _set_mode_calls.append((tuple(size), int(flags)))
    return FakeSurface(size)


_set_mode_calls: list = []


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
display_mod.set_mode_calls = _set_mode_calls
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
    _set_mode_calls.clear()
    _Time.ticks[0] = 0
    _Time.tick_increment = 16


# ---- pytest fixtures ----

def _resolve_pg_module():
    """返回 fake_pygame 模块对象（跨 conftest 实例单例化）。

    pytest 通过两套路径加载 conftest.py：一次作为顶层模块（fixture 用），一次作为
    `tests.conftest` 子模块（测试代码 `from tests.conftest import` 用）。两套实例化
    会各自创建 _pg_module，导致 monkeypatch 替换的 rmod.pygame 是「顶层 conftest 」
    的 _pg_module，而测试断言读的是「tests.conftest」的 _pg_module._set_mode_calls，
    set_mode 被 append 到「顶层」的 list，「tests.conftest」的 list 仍空。

    修复：fixture 内 lazy 走 `sys.modules['tests.conftest']` 拿 tests 包版本，
    让两套 conftest 共享同一个 _pg_module + 同一个 _set_mode_calls / _draw_calls。
    """
    import sys as _sys
    mod = _sys.modules.get("tests.conftest")
    if mod is not None and getattr(mod, "_pg_module", None) is not None:
        return mod, mod._pg_module
    return sys.modules[__name__], _pg_module


@pytest.fixture
def fake_pygame(monkeypatch):
    """把 gui_renderer.renderer 模块顶层的 pygame 替换为 fake_pygame 模块。

    用法：
        def test_x(fake_pygame, renderer):
            _pg_module.draw.calls.reset()  # 如需清空
            ...
    """
    import gui_renderer.renderer as rmod
    _mod, pg = _resolve_pg_module()
    monkeypatch.setattr(rmod, "pygame", pg)
    _mod.reset_fake_pygame()
    return pg


@pytest.fixture
def renderer(fake_pygame):
    """构造已 init() 的 Renderer（最小窗口尺寸；修订 P1-1 方案②：enable_high_dpi=False）。"""
    from gui_renderer import Renderer

    r = Renderer((640, 480), enable_high_dpi=False)
    r.init()
    yield r
    try:
        r.shutdown()
    except Exception:
        pass


@pytest.fixture
def renderer_high_dpi(fake_pygame):
    """高分屏专用 fixture（修订 P1-1 方案②：显式 enable_high_dpi=True）。

    依赖 fake_pygame.SCALED 常量（方案①）。仅用于 test_renderer_hidpi.py 等专项用例。
    """
    from gui_renderer import Renderer

    r = Renderer((640, 480), enable_high_dpi=True)
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


# ---- 迭代 3 增量 fixtures（设计 §7.3）----

@pytest.fixture
def prev_snapshot():
    """game-core 初始快照：未推进 step，蛇身长度 3、初始方向 RIGHT、食物位置由 seed 决定。

    game-core 实测初始布局（state.py）：
      - 蛇身长度 = INITIAL_SNAKE_LEN = 3
      - 蛇头位置 (width // 2, height // 2) = (10, 7)（GRID_COLS=20, GRID_ROWS=15）
      - 蛇身 (10,7)→(9,7)→(8,7)（向左延伸，方向 RIGHT）
      - 食物位置：(rng 首次调用 → 与蛇身不重叠的随机格）

    修订 P3-5：fixture 显式断言初始值（蛇长 3 / 状态 RUN / 难度 MEDIUM / tick_ms=160）。
    """
    from game_core import Difficulty, GameState, GameStatus

    state = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM)  # keyword 写法（修订 P1-2）
    snap = state.snapshot()
    assert len(snap.snake_body) == 3, f"初始蛇长应为 3，实际 {len(snap.snake_body)}"
    assert snap.status == GameStatus.RUN
    assert snap.difficulty == Difficulty.MEDIUM
    assert snap.tick_ms == 160  # MEDIUM 基线节拍
    return snap


@pytest.fixture
def interp_half(prev_snapshot):
    """alpha=0.5 的插值上下文（prev = 当前快照的复制，模拟同位置）。"""
    from gui_renderer import InterpolationState

    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    food = (prev_snapshot.food.x, prev_snapshot.food.y)
    return InterpolationState(
        alpha=0.5,
        prev_snake_body=body,
        prev_food=food,
    )


@pytest.fixture
def interp_no_food(prev_snapshot):
    """修订 P2-1：prev_food=None 的插值上下文（吃食节拍场景）。"""
    from gui_renderer import InterpolationState

    body = tuple((p.x, p.y) for p in prev_snapshot.snake_body)
    return InterpolationState(
        alpha=0.5,
        prev_snake_body=body,
        prev_food=None,
    )
