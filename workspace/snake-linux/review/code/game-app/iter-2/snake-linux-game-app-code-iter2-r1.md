# 模块代码检视意见：game-app（snake-linux v2.0.0 迭代 2）r1

> **检视者**：MDE
> **检视视角**：模块内实现（数据结构 / 实现细节 / 可测试性 / 鲁棒性）
> **检视依据**：模块设计 `snake-linux/design/game-app/设计-iter2-r2.md`（r2，SE r1 评审 FAIL 已全消化）
> **检视对象**：`snake-linux/code/game-app/iter-1/`（iter-2 增量落在 iter-1 既有代码目录，未新建 iter-2 子目录，与设计 §0/§4.9 决策一致）
> **检视时间**：2026-08-14
> **结论**：**PASS**

---

## 1. 检视清单核对

| # | 检视项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 实现与模块设计一致（数据结构/接口/流程） | ✅ PASS | 见 §2 |
| 2 | 实现细节质量（边界/异常/资源释放） | ✅ PASS | 见 §3 |
| 3 | 可测试性（UT 可写可跑） | ✅ PASS | 见 §4 |
| 4 | 代码风格符合架构约定 | ✅ PASS | 见 §5 |

---

## 2. 检视项 1：实现与设计一致性

### 2.1 数据结构对齐

| 设计项 | 设计位置 | 实现位置 | 对齐状态 |
|--------|---------|---------|---------|
| `App` 字段（screen/_difficulty/game_state/_renderer/_storage/_high_score/_tick_accumulator_ms/_running/_menu_title_font/_menu_body_font/clock） | §3.4 描述 | `app.py:103-117` | ✅ 字段名严格一致；`_storage` 类型注解为 `Optional[Any]`（隐式 duck typing 让 UT 用 fake_storage；类型提示可改进但不影响功能） |
| `AppScreen` 枚举 4 态（MENU/PLAYING/PAUSED/GAME_OVER） | §3.2 | `screens.py:11-16` | ✅ 完全一致 |
| `InputAction` 枚举 13 项（含 G2-3/4/7 新增 RESET_HIGHSCORE/BACK_TO_MENU/UNFOCUS/ESCAPE） | §3.3 | `input.py:35-52` | ✅ 完全一致（含 P1-2 ESCAPE 独立 action） |
| `AppConfig` frozen + `__post_init__` 校验 | §3.1（G2-R-N1） | `config.py:13-33` | ✅ `fps_cap <= 0` 与 `window_w < min_window_w` 两条校验与设计一致 |
| `AppError`/子类（新增 `StorageUnavailableError`） | §3.6 | `errors.py:11-28` | ✅ `StorageUnavailableError(AppError)` 与设计一致 |
| `_DIFFICULTY_LABEL` / `_STATUS_LABEL`（三态含 PAUSED） | §4.10 第 9 条 | `app.py:76-86` | ✅ RUN/PAUSED/OVER 三态全覆盖 |

### 2.2 屏态同步方案 A（P0-1 修订）落地

设计 §0.0 修订摘要要求"屏态同步唯一发生在 _dispatch_* 内"，§1.4 INV-11 单点方案 A。代码核对：

| 屏态迁移 | 设计位置 | 实现位置 | 对齐 |
|---------|---------|---------|------|
| PLAYING→PAUSED（TOGGLE_PAUSE） | §4.4 + §1.4 INV-11 | `app.py:281-283` | ✅ `toggle_pause()` 后**显式** `self.screen = AppScreen.PAUSED` |
| PLAYING→PAUSED（UNFOCUS） | §4.4 | `app.py:284-287` | ✅ 同上（含 `status == RUN` 守卫，与 §4.4 一致） |
| PAUSED→PLAYING（TOGGLE_PAUSE） | §4.4 | `app.py:294-296` | ✅ `toggle_pause()` 后**显式** `self.screen = AppScreen.PLAYING` |
| _new_game→PLAYING | §4.6 | `app.py:339-340` | ✅ `screen=PLAYING` |
| _tick OVER→GAME_OVER | §4.5 | `app.py:361-362` | ✅ OVER 自动转 |
| GAME_OVER→MENU（BACK_TO_MENU） | §4.4 | `app.py:304-306` | ✅ 含 INV-7 重置 `game_state=None` |

