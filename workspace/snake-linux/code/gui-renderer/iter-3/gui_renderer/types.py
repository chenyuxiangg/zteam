"""types 模块：渲染侧不可变值对象与派生属性。

FR-06 图形渲染所需的最小值对象集。设计原则：renderer 不复用 game-core 的 Point/Direction，
避免渲染层对游戏层坐标语义产生隐式耦合（见设计 §1.1）。

迭代 3 增量（设计 §1.2 + §1.5）：
  - Skin 新增 3 字段（cell_gap / food_pattern / snake_pattern）—— 全默认值，迭代 1 字面量构造兼容
  - **修订 P2-1**：原 r3 hud_shadow 字段已删除（无消费点）
  - 新增 InterpolationState frozen dataclass
  - **修订 P2-2**：InterpolatedCell 已删除（无消费点，UT/实现均不引用）
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Tuple


@dataclass(frozen=True)
class Color:
    """RGB 颜色三元组；r/g/b ∈ [0, 255]。"""

    r: int
    g: int
    b: int


@dataclass(frozen=True)
class Rect:
    """屏幕像素矩形；迭代 1 公共类型，迭代 3 无新增消费点（设计 §1.4 修订 P2-2）。"""

    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Skin:
    """皮肤数据结构（迭代 1 仅内置 DEFAULT_SKIN；迭代 3 接入 SkinRegistry，3 套皮肤）。

    所有 Color 字段必须 r/g/b ∈ [0, 255]（由 Renderer.__init__ 在构造时校验）。
    迭代 3 新增字段（cell_gap / food_pattern / snake_pattern）全部带默认值 → 迭代 1
    DEFAULT_SKIN 字面量构造继续合法。
    """

    name: str
    background: Color
    grid_line: Color
    snake_head: Color
    snake_body: Color
    food: Color
    food_outline: Color
    hud_text: Color
    hud_accent: Color
    # ---- 迭代 3 新增（默认值兼容迭代 1；修订 P2-1：hud_shadow 已删除）----
    cell_gap: int = 1
    food_pattern: str = "solid"
    snake_pattern: str = "solid"


@dataclass(frozen=True)
class HudData:
    """HUD 渲染输入（由 game-app 主循环构造并注入）。"""

    score: int
    high_score: int
    length: int
    difficulty_label: str
    status_label: str


@dataclass
class FpsMetric:
    """帧率统计：滚动窗口采样最近 120 帧渲染耗时（毫秒）。

    p95_frame_ms / fps 是派生属性，按需计算。
    """

    samples: Deque[float] = field(default_factory=lambda: deque(maxlen=120))

    @property
    def p95_frame_ms(self) -> float:
        if not self.samples:
            return 0.0
        import statistics

        if len(self.samples) < 20:
            # 样本不足 → 降级为 mean（避免 quantiles 抛错）
            return sum(self.samples) / len(self.samples)
        return statistics.quantiles(self.samples, n=20)[-1]

    @property
    def fps(self) -> float:
        if not self.samples:
            return 0.0
        mean = sum(self.samples) / len(self.samples)
        if mean <= 0:
            return 0.0
        return 1000.0 / mean


@dataclass(frozen=True)
class InterpolationState:
    """一次 render 的插值上下文（FO 从主循环传入；renderer 只读）。

    设计 §1.5（修订 P2-1 / P2-2）：
      - prev_snake_body / prev_food 表示**上一节拍**（即 game-core step 推进前）的快照
        蛇身与食物网格坐标。
      - prev_food=None 语义：吃食节拍 → 食物不应插值（renderer 瞬移渲染 snap.food）。
      - 距离 >1 格（设计 §2.2 + §4.4 兜底）：renderer 内部 _grid_distance 检测后自动跳过。
    """

    alpha: float
    prev_snake_body: Tuple[Tuple[int, int], ...]
    prev_food: Optional[Tuple[int, int]] = None


__all__ = [
    "Color",
    "Rect",
    "Skin",
    "HudData",
    "FpsMetric",
    "InterpolationState",
]
