# 功能模块设计评审意见：game-app（snake-linux v2.0.0 迭代 1）r3

> SE 评审 · 依据：模块设计 `snake-linux/design/game-app/设计-r3.md`（修订版）+ 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）+ 上轮评审 `snake-linux-game-app-design-iter1-r2.md`（FAIL）
> 接口实核（本轮重新对落地代码逐条核对，非纸面对纸面）：
> - game-core **迭代 2** `code/game-core/iter-2/game_core/`（state.py / types.py / params.py / errors.py / __init__.py）——it_passed，契约锁定
> - gui-renderer **迭代 1** `code/gui-renderer/iter-1/gui_renderer/`（renderer.py / types.py / constants.py / __init__.py）——it_passed，契约锁定
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：PASS**
- 一句话理由：r2 的 **1×P0（None→START 转换点三处矛盾）+ 1×P1（直读 `_renderer._screen` 私有属性）+ 13×P2 全部正确修订并通过逐条实核**——转换点唯一落在 `_drain_events` 屏态兜底（含 UT 9a~9e/38 断言链），menu 自绘改走 `pygame.display.get_surface()` 且形参收窄；本轮新引用接口（`Renderer.shutdown()` / `fps_metric()` / 字体回退链 / `_tick` 循环内重读 tick_ms）经依赖代码实核全部真实存在且语义匹配；仅发现 6 项 P2 级文档表述/UT 笔误（不阻塞，FO 可落地），见 §5。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点（r3） | 结果 |
|---|---|---|
| 模块类型：上层应用，依赖 game-core / gui-renderer / platform-storage | §0 类型/依赖一致；迭代 1 不 import platform-storage（R3-6 已注明 iter-2 it_passed 契约锁定） | ✅ |
| 迭代排期：game-app 迭代 1,2,3,4（分工表） | §0 迭代 1 = 最小可玩闭环；2/3/4 只预告（附录 A） | ✅ |
| 迭代 1 出口 = 主循环/输入/开始-结束-重开-退出（架构） | §0 出口清单 ✅8 + ❌7；难度选择提前到迭代 1（R2-14 用户拍板，R3-3 分工表备注） | ✅（范围调整已论证） |
| 数据流：输入 → core.set_direction/step → snapshot → renderer.render | §2.1 数据流图一致；MENU/GAME_OVER 自绘不调 renderer.render（R2-5） | ✅ |
| `GameState(width, height, difficulty)`（架构 §接口清单） | `GameState(width=20, height=15, difficulty=..., rng=Random())` 全关键字，与 game-core 落地 `__init__`（仅关键字，args 非空抛 TypeError）一致 | ✅ |
| `Renderer(skin_name)` + `render(snapshot)`（架构 §接口清单） | `Renderer((640,480), skin=DEFAULT_SKIN)` + `init()` 后 `render(snapshot, hud)`，与 gui-renderer 落地一致 | ✅ |
| HUD 数据由 app 注入 renderer（HudData） | `HudData` dataclass 5 字段（score/high_score/length/difficulty_label/status_label），high_score=0 int 占位 | ✅ |
| 零配置（架构 §配置模型） | AppConfig frozen dataclass 硬编码默认值，不读文件 | ✅ |
| 无网络（NFR-06）/无音效（R-04） | §0/§4.10 明确不 import socket/urllib/http/requests、不 import pygame.mixer | ✅ |
| 语法兼容 Python 3.8 | §0 约束 + 代码示例用 Optional/Tuple/List 而非 3.9+ 语法 | ✅ |
| 难度游戏中不可切换（FR-05） | INV-3 + `_dispatch_playing` 无 SELECT_* 分支（UT-36 覆盖） | ✅ |
| 网格 20×15 | GameState(20,15) 与 gui-renderer GRID_COLS/GRID_ROWS=20/15 一致 | ✅ |
| 窗口职责单一（P0-2 修订方向） | 窗口创建唯一由 `renderer.init()` 承担，app 不 set_mode；自绘走 `pygame.display.get_surface()` | ✅ |
| 退出 1 秒内无残留进程（FR-11） | run() finally 调 `Renderer.shutdown()`（幂等）+ 退出码 0/1/2；退出码 2 路径外层 finally 兜底（R3-15） | ✅ |

### 1.1 与依赖模块实际契约核对（代码实核，本轮重新逐条验证，含 r3 新引用）

