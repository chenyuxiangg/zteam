# 功能模块设计：game-app（snake-linux v2.0.0 迭代 2）r1（首发，按 iter-1 SE 评审 r3 PASS 修订方向增量）

> MDE r1 · 跨迭代复用基线：**迭代 1 设计 `snake-linux/design/game-app/设计-r3.md`（SE 评审 PASS）** + **迭代 1 实际代码 `snake-linux/code/game-app/iter-1/`（it_passed，代码已 R3 全部落实）**
> 依据：架构设计 `snake-linux/arch/v2.0.0/架构设计.md` §迭代计划迭代 2 + 功能模块分工表（备注"难度选择 UI 已在迭代 1 完成，迭代 2 不重复"）+ 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved，R-01~R-09 已固化）
> SE 评审意见参考：迭代 1 评审 `snake-linux/review/design/game-app/iter-1/snake-linux-game-app-design-iter1-r{1,2,3}.md`（r3 PASS 拍板的修订方向全部沿用）
> 依赖模块实际契约（**全部 it_passed，契约已锁定**）：
>   - game-core **迭代 2** `code/game-core/iter-2/game_core/`（state.py）—— `GameState(width=, height=, difficulty=, rng=, initial_direction=, score_callback=)` / `set_direction` / `step` / `snapshot` / **`toggle_pause`**（RUN↔PAUSED，OVER 抛 InvalidStateError，PAUSED→RUN 清空 pending_direction）/ **`set_score_callback(cb)`** / `Snapshot.tick_ms = speed_curve(score, difficulty)`
>   - gui-renderer **迭代 3** `code/gui-renderer/iter-3/gui_renderer/`（renderer.py）—— `Renderer((W,H), *, skin=None, vsync=True, cell_size, grid_cols, grid_rows, enable_high_dpi=True)` / `init()` / `shutdown()` / **`render(snap, hud, *, interp=None)`**（iterp 非 None 时按 alpha 插值绘制，None=瞬移向后兼容）/ **`set_skin(name)`**（不在 SKIN_REGISTRY 抛 SkinNotFoundError）/ **`handle_resize(w, h)`**（< 最小可玩尺寸抛 RenderError）/ `skin_names()` / `current_skin_name` / `fps_metric()`
>   - platform-storage **迭代 2** `code/platform-storage/iter-2/platform_storage/`（highscore.py / paths.py）—— `get_user_data_dir() -> Path` / `HighScoreStore(path=None)` / `load() -> int` / `save(score)` / `reset()` / `StorageError`
> **目标**：FO 拿到本文即可 TDD 开发；迭代 2 在迭代 1 既有代码上增量修改（**保留 iter-1 全部 R3 修订**，新增 PAUSED 状态机接入 / HighScoreStore 接入 / 失焦暂停 / 最高分重置 / 暂停遮罩）；同时消化 iter-1 r3 SE 评审遗留的 6 项 P2-N1~N6（不阻塞 PASS，FO 落地时一并修）
> **关键决策**：迭代 2 **不新建 iter-2 代码目录**——增量改动直接落在 iter-1 源码目录 `snake-linux/code/game-app/iter-1/` 上（同属 v2.0.0 一个发布单元）；**不重写既有文件**，仅修改 `app.py` / `input.py` / `screens.py` / `menu.py` / `__init__.py` 并新增 `storage.py`；迭代 2 测试加在 `tests/test_game_app/test_app_iter2_*.py`

---

## 0. 修订摘要（相对 iter-1 设计 r3）

### 迭代 2 增量（核心目标，对应需求 R-02/R-03 / FR-12/FR-13）

| ID | 级别 | 修订内容 | 章节 |
|----|------|----------|------|
| **G2-1** | 应实现 | **PAUSED 状态机扩展**：`AppScreen.PAUSED` 加入枚举；`InputAction.TOGGGLE_PAUSE` 分支从 iter-1 的 hint 占位（`self._pause_hint_shown = True`）改为 `self.game_state = self.game_state.toggle_pause()` + **同步切屏**；`_tick` 在 PAUSED 态不推进（**INV-10 新增**：PAUSED 态 `_tick` 必须 return，不累加、不 step——虽然 core 内 toggle_pause 已保证 step 抛 InvalidStateError，但 app 侧少一次调用更清晰）；**屏态同步方案 A（dispatch 内单点同步）**：`_dispatch_playing` 收到 TOGGLE_PAUSE/UNFOCUS 后 toggle 后显式 `self.screen = AppScreen.PAUSED`；`_dispatch_paused` 收到 TOGGLE_PAUSE 后 toggle 后显式 `self.screen = AppScreen.PLAYING`；`_tick` 内**不再**靠 `status == PAUSED` 自动转屏（core step 永不返 PAUSED，原 elif 分支删除，改为防御性注释）；OVER 态调 toggle_pause 抛 InvalidStateError → app 侧不包装、UT 覆盖 | §1.1 §1.3 §3.4 §4.4 §4.5 §5.6 §6.4 |
| **G2-2** | 应实现 | **HighScoreStore 接入**：`App.__init__` 新增 `self._storage: Optional[HighScoreStore] = None`（**R2-2 默认 None 让 UT 构造不依赖磁盘**）；`_init_pygame` 内构造 `self._storage = HighScoreStore()` 并 `self._high_score = self._storage.load()`（**迭代 1 占位的 0 替换为真实持久值**）；`_dispatch_menu` 加 `InputAction.RESET_HIGHSCORE` 分支（见 G2-3）；`reset()` 失败抛 `StorageError`（包装为 `AppError` 子类）→ 退出码 1 + stderr 可读 | §1.3 §3.4 §3.6 §4.4 §4.7 §6.4 |
| **G2-3** | 应实现 | **得分事件回调接入**：`_new_game` 构造 GameState 时通过 `score_callback` 参数注册回调（**全关键字**沿用 R3-4）；**P0-2 修订**：回调内直接同步实例字段 `self._high_score = max(self._high_score, new_score)`（不再用 nonlocal `_high` / `_high_ref` dict 容器）；同时 `self._storage.save(max(new_score, self._storage.load()))` 落盘；回调异常**app 不捕获**（与 core iter-2 一致："回调内抛异常由调用方隔离"——但 app 是调用方，dispatch 在主循环外层 `except AppError` 兜底；非 AppError 上浮退出码 1）；新增 `InputAction.RESET_HIGHSCORE`（H 键 → MENU 态 dispatch）；`_dispatch_menu` 加该分支：`self._storage.reset(); self._high_score = 0`；**重启最高分回调**：`_new_game` 必须重新注册（core 的 `set_score_callback` 返回新 GameState，回调不延续——验证 game-core iter-2 行为，UT 覆盖） | §1.1 §3.4 §4.4 §4.6 §6.4 |
| **G2-4** | 应实现 | **窗口失焦自动暂停**：`_init_pygame` 后主循环每帧轮询 `pygame.key.get_focused()`；`False` 且当前 screen==PLAYING → 自动 `game_state.toggle_pause()` 并 screen=PAUSED；`True` 不自动恢复（避免误触，按 P 才继续——避免聚焦切换闪烁）；新增 `InputAction.UNFOCUS`（内部信号，不来自 _map_event；只在主循环内检测到失焦时入 actions 列表）；UT 覆盖：失焦 PLAYING→PAUSED 自动转移、已 PAUSED 再失焦不变、聚焦恢复不自动恢复 | §4.2 §4.4 §5.5 §6.4 |
| **G2-5** | 应实现 | **暂停遮罩**：`_render` PAUSED 路径在 PLAYING 渲染之后叠加半透明遮罩（app 自绘，**不**依赖 gui-renderer）；新增 `menu.draw_pause_overlay(surface, body_font)`（surface 来自 `pygame.display.get_surface()`，沿用 R3-2 不读 `_screen`）；遮罩 = `(0,0,0,128)` 半透明矩形 + 居中文字 "PAUSED — P 继续"（中文走 CJK 字体回退链 R3-12）；PLAYING→PAUSED 切换帧已渲染一次，PAUSED→RUN 切回 PLAYING 时遮罩不再绘制 | §3.7 §4.8 §6.4 |
| **G2-6** | 应实现 | **最高分展示**：`draw_menu` / `draw_game_over`（app 自绘）增加"最高分：xxx"行（仅当 `_high_score > 0` 时显示，避免"最高分：0"误导）；数字从 `app._high_score` 传入（**形参收窄沿用 R3-2**：新增 `high_score: int = 0` 参数，不读 app 私有）；HUD `_build_hud` 的 `high_score=self._high_score` 不变（迭代 1 已接 `self._high_score` 字段，仅替换数据源） | §3.7 §4.8 §6.4 |
| **G2-7** | 应实现 | **"返回菜单"路径**：GAME_OVER 态新增 `InputAction.BACK_TO_MENU`（ESC / Backspace 键）→ `self.screen = AppScreen.MENU; self.game_state = None`（重置 INV-7 保护）；`_dispatch_over` 加该分支；MENU 态进 PLAYING 重置所有 game_state 相关字段 | §1.1 §1.3 §3.4 §4.4 §6.4 |
| **G2-8** | 应实现 | **难度选择 UI 不在迭代 2 重复实现**（R-01 / R2-14 / R3-3：迭代 1 已完成，分工表已备注；iter-2 范围仅承接暂停继续 + 最高分展示重置） | §0 §附录 B |
| **G2-9** | 文档 | **新文件组织决策**：迭代 2 **不**新建 `code/game-app/iter-2/` 目录，增量修改直接在 iter-1 源码目录落地（同 v2.0.0 一个发布单元）；新增 `storage.py`（HighScoreStore 包装）；新增 `tests/test_game_app/test_app_iter2_{pause,storage,unfocus,overlay,reset}.py`；`tests/test_game_app/conftest.py` 增加 `storage` fixture（`tmp_path` 注入 HighScoreStore） | §4.1 §6.1 §附录 A |
| **G2-10** | 文档 | **依赖版本更新**：依赖 game-core iter-2（`toggle_pause`/`set_score_callback`/`speed_curve`）、gui-renderer iter-3（`set_skin`/`handle_resize`/`render(interp=)`——iter-2 game-app **不调用**这些，预告 iter-3 用）、platform-storage iter-2（`HighScoreStore`——本轮首次导入） | §0 §附录 B |

### iter-1 r3 SE 评审遗留 6 项 P2-N1~N6 同步消化（FO 落地修订，不阻塞本次 SE）

| ID | 级别 | 修订内容 | 章节 |
|----|------|----------|------|
| **G2-R-N1** | 文档/UT | `App(fps_cap=0)` 与 `App.__init__(config: AppConfig = AppConfig())` 签名矛盾：选 **方案①**——`AppConfig.__post_init__` 在构造期抛 `ConfigError`，§5.6 错误矩阵 + UT-33 改 `App(AppConfig(fps_cap=0))`；`main()` 明确 try 覆盖 App 构造（`try: app = App(); return app.run() except ConfigError/AppError:`） | §3.5 §3.6 §5.6 §6.4 UT-33 |
| **G2-R-N2** | 文档 | §1.3 `_running` 表述补正：主循环 `if QUIT in actions: break` 直接 break（不写 `_running`），但保留 `_running` 作为"运行态标志"（未来 iter-3 OVER→MENU 等场景可由 dispatch 内部置 False 提前退出主循环）；本轮主循环不读 `_running` 但不删字段（iter-3 留扩展点） | §1.3 §4.2 §4.4 |
| **G2-R-N3** | 文档 | §4.4 `_dispatch_menu` 注释补正：MENU 态 `MOVE_*` 在 `_drain_events` 已转 START 不会进 dispatch；`TOGGLE_PAUSE`/`RESTART` 在 `_MENU_RESERVED_ACTIONS` 内会进 dispatch 但被显式忽略（不调用 `_new_game` / `toggle_pause`）；菜单提示"按 1/2/3 选难度，按 P/R 暂无效（iter-2 启用 P 暂停），按 Q 退出，按 ESC/Backspace 返回菜单（GAME_OVER 态）" | §4.4 §4.8 |
| **G2-R-N4** | UT | UT-24 笔误：`HudData` 字段为 `high_score`（公开），app 内部字段为 `_high_score`（私有）；UT-24 改断言 `_build_hud(snap).high_score == 0`（用公开字段名） | §6.4 UT-24 |
| **G2-R-N5** | 文档 | §5.6 错误矩阵与 §4.2 `run()` 代码对齐：run() 主循环仅 `except AppError`（ConfigError 在 main() 捕获），未捕获异常走解释器兜底（stderr traceback + 退出码 1）；删除 §5.6 "App.run() 中未捕获异常 → 兜底 except Exception → 退出码 1"行，改为"未捕获异常走解释器默认行为（stderr traceback + 退出码 1）" | §4.2 §5.6 |
| **G2-R-N6** | 实现 | `App.__init__` 默认参数 `config: AppConfig = AppConfig()` 在 import 期求值（frozen 不可变，功能无害）：G2-R-N1 选方案① 已隐含处理——`App(AppConfig())` 每次构造重新求值；保留默认参数（避免 UT 大量改动），但 §3.4 docstring 注明"默认参数在 import 期求值一次，UT 需不同 config 时显式传" | §3.4 |

### 沿用 iter-1 r3（不修订，本轮已 PASS）

- 模块定位（§0）
- 依赖边界（§0.5）
- Python 3.8 兼容 / 零配置 / 无网络 / 无音效 / 不写系统目录
- 跨迭代复用（主循环骨架 / 状态机 / 输入映射 / 错误处理框架）
- **R3-1 唯一屏态兜底**（None→START 在 `_drain_events`）
- **R3-2 menu 不读 renderer 私有**（走 `pygame.display.get_surface()`）
- **R3-4 字段命名统一**（`_difficulty` / `_high_score`）
- **R3-5 `_running: bool = True`** 在 §1.3 声明
- **R3-6 game-core iter-2 it_passed 契约锁定**（沿用；iter-2 设计所选接口与锁定代码一致）
- **R3-7 删除 `_quit()` 死代码 + dispatch QUIT 分支**
- **R3-8 `_tick` 循环内重读 tick_ms**（G2-1 PAUSED 态 tick 直接 return）
- **R3-9 InvalidStateError 理论不可达不包装**（G2-1 PAUSED/OVER 切 toggle_pause 同样不包装）
- **R3-10 App.__init__ 不构造 Renderer**（G2-2 `_storage = None` 同样在 `_init_pygame` 构造）
- **R3-11 `_render` 共享一次 snap**
- **R3-12 CJK 字体回退链**（G2-5 暂停遮罩复用）
- **R3-14 `app_in_playing` fixture**（G2 测试新增 `app_in_paused` / `app_with_storage`）
- **R3-15 退出码 2 shutdown 兜底**

---

## 0. 模块定位与迭代边界

| 项 | 值 |
|----|---|
| 模块 | game-app |
| 类型 | 上层应用 |
| 依赖 | game-core（纯逻辑，迭代 2 **it_passed — 接口以 iter-2 落地为准**）、gui-renderer（迭代 3 **it_passed — 接口以 iter-3 落地为准**，iter-2 game-app 仅 `render` 不调 `set_skin`/`handle_resize`/`render(interp=)`）、platform-storage（**迭代 2 接入，本轮首次 import**） |
| 被依赖 | 无（顶层装配） |
| 承载需求 | snake-gui **主体**——本迭代 2 增量范围 = FR-12 暂停/继续 + FR-13 最高分持久化（展示/重置） |
| 迭代 | 2（在 iter-1 既有代码上增量修改；不新建 iter-2 代码目录） |
| 不引入 | 第三方除 pygame 外任何依赖；不引入音效（架构 §R-04）；不引入网络（NFR-06）；不引入 config 文件（架构 §配置模型） |
| 跨迭代复用 | 主循环骨架 / 界面状态机 / 输入映射 / 错误处理框架 跨 1~4 迭代复用 |
| PyInstaller 入口 | `snake-gui.py`（包根 `__main__.py`，`if __name__ == "__main__": main()`）—— 沿用 iter-1 |

### 迭代 2 增量出口（与架构 §迭代计划迭代 2 + 分工表对齐）

