# 功能模块设计评审意见：game-app（snake-linux v2.0.0 迭代 1）r2

> SE 评审 · 依据：模块设计 `snake-linux/design/game-app/设计-r2.md`（修订版）+ 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）+ 上轮评审 `snake-linux-game-app-design-iter1-r1.md`（FAIL）
> 接口实核（本轮逐条对落地代码核对，非纸面对纸面）：
> - game-core **迭代 2** `code/game-core/iter-2/game_core/`（state.py / types.py / params.py / errors.py / __init__.py）——**modules.json 现为 it_passed，契约已锁定**（r2 写作时标注 dev_reviewing 已过时，见 P2-4）
> - gui-renderer **迭代 1** `code/gui-renderer/iter-1/gui_renderer/`（renderer.py / types.py / constants.py / errors.py / __init__.py）——it_passed，契约锁定
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：r1 的 **6 项 P0 已全部正确修订并通过逐条实核**（Renderer 构造/生命周期/HUD/GameState 关键字构造/MENU·GAME_OVER 自绘/依赖版本声明，全部对齐锁定契约），但 r2 **新引入 1 项 P0**——「任意键开始」的 None→START 转换点全文三处互相矛盾（修订摘要说 `_map_event`、§4.3 注说 `_dispatch_menu`、§4.4 注释说 `_drain_events`、而 §4.4 实际代码是 `pass` 不转换），**FO 按 §4.4 字面代码实现则 START 永不被产生、Enter/任意键全部落空、游戏无法开始**；另有 1 项 P1（menu.py 直读 `renderer._screen` 私有属性，违反设计自身边界规则）与一批 P2。修订点小而集中，修订后即可复审通过。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点（r2） | 结果 |
|---|---|---|
| 模块类型：上层应用，依赖 game-core / gui-renderer / platform-storage | §0 类型/依赖一致；迭代 1 不 import platform-storage | ✅ |
| 迭代排期：game-app 迭代 1,2,3,4（分工表） | §0 迭代 1 = 最小可玩闭环；2/3/4 只预告（附录 A） | ✅ |
| 迭代 1 出口 = 主循环/输入/开始-结束-重开-退出（架构） | §0 出口清单 ✅8 + ❌5；难度选择提前到迭代 1（R2-14 已说明，见 P2-1） | ✅（范围调整已论证） |
| 数据流：输入 → core.set_direction/step → snapshot → renderer.render | §2.1 数据流图一致；core 只读快照不侵入 | ✅ |
| `GameState(width, height, difficulty)`（架构 §接口清单） | **修订对齐**：§3.4/§4.4 `GameState(width=20, height=15, difficulty=..., rng=Random())` 全关键字，与 game-core 落地 `__init__`（`args` 非空抛 TypeError）一致 | ✅ |
| `Renderer(skin_name)` + `render(snapshot)`（架构 §接口清单） | **修订对齐**：`Renderer((640,480), skin=DEFAULT_SKIN)` + `render(snapshot, hud)`，与 gui-renderer 落地一致 | ✅ |
| `set_skin(name)`（架构 §接口清单） | 修订：迭代 1 不调用（gui-renderer 无此方法，迭代 3 预告） | ✅ |
| HUD 数据由 app 注入 renderer（gui-renderer 设计 §1.1/HudData） | **修订对齐**：`HudData` dataclass 5 字段（score/high_score/length/difficulty_label/status_label），high_score=0 int 占位 | ✅ |
| 零配置（架构 §配置模型） | AppConfig frozen dataclass 硬编码默认值，不读文件 | ✅ |
| 无网络（NFR-06）/无音效（R-04） | §0/§4.10 明确不 import socket/urllib/http/requests、不 import pygame.mixer | ✅ |
| 语法兼容 Python 3.8 | §0 约束 + 代码示例用 Optional/Tuple/List 而非 3.9+ 语法 | ✅ |
| 难度游戏中不可切换（FR-05） | INV-3 + `_dispatch_playing` 无 SELECT_* 分支（UT-36 覆盖） | ✅ |
| 网格 20×15 | GameState(20,15) 与 gui-renderer GRID_COLS/GRID_ROWS=20/15 一致 | ✅ |
| 窗口职责单一（P0-2 修订方向） | 窗口创建唯一由 `renderer.init()` 承担，app 不再 set_mode | ✅（见 P1-1 唯一残留） |
| 退出 1 秒内无残留进程（FR-11） | run() finally 调 `Renderer.shutdown()`（幂等）+ 退出码 0/1/2 | ✅ |