**P0-1 死代码已剔除**：`_tick` 内不再有 `elif new_status == PAUSED` 分支（grep 验证：`app.py:360-363` 仅 OVER 分支），与 §4.5 设计一致。§6.4 UT P-8（AST 源码检查）尚未在测试代码中找到——属于 **轻量 nits**（设计 §6.4 P-8 要求 inspect.getsource 检测），见 §6.2。

### 2.3 G2-2 storage / G2-3 score_callback（P0-2 修订）落地

| 设计项 | 设计位置 | 实现位置 | 对齐 |
|--------|---------|---------|------|
| `create_storage()` 包装 HighScoreStore | §3.8 / §4.7 | `storage.py:18-31` | ✅ 签名 `create_storage(path: Optional[Path] = None) -> HighScoreStore`，异常注释清晰 |
| `_init_pygame` 内构造 storage 并捕获双类型 | §4.7 P1-1 | `app.py:167-172` | ✅ `if self._storage is None:` 守卫（P1-3）；`except (StorageError, OSError)` 双类型捕获，与设计完全一致 |
| `_new_game` 注册 score_callback 闭包 | §4.6 权威实现 | `app.py:322-331` | ✅ 闭包持有 `_storage` 局部引用；`try/except StorageError → StorageUnavailableError` 与设计一致 |
| **P0-2 INV-13 直接写实例字段** | §4.6 / §1.4 INV-13 | `app.py:328` | ✅ `self._high_score = max(self._high_score, score)` 直接写实例字段，未走 nonlocal / 外部容器，与 P0-2 修订完全一致 |
| `_dispatch_menu(RESET_HIGHSCORE)` 包 StorageUnavailableError | §4.4 | `app.py:253-259` | ✅ 转换链正确；`_storage is not None` 守卫与设计一致 |

### 2.4 G2-4 失焦自动暂停 / G2-5 遮罩 / G2-6 high_score / G2-7 BACK_TO_MENU（P1-2 修订）落地

| 设计项 | 设计位置 | 实现位置 | 对齐 |
|--------|---------|---------|------|
| `_drain_events` 仅 PLAYING 态检测失焦 | §4.4 G2-4 | `app.py:225-231` | ✅ `if self.screen == AppScreen.PLAYING:` 守卫；`try/except Exception → focused=True` 兜底与设计一致 |
| GAME_OVER 态 ESC → BACK_TO_MENU（仅 ESC；Q 仍 QUIT 直通） | §4.4 G2-7 / P1-2 | `app.py:218-220` | ✅ 仅 `action == InputAction.ESCAPE` 被覆盖；Q 与 BACKSPACE 不被覆盖 |
| `_drain_events` MENU 屏态兜底（None/非保留键 → START） | §4.4 R3-1 | `app.py:213-217` | ✅ ESCAPE 不在 `_MENU_RESERVED_ACTIONS` 中（input.py:62-63 注释 + 列表），与 P1-2 一致 |
| `_render` PAUSED 路径（先 renderer.render 后 draw_pause_overlay） | §4.8 / §3.4 | `app.py:399-406` | ✅ 顺序正确，先画底图再叠加遮罩；`assert _renderer and game_state is not None` 守卫合理 |
| `draw_pause_overlay` 形参与步骤 | §3.7 / §4.8 P2-6 | `menu.py:123-156` | ✅ 无废代码；常量走 `_constants.py:22-25`；使用 `pygame.SRCALPHA` 走 fake_pygame fixture 提供的属性 |
| `draw_menu` / `draw_game_over` 加 high_score 形参 | §3.7 / §4.8 G2-6 | `menu.py:28, 88` | ✅ 默认值 0 保持向后兼容 |
| ESCAPE / Backspace → BACK_TO_MENU 映射 | §4.3 G2-7 | `input.py:95-98` | ✅ ESCAPE 与 BACKSPACE 分别按 P1-2 / P2-1 走不同路径 |

### 2.5 CJK 字体回退链 / 字段命名约束（R3 沿用）

