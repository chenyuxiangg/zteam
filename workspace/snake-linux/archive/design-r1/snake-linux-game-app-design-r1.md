# 功能模块设计：game-app（snake-linux v2.0.0 迭代 1）

> MDE 首发产出 · 严格对齐架构 `snake-linux/arch/v2.0.0/架构设计.md`、分工表 `snake-linux/arch/v2.0.0/功能模块分工表.md`、需求规格 `snake-linux/analysis/snake-gui-r1.md`（R-01~R-09 用户拍板已固化）
> 依赖模块：game-core（迭代 1 已 it_passed）、gui-renderer（迭代 1 已 it_passed）、platform-storage（迭代 2 接入，本迭代不调用）
> **迭代 1 范围 = 最小时可玩闭环**（主循环 + 输入 + 开始/结束/重开/退出 + 难度选择最小集），对齐分工表 §迭代计划出口：FR-01~04 + FR-11（开始/重开/退出）+ FR-05 难度选择入口
> **迭代 2/3/4 增量**（本设计**不实现**，仅留接口与扩展点预告）：暂停/继续、最高分展示/重置（FR-12/FR-13）、皮肤切换 UI（FR-10）、三平台打包（FR-14/15）、用户指南（FR-16）、可读错误提示（NFR-03）、性能调优（NFR-01/02）
> **目标**：FO 拿到本文即可 TDD 开发，UT 框架明确

---

## 0. 模块定位与迭代边界

| 项 | 值 |
|----|---|
| 模块 | game-app |
| 类型 | 上层应用 |
| 依赖 | game-core（纯逻辑，零 GUI）、gui-renderer（pygame 渲染，迭代 1 已 it_passed）、platform-storage（迭代 2 接入） |
| 被依赖 | 无（顶层装配） |
| 承载需求 | snake-gui **主体**（FR-01~16 中除 gui-renderer 子集外的全部）—— 本迭代 1 范围 = FR-01~05 玩法闭环入口 + FR-11 开始/结束/重开/退出 |
| 迭代 | 1（首发） |
| 不引入 | 第三方除 pygame 外任何依赖；不引入音效（架构 §R-04）；不引入网络（NFR-06）；不引入 config 文件（架构 §配置模型）；不写系统目录（便携式，NFR-07） |
| 跨迭代复用 | 主循环骨架 / 界面状态机 / 输入映射 / 错误处理框架 跨 4 迭代复用；迭代 2/3 通过**新增状态节点与处理函数**接入，不重写主循环 |
| PyInstaller 入口 | `snake-gui.py`（包根 `__main__.py`，`if __name__ == "__main__": main()`） |

### 迭代 1 出口（与架构 §迭代计划 对齐）

- ✅ 主事件循环（pygame 帧驱动，clock.tick 60FPS）
- ✅ 输入映射（WASD/方向键 → core.set_direction；P/ESC 迭代 1 仅占位为"按 P 显示 'Pause (iter 2)' 提示文字"；Q 退出）
- ✅ 界面状态机：`MENU` → `PLAYING` → `GAME_OVER` →（重开 → `PLAYING` / 退出）
- ✅ 开始界面：标题 + "按任意键开始" + 难度选择（EASY/MEDIUM/HARD 通过 1/2/3 键 + 方向键 + Enter 确认）
- ✅ 游戏 HUD：得分 + 长度（最高分占位"---"，迭代 2 接入）
- ✅ 结束画面：最终得分 + "重开 (R) / 退出 (Q)"
- ✅ 退出 1 秒内无残留进程（FR-11，pygame.quit() + sys.exit 显式调用）
- ✅ 帧率 ≥ 60 FPS（pygame clock 兜底）
- ❌ 暂停/继续（FR-12，迭代 2）
- ❌ 最高分持久化（FR-13，迭代 2）
- ❌ 皮肤切换 UI（FR-10，迭代 3）
- ❌ 窗口缩放（FR-09，迭代 3）
- ❌ 平滑动画（FR-07，迭代 3）
- ❌ 三平台打包（FR-14/15，迭代 4）
- ❌ 完善错误提示（NFR-03，迭代 4）

### 迭代 1 已知技术约束（FO 实现必读）

1. **Python 3.8 兼容**：与架构 §代码风格约定一致，不使用 dataclass 自定义 `__setattr__` 之外的 3.9+ 特性；`Optional[X]` / `Tuple[X, ...]` 而非 `X | None` / `tuple[X, ...]`。
2. **零配置**：不读 ini/env/YAML/JSON 配置；难度/皮肤通过游戏内 UI 选择（皮肤迭代 1 仅经典单套，迭代 3 扩展）。
3. **无网络**：全模块不 `import socket` / `import urllib` / `import http` / `import requests`；UT 不发起网络（mocket 都不需要）。
4. **无音效**：不 `import pygame.mixer` 或任何音频模块。
5. **依赖边界**：game-app **可** import pygame（用于事件循环与窗口）；**不可**侵入 game-core 内部（仅通过 game-core 的公开 API：`Point`/`Direction`/`Difficulty`/`GameStatus`/`GameState`/`Snapshot`/`InvalidStateError`）；**不可**直接改 gui-renderer 内部状态（通过 `Renderer(skin_name).render(snapshot)` 调用）。
6. **platform-storage 迭代 1 不导入**：`import platform_storage` 不出现在迭代 1 代码中；最高分变量名 `high_score` 留位但赋值为 `0` 占位，迭代 2 接入。

---

## 数据结构

### 1.1 界面状态枚举（app 层级，独立于 core 的 GameStatus）

| 类型 | 字段 | 说明 |
|------|------|------|
| `AppScreen`（Enum） | `MENU` / `PLAYING` / `GAME_OVER` | app 顶层界面状态机；迭代 1 三态；`PAUSED` 枚举先占位但不允许进入（迭代 2 接入） |
| `InputAction`（Enum） | `QUIT` / `START` / `MOVE_UP` / `MOVE_DOWN` / `MOVE_LEFT` / `MOVE_RIGHT` / `TOGGLE_PAUSE` / `RESTART` / `SELECT_EASY` / `SELECT_MEDIUM` / `SELECT_HARD` | 输入归一化结果，pygame 事件 → InputAction 映射（详见 §3.3） |
| `AppConfig`（dataclass, frozen） | `window_w: int = 800` / `window_h: int = 600` / `fps_cap: int = 60` / `min_window_w: int = 480` / `min_window_h: int = 360` | 不可变运行期常量；迭代 1 硬编码默认值，迭代 3 接入窗口缩放时再扩字段 |

