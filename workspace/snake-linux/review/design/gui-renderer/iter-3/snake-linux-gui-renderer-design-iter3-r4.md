# 功能模块设计评审意见：gui-renderer（snake-linux v2.0.0 迭代 3）r4

> SE 评审（第四轮）· 依据：模块设计 `snake-linux/design/gui-renderer/设计-r4.md`（r4 修订版）+ 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）+ 迭代 1 已落地代码（实核 `code/gui-renderer/iter-1/gui_renderer/*.py` 与 `tests/*.py`，共 53 条用例）+ game-core 迭代 1 落地代码（实核 `state.py`/`types.py`/`params.py`）+ platform-storage 落地代码（实核 `highscore.py`）
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：PASS**
- 一句话理由：r3 的 6 条意见（P1×1 / P2×2 / P3×3）在 r4 **全部修订到位且质量高**（P1-1 三方案同时落实，实核 getattr 防御单独即可保证 fake 无 SCALED 时不崩，三方案冗余但安全；P2-1 删 hud_shadow 死字段并诚实化"同色描边"声称；P2-2 Rect 三处口径统一；P3×3 全部对齐）；**架构符合性 11/11 全绿**；**与迭代 1 落地代码向后兼容实核全绿**（53 条既有用例的断言方式逐一核对——font.render==5 / Status 颜色 / 蛇身 y 坐标过滤 / 食物 width 过滤 / fps 采样 / init 幂等 / 未 init 无 AssertionError 断言，r4 方案零破坏）；可落地性整体高（fixture 模板 / 桩规范 / 断言规范 / TDD 七步齐全），剩余 **P2×2 + P3×5 均为顺手修订级**，不阻塞 FO 开工，故 PASS。

---

## 1. r3 评审意见修订复核（逐条）

| r3 意见 | 修订位置（r4） | 复核结果 |
|---------|----------|----------|
| **P1-1** fake_pygame 缺 SCALED → 全套 UT 在 init() 崩溃 | §4.7（方案③ `flags \|= getattr(pygame, "SCALED", 0)` 防御）、§7.3（方案② renderer fixture 显式 `enable_high_dpi=False` + 新增 `renderer_high_dpi` fixture）、§7.4（方案① fake_pygame 必须提供 `SCALED = 0x40000000` 常量）、§7.5/§7.6/§5.5/§9/§10/§7.7 同步 | ✅ **三方案同时落实，冗余但安全**。实核迭代 1 conftest：`FakePygameModule` 无 SCALED 属性（r3 判断属实）；方案③ getattr 防御**单独**即可保证 fake 无 SCALED 时 `flags |= 0` 不崩——既有 renderer fixture `Renderer((512, 472))` 即便不改也能跑；方案②进一步让默认 fixture 完全避开 SCALED 路径；方案①支撑 hidpi 专项用例断言 flags 含 SCALED 位（§4.7 已注明此依赖） |
| **P2-1** HUD"阴影"实为同色重影 + hud_shadow 死字段 | §0.1/§1.1/§1.2/§3.1/§3.3/§4.2/§4.3/§4.4/§5.5/§7.5/§9/§10 | ✅ **方案 (a) 诚实化**：hud_shadow 字段删除彻底（实核 §1.2 代码块、§4.3 两个皮肤字面量、§4.2 _validate_skin 均无残留）；"阴影"改述为"同色描边/文字加粗"（§0.1 重写清晰）；**实核迭代 1 无 blit 次数断言**（test_renderer_render.py 仅断言 font.render==5、Status 颜色、draw.rect 按 y/width 过滤）→ 10 次 blit 不破坏任何既有用例 |
| **P2-2** Rect 消费点三处自相矛盾 | §1.4（删消费点表 + 4 条具体证据）、§4.4（"不绘制背景框"注释）、§9（红线改"Rect 无新增消费点"） | ✅ 三处口径统一为"迭代 3 无新增消费点，仅保留类型定义"。小瑕疵：§11 历史追溯表 P2-2 行仍写"Rect 仅保留 HUD 背景框 1 个真实消费点"（r2→r3 的历史记录，§12 已纠正），建议加注"r3 状态，r4 已改"（P3-5） |
| **P3-1** 用例编号不连续 + 合计计数不符 | §7.6 编号重排 + 合计改 50 | ✅ 编号连续 1-N；2+5+7+2+12+5+8+3+6 = **50** 核对无误 |
| **P3-2** §0.3 主循环驱动表述与架构不符 | §0.3 改述"主循环已在 game-app 迭代 1 落地"+ 注明架构出处 | ✅ 与架构迭代计划一致 |
| **P3-3** §0.1 阴影说明表述混乱 | §0.1 重写（同一 surface blit 至偏移 + 主版；本质同色描边；不二次 render） | ✅ 表述清晰，与 §4.4 docstring / §1.2 三处口径一致 |

