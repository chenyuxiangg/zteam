# SE 评审意见：game-app 迭代 2 功能模块设计（设计-iter2-r1）

> 评审人：SE · 2026-08-14
> 评审对象：`snake-linux/design/game-app/设计-iter2-r1.md`（MDE r1 首发）
> 评审基线：架构 `snake-linux/arch/v2.0.0/架构设计.md` + `功能模块分工表.md`；依赖契约实核 `code/game-core/iter-2/`、`code/gui-renderer/iter-3/`、`code/platform-storage/iter-2/`（均 it_passed）；代码基线 `code/game-app/iter-1/`（it_passed）；iter-1 评审 `review/design/game-app/iter-1/r3`（PASS）

## 结论：FAIL

设计整体框架完整（依赖契约逐条实核通过、架构遵循良好、UT 矩阵 ~70 条与 7 阶段 TDD 步骤自洽），但存在 **2×P0 内部自相矛盾（代码示例与 UT/不变量声明直接冲突，FO 按文落地必然崩溃或 UT 必红）+ 3×P1（一处异常类型契约错配、一处键位语义被破坏、一处 fixture 注入失效）**。P0 未修前 FO 无法开展 TDD，须 MDE 修订后复审。

---

## 一、P0（阻塞，必须修订）

### P0-1：PAUSED 屏态同步断链——「自动转屏」无实现，toggle_pause 后同帧必然崩溃

**位置**：§3.4（App docstring「自动转屏：core 返回 PAUSED → screen=PAUSED」）、§4.4（`_dispatch_playing` TOGGLE_PAUSE/UNFOCUS 分支、`_dispatch_paused`）、§4.5（`_tick`）、§6.4（UT P-1/P-2）。

**问题**：
1. `_dispatch_playing(TOGGLE_PAUSE)`（§4.4 第 883~885 行）与 `_dispatch_playing(UNFOCUS)`（§4.4 第 886~889 行）调 `toggle_pause()` 后**均未同步 `self.screen`**；`_dispatch_paused(TOGGLE_PAUSE)` 同样未把 screen 改回 PLAYING。
2. 设计声称的「自动转屏」落点 `_tick`（§4.5 第 934~936 行 `elif new_status == GameStatus.PAUSED`）是**死代码**：实核 game-core iter-2 `state.py`，`step()` 在 `status != RUN` 时直接抛 `InvalidStateError`，只可能返回 RUN/OVER，**永不返回 PAUSED**——该检测分支不可达。
3. 主循环（§4.2）dispatch 后 `if self.screen == AppScreen.PLAYING: self._tick(dt_ms)`——P 键/失焦后 screen 仍为 PLAYING → 进入 `_tick` → 开头 `assert self.game_state.status == GameStatus.RUN`（§4.5 INV-1）在 toggle_pause 后 **AssertionError 崩溃**。INV-1「screen==PLAYING ⇒ status==RUN」与「dispatch 内 toggle 不切屏」直接冲突。
4. §6.4 UT P-1 断言 `_dispatch_playing(TOGGLE_PAUSE)` 后 `screen == PAUSED`、P-2 断言 `screen == PLAYING`——按 §4.4 代码实现**必然失败**。设计文档内部（代码示例 vs UT vs 不变量）三方矛盾。

**修法建议**（MDE 选一，全文统一）：
- 方案 A（推荐，单点同步）：dispatch 内三处 toggle 后显式切屏——`_dispatch_playing` 的 TOGGLE_PAUSE/UNFOCUS 分支在 toggle 后 `self.screen = AppScreen.PAUSED`；`_dispatch_paused` 的 TOGGLE_PAUSE 分支 toggle 后 `self.screen = AppScreen.PLAYING`。同时删除 `_tick` 内死代码 PAUSED 检测分支（或改防御性注释），并把 INV-10/11 与 `_tick` 的 `assert status==RUN` 改为「`_tick` 仅 PLAYING 态调用（INV-10），调用时 status 必为 RUN（INV-1 前置条件成立）」的表述。
- 方案 B：主循环每帧末尾按 `game_state.status` 单点同步 screen（`screen = {RUN: PLAYING, PAUSED: PAUSED, OVER: GAME_OVER}[status]`），`_dispatch_*` 不再切屏。
- 无论选哪个，§6.4 P-1/P-2/P-3 与 §4.4/§4.5 必须同步改写为一致语义。

### P0-2：INV-13「回调同步 _high_score」与 §4.6 实现矛盾——本局破纪录不显示，UT SC-2 必红

