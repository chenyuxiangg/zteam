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

迭代 3 增量（G3-1/2/3/4/5）：
- 新增 _skin_index: int 字段（G3-1，皮肤循环索引；r2-4 修订：派生用 skin_names()[_skin_index]）
- 新增 _prev_snap: Optional[Snapshot] 字段（G3-3，r2-1 修订：_tick step 前保存 + r2-3 _new_game 重置）
- AppConfigV3 子类支持（G3-4）：isinstance 判定 + enable_high_dpi 传入 Renderer 构造
- _drain_events 同步处理 VIDEORESIZE（G3-2，r2-2 契约前置：不入 dispatch）
- _drain_events MENU 态处理 SET_SKIN_PREV/NEXT（G3-1，不入 dispatch）
- _render PLAYING 路径走 interp=InterpolationState（G3-3，r2-1 alpha=elapsed/tick_ms 公式）
- _tick step 前维护 _prev_snap（G3-3，r2-1 修订赋值时机）
- _new_game 重置 _prev_snap = None（G3-3，r2-3 修订生命周期）
- _render MENU 自绘加 current_skin_name 形参（G3-5）
- _interpolation_state 实现真实 Chebyshev 距离防御（G3-3，r2-3 修订）
- _interpolation_state 删除冗余 self.game_state 检查（G3-3，r2-6 修订）
- _switch_skin（MENU 态切换皮肤）/ _handle_resize（VIDEORESIZE 同步处理）新方法

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
import warnings
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

