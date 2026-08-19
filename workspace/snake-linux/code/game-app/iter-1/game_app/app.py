"""App 类：snake-gui 顶层装配（主事件循环 + 状态机 + 输入分发 + 渲染分发）。

迭代 2 增量（G2-1/2/3/4/5/7）：
- 新增 _storage: Optional[HighScoreStore] 字段（G2-2）
- 删除 _pause_hint_shown 字段（G2-1 INV-8：PAUSED 是真实屏态，不再需要 hint）
- TOGGLE_PAUSE dispatch 从 hint 占位改为 toggle_pause() + 同步切屏（P0-1 方案 A）
- 新增 RESET_HIGHSCORE / BACK_TO_MENU / UNFOCUS / ESCAPE 分支
- _new_game 注册 score_callback（P0-2：回调内直接写 self._high_score 实例字段）
- _run_loop 跳过 PAUSED 态的 _tick（INV-10）
- _render 在 PAUSED 态调 render + draw_pause_overlay（G2-5）
- _drain_events 检测 pygame.key.get_focused() 追加 UNFOCUS（G2-4 仅 PLAYING 态）

沿用 R3（iter-1）：
- R3-1：None→START 屏态兜底唯一在 _drain_events
- R3-2：menu 用 pygame.display.get_surface()
- R3-4：字段命名 _difficulty / _high_score
- R3-5：_running: bool = True（G2-R-N2：主循环不读，保留供 iter-3 dispatch 内部退出用）
- R3-7：删除 _quit() 死代码
- R3-8：_tick 循环内重读 tick_ms
- R3-9：InvalidStateError 理论不可达不包装
- R3-10：App.__init__ 不构造 Renderer / 不构造 HighScoreStore
- R3-11：_render 共享一次 snap
- R3-12：CJK 字体回退链
- R3-15：退出码 2 路径也尝试一次 Renderer.shutdown()

G2-R-N1 修订：
- AppConfig.__post_init__ 校验（构造期抛 ConfigError）
- main() 捕获 ConfigError + AppError 后退出码 1

G2-R-N2 修订：主循环 `while True`（不读 _running）
"""
from __future__ import annotations

import random
import sys
from typing import Any, List, Optional

import pygame  # noqa: F401  # 由 UT 替换为 fake_pygame

from game_core import (
    Direction,
    Difficulty,
    GameState,
    GameStatus,
    InvalidStateError,
    Snapshot,
)
from gui_renderer import (
    DEFAULT_SKIN,
    HudData,
    RenderError,
    Renderer,
)
from platform_storage import StorageError

from .config import AppConfig
from .errors import (
    AppError,
    ConfigError,
    GraphicsUnavailableError,
    StorageUnavailableError,
)
from .fonts import _load_cjk_font
from .input import (
    _GAME_OVER_RESERVED_ACTIONS,
    _MENU_RESERVED_ACTIONS,
    _map_event,
    InputAction,
)
from .menu import draw_game_over, draw_menu, draw_pause_overlay
from .screens import AppScreen
from .storage import create_storage


# HUD 字段映射（中文难度标签 + 英文状态标签）
_DIFFICULTY_LABEL = {
    Difficulty.EASY: "简单",
    Difficulty.MEDIUM: "普通",
    Difficulty.HARD: "困难",
}

_STATUS_LABEL = {
    GameStatus.RUN: "RUN",
    GameStatus.PAUSED: "PAUSED",
    GameStatus.OVER: "OVER",
}


