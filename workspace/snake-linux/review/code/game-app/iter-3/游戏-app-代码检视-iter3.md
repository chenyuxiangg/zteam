# 模块内代码检视：game-app（snake-linux v2.0.0 迭代 3）

> 检视人：MDE
> 设计：`snake-linux/design/game-app/设计-iter3-r2.md`（SE r1 评审 FAIL → r2 全部落地）
> 代码：`snake-linux/code/game-app/iter-3/`（iter-3 不新建代码目录，沿用 iter-1 源码目录增量修改）
> 测试：`snake-linux/code/game-app/iter-3/tests/test_game_app/`（67 通过）+ iter-1（181 通过）
> UT 运行：`pytest snake-linux/code/game-app/iter-3/tests/ -v` → **67 passed**
> `pytest snake-linux/code/game-app/iter-1/tests/ -v` → **181 passed**（iter-2/3 沿用无回归）

---

## 结论：PASS

| 检查项 | 结果 | 备注 |
|---|---|---|
| 1. 实现与模块设计一致（数据结构 / 接口 / 流程） | ✅ | G3-1/2/3/4/5 全部落地；r2 修订（r2-1 插值链路自洽 / r2-2 VIDEORESIZE 契约 / r2-3 _prev_snap 生命周期 / r2-4 skin_names 派生 / r2-5 InputAction=18 / r2-6 snap 参数防御 / r2-7 prev_food 始终传）全部一致 |
| 2. 实现细节质量（边界 / 异常 / 资源释放） | ✅ | SkinNotFoundError / RenderError / StorageError 兜底齐全；OVER 后 _prev_snap=None；退出码 0/1/2 路径完整；不抛/不退/不中断游戏的不变量（INV-15）实测守住 |
| 3. 可测试性（UT 可写可跑） | ✅ | 67 iter-3 UT 全绿；fake_pygame + fake_renderer_iter3 + fake_storage 三桩 + monkeypatch `create_storage`/`Renderer` 注入顺序符合 G3-R-P1-A/B；fixture 间互不泄漏 |
| 4. 代码风格符合架构约定 | ✅ | 单一职责 / no 全局变量 / R3-2 不读 renderer 私有 / R3-10 __init__ 不构造 Renderer / R3-12 CJK 字体回退链 / 退出码语义 |

---

## 1. 实现与设计一致性逐项核对

### 1.1 数据结构（G3-1 / G3-3 / G3-4）

| 设计 § | 项 | 代码落点 | 一致 |
|---|---|---|---|
| §1.1 `InputAction` enum = 18（iter-2 15 + iter-3 3，r2-5 修订） | `input.py:38-58` | `InputAction.QUIT...UNFOCUS + SET_SKIN_PREV/SET_SKIN_NEXT/RESIZE`，共 18 项 | ✅ |
| §1.1 `AppConfigV3`（frozen, 继承 AppConfig, +enable_high_dpi） | `config.py:46-58` | 完全对齐；__post_init__ 不重写（bool 无非法值）；ConfigError 父类继承 | ✅ |
| §1.2 `_skin_index: int = 0` 默认（r2-4 修订派生用 `skin_names()[_skin_index]`） | `app.py:121` | 实现一致 | ✅ |
| §1.2 `_prev_snap: Optional[Snapshot] = None`（r2-1/r2-3） | `app.py:122` | 实现一致 | ✅ |
| §1.4 字段汇总（_difficulty / _high_score / 字体 / clock 等） | `app.py:114-126` | 与设计 §1.4 完全对应 | ✅ |

### 1.2 输入映射（G3-1 / G3-2）

| 设计 § | 项 | 代码落点 | 一致 |
|---|---|---|---|
| §3.3 / §4.3 `_map_event` 不感知屏态 | `input.py:130-167` | ✅ 与设计一致 |
| §4.3 K_LEFT → SET_SKIN_PREV | `input.py:150-151` | ✅ |
| §4.3 K_RIGHT → SET_SKIN_NEXT | `input.py:152-153` | ✅ |
| §4.3 K_a 仍为 MOVE_LEFT（不映射皮肤） | `input.py:159-160` | ✅（注释已明示 K_LEFT 永远不走到这里；逻辑正确，仅 dead `or k == K_LEFT` 不美观，详 §3.4） |
| §4.3 VIDEORESIZE → RESIZE | `input.py:144-146` | ✅（r2-2 契约前置：依赖 gui-renderer iter-3 落实 RESIZABLE，**该契约尚未落实**，详 §4） |
| §4.3 总数 = 18（r2-5 修订） | `test_input_map.py` | ✅ UT 显式断言 `test_skin_actions_exist` / `test_resize_action_exists` |

