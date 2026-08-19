# 功能模块设计评审意见：game-app（snake-linux v2.0.0 迭代 1）r1

> SE 评审 · 依据：模块设计 `snake-linux/design/game-app/设计-r1.md` + 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）
> 接口实核：game-core 落地代码 `code/game-core/iter-2/game_core/`（state.py/types.py/params.py/__init__.py）、gui-renderer 落地代码 `code/gui-renderer/iter-1/gui_renderer/`（renderer.py/types.py/constants.py）
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：架构遵循性（分层/数据流/迭代边界）方向正确，但**模块间契约与已锁定依赖模块（gui-renderer 迭代 1 it_passed、game-core 迭代 2 dev_reviewing）的实际落地接口严重脱节**——Renderer 构造/生命周期/HUD 类型全部对不上（照做必挂），菜单与结束画面渲染无方案且 MENU 态 `_render()` 必崩，GameState 构造签名错误；另有难度选择/QUIT/START 等多处内部矛盾。修订后可复审。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点 | 结果 |
|---|---|---|
| 模块类型：上层应用，依赖 game-core / gui-renderer / platform-storage | §0 类型/依赖/被依赖一致；迭代 1 不 import platform-storage（迭代 2 接入） | ✅ |
| 迭代排期：game-app 迭代 1,2,3,4（分工表） | §0 迭代 1 范围 = 最小可玩闭环；2/3/4 增量只预告不实装 | ✅ |
| 迭代 1 出口 = 主循环/输入/开始-结束-重开-退出（架构） | §0 出口清单 8 ✅ + 7 ❌ 边界清晰 | ✅ |
| 数据流：输入 → core.set_direction/step → snapshot → renderer.render | §2.1 数据流图一致；core 只读快照、不侵入 | ✅ |
| `GameState(width, height, difficulty)`（架构 §接口清单） | **偏离：§3.4 `GameState(20, 15, difficulty, rng=Random())` 位置参数调用，而 game-core 落地仅接受关键字参数（`GameState only accepts keyword arguments`）——照做抛 TypeError，见 P0-4** | ❌ |
| `Renderer(skin_name)` 构造 + `render(snapshot)`（架构 §接口清单） | **偏离：设计用 `Renderer("classic")` + `render(snapshot, hud)`；gui-renderer 落地为 `Renderer(window_size, skin=None)` + `render(snapshot, hud: HudData)` + 强制先 `init()`，见 P0-1/P0-2** | ❌ |
| `set_skin(name)`（架构 §接口清单） | 设计 §2.2 称迭代 1 接受；**gui-renderer 迭代 1 落地无此方法**（skin 为只读 property），见 P0-2 | ❌ |
| HUD 数据由 app 注入 renderer（gui-renderer 设计 §1.1/HudData） | **偏离：设计 `_build_hud()` 返回 dict（score/length/difficulty/high_score 字符串），gui-renderer 要求 `HudData(score:int, high_score:int, length:int, difficulty_label:str, status_label:str)` dataclass——字段名/类型/缺 status_label 全不符，见 P0-3** | ❌ |
| 零配置（架构 §配置模型） | AppConfig frozen dataclass 硬编码默认值，不读文件 | ✅ |
| 无网络（NFR-06）/无音效（R-04） | §0 明确不 import socket/urllib/http/requests/音频 | ✅ |
| 语法兼容 Python 3.8 | §0 明确不用 3.9+ 特性 | ✅ |
| 难度游戏中不可切换（FR-05） | INV-3 + `_dispatch_playing` 无难度分支 | ✅ |
| 网格 20×15 | §3.4 GameState(20,15) 与 gui-renderer GRID_COLS/GRID_ROWS=20/15 一致 | ✅ |

### 1.1 与依赖模块实际契约核对（代码实核，非纸面对纸面）

