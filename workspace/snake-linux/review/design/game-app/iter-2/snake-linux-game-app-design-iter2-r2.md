# SE 评审意见：game-app 迭代 2 功能模块设计（设计-iter2-r2）

> 评审人：SE · 2026-08-14
> 评审对象：`snake-linux/design/game-app/设计-iter2-r2.md`（MDE r2 修订版）
> 评审基线：架构 `snake-linux/arch/v2.0.0/架构设计.md` + `功能模块分工表.md`；依赖契约实核 `code/game-core/iter-2/`、`code/gui-renderer/iter-3/`、`code/platform-storage/iter-2/`（均 it_passed）；代码基线 `code/game-app/iter-1/`（it_passed）；本轮评审对象为 r1 FAIL 意见（`snake-linux-game-app-design-iter2-r1.md`）的修订版

## 结论：PASS

r1 的 **2×P0 + 3×P1 + 7×P2 已全部给出全文一致修订**：P0-1（PAUSED 屏态同步断链）以方案 A 单点落地（dispatch 内三处 toggle 后显式切屏、`_tick` 死代码分支删除、INV-10/11 重写、UT P-1/P-2/P-3/P-8 配套改写）；P0-2（INV-13 回调断链）以 §4.6 单点权威实现（回调直接写 `self._high_score` 实例字段、§3.4/§4.6 合并）；P1-1（mkdir 裸 OSError）双类型捕获；P1-2（ESC/Q 键位语义分离）独立 `ESCAPE` action + GAME_OVER 屏态覆盖 + UT B-1/B-4 区分断言；P1-3（fixture 注入失效）`_init_pygame` 加 `if None` 守卫。

**依赖契约逐条实核通过**（对照锁定代码，非仅文档）：`GameState` 全关键字构造含 `score_callback`、`toggle_pause()` RUN↔PAUSED / OVER 抛 InvalidStateError / PAUSED→RUN 清 pending（INV-8）、`step()` 非 RUN 抛 InvalidStateError（**据此确认 _tick 死代码分支删除正确**）、`set_score_callback` 返回新 GameState、`Snapshot.tick_ms = speed_curve`；`HighScoreStore(path=None)` / `load()` 损坏返 0 / `save()` 仅升分落盘抛 StorageError / `reset()`；`Renderer((W,H), *, skin, vsync, cell_size, grid_cols, grid_rows, enable_high_dpi)` / `render(snap, hud, *, interp=None)` / `HudData` 5 字段。**架构遵循与迭代边界核对通过**（依赖单向、零配置无网络无音效、不写系统目录、难度 UI 不重复、不建 iter-2 目录决策合理、iter-3/4 增量仅预告）。

**可落地性**：设计整体可作为 FO TDD 依据——UT 矩阵（iter-1 42 条沿用 + G2 系列 ~40 条）与 7 阶段 TDD 步骤框架自洽，方案 A 的 PAUSED 状态机语义闭环。**但存在 5×P1（测试基建/文档表述级，不改变实现方案）**：其中 2 项（P1-A 迭代 1 UT 回归未识别、P1-C fixture 缺导入必崩）直接导致"FO 照文落地会红一批测试"，FO 落地时**必须**按修订要求修正 conftest；其余为表述残留。P1 不阻塞 PASS，MDE 修订时应一并修（或 FO 落地时按本意见修正）。

---

## 一、P1（不阻塞 PASS 判定，但 MDE 修订 / FO 落地时必须处理）

### P1-A：`app` fixture 语义变更 + `_pause_hint_shown` 字段删除 → iter-1 既有 UT 必红，r2 未识别回归

**位置**：§6.2（`app` fixture）、§1.3（删除 `_pause_hint_shown`）、§6.4（"iter-1 沿用 42 条"）。

**实核**：iter-1 conftest 的 `app` fixture 语义是**"构造 App：不调 `_init_pygame`；`_renderer is None`"**（有意轻量化）。r2 §6.2 将 `app` fixture 改写为 `a = App(); a._init_pygame(); a._storage = fake_storage; ...`——直接破坏 iter-1 依赖该轻量语义的测试：

- `test_app_init.py::test_renderer_is_none_at_init`（断言 `app._renderer is None`）→ 必红；
- `test_app_init.py::test_clock_is_none_until_init`（断言 `app.clock is None`）→ 必红；
- `test_app_init.py::test_pause_hint_shown_is_false`（断言 `app._pause_hint_shown is False`）→ iter-2 删除该字段 → **AttributeError 必红**。

r2 §6.4 声称"iter-1 沿用（42 条）"但未列出上述任何一条的删除/修改。

