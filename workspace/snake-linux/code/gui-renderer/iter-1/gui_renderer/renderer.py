"""renderer 模块：Renderer 类实现（pygame 适配层 + 绘制流程 + 帧率采样）。

设计要点：
- 构造期不调 pygame.init() / set_mode() —— 让 Renderer(...) 在 import 时无副作用（设计 §4.3）
- 所有 pygame 调用走模块顶层 import —— UT 用 monkeypatch 替换为 fake_pygame（设计 §4.2）
- render 末尾采样 fps；samples 容量 = FPS_SAMPLES_CAPACITY（设计 §4.7）
- 不引入 socket/urllib/http/requests（NFR-06）
"""
from typing import Optional, Tuple

import pygame  # noqa: F401  # 由 UT 替换为 fake_pygame

from .constants import (
    CELL_SIZE,
    DEFAULT_SKIN,
    FPS_SAMPLES_CAPACITY,
    GRID_COLS,
    GRID_ROWS,
    HUD_FIRST_LINE_Y,
    HUD_FONT_NAME,
    HUD_FONT_SIZE,
    HUD_HEIGHT,
    HUD_LINE_HEIGHT,
    HUD_SECOND_LINE_Y,
    PLAYFIELD_X,
    PLAYFIELD_Y,
)
from .errors import RenderError, SkinNotFoundError
from .types import FpsMetric, HudData, Skin


def _validate_skin(skin: Skin) -> None:
    """校验皮肤所有 Color 字段 r/g/b ∈ [0, 255]。"""
    for name, color in (
        ("background", skin.background),
        ("grid_line", skin.grid_line),
        ("snake_head", skin.snake_head),
        ("snake_body", skin.snake_body),
        ("food", skin.food),
        ("food_outline", skin.food_outline),
        ("hud_text", skin.hud_text),
        ("hud_accent", skin.hud_accent),
    ):
        for ch in ("r", "g", "b"):
            v = getattr(color, ch)
            if v < 0 or v > 255:
                raise RenderError(
                    f"皮肤 {skin.name} 的 {name}.{ch} = {v} 越界 [0, 255]"
                )


def _min_window_size(grid_cols: int, grid_rows: int, cell_size: int) -> Tuple[int, int]:
    """最小可玩窗口尺寸（含 HUD 与四边边距）。

    宽 = GRID_COLS * CELL_SIZE + 2 * PLAYFIELD_X
    高 = PLAYFIELD_Y + GRID_ROWS * CELL_SIZE + PLAYFIELD_X
        （PLAYFIELD_Y = HUD_HEIGHT + PLAYFIELD_Y_OFFSET；下边距 = PLAYFIELD_X 对齐）
    """
    min_w = grid_cols * cell_size + 2 * PLAYFIELD_X
    min_h = PLAYFIELD_Y + grid_rows * cell_size + PLAYFIELD_X
    return (min_w, min_h)