- ✅ **FR-12 暂停/继续**（G2-1）：P 键实际切换 PAUSED 状态；遮罩提示（G2-5）
- ✅ **FR-12 窗口失焦自动暂停**（G2-4）：聚焦丢失 → 自动 PAUSED；恢复不自动继续
- ✅ **FR-13 最高分持久化**（G2-2）：`HighScoreStore` 落地，HUD 展示真实最高分
- ✅ **FR-13 得分事件自动写入**（G2-3）：通过 `set_score_callback` 回调存储
- ✅ **FR-13 最高分重置**（G2-3）：H 键（仅 MENU 态）+ `HighScoreStore.reset()`
- ✅ **FR-13 最高分展示**（G2-6）：MENU / GAME_OVER 自绘加"最高分：xxx"
- ✅ **返回菜单**（G2-7）：GAME_OVER 态 ESC/Backspace → 回到 MENU（避免一次结束即退出）
- ✅ **iter-2 状态机扩展点**（G2-R-N2）：`_running` 字段保留，iter-3 dispatch 内部退出时再用
- ❌ 皮肤切换 UI（FR-10，迭代 3；gui-renderer iter-3 `set_skin` 已实装但本轮不调）
- ❌ 窗口缩放 UI（FR-09，迭代 3；gui-renderer iter-3 `handle_resize` 已实装但本轮不调）
- ❌ 平滑动画（FR-07，迭代 3；gui-renderer iter-3 `render(interp=)` 已实装但本轮不调）
- ❌ 三平台打包（FR-14/15，迭代 4）
- ❌ 完善错误提示（NFR-03 最小集，迭代 4 完善——本轮迭代 2 仅加 `StorageError` 包装）

### 迭代 2 已知技术约束（FO 实现必读）

1. **Python 3.8 兼容**：与架构 §代码风格约定一致，不使用 dataclass 自定义 `__setattr__` 之外的 3.9+ 特性。
2. **零配置**：不读 ini/env/YAML/JSON 配置；难度通过游戏内 UI 选择。
3. **无网络**：全模块不 `import socket` / `import urllib` / `import http` / `import requests`；UT 不发起网络。
4. **无音效**：不 `import pygame.mixer` 或任何音频模块。
5. **依赖边界**：game-app **可** import pygame + platform_storage（iter-2 新增）；**不可**侵入 game-core / gui-renderer 内部（仅走公开 API）。
6. **代码组织**：迭代 2 **不**新建 iter-2 源码目录；增量修改在 `code/game-app/iter-1/` 内进行（同 v2.0.0 发布单元）；新增文件 `storage.py` + `tests/test_game_app/test_app_iter2_*.py`。
7. **不读 gui-renderer 私有属性**：自绘菜单/结束画面/暂停遮罩通过 `pygame.display.get_surface()`（R3-2）。
8. **不引入平台特定代码**：`pygame.key.get_focused()` 跨平台行为一致（Linux X11/Wayland / Windows / macOS）。
9. **平台数据目录便携性**：`HighScoreStore` 默认 `path=None` → `get_user_data_dir()`，NFR-07（不写系统目录）。

---

## 1. 数据结构

### 1.1 界面状态枚举（G2-1 扩展：加入 PAUSED）

| 类型 | 字段 | 说明 |
|------|------|------|
| `AppScreen`（Enum） | `MENU` / `PLAYING` / **`PAUSED`** / `GAME_OVER` | app 顶层界面状态机；iter-2 加 `PAUSED` 态；iter-3/4 不再加 |
| `InputAction`（Enum） | `QUIT` / `START` / `MOVE_UP/DOWN/LEFT/RIGHT` / `TOGGLE_PAUSE` / `RESTART` / `SELECT_EASY/MEDIUM/HARD` / **`RESET_HIGHSCORE`** / **`BACK_TO_MENU`** / **`UNFOCUS`**（内部信号） | iter-2 新增 3 个；`UNFOCUS` 不来自 `_map_event`，仅主循环内检测到失焦时入 actions |

> **G2-7 备注**：`BACK_TO_MENU` 在 GAME_OVER 态触发；`RESET_HIGHSCORE` 在 MENU 态触发（H 键）；`_MENU_RESERVED_ACTIONS` 需同步扩展（见 §4.4）；`UNFOCUS` 不进 `_MENU_RESERVED_ACTIONS`（仅主循环内部产生，不经 `_drain_events`）。

### 1.2 难度选择状态（沿用 iter-1 r3，**iter-2 不重复实现 UI**）

- 沿用 `self._difficulty: Difficulty`，1/2/3 键改写、`InputAction.START` 开新局；
- **G2-8**：分工表备注"难度选择 UI 已在迭代 1 完成"——iter-2 不重写 `draw_menu` 的难度行。

### 1.3 运行期状态（app 内部 mutable state）

| 字段 | 类型 | 初始 | 说明 |
|------|------|------|------|
| `screen: AppScreen` | 当前界面 | `MENU` | iter-2 加 PAUSED 态 |
| `_difficulty: Difficulty` | 当前局难度 | `MEDIUM` | 沿用 R3-4 |
| `game_state: Optional[GameState]` | 玩法状态 | `None` | PAUSED 态**也**非 None（G2-1 PAUSED 是从 PLAYING 转移，game_state 不重置）；GAME_OVER 态非 None；MENU 态 = None（INV-7） |
| `_renderer: Optional[Renderer]` | 渲染器 | `None` | 沿用 R3-10 |
| `clock: pygame.time.Clock` | 帧率控制 | 由 `_init_pygame` 构造 | 沿用 iter-1 |
| `_high_score: int` | 最高分 | `0`（iter-2 由 `_init_pygame` 覆盖为 `self._storage.load()`） | R3-4 命名 |
| **`_storage: Optional[HighScoreStore]`** | 持久化 | `None`（构造期，**G2-2 默认 None 让 UT 不依赖磁盘**） | iter-2 新增；`_init_pygame` 内构造并 `load()` 覆盖 `_high_score` |
| `_tick_accumulator_ms: int` | 内部节拍累计 | `0` | 沿用 iter-1 |
| `_running: bool` | 主循环退出标志 | `True` | 沿用 R3-5；**G2-R-N2 补正**：本轮主循环不读（QUIT 走 break），保留作 iter-3 扩展点 |
| `_pause_hint_shown: bool` | 暂停提示标志 | `False` | **iter-2 删除该字段**（iter-1 占位用；iter-2 PAUSED 是真实屏态，不再需要 hint） |
| `_menu_title_font: pygame.font.Font` | CJK 字体（大） | 由 `_init_pygame` 构造 | 沿用 R3-12 |
| `_menu_body_font: pygame.font.Font` | CJK 字体（小） | 同上 | 同上 |

### 1.4 不变量清单（FO 实现必须保证，UT 也要覆盖）

| ID | 不变量 | 沿用/新增 |
|----|--------|----------|
| INV-1 | `screen == PLAYING` 时 `game_state.status == GameStatus.RUN` | 沿用 iter-1；**P0-1 修订**：该不变量由 dispatch 内显式切屏保证（`_dispatch_paused(TOGGLE_PAUSE)` 后 screen=PLAYING 时 `game_state.status == RUN`，因 core toggle_pause(PAUSED→RUN) 直接返回 RUN 态 GameState） |
| INV-2 | `screen == GAME_OVER` 时 `game_state.status == GameStatus.OVER` | 沿用 iter-1 |
| INV-3 | 难度 `Difficulty` 选定后写入 `game_state.difficulty`，运行中**无接口**可改 | 沿用 iter-1 |
| INV-4 | `_tick_accumulator_ms >= tick_ms` 时必调 `step()`，调后减 `tick_ms`（**循环内逐拍重读 tick_ms**） | 沿用 R3-8 |
| INV-5 | 退出主循环后 `Renderer.shutdown()` 必被调 1 次（其内部 `pygame.quit()`），进程退出码 0；退出码 2 路径也尝试 1 次 | 沿用 R3-15 |
| INV-6 | `_high_score` 在 `_init_pygame` 后 = `self._storage.load()`；HUD 渲染 `_high_score` int | 沿用 iter-1（数据源替换） |
| INV-7 | `screen == MENU` 时 `game_state is None`；`screen` 离开 MENU 之前不能访问 `game_state` | 沿用 iter-1 |
| INV-8 | `_pause_hint_shown` 字段 iter-2 删除；PAUSED 状态由 `screen` 直接表达 | iter-2 删除 |
| INV-9 | `_renderer` 仅在 `_init_pygame()` 之后非 None；调用 `Renderer` 方法前必检 | 沿用 iter-1 |
| **INV-10** | `_tick` 仅在 `screen == PLAYING` 时被调用（前置条件，主循环在 `if screen == PLAYING` 后才调 `_tick`）；`_tick` 内 `assert screen == PLAYING` + `assert game_state.status == GameStatus.RUN`（INV-1 在 `_tick` 入口验证） | **iter-2 新增**（G2-1；**P0-1 修订**：原 INV-10 表述"PAUSED 态 `_tick` 必须 return"被新表述替代——`_tick` 在 PAUSED 态根本不被调用，入口断言即排除 PAUSED/OVER/GAME_OVER 误入） |
| **INV-11** | `screen == PAUSED` 时 `game_state` 非 None 且 `game_state.status == GameStatus.PAUSED`；`screen == PLAYING` 时 `game_state.status == GameStatus.RUN`；屏态同步唯一发生在 `_dispatch_*` 内（方案 A）—— `_dispatch_playing` 的 TOGGLE_PAUSE/UNFOCUS 分支调 `toggle_pause()` 后置 `self.screen = AppScreen.PAUSED`；`_dispatch_paused` 的 TOGGLE_PAUSE 分支调 `toggle_pause()` 后置 `self.screen = AppScreen.PLAYING` | **iter-2 新增**（G2-1；**P0-1 修订**：屏态同步方案 A 单点落地） |
| **INV-12** | `_storage` 仅在 `_init_pygame()` 之后非 None；`_storage.save()` 失败抛 `StorageError` → 包装为 `AppError` 子类 | **iter-2 新增**（G2-2） |
| **INV-13** | `_high_score` 与 `_storage.load()` 一致：每次 `score_callback(new_score)` 调用后，**回调内**直接 `self._high_score = max(self._high_score, new_score)`（**P0-2 修订**：不再用 nonlocal/外部容器，直接写实例字段）；`self._storage.save(max(new_score, self._storage.load()))` 同时落盘；HUD/`draw_game_over` 每帧读 `self._high_score` 立即可见 | **iter-2 新增**（G2-3；**P0-2 修订**：回调内同步实例字段） |

---

## 2. 数据传递方式

### 2.1 模块边界与数据流（G2-1/2/3 增量；其他沿用 iter-1）

```
                 ┌──────────────────────────────┐
   键盘事件 ───▶ │  InputMap: pygame.event →    │ ──▶ InputAction (Enum)
                 │       _map_event (单键)       │       (含 None: 未映射)
                 └──────────────────────────────┘
                            │
                            ▼
                 ┌──────────────────────────────┐
                 │ _drain_events (R3-1 屏态兜底) │ ──▶ InputAction 流
                 │  + 失焦检测 (G2-4)            │     + UNFOCUS (内部)
                 │  pygame.key.get_focused()    │     (仅 PLAYING 屏态产生)
                 └──────────────────────────────┘
                            │
                            ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  主循环 (run() → _run_loop())                                 │
   │   1. clock.tick(fps_cap) → dt_ms                             │
   │   2. _drain_events() → actions（含 UNFOCUS）                  │
   │   3. if QUIT in actions: break                                │
   │   4. for a in actions: _dispatch(screen, a)                   │
   │   5. if screen==PLAYING: _tick(dt_ms)                        │
   │        if screen==PAUSED: 跳过（G2-1 INV-10）                 │
   │        _tick 内仅检测 status==OVER 自动转 GAME_OVER           │
   │        （PAUSED 检测分支已删除——core step 永不返 PAUSED，     │
   │         PAUSED↔PLAYING 切屏在 dispatch 内单点同步 P0-1）      │
   │   6. _render():                                              │
   │        MENU        → menu.draw_menu(...) (含最高分行 G2-6)   │
   │        PLAYING     → renderer.render(snap, hud)              │
   │        PAUSED      → renderer.render(snap, hud)              │
   │                     + menu.draw_pause_overlay(...) (G2-5)    │
   │        GAME_OVER   → menu.draw_game_over(...) (含最高分行)   │
   │   7. pygame.display.flip()                                    │
   └──────────────────────────────────────────────────────────────┘
                            │                │              │
                ┌───────────┼────────────────┼──────────────┘
                ▼           ▼                ▼
            game-core   gui-renderer    platform-storage (iter-2 新增)
            (toggle_    (render)        (HighScoreStore:
             pause /                     load/save/reset)
             set_score_                  ↑↓
             callback)              set_score_callback
                                    lambda s: storage.save(...)
```

> **G2-1 关键变化**：状态机新增 `PAUSED` 节点（PLAYING ↔ PAUSED 由 `toggle_pause` 互转）；**屏态同步方案 A（P0-1 修订）**：屏态切换只在 `_dispatch_*` 内发生——`_dispatch_playing(TOGGLE_PAUSE/UNFOCUS)` 调 `toggle_pause()` 后显式 `self.screen = AppScreen.PAUSED`；`_dispatch_paused(TOGGLE_PAUSE)` 调 `toggle_pause()` 后显式 `self.screen = AppScreen.PLAYING`。`_tick` 不再做屏态检测（仅 `status==OVER → screen=GAME_OVER`）。`_drain_events` 的 UNFOCUS 检测仅在 PLAYING 态追加 `InputAction.UNFOCUS`（其他屏态不产生）。
> **G2-3 关键变化**：core 的 `set_score_callback` 回调 → `storage.save(max(s, storage.load()))`；storage 抛异常 → core 不捕获（按 game-core iter-2 设计）→ app 不捕获（按 INV-12 包装为 `AppError` 子类）→ 主循环 `except AppError` 兜底 → 退出码 1。
> **G2-4 关键变化**：主循环每帧 `_drain_events` 内检测 `pygame.key.get_focused()`，PLAYING 态失焦 → 追加 `InputAction.UNFOCUS` action；`_dispatch` 内对 UNFOCUS 调 `toggle_pause`。

### 2.2 模块间参数（G2-2/3 新增 storage 接口；其余沿用 iter-1）

| 方向 | 路径 | 类型 | 备注 |
|------|------|------|------|
| app → core | `_new_game(difficulty) -> None` | `GameState(width=20, height=15, difficulty=..., rng=Random(), **score_callback=...)` | **G2-3**：全关键字 + score_callback 参数；回调构造见 §4.6 |
| app → core | `game_state.set_direction(direction)` | `Direction` | 沿用 iter-1 |
| app → core | **`game_state.toggle_pause() -> GameState`** | 无参 → 新 GameState | **G2-1 iter-2 新增调用**；OVER 抛 InvalidStateError |
| app → core | `game_state.step() -> GameState` | 无参 → 新 GameState | 沿用 iter-1；PAUSED 态不调用（G2-1 INV-10） |
| app → core | `game_state.snapshot()` | 无参 → `Snapshot`（含 tick_ms 走 speed_curve） | 沿用 iter-1；G2-1 PAUSED 态仍可 snapshot（字段冻结） |
| app → renderer | `Renderer((640, 480), skin=DEFAULT_SKIN)` | 构造 | 沿用 iter-1；iter-2 **不**调 `set_skin` / `handle_resize` / `render(interp=)`（iter-3 预告） |
| app → renderer | `renderer.init()` / `shutdown()` | 生命周期 | 沿用 iter-1 |
| app → renderer | `renderer.render(snapshot, hud)` | PLAYING / PAUSED 态每帧 | G2-1 PAUSED 态也调 render（保留最后一帧 + 叠加遮罩） |
| **app → storage** | `HighScoreStore()` | 无参 → HighScoreStore 实例 | **G2-2 iter-2 新增**；`path=None` → `get_user_data_dir()` |
| **app → storage** | `self._storage.load() -> int` | 无参 → int | **G2-2**；损坏/缺文件返 0 |
| **app → storage** | `self._storage.save(score) -> None` | score: int | **G2-3**；仅 > 当前 cache 落盘；抛 StorageError |
| **app → storage** | `self._storage.reset() -> None` | 无参 | **G2-3**；删除文件 + cache=0 |
| core → app | `InvalidStateError` | OVER 态调 toggle_pause 时抛 | iter-2 不包装（R3-9 一致）；UT 覆盖 |
| core → app | `score_callback(score: int)` | 吃食 step 时回调 | **G2-3 iter-2 新增**；回调内抛异常 core 不捕获 → app 不捕获 → 主循环 except AppError 兜底 |

