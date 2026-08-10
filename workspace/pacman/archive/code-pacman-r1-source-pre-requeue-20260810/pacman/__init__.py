"""pacman 包：Linux 终端版吃豆人游戏（人机对战，差异化 AI）。

模块清单（与开发方案 §3.1/§3.2 模块划分对应）：
  - config:    默认值/CLI 配置/难度公式常量
  - map:       地图加载/校验/查询；FR-03 三项离线判定
  - entities:  Player/Ghost/Mover 速度累积器
  - ghost_ai:  四幽灵差异化 AI（target_cell + choose_dir + 模式状态机）
  - game:      对局状态机（吃豆/能量豆/碰撞/过关/扣命/结算）
  - input:     键位映射（WASD/方向键/P/q）
  - renderer:  curses 渲染层（HUD/地图/颜色/闪烁/结算）
  - main:      入口（argparse + wrapper + 主循环）

依赖方向（单向）：main → config/map/game/input/renderer；game → entities → ghost_ai；
game/map/entities/ghost_ai 不 import curses（纯逻辑层，可无终端单测）。
"""

__version__ = "0.1.0"