class Renderer:
    """主控类：一帧绘制 + 帧率统计 + 生命周期管理。

    使用模式：
        with Renderer((640, 480)) as r:
            while running:
                snap = state.snapshot()
                hud = HudData(...)
                r.render(snap, hud)
                metric = r.fps_metric()
                pygame.display.flip()
    """

    def __init__(
        self,
        window_size: Tuple[int, int],
        *,
        skin: Optional[Skin] = None,
        vsync: bool = True,
        cell_size: int = CELL_SIZE,
        grid_cols: int = GRID_COLS,
        grid_rows: int = GRID_ROWS,
    ) -> None:
        """构造期不调 pygame.init() / set_mode()（设计 §4.3）。

        校验：
        - window_size >= 最小可玩尺寸（GRID_COLS * CELL_SIZE + 2 * PLAYFIELD_X 等）
        - skin 颜色 RGB ∈ [0, 255]
        """
        # ---- 校验参数 ----
        if not isinstance(window_size, tuple) or len(window_size) != 2:
            raise RenderError(f"window_size 应为 (w, h) 二元组，收到 {window_size!r}")
        if not isinstance(cell_size, int) or cell_size <= 0:
            raise RenderError(f"cell_size 应为正整数，收到 {cell_size!r}")
        if not isinstance(grid_cols, int) or grid_cols <= 0:
            raise RenderError(f"grid_cols 应为正整数，收到 {grid_cols!r}")
        if not isinstance(grid_rows, int) or grid_rows <= 0:
            raise RenderError(f"grid_rows 应为正整数，收到 {grid_rows!r}")

        # 校验最小可玩尺寸
        min_w, min_h = _min_window_size(grid_cols, grid_rows, cell_size)
        w, h = window_size
        if w < min_w or h < min_h:
            raise RenderError(
                f"窗口尺寸 {window_size} 小于最小可玩尺寸 {(min_w, min_h)}"
            )

        # ---- 校验皮肤 ----
        self._skin = skin if skin is not None else DEFAULT_SKIN
        _validate_skin(self._skin)

        # ---- 记录参数 ----
        self._window_size: Tuple[int, int] = window_size
        self._vsync = vsync
        self._cell_size = cell_size
        self._grid_cols = grid_cols
        self._grid_rows = grid_rows
        self._initialized = False
        self._screen = None
        self._font = None
        self._fps = FpsMetric()
        # 确保 deque 容量 = FPS_SAMPLES_CAPACITY（覆盖默认 120）
        from collections import deque
        self._fps.samples = deque(maxlen=FPS_SAMPLES_CAPACITY)

    # ---- 公开属性 ----

    @property
    def skin(self) -> Skin:
        return self._skin

    @property
    def cell_size(self) -> int:
        return self._cell_size

    @property
    def grid_cols(self) -> int:
        return self._grid_cols

    @property
    def grid_rows(self) -> int:
        return self._grid_rows

    # ---- 生命周期（设计 §3.1） ----

    def init(self) -> None:
        """pygame.init() + pygame.display.set_mode(...) + pygame.font.init() + 时钟；幂等。"""
        if self._initialized:
            return
        pygame.init()
        pygame.font.init()
        flags = 0
        # pygame.SCALED 在迭代 1 不引入（依赖环境；迭代 3 HiDPI 再启用）
        self._screen = pygame.display.set_mode(self._window_size, flags)
        self._font = pygame.font.SysFont(HUD_FONT_NAME, HUD_FONT_SIZE)
        self._initialized = True

    def shutdown(self) -> None:
        """pygame.display.quit() + pygame.font.quit() + pygame.quit()；幂等。"""
        pygame.display.quit()
        pygame.font.quit()
        pygame.quit()
        self._initialized = False

    def __enter__(self) -> "Renderer":
        self.init()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown()

    # ---- 绘制（设计 §4.4） ----

    def render(self, snapshot, hud: HudData) -> None:
        """一帧绘制（设计 §4.4）。

        1. t0 = pygame.time.get_ticks()
        2. screen.fill(background)
        3. 绘制蛇身（body[0] 用 snake_head；body[1:] 用 snake_body）
        4. 绘制食物（填充 + 1px outline）
        5. 绘制 HUD（5 行文本）
        6. 采样 fps（t1 - t0）
        """
        if snapshot is None:
            raise RenderError("snapshot 不能为 None")
        if not snapshot.snake_body:
            raise RenderError("snapshot.snake_body 不能为空")

        screen = self._screen
        assert screen is not None, "render 前必须先 init() 或 __enter__"

        t0 = pygame.time.get_ticks()

        # 1. 背景填充
        screen.fill(self._skin.background)

        # 2. 蛇身（蛇头 body[0] 用 snake_head；蛇身 body[1:] 用 snake_body；-1 像素间隙）
        cell = self._cell_size - 1
        for i, point in enumerate(snapshot.snake_body):
            px, py = self._grid_to_pixel((point.x, point.y))
            color = self._skin.snake_head if i == 0 else self._skin.snake_body
            pygame.draw.rect(screen, color, (px, py, cell, cell))

        # 3. 食物（填充 + 1 像素 outline）
        fpx, fpy = self._grid_to_pixel((snapshot.food.x, snapshot.food.y))
        pygame.draw.rect(screen, self._skin.food, (fpx, fpy, cell, cell))
        pygame.draw.rect(screen, self._skin.food_outline, (fpx, fpy, cell, cell), width=1)

        # 4. HUD
        self._draw_hud(hud)

        # 5. 帧率采样
        t1 = pygame.time.get_ticks()
        self._fps.samples.append(float(t1 - t0))

    def _draw_hud(self, hud: HudData) -> None:
        """绘制 5 行 HUD（设计 §4.6）：score / high_score / length / difficulty / status。

        布局：
          第 1 行（y=HUD_FIRST_LINE_Y）：Score: x   High: y   Length: z
          第 2 行（y=HUD_SECOND_LINE_Y）：Difficulty: ...   Status: ...
        颜色：主文本 = hud_text；High Score / Status 强调 = hud_accent（设计 §4.6）
        OVER 状态时 Status 文字用 hud_accent。
        """
        assert self._font is not None, "HUD 绘制需要 init() 完成"

        # 第 1 行：Score / High Score / Length
        line1_score = self._font.render(f"Score: {hud.score}", True, self._skin.hud_text)
        line1_high = self._font.render(f"High: {hud.high_score}", True, self._skin.hud_accent)
        line1_length = self._font.render(f"Length: {hud.length}", True, self._skin.hud_text)
        self._screen.blit(line1_score, (16, HUD_FIRST_LINE_Y))
        self._screen.blit(line1_high, (200, HUD_FIRST_LINE_Y))
        self._screen.blit(line1_length, (400, HUD_FIRST_LINE_Y))

        # 第 2 行：Difficulty / Status
        line2_diff = self._font.render(
            f"Difficulty: {hud.difficulty_label}", True, self._skin.hud_text
        )
        # OVER 时状态文字用 accent 高亮
        status_color = (
            self._skin.hud_accent if hud.status_label.upper() == "OVER" else self._skin.hud_text
        )
        line2_status = self._font.render(
            f"Status: {hud.status_label}", True, status_color
        )
        self._screen.blit(line2_diff, (16, HUD_SECOND_LINE_Y))
        self._screen.blit(line2_status, (300, HUD_SECOND_LINE_Y))

    def _grid_to_pixel(self, cell: Tuple[int, int]) -> Tuple[int, int]:
        """网格坐标 → 像素坐标（设计 §4.5）。

        调用方传入 (x, y) tuple 而非 Point，避免 renderer 显式 import game_core.types。
        """
        x, y = cell
        return (PLAYFIELD_X + x * self._cell_size, PLAYFIELD_Y + y * self._cell_size)

    # ---- 帧率（设计 §3.1 / §4.7） ----

    def fps_metric(self) -> FpsMetric:
        """返回最近 120 帧渲染耗时的 P95 与平均 FPS（设计 §4.7）。"""
        return self._fps


__all__ = ["Renderer", "RenderError", "SkinNotFoundError"]