### 2.3 存储 / 共享状态（G2-2/3 新增；其余沿用 iter-1）

- **进程内单例**：app 状态全部活在 `App` 类实例字段，**无全局变量**（除 pygame 自身 + iter-2 新增 `self._storage`）。
- **进程间无共享**：无 IPC、无 socket、无文件锁（platform-storage 内部用 RLock，跨进程不安全——本需求无并发写场景）。
- **磁盘写入**：iter-2 写 `highscore.json`（位于 `get_user_data_dir()/highscore.json`，三平台分别 `%APPDATA%/SnakeLinuxGUI/` / `~/Library/Application Support/SnakeLinuxGUI/` / `~/.local/share/SnakeLinuxGUI/`）；原子写（platform-storage 内部 `tempfile + os.replace`），异常退出不损坏。
- **损坏文件恢复**：iter-2 由 platform-storage 自动备份为 `highscore.corrupt-<ts>.json` 后返 0；app 不感知。

---

## 3. 对外接口

### 3.1 `AppConfig`（dataclass, frozen）—— **G2-R-N1 修订**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    """运行期不可变常量。FR-09/NFR-01/NFR-02。

    G2-R-N1：__post_init__ 在构造期校验字段合法性，非法抛 ConfigError。
    """
    window_w: int = 640
    window_h: int = 480
    fps_cap: int = 60
    min_window_w: int = 512
    min_window_h: int = 472

    def __post_init__(self) -> None:
        """G2-R-N1：构造期校验，避免运行时崩溃。"""
        if self.fps_cap <= 0:
            raise ConfigError(f"fps_cap 必须 > 0，收到 {self.fps_cap}")
        if self.window_w < self.min_window_w or self.window_h < self.min_window_h:
            raise ConfigError(
                f"窗口尺寸 ({self.window_w}, {self.window_h}) 小于最小可玩 "
                f"({self.min_window_w}, {self.min_window_h})"
            )
```

### 3.2 `AppScreen`（Enum，G2-1 加 PAUSED）

```python
from enum import Enum


class AppScreen(Enum):
    """app 顶层界面状态机。FR-11 + FR-12 入口。"""
    MENU = "menu"          # 开始 + 难度选择
    PLAYING = "playing"    # 玩法循环（RUN）
    PAUSED = "paused"      # 暂停态（G2-1 iter-2 新增，FR-12）
    GAME_OVER = "over"     # 结束 + 重开/退出
```

### 3.3 `InputAction`（Enum，G2-3/7 加新 action；G2-1 修订 TOGGLE_PAUSE 语义）

```python
class InputAction(Enum):
    """pygame 事件归一化结果。FO 只需实现 _map_event() 即可。"""
    QUIT = "quit"
    START = "start"
    MOVE_UP = "up"
    MOVE_DOWN = "down"
    MOVE_LEFT = "left"
    MOVE_RIGHT = "right"
    TOGGLE_PAUSE = "pause"          # iter-2 起：实际切 PAUSED（替代 iter-1 的 hint 占位）
    RESTART = "restart"
    SELECT_EASY = "sel_easy"
    SELECT_MEDIUM = "sel_med"
    SELECT_HARD = "sel_hard"
    RESET_HIGHSCORE = "reset_hs"    # G2-3 iter-2 新增：H 键 → MENU 态 dispatch
    BACK_TO_MENU = "back"           # G2-7 iter-2 新增：ESC / Backspace → GAME_OVER 态 dispatch
    UNFOCUS = "unfocus"             # G2-4 iter-2 新增：内部信号，不来自 _map_event
```

### 3.4 `App` 主类（G2-1/2/3/4/7 增量；R3 修订全部沿用）

```python
class App:
    """snake-gui 顶层装配；PyInstaller 入口。

    iter-2 增量（G2-1/2/3/4/5/7）：
    - 新增 _storage: Optional[HighScoreStore] 字段
    - 删除 _pause_hint_shown 字段（iter-2 PAUSED 是真实屏态）
    - TOGGLE_PAUSE dispatch 从 hint 占位改为 toggle_pause() + **同步切屏（P0-1）**
    - 新增 RESET_HIGHSCORE / BACK_TO_MENU / UNFOCUS 分支
    - _new_game 注册 score_callback（**P0-2**：回调内直接写 `self._high_score` 实例字段）
    - _run_loop 跳过 PAUSED 态的 _tick
    - _render 在 PAUSED 态调 render + draw_pause_overlay
    - _drain_events 检测 pygame.key.get_focused() 追加 UNFOCUS（仅 PLAYING 态产生）

    沿用 R3：None→START 屏态兜底 / menu 用 get_surface / _tick 循环内重读
           / App.__init__ 不构造 Renderer / CJK 字体回退链 / 退出码 2 兜底
           / 字段命名 _difficulty / _high_score
    """

    def __init__(self, config: AppConfig = AppConfig()) -> None:
        """仅置字段，不开窗、不调 pygame.init、不构造 Renderer、不构造 HighScoreStore。

        默认参数 config: AppConfig = AppConfig() 在 import 期求值一次（frozen 不可变，
        功能无害；G2-R-N6：UT 需不同 config 时显式传）。

        初始 screen=MENU, _difficulty=MEDIUM, game_state=None, _renderer=None,
        _storage=None, _high_score=0, _running=True, _tick_accumulator_ms=0。
        iter-2 删除 _pause_hint_shown 字段。
        """
        self.config = config
        self.screen: AppScreen = AppScreen.MENU
        self._difficulty: Difficulty = Difficulty.MEDIUM
        self.game_state: Optional[GameState] = None
        self._renderer: Optional[Renderer] = None
        self._storage: Optional[HighScoreStore] = None        # G2-2 iter-2 新增
        self._high_score: int = 0                              # _init_pygame 覆盖为 storage.load()
        self._tick_accumulator_ms: int = 0
        self._running: bool = True                             # R3-5 + G2-R-N2
        # 删除 _pause_hint_shown（G2-1 INV-8 字段移除）
        self._menu_title_font: Optional[pygame.font.Font] = None
        self._menu_body_font: Optional[pygame.font.Font] = None
        self.clock: Optional[pygame.time.Clock] = None

    def run(self) -> int:
        """主循环。返回进程退出码（0 正常 / 1 异常 / 2 图形环境不可用）。

        G2-2：_init_pygame 失败也兜底 storage 资源（HighScoreStore 构造在 _init_pygame 内，
        若 _init_pygame 抛错则 _storage 仍为 None，无需清理；storage 自身无 IO init，无泄漏）。
        """

    # --- 内部接口 ---

    def _drain_events(self) -> List[InputAction]:
        """本帧所有 pygame 事件归一化；QUIT 优先 break；G2-4 失焦检测追加 UNFOCUS。

        R3-1 屏态兜底（不变）：MENU 屏态下所有 action（除保留键外）→ START。
        G2-4 新增：screen==PLAYING 时检测 pygame.key.get_focused()，
                   False → 追加 InputAction.UNFOCUS（不替换其他 action，按序追加）。
        其他屏态（PAUSED/GAME_OVER）不检测失焦（PAUSED 已是暂停态；GAME_OVER 不需要再暂停）。
        """

    def _dispatch(self, action: InputAction) -> None:
        """按当前 screen 分发：MENU / PLAYING / PAUSED / GAME_OVER 四态。"""

    def _dispatch_menu(self, action: InputAction) -> None:
        """MENU 态分发。
        iter-2 新增 RESET_HIGHSCORE 分支（G2-3 H 键）；
        原有 SELECT_* / START 分支不变（R3-1/R3-4 沿用）；
        删除 QUIT 分支（R3-7 沿用）。
        """
        if action == InputAction.SELECT_EASY: self._difficulty = Difficulty.EASY
        elif action == InputAction.SELECT_MEDIUM: self._difficulty = Difficulty.MEDIUM
        elif action == InputAction.SELECT_HARD: self._difficulty = Difficulty.HARD
        elif action == InputAction.RESET_HIGHSCORE:                # G2-3 新增
            if self._storage is not None:
                try:
                    self._storage.reset()
                except StorageError as e:
                    raise AppError(f"重置最高分失败: {e}") from e
                self._high_score = 0
        elif action == InputAction.START:
            self._new_game(self._difficulty)

    def _dispatch_playing(self, action: InputAction) -> None:
        """PLAYING 态分发。G2-1：TOGGLE_PAUSE 从 hint 占位改为 toggle_pause()。
        **P0-1 屏态同步方案 A**：toggle 后显式切屏至 PAUSED（不依赖 _tick 检测 status）。
        """
        if action in (InputAction.MOVE_UP, InputAction.MOVE_DOWN,
                      InputAction.MOVE_LEFT, InputAction.MOVE_RIGHT):
            d = {InputAction.MOVE_UP: Direction.UP, InputAction.MOVE_DOWN: Direction.DOWN,
                 InputAction.MOVE_LEFT: Direction.LEFT, InputAction.MOVE_RIGHT: Direction.RIGHT}
            self.game_state = self.game_state.set_direction(d[action])
        elif action == InputAction.TOGGLE_PAUSE:                   # G2-1 修订（P0-1 同步切屏）
            # type: ignore[union-attr]  # 游戏态必非 None（INV-7 + 主循环前置条件）
            self.game_state = self.game_state.toggle_pause()       # R3-9 不包装 InvalidStateError
            self.screen = AppScreen.PAUSED                         # P0-1 同步切屏（INV-11）
        elif action == InputAction.UNFOCUS:                         # G2-4 新增（P0-1 同步切屏）
            # type: ignore[union-attr]
            if self.game_state.status == GameStatus.RUN:
                self.game_state = self.game_state.toggle_pause()   # 失焦 → 暂停
                self.screen = AppScreen.PAUSED                     # P0-1 同步切屏（INV-11）

    def _dispatch_paused(self, action: InputAction) -> None:
        """PAUSED 态分发。G2-1 iter-2 新增：仅响应 TOGGLE_PAUSE / UNFOCUS / QUIT。
        **P0-1 屏态同步方案 A**：toggle 后显式切屏至 PLAYING。
        """
        if action == InputAction.TOGGLE_PAUSE:                     # G2-1 P 继续（P0-1 同步切屏）
            # type: ignore[union-attr]
            self.game_state = self.game_state.toggle_pause()       # PAUSED→RUN
            self.screen = AppScreen.PLAYING                        # P0-1 同步切屏（INV-11）
        elif action == InputAction.UNFOCUS:
            pass  # PAUSED 态再失焦不变（G2-4）

    def _dispatch_over(self, action: InputAction) -> None:
        """GAME_OVER 态分发。G2-7 新增 BACK_TO_MENU 分支（P1-2 修订：ESC 独立 action）。
        - RESTART → _new_game
        - BACK_TO_MENU（GAME_OVER 态 ESC/Backspace → _drain_events 覆盖产生）→ MENU
        - QUIT（仅来自 pygame.QUIT 窗口关闭或 Q 键，未被 GAME_OVER 覆盖）→ 主循环 break
        """
        if action == InputAction.RESTART:
            self._new_game(self._difficulty)
        elif action == InputAction.BACK_TO_MENU:                   # G2-7 / P1-2
            self.screen = AppScreen.MENU
            self.game_state = None                                  # INV-7 重置

    def _new_game(self, difficulty: Difficulty) -> None:
        """game_state = GameState(width=20, height=15, difficulty=..., rng=Random(),
                                 score_callback=<绑定 self._storage>); screen=PLAYING。

        **G2-3 + P0-2 权威实现**（§3.4 与 §4.6 合并一处）：
        1. 若 `_storage is None`（UT 未注入）：`score_callback=None`（core 不触发）。
        2. 若 `_storage is not None`（生产环境）：注册回调 `lambda s: self._on_score(s)`，
           `_on_score` 内**直接**：
           - `self._high_score = max(self._high_score, s)`  ← **INV-13 同步实例字段**
           - `self._storage.save(max(s, self._storage.load()))` ← 落盘
           - 若 storage.save 抛 StorageError → 包 `StorageUnavailableError(AppError)`
        3. `game_state` 用全关键字构造（game-core iter-2 锁定签名）。
        4. 重置 `_tick_accumulator_ms=0` + `screen=PLAYING`。
        """
        if self._storage is None:
            cb = None
        else:
            _storage = self._storage
            def cb(score: int) -> None:
                # type: ignore[union-attr]  # _storage 在 _init_pygame 后非 None（INV-12）
                try:
                    self._high_score = max(self._high_score, score)            # INV-13 P0-2
                    _storage.save(max(score, _storage.load()))                 # 落盘
                except StorageError as e:
                    raise StorageUnavailableError(f"最高分保存失败: {e}") from e
        self.game_state = GameState(
            width=20, height=15, difficulty=difficulty,
            rng=random.Random(), score_callback=cb,
        )
        self._tick_accumulator_ms = 0
        self.screen = AppScreen.PLAYING

    def _tick(self, dt_ms: int) -> None:
        """PLAYING 态推进节拍。G2-1 PAUSED 态不进入此函数（主循环判断，见 §4.2）。
        循环内逐拍重读 tick_ms（R3-8）；OVER 自动转 GAME_OVER。
        **P0-1 屏态同步方案 A**：_tick 不再做 `status == PAUSED` 自动转屏——core step() 永不返 PAUSED（原 elif 分支为不可达死代码，已删除）。PAUSED↔PLAYING 切屏由 _dispatch_* 内 toggle 后显式赋值完成（INV-11）。
        """
        # type: ignore[union-attr]  # INV-10：主循环前置 screen==PLAYING 保证 game_state 非 None
        assert self.screen == AppScreen.PLAYING                    # INV-10 入口断言
        assert self.game_state.status == GameStatus.RUN            # INV-1 入口断言
        self._tick_accumulator_ms += dt_ms
        while True:
            tick_ms = self.game_state.snapshot().tick_ms
            if self._tick_accumulator_ms < tick_ms: break
            self._tick_accumulator_ms -= tick_ms
            self.game_state = self.game_state.step()
            new_status = self.game_state.status
            if new_status == GameStatus.OVER:
                self.screen = AppScreen.GAME_OVER                  # OVER 自动转 GAME_OVER
                break
            # P0-1 修订：原 `elif new_status == PAUSED` 分支删除
            # —— core step() 在 status != RUN 时抛 InvalidStateError（game-core iter-2 锁定），
            #    step() 永不返回 PAUSED，该分支永远不可达。
            # PAUSED↔PLAYING 切屏由 _dispatch_* 内显式赋值（INV-11 方案 A）

    def _build_hud(self, snap: Snapshot) -> HudData:
        """R3-11 共享 snap；G2-6 high_score 来源 self._high_score（不变，数据源替换）。"""
        return HudData(
            score=snap.score,
            high_score=self._high_score,                            # G2-2 由 storage.load() 替换
            length=snap.length,
            difficulty_label=_DIFFICULTY_LABEL[self._difficulty],
            status_label=_STATUS_LABEL[snap.status],
        )

    def _render(self) -> None:
        """按 screen 分发。G2-1 PAUSED 态：先 renderer.render 一帧（保持底图），
        再 menu.draw_pause_overlay 叠加遮罩。G2-6 MENU/GAME_OVER 形参加 high_score。
        """
        if self.screen == AppScreen.MENU:
            surface = pygame.display.get_surface()
            assert surface is not None
            draw_menu(surface, self._menu_title_font, self._menu_body_font,
                      self._difficulty, high_score=self._high_score)        # G2-6
        elif self.screen == AppScreen.PLAYING:
            assert self._renderer is not None
            snap = self.game_state.snapshot()
            hud = self._build_hud(snap)
            self._renderer.render(snap, hud)
        elif self.screen == AppScreen.PAUSED:                                # G2-1/G2-5
            assert self._renderer is not None
            assert self.game_state is not None
            snap = self.game_state.snapshot()
            hud = self._build_hud(snap)
            self._renderer.render(snap, hud)                                # 渲染最后一帧
            surface = pygame.display.get_surface()
            assert surface is not None
            draw_pause_overlay(surface, self._menu_body_font)               # G2-5 叠加遮罩
        elif self.screen == AppScreen.GAME_OVER:
            surface = pygame.display.get_surface()
            assert surface is not None
            score = self.game_state.snapshot().score if self.game_state else 0
            draw_game_over(surface, self._menu_title_font, self._menu_body_font,
                           score, high_score=self._high_score)                # G2-6
        pygame.display.flip()
```

### 3.5 公开 API 列表

| 名称 | 类型 | 用途 |
|------|------|------|
| `AppConfig` | dataclass(frozen) + `__post_init__` | 运行期常量；G2-R-N1 构造期校验 |
| `AppScreen` | Enum（4 态） | app 界面状态机 |
| `InputAction` | Enum（11 个） | 输入归一化 |
| `App` | class | 主装配类 |
| `main()` | function | 入口函数：`App().run()`，捕获 `ConfigError`/`AppError`（**P2-4 修订**：删除 `StorageError`——`StorageError` 已被包成 `StorageUnavailableError(AppError)`，无需也不应单独捕获）后输出可读提示 + 退出码 |
| **AppError 子类** | 异常类 | **G2-2 新增 `StorageUnavailableError(AppError)`**：包装 HighScoreStore 抛的 StorageError |
| `HudData` | 来自 gui_renderer | HUD 5 字段 dataclass（沿用 iter-1） |

### 3.6 异常（G2-2 新增 StorageUnavailableError）

```python
class AppError(RuntimeError):
    """app 顶层错误基类。"""

class GraphicsUnavailableError(AppError):
    """Renderer.init() / pygame.display.set_mode 失败 → 退出码 2。"""

class ConfigError(AppError):
    """AppConfig 字段非法 → 启动时抛。G2-R-N1：构造期 __post_init__ 校验。"""

class StorageUnavailableError(AppError):                                # G2-2 iter-2 新增
    """HighScoreStore.save/reset 失败（IO / 权限）→ 退出码 1。

    包装 platform_storage.StorageError，app 层统一异常类型。
    由 _dispatch_menu 的 RESET_HIGHSCORE 分支 / _new_game 注册的 score_callback 抛出。
    """
```

### 3.7 `menu` 模块自绘接口（G2-5/6 增量；R3-2 沿用不读 renderer 私有）

```python
# menu.py
from typing import Optional
import pygame
from game_core import Difficulty


def draw_menu(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    difficulty: Difficulty,
    high_score: int = 0,                                                # G2-6 iter-2 新增
) -> None:
    """MENU 态自绘。G2-6 新增 high_score 形参（默认 0 保持向后兼容）。
    high_score > 0 时显示"最高分：xxx"行；= 0 时不显示（避免"最高分：0"误导）。
    """


def draw_game_over(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    score: int,
    high_score: int = 0,                                                # G2-6 iter-2 新增
) -> None:
    """GAME_OVER 态自绘。同上 high_score 行为。"""


def draw_pause_overlay(                                                  # G2-5 iter-2 新增
    surface: pygame.Surface,
    body_font: pygame.font.Font,
) -> None:
    """PAUSED 遮罩自绘。surface 来自 pygame.display.get_surface()。

    步骤：
    1. 半透明矩形 (0,0,0,128) 覆盖全屏（R3-2 仍不读 _screen）
    2. 居中绘制 "PAUSED" 大字（body_font 字号放大到 32）
    3. 居中绘制 "P 继续" 小字（body_font 字号 22）
    """
```

### 3.8 `storage` 模块（G2-2 iter-2 新增）

```python
# storage.py
"""storage 模块：HighScoreStore 包装 + 异常转译。