**复核结论：r3 全部 6 条意见修订质量合格，无回退，无新 P1。**

---

## 2. 架构符合性核对（本轮独立复核）

| 架构契约 | 设计落点 | 结果 |
|---|---|---|
| 模块类型：中间件，依赖 game-core | §0 | ✅ |
| 迭代排期：gui-renderer 迭代 1, 3；迭代 3 = 平滑动画/皮肤/缩放/高分屏 | §0.2 出口 5 项（FR-07/09/10/NFR-04 + SkinRegistry + SkinNotFoundError）；与分工表"迭代 3 视觉增强：gui-renderer（平滑动画+皮肤系统+窗口缩放）"一致 | ✅ |
| `Renderer(window_size, *, skin=None, vsync=True, cell_size, grid_cols, grid_rows, enable_high_dpi=True)` | §3.1 签名一致（尾部追加 enable_high_dpi=True，keyword-only） | ✅ |
| `render(snapshot, hud, *, interp=None)` 向后兼容 | §1.5/§3.1（None=瞬移 alpha=1.0）；实核迭代 1 `render(snapshot, hud)` 签名不变 | ✅ |
| `set_skin(name)` 对局不中断 / `handle_resize(w,h)` 等比缩放 / `skin_names()` / `current_skin_name` | §3.1/§4.5/§4.6 | ✅ |
| 皮肤注册表 ≥3 套（经典/深色/色盲友好，不以颜色为唯一区分） | §1.3 SKIN_REGISTRY 3 套 + 三重视觉冗余（cell_gap 间隙 + food_pattern 纹理 + snake_pattern 纹理 + 形状） | ✅ |
| NFR-04 高分屏清晰（pygame.SCALED） | §4.7 enable_high_dpi 默认 True + getattr 防御 | ✅ |
| 数据流：core snapshot → renderer 只读；renderer 不持有游戏状态 | §1.5/§2.2 interp 由 game-app 维护；实核迭代 1 renderer 无状态写回 | ✅ |
| 无网络（NFR-06）/无音效（R-04）/无第三方依赖（除 pygame） | §5.4/§5.7 | ✅ |
| 迭代 1 遗留项：SkinNotFoundError 占位实装 | §2.4 实装 `__init__(name, available)` + self.name/self.available | ✅ |

**架构符合性：10/10 全绿。**

---

## 3. 与迭代 1 落地代码向后兼容实核（逐项核对 53 条既有用例）

