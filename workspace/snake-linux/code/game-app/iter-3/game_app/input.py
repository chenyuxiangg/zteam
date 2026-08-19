"""input 模块：pygame 事件 → InputAction 归一化。

设计要点：
- _map_event 仅做单键归一化，**不感知屏态**（返 None = 未映射）
- 屏态兜底（None→START、保留键透传）由 App._drain_events 完成（R3-1 全文统一）
- _MENU_RESERVED_ACTIONS：MENU 态保留不转 START 的 actions
- _GAME_OVER_RESERVED_ACTIONS：GAME_OVER 态保留不转 BACK_TO_MENU 的 actions（G2-7）
- 所有 pygame 常量（K_*, KEYDOWN, QUIT, VIDEORESIZE）通过 _pygame_attr(name) 延迟读取，
  让 UT 可在 monkeypatch.fake_pygame 替换后再读这些常量。

G2-3/7 新增 action：
- RESET_HIGHSCORE：H 键 → MENU 态 dispatch
- BACK_TO_MENU：Backspace → GAME_OVER 态 dispatch
- ESCAPE：ESC 键（独立 action，与 Q 的 QUIT 区分——P1-2 修订）

G2-4 新增 action：
- UNFOCUS：内部信号，不来自 _map_event，仅主循环内检测到失焦时入 actions

迭代 3 增量（G3-1/G3-2）：
- SET_SKIN_PREV / SET_SKIN_NEXT（G3-1）：←/→ 键 → _drain_events 内按屏态分发
  （MENU 态切皮肤，其他屏态透传为 MOVE_LEFT/MOVE_RIGHT——保持对局不中断）
- RESIZE（G3-2）：pygame.VIDEORESIZE 事件 → _drain_events 内同步处理（直接调
  Renderer.handle_resize，不入 dispatch 列表）。r2-2 契约前置：Renderer 窗口必须
  带 RESIZABLE 标志（VIDEORESIZE 事件源），由 gui-renderer iter-3 落实。
- 成员总数 = 18（iter-2 15 + iter-3 3，r2-5 修订）
- K_a/K_d 始终为 MOVE_LEFT/MOVE_RIGHT（G3-1 修订：避免 WASD 用户意外触发皮肤切换）
"""
from __future__ import annotations

import sys
from enum import Enum
from typing import Any, Optional


def _pygame_attr(name: str) -> Any:
    """通过 sys.modules['pygame'].__dict__ 读取当前 pygame 模块的属性。

    关键：使用 sys.modules['pygame'].__dict__ 而非 import pygame 缓存的属性，
    让 UT 在 monkeypatch.setitem(sys.modules, 'pygame', fake) 后能读到 fake 的值。
    """
    return sys.modules["pygame"].__dict__.get(name)


class InputAction(Enum):
    """pygame 事件归一化结果。FO 只需实现 _map_event() 即可。

    迭代 3 增量（G3-1/G3-2，r2-5 修订计数）：
    - SET_SKIN_PREV = "skin_prev"    # ← 键：MENU 态切上一皮肤（G3-1）
    - SET_SKIN_NEXT = "skin_next"    # → 键：MENU 态切下一皮肤（G3-1）
    - RESIZE = "resize"              # pygame.VIDEORESIZE 事件（G3-2，r2-2 契约前置）
                                     # _drain_events 内同步处理（直接调 Renderer.handle_resize）
                                     # 其他动作维持原行为
    成员总数 = 18（iter-2 沿用 15 + iter-3 新增 3）：
      QUIT/START/MOVE_UP/MOVE_DOWN/MOVE_LEFT/MOVE_RIGHT/TOGGLE_PAUSE/RESTART
      /SELECT_EASY/SELECT_MEDIUM/SELECT_HARD/RESET_HIGHSCORE/BACK_TO_MENU/ESCAPE/UNFOCUS
      +SET_SKIN_PREV/SET_SKIN_NEXT/RESIZE
    """

    QUIT = "quit"
    START = "start"             # MENU 态：所有"非 QUIT/SELECT_*/TOGGLE_PAUSE/RESTART/RESET_HIGHSCORE"的 KEYDOWN（R3-1）
    MOVE_UP = "up"
    MOVE_DOWN = "down"
    MOVE_LEFT = "left"
    MOVE_RIGHT = "right"
    TOGGLE_PAUSE = "pause"      # P 键：G2-1 切换 PLAYING ↔ PAUSED
    RESTART = "restart"         # GAME_OVER 态：R 键
    SELECT_EASY = "sel_easy"    # MENU 态：1 键
    SELECT_MEDIUM = "sel_med"   # MENU 态：2 键
    SELECT_HARD = "sel_hard"    # MENU 态：3 键
    RESET_HIGHSCORE = "reset_hs"   # G2-3 iter-2 新增：H 键 → MENU 态 dispatch
    BACK_TO_MENU = "back"          # G2-7 iter-2 新增：Backspace → GAME_OVER 态 dispatch
    ESCAPE = "escape"             # P1-2 iter-2 新增：ESC 键独立 action（与 Q 区分）
    UNFOCUS = "unfocus"           # G2-4 iter-2 新增：内部信号，不来自 _map_event
    # ---- iter-3 增量（G3-1/G3-2）----
    SET_SKIN_PREV = "skin_prev"     # G3-1 ← 键：MENU 态切上一皮肤
    SET_SKIN_NEXT = "skin_next"     # G3-1 → 键：MENU 态切下一皮肤
    RESIZE = "resize"               # G3-2 pygame.VIDEORESIZE 事件（r2-2 契约前置）