### 1.3 状态机分发（G2-1 / G2-7 / G3-1 / G3-2）

| 设计 § | 项 | 代码落点 | 一致 |
|---|---|---|---|
| §4.4 `_drain_events` VIDEORESIZE 同步处理、不入 actions | `app.py:200-203` | ✅ |
| §4.4 `_drain_events` SET_SKIN 屏态分发：MENU 同步处理、其他态透传 MOVE_* | `app.py:205-211` | ✅ |
| §4.4 `_switch_skin` 循环索引 + SkinNotFoundError 兜底 | `app.py:241-262` | ✅（assert _renderer / 空注册表防御 / try-except SkinNotFoundError → stderr） |
| §4.4 `_handle_resize` RenderError 兜底 stderr 不中断 | `app.py:268-278` | ✅ |
| §4.4 `_new_game` 首行 `self._prev_snap = None`（r2-3 修订） | `app.py:280` | ✅ |
| §4.5 `_tick` step **前**保存 _prev_snap（r2-1 全链修订） | `app.py:295-313` | ✅（与 r1 错版"step 后保存"区分明确） |
| §4.6 `_interpolation_state` 真实 Chebyshev 距离防御（r2-3 修订） | `app.py:350-375` | ✅（`max(|dx|, |dy|) > 1 → None`，与 renderer `_grid_distance` 一致） |
| §4.6 alpha 公式 = `elapsed_in_tick / tick_ms`（r2-1 修订，非 `1.0 - ...`） | `app.py:383-385` | ✅ |
| §4.6 删除 `self.game_state is None` 冗余检查，改为 `if snap is None`（r2-6 修订） | `app.py:345-346` | ✅ |
| §4.6 `prev_food` 始终传（r2-7 修订，不再 None 兜底） | `app.py:389` | ✅ |
| §4.7 `_init_pygame` isinstance AppConfigV3 判定 enable_high_dpi | `app.py:151-156` | ✅（iter-2 AppConfig 兜底 True，向后兼容） |
| §4.4 `_dispatch_over(BACK_TO_MENU)` 重置 game_state=None（INV-7） | `app.py:247-249` | ✅ |

### 1.4 主循环骨架（§4.2）

| 项 | 落点 | 一致 |
|---|---|---|
| `run` / `_run_loop` / `_drain_events` / `_dispatch` / `_tick` | `app.py:131-216` | ✅ 主循环 ≤ 30 行原则守住 |
| 退出码 0/1/2 + R3-15 shutdown 兜底（`finally: self._renderer.shutdown()`） | `app.py:131-151` | ✅ |
| 失焦检测仅 PLAYING 态追加 UNFOCUS | `app.py:219-225` | ✅ |

### 1.5 `menu.py`（G3-5）

| 设计 § | 项 | 代码落点 | 一致 |
|---|---|---|---|
| §3.7 `draw_menu` 加 `current_skin_name: str = "classic"` 形参 | `menu.py:25,36,55-61` | ✅（默认值保持向后兼容；新行在 y=315，难度选项 y=220-292 与最高分行 y=340 之间） |
| §4.9 提示行加 ← → 切皮肤 | `menu.py:71-76` | ✅ |
| draw_game_over / draw_pause_overlay 沿用 iter-2 | `menu.py:88,131` | ✅ |

### 1.6 依赖契约（§0 关键决策 / §2.2 / §附录 B/ F）

- `Renderer((W,H), *, skin=..., enable_high_dpi=...)`：`code/gui-renderer/iter-3/gui_renderer/renderer.py:118-148` ✅
- `init()` / `shutdown()` / `render(snap, hud, *, interp=None)` / `set_skin` / `handle_resize` / `skin_names()` / `current_skin_name` / `InterpolationState`：**实核全部存在**（`gui-renderer/iter-3/gui_renderer/`）
- **`init()` 缺 `RESIZABLE` 标志**（`code/gui-renderer/iter-3/gui_renderer/renderer.py:206-220`）：与设计 §附录 F "实核缺失"一致，**由 gui-renderer 模块所有者落实，本设计仅声明契约前置** —— **不阻塞 game-app iter-3 PASS**，详见 §4