| 项 | 设计 | 实现 | 对齐 |
|----|------|------|------|
| 字段命名统一 `_difficulty` / `_high_score` | §4.10 R3-4 | `app.py:106, 110` | ✅ |
| `App.__init__` 仅置字段 | §3.4 / §4.10 R3-10 | `app.py:92-117` | ✅ 不构造 Renderer / HighScoreStore（构造在 `_init_pygame`） |
| 删除 `_pause_hint_shown` | §1.4 INV-8 | `app.py:113` 注释 | ✅ 字段已删除，注释确认 |
| `_render` 用 `pygame.display.get_surface()` | §4.10 R3-2 | `app.py:384, 404, 408` | ✅ 全部走公开 API，未读 `_screen` 私有 |

---

## 3. 检视项 2：实现细节质量

### 3.1 边界与异常处理

- **退出码分流**（§5.6）：`app.py:130` GraphicsUnavailableError → 退出码 2；`app.py:198-200` 主循环 AppError（含 StorageUnavailableError） → 退出码 1；`main()` (app.py:422-431) ConfigError + AppError 双捕获 → 退出码 1。完全覆盖 §5.6 错误处理矩阵。
- **finally 兜底**（§4.2）：`app.py:138-144` `_init_pygame` 异常路径亦尝试 `Renderer.shutdown()` 一次，与 R3-15 一致。
- **循环内重读 tick_ms**（§4.5 R3-8）：`app.py:354-359` while 内每次取 `tick_ms = self.game_state.snapshot().tick_ms`，避免 tick_ms 在循环内停滞，加速曲线下仍可正确推进。
- **PAUSED 态 _tick 不进入**（§1.4 INV-10）：主循环 `app.py:194` `if self.screen == AppScreen.PLAYING:` 守卫；`_tick` 内 `assert self.screen == AppScreen.PLAYING`（line 350）双重防护。
- **INV-7 重置**（§1.4）：`app.py:306` `self.game_state = None` 在 BACK_TO_MENU 分支执行。
- **StorageError → StorageUnavailableError 转译**（§5.6）：三处一致——`app.py:171` (`_init_pygame` mkdir/OSError)、`app.py:258` (`_dispatch_menu` RESET_HIGHSCORE)、`app.py:331` (`score_callback` save 失败)。
- **fake_storage fixture 与 _init_pygame 顺序**（§6.2 P1-3）：`conftest.py:117-123` 先调 `_init_pygame()` 再赋值 `self._storage = fake_storage`，配合 `app.py:167` 的 `if self._storage is None:` 守卫——避免 create_storage 覆盖 fixture 注入值。**与设计一致**。
- **`_pygame_attr` 延迟读取**（P2-1 修订）：`input.py:26-32` 通过 `sys.modules['pygame'].__dict__` 而非 `import pygame`，让 monkeypatch 后读到 fake 值。`conftest.py:75-89` 同步替换 `game_app.{app,menu,input,fonts}` 四个模块的 pygame 引用，与设计一致。

### 3.2 资源释放

- `Renderer` 构造失败 → `GraphicsUnavailableError` → 退出码 2 + finally shutdown 兜底（`app.py:130-144`）。
- `HighScoreStore` 失败 → `AppError` 包装，但不持有文件句柄（构造失败无资源），无泄漏风险。
- `pygame.time.Clock()` 构造在 `_init_pygame` 末尾，失败路径早已 raise。无时钟泄漏。
- CJK 字体由 fake_pygame 接管，无 SDL 资源在 UT 中保留。

### 3.3 锁与并发

设计 §4.10 第 12 条：HighScoreStore 单进程 RLock 保护（platform-storage 职责）；game-app 不直接接触文件锁。无并发问题。

---

## 4. 检视项 3：可测试性

### 4.1 UT 执行结果

```
$ cd snake-linux/code/game-app/iter-1 && python3 -m pytest tests/test_game_app/ -x --no-header -q
181 passed, 1 warning in 1.64s
```

**181/181 全绿**（iter-1 沿用 42 条 + G2-1~G2-7 新增 ~ 19 条 SC/U/O/H/B/C 系列 + iter2_storage_err 等）。

### 4.2 覆盖率（branch 模式）

```
game_app/__init__.py        82%   (__init__ 兜底 try/except 未执行，无关键代码)
game_app/__main__.py         0%   (PyInstaller 入口，仅 sys.exit(main())，无法 UT)
game_app/_constants.py     100%
game_app/app.py             91%   (215 stmts / 15 missed / 76 branches / 7 partial)
game_app/config.py         100%
game_app/errors.py         100%
game_app/fonts.py          100%
game_app/input.py          100%
game_app/menu.py           100%
game_app/screens.py        100%
game_app/storage.py        100%
TOTAL                       91%   (398 stmts / 22 missed / 122 branches / 7 partial)
```