**修法**：保留 iter-1 `app` fixture 的轻量语义（不调 `_init_pygame`）；需要渲染/存储基建的测试沿用 iter-1 既有模式（`app_with_mock_renderer` / `app_in_playing` 已存在）；明确列出删除 `test_pause_hint_shown_is_false`、以及 `_tick`/`_new_game`/`_dispatch_playing` 中 `_pause_hint_shown` 全部引用的清理。

### P1-B：P1-3 修复不彻底——fixture 在 `_init_pygame()` **之后**注入 fake_storage，真实 `create_storage()` 仍被执行（UT 触碰真实用户目录）

**位置**：§6.2（全部 5 个 fixture 的注入顺序）、§4.7（`if self._storage is None:` 守卫）。

**问题**：r1 P1-3 的核心批评是"UT 实际构造真实 HighScoreStore 并读写 `~/.local/share/SnakeLinuxGUI/highscore.json`（创建真实目录、受本机既有最高分文件影响 → 不确定 + 污染开发机）"。r2 选择了"`_init_pygame` 加 `if None` 守卫" **与** "fixture 在 `_init_pygame()` 之后注入 fake"两个修法叠加——但二者组合错误：fixture 调 `_init_pygame()` 时 `_storage` 仍是 None → **`create_storage()` 真实执行**（mkdir 真实目录 + `_load_uncached()` 读真实文件，损坏时还会 `replace` 备份写操作）→ 之后 `a._storage = fake_storage` 只是覆盖引用，真实副作用已发生。`app` / `app_in_playing` / `app_in_paused` / `app_in_game_over` / `app_with_storage` 全部如此。S-2（`App()._init_pygame()` 断言 `_storage is not None`）与 `app_with_storage` 更是必然走真实构造。

**修法**（与 §4.7 的 `if None` 守卫配套的正确顺序）：**在 `_init_pygame()` 之前注入 fake**（`a._storage = fake_storage` 先、`a._init_pygame()` 后）→ 守卫跳过 create_storage → 零真实 IO；`app_with_storage` 与 S-2 改为 monkeypatch `game_app.storage.create_storage` 返回 tmp_path 实例（或返回 fake），避免触碰真实目录。

### P1-C：§6.2 `app_in_game_over` fixture 缺 `GameStatus` 导入 → NameError，P-5 / B-1~B-4 五条 UT 照文落地必崩

**位置**：§6.2 `app_in_game_over`（`a.game_state = a.game_state._replace(status=GameStatus.OVER)`）。

**实核**：fixture 代码仅 `from game_core import Difficulty`；`GameStatus` 未导入（`game_app.__init__` 亦不 re-export GameStatus，实核 iter-1 `__init__.py` 无此项）→ `GameStatus.OVER` 处 **NameError**。依赖该 fixture 的 P-5 / B-1 / B-2 / B-3 / B-4 全部受影响。`_replace(status=...)` 本身可行（frozen dataclass，实核 `state.py` replace 路径接受全字段），仅缺导入。

**修法**：fixture 增加 `from game_core import GameStatus`（一行）。

### P1-D：P-8 断言"`inspect.getsource(app._tick)` 不含 `GameStatus.PAUSED`"与 §4.5 示例代码注释直接冲突——照文实现 P-8 必红

**位置**：§6.4 UT P-8、§4.5 `_tick` 注释。

**问题**：P-8 用**子串**断言 `inspect.getsource(app._tick)` 不含 `GameStatus.PAUSED`；但 §4.5 的 `_tick` 示例代码注释明确写入 `# P0-1 修订：原 elif new_status == GameStatus.PAUSED 分支已删除（死代码）：`——注释含该子串。FO 若按 §4.5 实现（保留说明注释），P-8 必红。这与 r1 的 P0 同类（UT 与实现描述直接冲突），但因仅影响 P-8 一条且易修，定 P1。

**修法**：P-8 改**语句级**断言（AST 解析 `_tick` 源码，断言不存在 `elif ... GameStatus.PAUSED` 分支语句），或 §4.5 注释改写作"原 PAUSED 检测分支（不可达死代码）已删除"（避免全名子串）。

### P1-E：§6.7 TDD 步骤 7 + §4.10 注意点 3 残留旧方案 B 表述——与方案 A 权威实现直接矛盾，FO 按 TDD 步骤会 reintroduce 死代码

**位置**：§6.7 步骤 7（"修改 `_tick` 检测 PAUSED 自动转屏"）、§4.10 注意点 3（"G2-1 PAUSED 态由 `_tick` 检测 `game_state.status == PAUSED` 后转 `screen=PAUSED`"）。