---

## 2. 实现细节质量

### 2.1 边界 / 异常路径

| 场景 | 实现 | 评价 |
|---|---|---|
| 皮肤注册表为空 | `app.py:248-249`：`if not skin_names: return` | ✅ 防御性 |
| SkinNotFoundError（理论不可达） | `app.py:259-261`：try-except → stderr 提示 + 维持 _skin_index | ✅ 兜底合理 |
| RenderError（窗口缩放过小） | `app.py:276-278`：try-except → stderr 提示 + 不抛/不退 | ✅ INV-15 实测守住 |
| `set_mode` 失败 / `pygame.error` | `app.py:157-158`：包 GraphicsUnavailableError → 退出码 2 | ✅ |
| HighScoreStore mkdir 失败 | `app.py:163-165`：`(StorageError, OSError)` 双类型兜底 → AppError → 退出码 1 | ✅（双类型捕获沿用 iter-2 §5.6 修订，符合 G3-R-P2-1） |
| INV-13 P0-2 score_callback 内直接写 self._high_score | `app.py:285-292` | ✅ |
| 退出码 2 路径 shutdown 兜底 | `app.py:147-150`：`finally` 内 `try: shutdown except: pass` | ✅（R3-15 沿用） |
| 失焦 platform 不支持 | `app.py:222-225`：`try/except Exception: focused=True` | ✅ 兜底 |
| `_dispatch_over(RESTART)` 重新 `_new_game` → 自动重置 `_prev_snap = None`（r2-3） | `app.py:244-246, 280` | ✅（`game_state.step()` 后重启链路中，新 game_state 自然产生新 _prev_snap=None） |

### 2.2 资源释放

- `_init_pygame` 失败时 `_renderer = None` → `run()` `finally` 内 `if self._renderer is not None: shutdown()` —— ✅ 不会有半构造 Renderer 泄漏
- `try/except Exception: pass` 吞 shutdown 异常 —— 兜底"退出码 2"路径不抛脏异常，意图合理
- 字体由 `_init_pygame` 构造，由 `pygame.font.quit()` 链释放（沿用 iter-2，无泄漏路径）

### 2.3 不变量（INV）

| # | 描述 | 落点 | 守住 |
|---|---|---|---|
| INV-1 | `_tick` 入口 `_tick_accumulator_ms.status == RUN` | `app.py:291` assert | ✅ |
| INV-7 | `_dispatch_over(BACK_TO_MENU)` 重置 game_state=None | `app.py:248` | ✅ |
| INV-8 | G2-1 删除 `_pause_hint_shown` | `app.py:119`（无字段） | ✅ |
| INV-10/11 | P0-1 方案 A 屏态同步切屏 | `app.py:236, 243, 256-257` | ✅（每次 toggle_pause 后立即写 self.screen） |
| INV-13 | P0-2 score_callback 内直接写 self._high_score | `app.py:289` | ✅ |
| INV-15 | 窗口缩放不中断游戏（新增） | `app.py:276-278` try-except | ✅（`test_app_iter3_resize.py::test_resize_during_playing_does_not_change_screen` 断言） |
| INV-16（隐式） | `_skin_index ∈ [0, len(skin_names))` | `app.py:251, 254` 取模运算 | ✅ |

### 2.4 错误矩阵（§5.6）

全部 11 个错误场景在 `app.py` 内均有对应捕获/兜底实现（exit code 0/1/2 + stderr + INV-15），无遗漏。

---

## 3. 可测试性

### 3.1 UT 框架（§6）

| 设计 § | 要求 | 实测 |
|---|---|---|
| §6.2 fake_pygame + fake_renderer_iter3 + fake_storage + monkeypatch create_storage/Renderer 注入顺序 | `conftest.py:97-145` | ✅ 与设计一致（G3-R-P1-A/B/C/D/E + G3-R-P2-6/7 全部落地） |
| §6.2 各 App fixture（app / app_in_playing / app_in_paused / app_in_game_over / app_with_storage / app_with_config_v3） | `conftest.py:145-240` | ✅ 7 个 fixture 完整 |
| §6.2 FakeEvent / make_keydown / make_resize_event 辅助类 | `conftest.py:243-272` | ✅（VIDEORESIZE 通过 `w`/`h` 构造） |
| §6.4 SK-1~11 / RS-1~7 / INTERP-1~13 / V3-1~7 全部覆盖 | iter-3 test 67 个用例 | ✅ 67/67 pass |
| §6.6 pytest 命令可跑 | 已在本机跑通 | ✅ |

