"""curses 渲染层：地图/HUD/颜色/闪烁/结算/尺寸检查。

职责：curses 窗口布局；六类元素 + 四幽灵分色 + 能量豆脆弱闪烁；终端 <80×24 检查；
      GAME_OVER 结算画面。
依赖：pacman.config / pacman.map / pacman.game。
对应方案：plans/pacman-r1.md §3.2 renderer.py、§5.3 边界处理、§6 颜色降级。

注意：curses 模块顶层 import——失败时（无 _curses/非 TTY）让导入异常透出
给 main.py wrapper 兜底并报错退出（FR-16/NFR-04）。逻辑层模块（map/entities/
ghost_ai/game/input/config）不依赖 curses，可无终端单测。

本文件为 r1 第 1 轮 code 阶段产出。
本轮相比 pre-requeue 旧版（已归档至 archive/code-pacman-r1-source-pre-requeue-20260810/）
的唯一调整：清理 r1 评审建议 1 指出的 _init_colors 死代码样式（嵌套 if False else
等价于单行 curses.init_pair(COLOR_CLYDE, COLOR_YELLOW, -1)），改为一行直白调用，
便于维护与静态分析。
"""


try:
    import curses
except ImportError as e:
    curses = None  # type: ignore
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None

from .config import (
    Dir, Kind, Mode, MIN_COLS, MIN_LINES,
    POWER_SCORE,
)
from .game import Game, Status, FinalScore
from .map import GameMap, Tile


def _require_curses():
    """Renderer 构造前调用，确保 curses 可用。"""
    if curses is None:
        raise RuntimeError(
            f"无法导入 curses 模块：{_IMPORT_ERROR}。"
            "在 Debian/Ubuntu 极简发行版请执行：apt install python3-curses"
        )


# ============================================================================
# 颜色对（curses init_pair）
# ============================================================================
COLOR_WALL    = 1
COLOR_DOT     = 2
COLOR_POWER   = 3
COLOR_DOOR    = 4
COLOR_PLAYER  = 5
COLOR_BLINKY  = 6
COLOR_PINKY   = 7
COLOR_INKY    = 8
COLOR_CLYDE   = 9
COLOR_FRIGHT  = 10   # 脆弱：蓝
COLOR_FRIGHT_FLASH = 11  # 脆弱最后 2s 闪烁白
COLOR_EYES    = 12
COLOR_HUD     = 13


def _init_colors() -> bool:
    """初始化颜色对。返回是否成功（无颜色能力时返回 False，回落到 --no-color 风格）。"""
    if not curses.has_colors():
        return False
    curses.start_color()
    try:
        curses.use_default_colors()
        # 颜色对：前景 + 背景（-1 = 默认背景）
        curses.init_pair(COLOR_WALL,   curses.COLOR_BLUE,    -1)
        curses.init_pair(COLOR_DOT,    curses.COLOR_WHITE,   -1)
        curses.init_pair(COLOR_POWER,  curses.COLOR_WHITE,   -1)
        curses.init_pair(COLOR_DOOR,   curses.COLOR_MAGENTA, -1)
        curses.init_pair(COLOR_PLAYER, curses.COLOR_YELLOW,  -1)
        curses.init_pair(COLOR_BLINKY, curses.COLOR_RED,     -1)
        curses.init_pair(COLOR_PINKY,  curses.COLOR_MAGENTA, -1)
        curses.init_pair(COLOR_INKY,   curses.COLOR_CYAN,    -1)
        # Clyde：黄色（与玩家黄区分——玩家在中央、Clyde 在鬼屋附近不易撞色；
        # 极端终端可降级见 main.py --no-color 模式，字符 "G" 仍可区分 4 幽灵）
        curses.init_pair(COLOR_CLYDE,  curses.COLOR_YELLOW,  -1)
        curses.init_pair(COLOR_FRIGHT,        curses.COLOR_BLUE,   -1)
        curses.init_pair(COLOR_FRIGHT_FLASH,  curses.COLOR_WHITE,  -1)
        curses.init_pair(COLOR_EYES,   curses.COLOR_WHITE,   -1)
        curses.init_pair(COLOR_HUD,    curses.COLOR_GREEN,   -1)
        return True
    except curses.error:
        return False