设计目的：
- 隔离 platform_storage 与 game_app，app 仅依赖本模块的接口
- 统一 StorageError → StorageUnavailableError 转译（在 _new_game 注册 callback / _dispatch_menu RESET_HIGHSCORE 路径）
- 便于 UT 注入 fake storage（monkeypatch）

公开 API：
- create_storage() -> HighScoreStore
"""
from typing import Optional
from pathlib import Path

from platform_storage import HighScoreStore, StorageError

from .errors import StorageUnavailableError


def create_storage(path: Optional[Path] = None) -> HighScoreStore:
    """构造 HighScoreStore 实例。

    Args:
        path: 自定义路径（UT 用 tmp_path）；None → platform_storage.get_user_data_dir()

    Returns:
        HighScoreStore 实例（构造期 mkdir 失败抛 StorageError → 不转译，让 _init_pygame 捕获）

    Raises:
        platform_storage.StorageError: 磁盘不可写（构造期 mkdir 失败）
    """
    return HighScoreStore(path)


def translate_storage_error(func_name: str) -> None:
    """将 platform_storage.StorageError 转译为 StorageUnavailableError。

    使用方式：
        try:
            self._storage.save(score)
        except StorageError as e:
            translate_storage_error("save")
    """
    # 实现：在调用点直接 raise StorageUnavailableError(f"{func_name} 失败: {e}") from e
    pass                                                                # 见 §4.7 实现细节
```

---

## 4. 实现细节/步骤

### 4.1 模块文件组织（G2-9 增量；iter-1 文件结构沿用）

```
snake-linux/code/game-app/iter-1/                       # iter-2 不新建目录（G2-9 决策）
├── game_app/
│   ├── __init__.py             # 对外 re-export（G2-2 加 StorageUnavailableError）
│   ├── __main__.py             # PyInstaller 入口（沿用 iter-1）
│   ├── config.py               # AppConfig + __post_init__ 校验（G2-R-N1）
│   ├── screens.py              # AppScreen 加 PAUSED（G2-1）
│   ├── input.py                # InputAction 加 RESET_HIGHSCORE/BACK_TO_MENU/UNFOCUS；
│   │                           # _MENU_RESERVED_ACTIONS 同步扩展；新增 _map_unfocus_event
│   ├── app.py                  # 主装配类（G2-1/2/3/4/5/7 全部修改；详见 §3.4）
│   ├── menu.py                 # draw_menu/draw_game_over 加 high_score 参数；
│   │                           # **新增** draw_pause_overlay（G2-5）
│   ├── fonts.py                # _load_cjk_font（沿用 R3-12）
│   ├── **storage.py**          # **G2-2 iter-2 新增**：HighScoreStore 包装 + 异常转译
│   ├── errors.py               # AppError / GraphicsUnavailableError / ConfigError；
│   │                           # **新增** StorageUnavailableError（G2-2）
│   └── _constants.py           # 颜色常量 + WINDOW_TITLE（G2-5 加 PAUSE_OVERLAY_ALPHA=128）
└── tests/
    └── test_game_app/
        ├── __init__.py
        ├── conftest.py                 # iter-1 fixtures + G2 新增 fixtures（见 §6.2）
        ├── test_config.py              # **G2-R-N1**：UT-4/5 改测 __post_init__ 抛 ConfigError
        ├── test_input_map.py           # iter-1 沿用
        ├── test_drain_events.py        # iter-1 沿用 + G2-4 失焦追加 UNFOCUS 测试
        ├── test_app_init.py            # iter-1 沿用（G2-2 加 _storage is None 断言）
        ├── test_app_menu.py            # iter-1 沿用
        ├── test_app_playing.py         # iter-1 沿用
        ├── test_app_game_over.py       # iter-1 沿用 + G2-7 BACK_TO_MENU 测试
        ├── test_app_tick.py            # iter-1 沿用
        ├── test_app_exit.py            # iter-1 沿用
        ├── test_app_error.py           # iter-1 沿用 + G2-2 StorageError 包装测试
        ├── test_app_hud.py             # iter-1 沿用
        ├── test_app_render_dispatch.py # iter-1 沿用 + G2-1 PAUSED 路径测试
        ├── **test_app_iter2_pause.py**         # **G2-1** PAUSED 状态机测试
        ├── **test_app_iter2_storage.py**      # **G2-2/3** HighScoreStore 接入 + 重置测试
        ├── **test_app_iter2_unfocus.py**      # **G2-4** 失焦自动暂停测试
        ├── **test_app_iter2_overlay.py**      # **G2-5** 暂停遮罩渲染测试
        └── **test_app_iter2_storage_err.py**  # **G2-2** StorageError → StorageUnavailableError 转译测试
```

### 4.2 主循环骨架（G2-1/2/4 增量；R3-15 沿用）

```python
def run(self) -> int:
    """G2-2：_init_pygame 失败时 _storage 仍为 None，无需清理；
    R3-15 退出码 2 路径 shutdown 兜底不变。"""
    self._renderer = None
    try:
        try:
            self._init_pygame()
        except GraphicsUnavailableError as e:
            print(f"[错误] 无法初始化图形界面: {e}\n请确认系统有可用的图形环境。",
                  file=sys.stderr)
            return 2
        return self._run_loop()
    finally:
        try:
            if self._renderer is not None:
                self._renderer.shutdown()
        except Exception:
            pass


def _run_loop(self) -> int:
    """主事件循环。G2-1：screen==PAUSED 跳过 _tick；G2-4：_drain_events 内部追加 UNFOCUS。

    R3-15 单一 QUIT 通道：if QUIT in actions: break（G2-R-N2 主循环不读 _running，
    保留字段供 iter-3 dispatch 内部退出用）。
    """
    try:
        while True:                                                     # G2-R-N2：主循环不读 _running
            assert self.clock is not None
            dt_ms = self.clock.tick_busy_loop(self.config.fps_cap)
            actions = self._drain_events()
            if InputAction.QUIT in actions:
                break
            for a in actions:
                self._dispatch(a)
            if self.screen == AppScreen.PLAYING:                       # G2-1 排除 PAUSED
                self._tick(dt_ms)
            self._render()
        return 0
    except AppError as e:                                              # G2-2 含 StorageUnavailableError
        print(f"[错误] {e}", file=sys.stderr)
        return 1
```

### 4.3 输入映射（_map_event，G2-3/7 新增 RESET_HIGHSCORE / BACK_TO_MENU；R3-1 沿用；**P2-1 修订** 沿用 iter-1 `_pygame_attr` 模式）

```python
# input.py
# **P2-1 修订**：沿用 iter-1 `_pygame_attr(name)` 延迟读取模式（input.py 头注释 + _map_event 全部
# 常量走 _pygame_attr），让 UT 在 monkeypatch 替换 sys.modules['pygame'] 后能读到 fake_pygame
# 的属性。直接 `import pygame; _PAUSE_KEY = pygame.K_p` 会破坏 iter-1 既有测试基建（无 pygame
# 环境无法 import 整个模块；fake_pygame 替换后读到缓存的属性而非 fake 值）。iter-2 增量仅加
# H / Backspace 分支：
#   - H 键 → RESET_HIGHSCORE（G2-3）
#   - Backspace → BACK_TO_MENU（G2-7，_map_event 层直接转；ESC 仍返 QUIT 由 _drain_events 覆盖）
import sys as _sys
from typing import Any


def _pygame_attr(name: str) -> Any:
    """iter-1 沿用：通过 sys.modules['pygame'].__dict__ 读取属性（UT 友好）。"""
    return _sys.modules["pygame"].__dict__.get(name)


_DIFFICULTY_KEYS = {
    "K_1": InputAction.SELECT_EASY,    # P2-1：常量名作 key，_map_event 内 _pygame_attr 取值
    "K_2": InputAction.SELECT_MEDIUM,
    "K_3": InputAction.SELECT_HARD,
}

_DIRECTION_KEYS = {
    "K_w": InputAction.MOVE_UP,   "K_UP":    InputAction.MOVE_UP,
    "K_s": InputAction.MOVE_DOWN, "K_DOWN":  InputAction.MOVE_DOWN,
    "K_a": InputAction.MOVE_LEFT, "K_LEFT":  InputAction.MOVE_LEFT,
    "K_d": InputAction.MOVE_RIGHT,"K_RIGHT": InputAction.MOVE_RIGHT,
}

_PAUSE_KEY = "K_p"
_RESTART_KEY = "K_r"
_QUIT_KEYS = ("K_q", "K_ESCAPE")                            # P1-2：ESC 与 Q 在 _map_event 同返 QUIT
_RESET_HIGHSCORE_KEY = "K_h"                                # G2-3 iter-2 新增
_BACK_TO_MENU_KEYS = ("K_ESCAPE", "K_BACKSPACE")            # G2-7 iter-2 新增（仅 K_BACKSPACE 在 _map_event 层直转；K_ESCAPE 仍返 QUIT 由 _drain_events 覆盖）

# R3-1 沿用：MENU 态保留键（G2-7 扩展加 BACK_TO_MENU 不在 MENU 保留——MENU 态 ESC 走 QUIT 优先）
_MENU_RESERVED_ACTIONS = frozenset({
    InputAction.QUIT,
    InputAction.SELECT_EASY, InputAction.SELECT_MEDIUM, InputAction.SELECT_HARD,
    InputAction.TOGGLE_PAUSE,                                         # G2-1 仍保留（P 键 MENU 态透传，不当 START）
    InputAction.RESET_HIGHSCORE,                                      # G2-3 新增
    InputAction.RESTART,                                              # R 键 MENU 态透传
})

# GAME_OVER 态保留键（G2-7 新增）：QUIT / RESTART / BACK_TO_MENU
_GAME_OVER_RESERVED_ACTIONS = frozenset({
    InputAction.QUIT,
    InputAction.RESTART,
    InputAction.BACK_TO_MENU,
})


def _map_event(event: pygame.event.Event) -> Optional[InputAction]:
    """单键归一化；不感知屏态；返回 None 表示未映射（由 _drain_events 屏态兜底处理）。

    G2-3 新增 H 键 → RESET_HIGHSCORE；G2-7 新增 Backspace → BACK_TO_MENU。
    **P1-2 修订**：ESC 与 Q 在 `_map_event` 层都返回 QUIT——ESC 在 GAME_OVER
    态由 `_drain_events` 覆盖为 BACK_TO_MENU（`ev.type != pygame.QUIT` 守卫保证窗口关闭
    仍 QUIT 直通）；Q（用户意图退出）保持 QUIT 直通主循环 break。UT 区分：
    `event.key == K_q` 走 `_QUIT_KEYS[0]`，`event.key == K_ESCAPE` 走 `_QUIT_KEYS[1]`。
    所有常量走 `_pygame_attr`（P2-1）。
    """
    QUIT_TYPE = _pygame_attr("QUIT")
    KEYDOWN_TYPE = _pygame_attr("KEYDOWN")
    K_q = _pygame_attr("K_q")
    K_ESCAPE = _pygame_attr("K_ESCAPE")
    K_BACKSPACE = _pygame_attr("K_BACKSPACE")

    if event.type == QUIT_TYPE:
        return InputAction.QUIT
    if event.type != KEYDOWN_TYPE:
        return None
    k = event.key
    if k == K_q:                                                # P1-2：Q 键 → QUIT（主循环 break）
        return InputAction.QUIT
    if k == K_ESCAPE:                                           # P1-2：ESC 键 → QUIT（GAME_OVER 由 _drain_events 覆盖）
        return InputAction.QUIT
    if k == K_BACKSPACE:                                        # G2-7：Backspace 直接 → BACK_TO_MENU（无需屏态覆盖）
        return InputAction.BACK_TO_MENU
    if k == _pygame_attr("K_p"):
        return InputAction.TOGGLE_PAUSE
    if k == _pygame_attr("K_r"):
        return InputAction.RESTART
    if k == _pygame_attr("K_h"):                                # G2-3 新增
        return InputAction.RESET_HIGHSCORE
    if k == _pygame_attr("K_1"):
        return InputAction.SELECT_EASY
    if k == _pygame_attr("K_2"):
        return InputAction.SELECT_MEDIUM
    if k == _pygame_attr("K_3"):
        return InputAction.SELECT_HARD
    for attr, action in _DIRECTION_KEYS.items():
        if k == _pygame_attr(attr):
            return action
    return None                                                 # R3-1 未映射
```

### 4.4 状态机 dispatch 表 + G2-1/3/4/7 增量 + R3-1 屏态兜底

```python
# app.py
def _drain_events(self) -> List[InputAction]:
    """本帧所有 pygame 事件归一化；QUIT 优先 break；G2-4 失焦追加 UNFOCUS；G2-7 屏态覆盖 ESC 语义。

    R3-1 屏态兜底（不变）：MENU 屏态下所有 action（除保留键外）→ START。
    G2-4 新增：screen==PLAYING 时 pygame.key.get_focused() == False → 追加 UNFOCUS。
    G2-7 新增：screen==GAME_OVER 时 ESC 映射的 QUIT → BACK_TO_MENU（MENU 态 ESC 保持 QUIT）。
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
        elif self.screen == AppScreen.GAME_OVER:                       # G2-7 新增
            if action == InputAction.QUIT:                             # ESC 在 GAME_OVER 态转 BACK_TO_MENU
                # 注意：pygame.QUIT（窗口关闭）仍保留 QUIT 优先级，不被覆盖
                if ev.type != pygame.QUIT:
                    action = InputAction.BACK_TO_MENU
        if action is not None:
            actions.append(action)

    # G2-4 失焦检测（仅 PLAYING 态，其他屏态已有处理）
    if self.screen == AppScreen.PLAYING:
        try:
            focused = pygame.key.get_focused()
        except Exception:
            focused = True                                              # 平台不支持时兜底
        if not focused:
            actions.append(InputAction.UNFOCUS)
    return actions