| 设计引用（r3） | 依赖模块落地 | 结果 |
|---|---|---|
| `Renderer((640,480), skin=DEFAULT_SKIN)` | renderer.py `__init__(window_size, *, skin=None, vsync=True, cell_size=24, grid_cols=20, grid_rows=15)`；(640,480)=WINDOW_WIDTH/HEIGHT，≥ 最小 (512,472)（=GRID_COLS*CELL_SIZE+2*PLAYFIELD_X=20*24+32=512；=PLAYFIELD_Y+GRID_ROWS*CELL_SIZE+PLAYFIELD_X=(80+16)+360+16=472） | ✅ |
| `renderer.init()` 幂等、render 前必须 init | init() 幂等（`if self._initialized: return`）；render 内 `assert screen is not None, "render 前必须先 init() 或 __enter__"` | ✅ |
| `renderer.shutdown()` 幂等（INV-5/R3-15 双路径兜底） | shutdown()：`pygame.display.quit() + pygame.font.quit() + pygame.quit() + _initialized=False`，幂等 | ✅ |
| `renderer.render(snap, hud)` 仅 PLAYING 态调用 | render 要求 snapshot.snake_body 非空（否则 RenderError）；PLAYING 态 game_state 非 None 且 body ≥3 | ✅ |
| `Renderer.fps_metric()` 回归（§0 出口清单） | renderer.py 存在 `fps_metric` 方法（r3 新引用，实核存在） | ✅ |
| `HudData(score:int, high_score:int, length:int, difficulty_label:str, status_label:str)` | gui_renderer/types.py HudData 5 字段一致；`from gui_renderer import HudData` 可导入（__init__ re-export） | ✅ |
| `DEFAULT_SKIN` | gui_renderer/__init__.py re-export 存在 | ✅ |
| `GameState(width=20, height=15, difficulty=..., rng=Random())` | state.py `__init__`：仅关键字；allowed={width,height,difficulty,rng,initial_direction,score_callback} | ✅ |
| `set_direction(d) -> GameState`（新对象）；反向静默 | state.py 存在；长度 ≥2 反向静默忽略/长度 1 放行 | ✅ |
| `step() -> GameState`（新对象，纯函数） | state.py 存在（dataclasses.replace） | ✅ |
| `snapshot()` 含 tick_ms（speed_curve 动态节拍） | types.py Snapshot 含 tick_ms；params.py `speed_curve = max(MIN_TICK_MS[diff], base - k*score)`，score=0 时 250/160/100 | ✅ |
| **`_tick` while 循环逐拍重读 tick_ms（R3-8）不会死循环** | speed_curve 下限 MIN_TICK_MS={EASY:100, MEDIUM:80, HARD:50}，tick_ms 恒 ≥50>0，每拍累加器必减正数，循环必然终止 | ✅（关键安全属性实核） |
| `InvalidStateError` | errors.py 存在（RuntimeError 子类），game_core re-export | ✅ |
| `GameState.set_score_callback(cb)`（迭代 2 接入预告） | state.py 实例方法存在；设计仅作预告不调用 | ✅ |
| 迭代 1 不调用 `toggle_pause()` | 设计 P 键仅置 `_pause_hint_shown`（INV-8），不触碰 core | ✅ |

## 2. r2 P0-1 修订验证（「任意键开始」None→START 转换点全文统一）——通过

| r2 指出的矛盾点 | r3 修订 | 实核结果 |
|---|---|---|
| 修订摘要说 `_map_event` 归一 | 修订摘要 R3-1 明确：转换点唯一 = `_drain_events` 屏态兜底 | ✅ 摘要/§3.3/§4.3/§4.4/§4.9/§6.4 UT 全部一致 |
| §4.3 注说 `_dispatch_menu` 兜底 None | §4.3 `_map_event` 不感知屏态、未映射返 None；docstring 注明由 `_drain_events` 兜底 | ✅ |
| §4.4 注说 `_drain_events` 已替换 | §4.4 `_drain_events` 实际代码实现：`action is None and MENU → START`；`action not in _MENU_RESERVED_ACTIONS and MENU → START` | ✅ 代码即承诺 |
| §4.4 代码 `elif action is None: pass` | `_dispatch_menu` 删除 None 分支，注释说明 None 已被 drain 兜底 | ✅ |
| 菜单提示「Enter / 任意键 开始」与转换范围不符 | 提示改「Enter / 空格 / 其他键 开始」；状态机图同步 | ✅ |
| 方向键/WASD 在 MENU 态语义 | MENU 态 MOVE_* 归一为 START（§4.4 第二个分支），按 W/A/S/D/方向键也能开局 | ✅ |