### 1.2 难度选择状态（菜单内子状态）

| 类型 | 字段 | 说明 |
|------|------|------|
| `MenuCursor`（Enum） | `START` / `EASY` / `MEDIUM` / `HARD` / `QUIT` | 菜单高亮项；↑/↓ 移动，Enter 确认 |
| `_selected_difficulty: Difficulty` | `class 内部 state` | 菜单态当前选中难度（默认 `Difficulty.MEDIUM`），按 Enter 后写入新 `GameState` |

### 1.3 运行期状态（app 内部 mutable state，不暴露给 core）

| 字段 | 类型 | 说明 |
|------|------|------|
| `screen: AppScreen` | 当前界面 | 初始 `MENU` |
| `difficulty: Difficulty` | 当前局难度 | 初始 `MEDIUM`；从菜单选好后固化到 `GameState`（**游戏中不可改**，对齐 FR-05） |
| `game_state: GameState` | 玩法状态 | 首次开局时由 `_new_game(difficulty)` 构造；`GAME_OVER` 时保留展示 |
| `renderer: Renderer` | 渲染器 | 迭代 1 构造时皮肤固定 `"classic"`；迭代 3 接受 `skin_name` 参数 |
| `clock: pygame.time.Clock` | 帧率控制 | `clock.tick_busy_loop(fps_cap)` |
| `high_score: int` | 最高分占位 | 迭代 1 写死 0，HUD 展示"---"；迭代 2 替换为 `HighScoreStore(...).load()` |
| `_tick_accumulator_ms: int` | 内部节拍累计 | 累加 frame 间隔，达到 `tick_ms` 时调 `game_state.step()` 一次；防止 pygame 时钟抖动导致节拍漂移 |

### 1.4 不变量清单（FO 实现必须保证，UT 也要覆盖）

| ID | 不变量 |
|----|--------|
| INV-1 | `screen == PLAYING` 时 `game_state.status == GameStatus.RUN`（不在 PLAYING 态持有 OVER 状态） |
| INV-2 | `screen == GAME_OVER` 时 `game_state.status == GameStatus.OVER` |
| INV-3 | 难度 `Difficulty` 选定后写入 `game_state.difficulty`，运行中**无接口**可改（`set_difficulty` 显式 raise `NotImplementedError`，迭代 1 文档约束） |
| INV-4 | `_tick_accumulator_ms >= game_state.snapshot().tick_ms` 时必调 `step()`，调后减 `tick_ms`（不丢节拍） |
| INV-5 | 退出主循环后 `pygame.quit()` 必被调用 1 次，进程退出码 0（FR-11，1 秒内无残留） |
| INV-6 | `high_score` 在迭代 1 = 0（占位），HUD 渲染"---"字符串而非数字 0 |

---

## 数据传递方式

### 2.1 模块边界与数据流

```
                 ┌──────────────────────────────┐
   键盘事件 ───▶ │  InputMap: pygame.event →    │ ──▶ InputAction (Enum)
                 │       InputAction             │
                 └──────────────────────────────┘
                            │
                            ▼
   ┌────────────────────────────────────────────────────────┐
   │  主循环 (Main Loop, run())                              │
   │   1. clock.tick(fps_cap) → dt_ms                       │
   │   2. drain_events() → InputAction 流                    │
   │   3. dispatch(screen, action):                         │
   │      - MENU: 调整 difficulty cursor / 确认 → new_game  │
   │      - PLAYING: core.set_direction / step 节拍         │
   │      - GAME_OVER: R 重开 / Q 退出                      │
   │   4. if screen==PLAYING:                                │
   │        _tick_accumulator_ms += dt_ms                   │
   │        while _tick_accumulator_ms >= tick_ms:          │
   │            game_state = game_state.step()              │
   │            _tick_accumulator_ms -= tick_ms             │
   │            if game_state.status==OVER: screen=GAME_OVER│
   │   5. snapshot = game_state.snapshot()                  │
   │   6. renderer.render(snapshot, hud={...})               │
   └────────────────────────────────────────────────────────┘
                            │
                ┌───────────┼───────────┐
                ▼           ▼           ▼
            game-core   gui-renderer  (platform-storage 迭代 2 接入)
```

### 2.2 模块间参数

| 方向 | 路径 | 类型 |
|------|------|------|
| app → core | `_new_game(difficulty) -> GameState` | `Difficulty` → `GameState` |
| app → core | `game_state.set_direction(direction)` | `Direction` |
| app → core | `game_state.step()` | 无参 → `GameState`（新对象） |
| app → core | `game_state.toggle_pause()` | 无参 → `GameState`（迭代 1 **不调用**，仅 import 占位，迭代 2 用） |
| app → core | `game_state.snapshot()` | 无参 → `Snapshot`（值对象） |
| app → renderer | `Renderer("classic").render(snapshot, hud)` | `Snapshot` + `HUDDict` |
| app → renderer | `Renderer("classic").set_skin(name)` | `str`（迭代 1 接受但仅 `"classic"` 生效；迭代 3 扩展） |
| core → app | `InvalidStateError`（异常传播） | 仅 OVER/PAUSED 调 set_direction/step 时抛，app 捕获后 log + 退出（迭代 1 应不可达，加 UT 覆盖） |
| 迭代 2 接入 | app → storage | `HighScoreStore(path).load() / .save(score) / .reset()` |

### 2.3 存储 / 共享状态