| 迭代 1 落地事实（实核） | r4 设计 | 结果 |
|---|---|---|
| `Skin` 9 字段 frozen，无默认值 | +3 字段全默认值（cell_gap=1/food_pattern="solid"/snake_pattern="solid"）→ DEFAULT_SKIN 字面量构造合法；r4 §4.3 新增皮肤同步使用 | ✅ |
| `render(snapshot, hud)` | `*, interp=None` 可选参；interp=None 时 prev_body=None → 不插值，行为一致 | ✅ |
| `init()` flags=0 局部变量（幂等 `if self._initialized: return`） | `self._flags` 属性 + `flags \|= getattr(pygame, "SCALED", 0)`；幂等保留 | ✅ |
| `_draw_hud` 5 段 font.render + 5 次 blit，y 坐标 12/44，x 坐标 16/200/400/300 | 单次 render/段 + 2 次 blit/段（偏移 (+1,+1) + 主版）→ font.render 仍 5 次，blit 10 次 | ✅（实核迭代 1 **无 blit 次数断言**，10 次不破坏） |
| `test_render_hud_calls_font_render_5_times`（==5） | font.render 仍 5 次 | ✅ 零修改通过 |
| `test_render_hud_status_over_uses_accent_color`（含 "Status" 的 render 调用 color == hud_accent） | OVER 时 Status 单次 render 用 hud_accent，无阴影版干扰 | ✅ 零修改通过 |
| `test_render_food_calls_draw_rect_twice`（outline width=1 == 1；fill width=0 == 蛇3+食物1 = 4） | classic food_pattern="solid" → 食物 fill 1 + outline 1；蛇身 3 次 width=0 | ✅ 零修改通过 |
| `test_render_snake_len_3/5`（按 y=PLAYFIELD_Y+CELL_SIZE 过滤蛇身 rect） | interp=None 时坐标不变；`cell_draw = cell_size - cell_gap`（classic=1 一致） | ✅ 零修改通过 |
| `test_render_rejects_empty/none_snapshot`（RenderError） | 保留 | ✅ |
| `test_init_is_idempotent` / shutdown 幂等 / 上下文管理 | 保留幂等 | ✅ |
| 未 init 直接 render：迭代 1 为 `assert screen is not None`（AssertionError） | r4 改 `raise RenderError`（P3-2） | ✅ 实核迭代 1 **无任何断言 AssertionError 的用例**，异常类型变更不破坏既有用例 |
| `_grid_to_pixel(cell: Tuple[int,int])` 公式 `PLAYFIELD_X + x*cell_size` | 注解放宽 `Tuple[float,float]`；插值路径 int(round()) 截断；非插值路径 int 运算不变 | ✅ |
| `_min_window_size` 公式（实核：20*24+32=512 / 96+15*24+16=472） | MIN_PLAYABLE_W = 20*8+32=192 / MIN_PLAYABLE_H = 96+15*8+16=232（CELL_SIZE_MIN=8 公式） | ✅ 公式一致（r4 用 CELL_SIZE_MIN 替换 CELL_SIZE 作下限） |
| fake_pygame 桩（FakePygameModule 无 SCALED；set_mode 不记录 flags；draw.rect 记录 (color,rect,width)；FakeSurface.blit 记录 blit_calls） | r4 要求增量：SCALED 常量 + set_mode 记录 + blit 断言依据（FakeSurface.blit_calls 已具备） | ✅ 增量方向正确，无结构性变更 |
| game-core `GameState` 仅接受 keyword 参数（实核 state.py L109-123） | §7.3 fixture / §8 伪代码全用 keyword 写法 | ✅ |
| game-core `step()` 返回新 GameState（dataclasses.replace 不可变风格，实核 L166+） | §2.2/§8 伪代码 `state = state.step()` | ✅ |
| MEDIUM.base_tick_ms = 160（实核 params.py） | §7.3 prev_snapshot fixture 断言 snap.tick_ms == 160 | ✅ |
| platform-storage `HighScoreStore(path: Optional[Path] = None)`（实核 highscore.py L45） | §8 伪代码 `HighScoreStore()` 无参 | ✅ |

**向后兼容实核：全部 ✅，迭代 1 的 53 条既有用例零修改通过（r4 声称"39 条"为计数误差，见 P3-2）。**

---

## 4. 可落地性（FO 可否据其 TDD）

- **整体高**：§7.3 conftest 模板（含 game-core 实测签名注释、prev_snapshot 显式断言初始值）、§7.4 桩规范（SCALED 常量/记录要求）、§7.5 断言规范（插值帧/食物形态/HUD 同色描边/缩放/高分屏）、§7.6 50 条用例编号连续、§7.7 TDD 七步、§7.8 运行命令——FO 照抄可开工；
- **❌ P2-1 直接误导 FO**：§7.6 test_interpolation 用例 3 期望值笔误——`_interpolate_position((0,0), (10,0), 0.5) == (5.0, 5.0)`，按 §4.4 公式 `py = 0 + 0.5*(0-0) = 0.0`，**应为 `(5.0, 0.0)`**。FO 照抄会得到错误断言：实现正确（返回 (5.0,0.0)）后测试仍红，FO 若优先信用例可能反向改坏实现；
- **❌ P2-2 断言口径矛盾**：食物 draw.rect 次数三处不一致——§7.4 桩规范"checkered 4 次"、§7.5 断言表"5 次（4 子格 + 1 outline）"、§7.6 用例 7"5 次"；且均未明确"按颜色过滤掉蛇身 rect"（同一帧蛇身还有 3 次 rect，总调用数 ≠ 断言数），FO 照抄 §7.5 按总数断言会红；
- 其余（插值时序推演表、缩放几何、皮肤注册表、异常路径、game-app 对接伪代码、资源评估）均可落地，质量高。

---

## 5. 问题清单

### P2（应修订，不阻塞主体开发但直接影响 FO 照抄）

