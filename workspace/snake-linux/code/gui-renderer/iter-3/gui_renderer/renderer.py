"""renderer 模块：Renderer 类实现（pygame 适配层 + 绘制流程 + 帧率采样）。

设计要点：
- 构造期不调 pygame.init() / set_mode() —— 让 Renderer(...) 在 import 时无副作用（设计 §4.3）
- 所有 pygame 调用走模块顶层 import —— UT 用 monkeypatch 替换为 fake_pygame（设计 §4.2）
- render 末尾采样 fps；samples 容量 = FPS_SAMPLES_CAPACITY（设计 §4.7）
- 不引入 socket/urllib/http/requests（NFR-06）

迭代 3 增量（设计 §3.1 / §4.4 / §4.5 / §4.6 / §4.7 / 修订 P1-1 三方案 + P2-1 + P2-2 + P3-1 + P3-2）：
  - enable_high_dpi 参数（默认 True，pygame.SCALED）
  - render(..., *, interp=None) 平滑插值
  - set_skin / handle_resize / skin_names / current_skin_name
  - _draw_food 按 food_pattern 分发
  - _draw_hud 同色描边（单次 render + 偏移 blit + 主版 blit，font.render 仍 5 次）
  - render 未 init 抛 RenderError（替代迭代 1 assert）
  - SkinNotFoundError 触发路径：构造签名 (name, available)
"""
from typing import Optional, Tuple

import pygame  # noqa: F401  # 由 UT 替换为 fake_pygame

from .constants import (
    CELL_SIZE,
    CELL_SIZE_MIN,
    DEFAULT_SKIN,
    FPS_SAMPLES_CAPACITY,
    GRID_COLS,
    GRID_ROWS,
    HUD_FIRST_LINE_Y,
    HUD_FONT_NAME,
    HUD_FONT_SIZE,
    HUD_SECOND_LINE_Y,
    MIN_PLAYABLE_H,
    MIN_PLAYABLE_W,
    PLAYFIELD_X,
    PLAYFIELD_Y,
    SKIN_REGISTRY,
)
from .errors import RenderError, SkinNotFoundError
from .types import Color, FpsMetric, HudData, InterpolationState, Skin


# ---- 工具函数（设计 §4.4 修订 P2-1）----

def _pygame_color(c) -> Tuple[int, int, int]:
    """把 gui_renderer.Color dataclass 转 pygame 接受的 tuple (r, g, b)。

    修复 MTO-4-01：pygame Surface.fill()/draw 系列/font.render 仅接受
    tuple/str/pygame.Color，不接受自定义 Color dataclass（真实集成首帧
    TypeError）。已传 tuple/str/pygame.Color 时原样返回（幂等兼容）。
    """
    if isinstance(c, Color):
        return (c.r, c.g, c.b)
    return c

def _interpolate_position(
    prev: Tuple[int, int], current: Tuple[int, int], alpha: float
) -> Tuple[float, float]:
    """线性插值：prev + alpha * (current - prev)。alpha=0→prev；alpha=1→current。"""
    px = prev[0] + alpha * (current[0] - prev[0])
    py = prev[1] + alpha * (current[1] - prev[1])
    return (px, py)


def _grid_distance(a: Tuple[int, int], b: Tuple[int, int]) -> int:
    """网格距离（max(|dx|, |dy|)，Chebyshev）。仅蛇身/食物单格场景。"""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


# ---- 校验（迭代 3 增量：cell_gap / food_pattern / snake_pattern，修订 P2-1 删 hud_shadow）----

def _validate_skin(skin: Skin) -> None:
    """校验皮肤所有 Color 字段 r/g/b ∈ [0, 255] + 迭代 3 新增字段合法。"""
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
    # ---- 迭代 3 增量（修订 P2-1：hud_shadow 校验已删除）----
    if skin.cell_gap < 0 or skin.cell_gap > 10:
        raise RenderError(
            f"皮肤 {skin.name} 的 cell_gap = {skin.cell_gap} 越界 [0, 10]"
        )
    if skin.food_pattern not in ("solid", "ringed", "checkered"):
        raise RenderError(
            f"皮肤 {skin.name} 的 food_pattern = {skin.food_pattern!r} 非法"
        )
    if skin.snake_pattern not in ("solid", "striped"):
        raise RenderError(
            f"皮肤 {skin.name} 的 snake_pattern = {skin.snake_pattern!r} 非法"
        )