**问题**：两处均为 r1 P0-1 所指的"自动转屏"（方案 B）语义残留，与方案 A 权威实现（§4.4 dispatch 内单点切屏、§4.5 `_tick` 不检测 PAUSED）直接矛盾。§6.7 是 FO 的落地步骤指引——照做会 reintroduce 死代码分支并破坏 INV-11 单点同步；§4.10 注意点 3 同样误导。

**修法**：步骤 7 改为"修改 `_dispatch_playing` TOGGLE_PAUSE 分支 + 新增 `_dispatch_paused` + 修改 `_run_loop` PAUSED 跳过 `_tick`（方案 A，`_tick` 不检测 PAUSED）"；§4.10 第 3 条同步改写（或删除）。另步骤 9 "UNFUSH" 为 "UNFOCUS" 笔误（P2）。

---

## 二、P2（文档/UT 级，FO 落地时注意，不阻塞）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P2-1 | §5.6 错误矩阵 | "HighScoreStore mkdir 失败"行只写 `StorageError → 包 AppError`，漏 OSError（§4.7 已捕获 `(StorageError, OSError)`；§5.5 已写双类型） | 表格同步补 OSError |
| P2-2 | §5.5 鲁棒性表 | "Q/ESC 任意态：`_map_event` 统一映射 `QUIT`"为 r1 前旧语义——r2 已改 ESC 独立 `ESCAPE` action（P1-2） | 改"Q → QUIT 直通；ESC → ESCAPE（GAME_OVER 覆盖为 BACK_TO_MENU）" |
| P2-3 | §3.7 `draw_pause_overlay` docstring | 第 2 步仍写"PAUSED 大字（body_font 字号放大到 32）"、第 1 步硬编码 `(0,0,0,128)`——与 §4.8 修订（统一 22px、色值走 `PAUSE_OVERLAY_COLOR` 常量）矛盾（r1 P2-6 只改了 §4.8，§3.7 未同步） | §3.7 docstring 与 §4.8 对齐 |
| P2-4 | §4.3 | 模块级常量 `_PAUSE_KEY`/`_RESTART_KEY`/`_QUIT_KEY`/`_ESCAPE_KEY`/`_RESET_HIGHSCORE_KEY`/`_BACK_TO_MENU_KEY` 定义后**未被 `_map_event` 引用**（函数内直接用 `_pygame_attr("K_p")` 等字符串）；`_GAME_OVER_RESERVED_ACTIONS` 定义后**未被 §4.4 `_drain_events` 引用**（直接 `if action == ESCAPE`）——均为死代码 | 删除未用常量，或统一引用（建议删，减少 FO 困惑） |
| P2-5 | §3.8 | `translate_storage_error(func_name)` 定义但全文无调用点（§4.4/§4.6/§4.7 均直接 `except StorageError as e: raise StorageUnavailableError(...)`），且实现体为 `pass` + "见 §4.7"注释（§4.7 无此函数） | 删除该函数，或改为真实被调用的工具函数 |
| P2-6 | §6.2 fake_pygame | 替换列表仅 app/menu/input 三模块，**漏 `fonts_mod`**（iter-1 conftest 有 `monkeypatch.setattr(fonts_mod, "pygame", fake)`）——FO 照抄会丢 fonts 替换 | 补 fonts 模块替换 |
| P2-7 | §6.2/§6.4 | r2 P2-1 修订声称"iter-1 conftest 只替换 game_app.app + game_app.menu"——**与 iter-1 实际不符**（实核：iter-1 conftest 已替换 input/fonts/gui_renderer.renderer）；且 B-1 等测试用 `Event(KEYDOWN, key=...)` 构造语法，而 iter-1 conftest 提供的是 `FakeEvent`/`make_keydown` 辅助类（r2 §6.2 未延续说明） | 修订描述改正；测试事件构造统一沿用 iter-1 `FakeEvent` 或明确 `pygame.event.Event` 的 mock 用法（MagicMock 的 `.type` 需显式赋值，否则 B-3 的 QUIT 判断失效） |
| P2-8 | §6.7 | 步骤 1 引用 `test_storage.py`——§4.1 文件树无此文件（storage 测试在 `test_app_iter2_storage.py`）；且步骤 1 与步骤 2 的 S-1/S-2 归属重复 | 统一文件名与用例归属 |
| P2-9 | §6.4 H-1~H-4 | 断言"spy `surface.blit` 调用含 '最高分：100' 文本"——fake font.render 返回 MagicMock，blit 参数无文本；需用 `font.render.call_args`（`call_args[0][0] == "最高分：100"`）断言 | 补断言实现方式 |
| P2-10 | §3.4 vs §4.4 | `_dispatch_playing` 仍双版本（§3.4 用 dict 映射 MOVE_* + `# type: ignore[union-attr]`；§4.4 用 if/elif 且无 type ignore 注释）——语义一致但风格不一致（r1 P2-5 只合并了 `_new_game`） | 标注 §3.4 为概览、§4.4 为权威，或统一风格 |
| P2-11 | §0.0 / §4.7 | r2 声称"同时记 platform-storage issue：`__init__` mkdir 失败应包 StorageError"——实核 `workspace/snake-linux/issues/` 为空，**issue 未实际开** | 补开 issue（或删去"已记"表述） |
| P2-12 | §4.4 `_dispatch_menu` | 注释"RESET_HIGHSCORE 理论上进不来（_drain_events 保留键透传）但 RESET_HIGHSCORE 显式处理"——语义矛盾（RESET_HIGHSCORE 在 `_MENU_RESERVED_ACTIONS` 内**会**透传进来，需显式处理） | 注释改为"MOVE_*/TOGGLE_PAUSE/RESTART 理论上进不来；RESET_HIGHSCORE 在保留键内会进来，已显式处理" |
| P2-13 | §6.4 P-4 | 断言描述"由 core iter-2 静默忽略保证"不准确——`_dispatch_paused` 对 MOVE_* **无分支直接忽略**（未调 core），core 静默忽略只兜底 `set_direction` 直调场景 | 改述为"app 层 `_dispatch_paused` 不处理 MOVE_*" |