**位置**：§1.4 INV-13、§3.4 `_new_game`（第 434~439 行 nonlocal `_high` 版本）、§4.6 `_new_game`（第 951~961 行 `_high_ref` dict 版本）、§6.4 UT SC-2。

**问题**：
1. 两处回调实现（§3.4 与 §4.6，本身互不一致）都只更新**回调闭包内变量**（nonlocal `_high` / `_high_ref["v"]`），**从不写 `self._high_score`**；而 HUD（`_build_hud` → `high_score=self._high_score`，§4.8）与 GAME_OVER 画面（`draw_game_over(high_score=self._high_score)`）每帧读的都是 `self._high_score`。
2. 实际效果：一局中吃食破纪录 → `storage.save()` 已落盘（core cache 更新）但 `self._high_score` 不变 → HUD 与 GAME_OVER 画面**显示旧最高分**，直到下次 `_new_game` 才从 `storage.load()` 刷新。FR-13「最高分展示」在当局破纪录场景下功能缺失。
3. §6.4 UT SC-2 断言 `app._high_score == 10`——按 §4.6 实现**必然失败**。INV-13 声明与实现代码矛盾。

**修法建议**：回调内直接同步实例字段：`self._high_score = max(self._high_score, new_val)`（`_high_ref`/nonlocal 容器可删，闭包内直接写 `self._high_score` 即可，UT 用注入的 app 实例天然可断言）；§3.4 与 §4.6 合并为一处权威实现（建议以 §4.6 为基底），消除双版本。

---

## 二、P1（不阻塞 PASS 判定，但 MDE 修订时应一并修）

### P1-1：`HighScoreStore.__init__` mkdir 失败抛的是 OSError 而非 StorageError——「用户数据目录不可写」包装失效

**位置**：§4.7（`except StorageError as e: raise AppError(...)`）、§5.5 鲁棒性表「用户数据目录不可写」行。

**实核**：platform-storage iter-2 `highscore.py` —— `__init__` 内 `self.path.parent.mkdir(parents=True, exist_ok=True)` 失败抛**裸 OSError（PermissionError 等）**；`StorageError` 仅在 `save()` 内包装 `atomic_write_json` 的 OSError 时抛出。文档注释也明确「load 永不抛异常给上层（仅 __init__ 在 mkdir 失败时抛 StorageError）」——**注释与代码不符，代码事实是抛 OSError**。
**后果**：目录不可写时 `except StorageError` 捕获不到 → 裸 OSError 上浮 → `main()` 的 `except AppError` 也捕获不到 → 解释器兜底裸 traceback，违反 NFR-03「可读错误提示 + 无裸 traceback」。
**修法**：`_init_pygame` 改为 `except (StorageError, OSError) as e: raise AppError(f"用户数据目录不可写: {e}") from e`（同时建议向 platform-storage 提 issue：__init__ mkdir 失败应包 StorageError，与模块自身 docstring 对齐）。

### P1-2：GAME_OVER 态 Q 键被误转 BACK_TO_MENU——无法在结束画面退出

**位置**：§4.3 `_map_event`（`_QUIT_KEYS = (K_q, K_ESCAPE)` 两者同归 QUIT）、§4.4 `_drain_events` GAME_OVER 覆盖（`if action == QUIT and ev.type != pygame.QUIT: action = BACK_TO_MENU`）。

**问题**：`_map_event` 对 ESC 与 Q **不可区分地**都返回 QUIT；`_drain_events` 的 GAME_OVER 覆盖只排除窗口关闭事件（`pygame.QUIT`），**无法区分 ESC 与 Q** → GAME_OVER 态按 Q（用户意图退出）也被转成 BACK_TO_MENU。与 §4.8 `draw_game_over` 提示语「Q 退出」直接矛盾；GAME_OVER 态实际无法直接退出（须先回菜单再按 Q）。
**修法**：`_map_event` 对 ESC 返回独立 action（如新增 `InputAction.ESCAPE` 或 `QUIT_BY_ESC`），`_drain_events` 仅对该 action 做 GAME_OVER 覆盖；Q 保持 QUIT 直通主循环 break。UT B-1/B-4 同步补 ESC/Q 区分断言。

### P1-3：§6.2 fixture 注入 fake_storage 被 `_init_pygame` 无条件覆盖——UT 触碰真实用户目录

**位置**：§6.2 `app_in_playing`/`app_in_paused` fixture（先 `a._storage = fake_storage` 再 `a._init_pygame()`）、§4.7 `_init_pygame`（无条件 `self._storage = create_storage()`）。

