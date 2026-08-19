# 功能模块设计评审意见：gui-renderer（snake-linux v2.0.0 迭代 3）r1

> SE 评审 · 依据：模块设计 `snake-linux/design/gui-renderer/设计-r3.md` + 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）+ 迭代 1 已落地代码 `snake-linux/code/gui-renderer/iter-1/`（it_passed）+ game-core 已落地代码 `snake-linux/code/game-core/iter-1/`（接口实核）
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：架构遵循性整体成立（模块类型/依赖方向/迭代边界/向后兼容契约设计优秀），但存在 **2 项 P1 阻塞问题**——①插值 prev 缓存时序错误（§2.2/§8 按此实现 FR-07 平滑动画完全失效）；②§7.3 conftest 与 §8 用 `GameState(20, 15, Difficulty.MEDIUM)` 位置参数调用，而 game-core 实测**仅接受 keyword 参数**（`TypeError: GameState only accepts keyword arguments`），FO 照抄 UT 即刻崩溃。另有 2 项 P2、5 项 P3，详见 §3。

---

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点 | 结果 |
|---|---|---|
| 模块类型：中间件，依赖 game-core | §0 中间件/依赖 game-core（已 it_passed）/被 game-app 依赖 | ✅ |
| 迭代排期：迭代 1, 3（分工表） | §0 迭代 3 = 平滑动画/皮肤/缩放/高分屏；迭代 3 不做 game-app 主循环/难度 UI/打包 | ✅ |
| `Renderer(skin_name)` / `render(snapshot)` | 架构接口清单仍为旧签名（**P2-2**，见 §3）；设计沿用迭代 1 已落地 `Renderer(window_size, skin=None)` / `render(snapshot, hud)` 并加 `interp` 可选参 | ⚠️ |
| `set_skin(name)` 游戏中对局不中断 | §3.1 set_skin 只换 self._skin 引用，下一帧生效；不中断对局 | ✅ |
| `handle_resize(w, h)` 等比缩放 | §4.6 重算 cell_size（下限 8/上限 48）+ 字体比例缩放 + set_mode；保持 grid_cols/rows 不变 | ✅（异常口径矛盾见 P2-1） |
| `fps_metric()` 帧率统计（P95 帧时间） | 字段不变；迭代 3 验证插值后 P95 仍反映真实帧时间 | ✅ |
| 皮肤注册表 ≥3 套（经典/深色/色盲友好） | §1.3 SKIN_REGISTRY 3 套 + set_skin 查表；色盲方案三重视觉冗余（颜色+纹理+形状）对齐 FR-10「不以颜色为唯一区分手段」 | ✅ |
| 数据流：core snapshot → renderer 只读 | §1.5/§2.2 renderer 不缓存游戏状态，interp 由 game-app 维护——职责边界正确 | ✅（但 game-app 侧缓存时序错误，P1-1） |
| 无网络（NFR-06）/无音效（R-04） | §5.4/§5.7 不 import socket/urllib/http/requests；无音频 | ✅ |
| NFR-04 高分屏清晰 | §4.7 enable_high_dpi=True 默认启用 pygame.SCALED（pygame 2.x） | ✅ |
| 语法兼容 Python 3.8 | dataclass/typing 均 3.8 支持（架构「不用 dataclass」条款为迭代 1 评审 P2-3 遗留，未修订——P2-2） | ⚠️ |
| 不引入第三方依赖（除 pygame） | §0 明确 | ✅ |

### 1.1 与 game-core 实际契约核对（代码实核，非纸面对纸面）

| 设计引用 | game-core 落地实测 | 结果 |
|---|---|---|
| `GameState(20, 15, Difficulty.MEDIUM)`（§7.3/§8） | **仅接受 keyword**：`GameState(width=20, height=15, difficulty=Difficulty.MEDIUM)`；位置参数抛 `TypeError` | ❌ **P1-2** |
| `state.step()` 返回新实例 | `def step(self) -> "GameState"` 返回新状态；§8 `state = state.step()` 用法正确 | ✅ |
| `snapshot.snake_body` / `.food` / `.score` / `.length` / `.status` / `.difficulty` / `.tick_ms` | 实测全部字段存在（snake_body Tuple[Point]，Point 有 .x/.y；status=GameStatus.RUN；tick_ms=160@MEDIUM） | ✅ |
| `snapshot.status.name` / `difficulty.name` | "RUN"/"PAUSED"/"OVER"；"easy"/"medium"/"hard"——HUD 显示用 name 一致 | ✅ |
| `snap.tick_ms // 16` 节拍帧数估算（§8） | tick_ms=160 → 10 帧 @60FPS，可用 | ✅（插值时序见 P1-1） |