class App:
    """snake-gui 顶层装配；PyInstaller 入口。"""

    def __init__(self, config: AppConfig = AppConfig()) -> None:
        """仅置字段，不开窗、不调 pygame.init、不构造 Renderer（R3-10）、不构造 HighScoreStore（R3-10 + G2-2）。

        默认参数 config: AppConfig = AppConfig() 在 import 期求值一次（frozen 不可变，
        功能无害；G2-R-N6：UT 需不同 config 时显式传）。

        初始 screen=MENU, _difficulty=MEDIUM, game_state=None, _renderer=None,
        _storage=None（G2-2 让 UT 不依赖磁盘）, _high_score=0, _running=True,
        _tick_accumulator_ms=0。
        G2-1 删除 _pause_hint_shown 字段（INV-8）。
        """
        self.config = config
        # 字段名遵循 R3-4 统一为 _difficulty / _high_score
        self.screen: AppScreen = AppScreen.MENU
        self._difficulty: Difficulty = Difficulty.MEDIUM
        self.game_state: Optional[GameState] = None
        self._renderer: Optional[Renderer] = None
        self._storage: Optional[Any] = None  # G2-2：默认 None 让 UT 不依赖磁盘
        self._high_score: int = 0  # _init_pygame 覆盖为 storage.load()
        self._tick_accumulator_ms: int = 0
        self._running: bool = True  # R3-5 + G2-R-N2：主循环不读，保留供 iter-3 用
        # 删除 _pause_hint_shown（G2-1 INV-8）
        # CJK 字体（_init_pygame 内构造）
        self._menu_title_font: Optional[pygame.font.Font] = None
        self._menu_body_font: Optional[pygame.font.Font] = None
        self.clock: Optional[pygame.time.Clock] = None

    # ---- 公开入口 ----

    def run(self) -> int:
        """主循环。返回进程退出码（0 正常 / 1 异常 / 2 图形环境不可用）。

        R3-15：退出码 2 路径也尝试 renderer.shutdown() 兜底。
        """
        self._renderer = None
        try:
            try:
                self._init_pygame()
            except GraphicsUnavailableError as e:
                print(
                    f"[错误] 无法初始化图形界面: {e}\n"
                    "请确认系统有可用的图形环境。",
                    file=sys.stderr,
                )
                return 2
            return self._run_loop()
        finally:
            # 即便 _init_pygame 部分成功（display.set_mode 失败）也尝试一次 shutdown
            try:
                if self._renderer is not None:
                    self._renderer.shutdown()
            except Exception:
                pass

    # ---- 内部接口 ----

    def _init_pygame(self) -> None:
        """构造 renderer + HighScoreStore；CJK 字体回退链。

        R3-10：App.__init__ 不构造 Renderer / HighScoreStore，_init_pygame 内才赋值。
        R3-12：CJK 字体走回退链构造 _menu_title_font / _menu_body_font。
        失败时 RenderError / pygame.error → GraphicsUnavailableError。
        G2-2：HighScoreStore 构造在 _init_pygame 内；mkdir 失败抛 (StorageError, OSError) → AppError。
        P1-3：_storage = None 时由 fixture 注入 fake；构造前 `if self._storage is None:` 跳过 create_storage。
        """
        try:
            self._renderer = Renderer(
                (self.config.window_w, self.config.window_h),
                skin=DEFAULT_SKIN,
            )
            self._renderer.init()
        except (RenderError, pygame.error) as e:
            raise GraphicsUnavailableError(str(e)) from e

        # G2-2：构造 HighScoreStore（P1-3 已注入 fake 则跳过；P1-1 捕获双类型）
        if self._storage is None:
            try:
                self._storage = create_storage()
                self._high_score = self._storage.load()
            except (StorageError, OSError) as e:
                raise AppError(f"用户数据目录不可写: {e}") from e

        # R3-12：CJK 字体回退链
        self._menu_title_font = _load_cjk_font(48, bold=True)
        self._menu_body_font = _load_cjk_font(22)

        self.clock = pygame.time.Clock()

    def _run_loop(self) -> int:
        """主事件循环。G2-1：screen==PAUSED 跳过 _tick（INV-10）。

        G2-R-N2 修订：主循环 `while True`（不读 _running，保留字段供 iter-3 用）。
        """
        try:
            while True:
                assert self.clock is not None
                dt_ms = self.clock.tick_busy_loop(self.config.fps_cap)
                actions = self._drain_events()
                if InputAction.QUIT in actions:
                    break
                for a in actions:
                    self._dispatch(a)
                if self.screen == AppScreen.PLAYING:  # G2-1 排除 PAUSED
                    self._tick(dt_ms)
                self._render()
            return 0
        except AppError as e:  # G2-2 含 StorageUnavailableError
            print(f"[错误] {e}", file=sys.stderr)
            return 1

    def _drain_events(self) -> List[InputAction]:
        """本帧所有 pygame 事件归一化；QUIT 优先 break；G2-4 失焦追加 UNFOCUS；G2-7 GAME_OVER 态 ESC 覆盖。

        R3-1 屏态兜底（不变）：MENU 屏态下所有 action（除保留键外）→ START。
        G2-4 新增：screen==PLAYING 时 pygame.key.get_focused() == False → 追加 UNFOCUS。
        G2-7 / P1-2 修订：screen==GAME_OVER 时 ESCAPE → BACK_TO_MENU（仅 ESC 转，Q 保持 QUIT 直通 break）。
        """
        raw = pygame.event.get()
        actions: List[InputAction] = []
        for ev in raw:
            action = _map_event(ev)
            if self.screen == AppScreen.MENU:
                if action is None:
                    action = InputAction.START
                elif action not in _MENU_RESERVED_ACTIONS:
                    action = InputAction.START
            elif self.screen == AppScreen.GAME_OVER:  # G2-7 / P1-2
                if action == InputAction.ESCAPE:
                    action = InputAction.BACK_TO_MENU
            if action is not None:
                actions.append(action)

        # G2-4 失焦检测（仅 PLAYING 态，其他屏态已有处理）
        if self.screen == AppScreen.PLAYING:
            try:
                focused = pygame.key.get_focused()
            except Exception:
                focused = True  # 平台不支持时兜底
            if not focused:
                actions.append(InputAction.UNFOCUS)
        return actions

    def _dispatch(self, action: InputAction) -> None:
        """按当前 screen 分发。G2-1 加 PAUSED 态。"""
        if self.screen == AppScreen.MENU:
            self._dispatch_menu(action)
        elif self.screen == AppScreen.PLAYING:
            self._dispatch_playing(action)
        elif self.screen == AppScreen.PAUSED:  # G2-1 新增
            self._dispatch_paused(action)
        elif self.screen == AppScreen.GAME_OVER:
            self._dispatch_over(action)

    def _dispatch_menu(self, action: InputAction) -> None:
        """MENU 态分发。G2-3 新增 RESET_HIGHSCORE；R3-1/4/7 沿用。"""
        if action == InputAction.SELECT_EASY:
            self._difficulty = Difficulty.EASY
        elif action == InputAction.SELECT_MEDIUM:
            self._difficulty = Difficulty.MEDIUM
        elif action == InputAction.SELECT_HARD:
            self._difficulty = Difficulty.HARD
        elif action == InputAction.RESET_HIGHSCORE:  # G2-3 新增
            if self._storage is not None:
                try:
                    self._storage.reset()
                except StorageError as e:
                    raise StorageUnavailableError(f"重置最高分失败: {e}") from e
                self._high_score = 0
        elif action == InputAction.START:
            self._new_game(self._difficulty)
        # 其他 action（MOVE_*/TOGGLE_PAUSE/RESTART 等）由 _drain_events MENU 态兜底转 START

    def _dispatch_playing(self, action: InputAction) -> None:
        """PLAYING 态分发。G2-1：TOGGLE_PAUSE 从 hint 占位改为 toggle_pause() + 同步切屏。

        **P0-1 屏态同步方案 A**：TOGGLE_PAUSE / UNFOCUS 调 `toggle_pause()` 后
        **显式**写 `self.screen = AppScreen.PAUSED`（与 §1.4 INV-11 一致）。
        """
        if action in (
            InputAction.MOVE_UP, InputAction.MOVE_DOWN,
            InputAction.MOVE_LEFT, InputAction.MOVE_RIGHT,
        ):
            d = {
                InputAction.MOVE_UP: Direction.UP,
                InputAction.MOVE_DOWN: Direction.DOWN,
                InputAction.MOVE_LEFT: Direction.LEFT,
                InputAction.MOVE_RIGHT: Direction.RIGHT,
            }
            self.game_state = self.game_state.set_direction(d[action])
        elif action == InputAction.TOGGLE_PAUSE:  # G2-1 修订（P0-1 同步切屏）
            self.game_state = self.game_state.toggle_pause()  # R3-9 不包装
            self.screen = AppScreen.PAUSED  # P0-1 同步切屏（INV-11）
        elif action == InputAction.UNFOCUS:  # G2-4 新增（P0-1 同步切屏）
            if self.game_state.status == GameStatus.RUN:
                self.game_state = self.game_state.toggle_pause()
                self.screen = AppScreen.PAUSED

    def _dispatch_paused(self, action: InputAction) -> None:
        """PAUSED 态分发（G2-1 新增）。仅响应 TOGGLE_PAUSE / UNFOCUS。

        **P0-1 屏态同步方案 A**：TOGGLE_PAUSE 调 `toggle_pause()` 后显式切屏至 PLAYING。
        """
        if action == InputAction.TOGGLE_PAUSE:  # G2-1 P 继续
            self.game_state = self.game_state.toggle_pause()  # PAUSED→RUN
            self.screen = AppScreen.PLAYING  # P0-1 同步切屏（INV-11）
        elif action == InputAction.UNFOCUS:
            pass  # PAUSED 态再失焦不变（G2-4）

    def _dispatch_over(self, action: InputAction) -> None:
        """GAME_OVER 态分发。G2-7 新增 BACK_TO_MENU；R3-7 删除 QUIT 分支。"""
        if action == InputAction.RESTART:
            self._new_game(self._difficulty)
        elif action == InputAction.BACK_TO_MENU:  # G2-7 新增（P1-2 修订 ESC 由 _drain_events 覆盖）
            self.screen = AppScreen.MENU
            self.game_state = None  # INV-7 重置

    def _new_game(self, difficulty: Difficulty) -> None:
        """game_state = GameState(width=20, height=15, difficulty=..., rng=Random(),
                                 score_callback=<绑定 self._storage>); screen=PLAYING。

        **G2-3 + P0-2 权威实现**（仅本函数）：
        1. 若 `_storage is None`（UT 未注入）：`score_callback=None`（core 不触发）。
        2. 若 `_storage is not None`（生产环境）：注册回调 `lambda s: self._on_score(s)`，
           `_on_score` 内**直接写**（P0-2）：
           - `self._high_score = max(self._high_score, s)` ← INV-13 同步实例字段
           - `self._storage.save(max(s, self._storage.load()))` ← 落盘
           - 若 storage.save 抛 StorageError → 包 StorageUnavailableError(AppError)
        3. `game_state` 用全关键字构造（game-core iter-2 锁定签名）。
        4. 重置 `_tick_accumulator_ms=0` + `screen=PLAYING`。
        """
        if self._storage is None:
            cb = None
        else:
            _storage = self._storage
            def cb(score: int) -> None:
                try:
                    self._high_score = max(self._high_score, score)  # INV-13 P0-2
                    _storage.save(max(score, _storage.load()))
                except StorageError as e:
                    raise StorageUnavailableError(f"写入最高分失败: {e}") from e
        self.game_state = GameState(
            width=20,
            height=15,
            difficulty=difficulty,
            rng=random.Random(),
            score_callback=cb,
        )
        self._tick_accumulator_ms = 0
        self.screen = AppScreen.PLAYING

    def _tick(self, dt_ms: int) -> None:
        """PLAYING 态累加节拍。G2-1 PAUSED 不进入此函数（主循环判断）。

        循环内逐拍重读 tick_ms（R3-8）；OVER 自动转 GAME_OVER（G2-1）。
        **P0-1 屏态同步方案 A**：_tick 不再做屏态切换——
        - 切屏发生在 _dispatch_* 内显式赋值（INV-11 方案 A）
        - core step() 在 status != RUN 时抛 InvalidStateError，永不返回非 RUN 状态
        """
        assert self.screen == AppScreen.PLAYING  # G2-1 INV-10/11 入口断言
        assert self.game_state is not None
        assert self.game_state.status == GameStatus.RUN  # INV-1 入口断言
        self._tick_accumulator_ms += dt_ms
        while True:
            tick_ms = self.game_state.snapshot().tick_ms
            if self._tick_accumulator_ms < tick_ms:
                break
            self._tick_accumulator_ms -= tick_ms
            self.game_state = self.game_state.step()
            new_status = self.game_state.status
            if new_status == GameStatus.OVER:
                self.screen = AppScreen.GAME_OVER  # OVER 自动转 GAME_OVER
                break

    def _build_hud(self, snap: Snapshot) -> HudData:
        """R3-11：_render 共享一次 snapshot 后传入。G2-6 high_score 来源 self._high_score。"""
        assert self._menu_body_font is not None
        return HudData(
            score=snap.score,
            high_score=self._high_score,  # G2-2 由 storage.load() 替换
            length=snap.length,
            difficulty_label=_DIFFICULTY_LABEL[self._difficulty],
            status_label=_STATUS_LABEL[snap.status],
        )

    def _render(self) -> None:
        """按 screen 分发。G2-1 PAUSED：renderer.render + draw_pause_overlay。

        R3-2：用 pygame.display.get_surface()，不读 _screen。
        R3-11：PLAYING 路径只取一次 snap。
        G2-6：MENU / GAME_OVER 自绘加 high_score 形参。
        """
        if self.screen == AppScreen.MENU:
            surface = pygame.display.get_surface()
            assert surface is not None, "MENU graphic not initialized"
            assert self._menu_title_font is not None and self._menu_body_font is not None
            draw_menu(  # G2-6 加 high_score
                surface,
                self._menu_title_font,
                self._menu_body_font,
                self._difficulty,
                high_score=self._high_score,
            )
        elif self.screen == AppScreen.PLAYING:
            assert self._renderer is not None
            snap = self.game_state.snapshot()
            hud = self._build_hud(snap)
            self._renderer.render(snap, hud)
        elif self.screen == AppScreen.PAUSED:  # G2-1/G2-5 新增
            assert self._renderer is not None and self.game_state is not None
            snap = self.game_state.snapshot()
            hud = self._build_hud(snap)
            self._renderer.render(snap, hud)  # 渲染最后一帧
            surface = pygame.display.get_surface()
            assert surface is not None
            draw_pause_overlay(surface, self._menu_body_font)  # G2-5 叠加遮罩
        elif self.screen == AppScreen.GAME_OVER:
            surface = pygame.display.get_surface()
            assert surface is not None
            score = self.game_state.snapshot().score if self.game_state else 0
            assert self._menu_title_font is not None and self._menu_body_font is not None
            draw_game_over(  # G2-6 加 high_score
                surface,
                self._menu_title_font,
                self._menu_body_font,
                score,
                high_score=self._high_score,
            )
        pygame.display.flip()


def main() -> int:
    """入口函数：捕获 ConfigError / AppError 后输出可读提示 + 退出码。"""
    try:
        return App().run()
    except ConfigError as e:
        print(f"[错误] 配置非法: {e}", file=sys.stderr)
        return 1
    except AppError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1


__all__ = [
    "App",
    "main",
    "_DIFFICULTY_LABEL",
    "_STATUS_LABEL",
    "_GAME_OVER_RESERVED_ACTIONS",
]