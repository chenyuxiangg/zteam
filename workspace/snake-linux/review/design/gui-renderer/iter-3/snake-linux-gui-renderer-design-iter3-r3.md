# 功能模块设计评审意见：gui-renderer（snake-linux v2.0.0 迭代 3）r3

> SE 评审（第三轮）· 依据：模块设计 `snake-linux/design/gui-renderer/设计-r3.md`（r3 修订版）+ 架构设计 `snake-linux/arch/v2.0.0/架构设计.md`（**已含 S1 同步修订**）+ 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）+ 迭代 1 已落地代码 `snake-linux/code/gui-renderer/iter-1/`（实核 gui_renderer/*.py 与 tests/*.py）+ game-core 已落地代码（实核 GameState/Point/Snapshot）
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：FAIL**
- 一句话理由：r2 的 6 条意见（P1×2 / P2×2 / P3×2）在 r3 **全部修订到位且质量高**（HUD 阴影改为「单次 render + 阴影 blit 偏移」保住迭代 1 断言、常量引用修正、InterpolatedCell 删除、SkinNotFoundError 实装、食物插值开关语义）；架构符合性本轮**全绿**（含 S1 架构文档同步已落实）；但实核发现 **1 项新 P1 阻塞**——`enable_high_dpi` 默认 True + `init()` 无条件执行 `pygame.SCALED`，而 fake_pygame 桩**未提供 SCALED 常量**且设计 §7.4 桩规范未要求补齐 → 迭代 1 既有 39 条用例与迭代 3 新增用例在 `r.init()` 处全部 AttributeError 崩溃，FO 按设计照抄即全红。另有 2 项 P2（HUD「阴影」实为同色重影、hud_shadow 字段无消费点；Rect 消费点文档自相矛盾）、3 项 P3。

---

## 1. r2 评审意见修订复核（逐条）

| r2 意见 | 修订位置（r3） | 复核结果 |
|---------|----------|----------|
| **P1-1** HUD 阴影破坏迭代 1 断言 | §0.1 兼容契约 + §3.1 docstring + §4.4 `_draw_hud`（每段单次 `font.render` + 阴影 blit 偏移 (+1,+1) + 主版 blit）+ §7.4/§7.5/§7.6 + §10 实核表 | ✅ 方案正确：`font.render` 仍 5 次、blit 10 次（5 阴影 + 5 主版）；迭代 1 既有 `test_render_hud_calls_font_render_5_times`（==5）与 `test_render_hud_status_over_uses_accent_color`（"Status" 单次 render 用 hud_accent）零修改通过；§0.1 明确声明「HUD 阴影 blit 属本迭代预期变更，font.render 计数不变」 |
| **P1-2** 引用不存在常量 | §4.4/§2.3 改引用迭代 1 既有 `HUD_FIRST_LINE_Y`/`HUD_SECOND_LINE_Y`；删除 HUD_TOP_ROW_Y/HUD_GAP/self._line_height 设计 | ✅ 与迭代 1 constants.py 实核一致（HUD_FIRST_LINE_Y=12 / HUD_SECOND_LINE_Y=44 / HUD_LINE_HEIGHT=28，无 HUD_TOP_ROW_Y/HUD_GAP）；FO 照抄无 NameError |
| **P2-1** 吃食节拍食物滑行 | §1.5 prev_food=None 语义 + §2.2 数据流 + §4.4 `_grid_distance` 距离兜底 + §7.3 fixture + §7.5/§7.6 用例 | ✅ 语义闭环：game-app 吃食节拍传 None → renderer 瞬移；距离 >1 格 renderer 自动跳过；用例 11/12 覆盖；game-app 伪代码 `prev_snap.food == cur_snap.food` 判断实核 Point == 可比较 ✅ |
| **P2-2** InterpolatedCell 死类型 + Rect 纸面消费点 | §1.5/§3.2/§3.3/§7.6 删除 InterpolatedCell；§1.4 Rect 声称 1 个消费点 | ⚠️ InterpolatedCell 删除彻底 ✅；**Rect 消费点文档自相矛盾**（见 P2-2，§1.4 声称消费 vs §4.4 明确不绘制） |
| **P3-1** SkinNotFoundError 构造签名 | §2.4 实装 `__init__(name, available)` + self.name/self.available；§4.5 set_skin 抛法同步；§7.6 断言 e.name/e.available | ✅ 与 errors.py 占位类演进一致，FO 可实现 |
| **P3-2** render 未 init 保护 | §3.1/§4.4 改为 `if self._screen is None: raise RenderError`；§5.5 鲁棒性表 + §7.6 用例 13 | ✅ 异常语义明确化，优于迭代 1 assert；与「不破坏契约」不冲突（异常类型变化非 API 变化） |

**复核结论：r2 全部 6 条意见修订质量合格，无回退。**

---

## 2. 架构符合性核对（本轮独立复核）

| 架构契约 | 设计落点 | 结果 |
|---|---|---|
| 模块类型：中间件，依赖 game-core | §0 | ✅ |
| 迭代排期：gui-renderer 迭代 1, 3；迭代 3 = 平滑动画/皮肤/缩放/高分屏 | §0.2/§0.3 出口 5 项全对齐 FR-07/09/10/NFR-04 | ✅ |
| `Renderer(window_size, *, skin=None, vsync=True, cell_size, grid_cols, grid_rows, enable_high_dpi=True)` | §3.1 签名一致（补默认值） | ✅ |
| `render(snapshot, hud, *, interp=None)` 向后兼容 | §3.1/§1.5 None=瞬移 | ✅ |
| `set_skin(name)` 对局不中断 / `handle_resize(w,h)` 等比缩放 / `skin_names()` / `current_skin_name` | §3.1/§4.5/§4.6 | ✅ |
| 皮肤注册表 ≥3 套（经典/深色/色盲友好，不以颜色为唯一区分） | §1.3 SKIN_REGISTRY 3 套 + 三重视觉冗余（cell_gap/纹理/形状） | ✅ |
| NFR-04 高分屏清晰（pygame.SCALED） | §4.7 enable_high_dpi 默认 True | ✅（**桩侧缺口见 P1-1**） |
| 数据流：core snapshot → renderer 只读；renderer 不持有游戏状态 | §1.5/§2.2 interp 由 game-app 维护 | ✅ |
| 无网络（NFR-06）/无音效（R-04）/无第三方依赖（除 pygame） | §5.4/§5.7 | ✅ |
| **S1（r2 遗留）：架构文档接口清单 + dataclass 条款同步** | 实核 arch/v2.0.0/架构设计.md：`Renderer(..., enable_high_dpi=True)` / `render(snapshot, hud, *, interp=None)` / set_skin / handle_resize / skin_names / current_skin_name 已写入接口清单；「dataclass 可用；禁 3.9+ 新语法」已修订 | ✅ **S1 已落实** |

**架构符合性：11/11 全绿（含 S1）。**

### 2.1 与迭代 1 落地代码向后兼容核对（实核 gui_renderer/*.py + tests/*.py）

| 迭代 1 落地事实 | 迭代 3 r3 设计 | 结果 |
|---|---|---|
| `Skin` 9 字段 frozen | +4 字段全默认值 → DEFAULT_SKIN 字面量构造合法 | ✅ |
| `render(snapshot, hud)` | `*, interp=None` 可选参，None 行为一致 | ✅ |
| `init()` flags=0 局部变量 | `self._flags` 属性 + SCALED 位（§4.7）；handle_resize 保留 flags | ✅ |
| `_draw_hud` x 坐标硬编码 16/200/400/300 | §4.4 同坐标（SCORE_X=16/HIGH_X=200/LENGTH_X=400/DIFF_X=16/STATUS_X=300） | ✅ |
| `cell = self._cell_size - 1` | `cell_draw = cell_size - skin.cell_gap`（classic=1 一致） | ✅ |
| HUD 常量 HUD_FIRST_LINE_Y/HUD_SECOND_LINE_Y | §4.4 引用既有常量 | ✅ |
| `test_render_hud_calls_font_render_5_times`（==5） | 单次 render + 阴影 blit 方案 → 5 次不变 | ✅ |
| `test_render_hud_status_over_uses_accent_color`（"Status" 单次 render == hud_accent） | OVER 时 Status 单次 render 用 hud_accent，无阴影版干扰 | ✅ |
| `_grid_to_pixel(cell: Tuple[int,int])` | 注解放宽 Tuple[float,float] + int(round()) 截断 | ✅ |
| `_validate_skin` RGB 校验 | 增量 hud_shadow/cell_gap/food_pattern/snake_pattern | ✅ |
| `_min_window_size` 公式（192×232） | MIN_PLAYABLE_W/H 常量公式一致（20×8+32=192；96+15×8+16=232） | ✅ |

---

## 3. 可落地性（FO 可否据其 TDD）

- **UT 框架整体质量高**：51 条增量用例 + TDD 七步顺序 + fake_pygame headless 方案 + fixture 显式断言 game-core 初始行为（蛇长 3/RUN/MEDIUM/tick_ms=160，实核全部吻合）；§7.5 断言规范与 §4.6/§5.5 三处口径一致（缩放 < 最小可玩尺寸统一抛 RenderError）；
- **❌ P1-1 直接阻塞 FO 开工**：enable_high_dpi 默认 True 时 `init()` 无条件执行 `flags |= pygame.SCALED`，fake_pygame 桩（迭代 1 conftest 沿用）无 SCALED 属性 → `r.init()` AttributeError → **迭代 1 既有全部用例 + 迭代 3 新增用例全崩**；设计 §7.4 桩规范只要求「set_mode 记录 flags」，未要求 fake 提供 SCALED 常量；§4.7 注释「若版本不支持会抛 AttributeError → UT 跳过此分支」对 fake 场景是空话（fake 无该属性即抛错，无「跳过」路径）；
- **P2-1 视觉语义不实**：HUD「阴影」实际是同一 surface 同色 blit 偏移两次 → 文字重影/加粗而非阴影；`hud_shadow` 字段被定义、被校验（§4.2），但 §4.4 `_draw_hud` 全程未读它——死字段，与 r2 P2-2（InterpolatedCell 无消费点）同类教训；深色皮肤下同色偏移视觉上仅轻微描边，色盲皮肤（浅底深字）偏移重影反而劣化可读性；
- **P2-2 Rect 消费点自相矛盾**：§1.4 声称「HUD 文本背景框是 Rect 真实消费点（见 §4.4）」；§4.4 注释明确「背景框不绘制，Rect 仅保留类型定义，无实际渲染消费」；§9 红线又写「Rect 真实消费点仅 HUD 背景框 1 处」——三处两说，FO 无法判断 Rect 是否参与绘制；
- 其余（插值时序推演表/缩放口径/皮肤注册表/异常路径/game-app 对接伪代码）均可落地，质量高。

---

## 4. 问题清单

### P1（阻塞，必须修订后重新评审）

**P1-1 fake_pygame 缺 `SCALED` 常量 + enable_high_dpi 默认 True → 全套 UT 在 init() 崩溃（§4.7 init() vs §7.4 桩规范 vs 迭代 1 conftest）**
- 迭代 1 conftest 的 fake_pygame（`types.ModuleType` 实例）**无 SCALED 属性**；r3 §4.7 `init()`：
  ```python
  flags = 0
  if self._enable_high_dpi:          # 默认 True
      flags |= pygame.SCALED          # fake 无此属性 → AttributeError
  ```
- r3 §7.3 conftest 模板 renderer fixture 用 `Renderer((640, 480))`（enable_high_dpi 走默认 True）→ `r.init()` 必崩；迭代 1 既有 renderer fixture `Renderer((512, 472))` 同样默认 True → 既有 39 条用例全部崩溃；§7.4 桩规范未要求 fake 提供 SCALED；§4.7 注释「UT 跳过此分支」无对应实现路径；
- **修改点（三选一，建议前两者同时做）**：
  1. §7.4 桩规范加一条「**必须**：fake_pygame 模块增加 `SCALED = 0x40000000` 常量（与 pygame 2.x 一致），否则默认 enable_high_dpi=True 时 init() AttributeError」；§7.3 模板同步补；
  2. 或 §7.3/迭代 1 renderer fixture 显式 `Renderer((512, 472), enable_high_dpi=False)`，hidpi 用例单独用 enable_high_dpi=True 的专用 fixture（§7.1 已预留 enable_high_dpi_disabled，需落到模板）；
  3. 或 init() 用 `flags |= getattr(pygame, "SCALED", 0)` 防御（兼容旧版 pygame 1.x 语义），并在 §5.5 鲁棒性表注明降级路径——注意此方案下「高分屏断言 flags 含 SCALED 位」需依赖 fake 提供 SCALED 才成立，仍需方案 1 配合。

### P2（应修订，不阻塞主体开发但影响声明一致性）

**P2-1 HUD「阴影」实为同色重影，hud_shadow 字段无消费点（§4.4 _draw_hud vs §1.2/§4.2）**
- §4.4 实现：`screen.blit(surf_score, (x+1, y+1))` + `screen.blit(surf_score, (x, y))`——**同一 surface、同一颜色**偏移两次：深色背景上同色文字偏移看起来是残影/加粗，不是阴影；`hud_shadow` 字段定义了（§1.2）、校验了（§4.2 RGB 越界检查）、兼容矩阵列了（§1.2），但 `_draw_hud` **从未读取 `self._skin.hud_shadow`**——死字段（与 r2 P2-2 InterpolatedCell 同类）；
- 若真要阴影：需用 hud_shadow 色再 render 一次阴影 surface（→ font.render 10 次，破坏迭代 1 断言，需显式修订断言）或对 surface 做颜色变换（复杂化，fake 也要同步支持）；
- **修改点**：二选一——(a) 诚实化：撤销「阴影」声称，§0.1/§4.4 明确为「同色偏移描边（文字加粗）效果」，并**删除 hud_shadow 字段**（§1.2/§4.2/§3.3/§10 同步）；(b) 真阴影：改用 hud_shadow 色二次 render，§7.4/§7.5/§7.6 同步修订断言并**显式声明修订迭代 1 两个 HUD 用例**（font.render 5→10 次、Status 断言取主版）。推荐 (a)（FR-10 皮肤系统不要求 HUD 阴影，去掉无功能损失，避免字段无消费点的设计债）。

**P2-2 Rect 消费点文档自相矛盾（§1.4 vs §4.4 vs §9）**
- §1.4 表：「HUD 文本背景框 `Rect(x,y,w,h)` 用于 `pygame.draw.rect` 给 HUD 文本行加底色——真实使用见 §4.4」；
- §4.4 注释：「HUD 背景框的 Rect **不绘制**……Rect 在迭代 3 仅保留类型定义，无实际渲染消费（迭代 1 评审遗留）」；
- §9 红线：「Rect 真实消费点仅 HUD 背景框 1 处」；
- **修改点**：统一口径——若保持「不绘制」，删 §1.4 消费点声称（改述「Rect 仍为迭代 1 遗留类型，迭代 3 无渲染消费」）、§9 红线同步改为「Rect 无新增消费点」；若坚持画背景框，需在 §4.4 给出真实绘制代码并同步 §7.5/§7.6 断言（draw.rect 次数将 +5），且确认「背景框遮挡游戏画面」的视觉取舍。

### P3（建议，顺手修订）

- **P3-1** §7.6 用例编号不连续（test_renderer_render 从 1 跳到 3、test_renderer_skin 从 3 跳到 5）且 skin 实际列出 5 条声称 6 条 → 合计应为 50 条而非 51；编号重排，计数与清单核对一致。
- **P3-2** §0.3「主循环驱动（game-app 职责，迭代 4 game-app 设计会接入）」表述与架构不符：架构迭代 1 game-app 已装配主循环（§迭代计划迭代 1），迭代 3 是「皮肤切换/设置界面」；应改述「主循环已在 game-app 迭代 1 落地，本模块只提供接口」。
- **P3-3** §0.1 阴影说明文字「阴影用 (255,255,255)→(255,255,255) 不行会变白」表述混乱（易误读为要二次 render 白色），随 P2-1 方案一起重写为清晰实现描述。

---

## 5. 结论与后续

- **FAIL**（r2 全部 6 条意见修订合格，无回退；架构符合性 11/11 全绿含 S1 落实；但新增 P1×1 阻塞 FO 开工，另有 P2×2、P3×3）。
- 后续要求：
  1. **P1-1**：§7.4 桩规范补 fake_pygame SCALED 常量（或 renderer fixture 显式 enable_high_dpi=False + hidpi 专用 fixture），保证 `r.init()` 在既有 + 新增用例全绿；
  2. **P2-1**：hud_shadow 字段与「阴影」声称二选一（推荐删字段去声称，或真阴影 + 显式修订既有断言）；
  3. **P2-2**：Rect 消费点三处口径统一；
  4. P3-1~3 顺手修订；
  5. 修订后重新提交评审（release_module design FAIL 后 MDE 修订 → 重新 DONE → 本评审复核 PASS）。