### 1.1 与依赖模块实际契约核对（代码实核，r2 声称已对齐——逐条验证）

| 设计引用（r2） | 依赖模块落地 | 结果 |
|---|---|---|
| `Renderer((self.config.window_w, self.config.window_h), skin=DEFAULT_SKIN)` | renderer.py `__init__(window_size, *, skin=None, ...)`；DEFAULT_SKIN 由 `gui_renderer/__init__` re-export；(640,480) ≥ 最小 (512,472) | ✅ |
| `renderer.init()` 幂等，render 前必须 init | renderer.py L149 `init()`（`if self._initialized: return`）；render L193 `assert self._screen is not None` | ✅ |
| `renderer.render(snapshot, hud)` 仅 PLAYING 态调用 | render 要求 snapshot.snake_body 非空；PLAYING 态 game_state 非 None 且 body ≥3 | ✅ |
| `HudData(score:int, high_score:int, length:int, difficulty_label:str, status_label:str)` | gui_renderer/types.py HudData 5 字段一致；`from gui_renderer import HudData` 可导入 | ✅ |
| `_STATUS_LABEL[snap.status]` → "RUN"/"PAUSED"/"OVER" | renderer `hud.status_label.upper() == "OVER"` 高亮判断兼容 | ✅ |
| `GameState(width=20, height=15, difficulty=..., rng=Random())` | state.py `__init__`：仅关键字；allowed={width,height,difficulty,rng,initial_direction,score_callback} | ✅ |
| `set_direction(d) -> GameState`（新对象） | state.py L156 返回新对象；OVER 抛 InvalidStateError；反向静默忽略/长度 1 放行 | ✅ |
| `step() -> GameState`（新对象） | state.py L186 纯函数式；`dataclasses.replace` | ✅ |
| `snapshot()` 含 tick_ms（speed_curve 动态节拍） | types.py Snapshot 含 tick_ms；params.py speed_curve(score,difficulty)，score=0 时 250/160/100 | ✅（UT-19/20 的 160/100ms 与 speed_curve(0) 一致） |
| `InvalidStateError` | errors.py 存在（RuntimeError 子类），game_core re-export | ✅ |
| `set_score_callback(cb)`（迭代 2 接入预告） | state.py L270 方法存在；设计已剔除 r1 误引的 `on_score` | ✅ |
| 迭代 1 不调用 `toggle_pause()` | 设计 P 键仅置 `_pause_hint_shown`，不触碰 core（INV-8） | ✅ |

## 2. P0（阻塞，必须修订）

### P0-1 「任意键开始」None→START 转换点全文三处矛盾，按字面代码实现游戏无法开始
- **矛盾点**（同一机制四个说法）：
  1. 修订摘要 R2-9：「MENU 态下 `_map_event` 把所有**未映射**的 KEYDOWN 归一为 `InputAction.START`」——但 §4.3 的 `_map_event` 对未映射键 `return None`（且注明确说「`_map_event` 不感知 screen」）；
  2. §4.3 注：「调用方（MENU dispatch）把 None 视为 START——见 `_dispatch_menu` 的 `if action is None: self._new_game(...)`」——但 §4.4 的 `_dispatch_menu` 实际代码没有该行；
  3. §4.4 注释：「由 `_drain_events` 已在 MENU 态把 None 替换为 START；这里不再处理 None」——但 §3.4 `_drain_events` 的职责描述（「本帧所有 pygame 事件归一化；QUIT 优先 break」）未提任何屏态感知转换；
  4. §4.4 实际代码：`elif action is None: pass` —— **什么都不做**。