---

## 三、通过项核验（契约实核 + 架构遵循 + 可落地性）

### r1 FAIL 意见逐条闭合核对（全部 ✅）

| r1 意见 | r2 状态 | 验证 |
|---------|---------|------|
| P0-1 PAUSED 屏态同步断链 | ✅ 方案 A 单点落地：§4.4 三处 toggle 后显式切屏、§4.5 死代码分支删除、INV-10/11 重写、UT P-1/P-2/P-3/P-8 配套 | 全文一致（除 P1-E 两处表述残留） |
| P0-2 INV-13 回调断链 | ✅ §4.6 单点权威实现，回调直接写 `self._high_score`；§3.4/§4.6 合并；SC-1/SC-2 一致 | 实核 core `_score_callback` 字段（state.py 第 116 行，带下划线）→ S-7 引用正确 |
| P1-1 mkdir 裸 OSError | ✅ §4.7 捕获 `(StorageError, OSError)` 包 AppError；§5.5 同步 | 实核 highscore.py 第 53 行 `mkdir` 裸 OSError 成立；§5.6 表格漏 OSError → P2-1 |
| P1-2 ESC/Q 键位语义 | ✅ ESCAPE 独立 action、GAME_OVER 屏态覆盖、Q 直通 QUIT、UT B-1/B-4 区分 | §4.3/§4.4/§6.4 一致 |
| P1-3 fixture 注入失效 | ⚠️ 部分：`if None` 守卫已加，但注入顺序错误 → P1-B | 见 P1-B |
| P2-1~P2-7 | ✅ 全部消化（P2-6 仅 §4.8 代码块、§3.7 docstring 残留 → P2-3；P2-7 断言风格 → P2-10） | — |

### 依赖契约逐条实核（对照锁定代码）

| 设计引用 | 实核结果 |
|----------|----------|
| `GameState(width=, height=, difficulty=, rng=, initial_direction=, score_callback=)` 全关键字 | ✅ iter-2 `state.py`：allowed 集合完全一致；`score_callback` → 字段 `_score_callback`（repr=False, compare=False） |
| `toggle_pause()`：RUN↔PAUSED、OVER 抛 InvalidStateError、PAUSED→RUN 清 pending（INV-8） | ✅ 逐行一致 |
| `set_score_callback(cb)` 返回新 GameState | ✅ 存在（iter-2 app 用构造参数注册，语义等价） |
| `step()` 仅 RUN 可调，PAUSED/OVER 抛 InvalidStateError | ✅ **确认 _tick 死代码分支删除正确** |
| `set_direction` PAUSED 静默忽略、OVER 抛 InvalidStateError | ✅ |
| `snapshot().tick_ms = speed_curve(score, difficulty)`；tick_ms 下限 ≥50 | ✅ params.py；_tick while 必终止（R3-8 保持） |
| `HighScoreStore(path=None)` / `load()` 损坏返 0 / `save()` 仅升分落盘抛 StorageError / `reset()` | ✅（除 P1-1 已由 app 侧双捕获兜住；issue 未开 → P2-11） |
| `Renderer((W,H), *, skin=None, vsync=True, cell_size, grid_cols, grid_rows, enable_high_dpi=True)` | ✅ iter-3 renderer.py 签名一致；iter-2 仅构造 + init/shutdown/render 的边界正确 |
| `render(snap, hud, *, interp=None)`；未 init 抛 RenderError | ✅ |
| `HudData` 5 字段（score/high_score/length/difficulty_label/status_label） | ✅ iter-3 types.py |
| `DEFAULT_SKIN` / `SKIN_REGISTRY` / `RenderError` / `SkinNotFoundError` 导出 | ✅ |