### 3.2 UT 计数核对

| 用例族 | 设计要求 | 实测 |
|---|---|---|
| SK | 11 | 13（SK-1~11 + 边界 2 冗余覆盖） |
| RS | 7 | 8（RS-1~7 + 状态冗余） |
| INTERP | 13 | 20（含辅助类） |
| V3 | 7 | 14 |
| input_map | 沿用 | 10 |
| **合计 iter-3** | —— | **67 全绿** |
| 沿用 iter-2/1 | （不新计数） | 181 全绿 |

### 3.3 可测试性亮点 / 关注点

- **亮点**：`app._interpolation_state` 可单测（无 pygame 副作用）—— 与设计 §5.4 述一致
- **关注点**：`_switch_skin` 需 `_renderer is not None`（assert），UT 必须先 `app._init_pygame()`（fake_renderer_iter3 注入），fixture 编排已处理（`app`/`app_in_playing` 等都已 _init_pygame 后才用）
- **关注点**：`_handle_resize` 同 `_switch_skin`，依赖 _init_pygame 完成

### 3.4 代码风格小瑕疵（不阻塞 PASS，仅记录）

1. **`input.py:159-160` K_a/K_d 行**：注释 "永远不会命中（已被 SET_SKIN_PREV 截获）" 表明是 dead code（`or k == _pygame_attr("K_LEFT")` 在 SET_SKIN_PREV 早返回后永远走不到）。逻辑仍然正确（仅看 K_a 部分），但写法不简洁，建议下版清理（删除死分支或精简注释）。**不构成 FAIL**。
2. **`app.py:54-56` 与 `58`**：多次 `from ... import` 同一包（`from gui_renderer import ... DEFAULT_SKIN, HudData, RenderError, Renderer` + `from gui_renderer import InterpolationState, SkinNotFoundError`），可合并一处。**纯风格，不构成 FAIL**。
3. **`errors.py` 缺 `OSError` 重导出**：设计 §5.6 提到 StorageError / OSError 双类型兜底，代码已实现捕获，但 errors 模块未显式说明 OSError 兜底（仅 docstring 注释）—— 也无碍。

---

## 4. 与上游（gui-renderer）的契约依赖

| 契约 | 设计要求 | 实核（gui-renderer iter-3） | 评价 |
|---|---|---|---|
| `init()` flags = SCALED | `code/gui-renderer/iter-3/gui_renderer/renderer.py:209-215` ✅ | ✅ |
| **`init()` flags = RESIZABLE**（r2-2 P0-2 契约前置） | 实核 `renderer.py:213-220` flags=0 + `flags |= SCALED` —— **缺 RESIZABLE** | ⚠️ 契约依赖缺口 |
| `handle_resize` 保留 RESIZABLE | `renderer.py:255-294` 实核沿用 self._flags —— 同步缺 RESIZABLE | ⚠️ 跟随 init 同问题 |
| 其余 `set_skin` / `skin_names` / `current_skin_name` / `InterpolationState` / `render(interp=)` | 全部实核存在 | ✅ |

**说明**：

- 设计 §0 关键决策 ② + §2.2 + §4.10 注意点 10/16 + §附录 B + §附录 F 已**显式声明**该契约前置为 gui-renderer 模块所有者责任。
- `game-app iter-3` 代码侧已正确按契约实现（`_handle_resize` 收到事件后调 `Renderer.handle_resize`），不构成 game-app 实现错误。
- 真实窗口拖拽缩放需 gui-renderer 落实 RESIZABLE 后才能触发 VIDEORESIZE —— 这一缺口**已由设计文档透明声明**，本检视认可 game-app 侧责任完成。**不阻塞 game-app iter-3 PASS**。
- 该契约缺口由 SE 评审 `release_module ... review` 检视 gui-renderer 模块时关注。

---

## 5. 风格 / 架构约定核对

