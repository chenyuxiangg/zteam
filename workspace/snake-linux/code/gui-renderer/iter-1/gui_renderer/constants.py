"""constants 模块：默认皮肤与布局常量。

迭代 1 内置经典皮肤；布局固定尺寸，不做缩放（迭代 3 接入 handle_resize）。
"""
from .types import Color, Skin

# ---- 布局常量（迭代 1 固定尺寸）----
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

# ---- 帧率采样 ----
FPS_SAMPLES_CAPACITY = 120  # deque maxlen（约 2 秒 @ 60FPS）

# ---- HUD 布局 ----
HUD_LINE_HEIGHT = 28  # HUD 行高（像素）
HUD_FIRST_LINE_Y = 12  # HUD 第一行 y
HUD_SECOND_LINE_Y = 44  # HUD 第二行 y

# ---- 字体 ----
HUD_FONT_NAME = "Arial"  # pygame.font.SysFont 首选字体；失败回退 SDL 默认字体
HUD_FONT_SIZE = 22

# ---- 经典皮肤（DEFAULT_SKIN）----
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
)


__all__ = [
    "WINDOW_WIDTH",
    "WINDOW_HEIGHT",
    "HUD_HEIGHT",
    "PLAYFIELD_X",
    "PLAYFIELD_Y",
    "CELL_SIZE",
    "GRID_COLS",
    "GRID_ROWS",
    "FPS_SAMPLES_CAPACITY",
    "HUD_LINE_HEIGHT",
    "HUD_FIRST_LINE_Y",
    "HUD_SECOND_LINE_Y",
    "HUD_FONT_NAME",
    "HUD_FONT_SIZE",
    "DEFAULT_SKIN",
]