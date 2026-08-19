"""constants 模块：默认皮肤与布局常量。

迭代 1 内置经典皮肤；迭代 3 增量：深色 / 色盲友好 2 套新皮肤 + SKIN_REGISTRY +
CELL_SIZE_MIN / MIN_PLAYABLE_W/H 缩放常量。

设计 §1.3 / §4.3：所有 Color 字段走 `field(default_factory=lambda: Color(...))` 写法
（r2 P3-3 保留，修订 P2-1 同步：hud_shadow 字段已删除）。
"""
from typing import Dict

from .types import Color, Skin

# ---- 布局常量（迭代 1 既有）----
WINDOW_WIDTH = 640  # 窗口宽（像素）
WINDOW_HEIGHT = 480  # 窗口高（像素）
HUD_HEIGHT = 80  # 顶部 HUD 区域高
PLAYFIELD_X = 16  # 游戏区左上角 X 偏移（边距）
PLAYFIELD_Y = HUD_HEIGHT + 16  # 游戏区左上角 Y 偏移
CELL_SIZE = 24  # 单格像素（20×15 网格 → 480×360，刚好放下）
GRID_COLS = 20  # 与 game-core 默认一致
GRID_ROWS = 15

# 几何自洽校验（FO 实现时核对，FO 不允许破坏以下不变量）：
# WINDOW_WIDTH  = 16 + 20*24 + 16 = 512（FO 在 renderer 校验最小可玩尺寸时取 512）
# WINDOW_HEIGHT = 80 + 16 + 15*24 + 16 = 472

# ---- 迭代 3 增量：缩放常量（设计 §4.3）----
CELL_SIZE_MIN = 8  # 缩放下限（像素），防止网格过小无法辨识

# 最小可玩尺寸（r2 P2-1 保留：与 handle_resize 校验口径一致）
MIN_PLAYABLE_W = GRID_COLS * CELL_SIZE_MIN + 2 * PLAYFIELD_X
MIN_PLAYABLE_H = GRID_ROWS * CELL_SIZE_MIN + PLAYFIELD_Y + PLAYFIELD_X

# ---- 帧率采样 ----
FPS_SAMPLES_CAPACITY = 120  # deque maxlen（约 2 秒 @ 60FPS）

# ---- HUD 布局 ----
HUD_LINE_HEIGHT = 28  # HUD 行高（像素）
HUD_FIRST_LINE_Y = 12  # HUD 第一行 y
HUD_SECOND_LINE_Y = 44  # HUD 第二行 y

# ---- 字体 ----
HUD_FONT_NAME = "Arial"  # pygame.font.SysFont 首选字体；失败回退 SDL 默认字体
HUD_FONT_SIZE = 22

# ---- 经典皮肤（DEFAULT_SKIN，迭代 1 既有）----
DEFAULT_SKIN = Skin(
    name="classic",
    background=Color(18, 18, 24),  # 深灰蓝
    grid_line=Color(30, 30, 40),
    snake_head=Color(120, 220, 120),  # 鲜绿
    snake_body=Color(60, 180, 90),  # 稍深绿
    food=Color(230, 80, 80),  # 红
    food_outline=Color(255, 240, 220),
    hud_text=Color(230, 230, 240),
    hud_accent=Color(255, 210, 90),  # 金黄强调
    # 迭代 3 新增字段走默认值（cell_gap=1 / food_pattern="solid" / snake_pattern="solid"）
)

# ---- 迭代 3 增量：DARK_SKIN（设计 §4.3）----
DARK_SKIN = Skin(
    name="dark",
    background=Color(8, 8, 14),  # 极深蓝
    grid_line=Color(20, 20, 30),
    snake_head=Color(140, 255, 200),  # 亮绿
    snake_body=Color(80, 200, 140),  # 深绿
    food=Color(255, 160, 80),  # 暖橙
    food_outline=Color(255, 220, 180),
    hud_text=Color(240, 240, 250),
    hud_accent=Color(255, 230, 140),
    cell_gap=2,
    food_pattern="ringed",  # 食物描边强调（环形）
    snake_pattern="solid",
)

# ---- 迭代 3 增量：COLORBLIND_FRIENDLY_SKIN（设计 §4.3，修订 P2-1 删 hud_shadow）----
COLORBLIND_FRIENDLY_SKIN = Skin(
    name="colorblind_friendly",
    background=Color(245, 245, 240),  # 浅米黄（避免红绿混淆）
    grid_line=Color(200, 200, 190),
    snake_head=Color(20, 60, 160),  # 蓝色（蓝黄对比最强色盲友好）
    snake_body=Color(70, 110, 200),  # 稍浅蓝
    food=Color(240, 200, 40),  # 黄（避免红绿）
    food_outline=Color(40, 40, 40),
    hud_text=Color(30, 30, 30),
    hud_accent=Color(160, 80, 20),  # 棕橙强调
    cell_gap=1,
    food_pattern="checkered",  # 棋盘格辅助辨识
    snake_pattern="striped",  # 横条纹辅助辨识
)

# ---- 迭代 3 增量：SKIN_REGISTRY（设计 §1.3）----
SKIN_REGISTRY: Dict[str, Skin] = {
    "classic": DEFAULT_SKIN,
    "dark": DARK_SKIN,
    "colorblind_friendly": COLORBLIND_FRIENDLY_SKIN,
}


__all__ = [
    "WINDOW_WIDTH",
    "WINDOW_HEIGHT",
    "HUD_HEIGHT",
    "PLAYFIELD_X",
    "PLAYFIELD_Y",
    "CELL_SIZE",
    "CELL_SIZE_MIN",
    "GRID_COLS",
    "GRID_ROWS",
    "MIN_PLAYABLE_W",
    "MIN_PLAYABLE_H",
    "FPS_SAMPLES_CAPACITY",
    "HUD_LINE_HEIGHT",
    "HUD_FIRST_LINE_Y",
    "HUD_SECOND_LINE_Y",
    "HUD_FONT_NAME",
    "HUD_FONT_SIZE",
    "DEFAULT_SKIN",
    "DARK_SKIN",
    "COLORBLIND_FRIENDLY_SKIN",
    "SKIN_REGISTRY",
]