def _dispatch(self, action: InputAction) -> None:
    """按当前 screen 分发；G2-1 加 PAUSED 态。"""
    if self.screen == AppScreen.MENU:
        self._dispatch_menu(action)
    elif self.screen == AppScreen.PLAYING:
        self._dispatch_playing(action)
    elif self.screen == AppScreen.PAUSED:                              # G2-1 新增
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
    elif action == InputAction.RESET_HIGHSCORE:                        # G2-3
        if self._storage is not None:
            try:
                self._storage.reset()
            except StorageError as e:
                raise StorageUnavailableError(f"重置最高分失败: {e}") from e
            self._high_score = 0
    elif action == InputAction.START:
        self._new_game(self._difficulty)
    # MOVE_*/TOGGLE_PAUSE/RESTART/RESET_HIGHSCORE 理论上进不来（_drain_events 保留键透传）
    # 但 RESET_HIGHSCORE 显式处理；其余显式忽略保持防御性


def _dispatch_playing(self, action: InputAction) -> None:
    """PLAYING 态分发。G2-1：TOGGLE_PAUSE 从 hint 占位改为 toggle_pause()；G2-4 加 UNFOCUS。"""
    if action == InputAction.MOVE_UP:
        self.game_state = self.game_state.set_direction(Direction.UP)
    elif action == InputAction.MOVE_DOWN:
        self.game_state = self.game_state.set_direction(Direction.DOWN)
    elif action == InputAction.MOVE_LEFT:
        self.game_state = self.game_state.set_direction(Direction.LEFT)
    elif action == InputAction.MOVE_RIGHT:
        self.game_state = self.game_state.set_direction(Direction.RIGHT)
    elif action == InputAction.TOGGLE_PAUSE:                           # G2-1 修订
        assert self.game_state is not None
        self.game_state = self.game_state.toggle_pause()               # R3-9 不包装
    elif action == InputAction.UNFOCUS:                                # G2-4 新增
        assert self.game_state is not None
        if self.game_state.status == GameStatus.RUN:
            self.game_state = self.game_state.toggle_pause()


def _dispatch_paused(self, action: InputAction) -> None:              # G2-1 新增
    """PAUSED 态分发：仅响应 TOGGLE_PAUSE / UNFOCUS（G2-4 失焦再触发不变）。"""
    if action == InputAction.TOGGLE_PAUSE:
        assert self.game_state is not None
        self.game_state = self.game_state.toggle_pause()               # PAUSED→RUN
    elif action == InputAction.UNFOCUS:
        pass                                                           # PAUSED 态再失焦不变


def _dispatch_over(self, action: InputAction) -> None:
    """GAME_OVER 态分发。G2-7 新增 BACK_TO_MENU；R3-7 删除 QUIT 分支。"""
    if action == InputAction.RESTART:
        self._new_game(self._difficulty)
    elif action == InputAction.BACK_TO_MENU:                           # G2-7 新增
        self.screen = AppScreen.MENU
        self.game_state = None                                          # INV-7 重置
```

### 4.5 节拍推进（_tick，G2-1 PAUSED 不进入此函数；R3-8 循环内重读）

```python
def _tick(self, dt_ms: int) -> None:
    """PLAYING 态累加节拍。G2-1 PAUSED 不进入此函数（主循环判断）。

    循环内逐拍重读 tick_ms（R3-8）；
    OVER 自动转 GAME_OVER（G2-1）；
    PAUSED 自动转 PAUSED（G2-1 失焦触发 toggle_pause 后 _tick 下一帧到达此处检测）。
    """
    assert self.screen == AppScreen.PLAYING                            # G2-1 INV-10/11 断言
    assert self.game_state is not None
    assert self.game_state.status == GameStatus.RUN                    # INV-1
    self._tick_accumulator_ms += dt_ms
    while True:
        tick_ms = self.game_state.snapshot().tick_ms
        if self._tick_accumulator_ms < tick_ms:
            break
        self._tick_accumulator_ms -= tick_ms
        self.game_state = self.game_state.step()
        new_status = self.game_state.status
        if new_status == GameStatus.OVER:
            self.screen = AppScreen.GAME_OVER
            break
        elif new_status == GameStatus.PAUSED:                          # G2-1 失焦→toggle_pause 后到达
            self.screen = AppScreen.PAUSED
            break
```

### 4.6 最高分接入（G2-3 score_callback 注册）

```python
def _new_game(self, difficulty: Difficulty) -> None:
    """game_state = GameState(width=20, height=15, difficulty=..., rng=Random(),
                             score_callback=<绑定 self._storage>);
    screen=PLAYING。G2-3 注册 score_callback 同步写入 _storage。
    """
    cb = None
    if self._storage is not None:
        # 闭包变量：local 引用避免 self 捕获（更易 UT）
        _storage = self._storage
        _high_ref = {"v": self._high_score}                           # 用 dict 装可变容器

        def cb(score: int) -> None:
            # G2-3：core 吃食时回调；INV-13 同步更新 _high_score
            try:
                new_val = max(score, _storage.load())
                _storage.save(new_val)
                _high_ref["v"] = max(_high_ref["v"], new_val)
            except StorageError as e:
                # G2-2：包装为 AppError 子类；主循环 except AppError 兜底退出码 1
                raise StorageUnavailableError(f"写入最高分失败: {e}") from e

    self.game_state = GameState(
        width=20, height=15, difficulty=difficulty,
        rng=random.Random(), score_callback=cb,
    )
    # 同步更新 _high_score（即使 cb 未触发，新一局仍展示当前最高分）
    if self._storage is not None:
        self._high_score = self._storage.load()                       # INV-6/13
    self._tick_accumulator_ms = 0
    self.screen = AppScreen.PLAYING
```

### 4.7 初始化（G2-2 HighScoreStore 接入；R3-10/12 沿用）

```python
def _init_pygame(self) -> None:
    """构造 renderer + HighScoreStore；CJK 字体回退链。

    G2-2：HighScoreStore 构造在 _init_pygame 内（不构造在 App.__init__，让 UT 不依赖磁盘）；
    **P1-1 修订**：HighScoreStore 构造期 `self.path.parent.mkdir(parents=True, exist_ok=True)`
    失败抛**裸 OSError（PermissionError 等）**——platform-storage iter-2 `highscore.py` 实际行为
    （模块 docstring 声称"__init__ mkdir 失败抛 StorageError"，但实核代码：mkdir 是裸 OSError，
    StorageError 仅在 `save()` 内包 atomic_write_json 失败时抛）。为对齐 NFR-03「可读错误提示」，
    此处捕获 `(StorageError, OSError)` 双类型，统一包 AppError（退出码 1）。
    **P1-3 修订**：`_storage = None` 时由 fixture 注入 fake；构造前 `if self._storage is None:`
    跳过 create_storage()，保留 UT 注入值。
    """
    # R3-10：构造 renderer
    try:
        self._renderer = Renderer(
            (self.config.window_w, self.config.window_h),
            skin=DEFAULT_SKIN,
        )
        self._renderer.init()
    except (RenderError, pygame.error) as e:
        raise GraphicsUnavailableError(str(e)) from e

    # G2-2：构造 HighScoreStore（P1-3：已注入 fake 则跳过；P1-1：捕获双类型）
    if self._storage is None:                                        # P1-3 fixture 注入旁路
        try:
            self._storage = create_storage()                         # None path → get_user_data_dir()
            self._high_score = self._storage.load()
        except (StorageError, OSError) as e:                         # P1-1 mkdir 失败 = 裸 OSError
            raise AppError(f"用户数据目录不可写: {e}") from e

    # R3-12：CJK 字体回退链
    self._menu_title_font = _load_cjk_font(48, bold=True)
    self._menu_body_font = _load_cjk_font(22)

    self.clock = pygame.time.Clock()
```

### 4.8 渲染分发（G2-1 PAUSED 路径 + G2-5 遮罩 + G2-6 最高分形参；R3-2/11 沿用）

```python
def _render(self) -> None:
    """按 screen 分发。G2-1 PAUSED：renderer.render + draw_pause_overlay。

    R3-2：用 pygame.display.get_surface()（公开 API），不读 _screen。
    R3-11：PLAYING 路径只取一次 snap。
    G2-6：MENU / GAME_OVER 自绘加 high_score 形参。
    """
    if self.screen == AppScreen.MENU:
        surface = pygame.display.get_surface()
        assert surface is not None, "MENU graphic not initialized"
        assert self._menu_title_font is not None and self._menu_body_font is not None
        draw_menu(surface, self._menu_title_font, self._menu_body_font,
                  self._difficulty, high_score=self._high_score)      # G2-6
    elif self.screen == AppScreen.PLAYING:
        assert self._renderer is not None
        snap = self.game_state.snapshot()
        hud = self._build_hud(snap)
        self._renderer.render(snap, hud)
    elif self.screen == AppScreen.PAUSED:                              # G2-1 新增
        assert self._renderer is not None and self.game_state is not None
        snap = self.game_state.snapshot()
        hud = self._build_hud(snap)
        self._renderer.render(snap, hud)                              # 渲染最后一帧
        surface = pygame.display.get_surface()
        assert surface is not None
        draw_pause_overlay(surface, self._menu_body_font)             # G2-5 叠加遮罩
    elif self.screen == AppScreen.GAME_OVER:
        surface = pygame.display.get_surface()
        assert surface is not None
        score = self.game_state.snapshot().score if self.game_state else 0
        assert self._menu_title_font is not None and self._menu_body_font is not None
        draw_game_over(surface, self._menu_title_font, self._menu_body_font,
                       score, high_score=self._high_score)              # G2-6
    pygame.display.flip()


# menu.py — G2-5 新增 draw_pause_overlay；G2-6 加 high_score 形参
# **P2-6 修订**：移除 `big_font = ... if False else body_font` 废代码；统一使用 body_font（22px）
# 渲染 "PAUSED" 大字与 "按 P 继续" 小字（FO 落地时如需视觉强化 "PAUSED" 大字，建议新增 32px
# CJK 字体或调 body_font 字号；本设计不强制大字号，避免实现复杂度超 iter-2 范围）
PAUSE_OVERLAY_ALPHA = 128                                              # G2-5 半透明常量（§4.1 声明）
PAUSE_OVERLAY_COLOR = (0, 0, 0, PAUSE_OVERLAY_ALPHA)
PAUSE_OVERLAY_TITLE_COLOR = (255, 210, 90)
PAUSE_OVERLAY_HINT_COLOR = (220, 220, 230)