**问题**：`_init_pygame` 内 `self._storage = create_storage()` 会**覆盖** fixture 刚注入的 fake_storage；且 `create_storage()` 无参 → 真实 `get_user_data_dir()` → UT 实际构造真实 HighScoreStore 并读写 `~/.local/share/SnakeLinuxGUI/highscore.json`（创建真实目录、受本机既有最高分文件影响 → 不确定 + 污染开发机）。§6.2 注释「直接注入 fake_storage，跳过 _init_pygame 内 create_storage()」与实际代码行为不符。
**修法**：`_init_pygame` 改为 `if self._storage is None: self._storage = create_storage()`（已注入则跳过）；或 fixture 在 `_init_pygame()` **之后**注入 fake_storage。两处 fixture 统一。

---

## 三、P2（文档/UT 级，FO 落地时注意，不阻塞）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P2-1 | §4.3 | input.py 示例改为**模块级常量直接引用**（`_PAUSE_KEY = pygame.K_p` 等），与 iter-1 实际代码的 `_pygame_attr(name)` 延迟读取模式（`input.py` 头注释 + `_map_event` 全部常量走 `_pygame_attr`）冲突。照抄会破坏 iter-1 既有测试基建（无 pygame 环境无法 import）。§6.2 fake_pygame fixture 也漏了 `game_app.input` 的 monkeypatch 项，且新增 `import pygame`（iter-1 conftest 无此依赖，用常量字典） | 明确「沿用 iter-1 `_pygame_attr` 模式，仅增量加 H/Backspace 分支」；fixture 补 input 模块替换 |
| P2-2 | §6.4 P-5 | 引用 `app_in_game_over` fixture——iter-1 不存在、§6.2 也未新增；且「OVER 态调 toggle_pause 抛 InvalidStateError」在 app 层**不可达**（GAME_OVER 态 dispatch 走 `_dispatch_over`，TOGGLE_PAUSE 被忽略不调 core） | 新增 fixture 或改为直接 `pytest.raises(InvalidStateError)` 调 `app.game_state.toggle_pause()`（先手动把 status 置 OVER） |
| P2-3 | §6.4 P-6 | 「pending_direction 由 None → some → None」序列描述含糊：app 层 PAUSED 态 MOVE_* 被忽略，pending 只能先在 RUN 态 set_direction 构造 | 补前置步骤：RUN 态按方向键 → P → P（依赖 core INV-8 清 pending） |
| P2-4 | §3.5 | `main()` 公开 API 表写「捕获 ConfigError/AppError/StorageError」——iter-1 `main()` 实际仅 `except ConfigError/AppError`；StorageError 已被包成 `StorageUnavailableError(AppError)`，无需也不应单独捕获 | 删 StorageError 项，与 §4.2/iter-1 对齐 |
| P2-5 | §3.4 vs §4.6 | `_new_game` 双版本实现不一致（nonlocal `_high` vs `_high_ref` dict；`self._storage.load()` 只有注释 vs 有赋值） | 随 P0-2 合并为一处权威实现 |
| P2-6 | §4.8 `draw_pause_overlay` 示例 | 存在废代码行 `big_font = ... if False else body_font`（§4.8 第 2 步注释）；「PAUSED 大字 32px」注释与实际 `body_font`（22px）直接渲染不一致；遮罩矩形色值硬编码 128 但 §4.1 声明走 `PAUSE_OVERLAY_ALPHA` 常量 | 清理示例代码，字号语义与实现二选一（建议新增放大字号 font 或明确 22px） |
| P2-7 | §4.4 | `_dispatch_playing` 里 `assert self.game_state is not None` 后接 `self.game_state.toggle_pause()`——iter-1 风格是 `# type: ignore[union-attr]` 注释；断言风格与 iter-1 不一致（小） | 统一风格即可 |

---

## 四、通过项核验（契约实核 + 架构遵循，均 ✅）

### 依赖契约逐条实核（对照锁定代码，非仅文档）