转换范围最终定义：MENU 态保留键 = QUIT / SELECT_EASY/MEDIUM/HARD / TOGGLE_PAUSE / RESTART（`_MENU_RESERVED_ACTIONS`），其余 KEYDOWN（含 None）→ START。UT 9a/9b/9c/9d/9e/38 断言链完整覆盖 4 分支（None→START、方向键→START、保留键透传、PLAYING 透传、QUIT 优先级）。

## 3. r2 P1-1 修订验证（menu 自绘不读 renderer 私有）——通过

- menu.py 不再接收 `App` 实例：`draw_menu(surface, title_font, body_font, difficulty)` / `draw_game_over(surface, title_font, body_font, score)`（§3.7），surface 由 `pygame.display.get_surface()` 提供（§4.8），与 `Renderer.init()` 内 set_mode 创建的 surface 等价且不碰 `_screen`；
- §0.5 边界 / §4.10.4「不读 gui-renderer 私有属性」维持原约束，与实现一致（不再需要受控例外声明）；
- UT-40 以 spy 断言 `app._renderer._screen` 访问次数 = 0、`get_surface()` 调用次数 = 1，机制可验证；
- 顺带修复：自绘函数不再扒 `app._difficulty` / `app._menu_title_font` 等私有字段，形参显式传入。

## 4. 13×P2 修订验证（逐条核对，全部落地且有 UT 支撑）

| r2 P2 | r3 修订落点 | 实核 |
|---|---|---|
| P2-1 分工表迭代 2 出口残留「难度选择界面」 | 附录 B 备注「难度 UI 已在迭代 1 完成，迭代 2 仅承接最高分展示+重置」 | ✅（分工表.md 实体同步见 §6 行动项） |
| P2-2 字段命名三套并存 | 统一 `_difficulty` / `_high_score`（§1.2/§1.3/§4.4/§4.6/§6.2/§6.4 同步） | ✅ |
| P2-3 `_running` 未声明 | §1.3 状态表补 `_running: bool = True` | ✅（表述微瑕见 P2-N2） |
| P2-4 game-core iter-2 状态过时 | 改「it_passed，契约已锁定」；fallback 流程降级 | ✅ |
| P2-5 `_quit()` 死代码 + dispatch QUIT 分支不可达 | 删除 `_quit()` 定义与两处 QUIT 分支；UT-41（`hasattr(app,'_quit') is False`）/UT-42（dispatch 不写 `_running`） | ✅ |
| P2-6 帧首 tick_ms 漂移 | `_tick` 循环内逐拍重读 `tick_ms`；UT-19a 吃食加速序列断言 | ✅ |
| P2-7 InvalidStateError 包装契约未落实 | §5.6 改「理论不可达（INV-1/2 保护），不包装」；`_dispatch_playing` 无 try/except；UT-23 用 pytest.raises 验证不包装 | ✅ |
| P2-8 Renderer 构造点两处矛盾 | `App.__init__` 只置 `_renderer = None`，构造+init 统一在 `_init_pygame`；UT-1 断言改 `_renderer is None` | ✅ |
| P2-9 event_queue fixture 死代码 | 删除；conftest 改 `fake.event.get.return_value` / `side_effect=[[evt1],[evt2],...]` | ✅ |
| P2-10 中文豆腐块 | `_load_cjk_font` 候选 5 字体 match_font 回退链 + `Font(None,size)` 兜底；UT-39 序列断言 | ✅ |
| P2-11 每帧两次 snapshot | `_render` 取一次 snap 传 `_build_hud(snap)`；UT-29 spy 断言 snapshot() 调用 1 次 | ✅ |
| P2-12 渲染类用例缺 init 前置 | 新增 `app_in_playing` fixture（已 `_init_pygame`+PLAYING）；UT-28/29/30 改用 | ✅ |
| P2-13 退出码 2 路径不清理 | `run()` 抽 `_run_loop()` + 外层 try/finally，退出码 2 也尝试一次 shutdown（幂等）；UT-32 | ✅ |