- **进程内单例**：app 状态（`screen` / `difficulty` / `game_state` / `high_score`）全部活在 `App` 类的实例字段，**无全局变量**（除 pygame 自身必要的 `pygame.init()` 全局副作用）。
- **进程间无共享**：无 IPC、无 socket、无文件锁。
- **磁盘写入**：迭代 1 写 0 字节（不创建任何文件）；迭代 2 通过 `platform_storage.get_user_data_dir()` + `HighScoreStore` 落 `highscore.json`。

---

## 对外接口

### 3.1 `AppConfig`（dataclass, frozen）

```python
@dataclass(frozen=True)
class AppConfig:
    """FR-09/NFR-01/NFR-02 迭代 1 固定值。"""
    window_w: int = 800        # 窗口初始宽（px）
    window_h: int = 600        # 窗口初始高（px）
    fps_cap: int = 60          # NFR-01 帧率目标
    min_window_w: int = 480    # 迭代 3 缩放下限（迭代 1 文档占位，pygame 实际允许 0）
    min_window_h: int = 360    # 迭代 3 缩放下限
```

### 3.2 `AppScreen`（Enum）

```python
class AppScreen(Enum):
    """app 顶层界面状态机。FR-11 + FR-12 入口。"""
    MENU = "menu"          # 开始 + 难度选择
    PLAYING = "playing"    # 玩法循环
    GAME_OVER = "over"     # 结束 + 重开/退出
    # PAUSED = "paused"   # 迭代 2 启用；迭代 1 保留枚举值但 dispatch 不处理
```

### 3.3 `InputAction`（Enum）

```python
class InputAction(Enum):
    """pygame 事件归一化结果。FO 只需实现 _map_event() 即可。"""
    QUIT = "quit"
    START = "start"             # MENU 态：任意键 → PLAYING
    MOVE_UP = "up"
    MOVE_DOWN = "down"
    MOVE_LEFT = "left"
    MOVE_RIGHT = "right"
    TOGGLE_PAUSE = "pause"      # 迭代 1 触发"按 P 提示"；迭代 2 实际切 PAUSED
    RESTART = "restart"         # GAME_OVER 态：R 键
    SELECT_EASY = "sel_easy"    # MENU 态：1 / ↑
    SELECT_MEDIUM = "sel_med"   # MENU 态：2
    SELECT_HARD = "sel_hard"    # MENU 态：3 / ↓
    SELECT_QUIT = "sel_quit"    # MENU 态：Q / ESC
```

### 3.4 `App` 主类

```python
class App:
    """snake-gui 顶层装配；PyInstaller 入口。"""

    def __init__(self, config: AppConfig = AppConfig()) -> None:
        """初始化 pygame（display.set_mode / clock），构造经典皮肤 renderer，
        初始 screen=MENU, difficulty=MEDIUM, game_state=None（首次开局时构造）。"""

    def run(self) -> int:
        """主循环。返回进程退出码（0 正常 / 1 异常 / 2 图形环境不可用）。"""

    # --- 内部接口（供 UT 注入 / 桩替，不导出给 core/renderer） ---

    def _drain_events(self) -> List[InputAction]: ...
        """本帧所有 pygame 事件归一化为 InputAction 列表。"""

    def _dispatch(self, action: InputAction) -> None:
        """按当前 screen 分发：MENU 改 cursor / 确认开新局；PLAYING 推方向 / 暂停占位；GAME_OVER 重开 / 退出。"""

    def _new_game(self, difficulty: Difficulty) -> None:
        """构造新 GameState；game_state = GameState(20, 15, difficulty, rng=Random())；screen=PLAYING。"""

    def _tick(self, dt_ms: int) -> None:
        """累加 dt_ms 到 _tick_accumulator_ms；while >= tick_ms 调 step()；OVER 自动转 GAME_OVER。"""

    def _render(self) -> None:
        """renderer.render(snapshot, hud={"score":..,"length":..,"high_score":..,"difficulty":..})；pygame.display.flip()。"""

    def _build_hud(self) -> dict:
        """构造 HUD dict（迭代 1：score/length/difficulty/high_score 字符串占位）。"""
```

### 3.5 公开 API 列表（供 FO 实现核对）

| 名称 | 类型 | 用途 |
|------|------|------|
| `AppConfig` | dataclass(frozen) | 运行期常量 |
| `AppScreen` | Enum | app 界面状态机 |
| `InputAction` | Enum | 输入归一化 |
| `App` | class | 主装配类 |
| `main()` | function | 入口函数：`App().run()`，捕获 `AppError` 后输出可读提示 + 退出码 |

### 3.6 异常

```python
class AppError(RuntimeError):
    """app 顶层错误基类。"""

class GraphicsUnavailableError(AppError):
    """pygame.display.set_mode 失败（无图形环境 / 驱动异常）→ 退出码 2，对齐 NFR-03。"""

class ConfigError(AppError):
    """AppConfig 字段非法（如 fps_cap <= 0）→ 启动时抛。"""
```

---

## 实现细节/步骤

### 4.1 模块文件组织

```
game_app/
├── __init__.py             # 对外 re-export: App, AppConfig, main, AppScreen, InputAction, AppError
├── __main__.py             # `from game_app import main; sys.exit(main())` —— PyInstaller 入口
├── config.py               # AppConfig
├── screens.py              # AppScreen, MenuCursor
├── input.py                # InputAction, _map_event(event) -> Optional[InputAction]
├── app.py                  # App 类
├── errors.py               # AppError, GraphicsUnavailableError, ConfigError
└── _constants.py           # WINDOW_TITLE="Snake GUI v2.0.0"、MENU_ITEMS 列表等

tests/
└── test_game_app/
    ├── __init__.py
    ├── conftest.py                 # 共享 fixture：App 实例、注入 fake pygame（pygame 桩见 §6.2）
    ├── test_config.py              # AppConfig 默认值 + frozen 性质
    ├── test_input_map.py           # 事件 → InputAction 映射
    ├── test_app_init.py            # 构造 App 不开窗口（注入桩）
    ├── test_app_menu.py            # MENU 态：cursor 移动、Enter 开局
    ├── test_app_playing.py         # PLAYING 态：方向输入、节拍 step、撞墙/撞身自动转 GAME_OVER
    ├── test_app_game_over.py       # GAME_OVER 态：R 重开 / Q 退出
    ├── test_app_tick.py            # 节拍累加 + 多次 step 在一帧内执行
    ├── test_app_exit.py            # 退出主循环 + pygame.quit 调用次数
    ├── test_app_error.py           # 图形环境不可用 → GraphicsUnavailableError → 退出码 2
    └── test_app_hud.py             # HUD dict 字段齐全 + high_score 字符串"---"
```