from .config import AppConfig, AppConfigV3
from .errors import (
    AppError,
    ConfigError,
    GraphicsUnavailableError,
    HighDPIWarning,
    PlatformUnsupportedWarning,
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
from gui_renderer import InterpolationState, SkinNotFoundError  # G3-3 iter-3 新增 + G3-1 SkinNotFoundError 兜底


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


# ---- 迭代 4 G4-2 模块级辅助函数 ----

def _create_renderer_with_hidpi_fallback(
    window_size: tuple,
    *,
    skin: Any,
    enable_high_dpi: bool,
) -> Any:
    """G4-2 新增：HiDPI 降级包装（设计 §4.7）。

    步骤：
      1. 尝试构造 Renderer(window_size, skin=skin, enable_high_dpi=enable_high_dpi) + init()
      2. 第一次失败 → stderr warning（HighDPIWarning）+ 降级到 enable_high_dpi=False
      3. 第二次仍失败 → GraphicsUnavailableError 退出码 2

    副作用：调用方（_init_pygame）需在降级成功后将 self._hidpi_degraded 置 True。

    Args:
        window_size: (width, height) 元组
        skin: 初始皮肤（gui_renderer.Skin）
        enable_high_dpi: 是否启用 HiDPI 缩放

    Returns:
        已 init 的 Renderer 实例

    Raises:
        GraphicsUnavailableError: 两次 init 均失败时（退出码 2）
    """
    try:
        renderer = Renderer(window_size, skin=skin, enable_high_dpi=enable_high_dpi)
        renderer.init()
        return renderer
    except (RenderError, pygame.error) as e:
        if not enable_high_dpi:
            # 本就没开 HiDPI，仍失败 → 直接抛 GraphicsUnavailableError
            raise GraphicsUnavailableError(
                f"图形环境初始化失败: {e}",
                suggestion="请检查：1. 显示器已连接；2. SDL2 库已安装（Linux: apt install libsdl2-dev）；3. 显卡驱动版本正常",
            ) from e

        # HiDPI 失败 → 降级到非 HiDPI（stderr warning）
        warnings.warn(
            f"HiDPI 缩放失败，降级到非 SCALED 模式: {e}",
            HighDPIWarning,
            stacklevel=2,
        )
        try:
            renderer = Renderer(window_size, skin=skin, enable_high_dpi=False)
            renderer.init()
            # 通知调用方降级成功（G4-2 通过 monkeypatch 访问 _create_renderer_with_hidpi_fallback 调用栈
            # 不便直接改 App 实例字段；改用线程局部 / 全局标记是不优雅的做法。
            # 这里采用更直接的方式：把降级标志写到 Renderer 实例上的自定义属性，App._init_pygame 读取。
            setattr(renderer, "_hidpi_degraded_marker", True)
            return renderer
        except (RenderError, pygame.error) as e2:
            raise GraphicsUnavailableError(
                f"图形环境初始化失败: {e2}",
                suggestion="请检查：1. 显示器已连接；2. SDL2 库已安装（Linux: apt install libsdl2-dev）；3. 显卡驱动版本正常",
            ) from e2


def _check_platform_version() -> None:
    """G4-2 新增：平台版本检查（非致命，仅 stderr warning）。

    最低版本要求：
      - macOS 12 (Monterey)
      - Windows 10

    低于最低版本时触发 PlatformUnsupportedWarning，但不退出。
    尽力兼容（用户可在"已知限制"小节查看）。
    """
    import platform as platform_mod

    system = platform_mod.system()
    if system == "Darwin":
        mac_ver = platform_mod.mac_ver()[0]
        try:
            major = int(mac_ver.split(".")[0])
            if major < 12:
                warnings.warn(
                    f"macOS {mac_ver} 低于最低要求 12.0，可能存在兼容性问题",
                    PlatformUnsupportedWarning,
                    stacklevel=2,
                )
        except (ValueError, IndexError, AttributeError):
            pass
    elif system == "Windows":
        win_ver = platform_mod.win32_ver()[1]
        try:
            major = int(win_ver.split(".")[0])
            if major < 10:
                warnings.warn(
                    f"Windows {win_ver} 低于最低要求 10，可能存在兼容性问题",
                    PlatformUnsupportedWarning,
                    stacklevel=2,
                )
        except (ValueError, IndexError, AttributeError):
            pass
    # Linux 不做版本检查（发行版碎片化严重，最低版本意义不大）


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
        G3-1 iter-3 新增 _skin_index=0（皮肤循环索引，默认经典 skin_names()[0]）。
        G3-3 iter-3 新增 _prev_snap=None（r2-1 修订：step 前保存；r2-3 修订：_new_game 重置）。
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
        # ---- iter-3 增量（G3-1/G3-3）----
        self._skin_index: int = 0  # G3-1：皮肤循环索引（默认经典）；r2-4 文档修订
        self._prev_snap: Optional[Snapshot] = None  # G3-3：上一节拍前快照
        # ---- iter-4 增量（G4-2）----
        self._last_error: Optional["AppError"] = None  # G4-2：最后一次捕获的 AppError
        self._hidpi_degraded: bool = False  # G4-2：HiDPI 降级后标志（INV-18）
        self._cjk_font_fallback: bool = False  # G4-5：CJK 字体回退后标志（INV-19）
        # 删除 _pause_hint_shown（G2-1 INV-8）
        # CJK 字体（_init_pygame 内构造）
        self._menu_title_font: Optional[pygame.font.Font] = None
        self._menu_body_font: Optional[pygame.font.Font] = None
        self.clock: Optional[pygame.time.Clock] = None

    # ---- 公开入口 ----

    def run(self) -> int:
        """主循环。返回进程退出码（0 正常 / 1 异常 / 2 图形环境不可用 / 3 用户数据目录不可写）。

        迭代 4 增量（G4-2 NFR-03）：
        - StorageUnavailableError → 退出码 3（区分于一般 AppError 的 1）
        - GraphicsUnavailableError / StorageUnavailableError 的 suggestion 字段写入 stderr
        - 仍保留 R3-15 兜底：退出码 2/3 路径也尝试 renderer.shutdown()
        """
        self._renderer = None
        try:
            try:
                self._init_pygame()
            except GraphicsUnavailableError as e:
                # G4-2 修订：写入 suggestion 字段（INV-17）
                msg = f"[错误] 无法初始化图形界面: {e}"
                if e.suggestion:
                    msg += f"\n建议: {e.suggestion}"
                print(msg, file=sys.stderr)
                return 2
            except StorageUnavailableError as e:
                # G4-2 新增退出码 3
                msg = f"[错误] 用户数据目录不可写: {e}"
                if e.suggestion:
                    msg += f"\n建议: {e.suggestion}"
                print(msg, file=sys.stderr)
                return 3
            except ConfigError as e:
                print(f"[错误] 配置非法: {e}", file=sys.stderr)
                return 1
            except AppError as e:
                print(f"[错误] app 异常: {e}", file=sys.stderr)
                return 1
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
        """构造 renderer + HighScoreStore；CJK 字体回退链 + HiDPI 降级 + 平台检查。

        R3-10：App.__init__ 不构造 Renderer / HighScoreStore，_init_pygame 内才赋值。
        R3-12：CJK 字体走回退链构造 _menu_title_font / _menu_body_font。
        失败时 RenderError / pygame.error → GraphicsUnavailableError。
        G2-2：HighScoreStore 构造在 _init_pygame 内；mkdir 失败抛 (StorageError, OSError) → AppError。
        P1-3：_storage = None 时由 fixture 注入 fake；构造前 `if self._storage is None:` 跳过 create_storage。
        G3-4 iter-3 增量：构造 Renderer 时根据 config 类型判定 enable_high_dpi（NFR-04 高分屏清晰）：
            - isinstance(config, AppConfigV3) → enable_high_dpi=config.enable_high_dpi
            - 否则（AppConfig 或其子类无 enable_high_dpi）→ enable_high_dpi=True（默认）
        r2-2 契约前置：Renderer.__init__ 内部必须带 pygame.RESIZABLE 标志（FR-09 VIDEORESIZE 事件源）。

        迭代 4 增量（G4-2）：
        - 平台版本检查（macOS <12 / Windows <10）→ PlatformUnsupportedWarning，非致命
        - HiDPI 降级包装：try enable_high_dpi=True → 失败降级到 False + HighDPIWarning + _hidpi_degraded=True
        - HiDPI 降级也失败 → GraphicsUnavailableError 退出码 2
        - StorageUnavailableError 退出码 3（区分于一般 AppError 退出码 1）
        """
        # G4-2 新增：平台版本检查（非致命，仅 stderr warning）
        _check_platform_version()

        # G3-4：构造 Renderer（enable_high_dpi 判定 + G4-2 HiDPI 降级）
        enable_high_dpi = True  # 默认（NFR-04）
        if isinstance(self.config, AppConfigV3):
            enable_high_dpi = self.config.enable_high_dpi
        self._renderer = _create_renderer_with_hidpi_fallback(
            window_size=(self.config.window_w, self.config.window_h),
            skin=DEFAULT_SKIN,
            enable_high_dpi=enable_high_dpi,
        )
        # G4-2 INV-18：HiDPI 降级后置 _hidpi_degraded=True
        if getattr(self._renderer, "_hidpi_degraded_marker", False):
            self._hidpi_degraded = True

        # G2-2：构造 HighScoreStore（P1-3 已注入 fake 则跳过；P1-1 捕获双类型）
        if self._storage is None:
            try:
                self._storage = create_storage()
                self._high_score = self._storage.load()
            except (StorageError, OSError) as e:
                # G4-2 修订：抛 StorageUnavailableError（退出码 3 而非 1）
                raise StorageUnavailableError(
                    f"用户数据目录不可写: {e}",
                    suggestion="请检查 ~/.local/share (Linux) / ~/Library/Application Support (macOS) / %APPDATA% (Windows) 目录权限；或清理磁盘空间",
                ) from e

        # G4-5 修订：CJK 字体回退链（优先打包内置文件）
        # 跟踪 CJKFontFallbackWarning 触发（INV-19）—— 全失败时 _cjk_font_fallback=True
        from .errors import CJKFontFallbackWarning
        with warnings.catch_warnings(record=True) as wlist:
            warnings.simplefilter("always")
            self._menu_title_font = _load_cjk_font(48, bold=True)
            self._menu_body_font = _load_cjk_font(22)
        self._cjk_font_fallback = any(
            issubclass(w.category, CJKFontFallbackWarning) for w in wlist
        )

        self.clock = pygame.time.Clock()

    def _run_loop(self) -> int:
        """主事件循环。G2-1：screen==PAUSED 跳过 _tick（INV-10）。

        G2-R-N2 修订：主循环 `while True`（不读 _running，保留字段供 iter-3 用）。

        迭代 4 增量（G4-2）：通过 error_to_exit_code() 统一映射退出码——
        score_callback 抛 StorageUnavailableError 时返 3（而非旧版兜底的 1）。
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
        except AppError as e:  # G2-2 + G4-2
            from .errors import error_to_exit_code
            print(f"[错误] {e}", file=sys.stderr)
            return error_to_exit_code(e)

    def _drain_events(self) -> List[InputAction]:
        """本帧所有 pygame 事件归一化；QUIT 优先 break；G2-4 失焦追加 UNFOCUS；G2-7 GAME_OVER 态 ESC 覆盖。

        R3-1 屏态兜底（不变）：MENU 屏态下所有 action（除保留键外）→ START。
        G2-4 新增：screen==PLAYING 时 pygame.key.get_focused() == False → 追加 UNFOCUS。
        G2-7 / P1-2 修订：screen==GAME_OVER 时 ESCAPE → BACK_TO_MENU（仅 ESC 转，Q 保持 QUIT 直通 break）。

        迭代 3 增量（G3-1/G3-2）：
        - G3-2：VIDEORESIZE 事件在循环内**同步处理**（调 Renderer.handle_resize），
          然后**不**进入 actions 列表（不入 dispatch）。r2-2 契约前置：Renderer 窗口
          必须带 RESIZABLE 标志（pygame 产生 VIDEORESIZE 事件源）。
        - G3-1：SET_SKIN_PREV/NEXT 在 MENU 态**同步处理**（调 Renderer.set_skin +
          更新 _skin_index），然后**不**进入 actions 列表（不入 dispatch）；其他屏态
          （PLAYING/PAUSED/GAME_OVER）透传为 MOVE_LEFT/MOVE_RIGHT（保持对局控制，FR-10）。
        """
        raw = pygame.event.get()
        actions: List[InputAction] = []
        for ev in raw:
            action = _map_event(ev)
            # G3-2 增量：VIDEORESIZE 同步处理（不入 actions）
            if action == InputAction.RESIZE:
                self._handle_resize(ev)  # 见下方 RenderError 兜底
                continue
            # G3-1 增量：SET_SKIN_PREV/NEXT 按屏态分发
            if action in (InputAction.SET_SKIN_PREV, InputAction.SET_SKIN_NEXT):
                if self.screen == AppScreen.MENU:
                    # MENU 态：同步处理皮肤切换
                    self._switch_skin(direction=action)
                    continue  # 不入 actions
                else:
                    # 其他屏态（PLAYING/PAUSED/GAME_OVER）：透传为 MOVE_LEFT/MOVE_RIGHT
                    action = (InputAction.MOVE_LEFT if action == InputAction.SET_SKIN_PREV
                              else InputAction.MOVE_RIGHT)
            # R3-1 屏态兜底（不变）+ ESC 覆盖（G2-7 / P1-2）
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

    def _switch_skin(self, direction: InputAction) -> None:
        """G3-1：皮肤切换（仅 MENU 态调用）。

        步骤：
        1. 调 Renderer.skin_names() 获当前注册表所有皮肤名 tuple
        2. 计算新索引：(direction==SET_SKIN_PREV) ? (_skin_index - 1) % len : (_skin_index + 1) % len
        3. 调 self._renderer.set_skin(skin_names[new_index])
        4. 更新 self._skin_index = new_index
        5. SkinNotFoundError 兜底：理论上不会发生（skin_names() 返注册表内的所有 key），
           但若 set_skin 抛 SkinNotFoundError（防御），维持 _skin_index 不变 + stderr 提示

        r2-4 修订：皮肤名派生统一用 skin_names()[_skin_index]，不再引用不存在的 SKIN_REGISTRY_NAMES。
        """
        assert self._renderer is not None, "MENU 态 _renderer 必须已 init"
        skin_names = self._renderer.skin_names()
        if not skin_names:
            return  # 防御：注册表为空不切
        if direction == InputAction.SET_SKIN_PREV:
            new_index = (self._skin_index - 1) % len(skin_names)
        else:  # SET_SKIN_NEXT
            new_index = (self._skin_index + 1) % len(skin_names)
        try:
            self._renderer.set_skin(skin_names[new_index])
            self._skin_index = new_index
        except SkinNotFoundError as e:
            # 理论不可达（skin_names() 返注册表内的所有 key）；防御性 stderr 提示
            print(f"[警告] 切换皮肤失败: {e}", file=sys.stderr)

    def _handle_resize(self, event: Any) -> None:
        """G3-2：窗口缩放处理（_drain_events 内同步调用，r2-2 契约前置）。

        步骤：
        1. 调 self._renderer.handle_resize(event.w, event.h)
        2. RenderError 兜底（< MIN_PLAYABLE_W/H 或类型错误）：
           stderr 提示 + 不更新（renderer 内部维持原尺寸）—— 不抛异常，不退游戏

        r2-2 契约前置：Renderer 窗口必须带 RESIZABLE 标志，否则 pygame 不产生 VIDEORESIZE 事件，
        此函数仅在真窗口拖拽缩放时被调用；UT 注入 fake 事件时仍可达。
        """
        assert self._renderer is not None, "_handle_resize 前 renderer 必须 init"
        try:
            self._renderer.handle_resize(event.w, event.h)
        except RenderError as e:
            # G3-2 兜底：尺寸过小/类型错误 → stderr 提示 + 维持当前尺寸（不抛、不退）
            # INV-15（新增）：缩放失败不中断游戏
            print(f"[警告] 窗口缩放失败: {e}", file=sys.stderr)

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

        迭代 3 增量（G3-3，**r2-3 修订**）：
        - 首行 `self._prev_snap = None`（新局首帧瞬移渲染，防御新局开局蛇身漂移）
        """
        self._prev_snap = None  # r2-3 修订：新局首帧不读残留快照，防御蛇身漂移
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

        迭代 3 增量（G3-3，**r2-1 全链修订**）：
        - step 前 snapshot 保存到 self._prev_snap（用于下一帧 _render 构造 InterpolationState 的 prev_snake_body，旧位置）
        - step 后 self.game_state = self.game_state.step()
        - OVER 后 self._prev_snap = None（_render GAME_OVER 不读）
        - PAUSED 态不进入此函数；_prev_snap 不变

        **r2-1 关键修订说明**：
        - 旧版（r1 错）写法：step 后写 self._prev_snap = self.game_state.snapshot() → prev 与 cur 恒相等 → 插值无效
        - 新版（r2-1 正）写法：step 前写 self._prev_snap = self.game_state.snapshot() → prev = step 前（旧）位置，cur = step 后（新）位置 → 插值有效
        - alpha 公式（r2-1 修订）：alpha = (_tick_accumulator_ms % tick_ms) / tick_ms
          - step 刚完成（elapsed≈0）→ alpha≈0.0 → 显示 prev（旧位置）
          - 节拍推进（elapsed→tick_ms）→ alpha→1.0 → 显示 cur（新位置）—— 蛇从旧位置滑向新位置，连续
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
            # **r2-1 修订**：step 前 snapshot 保存到 _prev_snap（用于下一帧 _render 插值的 prev）
            self._prev_snap = self.game_state.snapshot()
            self.game_state = self.game_state.step()
            new_status = self.game_state.status
            if new_status == GameStatus.OVER:
                self.screen = AppScreen.GAME_OVER
                self._prev_snap = None  # G3-3：OVER 态 _prev_snap 清空（_render GAME_OVER 不读）
                break
            # **r2-1 修订**：step 后不再写 _prev_snap（仅 step 前写一次，下一帧 _render 读）

    def _interpolation_state(self, snap: Snapshot) -> Optional[InterpolationState]:
        """G3-3 构造 InterpolationState（仅 PLAYING 路径调用）；r2-1/r2-3/r2-6/r2-7 修订。

        返回：
        - 若 _prev_snap is None → 返回 None（首帧 / OVER 后 / 新局首帧——r2-3 修订 _new_game 已重置；
          Renderer 走瞬移渲染）
        - 若 _prev_snap.snake_body 与 snap.snake_body **Chebyshev 距离 > 1 格** → 返回 None
          （r2-3 修订：实现真实距离防御 max(|dx|, |dy|) > 1，与 renderer 内部 _grid_distance 一致；
          防御吃食节拍/蛇身跳变/新局残留快照——消除原 docstring "距离 > 1 格" 与实现 "仅长度检查" 的偏差）
        - 若 len(prev_body) != len(cur_body) → 返回 None（吃食节拍防御——r2-7 修订：app 侧选择
          更保守防御，prev_food=None 语义由 renderer 单独兜底）
        - 否则返回 InterpolationState(alpha, prev_snake_body, prev_food)
          - alpha = (_tick_accumulator_ms % tick_ms) / tick_ms  **r2-1 修订**：已消费时长占整节拍比例
            → step 完成后 elapsed=0 → alpha=0（显示 prev 旧位置）
            → elapsed→tick 时 alpha=1（显示 cur 新位置，连续）
            → clip [0, 1]
          - prev_snake_body = tuple((p.x, p.y) for p in _prev_snap.snake_body)
          - prev_food = (_prev_snap.food.x, _prev_snap.food.y)  # r2-7 修订：始终传 prev_food
            （renderer 内部处理 prev_food=None 语义：吃食节拍食物瞬移）
        """
        # r2-6 修订：删除冗余 self.game_state is None 检查（调用点 _render PLAYING 已 assert）
        if snap is None:
            return None  # 防御性 snap 参数检查
        if self._prev_snap is None:
            return None
        # r2-3 修订：真实 Chebyshev 距离防御（消除 docstring 与实现偏差）
        prev_body = self._prev_snap.snake_body
        cur_body = snap.snake_body
        if len(prev_body) != len(cur_body):
            return None  # 蛇身长度变化（吃食）→ renderer 兜底（r2-7：更保守防御）
        # r2-3 修订：蛇身逐节 Chebyshev 距离 > 1 → 跳变，不插值
        for prev_pt, cur_pt in zip(prev_body, cur_body):
            dx = abs(prev_pt.x - cur_pt.x)
            dy = abs(prev_pt.y - cur_pt.y)
            if dx > 1 or dy > 1:
                return None  # 跳变，不插值（防御新局残留快照等异常）
        # alpha 计算（r2-1 修订：与 _tick 循环内重读 tick_ms 一致——避免漂移）
        tick_ms = snap.tick_ms
        if tick_ms <= 0:
            return None  # 防御：tick_ms 异常
        elapsed_in_tick = self._tick_accumulator_ms % tick_ms
        alpha = elapsed_in_tick / tick_ms  # r2-1 修订：不再是 1.0 - elapsed / tick_ms
        alpha = max(0.0, min(1.0, alpha))  # clip
        return InterpolationState(
            alpha=alpha,
            prev_snake_body=tuple((p.x, p.y) for p in prev_body),
            prev_food=(self._prev_snap.food.x, self._prev_snap.food.y),  # r2-7 修订：始终传 prev_food
        )

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
            # G3-5 iter-3 增量：从 Renderer 公开属性读当前皮肤名（r2-4 修订：不读 _skin 私有）
            current_skin = self._renderer.current_skin_name if self._renderer else "classic"
            draw_menu(  # G3-5 加 current_skin_name
                surface,
                self._menu_title_font,
                self._menu_body_font,
                self._difficulty,
                high_score=self._high_score,
                current_skin_name=current_skin,
            )
        elif self.screen == AppScreen.PLAYING:
            assert self._renderer is not None
            snap = self.game_state.snapshot()  # R3-11：取一次 snap
            hud = self._build_hud(snap)
            # G3-3 + r2-1：构造 InterpolationState 走平滑插值（alpha = elapsed/tick_ms）
            interp = self._interpolation_state(snap)
            self._renderer.render(snap, hud, interp=interp)
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