| 约定 | 实测 |
|---|---|
| Python 3.8 兼容（frozen dataclass / `from __future__ import annotations`） | ✅ |
| 无 `import socket` / `import urllib` / `import http` / `import requests` | ✅（`grep -r '^import \(socket\|urllib\|http\|requests\)' game_app/` 无结果） |
| 无 `pygame.mixer` | ✅ |
| 不读 renderer 私有（`R3-2`：surface 走 `pygame.display.get_surface()`，不读 `Renderer._skin` / `_screen`） | ✅（`grep -r 'Renderer\._screen\|Renderer\._skin' game_app/` 无业务读取；app.py:283 仅 `_renderer.current_skin_name` 公开属性） |
| `App.__init__` 不构造 Renderer / 不构造 HighScoreStore（R3-10） | ✅ |
| 退出码 0/1/2 语义（R3-15） | ✅ |
| CJK 字体回退链（R3-12） | ✅（`fonts.py` `_load_cjk_font` 6 个候选 + SDL 默认兜底） |
| `_render` 共享一次 snap（R3-11） | ✅（app.py:308 `snap = self.game_state.snapshot()` 取一次后传 hud + interp + render） |
| 单一职责：`storage.py` 仅 `create_storage`；`menu.py` 仅自绘 | ✅ |

---

## 6. 检视结论与建议

### 6.1 PASS 理由汇总

1. **设计一致性**：G3-1（皮肤切换 UI）/ G3-2（VIDEORESIZE 接入）/ G3-3（平滑插值）/ G3-4（AppConfigV3）/ G3-5（菜单皮肤行）五项增量目标全部落地，无遗漏无多余。
2. **r2 修订全部一致落地**：r2-1（step 前保存 + alpha=elapsed/tick_ms）/ r2-2（VIDEORESIZE 契约前置 + 设计同步声明）/ r2-3（_new_game 重置 + 真实 Chebyshev 防御）/ r2-4（`skin_names()[_skin_index]` 派生）/ r2-5（InputAction=18）/ r2-6（`if snap is None` 替代实例字段）/ r2-7（`prev_food` 始终传）七条修订，与设计文档 §0.r2 一一对应，UT 同步覆盖。
3. **r2-2 契约前置透明声明**：`game-app` 侧按契约正确实现 `_handle_resize`；gui-renderer 缺 RESIZABLE 由设计 §附录 F 与 issue-003 透明登记，**不阻塞 game-app iter-3 PASS**。
4. **可测试性达成**：67 iter-3 UT + 181 iter-1/2 UT 全绿，UT 框架 §6.2 fixture 化按 G3-R-P1-A/B/C 落实，真实 IO 彻底断绝。
5. **边界 / 异常路径完整**：SkinNotFoundError / RenderError / StorageError / OSError / GraphicsUnavailableError / ConfigError 兜底齐全；INV-15（缩放不中断）/ INV-13（high_score 同步）/ INV-11（屏态同步切屏）守住。
6. **架构风格一致**：R3-2 / R3-10 / R3-11 / R3-12 / R3-15 全沿用，单一职责 / 不可变 / 显式常量。

### 6.2 不构成 FAIL，仅供下版参考（详 §3.4）

1. `input.py:159-160` K_a/K_d 行 dead `or k == _pygame_attr("K_LEFT/RIGHT")` 分支 —— 建议下版清理（不影响功能）。
2. `app.py` 中 `from gui_renderer import ...` 重复两处 —— 建议合并。
3. `errors.py` docstring 可加 OSError 兜底说明（已实现在 app.py）。

### 6.3 跨模块契约提示（非本检视范围）

- gui-renderer iter-3 需在 `init()` / `handle_resize` 内 flags 增加 `getattr(pygame, "RESIZABLE", 0)`，否则真实窗口 VIDEORESIZE 事件源断裂，FR-09 不可达。**此为 gui-renderer 模块责任，由 SE 评审 gui-renderer iter-3 时关注。**

---

## 检视签字

- 检视图：`snake-linux/review/code/game-app/iter-3/游戏-app-代码检视-iter3.md`
- 输入：设计 `snake-linux/design/game-app/设计-iter3-r2.md` + 代码 `snake-linux/code/game-app/iter-3/`（含 iter-1 沿用）
- 测试命令：`pytest snake-linux/code/game-app/iter-3/tests/ snake-linux/code/game-app/iter-1/tests/ -v` → 248 passed
- 结论：**PASS**（代码实现与设计 r2 一致；r2-2 契约前置按设计透明声明，不阻塞 game-app 模块）
- 后续：FO 可进入下一阶段（MTO 集成测试 / 用例 TE 评审）