### 架构遵循（对照 arch/v2.0.0）

- ✅ 依赖方向单向（app → core/renderer/storage），不侵入依赖模块内部（仅公开 API + `pygame.display.get_surface()`，R3-2 保持）；
- ✅ 零配置 / 无网络 / 无音效 / 不写系统目录（highscore 走 `get_user_data_dir()`，NFR-07）；
- ✅ Python 3.8 兼容（frozen dataclass + `__post_init__` 均为 3.7+ 特性）；
- ✅ 迭代边界与分工表一致：难度选择 UI 不重复（分工表备注 ✓）；iter-3/4 增量仅预告不实现（§附录 A）；
- ✅ AppConfig 最小窗口 512×472 与 renderer 最小可玩尺寸精确一致；G2-R-N1 与 iter-1 `config.py` 已有 `__post_init__` 行为一致（实核确认，仅文档/UT 写法统一）；
- ✅ 退出码 0/1/2 语义与 iter-1 一致；R3-15 shutdown 兜底保持；
- ✅ 新增文件组织决策（不建 iter-2 目录、`storage.py` 包装、`test_app_iter2_*.py`）合理；PyInstaller collect 补 platform_storage 正确；
- ✅ 状态机扩展（PAUSED 态 + UNFOCUS 内部信号 + GAME_OVER BACK_TO_MENU）与架构"界面流程(开始/难度/暂停/结束/重开/退出)"对齐；G2-4 失焦暂停为架构未明说但需求 FR-12 合理推导，不越界。

### 可落地性（FO TDD 依据）

- ✅ UT 矩阵规模与组织完整（iter-1 42 条 + G2-1 8 条 + G2-2/3 13 条 + G2-4 6 条 + G2-5 4 条 + G2-6 4 条 + G2-7 5 条 + G2-R-N1 5 条 ≈ 87 条）；conftest 桩、断言规范、7 阶段 TDD 步骤框架自洽；
- ✅ 方案 A 的 PAUSED 状态机、score_callback 闭包（P0-2 修订后直接写实例字段）、失焦检测跨平台兜底（headless 抛异常 → True）设计自洽；
- ❌ **但 P1-A/P1-C 使 iter-1 回归 + 新 fixture 必崩，P1-B 使 UT 触碰真实用户目录**——FO 落地时须按本意见修正 conftest（顺序 + 导入 + 保留轻量 fixture），再进入 TDD 主流程。

---

## 四、修订要求（MDE 下次提交 / FO 落地前自查）

- [ ] P1-A：`app` fixture 恢复轻量语义（不调 `_init_pygame`）；明确 `_pause_hint_shown` 相关 iter-1 UT 与代码引用的删除清单；
- [ ] P1-B：fixture 注入顺序改为 `_init_pygame()` **之前**（配合 §4.7 `if None` 守卫）；`app_with_storage` / S-2 monkeypatch `create_storage` 走 tmp_path；
- [ ] P1-C：`app_in_game_over` fixture 补 `from game_core import GameStatus`；
- [ ] P1-D：P-8 改语句级断言（AST）或 §4.5 注释避免全名子串；
- [ ] P1-E：§6.7 步骤 7 / §4.10 注意点 3 改方案 A 表述；步骤 9 UNFUSH→UNFOCUS；
- [ ] P2-1~P2-13 随修订消化（§5.6 补 OSError、§5.5 改 ESC 语义、§3.7 docstring 对齐、删死代码常量/函数、补 fonts 替换、统一测试文件引用与断言方式、补开 platform-storage issue）。

> 本轮 PASS 判定依据：r1 的 P0 已清零，无实现方案与 UT 直接矛盾的必红代码；P1 均集中在 conftest/测试基建与文档表述层（不改变实现方案本身），FO 按本意见修正后即可开展 TDD。架构与依赖契约维持 r1 的实核通过结论。