**与 §6.5 覆盖率目标对比**：
- 行覆盖 ≥ 90%：app.py 93% / menu.py 100% / fonts.py 100% / storage.py 100% — **达标**
- 分支覆盖 ≥ 85%：TOTAL 91% — **达标**

### 4.3 UT 覆盖完整性

- **iter-1 沿用 42 条**：全数保留（test_app_init/exit/game_over/hud/menu/playing/render_dispatch/tick/input_map/drain_events/config/fonts），未破坏。
- **G2-1 PAUSED**（P-1~P-8）：含 P-5/P-6/P-8 三处 P1/P2 修订用例，全数落地（test_app_iter2_pause.py）。
- **G2-2 storage**（S-1~S-10）：含 S-3 mkdir 失败 / S-8 score_callback save 失败用例，全数落地（test_app_iter2_storage.py）。
- **G2-4 UNFOCUS**（U-1~U-6）：含跨平台兜底用例（U-5 异常兜底 / U-6 聚焦恢复不自动继续），全数落地（test_app_iter2_unfocus.py）。
- **G2-5 遮罩**（O-1~O-4）：全数落地（test_app_iter2_overlay.py）。
- **G2-6 high_score 展示**（H-1~H-4）：全数落地。
- **G2-7 BACK_TO_MENU**（B-1~B-5）：含 P1-2 ESC/Q 分离所有用例，全数落地（test_app_game_over.py）。
- **G2-R-N1 ConfigError**（C-1~C-5）：UT-4/5/33 已修订，全数落地（test_config.py）。

### 4.4 fixture 健壮性

`conftest.py` 提供 8 个 fixture（`fake_pygame` / `fake_storage` / `app_uninitialized` / `app` / `app_with_mock_renderer` / `app_in_playing` / `app_in_paused` / `app_in_game_over` / `app_with_storage`），覆盖 4 屏态（MENU/PLAYING/PAUSED/GAME_OVER）。`FakeEvent` + `make_keydown` / `make_quit_event` 辅助函数便于构造 pygame 事件实例。

---

## 5. 检视项 4：代码风格

- **类型注解**：完整覆盖（dataclass、Enum、Optional[...]），与架构一致。
- **docstring**：所有公开/内部方法有 docstring（App 主类、_init_pygame / _run_loop / _drain_events / _dispatch* / _new_game / _tick / _build_hud / _render / main / draw_* / create_storage）。注释中明确引用设计章节（如 "P0-1" / "G2-1" / "INV-11"），便于回溯设计意图。
- **命名约定**：`_private` 字段名与 `_MENU_RESERVED_ACTIONS` / `_GAME_OVER_RESERVED_ACTIONS` 模块内 frozenset 一致；常量走 `_constants.py` 而非散落 magic number。
- **跨迭代复用**：iter-1 既有代码大量保留并增量修改（app.py / input.py / menu.py / screens.py / config.py / _init__.py / errors.py / storage.py 新增），未触发既有 iter-1 it_passed 行为。`modules.json:88-117` 显示 iter-1 status=it_passed 无变化——兼容。
- **错误处理风格**：`try/except` 分层捕获（`RenderError`/`pygame.error` / `StorageError`/`OSError` / `AppError`），异常包装明示 `from e` 保留链路。

---

## 6. 轻量观察（不阻塞 PASS，建议 MTO / 维护期关注）

### 6.1 [nits] §6.4 P-8 AST 源码检查未单独实施

设计 §6.4 P-8 要求"额外断言 `_tick` 内不存在 `elif new_status == PAUSED` 分支（AST/源码检查：`inspect.getsource(app._tick)` 不含 `GameStatus.PAUSED`）"。当前 test_app_iter2_pause.py 已通过 grep/代码阅读自然实现了功能（P-1~P-7 + 当前 _tick 实现），但 P-8 的机器化断言尚未见专门实现（防止后续误把 `elif` 加回）。

**严重性**：低——当前 _tick 实现明确无误（grep `app.py` 无 `new_status == PAUSED`），但建议在 `test_app_iter2_pause.py` 补 P-8：