### 1.2 与迭代 1 已落地代码的向后兼容核对（实核 gui_renderer/*.py）

| 迭代 1 契约 | 迭代 3 增量 | 结果 |
|---|---|---|
| `Skin` 9 字段 frozen dataclass | 新增 4 字段全带默认值（hud_shadow/cell_gap/food_pattern/snake_pattern）→ 迭代 1 DEFAULT_SKIN 字面量构造仍合法 | ✅ |
| `render(snapshot, hud)` | 加 `*, interp=None` 可选参，None 时 alpha=1.0 瞬移，行为与迭代 1 一致 | ✅ |
| `Renderer.__init__(window_size, *, skin=None, vsync=True, cell_size, grid_cols, grid_rows)` | 尾部追加 `enable_high_dpi=True` keyword 参数，旧调用零修改 | ✅ |
| `init()` 不调 pygame.init / 顶层 import pygame 可 monkeypatch | 迭代 3 保持（§4.7/§5.1） | ✅ |
| `_min_window_size`（512×472 最小可玩） | §4.6 handle_resize 复用 PLAYFIELD_X/Y 公式 | ✅ |
| `_validate_skin` RGB ∈ [0,255] | 增量校验 hud_shadow/cell_gap/food_pattern/snake_pattern | ✅ |
| Rect 迭代 1 无消费点（迭代 1 评审 P3-B） | §1.4 补齐 2 个消费点（HUD 背景框 + 插值裁剪 Rect） | ✅ |
| skin 属性 / cell_size / grid_cols / grid_rows 只读属性 | 新增 current_skin_name 属性 | ✅ |

---

## 2. 可落地性（FO 可否据其 TDD）

- **UT 框架完备**：增量 46 条用例（types 3 + constants 5 + skin_registry 6 + init 2 + render 8 + skin 6 + resize 8 + hidpi 3 + interpolation 5 = 46）✓；覆盖率 ≥90%（render ≥95%）✓；fake_pygame + monkeypatch headless 方案沿用迭代 1 ✓；TDD 六步顺序合理 ✓；
- **向后兼容设计是亮点**：Skin 新字段默认值 + render interp 可选参 + __init__ 尾部新增参数，三处增量均不破坏迭代 1 已通过 code/IT 契约，FO 可在 iter-1 目录原地增量（§4.1 目录决策合理）；
- **❌ P1-2 直接阻塞 FO 开工**：§7.3 `prev_snapshot` fixture 模板与 §8 对接契约均使用位置参数构造 GameState，game-core 实测抛 TypeError；FO 照抄 §7.3 则 pytest 全红且误导（会怀疑自己代码而非设计）；
- **❌ P1-1 使 FR-07 出口不达标**：§8 主循环伪代码在 `state.step()` **之后**缓存 prev_snap，导致 interp.prev == 当前 snapshot，插值恒等于同位置渲染——按此实现蛇仍整格瞬移，FR-07「无整格跳变」验收必然失败；
- **P2-1 口径矛盾**：§7.5 断言 4 要求 handle_resize(100,100) 抛 RenderError，但 §4.6 代码只有类型校验（正整数），无最小尺寸校验分支；且 (200,200) 断言 3 期望降级到 8 不抛——同属「放不下最小网格」的两个尺寸行为不同，FO 无法确定正确口径。

---

## 3. 问题清单

### P1（阻塞，必须修订后重新评审）

**P1-1 插值 prev 缓存时序错误 → FR-07 平滑动画失效（§2.2 含糊 + §8 明确错误）**
- §8 伪代码：
  ```python
  if ticks_in_step >= state.snapshot().tick_ms // 16:
      state = state.step()            # snapshot 已变为新位置 B
      prev_snap = state.snapshot()    # ❌ 缓存的是 step 之后的新位置 B
      prev_body = tuple(...)          # prev == current
      ...
  snap = state.snapshot()             # B
  alpha = ticks_in_step / (snap.tick_ms // 16)   # 0 → 0.1 → ...
  interp = InterpolationState(alpha=alpha, prev_snake_body=prev_body, ...)
  render(snap, hud, interp=interp)
  ```