### 4.2 主循环骨架（`_run_loop` 内部伪码）

```python
def run(self) -> int:
    try:
        self._init_pygame()        # 失败抛 GraphicsUnavailableError
    except GraphicsUnavailableError as e:
        print(f"[错误] 无法初始化图形界面: {e}\n请确认系统有可用的图形环境。", file=sys.stderr)
        return 2

    try:
        while True:
            dt_ms = self.clock.tick_busy_loop(self.config.fps_cap)
            actions = self._drain_events()
            if InputAction.QUIT in actions:
                break
            for a in actions:
                if a == InputAction.QUIT:
                    break
                self._dispatch(a)
            if self.screen == AppScreen.PLAYING:
                self._tick(dt_ms)
            self._render()
        return 0
    except AppError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
    finally:
        pygame.quit()              # INV-5
```

### 4.3 输入映射（`_map_event`）

```python
# input.py
_KEY_TO_DIRECTION = {
    pygame.K_w: InputAction.MOVE_UP, pygame.K_UP: InputAction.MOVE_UP,
    pygame.K_s: InputAction.MOVE_DOWN, pygame.K_DOWN: InputAction.MOVE_DOWN,
    pygame.K_a: InputAction.MOVE_LEFT, pygame.K_LEFT: InputAction.MOVE_LEFT,
    pygame.K_d: InputAction.MOVE_RIGHT, pygame.K_RIGHT: InputAction.MOVE_RIGHT,
}

def _map_event(event: pygame.event.Event) -> Optional[InputAction]:
    if event.type == pygame.QUIT:
        return InputAction.QUIT
    if event.type == pygame.KEYDOWN:
        k = event.key
        if k in (pygame.K_q, pygame.K_ESCAPE):
            return InputAction.QUIT  # 全局 Q/ESC 一律退出（MENU 态 SELECT_QUIT 走 _dispatch 单独处理）
        if k == pygame.K_p:
            return InputAction.TOGGLE_PAUSE
        if k == pygame.K_r:
            return InputAction.RESTART
        if k == pygame.K_RETURN or k == pygame.K_SPACE:
            return InputAction.START
        if k in (pygame.K_1,):
            return InputAction.SELECT_EASY
        if k in (pygame.K_2,):
            return InputAction.SELECT_MEDIUM
        if k in (pygame.K_3,):
            return InputAction.SELECT_HARD
        if k in _KEY_TO_DIRECTION:
            return _KEY_TO_DIRECTION[k]
    return None
```

### 4.4 状态机 dispatch 表

```python
# app.py
def _dispatch(self, action: InputAction) -> None:
    if self.screen == AppScreen.MENU:
        self._dispatch_menu(action)
    elif self.screen == AppScreen.PLAYING:
        self._dispatch_playing(action)
    elif self.screen == AppScreen.GAME_OVER:
        self._dispatch_over(action)

def _dispatch_menu(self, action: InputAction) -> None:
    if action == InputAction.SELECT_EASY:
        self._difficulty = Difficulty.EASY
    elif action == InputAction.SELECT_MEDIUM:
        self._difficulty = Difficulty.MEDIUM
    elif action == InputAction.SELECT_HARD:
        self._difficulty = Difficulty.HARD
    elif action == InputAction.START:
        self._new_game(self._difficulty)
    elif action == InputAction.QUIT:
        self._quit_requested = True  # 主循环 next tick 检测到 QUIT 后 break

def _dispatch_playing(self, action: InputAction) -> None:
    if action == InputAction.MOVE_UP:
        self.game_state = self.game_state.set_direction(Direction.UP)
    elif action == InputAction.MOVE_DOWN:
        self.game_state = self.game_state.set_direction(Direction.DOWN)
    elif action == InputAction.MOVE_LEFT:
        self.game_state = self.game_state.set_direction(Direction.LEFT)
    elif action == InputAction.MOVE_RIGHT:
        self.game_state = self.game_state.set_direction(Direction.RIGHT)
    elif action == InputAction.TOGGLE_PAUSE:
        # 迭代 1 占位：仅记录到 _pause_hint_shown（渲染时显示"Pause (iter 2)"），
        # 实际 toggle_pause() 迭代 2 启用。**迭代 1 不调 game_state.toggle_pause()**。
        self._pause_hint_shown = True

def _dispatch_over(self, action: InputAction) -> None:
    if action == InputAction.RESTART:
        self._new_game(self._difficulty)
    elif action == InputAction.QUIT:
        self._quit_requested = True
```

### 4.5 节拍推进（`_tick`）

```python
def _tick(self, dt_ms: int) -> None:
    """累加节拍；当 >= tick_ms 时 step 一次；OVER 自动转 GAME_OVER。"""
    self._tick_accumulator_ms += dt_ms
    tick_ms = self.game_state.snapshot().tick_ms
    while self._tick_accumulator_ms >= tick_ms:
        self._tick_accumulator_ms -= tick_ms
        self.game_state = self.game_state.step()
        if self.game_state.status == GameStatus.OVER:
            self.screen = AppScreen.GAME_OVER
            self._pause_hint_shown = False
            break
```

### 4.6 HUD 构造（`_build_hud`）

```python
def _build_hud(self) -> dict:
    snap = self.game_state.snapshot()
    return {
        "score": str(snap.score),                  # FR-04/11 HUD
        "length": str(len(snap.snake)),            # 规格 NFR/FR-04 隐含
        "difficulty": self._difficulty.name,       # 简单/普通/困难 显示
        "high_score": "---",                       # 迭代 1 INV-6；迭代 2 替换为 str(high_score)
    }
```

