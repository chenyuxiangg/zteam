"""模块 IT 测试：gui-renderer（snake-linux v2.0.0 迭代 1）。

按 `snake-linux/it/gui-renderer/iter-1/测试用例.md` 落地，pytest 9.x。
覆盖 FR-06（基础渲染闭环）、NFR-01（fps 接口）、NFR-05（职责分离）、NFR-06（无网络）；
运行通过 fake_pygame 模块替换 pygame（设计 §4.2 可测性）。

执行：pytest test_it_gui_renderer_1.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# ---- 路径定位（与 game-core IT 模板一致） ----
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[2]  # it/gui-renderer/iter-1 -> snake-linux
_GUI_CODE = _WORKSPACE / "code" / "gui-renderer" / "iter-1"
_GAMECORE_CODE = _WORKSPACE / "code" / "game-core" / "iter-1"
sys.path.insert(0, str(_GUI_CODE))
sys.path.insert(0, str(_GAMECORE_CODE))

# 路径注入与 fake_pygame 来自 conftest.py
from gui_renderer import (  # noqa: E402
    CELL_SIZE,
    DEFAULT_SKIN,
    GRID_COLS,
    GRID_ROWS,
    HUD_HEIGHT,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
    Color,
    FpsMetric,
    HudData,
    RenderError,
    Renderer,
    Skin,
)
from gui_renderer.constants import PLAYFIELD_X, PLAYFIELD_Y  # noqa: E402
from game_core import Difficulty, GameStatus, Point, Snapshot  # noqa: E402


# 路径与 fake_pygame 注入由本目录 conftest.py 提供（pytest 自动发现）。


@pytest.fixture
def renderer(fake_pg):
    """已 init() 的 Renderer（最小可玩尺寸）。"""
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
    r = Renderer((WINDOW_WIDTH, WINDOW_HEIGHT))
    r.init()
    yield r
    try:
        r.shutdown()
    except Exception:
        pass


def _make_snapshot(snake=((10, 7), (9, 7), (8, 7)), food=(15, 7), score=0,
                   length=3, status=GameStatus.RUN, difficulty=Difficulty.MEDIUM):
    """构造 game_core.Snapshot（真实跨模块契约）。"""
    return Snapshot(
        snake_body=tuple(Point(*p) for p in snake),
        food=Point(*food),
        score=score,
        length=length,
        status=status,
        difficulty=difficulty,
        tick_ms=160,
    )


def _make_hud(score=0, high_score=128, length=3, difficulty_label="MEDIUM",
              status_label="RUN"):
    return HudData(score=score, high_score=high_score, length=length,
                   difficulty_label=difficulty_label, status_label=status_label)


# ---------- IT-01~08：渲染闭环 ----------

@pytest.mark.p0
def test_it_gui_renderer_1_01_first_frame_renders_all_elements(default_window_renderer, fake_pg):
    """IT-gui-renderer-1-01 首帧渲染：蛇/食物/背景/HUD 元素均出现。FR-06."""
    snap = _make_snapshot()
    hud = _make_hud()

    default_window_renderer.render(snap, hud)

    # 背景：surface.fill 调用 1 次，颜色 = background
    screen = default_window_renderer._screen  # type: ignore[attr-defined]
    assert len(screen.fill_calls) == 1, "背景 fill 应被调用 1 次"
    assert screen.fill_calls[0][0] == DEFAULT_SKIN.background, "FR-06 背景色应为 DEFAULT_SKIN.background"

    # draw.rect：3 蛇节 + 2 食物（填充 + outline）= ≥ 5 次
    draw_calls = fake_pg.draw.calls
    rect_calls = [c for c in draw_calls if c[2] == 0]  # 填充
    outline_calls = [c for c in draw_calls if c[2] == 1]  # outline width=1
    assert len(rect_calls) >= 3, f"蛇身 3 节应至少 3 次 fill 矩形，实际 {len(rect_calls)}"
    assert len(outline_calls) == 1, f"食物 outline 应 1 次（width=1），实际 {len(outline_calls)}"

    # HUD 5 行
    font = default_window_renderer._font  # type: ignore[attr-defined]
    assert len(font.render_calls) == 5, f"HUD 应 5 行文本，实际 {len(font.render_calls)}"

    # 蛇头像素位置（PLAYFIELD_Y = HUD_HEIGHT + 16 = 96；head_y = 96 + 7*24 = 264）
    head_px = PLAYFIELD_X + 10 * CELL_SIZE
    head_py = PLAYFIELD_Y + 7 * CELL_SIZE
    assert (head_px, head_py) == (256, 264), "FR-06 蛇头像素坐标计算（HEAD=10 行=Y=7）"

    # 蛇头颜色 = snake_head
    head_color_calls = [c for c in draw_calls if c[0] == DEFAULT_SKIN.snake_head]
    assert len(head_color_calls) == 1, "FR-06 蛇头颜色 = snake_head"

    # 食物填充颜色 + outline 颜色
    food_fill = [c for c in draw_calls if c[0] == DEFAULT_SKIN.food and c[2] == 0]
    food_outline = [c for c in draw_calls if c[0] == DEFAULT_SKIN.food_outline and c[2] == 1]
    assert len(food_fill) >= 1, "FR-06 食物填充颜色"
    assert len(food_outline) == 1, "FR-06 食物 outline 颜色"

    # 食物像素位置（与蛇头同 Y=7，X=15）
    fpx_expected = PLAYFIELD_X + 15 * CELL_SIZE
    fpy_expected = PLAYFIELD_Y + 7 * CELL_SIZE
    assert food_fill[0][1] == (fpx_expected, fpy_expected, CELL_SIZE - 1, CELL_SIZE - 1), \
        f"FR-06 食物 rect = ({fpx_expected},{fpy_expected},23,23)"


@pytest.mark.p0
def test_it_gui_renderer_1_02_head_vs_body_color(renderer, fake_pg):
    """IT-gui-renderer-1-02 蛇头 vs 蛇身颜色。FR-06."""
    snap = _make_snapshot(snake=((5, 5), (4, 5), (3, 5), (2, 5)))  # 4 节
    hud = _make_hud(length=4)

    renderer.render(snap, hud)

    draw_calls = fake_pg.draw.calls
    # 蛇头 = body[0] 用 snake_head；body[1:] 用 snake_body
    head_calls = [c for c in draw_calls if c[0] == DEFAULT_SKIN.snake_head]
    body_calls = [c for c in draw_calls if c[0] == DEFAULT_SKIN.snake_body]
    assert len(head_calls) == 1, "FR-06 蛇头 1 节"
    assert len(body_calls) == 3, f"FR-06 蛇身 3 节（除头），实际 {len(body_calls)}"


@pytest.mark.p0
def test_it_gui_renderer_1_03_snake_len_n_calls_draw_rect_n_times(renderer, fake_pg):
    """IT-gui-renderer-1-03 蛇身长度 N：draw.rect 调用 N 次（蛇节）。FR-06."""
    for n in (1, 3, 5, 8):
        # 重置记录
        from conftest import reset_fake_pygame
        reset_fake_pygame()
        snake = tuple((x, 5) for x in range(n))  # 任意 n 节
        snap = _make_snapshot(snake=snake, food=(0, 0), length=n)
        hud = _make_hud(length=n)
        renderer.render(snap, hud)

        draw_calls = fake_pg.draw.calls
        snake_calls = [c for c in draw_calls
                       if c[0] in (DEFAULT_SKIN.snake_head, DEFAULT_SKIN.snake_body)]
        assert len(snake_calls) == n, f"FR-06 蛇身 {n} 节应 {n} 次 draw.rect，实际 {len(snake_calls)}"


@pytest.mark.p0
def test_it_gui_renderer_1_04_food_fill_and_outline(renderer, fake_pg):
    """IT-gui-renderer-1-04 食物渲染：填充 + 1px outline。FR-06."""
    from conftest import reset_fake_pygame
    reset_fake_pygame()
    snap = _make_snapshot(snake=((5, 5),), food=(10, 10))  # 蛇 1 节，避免蛇节色干扰
    hud = _make_hud(length=1)

    renderer.render(snap, hud)

    draw_calls = fake_pg.draw.calls
    food_fill = [c for c in draw_calls if c[0] == DEFAULT_SKIN.food and c[2] == 0]
    food_outline = [c for c in draw_calls if c[0] == DEFAULT_SKIN.food_outline and c[2] == 1]
    assert len(food_fill) == 1, "FR-06 食物填充 1 次（width=0）"
    assert len(food_outline) == 1, "FR-06 食物 outline 1 次（width=1）"

    # food_rect 像素位置
    expected_rect = (PLAYFIELD_X + 10 * CELL_SIZE,
                     PLAYFIELD_Y + 10 * CELL_SIZE,
                     CELL_SIZE - 1, CELL_SIZE - 1)
    assert food_fill[0][1] == expected_rect, f"FR-06 食物 rect = {expected_rect}"


@pytest.mark.p0
def test_it_gui_renderer_1_05_hud_five_text_lines(renderer):
    """IT-gui-renderer-1-05 HUD 文本 5 行。FR-06."""
    snap = _make_snapshot()
    hud = _make_hud(score=42, high_score=128, length=15,
                    difficulty_label="HARD", status_label="RUN")

    renderer.render(snap, hud)

    font = renderer._font  # type: ignore[attr-defined]
    texts = [call[0] for call in font.render_calls]
    assert any("Score: 42" in t for t in texts), "FR-06 HUD 第 1 行：Score"
    assert any("High: 128" in t for t in texts), "FR-06 HUD 第 1 行：High（强调）"
    assert any("Length: 15" in t for t in texts), "FR-06 HUD 第 1 行：Length"
    assert any("Difficulty: HARD" in t for t in texts), "FR-06 HUD 第 2 行：Difficulty"
    assert any("Status: RUN" in t for t in texts), "FR-06 HUD 第 2 行：Status"


@pytest.mark.p0
def test_it_gui_renderer_1_06_hud_status_over_uses_accent(renderer):
    """IT-gui-renderer-1-06 HUD Status=OVER 高亮用 hud_accent。FR-06."""
    snap = _make_snapshot(status=GameStatus.OVER)
    hud = _make_hud(status_label="OVER")

    renderer.render(snap, hud)

    font = renderer._font  # type: ignore[attr-defined]
    over_calls = [c for c in font.render_calls if "Status: OVER" in c[0]]
    assert len(over_calls) == 1, "FR-06 Status: OVER 1 次"
    assert over_calls[0][2] == DEFAULT_SKIN.hud_accent, "FR-06 OVER 状态用 hud_accent 高亮"


@pytest.mark.p1
def test_it_gui_renderer_1_07_hud_status_non_over_uses_text(renderer):
    """IT-gui-renderer-1-07 HUD Status 非 OVER 用 hud_text。FR-06."""
    for label in ("RUN", "PAUSED"):
        from conftest import reset_fake_pygame
        reset_fake_pygame()
        snap = _make_snapshot()
        hud = _make_hud(status_label=label)
        renderer.render(snap, hud)

        font = renderer._font  # type: ignore[attr-defined]
        status_calls = [c for c in font.render_calls if f"Status: {label}" in c[0]]
        assert len(status_calls) == 1, f"FR-06 Status: {label} 1 次"
        assert status_calls[0][2] == DEFAULT_SKIN.hud_text, f"FR-06 {label} 状态用 hud_text"


@pytest.mark.p0
def test_it_gui_renderer_1_08_background_fill_once(renderer):
    """IT-gui-renderer-1-08 背景填充 1 次，颜色 = skin.background。FR-06."""
    snap = _make_snapshot()
    hud = _make_hud()

    renderer.render(snap, hud)

    screen = renderer._screen  # type: ignore[attr-defined]
    assert len(screen.fill_calls) == 1, "FR-06 背景 fill 应被调用 1 次"
    assert screen.fill_calls[0][0] == DEFAULT_SKIN.background, "FR-06 背景色 = DEFAULT_SKIN.background"


# ---------- IT-09~13：帧率 ----------

@pytest.mark.p0
def test_it_gui_renderer_1_09_fps_sample_appended_after_render(renderer):
    """IT-gui-renderer-1-09 单次 render 后 samples +1。NFR-01."""
    before = len(renderer._fps.samples)  # type: ignore[attr-defined]
    renderer.render(_make_snapshot(), _make_hud())
    after = len(renderer._fps.samples)  # type: ignore[attr-defined]
    assert after == before + 1, f"NFR-01 render 后 samples 应 +1：{before} -> {after}"


@pytest.mark.p1
def test_it_gui_renderer_1_10_fps_samples_capacity_120(renderer):
    """IT-gui-renderer-1-10 samples 容量上限 120。NFR-01."""
    from conftest import reset_fake_pygame, _Time
    assert renderer._fps.samples.maxlen == 120, "NFR-01 samples 容量应 120"

    # 跑 150 次 render，超过容量
    reset_fake_pygame()
    _Time.tick_increment = 1  # 提速
    for _ in range(150):
        renderer.render(_make_snapshot(), _make_hud())
    assert len(renderer._fps.samples) == 120, f"NFR-01 容量满后稳定 120，实际 {len(renderer._fps.samples)}"


@pytest.mark.p1
def test_it_gui_renderer_1_11_fps_p95_falls_back_to_mean_when_lt_20():
    """IT-gui-renderer-1-11 样本 < 20 时 P95 降级为 mean。NFR-01."""
    fm = FpsMetric()
    for ms in (10, 20, 30, 40, 50):
        fm.samples.append(float(ms))
    # 5 个样本时 P95 应 = mean = 30
    assert fm.p95_frame_ms == 30.0, f"NFR-01 < 20 样本 P95 = mean：实际 {fm.p95_frame_ms}"


@pytest.mark.p1
def test_it_gui_renderer_1_12_fps_empty_returns_zeros():
    """IT-gui-renderer-1-12 样本为空时 P95=0、fps=0。NFR-01."""
    fm = FpsMetric()
    assert fm.p95_frame_ms == 0.0, "NFR-01 空样本 P95=0"
    assert fm.fps == 0.0, "NFR-01 空样本 fps=0"


@pytest.mark.p1
def test_it_gui_renderer_1_13_fps_samples_accumulate_across_renders(renderer):
    """IT-gui-renderer-1-13 多次 render 累加 samples 长度。NFR-01."""
    for n in (3, 5, 10):
        before = len(renderer._fps.samples)  # type: ignore[attr-defined]
        for _ in range(n):
            renderer.render(_make_snapshot(), _make_hud())
        after = len(renderer._fps.samples)  # type: ignore[attr-defined]
        assert after == before + n, f"NFR-01 {n} 次 render 后 samples 应 +{n}"


# ---------- IT-14：几何映射 ----------

@pytest.mark.p0
def test_it_gui_renderer_1_14_grid_to_pixel_mapping(renderer):
    """IT-gui-renderer-1-14 网格→像素映射。FR-06."""
    cases = [
        ((0, 0), (PLAYFIELD_X, PLAYFIELD_Y)),
        ((5, 3), (PLAYFIELD_X + 5 * CELL_SIZE, PLAYFIELD_Y + 3 * CELL_SIZE)),
        ((19, 14), (PLAYFIELD_X + 19 * CELL_SIZE, PLAYFIELD_Y + 14 * CELL_SIZE)),
    ]
    for (gx, gy), (ex, ey) in cases:
        px, py = renderer._grid_to_pixel((gx, gy))  # type: ignore[attr-defined]
        assert (px, py) == (ex, ey), f"FR-06 grid({gx},{gy}) -> pixel({px},{py}) ≠ 期望({ex},{ey})"


# ---------- IT-15~21：构造/渲染鲁棒性 ----------

@pytest.mark.p0
def test_it_gui_renderer_1_15_construct_too_small_window_raises(fake_pg):
    """IT-gui-renderer-1-15 窗口过小 → RenderError。FR-06."""
    with pytest.raises(RenderError, match="小于最小可玩尺寸"):
        Renderer((100, 100))


@pytest.mark.p0
def test_it_gui_renderer_1_16_construct_invalid_color_raises(fake_pg):
    """IT-gui-renderer-1-16 skin 颜色越界 → RenderError。FR-06."""
    bad = Skin(
        name="bad",
        background=Color(300, 0, 0),  # r > 255
        grid_line=Color(30, 30, 40),
        snake_head=Color(120, 220, 120),
        snake_body=Color(60, 180, 90),
        food=Color(230, 80, 80),
        food_outline=Color(255, 240, 220),
        hud_text=Color(230, 230, 240),
        hud_accent=Color(255, 210, 90),
    )
    with pytest.raises(RenderError, match="越界"):
        Renderer((640, 480), skin=bad)


@pytest.mark.p1
def test_it_gui_renderer_1_17_construct_invalid_window_size_type_raises(fake_pg):
    """IT-gui-renderer-1-17 window_size 非 tuple → RenderError。FR-06."""
    with pytest.raises(RenderError):
        Renderer([640, 480])  # type: ignore[arg-type]


@pytest.mark.p1
def test_it_gui_renderer_1_18_construct_non_positive_grid_params_raise(fake_pg):
    """IT-gui-renderer-1-18 cell_size/grid_cols/grid_rows 非正整数 → RenderError。FR-06."""
    with pytest.raises(RenderError):
        Renderer((640, 480), cell_size=0)
    with pytest.raises(RenderError):
        Renderer((640, 480), grid_cols=-1)
    with pytest.raises(RenderError):
        Renderer((640, 480), grid_rows=0)


@pytest.mark.p1
def test_it_gui_renderer_1_19_render_without_init_raises(fake_pg):
    """IT-gui-renderer-1-19 render 前未 init：assertion error。FR-06."""
    r = Renderer((512, 472))  # 未 init
    snap = _make_snapshot()
    hud = _make_hud()
    with pytest.raises((AssertionError, AttributeError, RenderError)):
        r.render(snap, hud)


@pytest.mark.p0
def test_it_gui_renderer_1_20_render_none_snapshot_raises(renderer):
    """IT-gui-renderer-1-20 snapshot=None → RenderError。FR-06."""
    with pytest.raises(RenderError, match="snapshot 不能为 None"):
        renderer.render(None, _make_hud())  # type: ignore[arg-type]


@pytest.mark.p0
def test_it_gui_renderer_1_21_render_empty_snake_body_raises(renderer):
    """IT-gui-renderer-1-21 snake_body 为空 → RenderError。FR-06."""
    snap = _make_snapshot(snake=())  # 空蛇身
    with pytest.raises(RenderError, match="snake_body 不能为空"):
        renderer.render(snap, _make_hud())


# ---------- IT-22~28：接口契约/生命周期 ----------

@pytest.mark.p1
def test_it_gui_renderer_1_22_custom_skin_injected(fake_pg):
    """IT-gui-renderer-1-22 自定义 skin 注入生效。FR-06."""
    custom = Skin(
        name="custom",
        background=Color(255, 0, 0),
        grid_line=Color(0, 0, 0),
        snake_head=Color(0, 255, 0),
        snake_body=Color(0, 200, 0),
        food=Color(0, 0, 255),
        food_outline=Color(255, 255, 255),
        hud_text=Color(255, 255, 255),
        hud_accent=Color(255, 255, 0),
    )
    r = Renderer((640, 480), skin=custom)
    assert r.skin is custom, "FR-06 自定义 skin 注入"


@pytest.mark.p1
def test_it_gui_renderer_1_23_default_skin_is_default(fake_pg):
    """IT-gui-renderer-1-23 默认 skin = DEFAULT_SKIN。FR-06."""
    r = Renderer((640, 480))
    assert r.skin is DEFAULT_SKIN, "FR-06 默认 skin = DEFAULT_SKIN"


@pytest.mark.p0
def test_it_gui_renderer_1_24_init_idempotent(fake_pg):
    """IT-gui-renderer-1-24 init 幂等。FR-06."""
    r = Renderer((512, 472))
    r.init()
    r.init()  # 第二次不应报错
    r.init()
    r.shutdown()


@pytest.mark.p0
def test_it_gui_renderer_1_25_shutdown_idempotent(fake_pg):
    """IT-gui-renderer-1-25 shutdown 幂等。FR-06."""
    r = Renderer((512, 472))
    r.init()
    r.shutdown()
    r.shutdown()  # 第二次不应报错
    r.shutdown()


@pytest.mark.p0
def test_it_gui_renderer_1_26_context_manager(fake_pg):
    """IT-gui-renderer-1-26 __enter__ 返回 self、__exit__ 调 shutdown。FR-06."""
    with Renderer((512, 472)) as r:
        assert isinstance(r, Renderer), "FR-06 __enter__ 返回 Renderer"
        # 期间可正常 render
        r.render(_make_snapshot(), _make_hud())
    # 退出后已 shutdown（幂等再 shutdown 不报错）
    r.shutdown()


@pytest.mark.p1
def test_it_gui_renderer_1_27_context_manager_exception_safe(fake_pg):
    """IT-gui-renderer-1-27 __exit__ 即使 render 抛异常也调 shutdown。FR-06."""
    r = Renderer((512, 472))
    try:
        with r:
            # 故意让 render 抛错
            r.render(None, _make_hud())  # type: ignore[arg-type]
    except RenderError:
        pass
    # 即使异常，__exit__ 应已调 shutdown；再 shutdown 幂等
    r.shutdown()


@pytest.mark.p1
def test_it_gui_renderer_1_28_dataclasses_frozen():
    """IT-gui-renderer-1-28 HudData/Skin/Color 不可变（frozen=True）。FR-06."""
    from dataclasses import FrozenInstanceError
    c = Color(1, 2, 3)
    with pytest.raises(FrozenInstanceError):
        c.r = 99  # type: ignore[misc]

    hud = HudData(score=1, high_score=2, length=3, difficulty_label="EASY", status_label="RUN")
    with pytest.raises(FrozenInstanceError):
        hud.score = 99  # type: ignore[misc]

    sk = Skin(name="t", background=Color(0, 0, 0), grid_line=Color(0, 0, 0),
              snake_head=Color(0, 0, 0), snake_body=Color(0, 0, 0),
              food=Color(0, 0, 0), food_outline=Color(0, 0, 0),
              hud_text=Color(0, 0, 0), hud_accent=Color(0, 0, 0))
    with pytest.raises(FrozenInstanceError):
        sk.name = "x"  # type: ignore[misc]


# ---------- IT-29~31：静态检查 + 跨模块契约 ----------

@pytest.mark.p0
def test_it_gui_renderer_1_29_no_network_imports():
    """IT-gui-renderer-1-29 renderer 不导入 socket/urllib/http/requests。NFR-06."""
    forbidden = {"socket", "urllib", "http", "requests", "httpx", "aiohttp"}
    root = _GUI_CODE / "gui_renderer"
    offenders = []
    for py in root.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in forbidden:
                        offenders.append((py.name, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in forbidden:
                        offenders.append((py.name, node.module))
    assert not offenders, f"NFR-06 无网络：发现禁止导入 {offenders}"


@pytest.mark.p0
def test_it_gui_renderer_1_30_no_game_core_imports():
    """IT-gui-renderer-1-30 renderer 不导入 game_core（NFR-05 职责分离）。"""
    root = _GUI_CODE / "gui_renderer"
    offenders = []
    for py in root.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top == "game_core":
                        offenders.append((py.name, alias.name))
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if mod == "game_core":
                    offenders.append((py.name, node.module))
    assert not offenders, f"NFR-05 职责分离：renderer 不应 import game_core，发现 {offenders}"


@pytest.mark.p0
def test_it_gui_renderer_1_31_real_snapshot_contract(default_window_renderer):
    """IT-gui-renderer-1-31 跨模块契约：真实 Snapshot 入参正常 render。FR-06."""
    # 真实 Snapshot（含 game_core 类型）
    snap = Snapshot(
        snake_body=(Point(10, 7), Point(9, 7), Point(8, 7)),
        food=Point(15, 7),
        score=0,
        length=3,
        status=GameStatus.RUN,
        difficulty=Difficulty.MEDIUM,
        tick_ms=160,
    )
    hud = HudData(score=0, high_score=128, length=3,
                  difficulty_label="MEDIUM", status_label="RUN")

    # 不应抛 TypeError / AttributeError
    default_window_renderer.render(snap, hud)

    # 跨模块字段读取正确
    font = default_window_renderer._font  # type: ignore[attr-defined]
    texts = " | ".join(call[0] for call in font.render_calls)
    assert "MEDIUM" in texts, "FR-06 真实 Snapshot 的 difficulty.name = MEDIUM"
    assert "RUN" in texts, "FR-06 真实 Snapshot 的 status.name = RUN"