- **后果**：`InputAction.START` 在全文没有任何键被映射产生（Enter/Space 走 None，q/esc/p/r/1/2/3/WASD 各有归属），唯一产生途径就是这个 None→START 转换。若 FO 按 §4.4 代码字面实现（pass），**Enter/任意键全部落空，菜单永远无法开局**——比 r1 的 P1-3 更严重（r1 至少 Enter/Space 还能 START，r2 字面实现连这都丢了）。
- **修订**（三选一，必须全文统一成一处）：
  - 推荐：转换点定为 **`_drain_events`**（UT-38 已按此断言「MENU 态 drain_events 返 [START]」）——`_drain_events` 内：`act = _map_event(ev)`；`if self.screen == MENU and act is None: act = InputAction.START`；`_dispatch_menu` 删掉 None 分支（或保留为防御性 assert）。同步删 §4.3 注与修订摘要 R2-9 中「_map_event / _dispatch_menu 归一」的表述，统一写「_drain_events 屏态兜底」。
  - 或：转换点定为 `_dispatch_menu`：`elif action is None: self._new_game(self._difficulty)`，且 §4.4 注释改为「_drain_events 保留原始 None，由 MENU dispatch 兜底」，删「已替换为 START」的说法。
- **连带语义统一**（同条修订）：FR-11 是「按**任意键**开始」；r2 只转换未映射键，则 MENU 态按 W/A/S/D/方向键/P/R（均已映射为 MOVE_*/TOGGLE_PAUSE/RESTART）**不会开始**，与菜单提示「Enter / 任意键 开始」仍不符。要么把 MENU 态转换范围扩为「除 QUIT/SELECT_* 外全部 → START」，要么把提示改为「Enter / 空格 / 未绑定键 开始」。二选一并在 §4.9 状态机图（仍写「任意键(START)」）同步。

## 3. P1（内部矛盾/歧义，FO 会踩坑）

### P1-1 menu.py 直读 `app._renderer._screen` 私有属性，违反设计自身边界规则
- §4.8 `_draw_menu`/`_draw_game_over` 用 `screen = app._renderer._screen`——这是**跨模块读 gui-renderer 内部状态**，与设计自己写的边界冲突：§0.5「不可直接改 gui-renderer 内部状态（仅通过 Renderer 构造 / init / shutdown / render / skin property）」、§4.10.4「不直接调 renderer 私有方法」。当前 it_passed 代码恰好能跑（init() 后 `_screen` 即 set_mode surface），但 app 从此被绑死在 gui-renderer 实现细节上，后续迭代改内部名即断。
- **修订**：改用 **`pygame.display.get_surface()`**（pygame 公开 API，返回 renderer.init() 内 set_mode 创建的当前 surface，语义等价且不碰私有属性），menu.py 不再触碰 `_renderer`；同时把 `_draw_menu(app)` / `_draw_game_over(app)` 的形参从「整个 App 实例」收窄为「(surface, fonts, difficulty, score)」显式传参，避免自绘模块扒 App 私有字段（`app._difficulty`/`app._menu_title_font` 同属此类）。
- 注：若坚持用 `_screen`，必须在 §0.5/§4.10 显式声明「读取 `Renderer._screen` 为与 gui-renderer 约定的受控例外」，不能既禁止又使用。

## 4. P2（建议修订，不阻塞）