- **推演**（tick_ms=160，10 帧/节拍）：帧 1~10 蛇画在 A（alpha 从 0→0.9，prev/current 均为 A，位置不变）；帧 11 节拍到达 step 后 prev 被更新为 B，alpha=0 → 画在 B——**蛇从 A 直接瞬移到 B，节拍间隔内完全静止**。FR-07 验收「无整格跳变/观感连续」必然失败。
- **修改点**：prev 必须在 step **之前**缓存（prev = 上一节拍位置）：
  ```python
  if ticks_in_step >= state.snapshot().tick_ms // 16:
      prev_snap = state.snapshot()    # ✅ step 前：旧位置 A
      state = state.step()            # snapshot 变新位置 B
      prev_body = tuple((p.x, p.y) for p in prev_snap.snake_body)
      prev_food = (prev_snap.food.x, prev_snap.food.y)
      ticks_in_step = 0
  ```
  同步修订 §2.2 数据流图的「state_prev = snapshot_now 缓存」时序描述（当前文字先 step 后缓存，与正确语义矛盾），并在 §1.5 InterpolationState 字段注释把「上一帧」明确为「**上一节拍**（step 前）快照」。模块内 render 实现（§4.4）与 UT（§7）不受影响，仅对接契约与数据流描述需修订。

**P1-2 §7.3 conftest 与 §8 的 GameState 构造签名与 game-core 实测不符**
- game-core 实测：`GameState.__init__` 仅接受 keyword（`GameState only accepts keyword arguments`），正确写法 `GameState(width=20, height=15, difficulty=Difficulty.MEDIUM)`；
- 设计 §7.3 `prev_snapshot` fixture、§8 对接契约均写 `GameState(20, 15, Difficulty.MEDIUM)` → 照抄即 TypeError，UT 全崩；
- **修改点**：两处改为 keyword 写法（§7.3 注释「推进 1 步得到 base 快照」也与代码不符——fixture 只构造未 step，注释与实际行为不一致，一并修正）。建议补一条「GameState 构造后 snapshot 蛇身长度/初始方向」的显式断言，避免 fixture 语义含糊。

### P2（应修订，不阻塞 FO 主体开发但影响口径/文档一致性）

**P2-1 handle_resize 最小尺寸校验口径自相矛盾（§4.6 代码 vs §5.5/§7.5 断言）**
- §4.6 步骤 1 声称「校验 w/h >= 最小可玩尺寸」，但代码示例只有类型校验（isinstance + 正整数），**无最小尺寸校验分支**——按代码，100×100 也会被 clamp 到 8 而不抛异常；
- §5.5 鲁棒性表「handle_resize 尺寸 < 最小可玩尺寸 → 抛 RenderError（是）」、§7.5 断言 4「handle_resize(100,100) → assertRaises(RenderError)」——文档与代码示例冲突；
- 且断言 3「(200,200) → cell_size == 8」与断言 4「(100,100) → 抛异常」口径不一：按「最小可玩 = 能容纳 CELL_SIZE_MIN 网格」（192×232，迭代 1 _min_window_size 公式），200<232 同样放不下，为何降级不抛？FR-09 验收要求「小于最小尺寸时给出提示而非画面错乱」——**提示 = 抛 RenderError 由 game-app 呈现**，与「静默降级到 8」是两种不同行为，设计必须二选一并统一代码/鲁棒性表/断言三处。
- **修改点**：建议采用「w/h 任一方小于最小可玩尺寸（含 CELL_SIZE_MIN 网格 + 边距）→ 抛 RenderError」口径，§4.6 代码补校验分支，§7.5 断言 3 改为 (200,200) 也抛异常（或重新定义降级阈值并同步三处）。