# ============================================================================
# Renderer
# ============================================================================
class Renderer:
    """curses 渲染器。

    draw(game) 一帧：
      - 顶部 HUD（分数/命数/关卡/能量倒计时）
      - 地图
      - PAUSED/GAME_OVER 时叠加画面
    """

    def __init__(self, stdscr, *, no_color: bool = False):
        self.stdscr = stdscr
        self.no_color = no_color
        self.colors_ok = (not no_color) and _init_colors()
        curses.curs_set(0)  # 隐藏光标
        stdscr.nodelay(True)
        stdscr.keypad(True)
        stdscr.timeout(20)  # 主循环 50 FPS 输入轮询（与 TICK_MS 解耦）

    # ------------------------------------------------------------------
    # 主渲染
    # ------------------------------------------------------------------
    def draw(self, game: Game) -> None:
        """绘制一帧。"""
        self.stdscr.erase()
        # 终端尺寸检查（NFR-04/FR-14）
        h, w = self.stdscr.getmaxyx()
        if h < MIN_LINES or w < MIN_COLS:
            self._draw_too_small(h, w)
            self.stdscr.refresh()
            return

        self._draw_hud(game, w)
        self._draw_map(game, top=1)
        if game.status == Status.PAUSED:
            self._draw_paused(h, w)
        elif game.status == Status.GAME_OVER:
            self._draw_game_over(game, h, w)

        self.stdscr.refresh()

    # ------------------------------------------------------------------
    # HUD
    # ------------------------------------------------------------------
    def _draw_hud(self, game: Game, w: int) -> None:
        """顶部一行 HUD：分数 | 命数 | 关卡 | 能量倒计时（如有）。"""
        hud = f"分数: {game.score}  命: {game.lives}  关: {game.level}"
        if game.power_timer > 0.0:
            hud += f"  能量: {game.power_timer:.1f}s"
        else:
            hud += "  状态: 普通"
        self._safe_add(0, 0, hud[:w - 1], COLOR_HUD if self.colors_ok else 0)

    # ------------------------------------------------------------------
    # 地图
    # ------------------------------------------------------------------
    def _draw_map(self, game: Game, top: int) -> None:
        """绘制地图（动态 tile + 实体）。"""
        gm = game.gm
        for r in range(gm.rows):
            for c in range(gm.cols):
                t = game.tiles[r][c]
                ch, color = _tile_char_color(t, self.colors_ok)
                # 玩家位置覆盖
                if (r, c) == (game.player.row, game.player.col):
                    if game.player.protection_timer > 0.0 and int(game.player.protection_timer * 5) % 2 == 0:
                        # 保护期闪烁
                        ch, color = " ", 0
                    else:
                        ch, color = "C", COLOR_PLAYER if self.colors_ok else 0
                # 幽灵位置覆盖
                for g in game.ghosts:
                    if (r, c) == (g.row, g.col) and (r, c) != (game.player.row, game.player.col):
                        ch, color = _ghost_char_color(g, game.power_timer, self.colors_ok)
                        break
                self._safe_add(top + r, c, ch, color)

    # ------------------------------------------------------------------
    # 暂停 / 结算 / 尺寸不足
    # ------------------------------------------------------------------
    def _draw_paused(self, h: int, w: int) -> None:
        msg = "** 已暂停 ** 按 P 继续"
        self._safe_add(h // 2, max(0, (w - len(msg)) // 2), msg,
                       COLOR_HUD if self.colors_ok else 0)

    def _draw_game_over(self, game: Game, h: int, w: int) -> None:
        fs = game.final_score()
        lines = [
            "=== 游戏结束 ===",
            f"最终得分: {fs.score}",
            f"到达关卡: {fs.level}",
            f"吃幽灵数: {fs.ghosts_eaten}",
            "按任意键退出 ...",
        ]
        for i, line in enumerate(lines):
            self._safe_add(h // 2 - len(lines) // 2 + i,
                           max(0, (w - len(line)) // 2),
                           line,
                           COLOR_HUD if self.colors_ok else 0)

    def _draw_too_small(self, h: int, w: int) -> None:
        msg = f"需要 ≥{MIN_COLS}×{MIN_LINES} 终端，当前 {w}×{h}"
        self._safe_add(h // 2, max(0, (w - len(msg)) // 2), msg,
                       COLOR_HUD if self.colors_ok else 0)

    def wait_any_key(self) -> None:
        """等待任意按键退出（用于尺寸不足/结算画面）。"""
        self.stdscr.nodelay(False)
        self.stdscr.getch()

    # ------------------------------------------------------------------
    # 安全 addstr：吞 curses.error（终端边缘等场景）
    # ------------------------------------------------------------------
    def _safe_add(self, y: int, x: int, ch_or_str, color: int) -> None:
        """addstr/addch 的异常安全包装。

        边缘越界（坐标超界）时 curses.error；这里静默吞，不污染主循环。
        """
        try:
            if color and self.colors_ok:
                self.stdscr.addstr(y, x, ch_or_str, curses.color_pair(color))
            else:
                self.stdscr.addstr(y, x, ch_or_str)
        except curses.error:
            # 渲染异常：静默（边缘越界，不污染主循环）
            pass


# ============================================================================
# Tile → 字符 + 颜色
# ============================================================================
def _tile_char_color(t: Tile, colors_ok: bool) -> tuple[str, int]:
    """基础 tile 字符与颜色（不含玩家/幽灵覆盖）。"""
    if t == Tile.WALL:
        return ("█", COLOR_WALL) if colors_ok else ("#", 0)
    if t == Tile.DOT:
        return ("·", COLOR_DOT) if colors_ok else (".", 0)
    if t == Tile.POWER:
        return ("●", COLOR_POWER) if colors_ok else ("o", 0)
    if t == Tile.DOOR:
        return ("-", COLOR_DOOR) if colors_ok else ("-", 0)
    if t == Tile.HOUSE:
        return ("·", COLOR_HUD) if colors_ok else ("H", 0)  # 鬼屋内部：点状灰
    if t == Tile.PLAYER_SPAWN:
        return (" ", 0)
    return (" ", 0)


def _ghost_char_color(g, power_timer: float, colors_ok: bool) -> tuple[str, int]:
    """幽灵字符与颜色（按模式分）。"""
    if not colors_ok:
        return ("G", 0)
    if g.mode == Mode.EYES:
        return ("E", COLOR_EYES)
    if g.mode == Mode.FRIGHTENED:
        # 最后 2s 闪烁
        if 0.0 < power_timer <= 2.0:
            blink = int(power_timer * 5) % 2 == 0
            return ("F", COLOR_FRIGHT_FLASH if blink else COLOR_FRIGHT)
        return ("F", COLOR_FRIGHT)
    # CHASE/SCATTER：按 kind 分色
    color_map = {
        Kind.BLINKY: COLOR_BLINKY,
        Kind.PINKY:  COLOR_PINKY,
        Kind.INKY:   COLOR_INKY,
        Kind.CLYDE:  COLOR_CLYDE,
    }
    return ("G", color_map.get(g.kind, COLOR_HUD))