### 4.7 错误处理（NFR-03 最小集，迭代 4 完善）

```python
def _init_pygame(self) -> None:
    pygame.init()
    try:
        self.screen_surface = pygame.display.set_mode(
            (self.config.window_w, self.config.window_h)
        )
    except pygame.error as e:
        raise GraphicsUnavailableError(str(e)) from e
    pygame.display.set_caption("Snake GUI v2.0.0")
    self.clock = pygame.time.Clock()
    self._renderer = Renderer("classic")  # gui-renderer 已在迭代 1 it_passed
```

### 4.8 状态机（迭代 1 子集）

```
        ┌────────┐ 任意键(START)        ┌──────────┐
        │  MENU  │ ─────────────────▶ │ PLAYING  │
        │  (选   │   _new_game(diff)   │  (节拍   │
        │  难度) │                      │   step)  │
        └────────┘                      └──────────┘
            ▲                                │
            │  R 键 (RESTART)                │ status==OVER
            │   _new_game(diff)              │  (INV-2 自动转)
            │                                ▼
            │                          ┌──────────┐
            └──────────────────────────│ GAME_OVER│
                 _new_game(diff)        │  (R/Q)   │
                                       └──────────┘
```

- Q/ESC：任意态调 `QUIT` → 主循环 `break` → `pygame.quit()` → `return 0`（INV-5）。
- P 键：PLAYING 态设 `_pause_hint_shown = True`，渲染层在 HUD 旁加"Pause (iter 2)"小字提示，**不调** `game_state.toggle_pause()`（迭代 2 启用）。

### 4.9 实现注意点

1. **无全局变量**：app 状态全部在 `App` 实例字段，UT 可通过构造多个 `App` 实例隔离测试。
2. **pygame 副作用隔离**：`pygame.init()` / `pygame.quit()` 调用次数在 UT 中通过 fake pygame 模块统计（详见 §6.2）。
3. **不直接读 game_state 内部字段**：所有访问走 `snapshot()`；修改走 `set_direction` / `step`（返回新对象）。
4. **不直接调 renderer 私有方法**：仅 `Renderer.render(snapshot, hud)` 与 `Renderer.set_skin(name)`。
5. **不引入 `time.sleep`**：所有延迟靠 `clock.tick_busy_loop(fps_cap)` + `_tick_accumulator_ms`。
6. **不 import platform_storage**：迭代 1 不调 `get_user_data_dir()` / `HighScoreStore`（对齐迭代边界）。
7. **不写任何文件**：迭代 1 进程不创建任何磁盘文件（无 log、无 config、无存档）。
8. **退出码约定**：0 正常 / 1 app 异常 / 2 图形环境不可用（NFR-03 最小集）。

---

## DFx / 可测试性 / 鲁棒性 / 韧性

### 5.1 可维护性（Maintainability）

- 每个公开类/方法有 docstring，标注对应 FR/NFR 编号（`"""FR-11 开始/重开/退出流程。NFR-03 错误处理。"""`）
- 不变量在代码中以 `# INV-N` 注释 + UT 用例双标注
- 单一职责：input.py 只管事件归一化；screens.py 只管状态机；app.py 只管装配
- 主循环 ≤ 30 行（`_run_loop`），便于一眼读完逻辑

### 5.2 可扩展性（Extensibility）

- **PAUSED 枚举先占位**：迭代 2 加 `TOGGLE_PAUSE` 处理仅需补 `_dispatch_playing` 分支与 `_render` 暂停遮罩
- **难度 UI 抽象**：`MENU_ITEMS = [...]` 列表 + cursor 索引；新增"返回主菜单"选项仅追加一项
- **HUD 构造独立函数**：迭代 2 加最高分只需改 `_build_hud` 一处
- **Renderer 皮肤参数化**：`Renderer(skin_name)` 已是字符串参数，迭代 3 扩展仅在 Renderer 内部加映射表，app 不动
- **错误处理 `_init_pygame` 集中**：迭代 4 加 SDL 驱动版本检测、HiDPI 提示仅改这一处

### 5.3 可部署性（Deployability）

- PyInstaller 单文件 `--onefile --windowed --name snake-gui --collect-submodules game_app` 即可（**迭代 1 不实际打**，但入口结构 `__main__.py → main()` 提前对齐 PyInstaller 约定）
- `game_app/` 单一包目录，PyInstaller 自动发现
- 无 C 扩展、无平台特定代码（pygame 自身跨平台，app 逻辑纯 Python）
- 入口无副作用 import（`import game_app` 不开窗、不调 `pygame.init()`，仅 `main()` 调用时才初始化）

### 5.4 可测试性（Testability）

- **pygame 依赖可桩化**：UT 通过 `monkeypatch` / `unittest.mock` 替换 `game_app.app.pygame` 模块为 fake（fake 提供 `init/quit/display/clock/event` 桩接口），UT 全部在无显示器环境运行
- **InputAction 归一化层独立**：`test_input_map.py` 单独测事件 → Action 映射，无需构造 App
- **`_tick` 纯函数**：`App` 实例化后调 `_tick(160)` 不依赖 `clock`，UT 可传任意 dt_ms 验证节拍累计与多次 step
- **`_dispatch_*` 状态机可枚举**：每态 × 每 action 可参数化（4 屏 × 12 action = 48 case 矩阵）
- **HUD 构造纯函数**：`App(...)._build_hud()` 返 dict，UT 直接断言字段
- **错误路径可触发**：`_init_pygame` 通过 fake pygame `set_mode` 抛 `pygame.error` → 测 `GraphicsUnavailableError` 传播

### 5.5 鲁棒性 / 韧性

