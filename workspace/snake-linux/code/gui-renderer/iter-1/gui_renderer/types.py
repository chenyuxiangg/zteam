"""types 模块：渲染侧不可变值对象与派生属性。

FR-06 图形渲染所需的最小值对象集。设计原则：renderer 不复用 game-core 的 Point/Direction，
避免渲染层对游戏层坐标语义产生隐式耦合（见设计 §1.1）。
"""
from collections import deque
from dataclasses import dataclass, field
from typing import Deque


@dataclass(frozen=True)
class Color:
    """RGB 颜色三元组；r/g/b ∈ [0, 255]。"""

    r: int
    g: int
    b: int


@dataclass(frozen=True)
class Rect:
    """屏幕像素矩形；用于 HUD 区域与绘制原语。"""

    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Skin:
    """皮肤数据结构（迭代 1 仅内置 DEFAULT_SKIN；迭代 3 接入 SkinRegistry）。

    所有 Color 字段必须 r/g/b ∈ [0, 255]（由 Renderer.__init__ 在构造时校验）。
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


__all__ = ["Color", "Rect", "Skin", "HudData", "FpsMetric"]