def _min_window_size(grid_cols: int, grid_rows: int, cell_size: int) -> Tuple[int, int]:
    """最小可玩窗口尺寸（含 HUD 与四边边距）。"""
    min_w = grid_cols * cell_size + 2 * PLAYFIELD_X
    min_h = PLAYFIELD_Y + grid_rows * cell_size + PLAYFIELD_X
    return (min_w, min_h)


# ---- 主类 ----

class Renderer:
    """主控类：一帧绘制 + 帧率统计 + 生命周期管理 + 皮肤切换 + 窗口缩放。

    使用模式：
        with Renderer((640, 480), enable_high_dpi=True) as r:
            while running:
                snap = state.snapshot()
                hud = HudData(...)
                r.render(snap, hud, interp=interp)  # interp=None 兼容迭代 1
                r.set_skin("dark")                  # 切皮肤
                r.handle_resize(1024, 768)          # 缩放
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
        enable_high_dpi: bool = True,  # 迭代 3 增量（设计 §4.7）
    ) -> None:
        """构造期不调 pygame.init() / set_mode()（设计 §4.3）。

        校验：
        - window_size >= 最小可玩尺寸（GRID_COLS * CELL_SIZE + 2 * PLAYFIELD_X 等）
        - skin 颜色 RGB ∈ [0, 255] + 迭代 3 新增字段合法
        - enable_high_dpi=True（默认；NFR-04 高分屏清晰）
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
        if not isinstance(enable_high_dpi, bool):
            raise RenderError(f"enable_high_dpi 应为 bool，收到 {enable_high_dpi!r}")

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
        self._enable_high_dpi = enable_high_dpi
        self._initialized = False
        self._screen = None
        self._font = None
        self._flags = 0
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

    @property
    def current_skin_name(self) -> str:
        """当前皮肤名（设计 §3.1，UI 显示用）。"""
        return self._skin.name

    def skin_names(self) -> Tuple[str, ...]:
        """返回注册表内皮肤名（UI 列出可选皮肤用）。"""
        return tuple(SKIN_REGISTRY.keys())

    # ---- 生命周期（设计 §3.1）----

    def init(self) -> None:
        """pygame.init() + pygame.display.set_mode(...) + pygame.font.init() + 时钟；幂等。

        修订 P1-1 方案③：enable_high_dpi=True 时
            flags |= getattr(pygame, "SCALED", 0)
        pygame 2.x: SCALED = 0x40000000；1.x 无 SCALED 属性时降级 flags=0。
        """
        if self._initialized:
            return
        pygame.init()
        pygame.font.init()
        flags = 0
        if self._enable_high_dpi:
            # 修订 P1-1 方案③：getattr 防御（pygame 1.x 降级为 flags=0）
            flags |= getattr(pygame, "SCALED", 0)
        self._flags = flags
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

    # ---- 切皮肤（设计 §3.1 + §4.5）----

    def set_skin(self, name: str) -> None:
        """切皮肤：SKIN_REGISTRY[name] → self._skin；不在 → SkinNotFoundError(name, available)。

        修订 P3-1：构造签名 (name, available) 携带可用列表供 game-app UI 提示。
        游戏中对局不中断：set_skin 只换 self._skin 引用；下一帧 render 即生效。
        """
        if name not in SKIN_REGISTRY:
            raise SkinNotFoundError(name=name, available=SKIN_REGISTRY.keys())
        new_skin = SKIN_REGISTRY[name]
        _validate_skin(new_skin)  # 防御：注册表内皮肤也校验一次
        self._skin = new_skin

    # ---- 窗口缩放（设计 §3.1 + §4.6，修订 P2-1）----

    def handle_resize(self, w: int, h: int) -> None:
        """窗口缩放：重算 cell_size + 字体 + set_mode（保留 SCALED 标志）。

        1. 校验 w/h 为正整数（类型）
        2. 校验 w >= MIN_PLAYABLE_W 且 h >= MIN_PLAYABLE_H（最小可玩尺寸）→ 否则 RenderError
        3. 重算 cell_size = min((w - 2*PLAYFIELD_X) / grid_cols,
                                (h - PLAYFIELD_Y - PLAYFIELD_X) / grid_rows)
           cell_size 下限 CELL_SIZE_MIN=8，上限不超过初始 cell_size 的 2 倍
        4. 字体按比例 font_size = HUD_FONT_SIZE * (new_cell_size / CELL_SIZE)
        5. pygame.display.set_mode((w, h), self._flags) 重建屏幕（保留 SCALED 标志）
        6. 更新 self._cell_size / self._window_size / self._font
        """
        if not self._initialized:
            raise RenderError("handle_resize 前必须 init()")
        # 1. 类型校验
        if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
            raise RenderError(f"handle_resize 尺寸应正整数，收到 {(w, h)}")

        # 2. 最小可玩尺寸校验（r2 P2-1 保留：与 §5.5 鲁棒性表 + §7.5 断言一致 → 抛 RenderError）
        if w < MIN_PLAYABLE_W or h < MIN_PLAYABLE_H:
            raise RenderError(
                f"handle_resize 尺寸 {(w, h)} 小于最小可玩尺寸 "
                f"({MIN_PLAYABLE_W} x {MIN_PLAYABLE_H})；"
                f"FR-09 要求小于最小尺寸时给出提示，由 game-app 捕获后向用户呈现"
            )

        # 3. 计算新 cell_size：保持 grid_cols/rows 不变，等比缩放
        avail_w = w - 2 * PLAYFIELD_X
        avail_h = h - PLAYFIELD_Y - PLAYFIELD_X
        new_cell_w = avail_w // self._grid_cols
        new_cell_h = avail_h // self._grid_rows
        new_cell = min(new_cell_w, new_cell_h)
        new_cell = max(CELL_SIZE_MIN, min(new_cell, CELL_SIZE * 2))
        # 上限 2*DEFAULT 防止窗口极大时网格过大溢出；下限 MIN 防止过小无法辨识

        # 4. 字体按 cell_size 比例缩放
        new_font_size = max(10, int(round(HUD_FONT_SIZE * new_cell / CELL_SIZE)))

        # 5. 重建屏幕（保留 SCALED 标志）
        self._screen = pygame.display.set_mode((w, h), self._flags)
        self._font = pygame.font.SysFont(HUD_FONT_NAME, new_font_size)

        # 6. 更新内部状态
        self._window_size = (w, h)
        self._cell_size = new_cell

    # ---- 绘制（设计 §4.4，迭代 3 修订 P1-1 + P2-1 + P3-2）----

    def render(
        self,
        snapshot,
        hud: HudData,
        *,
        interp: Optional[InterpolationState] = None,
    ) -> None:
        """一帧绘制。

        步骤（设计 §4.4）：
          1. 校验 init() / snapshot 非空 / snake_body 非空（修订 P3-2：未 init 抛 RenderError）
          2. t0 = pygame.time.get_ticks()
          3. screen.fill(background)
          4. 绘制蛇身（body[0] 用 snake_head；body[1:] 用 snake_body；间隙 = skin.cell_gap）
             - interp 非 None 且 alpha<1.0：按 prev_snake_body 与 current 间线性插值绘制
             - interp 为 None 或 alpha>=1.0：按当前快照绘制（瞬移，向后兼容）
          5. 绘制食物（按 skin.food_pattern 选择 solid/ringed/checkered 形态 + outline）
             - prev_food=None 或距离 >1 格（修订 P2-1 兜底）：按 snap.food 当前坐标（瞬移）
             - 否则：按 alpha 插值绘制
          6. 绘制 HUD（2 行 5 段；同色描边偏移 (+1,+1) blit，但 font.render 仍 5 次，修订 P1-1）
          7. 采样 fps（t1 - t0）
        """
        # 修订 P3-2：未 init 时抛 RenderError（替代迭代 1 assert；语义更明确）
        if self._screen is None:
            raise RenderError("render() 前必须 init()；未 init 时屏幕对象不存在")
        if snapshot is None:
            raise RenderError("snapshot 不能为 None")
        if not snapshot.snake_body:
            raise RenderError("snapshot.snake_body 不能为空")

        screen = self._screen
        t0 = pygame.time.get_ticks()

        # 1. 背景填充（MTO-4-01：Color dataclass → tuple）
        screen.fill(_pygame_color(self._skin.background))

        # 2. 插值上下文（默认 alpha=1.0 = 无插值）
        alpha = 1.0
        prev_body = None
        prev_food = None
        if interp is not None:
            alpha = max(0.0, min(1.0, interp.alpha))  # clip 越界
            prev_body = interp.prev_snake_body
            prev_food = interp.prev_food  # 可能为 None（修订 P2-1）

        # 3. 蛇身绘制（间隙 = cell_gap；亚像素截断）
        cell_draw = self._cell_size - self._skin.cell_gap
        for i, point in enumerate(snapshot.snake_body):
            cur = (point.x, point.y)
            if prev_body is not None and i < len(prev_body):
                cur = _interpolate_position(prev_body[i], cur, alpha)  # 浮点亚像素
            px, py = self._grid_to_pixel(cur)
            px_i, py_i = int(round(px)), int(round(py))
            color = self._skin.snake_head if i == 0 else self._skin.snake_body
            pygame.draw.rect(screen, _pygame_color(color), (px_i, py_i, cell_draw, cell_draw))

        # 4. 食物绘制（修订 P2-1：prev_food=None 或距离 >1 格 → 跳过插值）
        food_cur = (snapshot.food.x, snapshot.food.y)
        if prev_food is not None and _grid_distance(prev_food, food_cur) <= 1:
            food_cur = _interpolate_position(prev_food, food_cur, alpha)
        fpx, fpy = self._grid_to_pixel(food_cur)
        fpx_i, fpy_i = int(round(fpx)), int(round(fpy))
        self._draw_food(screen, fpx_i, fpy_i, cell_draw)

        # 5. HUD（同色描边：font.render 仍 5 次；blit 10 次；修订 P1-1 + P2-1）
        self._draw_hud(hud)

        # 6. 帧率采样
        t1 = pygame.time.get_ticks()
        self._fps.samples.append(float(t1 - t0))

    def _draw_food(self, screen, x: int, y: int, size: int) -> None:
        """按 skin.food_pattern 分发（设计 §4.4）：
            - solid：填充 + outline(width=1)            → 2 次 draw.rect
            - ringed：实心 + 内空 + 外圈双线(width=2)   → 3 次 draw.rect
            - checkered：4 子格(2+2) + outline(width=1)  → 5 次 draw.rect
        """
        pattern = self._skin.food_pattern
        if pattern == "solid":
            pygame.draw.rect(screen, _pygame_color(self._skin.food), (x, y, size, size))
            pygame.draw.rect(
                screen, _pygame_color(self._skin.food_outline), (x, y, size, size), width=1
            )
        elif pattern == "ringed":
            # 内部实心 + 镂空 + 外圈双线
            pygame.draw.rect(screen, _pygame_color(self._skin.food), (x, y, size, size))
            inner = size // 4
            pygame.draw.rect(
                screen,
                _pygame_color(self._skin.background),
                (x + inner, y + inner, size - 2 * inner, size - 2 * inner),
            )
            pygame.draw.rect(
                screen, _pygame_color(self._skin.food_outline), (x, y, size, size), width=2
            )
        elif pattern == "checkered":
            # 4 子格：左上+右下 food 色；右上+左下 outline 色；外加 1 outline
            half = size // 2
            pygame.draw.rect(screen, _pygame_color(self._skin.food), (x, y, half, half))
            pygame.draw.rect(
                screen, _pygame_color(self._skin.food_outline), (x + half, y, half, half)
            )
            pygame.draw.rect(
                screen, _pygame_color(self._skin.food_outline), (x, y + half, half, half)
            )
            pygame.draw.rect(
                screen, _pygame_color(self._skin.food), (x + half, y + half, half, half)
            )
            pygame.draw.rect(
                screen, _pygame_color(self._skin.food_outline), (x, y, size, size), width=1
            )
        else:
            # 防御：_validate_skin 已校验，但 fallback 仍画 solid
            pygame.draw.rect(screen, _pygame_color(self._skin.food), (x, y, size, size))
            pygame.draw.rect(
                screen, _pygame_color(self._skin.food_outline), (x, y, size, size), width=1
            )

    def _draw_hud(self, hud: HudData) -> None:
        """绘制 2 行 5 段 HUD（设计 §4.4 修订 P1-1 + P2-1）：
          第 1 行（y=HUD_FIRST_LINE_Y）：Score / High / Length
          第 2 行（y=HUD_SECOND_LINE_Y）：Difficulty / Status
          同色描边：每段单次 font.render（保持 5 次），同色 surface 被 blit 至
                    (x+1, y+1) 偏移位置 + (x, y) 主版位置 → 总 10 次 blit
        """
        assert self._font is not None, "HUD 绘制需要 init() 完成"

        # 偏移常量（设计 §4.4 修订 P1-1）
        SHADOW_OFFSET = 1

        # ---- 第 1 行：Score / High / Length ----
        line1_score = self._font.render(
            f"Score: {hud.score}", True, _pygame_color(self._skin.hud_text)
        )
        line1_high = self._font.render(
            f"High: {hud.high_score}", True, _pygame_color(self._skin.hud_accent)
        )
        line1_length = self._font.render(
            f"Length: {hud.length}", True, _pygame_color(self._skin.hud_text)
        )
        # Score：偏移 + 主版
        self._screen.blit(line1_score, (16 + SHADOW_OFFSET, HUD_FIRST_LINE_Y + SHADOW_OFFSET))
        self._screen.blit(line1_score, (16, HUD_FIRST_LINE_Y))
        # High：偏移 + 主版
        self._screen.blit(line1_high, (200 + SHADOW_OFFSET, HUD_FIRST_LINE_Y + SHADOW_OFFSET))
        self._screen.blit(line1_high, (200, HUD_FIRST_LINE_Y))
        # Length：偏移 + 主版
        self._screen.blit(line1_length, (400 + SHADOW_OFFSET, HUD_FIRST_LINE_Y + SHADOW_OFFSET))
        self._screen.blit(line1_length, (400, HUD_FIRST_LINE_Y))

        # ---- 第 2 行：Difficulty / Status ----
        line2_diff = self._font.render(
            f"Difficulty: {hud.difficulty_label}", True, _pygame_color(self._skin.hud_text)
        )
        # OVER 时状态文字用 accent 高亮（修订 P1-1 显式要求保留：与迭代 1 既有断言一致）
        status_color = (
            self._skin.hud_accent
            if hud.status_label.upper() == "OVER"
            else self._skin.hud_text
        )
        line2_status = self._font.render(
            f"Status: {hud.status_label}", True, _pygame_color(status_color)
        )
        # Difficulty：偏移 + 主版
        self._screen.blit(line2_diff, (16 + SHADOW_OFFSET, HUD_SECOND_LINE_Y + SHADOW_OFFSET))
        self._screen.blit(line2_diff, (16, HUD_SECOND_LINE_Y))
        # Status：偏移 + 主版
        self._screen.blit(line2_status, (300 + SHADOW_OFFSET, HUD_SECOND_LINE_Y + SHADOW_OFFSET))
        self._screen.blit(line2_status, (300, HUD_SECOND_LINE_Y))

    def _grid_to_pixel(self, cell) -> Tuple[float, float]:
        """网格坐标 → 像素坐标（设计 §4.5，修订 P3-2 注解放宽）。

        插值分支传入 _interpolate_position 返回的浮点坐标 → 返回类型放宽为 float；
        调用方用 int(round(...)) 截断。
        """
        x, y = cell
        return (PLAYFIELD_X + x * self._cell_size, PLAYFIELD_Y + y * self._cell_size)

    # ---- 帧率（设计 §3.1 / §4.7）----

    def fps_metric(self) -> FpsMetric:
        """返回最近 120 帧渲染耗时的 P95 与平均 FPS（设计 §4.7）。"""
        return self._fps


__all__ = [
    "Renderer",
    "RenderError",
    "SkinNotFoundError",
    # 工具函数也对外暴露（test_interpolation 会用；虽 §7.6 没单列文件但 import 路径已就位）
    "_interpolate_position",
    "_grid_distance",
]