**P2-1 §7.6 test_interpolation 用例 3 期望值错误（(5.0, 5.0) → 应为 (5.0, 0.0)）**
- `_interpolate_position((0,0), (10,0), 0.5)`：px = 0 + 0.5×(10-0) = 5.0；py = 0 + 0.5×(0-0) = **0.0**。文档写 `(5.0, 5.0)` 错误（疑似与用例 4 `(5,5)→(5,5)` 的结果混淆）；
- **修改点**：§7.6 test_interpolation 用例 3 期望值改 `(5.0, 0.0)`。FO 在 TDD 中若遇此用例红，按 §4.4 公式判定为文档笔误，勿反向修改实现。

**P2-2 食物 draw.rect 断言次数三处矛盾 + 未明确过滤方式**
- §7.4："断言食物 checkered **4 次** rect 调用" vs §7.5/§7.6："checkered → **5 次**（4 子格 + 1 outline）"；
- 且断言未说明过滤规则：同一帧蛇身（蛇长 3）另有 3 次 rect，`draw.rect` 总调用数 = 蛇 3 + 食物 5 = 8，按"总次数"断言必红。迭代 1 既有断言模式是"按 y 坐标过滤蛇身"（test_render_snake_len_3/5）与"按 width 过滤 outline"（test_render_food_calls_draw_rect_twice）；
- **修改点**：统一为"**按颜色过滤**（food / food_outline / background 色）后食物相关 draw.rect 次数：solid 2 / ringed 3 / checkered 5"，§7.4/§7.5/§7.6 三处同步；或在 §7.5 断言表注明"排除蛇身 rect 的过滤方式"。

### P3（建议，顺手修订）

- **P3-1** §3.1 render docstring 第 1 条残留"→ assert self._screen is not None（迭代 1 既有）"，与 §4.4 实现（raise RenderError）、§5.5、§7.5、§7.6 用例 12 不一致——修订后应统一为"未 init → raise RenderError"（docstring 是 FO 照抄入口，两处口径不一易写错）。
- **P3-2** §7.6 末尾"迭代 1 已有 39 条"计数不符：实核迭代 1 落地用例 = **53 条**（test_types 9 + test_constants 5 + test_renderer_init 15 + test_renderer_lifecycle 6 + test_renderer_render 10 + test_renderer_fps 8；conftest 中 1 处为 docstring 示例非用例）。本迭代后应共 ≥103 条而非 ≥89 条。不影响 FO 正确性，建议修正。
- **P3-3** §7.1 增量 fixtures 列表写 `enable_high_dpi_disabled`，§7.3 模板实际定义 `renderer_high_dpi`——名称不一致；且 §7.3 renderer fixture 是**修改既有 fixture**（(512,472) → (640,480) + enable_high_dpi=False），§7.1 表述为"增量"易让 FO 误以为新增同名 fixture 覆盖。建议 §7.1 明确"修改既有 renderer fixture + 新增 renderer_high_dpi"。
- **P3-4** §4.4 `SHADOW_OFFSET` 注释"name kept for iter-1 fixture compatibility"不实：实核迭代 1 renderer.py **无 SHADOW_OFFSET 变量**（迭代 1 HUD 无阴影）。变量名可保留（减少 diff），注释应诚实（如"沿用 r3 变量名"）。
- **P3-5** §11 修订追溯表（相对 r2）P2-2 行残留"Rect 仅保留 HUD 背景框 1 个真实消费点"，与 r4 最终口径（无新增消费点）相反（§12 已纠正）——历史追溯表建议加注"r3 状态，r4 已统一为无新增消费点"。

---

## 6. 结论与后续

- **PASS**（r3 全部 6 条意见修订合格；架构符合性 10/10 全绿；与迭代 1 落地 53 条用例向后兼容实核全绿；无 P1 阻塞。剩余 P2×2 为文档笔误/口径问题、P3×5 为表述与计数瑕疵，均不阻塞 FO 开工）。
- 后续要求：
  1. **P2-1**：§7.6 test_interpolation 用例 3 期望值改 `(5.0, 0.0)`（FO 若已开工，TDD 中按 §4.4 公式自行修正，勿反向改实现）；
  2. **P2-2**：§7.4/§7.5/§7.6 三处食物 rect 断言统一为"按颜色过滤后 solid 2 / ringed 3 / checkered 5"；
  3. P3-1~5 顺手修订；
  4. MDE 修订可不必重新评审（P2 不阻塞）；若修订，本轮意见复核表随附即可。
