"""menu 模块：MENU / GAME_OVER / PAUSED 自绘（R3-2 不读 renderer 私有）。

仅依赖 pygame + Difficulty 枚举；surface 由调用方通过 pygame.display.get_surface() 提供。

G2-5 iter-2 新增 draw_pause_overlay（暂停遮罩自绘）
G2-6 iter-2 新增 draw_menu / draw_game_over 形参 high_score
"""
from __future__ import annotations

import pygame

from game_core import Difficulty

from ._constants import (
    MENU_BG, MENU_DIFFICULTY_DEFAULT, MENU_DIFFICULTY_HIGHLIGHT,
    MENU_HINT_COLOR, MENU_QUIT_HINT_COLOR, MENU_TITLE_COLOR,
    OVER_BG, OVER_HINT_COLOR, OVER_SCORE_COLOR, OVER_TITLE_COLOR,
    PAUSE_OVERLAY_ALPHA, PAUSE_OVERLAY_COLOR,
    PAUSE_OVERLAY_TITLE_COLOR, PAUSE_OVERLAY_HINT_COLOR,
)


def draw_menu(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    difficulty: Difficulty,
    high_score: int = 0,
) -> None:
    """MENU 态自绘（pygame.font + pygame.draw）。

    入参：surface 来自 pygame.display.get_surface()（R3-2 不读 _screen）。
    G2-6：high_score > 0 时显示"最高分：xxx"行；= 0 时不显示（避免"最高分：0"误导）。
    """
    surface.fill(MENU_BG)

    # 标题
    title = title_font.render("Snake GUI v2.0.0", True, MENU_TITLE_COLOR)
    surface.blit(
        title,
        (surface.get_width() // 2 - title.get_width() // 2, 100),
    )

    # 难度选项（高亮当前选中档）
    lines = [
        ("按 1 键 = 简单", Difficulty.EASY),
        ("按 2 键 = 普通", Difficulty.MEDIUM),
        ("按 3 键 = 困难", Difficulty.HARD),
    ]
    for i, (text, diff) in enumerate(lines):
        color = MENU_DIFFICULTY_HIGHLIGHT if diff == difficulty else MENU_DIFFICULTY_DEFAULT
        surf = body_font.render(text, True, color)
        surface.blit(
            surf,
            (surface.get_width() // 2 - surf.get_width() // 2, 220 + i * 36),
        )

    # G2-6：最高分行
    if high_score > 0:
        hs_line = body_font.render(f"最高分：{high_score}", True, MENU_DIFFICULTY_HIGHLIGHT)
        surface.blit(
            hs_line,
            (surface.get_width() // 2 - hs_line.get_width() // 2, 340),
        )

    # G2-R-N3 提示补正
    hint = body_font.render(
        "Enter / 空格 / 其他键 开始（P 暂停 · H 重置最高分 · Q 退出）",
        True, MENU_HINT_COLOR,
    )
    surface.blit(
        hint,
        (surface.get_width() // 2 - hint.get_width() // 2, 400),
    )

    quit_hint = body_font.render("Q 退出", True, MENU_QUIT_HINT_COLOR)
    surface.blit(
        quit_hint,
        (surface.get_width() // 2 - quit_hint.get_width() // 2, 440),
    )


def draw_game_over(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    score: int,
    high_score: int = 0,
) -> None:
    """GAME_OVER 态自绘。G2-6：high_score > 0 时显示"最高分：xxx"行；G2-7：Esc/Backspace 提示。"""
    surface.fill(OVER_BG)

    big = title_font.render("Game Over", True, OVER_TITLE_COLOR)
    surface.blit(
        big,
        (surface.get_width() // 2 - big.get_width() // 2, 100),
    )

    line = body_font.render(f"最终得分：{score}", True, OVER_SCORE_COLOR)
    surface.blit(
        line,
        (surface.get_width() // 2 - line.get_width() // 2, 180),
    )

    if high_score > 0:
        hs_line = body_font.render(f"最高分：{high_score}", True, MENU_DIFFICULTY_HIGHLIGHT)
        surface.blit(
            hs_line,
            (surface.get_width() // 2 - hs_line.get_width() // 2, 220),
        )

    # G2-7 新增 Esc / Backspace 返回菜单提示
    hint = body_font.render(
        "R 重开    Esc / Backspace 返回菜单    Q 退出",
        True, OVER_HINT_COLOR,
    )
    surface.blit(
        hint,
        (surface.get_width() // 2 - hint.get_width() // 2, 320),
    )


def draw_pause_overlay(
    surface: pygame.Surface,
    body_font: pygame.font.Font,
) -> None:
    """PAUSED 遮罩自绘（G2-5 iter-2 新增）。

    surface 来自 pygame.display.get_surface()（R3-2 沿用）。
    步骤：
    1. 半透明矩形 (0,0,0,PAUSE_OVERLAY_ALPHA) 覆盖全屏
    2. 居中绘制 "PAUSED" 大字（body_font 22px 统一渲染，P2-6 修订）
    3. 居中绘制 "按 P 继续" 小字
    """
    # 1. 半透明矩形覆盖全屏
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill(PAUSE_OVERLAY_COLOR)
    surface.blit(overlay, (0, 0))
    # 2. 居中绘制 "PAUSED"
    title = body_font.render("PAUSED", True, PAUSE_OVERLAY_TITLE_COLOR)
    surface.blit(
        title,
        (
            surface.get_width() // 2 - title.get_width() // 2,
            surface.get_height() // 2 - title.get_height() // 2,
        ),
    )
    # 3. 居中绘制 "按 P 继续"
    hint = body_font.render("按 P 继续", True, PAUSE_OVERLAY_HINT_COLOR)
    surface.blit(
        hint,
        (
            surface.get_width() // 2 - hint.get_width() // 2,
            surface.get_height() // 2 + hint.get_height(),
        ),
    )


__all__ = ["draw_menu", "draw_game_over", "draw_pause_overlay"]