| 设计引用 | 依赖模块落地 | 结果 |
|---|---|---|
| `GameState(20, 15, difficulty, rng=Random())` | game-core `__init__(*args, **kwargs)`：`if args: raise TypeError("GameState only accepts keyword arguments")` | ❌ P0-4 |
| `game_state.step() -> GameState`（新对象） | state.py L186 返回新对象，dataclass.replace 纯函数式 | ✅ |
| `set_direction(d) -> GameState` | state.py L156 返回新对象；OVER 抛 InvalidStateError；反向静默忽略 | ✅ |
| `snapshot()` 含 `tick_ms` | types.py Snapshot 含 tick_ms 字段 | ✅ |
| `InvalidStateError` | errors.py 存在（RuntimeError 子类） | ✅ |
| `Renderer("classic")` | renderer.py `__init__(window_size, *, skin=None, ...)`：`"classic"` 当 window_size → `isinstance` 校验失败抛 RenderError | ❌ P0-1 |
| `Renderer(...).render(snapshot, hud)` | render() 存在但**前置要求 `init()`/`__enter__`**（`assert self._screen is not None`） | ❌ P0-2 |
| HUD dict（score/length/difficulty/high_score 字符串） | `HudData(score:int, high_score:int, length:int, difficulty_label:str, status_label:str)` | ❌ P0-3 |
| `Renderer("classic").set_skin(name)` | 迭代 1 落地无 set_skin；仅 `skin` 只读 property | ❌ P0-2 |
| `Renderer("classic").render(snapshot, hud)` 每帧调用（含 MENU/GAME_OVER 态） | render() 要求 `snapshot.snake_body` 非空；MENU 态 game_state=None → `_build_hud` 调 `None.snapshot()` 崩 | ❌ P0-5 |

## 2. P0（阻塞，必须修订）

### P0-1 Renderer 构造签名不符：`Renderer("classic")` 照做必挂
设计全文（§2.2/§3.4/§4.7/§5.2/§5.4/附录 A.2）用 `Renderer("classic")`（skin_name 字符串）；gui-renderer 迭代 1 落地为 `Renderer(window_size: Tuple[int,int], *, skin: Optional[Skin]=None, vsync=True, cell_size=24, grid_cols=20, grid_rows=15)`。字符串会被当作 window_size → `not isinstance(window_size, tuple)` → RenderError。**正确写法**：`Renderer((800, 600), skin=DEFAULT_SKIN)`（或省略 skin 用默认经典皮肤）。FO 按设计照抄即启动即崩。

### P0-2 Renderer 生命周期缺失 + set_skin 不存在
- gui-renderer 的 `render()` 内部 `assert self._screen is not None, "render 前必须先 init() 或 __enter__"`；`init()` 负责 `pygame.init() + display.set_mode + font.init`，且**幂等**。设计 §4.7 `_init_pygame` 自己 `pygame.init() + set_mode(800x600)` 后仅 `self._renderer = Renderer("classic")`，从不调 `renderer.init()`/`with` —— FO 照做，render 断言失败。
- 更严重：**窗口创建职责冲突**——设计让 app 自己 `set_mode(800x600)`，gui-renderer `init()` 又会 `set_mode(window_size)`（renderer 内部期望 640×480 布局常量、最小 512×472）。两处 set_mode 冲突，且 AppConfig 800×600 与 renderer 固定布局 640×480 不一致，画面留白/错位。**必须统一**：窗口创建交给 renderer.init()（传 window_size=(800,600) 并校验 ≥ 最小尺寸），app 不再 set_mode；或明确 app 自绘菜单时窗口尺寸语义。
- `set_skin(name)` 在 gui-renderer 迭代 1 **不存在**（只有只读 `skin` property）。设计 §2.2 声称"迭代 1 接受但仅 classic 生效"、附录 A.2 预告迭代 3 调用——引用的是虚构接口，应改为"迭代 1 不调用，迭代 3 待 gui-renderer 提供"。

### P0-3 HUD 契约类型/字段全不符
- 设计 §4.6 `_build_hud()` 返回 dict：`{"score": str, "length": str, "difficulty": "EASY..", "high_score": "---"}`。
- gui-renderer 要求 `HudData`（frozen dataclass）：`score:int, high_score:int, length:int, difficulty_label:str, status_label:str`。
- 差异：① dict vs dataclass；② `difficulty` 应叫 `difficulty_label`；③ **缺失 `status_label`**（renderer HUD 第 2 行 "Status: ..." 必读，OVER 时高亮，无此字段 AttributeError）；④ `high_score` 设计用字符串 "---" 占位（INV-6），但 HudData.high_score 是 int——迭代 1 占位语义与 renderer 类型冲突（可传 0，renderer 显示 "High: 0"；若坚持 "---" 需 gui-renderer 支持 str，属跨模块改契约，迭代 1 不建议）。
- 修订方向：`_build_hud` 返回 `HudData(score=snap.score, high_score=self.high_score, length=snap.length, difficulty_label=中文或枚举名, status_label=snap.status.name)`。

