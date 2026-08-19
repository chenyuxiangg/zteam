# 功能模块设计评审意见：gui-renderer（snake-linux v2.0.0 迭代 3）r2

> SE 评审（第二轮）· 依据：模块设计 `snake-linux/design/gui-renderer/设计-r3.md`（r2 修订版）+ 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）+ 迭代 1 已落地代码 `snake-linux/code/gui-renderer/iter-1/`（实核 gui_renderer/*.py 与 tests/*.py）+ game-core 已落地代码
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：r1 的 P1×2/P2×2/P3×5 **全部修订到位**（插值时序正确性推演表、GameState keyword 构造、handle_resize 抛异常口径统一，质量高）；但本轮**实核迭代 1 已落地代码与 UT 断言**后发现 2 项新 P1 阻塞问题——①HUD 阴影设计使每段文本 `font.render` 两次（5→10 次调用），直接破坏迭代 1 既有 UT 两个断言（render 调用次数 ==5、Status 颜色断言命中阴影版），设计未声明修订既有用例，§0「向后兼容契约」承诺不成立；②§4.4/§2.3 可照抄代码引用迭代 1 **不存在的常量/属性**（`HUD_TOP_ROW_Y`/`HUD_GAP`/`self._line_height`，落地实际为 `HUD_FIRST_LINE_Y`/`HUD_SECOND_LINE_Y`/`HUD_LINE_HEIGHT`），FO 照抄即 NameError/AttributeError。

---

## 1. r1 评审意见修订复核（逐条）

| r1 意见 | 修订位置 | 复核结果 |
|---------|----------|----------|
| **P1-1** 插值 prev 缓存时序 | §1.5 字段注释改「上一节拍（step 前）」；§2.2 数据流图 step 前缓存 + 帧推演表（帧 1~21）；§8 伪代码 `prev_snap = state.snapshot()` 置于 `state.step()` 之前 | ✅ 推演核对无误：帧 11 缓存 A→step→B、alpha=0 画 A；帧 12~20 从 A 平滑到 B；FR-07「无整格跳变」成立 |
| **P1-2** GameState 位置参数 | §7.3 conftest、§8 均改 keyword 写法；fixture 注释修正（未 step）并新增显式断言（蛇长 3/RUN/MEDIUM/tick_ms=160） | ✅ 与 game-core 实测签名一致（`GameState only accepts keyword arguments`）；fixture 语义不再含糊 |
| **P2-1** handle_resize 口径矛盾 | §2.3/§4.6 代码补 `MIN_PLAYABLE_W/H` 校验抛 RenderError；§5.5 鲁棒性表、§7.5 断言 4、§7.6 用例 3 三处统一；§3.3 新增 MIN_PLAYABLE_W/H 常量 | ✅ 代码/鲁棒性表/断言三处一致，无静默降级残留；阈值公式与迭代 1 `_min_window_size`（192×232）吻合 |
| **P2-2** 架构同步声明不实 | 头部删除虚假「已修订」声明，改述「接口对齐迭代 1 落地契约（架构文档同步修订由 SE 在架构侧落实）」 | ✅ 设计侧声明修正到位；**架构文档实测仍未同步**（接口清单/dataclass 条款），见 §4 S1（SE 侧待办，本评审后落实） |
| **P3-1** 兼容矩阵 hud_shadow | §1.2 表 + §4.3 定义统一 (255,255,255) | ✅ |
| **P3-2** _grid_to_pixel 注解 | 放宽 `Tuple[float, float]` + 截断语义说明 | ✅ |
| **P3-3** 默认值写法 | §1.2/§4.2 统一 `field(default_factory=lambda: Color(...))` | ✅ |
| **P3-4** HUD 5 行→2 行 5 段 + 阴影偏移 | §3.1 docstring、§4.4 _draw_hud、§7.4 FakePygame blit 记录、§7.5/§7.6 断言 | ⚠️ 描述口径修正到位，**但阴影实现与迭代 1 既有 UT 冲突**（见 P1-1） |
| **P3-5** fixture 注释/断言 | §7.3 修正 + 显式断言 | ✅ |

**复核结论：r1 全部 9 条意见修订质量合格，无回退。**

---

## 2. 架构符合性核对（本轮独立复核）

| 架构契约 | 设计落点 | 结果 |
|---|---|---|
| 模块类型：中间件，依赖 game-core（已 it_passed） | §0 | ✅ |
| 迭代排期：gui-renderer 迭代 1, 3 | §0 迭代 3 = 平滑动画/皮肤/缩放/高分屏；不做 game-app 主循环/难度 UI/打包 | ✅ |
| 迭代 3 出口对齐架构 §迭代计划「验收 3（GUI 呈现）」 | §0 出口清单 5 项全对齐 FR-07/09/10/NFR-04 | ✅ |
| 数据流：core snapshot → renderer 只读 | §1.5/§2.2 renderer 不缓存游戏状态，interp 由 game-app 维护 | ✅ |
| `set_skin(name)` 对局不中断（FR-10） | §4.5 只换 self._skin 引用，下一帧生效 | ✅ |
| `handle_resize(w,h)` 等比缩放（FR-09） | §4.6 重算 cell_size + 字体比例 + set_mode；保持 grid_cols/rows 不变 | ✅ |
| NFR-04 高分屏清晰 | §4.7 enable_high_dpi=True 默认 pygame.SCALED | ✅ |
| 无网络（NFR-06）/无音效（R-04） | §5.4/§5.7 | ✅ |
| 不引入第三方依赖（除 pygame） | §0 | ✅ |

### 2.1 与迭代 1 落地代码向后兼容核对（本轮实核 gui_renderer/*.py + tests/*.py）

| 迭代 1 落地事实 | 迭代 3 设计 | 结果 |
|---|---|---|
| `Skin` 9 字段 frozen dataclass | 新增 4 字段全默认值 → DEFAULT_SKIN 字面量构造合法 | ✅ |
| `render(snapshot, hud)`（迭代 1 签名无 interp） | `*, interp=None` 可选参，None 时行为一致 | ✅ |
| `__init__(window_size, *, skin, vsync, cell_size, grid_cols, grid_rows)` | 尾部追加 `enable_high_dpi=True` | ✅ |
| `init()` flags=0（局部变量） | 增量 `self._flags` 属性 + SCALED 位；handle_resize 保留 flags | ✅（新属性不破坏） |
| `_grid_to_pixel(cell)` 公式 `PLAYFIELD_X + x*cell_size` | 注解放宽 float | ✅ |
| `_validate_skin` RGB 校验 | 增量校验 hud_shadow/cell_gap/food_pattern/snake_pattern | ✅ |
| `cell = self._cell_size - 1`（经典 -1 间隙） | `cell_draw = cell_size - skin.cell_gap`（classic=1 → 一致） | ✅ |
| HUD 常量：`HUD_FIRST_LINE_Y`/`HUD_SECOND_LINE_Y`/`HUD_LINE_HEIGHT`（无 HUD_TOP_ROW_Y/HUD_GAP） | §4.4 伪代码用 `HUD_TOP_ROW_Y`/`HUD_GAP`/`self._line_height` | ❌ **P1-2** |
| 迭代 1 `test_render_hud_calls_font_render_5_times`（render 调用 ==5）、`test_render_hud_status_over_uses_accent_color`（next() 取首个含 "Status" 调用断言 accent） | §4.4 阴影方案每段 render 2 次（阴影+主版）→ 5 段 = 10 次；首含 "Status" 调用变为阴影版（hud_shadow 色） | ❌ **P1-1** |
| `test_render_food_calls_draw_rect_twice`（classic：食物 2 次 rect） | classic food_pattern="solid" → 2 次，一致 | ✅ |
| `test_render_snake_len_3/5`（y 坐标过滤） | interp=None 时坐标不变 | ✅ |

---

## 3. 可落地性（FO 可否据其 TDD）

- **UT 框架增量完备**：46 条增量用例 + TDD 六步顺序 + fake_pygame headless 方案，整体质量高；§7.3 fixture 显式断言 game-core 初始行为，插值用例基线明确；
- **❌ P1-1 使「向后兼容」承诺不成立**：按 §4.4 实现 HUD 阴影后，迭代 1 既有 2 个用例必红；设计 §7.6 仅列增量用例、未声明修订既有用例，FO 无法判断「改实现还是改测试」——这比「照抄即崩」更隐蔽（实现符合设计，测试却失败）；
- **❌ P1-2 破坏「FO 照抄即可」承诺**：§4.4 _draw_hud 与 §2.3 可照抄代码含 3 个不存在的标识符，且若按设计新增这些常量，§4.3/§3.3 增量常量清单又未列入——FO 要么 NameError、要么改动契约清单；
- 其余（插值时序/缩放口径/皮肤注册表/异常路径）均可落地。

---

## 4. 问题清单

### P1（阻塞，必须修订后重新评审）

**P1-1 HUD 阴影方案破坏迭代 1 既有 UT 两个断言，设计未声明修订（§4.4 vs 迭代 1 tests/test_renderer_render.py）**
- 迭代 1 实核断言：
  - `test_render_hud_calls_font_render_5_times`：`assert len(font.render_calls) == 5`（5 段文本各 render 一次）；
  - `test_render_hud_status_over_uses_accent_color`：`next((c for c in font.render_calls if "Status" in c[0]))` 取**第一个**含 "Status" 的调用断言 `[2] == hud_accent`；
- 设计 §4.4 _draw_hud 阴影方案：每段**先 render 阴影版（hud_shadow 色）再 render 主版**——5 段 → `font.render` 共 10 次；且含 "Status" 的第一个调用变为阴影版（颜色 hud_shadow 而非 hud_accent）→ **两个用例必红**；
- 设计 §0 声称「不修改迭代 1 契约」「向后兼容」，§7.6 用例计数「39 → ≥85」隐含既有用例全通过——与实现效果矛盾；
- **修改点**：在 §7.6 显式声明修订迭代 1 两个用例（`test_render_hud_calls_font_render_5_times`：5→10 次并注明阴影版+主版各 5 次；`test_render_hud_status_over_uses_accent_color`：改为取**主版**调用——按颜色 != hud_shadow 过滤或取第二个含 "Status" 的调用），并在 §0 兼容性声明中注明「HUD 绘制行为变更（阴影增强）属本迭代预期变更，同步修订 2 个既有断言」；若坚持既有用例不动，则需改设计（如阴影用同一 surface 二次 blit 的替代方案并给出可行论证）。

**P1-2 §4.4/§2.3 可照抄代码引用迭代 1 不存在的常量/属性（§4.4 _draw_hud / §2.3 数据流 vs 迭代 1 constants.py/renderer.py 实核）**
- 设计 §4.4 _draw_hud 伪代码：`HUD_TOP_ROW_Y`、`HUD_TOP_ROW_Y + self._line_height`、`HUD_GAP`；§2.3 步骤 4 同源；
- 迭代 1 落地实际：constants.py 只有 `HUD_FIRST_LINE_Y=12` / `HUD_SECOND_LINE_Y=44` / `HUD_LINE_HEIGHT=28`，**无 HUD_TOP_ROW_Y、无 HUD_GAP**；renderer.py **无 `_line_height` 属性**（HUD 行坐标直接引用 HUD_FIRST_LINE_Y/HUD_SECOND_LINE_Y）；
- FO 照抄 §4.4 → NameError（HUD_TOP_ROW_Y/HUD_GAP）或 AttributeError（self._line_height）；
- **修改点**：_draw_hud 伪代码改用迭代 1 既有常量（行 1 y = `HUD_FIRST_LINE_Y`，行 2 y = `HUD_SECOND_LINE_Y`，段间距用既有坐标差或新增 `HUD_GAP` 常量）；若确需新增 HUD_GAP/HUD_TOP_ROW_Y，必须同步列入 §4.3 常量增量代码块与 §3.3 公开 API 清单（当前均未列），并说明与迭代 1 既有常量的关系。

### P2（应修订，不阻塞主体开发）

**P2-1 吃食节拍食物长距离插值滑行（§2.2/§4.4 食物插值分支）**
- FR-07 原文仅要求**蛇**「逐帧插值移动而非整格跳变」；设计对食物同样插值——吃食节拍 prev_food = 被吃位置、snapshot.food = 新随机位置（可相距 >10 格），alpha 0→0.9 间食物从被吃位置「滑行」到新位置，视觉语义错误（食物应消失于原位、出现于新位）；
- **修改点**：InterpolationState 增「食物插值开关」语义（如约定 prev_food=None 表示该节拍食物不插值、直接画新位置），由 game-app 在吃食节拍传 None；或 render 内按新旧食物距离 >1 格自动跳过插值；§7 增对应用例（吃食节拍食物无中间帧）。

**P2-2 InterpolatedCell 无消费点 + Rect 纸面消费点（§1.5/§1.4 vs §4.4/§4.6 实现）**
- `InterpolatedCell` 在 §1.5 定义、§3.3 导出、§7.6 有 UT，但 §4.4 render 流程与 §8 对接契约**均未构造/消费它**（插值直接用 `_interpolate_position` 内联）——死公共类型，重蹈迭代 1 评审 P3-B「Rect 无消费点」覆辙；
- §1.4 声称 Rect 补齐 2 个消费点（HUD 文本背景框、插值子区域裁剪），但 §4.4 _draw_hud（无背景框绘制）与 §4.6 handle_resize 代码示例**均未使用 Rect**——纸面消费点；
- **修改点**：二选一——(a) 删除 InterpolatedCell（保持公共 API 精简，删 §3.3/§7.6 对应条目）；(b) 在 §4.4 或 §8 给出真实消费点（如 §4.4 用 Rect 表达插值绘制矩形、_draw_hud 用 Rect 画 HUD 背景框）；Rect 消费点同样需给出真实代码或撤回声称。

### P3（建议，顺手修订）

**P3-1 SkinNotFoundError 构造签名未定义（§2.4 vs §3.1）**
- §2.4 声称「构造时记录：缺失的皮肤名 + 当前注册表 key 列表」，§3.1 抛法为单字符串 `SkinNotFoundError(f"皮肤 {name!r} 不在注册表 ...")`；迭代 1 errors.py 中该类为空占位类——结构化字段（name/available）无定义，FO 无法按设计实现「记录」语义；
- **修改点**：定义构造签名 `SkinNotFoundError(name: str, available: Tuple[str, ...])`（继承 RenderError，message 由基类拼装），§3.1 同步，§7.6 增断言 `e.name == "nope"`。

**P3-2 render 未 init 保护退化（§4.4 vs 迭代 1）**
- 迭代 1 `render` 内 `assert screen is not None`（未 init 时 AssertionError）；设计 §4.4 伪代码直接 `screen = self._screen` 解引用——未 init 时变为 AttributeError（None.fill），异常语义退化；
- **修改点**：保留迭代 1 的 assert 或改为抛 RenderError，并在 §5.5 鲁棒性表增一行。

### SE 侧待办（非设计 FAIL 项；本轮评审后由 SE 落实）

**S1 架构文档同步（r1 P2-2 遗留）**：`arch/v2.0.0/架构设计.md` 实核仍为旧契约——①接口清单 `Renderer(skin_name)` / `render(snapshot)` 未对齐迭代 1 落地（`Renderer(window_size, *, skin=None, ...)` / `render(snapshot, hud)` + 迭代 3 set_skin/handle_resize）；②代码风格仍写「不用 dataclass/海象/3.9+ 特性」，与 game-core/gui-renderer 迭代 1 全量 dataclass 已落地的事实冲突。SE 本轮落实修订（不改架构决策，仅对齐落地契约），避免下游 game-app 设计与 code 检视以失效条款为基线。

---

## 5. 结论与后续

- **FAIL**（r1 全部 9 条修订合格；新增 P1×2 阻塞：HUD 阴影破坏迭代 1 UT 兼容性、可照抄代码引用不存在常量；另有 P2×2、P3×2；S1 为 SE 侧落实项）。
- 后续要求：
  1. **P1-1**：MDE 声明并落实迭代 1 两个 HUD 用例的修订（render 次数 5→10、Status 断言取主版调用），或改阴影方案避免破坏既有断言；同步 §0 兼容性声明；
  2. **P1-2**：MDE 修订 §4.4/§2.3 常量引用为迭代 1 既有常量（HUD_FIRST_LINE_Y/HUD_SECOND_LINE_Y），新增常量则补入 §4.3/§3.3；
  3. **P2-1**：MDE 定义食物插值开关语义（吃食节拍食物不插值）+ 用例；
  4. **P2-2**：MDE 删除 InterpolatedCell 或给出真实消费点；Rect 消费点代码化或撤回声称；
  5. **P3-1/P3-2** 顺手修订；
  6. **S1**：SE 落实架构文档同步（接口清单 + dataclass 条款）；
  7. 修订后重新提交评审（release_module design FAIL 后 MDE 修订 → 重新 DONE → 本评审复核 PASS）。