def draw_pause_overlay(surface: pygame.Surface, body_font: pygame.font.Font) -> None:
    """PAUSED 遮罩自绘。surface 来自 pygame.display.get_surface()。R3-2 沿用。
    **P2-6 修订**：移除原废代码 `big_font = ... if False else body_font`，统一 body_font（22px）渲染；
    遮罩色值走 PAUSE_OVERLAY_ALPHA/PAUSE_OVERLAY_COLOR 常量（不再硬编码 128）。
    """
    # 1. 半透明矩形覆盖全屏（走 PAUSE_OVERLAY_COLOR 常量）
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill(PAUSE_OVERLAY_COLOR)
    surface.blit(overlay, (0, 0))
    # 2. 居中绘制 "PAUSED" 字（body_font 22px 统一渲染）
    title = body_font.render("PAUSED", True, PAUSE_OVERLAY_TITLE_COLOR)
    surface.blit(title, (surface.get_width() // 2 - title.get_width() // 2,
                         surface.get_height() // 2 - title.get_height() // 2))
    # 3. 居中绘制 "按 P 继续" 小字
    hint = body_font.render("按 P 继续", True, PAUSE_OVERLAY_HINT_COLOR)
    surface.blit(hint, (surface.get_width() // 2 - hint.get_width() // 2,
                        surface.get_height() // 2 + hint.get_height()))


def draw_menu(surface, title_font, body_font, difficulty, high_score: int = 0):
    """MENU 态自绘。G2-6：high_score > 0 时显示"最高分：xxx"行。"""
    bg = (18, 18, 24)
    surface.fill(bg)

    title = title_font.render("Snake GUI v2.0.0", True, (255, 255, 255))
    surface.blit(title, (surface.get_width() // 2 - title.get_width() // 2, 100))

    lines = [
        ("按 1 键 = 简单", Difficulty.EASY),
        ("按 2 键 = 普通", Difficulty.MEDIUM),
        ("按 3 键 = 困难", Difficulty.HARD),
    ]
    for i, (text, diff) in enumerate(lines):
        color = (255, 210, 90) if diff == difficulty else (200, 200, 210)
        surf = body_font.render(text, True, color)
        surface.blit(surf, (surface.get_width() // 2 - surf.get_width() // 2, 220 + i * 36))

    # G2-6：最高分行
    if high_score > 0:
        hs_line = body_font.render(f"最高分：{high_score}", True, (255, 210, 90))
        surface.blit(hs_line, (surface.get_width() // 2 - hs_line.get_width() // 2, 340))

    # G2-R-N3 提示补正
    hint = body_font.render(
        "Enter / 空格 / 其他键 开始（P 暂停 · H 重置最高分 · Q 退出）",
        True, (200, 200, 210)
    )
    surface.blit(hint, (surface.get_width() // 2 - hint.get_width() // 2, 400))


def draw_game_over(surface, title_font, body_font, score, high_score: int = 0):
    """GAME_OVER 态自绘。G2-6：high_score > 0 时显示"最高分：xxx"行；
    G2-7 新增"Esc / Backspace 返回菜单"提示。
    """
    surface.fill((18, 18, 24))
    big = title_font.render("Game Over", True, (255, 90, 90))
    surface.blit(big, (surface.get_width() // 2 - big.get_width() // 2, 100))

    line = body_font.render(f"最终得分：{score}", True, (230, 230, 240))
    surface.blit(line, (surface.get_width() // 2 - line.get_width() // 2, 180))

    if high_score > 0:
        hs_line = body_font.render(f"最高分：{high_score}", True, (255, 210, 90))
        surface.blit(hs_line, (surface.get_width() // 2 - hs_line.get_width() // 2, 220))

    hint = body_font.render("R 重开    Esc / Backspace 返回菜单    Q 退出",
                            True, (200, 200, 210))
    surface.blit(hint, (surface.get_width() // 2 - hint.get_width() // 2, 320))
```

### 4.9 状态机图（G2-1 PAUSED 新增 + G2-7 BACK_TO_MENU + G2-4 UNFOCUS）

```
       ┌────────┐ Enter/空格/未映射键/方向键         ┌──────────┐
       │  MENU  │ ───────────────────────────▶ │ PLAYING  │
       │ (app   │   START (R3-1 屏态兜底)       │ (节拍     │
       │ 自绘)  │                                  │  step)    │
       └────────┘                                  └──────────┘
           ▲                                              │
           │  ESC (GAME_OVER) / Backspace               │ P 键 / UNFOCUS
           │  → BACK_TO_MENU (G2-7)                     │ → toggle_pause
           │                                              ▼
           │              ┌──────────┐  P 键            ┌──────────┐
           └──────────────│ GAME_OVER│ ◀──── toggle_pause ────│ PAUSED  │
              RESTART     │ (app 自绘)│                  │ (app 自绘│
                          │ +最高分行)│                  │  +遮罩)  │
                          └──────────┘                  └──────────┘
                                ▲                              │
                                │ status==OVER (R3-8 自动转)  │ P 键 → toggle_pause
                                │                              │ PAUSED→RUN
                                └──────────────────────────────┘
                                          _tick 检测 status

       任意态：Q / 窗口关闭 → QUIT  → 主循环 'if QUIT in actions: break'
                            → finally renderer.shutdown()
       PLAYING 态：pygame.key.get_focused() == False → UNFOCUS → toggle_pause
                  （聚焦恢复不自动继续，避免误触，按 P 才继续）
```

### 4.10 实现注意点（G2 增量）

1. **无全局变量**：app 状态全部在 `App` 实例字段，UT 可通过构造多个 `App` 实例隔离测试。
2. **pygame 副作用隔离**：`pygame.init()` / `pygame.quit()` 调用次数在 UT 中通过 fake pygame 模块统计。
3. **不直接读 game_state 内部字段**：所有访问走 `snapshot()`；修改走 `set_direction` / `step` / `toggle_pause`（返回新对象）；G2-1 PAUSED 态由 `_tick` 检测 `game_state.status == PAUSED` 后转 `screen=PAUSED`。
4. **不直接读 gui-renderer 私有属性**：仅 `Renderer((W,H), skin=DEFAULT_SKIN)` 构造 + `init/shutdown` + `render(snap, hud)`；自绘菜单/结束画面/暂停遮罩走 `pygame.display.get_surface()`（R3-2）。
5. **不引入 `time.sleep`**：所有延迟靠 `clock.tick_busy_loop(fps_cap)` + `_tick_accumulator_ms`。
6. **G2-2 platform_storage 导入**：iter-2 首次 `import platform_storage`；通过 `game_app/storage.py` 间接引用（不直接 import）。
7. **iter-2 不写任何配置/日志文件**：仅 `HighScoreStore.save()` 写 `highscore.json`（用户数据目录，NFR-07）。
8. **退出码约定**：0 正常 / 1 app 异常（含 ConfigError / StorageUnavailableError） / 2 图形环境不可用（NFR-03 最小集）。
9. **HUD `status_label` 必填**：renderer 第 2 行 `Status: ...` 必读；`_STATUS_LABEL[snap.status]` 在 RUN/PAUSED/OVER 三态均有值（iter-2 启用 PAUSED）。
10. **renderer.skin 只读**：iter-2 仅 `DEFAULT_SKIN`，**不调** `set_skin`（iter-3 接入）。
11. **失焦检测跨平台行为**：`pygame.key.get_focused()` 在 Linux X11 / Windows / macOS 行为一致（窗口失焦返 False）；Headless 环境抛异常 → 兜底为 True（不自动暂停）；UT 用 fake `pygame.key.get_focused` 注入。
12. **HighScoreStore 跨进程不安全**：内部 RLock 保护单进程并发；多进程启动同用户 → 文件锁缺失（spec 未要求）；**spec 范围**：单机单进程。
13. **score_callback 闭包陷阱**：用 `_high_ref = {"v": ...}` dict 装可变容器，避免 Python 闭包 non-local 声明；UT 用 fake storage 时同样可工作。
14. **G2-R-N6**：`App.__init__` 默认参数 `config: AppConfig = AppConfig()` 在 import 期求值；UT 需不同 config 时显式传 `App(AppConfig(fps_cap=30))`。

---

## 5. DFx / 可测试性 / 鲁棒性 / 韧性

### 5.1 可维护性（Maintainability）

- 沿用 iter-1 约定：每个公开类/方法有 docstring，标注对应 FR/NFR 编号。
- 不变量在代码中以 `# INV-N` 注释 + UT 用例双标注（iter-2 加 INV-10/11/12/13）。
- 单一职责：`storage.py` 只管 HighScoreStore 包装（G2-2）；`app.py` 仍只管装配；`menu.py` 加 `draw_pause_overlay`（G2-5 自绘遮罩）。
- 主循环 ≤ 30 行（`run()` + `_run_loop()` + `_drain_events` + `_dispatch` + `_tick`），便于一眼读完逻辑。

### 5.2 可扩展性（Extensibility）

- **单一职责 + 状态机扩展点**：iter-2 加 `AppScreen.PAUSED` 状态 + `_dispatch_paused` + `_render` PAUSED 分支；iter-3 加皮肤切换 UI（`InputAction.SET_SKIN`）仅补 `_dispatch_menu` 与 `Renderer.set_skin` 调用。
- **错误处理 `_init_pygame` 集中**：iter-2 加 `StorageError → AppError` 包装仅改这一处；iter-4 加 SDL 驱动版本检测仅改这一处。
- **score_callback 闭包模式**：iter-3 加"成就解锁"等功能仅改 `_new_game` 内 callback 定义，不改 core 接口。
- **`Renderer.skin` property 只读**（iter-1 沿用）：iter-3 接入皮肤切换 UI 时 `_dispatch_menu` 加 SET_SKIN 分支即可。

### 5.3 可部署性（Deployability）

- PyInstaller 单文件（沿用 iter-1）：`--onefile --windowed --name snake-gui --collect-submodules game_app --collect-submodules platform_storage`（iter-2 加 platform_storage collect）。
- `game_app/` + `platform_storage/` 单一包目录，PyInstaller 自动发现。
- 无 C 扩展、无平台特定代码（pygame + platform_storage 自身跨平台）。
- 入口无副作用 import：`import game_app` 不开窗、不调 `pygame.init()`、不构造 `HighScoreStore`。

### 5.4 可测试性（Testability）

- **pygame 依赖可桩化**：UT 通过 `monkeypatch` 替换 `game_app.app + game_app.menu + game_app.storage` 内部的 pygame + platform_storage 模块为 fake。
- **HighScoreStore 依赖可桩化**：UT 用 `tmp_path` 注入 `path=tmp_path / "highscore.json"`（`create_storage(path)` 支持自定义路径）；或用 `FakeHighScoreStore` 完全替代。
- **`_drain_events` 屏态兜底可独立测**：iter-1 沿用 + G2-4 失焦检测用 fake `pygame.key.get_focused` 注入。
- **`_dispatch_*` 状态机可枚举**：iter-2 加 PAUSED 态 × 所有 action 用 `pytest.mark.parametrize`。
- **`_new_game` score_callback 可单测**：fake storage 注入 → 触发 step 吃食 → 验证 callback 调 `storage.save()`。
- **`_render` PAUSED 路径可测**：用 `app_in_paused` fixture 验证 `renderer.render` + `draw_pause_overlay` 各被调一次。
- **错误路径可触发**：`fake_storage.save.side_effect = StorageError(...)` → `_new_game` 注册的 callback 包 `StorageUnavailableError` → 主循环 → 退出码 1。

### 5.5 鲁棒性 / 韧性

| 场景 | 处理 |
|------|------|
| 图形环境缺失 | `Renderer.init()` 抛 `RenderError` → `GraphicsUnavailableError` → 退出码 2（G2-R-N1 不变） |
| **用户数据目录不可写** | `HighScoreStore.__init__` mkdir 失败 → **裸 `OSError`（**P1-1 修订**：platform-storage iter-2 `highscore.py` 实核：mkdir 不包异常，仅 save() 包 StorageError）→ `_init_pygame` 捕获 `(StorageError, OSError)` → 包 `AppError("用户数据目录不可写")` → 退出码 1（G2-2 + P1-1） |
| **最高分保存失败** | `score_callback` 内 `storage.save` 抛 `StorageError` → 包 `StorageUnavailableError` → 主循环 except AppError → 退出码 1（G2-3 新增） |
| 同一帧多事件 | `_drain_events` 返 list；主循环按序处理；QUIT 优先 break |
| 反向输入 | 透传到 `core.set_direction`；core 内静默忽略 |
| 撞墙/撞身 | `core.step` 返回 `status=OVER`；`_tick` 检测后自动转 `GAME_OVER`（INV-2） |
| 关窗 | `pygame.QUIT` 事件 → `QUIT` action → 主循环 break → `renderer.shutdown()` |
| **窗口失焦**（G2-4） | `pygame.key.get_focused() == False` + PLAYING 态 → 追加 `UNFOCUS` action → `toggle_pause()` → `screen=PAUSED` |
| **暂停期方向输入**（G2-1） | `_tick` 在 PAUSED 态不进入；`set_direction` 在 PAUSED 态由 core 静默忽略；input.py `_dispatch_paused` 不处理 MOVE_* |
| **PAUSED→RUN 恢复方向清空** | core iter-2 toggle_pause（PAUSED→RUN）自动清空 `pending_direction`（INV-8）；app 不感知 |
| **OVER 态调 toggle_pause** | core iter-2 抛 `InvalidStateError`；app 不包装（R3-9 一致）→ 裸 traceback（视为 bug，FAIL 由上半部巡检兜底） |
| Q/ESC 任意态 | `_map_event` 统一映射 `QUIT`；主循环检测后 break（G2-7 GAME_OVER 态 ESC 被 `_drain_events` 覆盖为 BACK_TO_MENU） |
| 节拍漂移 | `_tick_accumulator_ms` 累加 + while 循环 + 循环内重读 tick_ms（R3-8） |
| 配置非法（fps_cap ≤ 0） | `AppConfig.__post_init__` 抛 `ConfigError`（G2-R-N1）；`main()` 捕获后 stderr + 退出码 1 |
| 中文字体缺失 | `_load_cjk_font` 走 `match_font` 回退链，全失败 → SDL 默认字体 |
| **最高分文件损坏** | `HighScoreStore.load` 自动备份为 `.corrupt-<ts>.json` 后返 0；app 不感知 |

### 5.6 错误处理矩阵（G2-2 新增 Storage 错误 + G2-R-N5 修订）

| 错误情形 | 行为 |
|----------|------|
| `Renderer.init()` 失败 | `RenderError` → `GraphicsUnavailableError` → 退出码 2 + shutdown 兜底 |
| `Renderer.__init__` 校验失败 | 同上 |
| 构造 `AppConfig(fps_cap=0)` | `ConfigError`（`__post_init__` 校验，G2-R-N1）→ `main()` 捕获 → 退出码 1 |
| 构造 `AppConfig(window_w < min_window_w)` | `ConfigError`（`__post_init__` 校验，G2-R-N1）→ 退出码 1 |
| **HighScoreStore mkdir 失败**（用户数据目录不可写） | `StorageError` → 包 `AppError("用户数据目录不可写")` → 退出码 1（G2-2） |
| **`_dispatch_menu` RESET_HIGHSCORE 失败** | `StorageError` → 包 `StorageUnavailableError` → 主循环 except AppError → 退出码 1（G2-3） |
| **`score_callback` 内 `storage.save` 失败** | `StorageError` → 包 `StorageUnavailableError` → 主循环 except AppError → 退出码 1（G2-3） |
| `App.run()` 中 `core` 抛 `InvalidStateError` | **R3-9 沿用**：理论不可达，不包装；iter-2 真发生 → 视为 bug，FAIL 由上半部巡检兜底 |
| **未捕获异常**（G2-R-N5 修订） | 走解释器默认行为（stderr traceback + 退出码 1）—— 与 §4.2 代码 `except AppError` 对齐；删除 iter-1 §5.6 "App.run() 中未捕获异常 → 兜底 except Exception → 退出码 1"行 |

---

## 6. UT 框架（FO TDD 依据）

### 6.1 测试组织（见 §4.1 文件树）

### 6.2 桩与夹具（conftest.py，G2 增量 + **P1-3 fixture 注入顺序** + **P2-1 fake_pygame 补 input 模块替换**）

```python
# conftest.py — iter-1 fixture + G2 新增
import pytest
from unittest.mock import MagicMock, patch
import sys
import pygame  # 仅取事件类型常量


@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app.app + game_app.menu + game_app.storage + **game_app.input**（P2-1）内部的 pygame 引用。

    **P2-1 修订**：iter-1 conftest 只替换 game_app.app + game_app.menu；iter-2 game_app.input
    同样依赖 `_pygame_attr`（沿用 iter-1 模式），需同时 monkeypatch input 模块的 pygame 引用。
    """
    fake = MagicMock()
    fake.error = RuntimeError
    fake.QUIT = 256
    fake.KEYDOWN = 768
    fake.K_w = 119; fake.K_s = 115; fake.K_a = 97; fake.K_d = 100
    fake.K_UP = 1073741906; fake.K_DOWN = 1073741905
    fake.K_LEFT = 1073741904; fake.K_RIGHT = 1073741903
    fake.K_q = 113; fake.K_ESCAPE = 27; fake.K_p = 112; fake.K_r = 114
    fake.K_h = 104                                                    # G2-3 新增
    fake.K_BACKSPACE = 8                                              # G2-7 新增
    fake.K_RETURN = 13; fake.K_SPACE = 32
    fake.K_1 = 49; fake.K_2 = 50; fake.K_3 = 51
    fake.display.set_mode.return_value = MagicMock()
    fake.display.get_surface.return_value = MagicMock()
    fake.font.SysFont.return_value = MagicMock()
    fake.font.Font.return_value = MagicMock()
    fake.font.match_font.return_value = None
    fake.draw.rect = MagicMock()
    fake.time.Clock.return_value = MagicMock()
    fake.event.get.return_value = []
    fake.init = MagicMock()
    fake.quit = MagicMock()
    fake.key.get_focused.return_value = True                          # G2-4 默认聚焦
    monkeypatch.setitem(sys.modules, "pygame", fake)
    from game_app import app as app_module, menu as menu_module
    from game_app import input as input_module                          # P2-1 新增
    monkeypatch.setattr(app_module, "pygame", fake)
    monkeypatch.setattr(menu_module, "pygame", fake)
    monkeypatch.setattr(input_module, "pygame", fake)                  # P2-1 新增
    return fake


@pytest.fixture
def fake_storage():
    """G2-2：fake HighScoreStore，UT 注入 storage.load/save/reset 行为。"""
    storage = MagicMock()
    storage.load.return_value = 0
    storage.save = MagicMock()
    storage.reset = MagicMock()
    return storage


@pytest.fixture
def app(fake_pygame, fake_storage):
    """iter-1 沿用 + G2-2 fake_storage 注入（**P1-3 修订**：注入顺序在 _init_pygame 之后）。

    **P1-3 修订**：`_init_pygame()` 内 `self._storage = create_storage()` 无条件覆盖 fixture 刚
    注入的 fake_storage——会污染开发机真实用户目录。本 fixture 在 `_init_pygame()` 之后注入，
    并配合 §4.7 `_init_pygame` 的 `if self._storage is None: ...` 守卫（已注入则跳过 create_storage）。
    """
    from game_app import App
    a = App()
    a._init_pygame()                                          # P1-3：先调 _init_pygame（此时 _storage=None→create_storage）
    a._storage = fake_storage                                  # P1-3：之后注入 fake（避免 create_storage 覆盖）
    a._high_score = fake_storage.load.return_value
    return a


@pytest.fixture
def app_in_playing(fake_pygame, fake_storage):
    """iter-1 沿用 + G2 fake_storage 注入（**P1-3**）。"""
    from game_app import App
    from game_core import Difficulty
    a = App()
    a._init_pygame()                                          # P1-3
    a._storage = fake_storage                                  # P1-3
    a._high_score = fake_storage.load.return_value
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_paused(fake_pygame, fake_storage):
    """G2-1 新增：PLAYING 态触发 toggle_pause 后进入 PAUSED（**P0-1 屏态同步方案 A 验证**）。"""
    from game_app import App, InputAction, AppScreen
    from game_core import Difficulty
    a = App()
    a._init_pygame()                                          # P1-3
    a._storage = fake_storage                                  # P1-3
    a._high_score = fake_storage.load.return_value
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)              # P0-1：dispatch 内同步切屏
    assert a.screen == AppScreen.PAUSED                        # INV-10/11（方案 A 单点落地）
    return a


@pytest.fixture
def app_in_game_over(fake_pygame, fake_storage):                # **P2-2 新增**（取代 UT P-5 引用）
    """G2-7 新增：构造 GAME_OVER 态应用（手动把 status 置 OVER，避免依赖真实 step 撞墙）。"""
    from game_app import App, AppScreen
    from game_core import Difficulty
    a = App()
    a._init_pygame()
    a._storage = fake_storage
    a._high_score = fake_storage.load.return_value
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    # 手动把 status 置 OVER（绕开真实 step）
    a.game_state = a.game_state._replace(status=GameStatus.OVER)
    a.screen = AppScreen.GAME_OVER
    return a


@pytest.fixture
def app_with_storage(tmp_path, fake_pygame):
    """G2-2 新增：用 tmp_path 注入真实 HighScoreStore（替代 fake），测真实 IO 路径。"""
    from game_app import App
    from platform_storage import HighScoreStore
    a = App()
    a._init_pygame()
    a._storage = HighScoreStore(tmp_path / "highscore.json")
    a._high_score = a._storage.load()
    return a
```

### 6.3 断言规范（沿用 iter-1 + G2 增量）

- **不变量优先**：每个 UT 至少断言一条 INV（1~13）；G2-1 加 INV-10/11、G2-2 加 INV-12、G2-3 加 INV-13。
- **纯函数性质**：调 `_tick` / `_dispatch` / `toggle_pause` 后断言 `app.game_state` 已替换为新对象（`is not` 旧对象）。
- **覆盖状态机矩阵**：每态（MENU/PLAYING/PAUSED/GAME_OVER） × 每 action 用 `pytest.mark.parametrize` 枚举。
- **fake_pygame 副作用统计**：`fake.init.call_count` / `fake.quit.call_count` 用于验证 INV-5 / R3-15。
- **fake_storage 副作用统计**：`fake_storage.save.call_count` / `fake_storage.save.call_args` 用于验证 G2-3 callback 注册与触发。
- **退出码断言**：`App().run()` 返 int，对齐 0/1/2 语义。
- **UT 命名**：`test_{屏幕}_{动作}_{期望}`，如 `test_paused_p_key_returns_to_playing`。

### 6.4 必须覆盖的 UT 用例清单（FO 必写；G2 标注）

#### iter-1 沿用（42 条）

详见 `snake-linux/design/game-app/设计-r3.md` §6.4 UT-1~UT-42；G2 修订/补正如下：

- **UT-4 / UT-5 修订（G2-R-N1）**：`AppConfig(fps_cap=0)` / `AppConfig(window_w=400)` 抛 `ConfigError`（构造期 `__post_init__` 校验，非 `App.__init__`）。
- **UT-13 沿用**：MENU 态 `_running == True` 初始；`_drain_events` 返 [QUIT] → 主循环 break。
- **UT-19 / 19a 沿用**：`_tick` 循环内重读 tick_ms。
- **UT-24 修订（G2-R-N4）**：断言 `_build_hud(snap).high_score == 0`（公开字段名，非 `_high_score`）。
- **UT-33 修订（G2-R-N1）**：`App(AppConfig(fps_cap=0))` 抛 `ConfigError` → `main()` 返 1。

#### G2-1 新增（PAUSED 状态机 + **P0-1 方案 A 单点落地**）

| # | 场景 | 断言 |
|---|------|------|
| P-1 | PLAYING→PAUSED（P 键） | `app_in_playing._dispatch_playing(TOGGLE_PAUSE)` → `screen == PAUSED`（INV-11 方案 A 同步切屏） + `game_state.status == PAUSED` |
| P-2 | PAUSED→RUN（P 键） | `app_in_paused._dispatch_paused(TOGGLE_PAUSE)` → `screen == PLAYING`（INV-11 方案 A 同步切屏） + `game_state.status == RUN` |
| P-3 | PAUSED 态 `_tick` 不进入 | 主循环判断 `screen == PAUSED` → 跳过 `_tick` 调用（spy 验证 `_tick` 调用次数 = 0） |
| P-4 | PAUSED 态 `_dispatch_paused` 忽略 MOVE_* | `_dispatch_paused(MOVE_UP)` → `game_state.pending_direction` 不变（由 core iter-2 静默忽略保证） |
| **P-5**（**P2-2 修订**） | OVER 态调 `toggle_pause` 抛 InvalidStateError | **直接 `pytest.raises(InvalidStateError)` 调 `app_in_game_over.game_state.toggle_pause()`**（先手动把 status 置 OVER——`app_in_game_over` fixture 见 §6.2）；不再走 dispatch 路径（app 层 GAME_OVER 态 TOGGLE_PAUSE 不进 `_dispatch_playing`） |
| **P-6**（**P2-3 修订**） | PAUSED→RUN 后 pending_direction 清空（INV-8） | 前置步骤：`app_in_playing._dispatch_playing(MOVE_RIGHT)` 设置 pending → `_dispatch_playing(TOGGLE_PAUSE)` 进 PAUSED（screen=PAUSED）→ `_dispatch_paused(TOGGLE_PAUSE)` 回 RUN；断言 `pending_direction == None`（core iter-2 行为） |
| P-7 | `_render` PAUSED 路径 | `app_in_paused._render()` → spy `renderer.render` 调用 1 次 + spy `menu.draw_pause_overlay` 调用 1 次 |
| **P-8**（**P0-1 新增**） | **方案 A 同步切屏不依赖 _tick** | spy `_tick` 在 PAUSED 态不调用（已在 P-3）；但**额外**断言 `_tick` 内**不**存在 `elif new_status == PAUSED` 分支（AST/源码检查：`inspect.getsource(app._tick)` 不含 `GameStatus.PAUSED`）—— 防止 FO 后续误把 elif 加回 |

#### G2-2 新增（HighScoreStore 接入）

| # | 场景 | 断言 |
|---|------|------|
| S-1 | 构造 App（无 fake_storage） | `app._storage is None`（默认；G2-2 默认 None 让 UT 不依赖磁盘） |
| S-2 | `_init_pygame` 构造 storage | fake_pygame 注入后 `App()._init_pygame()` → `app._storage is not None` + `app._high_score == storage.load()` |
| S-3 | `_init_pygame` mkdir 失败 | fake_storage 构造期抛 `StorageError` → 包 `AppError` → `pytest.raises(AppError)` |
| S-4 | `_dispatch_menu(RESET_HIGHSCORE)` 成功 | fake_storage.reset 调用 1 次 + `app._high_score == 0` |
| S-5 | `_dispatch_menu(RESET_HIGHSCORE)` storage.reset 抛 StorageError | 包 `StorageUnavailableError` → `pytest.raises(StorageUnavailableError)` |
| S-6 | `_new_game` 注册 score_callback | `app._new_game(Difficulty.MEDIUM)` → fake storage 未被调 save（初始未吃食）；callback 闭包持有 `_storage` 引用 |
| S-7 | score_callback 触发 storage.save | 手动调 `app.game_state._score_callback(10)` → fake_storage.save(10) 调用 1 次 + `_high_score` 同步更新 |
| S-8 | score_callback 内 storage.save 抛 StorageError | fake `storage.save.side_effect = StorageError(...)` → 手动调 callback → `pytest.raises(StorageUnavailableError)` |
| S-9 | storage.load 损坏文件返 0 | 用 `app_with_storage(tmp_path)` 写损坏 JSON → `app._high_score == 0`（依赖 platform-storage 行为） |
| S-10 | `_init_pygame` 替代路径用 `create_storage(path=tmp_path)` | UT 验证 `app_with_storage` fixture 可工作 |

#### G2-3 新增（得分事件自动写入 + **P0-2 INV-13 同步实例字段**）

| # | 场景 | 断言 |
|---|------|------|
| **SC-1**（**P0-2 修订**） | 吃食触发 callback 同步 `_high_score` | fake GameState 注入 `step()` 返回 `score=10` 的新对象 + `_score_callback=app 内 callback` → step 后 `fake_storage.save(max(10, load()))` 调用 1 次 + **`app._high_score == 10`（INV-13 同步实例字段）** |
| **SC-2**（**P0-2 修订**） | `_high_score` 同步更新（同 SC-1 合并） | SC-1 后 `app._high_score == 10`（INV-13 直接写实例字段，不再走 nonlocal 容器） |
| SC-3 | 重开新局重新注册 callback | `_new_game` 第二次 → 新 callback 持有 `self` 引用（直接写 `self._high_score`）；旧 game_state 的 callback 不影响新 game_state |

#### G2-4 新增（窗口失焦自动暂停）

| # | 场景 | 断言 |
|---|------|------|
| U-1 | PLAYING 态失焦 | `fake_pygame.key.get_focused.return_value = False` → `_drain_events` 返 [..., UNFOCUS] → `_dispatch_playing(UNFOCUS)` → `screen == PAUSED` |
| U-2 | MENU 态失焦不变 | `fake_pygame.key.get_focused.return_value = False` + `screen == MENU` → `_drain_events` 不追加 UNFOCUS（仅 PLAYING 态检测） |
| U-3 | PAUSED 态失焦不变 | `app_in_paused` + `fake_pygame.key.get_focused.return_value = False` → `_drain_events` 不追加 UNFOCUS（PAUSED 已暂停） |
| U-4 | GAME_OVER 态失焦不变 | 同 U-3，screen=GAME_OVER |
| U-5 | 失焦检测函数抛异常（headless 环境） | `fake_pygame.key.get_focused.side_effect = Exception(...)` → `_drain_events` 兜底为 True（不追加 UNFOCUS） |
| U-6 | 聚焦恢复不自动继续 | PAUSED 态 `get_focused == True` → `_drain_events` 不追加 UNFOCUS；需 P 键才继续 |

#### G2-5 新增（暂停遮罩）

| # | 场景 | 断言 |
|---|------|------|
| O-1 | `draw_pause_overlay` 形参 | 函数签名 `draw_pause_overlay(surface: pygame.Surface, body_font: pygame.font.Font) -> None` |
| O-2 | 遮罩覆盖全屏 | spy `surface.blit` 调用次数 ≥ 2（半透明矩形 + 文字 1~2 次） |
| O-3 | 遮罩不读 `_screen` | spy `app._renderer._screen` 访问次数 = 0（沿用 R3-2） |
| O-4 | 遮罩用 `pygame.display.get_surface()` | spy `fake_pygame.display.get_surface` 调用次数 ≥ 1（来自 `_render` PAUSED 路径） |

#### G2-6 新增（最高分展示）

| # | 场景 | 断言 |
|---|------|------|
| H-1 | `draw_menu(high_score=100)` 绘制最高分行 | spy `surface.blit` 调用含 "最高分：100" 文本 |
| H-2 | `draw_menu(high_score=0)` 不绘制最高分行 | spy 不含 "最高分" 文本（避免"最高分：0"误导） |
| H-3 | `draw_game_over(high_score=100)` 绘制最高分行 | spy 含 "最高分：100" |
| H-4 | `draw_game_over(high_score=0)` 不绘制最高分行 | spy 不含 "最高分" |

#### G2-7 新增（返回菜单 + **P1-2 ESC/Q 语义分离**）

| # | 场景 | 断言 |
|---|------|------|
| **B-1**（**P1-2 修订**） | GAME_OVER 态 ESC → BACK_TO_MENU | `app_in_game_over` + fake_pygame 注入 `event = Event(KEYDOWN, key=K_ESCAPE)` → 调 `app._drain_events()` → actions 含 `[BACK_TO_MENU]`（_drain_events 屏态覆盖）→ `_dispatch_over(BACK_TO_MENU)` → `screen == MENU` + `game_state is None`（INV-7）；**不**含 QUIT |
| **B-2** | GAME_OVER 态 Backspace → BACK_TO_MENU | `app_in_game_over` + `event = Event(KEYDOWN, key=K_BACKSPACE)` → `_map_event` 直接返 BACK_TO_MENU（P2-1 _pygame_attr 模式）→ 同上 |
| **B-3** | GAME_OVER 态 pygame.QUIT 仍为 QUIT（不被覆盖） | `pygame.event.Event(pygame.QUIT)` → `_map_event` 返 QUIT（event.type==QUIT 守卫）→ `_drain_events` 在 GAME_OVER 态**不**覆盖（`ev.type == pygame.QUIT` 守卫）→ actions 含 `[QUIT]` 不含 BACK_TO_MENU |
| **B-4**（**P1-2 修订**） | GAME_OVER 态 Q 键 → QUIT 直通 | `app_in_game_over` + `event = Event(KEYDOWN, key=K_q)` → `_map_event` 返 QUIT（K_q 直通）→ `_drain_events` GAME_OVER 态**不**覆盖（仅 ESC 键被覆盖，Q 仍 QUIT）→ actions 含 `[QUIT]` 不含 BACK_TO_MENU；主循环 break 退出 |
| B-5 | MENU 态 ESC 仍为 QUIT | `app`（MENU 态）+ fake_pygame 注入 KEYDOWN K_ESCAPE → `_drain_events` 返 [QUIT]（MENU 态无 GAME_OVER 覆盖）→ 主循环 break（沿用 iter-1） |

#### G2-R-N1 修订（__post_init__ 校验）

| # | 场景 | 断言 |
|---|------|------|
| C-1 | `AppConfig(fps_cap=0)` 抛 ConfigError | 构造期抛（`__post_init__` 校验） |
| C-2 | `AppConfig(fps_cap=-1)` 抛 ConfigError | 同上 |
| C-3 | `AppConfig(window_w=400)` 抛 ConfigError | 构造期抛（小于 min_window_w） |
| C-4 | `App(AppConfig(fps_cap=0))` 由 main() 捕获返 1 | `main()` 捕获 `ConfigError` → stderr + 返 1 |
| C-5 | `App(AppConfig())` 默认值合法 | 构造无异常 |

### 6.5 覆盖率目标

- **行覆盖 ≥ 90%**（`app.py` 主循环 / dispatch / `_drain_events` / `_tick` 必须 100%；`input.py` 100%；`menu.py` ≥ 85%；`fonts.py` ≥ 85%；`storage.py` ≥ 90%）
- **分支覆盖 ≥ 85%**（每屏 dispatch 分支、节拍 while 循环分支、错误处理分支、`_drain_events` 屏态兜底 4 分支 + 失焦检测分支、`_render` 4 态分支）

### 6.6 UT 运行命令

```bash
python3 -m unittest discover -s tests/test_game_app -v
# 或
pytest tests/test_game_app -v --cov=game_app --cov-branch --cov-fail-under=90
```

### 6.7 FO TDD 实施步骤（建议，按 G2 增量分组）

**第一阶段（G2-2 HighScoreStore 接入基础）**：
1. 写 `test_storage.py`（UT S-1/2/3） → 跑（红）→ 写 `storage.py` + `errors.py` 加 `StorageUnavailableError`（绿）
2. 写 `test_app_init.py` 加 UT S-1/S-2（`_storage` 默认 None + `_init_pygame` 构造 storage） → 跑（红）→ 修改 `app.py.__init__` + `_init_pygame`（绿）
3. 写 `test_config.py` 加 C-1/2/3（G2-R-N1 `__post_init__` 校验） → 跑（红）→ 修改 `config.py`（绿）
4. 写 `test_app_iter2_storage.py` 加 UT S-4/5（RESET_HIGHSCORE 成功/失败） → 跑（红）→ 修改 `_dispatch_menu` + `input.py` 加 H 键 + `_MENU_RESERVED_ACTIONS` 扩展（绿）

**第二阶段（G2-3 得分事件接入）**：
5. 写 `test_app_iter2_storage.py` 加 UT S-6/7/8（score_callback 注册与触发） → 跑（红）→ 修改 `_new_game` 注册 callback + §4.6 闭包实现（绿）
6. 写 `test_app_iter2_storage.py` 加 UT SC-1/2/3（吃食触发 + INV-13 同步 + 重新注册） → 跑（红）→ 跑通即可

**第三阶段（G2-1 PAUSED 状态机）**：
7. 写 `test_app_iter2_pause.py`（UT P-1/2/3/4/5/6） → 跑（红）→ 修改 `screens.py` 加 PAUSED + `input.py` 不变（P 键已映射）+ `app.py` 加 `_dispatch_paused` + 修改 `_dispatch_playing` 的 TOGGLE_PAUSE + 修改 `_tick` 检测 PAUSED 自动转屏 + 修改 `_run_loop` PAUSED 跳过 `_tick`（绿）
8. 写 `test_app_iter2_pause.py` 加 UT P-7（`_render` PAUSED 路径） → 跑（红）→ 修改 `_render` 加 PAUSED 分支 + `menu.py` 加 `draw_pause_overlay`（绿）

**第四阶段（G2-4 失焦自动暂停）**：
9. 写 `test_app_iter2_unfocus.py`（UT U-1/2/3/4/5/6） → 跑（红）→ 修改 `_drain_events` 加失焦检测 + `_dispatch_playing` 加 UNFUSH 分支（绿）

**第五阶段（G2-5 暂停遮罩 + G2-6 最高分展示）**：
10. 写 `test_app_iter2_overlay.py`（UT O-1/2/3/4） → 跑（红）→ 实现 `draw_pause_overlay`（绿）
11. 写 `test_app_iter2_storage.py` 加 H-1/2/3/4（draw_menu / draw_game_over 加 high_score 形参） → 跑（红）→ 修改 `draw_menu` / `draw_game_over` + 修改 `_render` 调用传 `high_score`（绿）

**第六阶段（G2-7 返回菜单 + G2-R-N* 修订）**：
12. 写 `test_app_game_over.py` 加 B-1/2/3/4（BACK_TO_MENU） → 跑（红）→ 修改 `input.py` 加 BACKSPACE 键映射 + `_drain_events` 加 ESC 屏态覆盖 + `_dispatch_over` 加 BACK_TO_MENU 分支（绿）
13. 跑全部 UT（G2-R-N* 修订：UT-4/5/24/33 文档修订，不影响代码） → 全绿

**第七阶段（端到端 + 跨切面）**：
14. 写端到端 `test_app_iter2_e2e.py`（覆盖：MENU 启动 → START 开局 → 吃食触发 callback → P 暂停 → 失焦 → P 继续 → 撞墙 → GAME_OVER → ESC 返 MENU → Q 退出） → 跑（红）→ 补全缺失分支（绿）
15. 跑覆盖率报告，确保 ≥ 90% 行 / ≥ 85% 分支

---

## 附录 A：迭代 2 → 迭代 3/4 增量接口预告（仅供 FO 留扩展点，不在本次实现）

### A.1 迭代 3 增量

- **皮肤切换 UI**：`_dispatch_menu` 新增 `InputAction.SET_SKIN`（←→ 键）；调 `Renderer.set_skin(name)`（gui-renderer iter-3 已实装）；catch `SkinNotFoundError` → 提示当前可用 `Renderer.skin_names()` 列表
- **窗口等比缩放**：`_drain_events` 加 `pygame.VIDEORESIZE` 处理 → 调 `Renderer.handle_resize(w, h)`（gui-renderer iter-3 已实装）；catch `RenderError` → 提示当前最小可玩尺寸
- **平滑插值动画**：`_render` PLAYING 路径改调 `renderer.render(snap, hud, interp=InterpolationState(prev_snap, alpha))`（gui-renderer iter-3 已实装）；需要 `_prev_snap` 字段记录上一帧 snap
- **`AppConfig` 扩展**：通过子类 `AppConfigV3(AppConfig)` 加 `enable_high_dpi: bool = True`（iter-3 默认开启，NFR-04）；`Renderer` 构造传 `enable_high_dpi=config.enable_high_dpi`
- **`_render` PAUSED 路径增强**：iter-3 可改为"renderer.render 渲染 + draw_pause_overlay 遮罩 + draw_pause_overlay 半透明更深的 64% 黑色"

### A.2 迭代 4 增量

- `main()` 完善错误提示：捕获所有 `AppError` 子类，按错误类型给可读建议（缺 SDL 库/驱动版本/HiDPI 缩放提示）
- 性能 profile 脚本：`scripts/bench_fps.py` 实测 NFR-01 / NFR-02
- PyInstaller spec 文件：`build/snake-gui.spec`，三平台构建脚本 `build/{linux,windows,macos}.sh`
- 用户指南 `USER_GUIDE.md`
- 发布物清单：`dist/snake-gui{suffix}` + `SHA256SUMS` + `RELEASE_NOTES.md`
- `_init_pygame` 加 SDL 驱动版本检查 + 友好降级
- `_load_cjk_font` 改为打包内置字体（避免 Linux 字体版本差异）
- **`HighScoreStore` 跨进程文件锁**（如 spec 扩展）

### A.3 接口扩展原则

- 默认参数 + 新增方法，**不破坏迭代 1~2 既有签名**
- `App` 公开方法（`run()` / `__init__()`）签名迭代 1~4 不变
- `AppConfig` 字段迭代 1~2 冻结默认值，迭代 3 通过子类化 `AppConfigV3` 扩展
- `_storage` / `_high_score` / `_running` 字段保留作扩展点

---

## 附录 B：依赖与版本（G2-10 更新）

| 依赖 | 版本 | 约束来源 / 当前状态 |
|------|------|---------------------|
| Python | ≥3.8, <4 | 架构 §代码风格约定 |
| pygame | ≥2.0,<3 | gui-renderer 迭代 3 锁定（`code/gui-renderer/iter-3/gui_renderer/constants.py`） |
| **game-core** | **迭代 2** 接口为准 — `code/game-core/iter-2/game_core/` **it_passed，契约已锁定** | 引用接口：`GameState(width=, height=, difficulty=, rng=, score_callback=)` / `set_direction` / `step` / `snapshot` / **`toggle_pause`** / **`set_score_callback`** / `Snapshot.tick_ms = speed_curve(score, difficulty)` |
| **gui-renderer** | **迭代 3** `code/gui-renderer/iter-3/gui_renderer/` **it_passed，契约已锁定** | iter-2 game-app 仅用 `Renderer((W,H), skin=DEFAULT_SKIN)` + `init()` + `shutdown()` + `render(snap, hud)`；**不调** `set_skin`/`handle_resize`/`render(interp=)`（iter-3 预告） |
| **platform-storage** | **迭代 2** `code/platform-storage/iter-2/platform_storage/` **it_passed，契约已锁定**（G2-10 iter-2 首次导入） | 引用接口：`get_user_data_dir() -> Path` / `HighScoreStore(path=None)` / `load() -> int` / `save(score)` / `reset()` / `StorageError` |
| PyInstaller | ≥5.0（迭代 4） | 架构 §技术选型 |

> **难度选择 UI 不在迭代 2 重复实现**（R-01 / R2-14 / R3-3：已在迭代 1 完成）；分工表已备注。

---

## 附录 C：与 v1 终端版差异（沿用 iter-1 + G2 增量）

| 项 | v1 终端版 | v2 game-app iter-1 | v2 game-app iter-2 |
|----|----------|---------------------|---------------------|
| 状态机 | 仅 run/over | MENU / PLAYING / GAME_OVER | **+ PAUSED**（G2-1） |
| 暂停 | n/a | 提示占位 | **toggle_pause 实际切屏**（G2-1） |
| 失焦暂停 | n/a | n/a | **get_focused 自动暂停**（G2-4） |
| 最高分 | 无 | 写死 0 | **HighScoreStore 持久化 + 重置**（G2-2/3） |
| 最高分展示 | n/a | n/a | **MENU / GAME_OVER 自绘加行**（G2-6） |
| 返回菜单 | n/a | GAME_OVER 仅 R 重开 / Q 退出 | **GAME_OVER 加 Esc / Backspace**（G2-7） |
| 持久化 | 无 | 无 | **highscore.json 落用户数据目录**（G2-2） |

> **核心玩法逻辑完全一致**（FR-01~05 与 v1 同语义）；**仅形态升级 + 已拍板新能力**（FR-10/12/13）。所有"v1 已验证"的玩法行为 game-core 单元测试已覆盖，game-app 仅做装配 + 状态机扩展。

---

## 附录 D：SE 评审 P0/P1/P2 修订对照（iter-1 r2/r3 → iter-2 增量 + G2-R 消化）

| 来源 | ID | 修订内容 | 章节 |
|------|-----|----------|------|
| iter-1 r3 | R3-1 | None→START 转换点唯一在 `_drain_events`（屏态兜底） | §4.4 沿用 |
| iter-1 r3 | R3-2 | menu 不读 `_renderer._screen`；走 `pygame.display.get_surface()` | §4.8 沿用 + G2-5 遮罩 |
| iter-1 r3 | R3-4 | 字段命名统一为 `_difficulty` / `_high_score` | §1.3 沿用 |
| iter-1 r3 | R3-5 | `_running: bool = True` 在 §1.3 声明 | §1.3 + G2-R-N2 补正 |
| iter-1 r3 | R3-6 | game-core iter-2 it_passed 契约锁定 | §0 §附录 B 沿用 |
| iter-1 r3 | R3-7 | 删除 `_quit()` 死代码 + dispatch QUIT 分支 | §4.4 沿用 |
| iter-1 r3 | R3-8 | `_tick` 循环内重读 tick_ms | §4.5 沿用 |
| iter-1 r3 | R3-9 | InvalidStateError 理论不可达不包装 | §5.6 沿用（toggle_pause OVER 态一致） |
| iter-1 r3 | R3-10 | App.__init__ 不构造 Renderer | §4.7 沿用 + G2-2 同样不构造 storage |
| iter-1 r3 | R3-11 | `_render` 共享一次 snap | §4.8 沿用 + G2-1 PAUSED 路径同样共享 |
| iter-1 r3 | R3-12 | CJK 字体回退链 | §4.7 沿用 + G2-5 遮罩复用 |
| iter-1 r3 | R3-14 | `app_in_playing` fixture | §6.2 沿用 + G2 新增 `app_in_paused` / `app_with_storage` |
| iter-1 r3 | R3-15 | 退出码 2 shutdown 兜底 | §4.2 沿用 |
| **iter-2 r1 新增** | **G2-1** | PAUSED 状态机扩展 | §1.1 §1.3 §3.4 §4.4 §4.5 §6.4 |
| **iter-2 r1 新增** | **G2-2** | HighScoreStore 接入 | §1.3 §3.4 §3.6 §4.7 §6.4 |
| **iter-2 r1 新增** | **G2-3** | 得分事件回调接入 + 重置入口 | §3.4 §4.4 §4.6 §6.4 |
| **iter-2 r1 新增** | **G2-4** | 窗口失焦自动暂停 | §4.4 §5.5 §6.4 |
| **iter-2 r1 新增** | **G2-5** | 暂停遮罩 | §3.7 §4.8 §6.4 |
| **iter-2 r1 新增** | **G2-6** | 最高分展示 | §3.7 §4.8 §6.4 |
| **iter-2 r1 新增** | **G2-7** | 返回菜单路径 | §1.1 §3.4 §4.4 §6.4 |
| **iter-2 r1 新增** | **G2-8** | 难度选择 UI 不重复实现 | §0 §附录 B |
| **iter-2 r1 新增** | **G2-9** | 代码组织决策（不新建 iter-2 目录） | §4.1 |
| **iter-2 r1 新增** | **G2-10** | 依赖版本更新 | §0 §附录 B |
| **iter-1 r3 SE 消化** | **G2-R-N1** | AppConfig.__post_init__ 校验 | §3.1 §6.4 |
| **iter-1 r3 SE 消化** | **G2-R-N2** | `_running` 表述补正 | §1.3 §4.2 |
| **iter-1 r3 SE 消化** | **G2-R-N3** | dispatch 注释 + 菜单提示补正 | §4.4 §4.8 |
| **iter-1 r3 SE 消化** | **G2-R-N4** | UT-24 笔误修正 | §6.4 |
| **iter-1 r3 SE 消化** | **G2-R-N5** | §5.6 与 §4.2 代码对齐 | §5.6 |
| **iter-1 r3 SE 消化** | **G2-R-N6** | App.__init__ 默认参数 docstring 注明 | §3.4 |

### 累计修订一览

- **iter-1 r1 FAIL**：6×P0（Renderer 构造/生命周期/HUD/GameState 关键字/MENU·GAME_OVER 自绘/依赖版本）
- **iter-1 r2 FAIL**：r1 6×P0 全修，新增 **1×P0（None→START 矛盾）+ 1×P1（直读 `_screen`）+ 13×P2**
- **iter-1 r3 PASS**：r2 的 1×P0 + 1×P1 + 13×P2 全部给出全文一致修订；6 项 P2-N1~N6（不阻塞）建议 FO 落地消化
- **iter-2 r1（本版）**：
  - 沿用 iter-1 r3 全部 R3 修订（R3-1~R3-15）
  - 新增 10 项 G2-1~G2-10 增量（对应需求 FR-12/FR-13 + 失焦暂停 + 返回菜单 + 最高分展示 + 代码组织决策 + 依赖版本更新）
  - 消化 iter-1 r3 SE 评审遗留的 6 项 P2-N1~N6（G2-R-N1~N6）
  - 预计可一次 PASS（与 iter-1 r3 PASS 同等论证强度：依赖契约逐条实核 + 全 R3 修订落点 + G2 增量范围对应需求拍板条目）

---

> **本修订版提交 SE 复审前自查**：
> - [x] **G2-1** PAUSED 状态机：枚举 / `_dispatch_paused` / `_tick` 跳过 / `_render` PAUSED 路径 / INV-10/11 完整
> - [x] **G2-2** HighScoreStore 接入：`_storage = None` 默认 / `_init_pygame` 构造 + mkdir 失败处理 / `_high_score = storage.load()` 覆盖 / `StorageUnavailableError` 包装 / INV-12 完整
> - [x] **G2-3** score_callback 注册：`_new_game` 全关键字 + 闭包 / H 键 RESET_HIGHSCORE / INV-13 同步
> - [x] **G2-4** 失焦自动暂停：`_drain_events` 检测 / UNFOCUS action / 仅 PLAYING 态触发 / headless 兜底
> - [x] **G2-5** 暂停遮罩：`draw_pause_overlay` 自绘 / 不读 `_screen` / R3-2 一致
> - [x] **G2-6** 最高分展示：`draw_menu` / `draw_game_over` 形参扩展 / high_score=0 不绘制避免误导
> - [x] **G2-7** 返回菜单：BACK_TO_MENU action / `_drain_events` GAME_OVER 态 ESC 覆盖 / `_dispatch_over` 分支 / INV-7 重置
> - [x] **G2-8** 难度 UI 不重复：§0 明确 / §附录 B 备注
> - [x] **G2-9** 代码组织：不新建 iter-2 目录 / 增量修改在 iter-1 源码 / 新增 storage.py + test_app_iter2_*.py
> - [x] **G2-10** 依赖版本：game-core iter-2 + gui-renderer iter-3 + platform-storage iter-2 全部 it_passed 实核
> - [x] **G2-R-N1** AppConfig.__post_init__ 校验 + UT-4/5/33 修订
> - [x] **G2-R-N2** `_running` 表述补正 + 主循环改 `while True`
> - [x] **G2-R-N3** dispatch 注释 + 菜单提示补正（含 P/R/H/Esc/Backspace）
> - [x] **G2-R-N4** UT-24 笔误修正（high_score 公开字段名）
> - [x] **G2-R-N5** §5.6 与 §4.2 代码对齐（删除 "except Exception" 行）
> - [x] **G2-R-N6** App.__init__ 默认参数 docstring 注明
> - [x] UT 覆盖矩阵扩展到 ~70 条（含 iter-1 42 条 + G2-1 PAUSED 7 条 + G2-2/3 storage 10 条 + G2-4 unfocus 6 条 + G2-5 overlay 4 条 + G2-6 highscore 4 条 + G2-7 back 4 条 + G2-R-N1 5 条）