**P2-2 架构同步声明不实：设计称「P2-1/P2-2/P2-3 已修订」，架构文档实测未修订**
- 设计 r3 头部声明「严格对齐架构（P2-1/P2-2/P2-3 已修订）」；实核 `arch/v2.0.0/架构设计.md`（git HEAD 4eb2247 无未提交改动）：
  - 接口清单仍为 `Renderer(skin_name)`：`render(snapshot)`（迭代 1 评审 P2-1 要求同步为 `Renderer(window_size, skin=None)` / `render(snapshot, hud)`）——**未修订**；
  - 代码风格仍写「不用 dataclass/海象/3.9+ 特性」（P2-3 要求改为「dataclass 可用；禁 3.9+ 新语法」）——**未修订**；且 game-core/gui-renderer 迭代 1 已落地代码全量 dataclass 并通过评审，该条款事实已失效；
- 设计 r3 的接口/数据结构与迭代 1 落地代码一致（这是正确方向），但「已修订」声明与架构文档事实不符，会造成下游（game-app 设计、code 检视）以旧架构为基线的二次争议；
- **修改点**：SE 侧落实迭代 1 评审遗留的架构同步（接口清单 + dataclass 条款），或在设计 r3 头部把声明改为「接口对齐迭代 1 落地契约（架构文档同步修订中）」，避免虚假引用。

### P3（建议，顺手修订）

**P3-1 兼容矩阵表与常量定义不一致（colorblind hud_shadow）**
- §1.2 兼容矩阵表 colorblind_friendly 行 hud_shadow 记 (0,0,0)；§4.3 COLORBLIND_FRIENDLY_SKIN 实际定义为 Color(255,255,255)（浅色背景用白阴影，正确）。表应改 (255,255,255)。

**P3-2 `_grid_to_pixel` 类型注解与插值浮点入参不符**
- 迭代 1 `_grid_to_pixel(cell: Tuple[int,int])` 注解 int；§4.4 插值分支传入 `_interpolate_position` 返回的 `Tuple[float,float]`——注解需放宽为 `Tuple[float, float]`（或说明插值路径传浮点），并确认 `x * cell_size` 浮点运算后 `int(round())` 截断语义（设计已说明，注解补齐即可）。

**P3-3 §1.2 Skin 字段代码块与 §4.2 的默认值写法不一致**
- §1.2 写 `hud_shadow: Color = Color(0, 0, 0)`（直接默认值），§4.2 写 `field(default_factory=lambda: Color(0, 0, 0))`——两处应统一（frozen dataclass 中 Color 不可变、直接默认值也合法，但规范应一致；建议统一用 default_factory）。

**P3-4 §3.1 render docstring「5 行文本」与迭代 1 实际 2 行布局不符**
- 迭代 1 `_draw_hud` 为 2 行 5 段文本（行 1：score/high/length；行 2：difficulty/status）；设计 §3.1/§4.4 写「绘制 HUD（5 行文本 + 阴影）」——应为「2 行 5 段」；hud_shadow 阴影的绘制偏移量（如 +1px 偏移 blit）未定义，建议给出具体偏移值供 UT 断言。

**P3-5 §7.3 fixture 注释与代码不符 + 依赖 game-core 行为未显式化**
- `prev_snapshot` fixture 注释「推进 1 步得到 base 快照」但代码未 step（与 P1-2 同源）；且 fixture 依赖 game-core 初始布局（蛇长 3、初始方向、食物位置），应显式断言或在注释中给出确定性初始值，否则插值用例 3/4 的坐标断言基线不明确。

---

## 4. 结论与后续

- **FAIL**（P1 × 2 阻塞；架构符合性 11 项中 9 项全绿 + 2 项偏离均与 P2-2 架构同步遗留相关；可落地性受 P1-2 直接阻塞）。
- 后续要求：
  1. **P1-1**：MDE 修订 §2.2/§8 插值 prev 缓存时序（step 前缓存），§1.5 字段注释改「上一节拍」；
  2. **P1-2**：MDE 修订 §7.3/§8 GameState 构造为 keyword 写法（实核签名），修正 fixture 注释；
  3. **P2-1**：MDE 统一 handle_resize 最小尺寸校验口径（建议抛 RenderError）并同步代码/鲁棒性表/断言；
  4. **P2-2**：SE 落实架构文档同步（接口清单 + dataclass 条款），修订设计 r3 头部声明；
  5. P3-1~5 顺手修订；
  6. 修订后重新提交评审（release_module design FAIL 后 MDE 修订 → 重新 DONE → 本评审复核 PASS）。