| 场景 | 处理 |
|------|------|
| 图形环境缺失 | `set_mode` 抛 `pygame.error` → `GraphicsUnavailableError` → 退出码 2 + 人类可读 stderr（对齐 NFR-03） |
| 同一帧多事件 | `_drain_events` 返 list；主循环按序处理；QUIT 优先 break |
| 反向输入 | 透传到 `core.set_direction`；core 内静默忽略（对齐 FR-02） |
| 撞墙/撞身 | `core.step` 返回 `status=OVER`；`_tick` 检测后自动转 `GAME_OVER`（INV-2） |
| 关窗 | `pygame.QUIT` 事件 → `QUIT` action → 主循环 break（INV-5） |
| OVER 态继续按方向键 | `_dispatch_playing` 在 OVER 屏不会被调用（已转 GAME_OVER），无副作用 |
| Q/ESC 任意态 | 统一映射 `QUIT` action；主循环 next iteration 检测后 break |
| 节拍漂移 | `_tick_accumulator_ms` 用累加 + while 循环，**不丢节拍**（慢帧会追跑多次 step） |
| 配置非法（fps_cap ≤ 0） | `AppConfig.__post_init__` 抛 `ConfigError`；`main()` 捕获后 stderr + 退出码 1 |

### 5.6 错误处理矩阵

| 错误情形 | 行为 |
|----------|------|
| `pygame.init()` 失败 | 抛 `pygame.error` → 包装为 `GraphicsUnavailableError` → 退出码 2 |
| `display.set_mode` 失败 | 同上 |
| 构造 `App(fps_cap=0)` | `ConfigError`（`__post_init__` 校验） |
| 构造 `App(fps_cap<0)` | `ConfigError` |
| `App.run()` 中 `core` 抛 `InvalidStateError` | 理论上迭代 1 不可达（INV-1/2 保护）；UT 覆盖；若真发生 → `AppError` 子类包装 → 退出码 1 |
| `App.run()` 中未捕获异常 | 兜底 `except Exception` → stderr traceback + 退出码 1（迭代 4 收敛为更友好提示） |

---

## 资源评估

| 资源 | 评估 |
|------|------|
| **CPU** | 主循环单帧 O(1)：drain_events O(事件数≤10) + dispatch O(1) + step O(W·H=300) + render O(W·H)。<br>60 FPS 下 <5ms/帧，单核占用 <30%（实测以 FO profiling 为准）<br>对齐 NFR-01 ≥60FPS、NFR-02 CPU ≤10% |
| **内存** | `App` 实例 <1KB；`GameState` <1KB；`Snapshot` <5KB；`Renderer`（pygame Surface）800×600×4 字节 ≈ 1.9MB；总进程 <50MB（远低于 NFR-02 ≤300MB） |
| **存储** | 迭代 1 写 0 字节；迭代 2 写 `highscore.json` <1KB（用户数据目录） |
| **外部依赖** | pygame（≥2.0；与 gui-renderer 共享版本约束，详见 gui-renderer/设计-r1.md） |
| **线程** | 非线程安全；pygame 主循环单线程；UT 单线程跑 |
| **GIL** | 不影响（pygame 帧驱动无 I/O 阻塞，core 纯计算） |
| **打包体积** | 迭代 1 不打包；迭代 4 估算：pygame ~30MB + Python 运行时 ~10MB + app + core + renderer ~1MB = ~40MB 单文件（PyInstaller --onefile 典型值） |

---

## UT 框架（FO TDD 依据）

### 6.1 测试组织

```
tests/
└── test_game_app/
    ├── __init__.py
    ├── conftest.py                  # fake_pygame fixture、App fixture
    ├── test_config.py               # AppConfig 默认值 + frozen 性质
    ├── test_input_map.py            # pygame event → InputAction 映射
    ├── test_app_init.py             # 构造 App（注入 fake_pygame，不开真实窗口）
    ├── test_app_menu.py             # MENU 态：cursor 移动、Enter 开局
    ├── test_app_playing.py          # PLAYING 态：方向输入、节拍 step、撞墙/撞身转 GAME_OVER
    ├── test_app_game_over.py        # GAME_OVER 态：R 重开 / Q 退出
    ├── test_app_tick.py             # 节拍累加 + 多次 step + 节拍不漂移
    ├── test_app_exit.py             # 退出主循环 + pygame.quit 调用次数
    ├── test_app_error.py            # 图形环境不可用 → GraphicsUnavailableError → 退出码 2
    └── test_app_hud.py              # HUD dict 字段齐全 + high_score 字符串"---"
```

### 6.2 桩与夹具（conftest.py）

```python
# conftest.py
import pytest
from unittest.mock import MagicMock
import sys

# fake_pygame 必须在 conftest 顶部注入（早于 game_app import）
@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app.app 模块内的 pygame 引用为可编程 fake。"""
    fake = MagicMock()
    fake.error = RuntimeError  # fake 异常类
    fake.QUIT = 256
    fake.KEYDOWN = 768
    fake.K_w = 119; fake.K_s = 115; fake.K_a = 97; fake.K_d = 100
    fake.K_UP = 1073741906; fake.K_DOWN = 1073741905
    fake.K_LEFT = 1073741904; fake.K_RIGHT = 1073741903
    fake.K_q = 113; fake.K_ESCAPE = 27; fake.K_p = 112; fake.K_r = 114
    fake.K_RETURN = 13; fake.K_SPACE = 32
    fake.K_1 = 49; fake.K_2 = 50; fake.K_3 = 51
    # 让 display.set_mode 默认成功；个别测试可 monkeypatch.setattr 改 fake.display.set_mode.side_effect
    fake.display.set_mode.return_value = MagicMock()
    # 桩化 game-core 与 gui-renderer（避免依赖）
    monkeypatch.setitem(sys.modules, "pygame", fake)
    # game_app.app 内 import 的 pygame 需重导
    from game_app import app as app_module
    monkeypatch.setattr(app_module, "pygame", fake)
    return fake


@pytest.fixture
def app(fake_pygame):
    from game_app import App
    return App()


@pytest.fixture
def app_in_playing(fake_pygame):
    """App 已开局进入 PLAYING 态。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    return a
```

### 6.3 断言规范