### P0-4 GameState 构造签名错误（位置参数）
设计 §3.4/§4.4：`GameState(20, 15, difficulty, rng=Random())` —— game-core 落地**只接受关键字参数**（`args` 非空直接 `TypeError`）。正确：`GameState(width=20, height=15, difficulty=difficulty, rng=Random())`。另注意 `rng` 可省略（默认 None 内部自建），`initial_direction`/`score_callback` 为可选关键字。FO 照抄设计即 UT 第一轮全红且非预期红。

### P0-5 菜单（MENU）/结束（GAME_OVER）画面渲染无方案，且 MENU 态必崩
- **必崩**：§3.4 `game_state=None`（首次开局时构造）、§4.2 主循环每帧无条件 `self._render()`、§4.6 `_build_hud` 调 `self.game_state.snapshot()` → MENU 态 `None.snapshot()` AttributeError。启动即崩，端到端 UT（用例 28）无法跑。
- **渲染空白**：迭代 1 出口硬需求"开始界面：标题 + 按任意键开始 + 难度选择（1/2/3 键）"与"结束画面：最终得分 + 重开 (R) / 退出 (Q)"（FR-11）——gui-renderer 迭代 1 **只画蛇/食物/背景/HUD，无菜单/结束画面渲染能力**（render 仅接受 snapshot+hud）；设计里 app 也只调 renderer.render，**没有任何 app 侧自绘方案**（标题/提示文字/菜单项由谁画？pygame.draw/font 直接调用？）。菜单与结束画面是 FR-11 验收主体，设计未给出任何可落地路径。
- 修订方向（二选一，需定夺）：① game-app 自绘菜单/结束画面（app 直接 pygame.font 渲染文字，renderer 只画对局画面；需在设计中给出绘制函数与布局）；② 扩展 gui-renderer 契约（renderer 提供 overlay/菜单渲染接口——跨模块改已 it_passed 契约，需架构/模块协调，不推荐迭代 1 动）。

### P0-6 依赖版本矛盾：引用 game-core 迭代 2 接口，却声明依赖迭代 1
- 设计 §0/附录 B 声明依赖 "game-core 迭代 1 it_passed"，但全文引用的接口形态（**纯函数式返回新对象** `set_direction`/`step`、`GameState` 仅关键字构造、`score_callback`、`Snapshot.tick_ms` 动态节拍）是 game-core **迭代 2** 的形态；当前 `code/game-core/iter-2/` 状态为 **dev_reviewing（未 it_passed）**。
- 风险：game-app 迭代 1 开发所依赖的 core 接口若在迭代 2 检视中被改，game-app 契约基础漂移。修订：设计必须明确"以 game-core 迭代 2 接口为准（dev_reviewing 中，落定后开发）"，或与当前 it_passed 的迭代 1 接口对齐（若迭代 1 接口是命令式原地修改，则 §4.4 `self.game_state = self.game_state.step()` 全错）。

## 3. P1（内部矛盾/歧义，FO 会踩坑）

### P1-1 难度选择双模型打架：MenuCursor 是死代码，↑/↓ 无效
- 设计并存两套：§1.2 `MenuCursor`（↑/↓ 移动 + Enter 确认）与 §3.3/§4.4 快捷键 1/2/3 直接选。但 `_dispatch_menu` **只处理 SELECT_EASY/MEDIUM/HARD/START/QUIT，MOVE_UP/MOVE_DOWN 无分支** → ↑/↓ 在菜单态完全无效；`MenuCursor` 枚举定义后从未被引用（死代码）。
- §3.3 注释 "SELECT_EASY：MENU 态：1 / ↑" 与 `_map_event` 实际（↑→MOVE_UP，非 SELECT_EASY）矛盾。
- 修订：二选一——① 保留 1/2/3 快捷键，删除 MenuCursor 与"↑/↓ 移动"描述；② 实现 cursor 模型（MOVE_UP/DOWN 移动高亮 + START/Enter 确认所选），删除 1/2/3 直接选。当前混合状态 FO 无法实现。

### P1-2 QUIT 处理冗余且不闭环
- §4.2 主循环 `if InputAction.QUIT in actions: break`（外层），`for a in actions` 内又 `if a == QUIT: break`（内层，永远到不了——外层已 break）。
- `_dispatch_menu`/`_dispatch_over` 里 `self._quit_requested = True` 设了但**主循环不消费该标志**（只看 actions），UT 用例 11/20 断言 `_quit_requested == True` 与主循环退出逻辑脱节。
- 修订：统一为一个退出通道——主循环只检查 `_quit_requested`（dispatch 内设置），或只检查 actions 含 QUIT（删 `_quit_requested`）。当前双通道是隐患。