- **P2-1** 迭代范围调整需落盘同步：难度选择 UI 提前到迭代 1（R2-14 文档论证充分，规格 R-01 高优先级可辩护，**本评审认可**）——但架构《功能模块分工表》迭代 2 出口仍写「难度选择界面」，两处不一致。建议在分工表/架构迭代计划补一行备注（迭代 2 仅承接最高分展示+重置，难度 UI 已在迭代 1 完成），避免后续迭代 2 范围复查时误判重复。
- **P2-2** 状态字段命名三套并存：`_selected_difficulty`（§1.2）/ `difficulty`（§1.3）/ `_difficulty`（§4.4 代码 + conftest + UT-10 断言）；`high_score`（§1.3、UT-25）与 `_high_score`（§4.6 代码）。FO 无法确定字段名，按任一套实现都可能与 UT 断言或伪码对不上。统一为一套（建议带下划线的私有名 `_difficulty`/`_high_score`，或全部公开名），全文 + conftest + UT 同步。
- **P2-3** `_running` 字段未声明：§1.3 运行期状态表没有 `_running`，§3.4 `__init__` docstring 也未说明初值 `True`，但 §4.2/§4.4/§3.4 `_quit()` 全文使用。状态表补一行（初始 True，主循环退出标志）。
- **P2-4** game-core 迭代 2 状态描述过时：设计头部/§0/附录 B 写「dev_reviewing」，`modules.json` 现为 **it_passed**（契约已锁定）——R2-6 的「iter-2 检视 FAIL 改回 iter-1 形态」fallback 已无风险，可改为「it_passed，契约锁定」，并把 R2-6 的 git diff 重核流程降级为「若未来 core 改动需重核」。
- **P2-5** `_quit()` 死代码：§3.4 定义 `_quit()`（设 `_running=False`），但 §4.4 dispatch 各分支直接写 `self._running = False`，全文无人调用 `_quit()`；同理 `_dispatch_menu`/`_dispatch_over` 的 QUIT 分支在主循环 `if QUIT in actions: break` 先行退出后永远不可达。删除 `_quit()` 与两个 QUIT 分支（保留主循环唯一通道），或统一改走 `_quit()`。
- **P2-6** `_tick` 帧内 tick_ms 用帧首快照值：`tick_ms = snapshot().tick_ms` 在 while 循环外取一次，若同帧内吃食（score+1 → speed_curve 加速），循环内后续 step 与累加器扣减都按旧值，产生微小节拍漂移（INV-4 语义是「调后减 tick_ms」，暗示逐拍取值）。建议循环内重读 `tick_ms`，或注明「帧内用帧首值、下一帧自校正」为有意取舍。
- **P2-7** InvalidStateError 包装契约未落实：§5.6 错误矩阵说「core 抛 InvalidStateError → AppError 子类包装 → 退出码 1」，但 §4.2 run() 只 `except AppError`，`_dispatch_playing`/`_tick` 直接调 core 方法无 try/except——真抛 InvalidStateError 会裸 traceback（NFR-03 违背）。迭代 1 理论不可达（INV-1/2 保护）可接受，但要么在 `_dispatch_playing` 包一层转 `AppError`，要么把 §5.6 表述改为「不可达，UT 覆盖即可，不包装」。
- **P2-8** Renderer 构造点两处矛盾：§1.3 说「构造时 `Renderer((640,480),...)`」（App 构造期），§4.7 `_init_pygame` 又构造一次；UT-1 说「构造期零副作用、renderer 未 init」。统一为「App.__init__ 只置 `self._renderer = None`，构造与 init 都在 `_init_pygame`」，UT-1 断言改为「构造后 `_renderer is None`」。
- **P2-9** event_queue fixture 与描述不符：§5.4 说「App.__init__ 替换 `pygame.event.get` 为 `lambda: event_queue.pop(0) or []`」，§6.2 conftest 实际只 `fake.event.get.return_value = []`、`event_queue` fixture 返回空 list 占位——且 `pop(0) or []` 在空队列时 IndexError。删掉死 fixture 或按 §5.4 真正实现注入；§6.2 的「R2-16 用法」直接写 `fake.event.get.return_value/side_effect` 即可。
- **P2-10** 中文标签字体未考虑：`pygame.font.SysFont("Arial", ...)` 在多数 Linux 发行版无 CJK 字形，「简单/普通/困难」及菜单中文提示会渲染为豆腐块（□）。建议字体回退链（Noto Sans CJK SC / WenQuanYi / `pygame.font.match_font` 候选表），并在 §4.7 注明；HUD 与菜单均受影响（Q-01 中文命名是规格拍板，不能改英文回避）。
- **P2-11** PLAYING 态每帧两次 `snapshot()`：`_render` 调一次、`_build_hud` 又调一次（§4.8 + §4.6）。无正确性问题，建议 `_render` 取一次 snap 传给 `_build_hud(snap)`，少一次 dataclass 构造。
- **P2-12** UT-28/30 前置条件未写明：`test_app_render_dispatch` 测 MENU/GAME_OVER 自绘路径时，若 App 未先 `_init_pygame()`（fake 环境下 renderer 未 init），`_draw_menu` 读 `_screen` 为 None 会崩（P1-1 改 get_surface 后同样依赖 init 已跑）。conftest 的 `app` fixture 需说明「渲染类用例必须先 `_init_pygame()`」或提供 `app_ready` fixture。
- **P2-13** 退出码 2 路径不清理：`_init_pygame` 失败返回 2 时（renderer.init 中途失败，pygame.init 已执行），`finally` 的 shutdown 不覆盖该路径（return 2 在第二个 try 之前）。进程退出本身会回收，但建议失败路径也补一次 `renderer.shutdown()` 兜底（幂等安全）。