- **不变量优先**：每个 UT 至少断言一条 INV（1~6）
- **纯函数性质**：调 `_tick` / `_dispatch` 后断言 `app.game_state` 已替换为新对象（`is not` 旧对象）；旧对象 snapshot 不变
- **覆盖状态机矩阵**：每态 × 每 action 用 `pytest.mark.parametrize` 枚举
- **fake_pygame 副作用统计**：`fake.init.call_count` / `fake.quit.call_count` 用于验证 INV-5（`pygame.quit` 必被调 1 次）
- **退出码断言**：`App().run()` 返 int，对齐 0/1/2 语义
- **UT 命名**：`test_{屏幕}_{动作}_{期望}`，如 `test_playing_w_key_sets_direction_up`

### 6.4 必须覆盖的 UT 用例清单（FO 必写）

| # | 场景 | 断言 |
|---|------|------|
| 1 | 构造 App | 初始 screen=MENU、difficulty=MEDIUM、high_score 占位、pygame.init 被调 1 次 |
| 2 | AppConfig frozen | 字段不可赋值 → `dataclasses.FrozenInstanceError` |
| 3 | AppConfig 默认值 | window_w=800, window_h=600, fps_cap=60 |
| 4 | AppConfig 非法 fps_cap | fps_cap=0/-1 抛 ConfigError |
| 5 | 事件 → Action 映射（WASD） | K_w → MOVE_UP, K_a → MOVE_LEFT, K_s → MOVE_DOWN, K_d → MOVE_RIGHT |
| 6 | 事件 → Action 映射（方向键） | K_UP → MOVE_UP, K_LEFT → MOVE_LEFT |
| 7 | 事件 → Action 映射（Q/ESC） | K_q/K_ESCAPE → QUIT |
| 8 | 事件 → Action 映射（其他） | K_x / K_y / 鼠标 → None（无映射） |
| 9 | MENU：SELECT_EASY 改 difficulty | 调 _dispatch(SELECT_EASY) → app._difficulty == Difficulty.EASY |
| 10 | MENU：START 开局 | 调 _dispatch(START) → screen==PLAYING 且 game_state 不为 None |
| 11 | MENU：QUIT 退出请求 | 调 _dispatch(QUIT) → app._quit_requested == True |
| 12 | PLAYING：WASD 推方向 | _dispatch(MOVE_UP) → game_state.direction/pending_direction == UP |
| 13 | PLAYING：连续方向合并（pending） | _dispatch(MOVE_UP) → _dispatch(MOVE_LEFT) → step 后按 LEFT 走（依赖 core pending 行为） |
| 14 | PLAYING：P 键占位（迭代 1 不调 toggle_pause） | _dispatch(TOGGLE_PAUSE) → _pause_hint_shown == True，game_state.status 仍 RUN |
| 15 | PLAYING：撞墙自动转 GAME_OVER | _new_game(HARD) + _tick 累计足够 → status=OVER 且 screen=GAME_OVER |
| 16 | PLAYING：撞自身自动转 GAME_OVER | 模拟蛇身填满后 step → screen=GAME_OVER |
| 17 | PLAYING：节拍不漂移 | _tick(50) 3 次（MEDIUM 160ms）→ step 调 0 次；_tick(170) 1 次 → step 调 1 次；累加器为 10 |
| 18 | PLAYING：节拍追跑（一帧多次 step） | _tick(500)（HARD 100ms）→ step 调 5 次；累加器为 0 |
| 19 | GAME_OVER：R 重开 | _dispatch(RESTART) → screen==PLAYING 且新 game_state.status==RUN |
| 20 | GAME_OVER：Q 退出 | _dispatch(QUIT) → _quit_requested == True |
| 21 | OVER 后再 PLAYING 调 set_direction | game_state.status=OVER 时 set_direction 抛 InvalidStateError（INV-1 边界） |
| 22 | HUD 字段齐全 | _build_hud() 返 dict 含 score/length/difficulty/high_score |
| 23 | HUD high_score 占位 | _build_hud()["high_score"] == "---"（INV-6） |
| 24 | 退出主循环调 pygame.quit | run() 触发 QUIT 后 → fake.quit.call_count == 1（INV-5） |
| 25 | 图形环境不可用 | fake.display.set_mode.side_effect=RuntimeError → run() 返 2 + stderr 可读消息 |
| 26 | ConfigError 触发退出码 1 | App(fps_cap=0) 构造抛 ConfigError → main() 返 1 |
| 27 | Q/ESC 任意态退出 | parametrize([MENU, PLAYING, GAME_OVER]) × QUIT → 主循环下次 break |
| 28 | 端到端：开新局→走 50 步→撞墙→重开→撞墙→退出 | fake_pygame 注入事件流，验证 screen 转换与退出码 0 |
| 29 | 难度游戏中不可切换 | _new_game(HARD) 后调 _dispatch(SELECT_EASY) → game_state.difficulty 仍 HARD（INV-3） |
| 30 | _tick_accumulator_ms 边界 | _tick(0) → step 调 0 次；_tick(160) 恰好调 1 次（MEDIUM） |

### 6.5 覆盖率目标

- **行覆盖 ≥ 90%**（`app.py` 主循环 / dispatch / tick 必须 100%；`input.py` 100%）
- **分支覆盖 ≥ 85%**（每屏 dispatch 分支、节拍 while 循环分支、错误处理分支）
- **不变量测试**：每条 INV 至少 1 个用例引用

### 6.6 UT 运行命令

```bash
# 单跑本模块
python3 -m unittest discover -s tests/test_game_app -v

# 或 pytest
pytest tests/test_game_app -v --cov=game_app --cov-branch --cov-fail-under=90
```

> 框架选型：unittest 即可（与 game-core 对齐）；pytest 作推荐（参数化 + monkeypatch 更顺手）。**强制**：app UT 不依赖真实显示器/窗口，能在 CI 干净容器里 `xvfb-run -a python3 -m unittest` 或纯 `python3 -m unittest`（fake_pygame 注入）通过。

### 6.7 FO TDD 实施步骤（建议）