### P1-3 "任意键开始"与映射实现矛盾
- FR-11/§4.8 状态机图/§3.3 注释均写"任意键(START) 开始"，但 `_map_event` 只有 `K_RETURN/K_SPACE → START`；按 WASD/方向键/其他字母在 MENU 态不开始（方向键变 MOVE_*，字母返 None）。语义与实现不符。
- 修订：要么补"MENU 态任何未映射键 → START"分支，要么把文档文字改为"回车/空格开始"。

### P1-4 窗口尺寸契约缺失
- AppConfig 默认 800×600；gui-renderer 布局固定 640×480（WINDOW_WIDTH/HEIGHT）、最小可玩 512×472、构造强校验 window_size ≥ 最小尺寸。设计未说明 renderer 构造时传什么 window_size、app 的 800×600 与 renderer 布局如何协调（800×600 窗口内 renderer 按 640×480 布局绘制 → 右侧/下方留白）。P0-2 统一窗口职责时必须一并定死。

## 4. P2（建议修订，不阻塞）

- **P2-1** `_pause_hint_shown` 字段在 §1.3 运行期状态表未声明（仅 §4.4 伪码出现），文档完整性。
- **P2-2** §1.1 说 "PAUSED 枚举先占位"，§3.2 代码却注释掉 `# PAUSED = "paused"`——占位与不占位矛盾，二选一。
- **P2-3** HUD difficulty_label 文案：规格 Q-01 拍板难度命名"简单/普通/困难"（中文），设计 §4.6 用 `self._difficulty.name`（英文枚举名）；gui-renderer HudData.difficulty_label 语义即展示标签，应传中文或明确枚举名映射。
- **P2-4** 难度选择入口提前到迭代 1（设计出口清单 ✅），而架构迭代 1 出口只列"主循环/输入/开始-结束-重开-退出"、架构把"难度选择界面"排在迭代 2——设计**越界提前**了 FR-05 入口。规格 FR-05 优先级高（R-01 拍板纳入本轮）可辩护，但应与架构迭代计划对齐说明，避免迭代 2 范围重复。
- **P2-5** `on_score` 事件名错误：架构接口清单写 `on_score(score)`，game-core 落地为 `set_score_callback(cb)`；设计附录 A.1"优先 on_score 事件"引用了不存在的 API 名，迭代 2 接入时误导。
- **P2-6** conftest 桩不完整：UT 用例 28 端到端需注入事件流（`pygame.event.get()` 队列桩），§6.2 conftest 只给了 display.set_mode 桩，无 event 桩——FO 需自建，设计应补。
- **P2-7** INV-3 描述"`set_difficulty` 显式 raise NotImplementedError"——game-core 无此方法，难度不可改是 core 字段不可变性保证；INV-3 表述应改为"难度固化于 GameState 字段，无运行中修改接口"，避免 FO 去找不存在的 set_difficulty。

## 5. 架构遵循性总体评价

- **遵循良好**：分层与依赖方向（app → renderer/core/storage，单向向下）、数据流（输入 → core → snapshot → renderer）、迭代边界（2/3/4 只预告不实装）、零配置/无网络/无音效、20×15 网格与 gui-renderer 常量一致、core 纯逻辑只读快照——方向全部正确。
- **FAIL 根因**：设计引用的是**架构文档里的理想接口**，而非**依赖模块已落地的真实接口**（gui-renderer 迭代 1 已 it_passed、接口锁定；game-core 迭代 2 代码在库）。"接口先行"红线的正确姿势是以依赖模块落地代码为准做契约核对（本评审已代核，见 §1.1），设计必须逐条对齐后复审。
- 附录 A（迭代 2/3/4 增量预告）与迭代边界管理值得肯定，修订后保留。

## 6. 修订后复审要点（下次评审先看这几条）

1. Renderer 构造传 window_size + skin，`init()` 生命周期纳入主循环（或 with 上下文），窗口职责唯一；
2. `_build_hud` 返回 `HudData`（含 status_label），high_score 占位语义与 renderer 类型一致；
3. `GameState(width=, height=, difficulty=, ...)` 关键字构造；
4. MENU/GAME_OVER 渲染方案落地（app 自绘 or renderer 扩展，含 game_state=None 分支）；
5. 难度选择单一模型（删死代码/补 ↑↓ 分支二选一）；QUIT 单一通道；"任意键开始"语义统一；
6. 依赖版本声明与所引用 core 接口形态一致。