## 5. r1 六项 P0 修订验证（逐条实核，全部通过——本轮最重要的正面结论）

| r1 P0 | r2 修订 | 实核结果 |
|---|---|---|
| P0-1 Renderer("classic") 字符串构造 | `Renderer((640,480), skin=DEFAULT_SKIN)` | ✅ 与 renderer.py `__init__(window_size, *, skin=None,...)` 一致；DEFAULT_SKIN 可导入 |
| P0-2 生命周期缺失 + set_skin 不存在 + 窗口职责冲突 | `init()` 在 `_init_pygame` 调一次；删 app 端 set_mode；删 set_skin 引用 | ✅ init 幂等、render 前断言、窗口唯一创建；§4.10.10 明确 skin 只读 |
| P0-3 HUD dict 类型不符 | `HudData` dataclass 5 字段；high_score=0 int；status_label 补齐 | ✅ 字段名/类型逐一对齐 types.py；renderer 高亮判断兼容 |
| P0-4 GameState 位置参数 | 全关键字 `GameState(width=, height=, difficulty=, rng=)` | ✅ 与 state.py 仅关键字构造一致 |
| P0-5 MENU/结束画面无方案 + MENU 态必崩 | app 自绘（pygame.font + draw）；render 仅 PLAYING 调；INV-7 保护 | ✅ game_state=None 不再触发 snapshot；三种屏态分发明确 |
| P0-6 依赖版本矛盾 | 显式声明以 game-core iter-2 接口为准 + fallback 流程 | ✅ iter-2 已 it_passed，契约锁定；设计所选接口与锁定代码一致 |

## 6. 复审要点（下次评审先看这几条）

1. 「任意键开始」None→START 转换点全文统一为**唯一一处**（建议 `_drain_events` 屏态兜底），§4.3 注 / §4.4 注释 / 修订摘要 R2-9 / §4.4 代码四处表述一致；MENU 态「任意键」语义范围与菜单提示二选一定死；
2. menu.py 不再直读 `_renderer._screen`（改 `pygame.display.get_surface()` 或显式受控例外声明），自绘函数形参收窄；
3. 字段命名（difficulty/_difficulty、high_score/_high_score）与 `_running` 声明补齐；
4. 分工表迭代 2 出口备注难度 UI 已提前（P2-1）；
5. 其余 P2 项（_quit 死代码、tick_ms 帧内取值、event_queue fixture、CJK 字体、退出码 2 清理等）按修订清单过一遍。

> 说明：本轮 FAIL 仅因 P0-1 一处文档矛盾 + P1-1 边界违规，修订面小且明确；契约实核层面 r2 已全部对齐锁定代码，修订后预计可一次 PASS。