# R3-1：MENU 态保留键（G2-3 新增 RESET_HIGHSCORE）
_MENU_RESERVED_ACTIONS = frozenset({
    InputAction.QUIT,
    InputAction.SELECT_EASY, InputAction.SELECT_MEDIUM, InputAction.SELECT_HARD,
    InputAction.TOGGLE_PAUSE, InputAction.RESTART,
    InputAction.RESET_HIGHSCORE,                  # G2-3 新增
    # 注意：ESCAPE **不在** _MENU_RESERVED_ACTIONS 内（P1-2 修订：MENU 态下 ESCAPE
    # 由 _drain_events 兜底转 START，与 iter-1 "ESC 视为开始"语义一致）
    # UNFOCUS 也不在（内部信号，不经 _drain_events）
})


# G2-7：GAME_OVER 态保留键（GAME_OVER 态下这些键不进 BACK_TO_MENU 兜底转换；
# _drain_events 在 GAME_OVER 态仅对 ESCAPE → BACK_TO_MENU 做屏态覆盖）
_GAME_OVER_RESERVED_ACTIONS = frozenset({
    InputAction.QUIT,
    InputAction.RESTART,
    InputAction.BACK_TO_MENU,
    InputAction.ESCAPE,
})


def _map_event(event: "pygame.event.Event") -> Optional[InputAction]:
    """单键归一化；不感知屏态；返回 None 表示未映射（由 _drain_events 屏态兜底处理）。

    所有 pygame 常量通过 _pygame_attr() 延迟读取（UT 友好）。

    iter-3 增量（G3-1/G3-2）：
    - ← 键 → SET_SKIN_PREV（G3-1）—— _drain_events 内按屏态分发：
      MENU 态切皮肤，其他屏态透传为 MOVE_LEFT（不影响对局，FR-10）
    - → 键 → SET_SKIN_NEXT（G3-1）—— 同上，右方向
    - pygame.VIDEORESIZE 事件 → RESIZE（G3-2）—— _drain_events 内同步处理，
      直接调 Renderer.handle_resize；r2-2 契约前置：Renderer 窗口必须带 RESIZABLE 标志
    - K_a/K_d 保持 MOVE_LEFT/MOVE_RIGHT（G3-1 修订：避免 WASD 用户意外触发皮肤切换）
    - K_UP/K_DOWN 保持 MOVE_UP/MOVE_DOWN（G3-1 修订：仅方向键 ← / → 触发皮肤切换）
    """
    QUIT_TYPE = _pygame_attr("QUIT")
    KEYDOWN_TYPE = _pygame_attr("KEYDOWN")
    VIDEORESIZE_TYPE = _pygame_attr("VIDEORESIZE")  # G3-2 新增
    K_q = _pygame_attr("K_q")
    K_ESCAPE = _pygame_attr("K_ESCAPE")
    K_BACKSPACE = _pygame_attr("K_BACKSPACE")

    if event.type == QUIT_TYPE:
        return InputAction.QUIT
    # G3-2 新增：VIDEORESIZE 事件 → RESIZE
    if event.type == VIDEORESIZE_TYPE:
        return InputAction.RESIZE
    if event.type != KEYDOWN_TYPE:
        return None
    k = event.key
    if k == K_q:
        return InputAction.QUIT  # P1-2：Q 键 → QUIT（主循环 break）
    if k == K_ESCAPE:
        return InputAction.ESCAPE  # P1-2：ESC 键 → ESCAPE（GAME_OVER 由 _drain_events 覆盖为 BACK_TO_MENU）
    if k == K_BACKSPACE:
        return InputAction.BACK_TO_MENU  # G2-7：Backspace 直返 BACK_TO_MENU
    if k == _pygame_attr("K_p"):
        return InputAction.TOGGLE_PAUSE
    if k == _pygame_attr("K_r"):
        return InputAction.RESTART
    if k == _pygame_attr("K_h"):
        return InputAction.RESET_HIGHSCORE  # G2-3 新增
    if k == _pygame_attr("K_1"):
        return InputAction.SELECT_EASY
    if k == _pygame_attr("K_2"):
        return InputAction.SELECT_MEDIUM
    if k == _pygame_attr("K_3"):
        return InputAction.SELECT_HARD
    # G3-1 新增：←/→ 键 → SET_SKIN_PREV/SET_SKIN_NEXT（在 _drain_events 内按屏态分发）
    if k == _pygame_attr("K_LEFT"):
        return InputAction.SET_SKIN_PREV
    if k == _pygame_attr("K_RIGHT"):
        return InputAction.SET_SKIN_NEXT
    # WASD 方向键（iter-2 沿用；G3-1 修订：K_a/K_d 不映射皮肤）
    if k == _pygame_attr("K_w") or k == _pygame_attr("K_UP"):
        return InputAction.MOVE_UP
    if k == _pygame_attr("K_s") or k == _pygame_attr("K_DOWN"):
        return InputAction.MOVE_DOWN
    if k == _pygame_attr("K_a") or k == _pygame_attr("K_LEFT"):  # 永远不会命中（已被 SET_SKIN_PREV 截获）
        return InputAction.MOVE_LEFT
    if k == _pygame_attr("K_d") or k == _pygame_attr("K_RIGHT"):  # 永远不会命中（已被 SET_SKIN_NEXT 截获）
        return InputAction.MOVE_RIGHT
    # 其他 KEYDOWN（含字母数字、鼠标等）→ None
    return None


__all__ = [
    "InputAction",
    "_MENU_RESERVED_ACTIONS",
    "_GAME_OVER_RESERVED_ACTIONS",
    "_map_event",
    "_pygame_attr",
]