## 5. 新发现问题（P2，不阻塞 PASS；FO 实现时注意，迭代 2 或下轮修订消化）

- **P2-N1** `App(fps_cap=0)` 与 `App.__init__` 签名矛盾：§5.6 错误矩阵 + UT-33 写 `App(fps_cap=0)`，但 §3.4 签名仅 `__init__(self, config: AppConfig = AppConfig())`——照抄会 `TypeError: unexpected keyword argument 'fps_cap'` 而非 ConfigError。修订（二选一）：① UT-33/§5.6 改 `App(AppConfig(fps_cap=0))`（ConfigError 在 AppConfig 构造期抛），且 §3.5 main() 明确 try 覆盖 App 构造（`try: app = App(); return app.run() except AppError:`）；② 或 App.__init__ 加 `**kwargs` 转发 AppConfig（改动签名，不推荐，破坏 §附录 A.4「公开方法签名迭代 1~4 不变」）。
- **P2-N2** §1.3「`_running`：QUIT action 唯一置 False 的字段」与 §4.2 代码不符：主循环 `if QUIT in actions: break` 直接 break，从不写 `_running = False`（行为正确，run() 返回即退出）。建议 §1.3 改「主循环退出标志；QUIT 由主循环 break 退出（_running 保留 True）；未来迭代若需从 dispatch 内部退出（OVER→MENU）再置 False」。
- **P2-N3** §4.4 `_dispatch_menu` 注释「MOVE_*/TOGGLE_PAUSE/RESTART 理论上进不来」前半句不精确：TOGGLE_PAUSE/RESTART 在 `_MENU_RESERVED_ACTIONS` 内，MENU 态会原样透传进 `_dispatch_menu` 并被末尾显式忽略兜住（行为正确），但注释应改「MOVE_* 进不来；TOGGLE_PAUSE/RESTART 显式忽略」。关联文案：菜单提示「Enter / 空格 / 其他键 开始」中「其他键」含 P/R 两键实际不开始（被保留），可接受（功能键保留是 R3-1 明确设计），建议提示微调为「Enter / 空格 / 其他键 开始（1/2/3 选难度，P/R 为功能键）」或维持现状。
- **P2-N4** UT-24 字段列表笔误：HudData 字段名为 `high_score`，UT-24 写成「_high_score/int」（与 app 内部字段混写）；UT-25 已正确用 `high_score`。仅改 UT-24 文案。
- **P2-N5** §5.6「App.run() 中未捕获异常 → 兜底 except Exception」与 §4.2 代码不符（代码仅 `except AppError`）：行为等价（解释器兜底 = stderr traceback + 退出码 1，与 §5.6 描述结果一致），但建议统一——删 §5.6 该行改「解释器兜底」，或代码补 `except Exception`。
- **P2-N6** `App.__init__` 默认参数 `config: AppConfig = AppConfig()` 在 import 期求值一次（frozen 不可变，功能无害），但若未来 AppConfig 默认值依赖运行期环境会踩坑；建议改 `config: Optional[AppConfig] = None` + 构造时 `config or AppConfig()`。非阻塞。

## 6. 复审要点与 SE 行动项

1. **SE 侧行动项（本轮同步处理）**：按 r3 附录 B 建议，分工表迭代 2 的 game-app 行「难度选择/暂停继续/最高分展示重置」需补备注「难度选择 UI 已在迭代 1 完成（R-01 用户拍板提前），迭代 2 仅承接暂停继续/最高分展示+重置」——避免后续迭代 2 范围复查误判重复；
2. FO 开工前先消化 §5 六项 P2（尤其 P2-N1 的 UT-33 写法，选方案① 不碰签名）；
3. 契约实核层面 r3 已全部对齐锁定代码，无 P0/P1；后续若 game-core/gui-renderer 迭代 2/3 改动锁定契约，需按 r3 附录 B「若未来 core 改动需重核」流程重核本文 §3.4/§4.4/§4.6/§6.4。

> 说明：本轮 PASS 基于 r2 的 P0/P1 修订正确性 + 依赖契约逐条实核 + 新问题均不阻塞（全部为文档表述/UT 笔误级，修法明确）。r3 的 42 条 UT 清单 + conftest + 14 步 TDD 步骤自洽，FO 可据此开展 TDD。