| 设计引用 | 实核结果 |
|----------|----------|
| `GameState(width=, height=, difficulty=, rng=, initial_direction=, score_callback=)` 全关键字 | ✅ iter-2 `state.py`：`__init__` 仅接受 kwargs，allowed 集合完全一致；`score_callback` 字段存在（repr=False, compare=False） |
| `toggle_pause()`：RUN↔PAUSED、OVER 抛 InvalidStateError、PAUSED→RUN 清 pending（INV-8） | ✅ 与 `state.py` 逐行一致 |
| `set_score_callback(cb)` 返回新 GameState | ✅ 存在；设计「回调不延续、_new_game 重新注册」前提成立 |
| `step()` 仅 RUN 可调，PAUSED/OVER 抛 InvalidStateError | ✅；**并据此确认 P0-1 的 _tick 死代码问题** |
| `set_direction` PAUSED 静默忽略 | ✅ |
| `snapshot().tick_ms = speed_curve(score, difficulty)`；tick_ms 下限 ≥50 | ✅ `params.py`；_tick while 循环必终止（R3-8 安全属性保持） |
| `HighScoreStore(path=None)` / `load()` 损坏返 0 / `save()` 仅升分落盘抛 StorageError / `reset()` | ✅ `highscore.py` 逐条一致（**除 P1-1：__init__ mkdir 抛 OSError**） |
| `Renderer((W,H), skin=..., cell_size/grid_cols/grid_rows 有默认值)` | ✅ iter-3 `renderer.py`：`cell_size=CELL_SIZE(24)` 等默认；`skin=None→DEFAULT_SKIN`；iter-2 不调 set_skin/handle_resize/interp 的边界正确 |
| `HudData` 5 字段（score/high_score/length/difficulty_label/status_label） | ✅ iter-3 `types.py` |
| `DEFAULT_SKIN` / `SKIN_REGISTRY` / `RenderError` 导出 | ✅ iter-3 `__init__.py` |

### 架构遵循（对照 arch/v2.0.0）

- ✅ 依赖方向单向（app → core/renderer/storage），不侵入依赖模块内部（仅公开 API + `pygame.display.get_surface()`，R3-2 保持）；
- ✅ 零配置 / 无网络 / 无音效 / 不写系统目录（highscore 走 `get_user_data_dir()`，NFR-07）；
- ✅ Python 3.8 兼容约束保持（frozen dataclass + `__post_init__` 均为 3.7+ 特性）；
- ✅ 迭代边界与分工表一致：难度选择 UI 不重复（分工表备注「难度 UI 已在迭代 1 完成」✓）；iter-3/4 增量仅预告不实现（§附录 A）；
- ✅ AppConfig 最小窗口 512×472 与 renderer 最小可玩尺寸精确一致（`20*24+2*16=512`、`96+15*24+16=472`），G2-R-N1 校验语义自洽；
- ✅ 退出码 0/1/2 语义与 iter-1 一致；R3-15 shutdown 兜底保持；
- ✅ iter-1 r3 遗留 6 项 P2-N1~N6 消化方向与 r3 评审建议一致（P2-N1 选方案①）；注：iter-1 `config.py` 已含 `__post_init__` 校验，G2-R-N1 实际为文档/UT 写法统一，不新增行为；
- ✅ 新增文件组织决策（不建 iter-2 目录、`storage.py` 包装、`test_app_iter2_*.py`）合理，PyInstaller collect 补 platform_storage 正确。

### 可落地性（FO TDD 依据）

- ✅ UT 矩阵规模与组织完整（iter-1 42 条沿用 + G2 系列 ~28 条 + G2-R-N1 5 条）；conftest 桩、断言规范、7 阶段 TDD 步骤框架自洽；
- ❌ **但 P0-1/P0-2 使 UT P-1/P-2/SC-2 与实现互相矛盾，P1-3 使 fixture 失效**——P0/P1 修订前不能交付 FO。

---

## 五、修订要求（MDE 下次提交前自查）

- [ ] P0-1：PAUSED 屏态同步方案落地（方案 A/B 选一），§4.4/§4.5/§1.4 INV-1/10/11/§6.4 P-1~P-3 全文一致；
- [ ] P0-2：score_callback 内同步 `self._high_score`，§3.4/§4.6 合并权威实现，UT SC-1/SC-2 一致；
- [ ] P1-1：`_init_pygame` 捕获 `(StorageError, OSError)`；可另向 platform-storage 开 issue（mkdir 失败包 StorageError）；
- [ ] P1-2：ESC 与 Q 在 GAME_OVER 态语义分离，UT B-1/B-4 补区分断言；
- [ ] P1-3：fixture 注入顺序修正（`_init_pygame` 已注入则跳过创建）；
- [ ] P2-1~P2-7 随修订消化。

> 本轮 FAIL 不涉及架构与依赖契约（均已实核通过），修订聚焦设计文档内部一致性与 3 处接口错配，预计下轮可 PASS。