1. 写 `test_config.py`（UT 2/3/4） → 跑（红）→ 写 `config.py`（绿）
2. 写 `test_input_map.py`（UT 5~8） → 跑（红）→ 写 `input.py`（绿）
3. 写 `test_app_init.py`（UT 1） → 写 `app.py.__init__`（含 fake_pygame 注入支撑）
4. 写 `test_app_menu.py`（UT 9/10/11） → 补 `_dispatch_menu` + `_new_game`
5. 写 `test_app_playing.py`（UT 12~14） → 补 `_dispatch_playing`（含 P 键占位）
6. 写 `test_app_tick.py`（UT 17/18/30） → 补 `_tick` 累加器
7. 写 `test_app_game_over.py`（UT 19/20） → 补 `_dispatch_over` + 撞墙/撞身自动转（UT 15/16）
8. 写 `test_app_hud.py`（UT 22/23） → 补 `_build_hud`
9. 写 `test_app_exit.py`（UT 24） → 补 `_run_loop` finally
10. 写 `test_app_error.py`（UT 25/26） → 补 `_init_pygame` 错误传播 + main() 退出码

> 严格 RED-GREEN-REFACTOR，UT 写完先红，实现只补到变绿，**不要超前写未测代码**。

---

## 附录 A：迭代 1 → 迭代 2/3/4 增量接口预告（仅供 FO 留扩展点，不在本次实现）

### A.1 迭代 2 增量

- `App._difficulty` 来源由"硬编码菜单 cursor"扩展为"启动时从 storage 读上次选择（可选）"
- `_dispatch_playing` 加 `TOGGLE_PAUSE` 实际处理：`game_state = game_state.toggle_pause()`；`_tick` 在 PAUSED 态不累加
- 新增 `AppScreen.PAUSED` 状态；`_render` 在 PAUSED 态叠加半透明遮罩 + "P to resume"
- `App.high_score: int` 从 `HighScoreStore(...).load()` 读；每次 `core.step` 后 `_maybe_update_high_score()`（用 `core.on_score` 事件或 step 返回值对比，**优先 on_score 事件**）
- HUD `high_score` 字段从"---"替换为 `str(high_score)`；开始界面 + 结束画面展示历史最高分
- `_dispatch_menu` 新增"重置最高分 (H 键)"入口 → `HighScoreStore.reset()` → HUD 实时更新
- 新增"返回菜单"状态（从 GAME_OVER 加 R / Esc 键），便于用户选择难度

### A.2 迭代 3 增量

- `App._renderer = Renderer(skin_name)` 接受皮肤参数；`_dispatch_menu` 新增皮肤选择（方向键 ←→ 切皮肤）
- `Renderer.set_skin(name)` 调用点：MENU 选皮肤时 + 游戏中"按 T 切换"（对局不中断，FR-10）
- `AppConfig` 启用 `min_window_w/min_window_h`；主循环加 `pygame.VIDEORESIZE` 处理 + 透传给 `Renderer.handle_resize`
- `_render` 透传 `(self.config.window_w, self.config.window_h)` 给 renderer（迭代 1 用固定尺寸）
- `Renderer` 内部切换为平滑插值模式（`interpolation_alpha` 参数，app 不用改）

### A.3 迭代 4 增量

- `main()` 完善错误提示：捕获所有 `AppError` 子类，按错误类型给可读建议（缺 SDL 库/驱动版本/HiDPI 缩放提示）
- 性能 profile 脚本：`scripts/bench_fps.py` 实测 NFR-01（≥60FPS, P95 帧时间 ≤25ms）、NFR-02（内存 ≤300MB, CPU ≤10%）
- PyInstaller spec 文件：`build/snake-gui.spec`，三平台构建脚本 `build/{linux,windows,macos}.sh`
- 用户指南 `USER_GUIDE.md`：下载运行、键位表、难度说明、皮肤说明、暂停说明、平台差异、已知限制
- 发布物清单：`dist/snake-gui{suffix}` + `SHA256SUMS` + `RELEASE_NOTES.md`
- `_init_pygame` 加 SDL 驱动版本检查 + 友好降级（找不到硬件加速 → 软件渲染）

### A.4 接口扩展原则

- 默认参数 + 新增方法，**不破坏迭代 1 既有签名**
- `App` 公开方法（`run()` / `__init__()`）签名迭代 1~4 不变
- `AppConfig` 字段迭代 1 冻结默认值，迭代 3 通过子类化 `AppConfigV3` 扩展（不修改 `AppConfig`）

---

## 附录 B：依赖与版本

| 依赖 | 版本 | 约束来源 |
|------|------|----------|
| Python | ≥3.8, <4 | 架构 §代码风格约定 |
| pygame | ≥2.0,<3 | gui-renderer 迭代 1 锁定（详见 gui-renderer/设计-r1.md） |
| game-core | 迭代 1 it_passed | 模块依赖 |
| gui-renderer | 迭代 1 it_passed | 模块依赖 |
| platform-storage | 迭代 2 接入 | 迭代边界（迭代 1 不 import） |
| PyInstaller | ≥5.0（迭代 4） | 架构 §技术选型 |

---

## 附录 C：与 v1 终端版差异（FO 实现须知）

| 项 | v1 终端版 | v2 game-app |
|----|----------|-------------|
| 主循环 | curses `getch` + `nodelay` 轮询 | pygame event pump + `clock.tick_busy_loop` |
| 输入缓冲 | 单字符 WASD 直接生效 | 事件队列 + InputAction 归一化 |
| 节拍控制 | `curses.napms(tick_ms)` | `_tick_accumulator_ms` 累加 + while 追跑 |
| 状态机 | 仅 run/over | MENU / PLAYING / GAME_OVER（PAUSED 迭代 2） |
| 难度切换 | 固定 160ms | 三档菜单选 + 游戏中不可改（FR-05） |
| 错误提示 | 终端字符 + 退出码 | pygame 异常包装 + 人类可读 stderr（NFR-03） |
| 退出 | main 返 0 | main 返 0/1/2（图形环境 2） |
| 持久化 | 无 | 迭代 2 接入（FR-13） |

> **核心玩法逻辑完全一致**（FR-01~05 与 v1 同语义）；**仅形态升级 + 已拍板新能力**（FR-10/12/13）。所有"v1 已验证"的玩法行为 game-core 单元测试已覆盖，game-app 仅做装配。