```python
import inspect
def test_P8_no_paused_branch_in_tick():
    src = inspect.getsource(app_in_playing._tick)
    assert "GameStatus.PAUSED" not in src
```

### 6.2 [nits] `_drain_events` 中 GAME_OVER 失焦不变 — 设计未明说但代码隐含

代码 `app.py:218-220` 先判断 GAME_OVER 屏态覆盖 ESC → BACK_TO_MENU；`app.py:225-231` 仅 PLAYING 态检测失焦 → GAME_OVER 态失焦不追加 UNFOCUS。UT U-4 覆盖此行为（`app_in_game_over + get_focused=False → 不含 UNFOCUS`），行为正确，但设计 §4.4 / §4.10 未明确写出"GAME_OVER 态失焦不变"，只通过 `_drain_events` 实现位置隐含。

**严重性**：低——行为合理且 UT 已覆盖；建议下轮设计修订时显式加一句"§4.10 第 11 条扩展：GAME_OVER 态失焦不自动暂停（避免无意义操作）"。

### 6.3 [nits] `menu.py:76-80` 多画了一行 "Q 退出"

设计 §4.8 `draw_menu` 示意只画 4 段（title / 难度 × 3 / high_score / hint），代码额外画了一段 "Q 退出" 单行（Y=440）。hint 文案内已包含 "Q 退出" 字样，新增这一行视觉冗余，但不影响正确性。

**严重性**：低——属于设计容许的功能扩展（视觉强化退出提示）。FO 若希望严格对齐设计，可删除 `menu.py:76-80` 段。

### 6.4 [nits] `_dispatch_paused(UNFOCUS)` 的 `pass` 行未直接覆盖

`app.py:298` 的 `elif action == InputAction.UNFOCUS: pass  # PAUSED 态再失焦不变（G2-4）` 是防御性兜底——但因 `_drain_events` 已在 PAUSED 态屏蔽 UNFOCUS 入口，正常路径永不到此行。

**严重性**：极低——属"防御性代码"层级（§4.10 实现注意点第 3 条强调鲁棒性兜底），分支覆盖率 91% 已合规；UT U-3 通过 `_drain_events` 屏态筛选间接验证行为正确性。建议补一个 `test_app_iter2_pause.py` 的 `def test_P9_dispatch_paused_unfocus_noop():` 直接调用 `_dispatch_paused(InputAction.UNFOCUS)` 断言不抛异常 + 屏态不变，以提升分支覆盖到接近 100%（nits）。

### 6.5 [nits] `App._storage` 类型注解为 `Optional[Any]`

`app.py:109` 注释为 duck typing（让 fake_storage MagicMock 可注入）。设计隐含 `Optional[HighScoreStore]`，但代码选 `Any` 避免 UT 时循环 import。

**严重性**：极低——类型注释优化空间，不影响运行行为。如需严格类型：可在 `TYPE_CHECKING` 分支用 `from platform_storage import HighScoreStore` 注解。

---

## 7. 总结

| 检视清单项 | 结论 |
|------------|------|
| §3.3 #1 实现与设计一致 | ✅ PASS |
| §3.3 #2 实现细节质量 | ✅ PASS（含兜底/异常/资源；5 处 §6 nits 不影响 PASS） |
| §3.3 #3 可测试性 | ✅ PASS（181/181 UT 全绿；行 93% / 分支 91% 均超 §6.5 目标） |
| §3.3 #4 代码风格 | ✅ PASS |

**最终结论**：**PASS**

- 设计实现一致性：P0 修订（P0-1 屏态同步方案 A / P0-2 INV-13 直接写实例字段 / P1-1 双类型捕获 / P1-2 ESC 独立 action / P1-3 fixture 注入顺序）单点落地；
- 边界与异常：5.6 错误处理矩阵全覆盖，finally 兜底，INV 不变量在代码中明确保证；
- 可测试性：181 UT 全绿，覆盖率超 §6.5 目标；
- 代码风格：跨迭代增量修改不破坏 iter-1 it_passed；命名/类型/注释/常量组织与架构一致。

模块 game-app（snake-linux v2.0.0 迭代 2）代码实现通过本轮 MDE 检视，可进入下一阶段（IT / 集成测试评审）。
