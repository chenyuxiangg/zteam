# SE 评审意见：game-app 迭代 3 功能模块设计（设计-iter3-r2，修订版）

> 评审人：SE · 2026-08-14
> 评审对象：`snake-linux/design/game-app/设计-iter3-r2.md`（MDE r2 修订版，回应 SE r1 评审）
> 评审基线：架构 `snake-linux/arch/v2.0.0/架构设计.md` + `功能模块分工表.md`（迭代 3 出口 = 皮肤切换 UI/窗口缩放/平滑动画/NFR-04）；依赖契约实核 `code/game-core/iter-2/game_core/`（it_passed）、`code/gui-renderer/iter-3/gui_renderer/`（it_passed）、`code/platform-storage/iter-2/`（it_passed）；代码基线 `code/game-app/iter-1/`（it_passed）；需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved，FR-07/09/10/NFR-04 验收语句）；iter-3 r1 SE 评审（FAIL，2×P0 + 1×P1 + 4×P2）

## 结论：PASS

r1 评审的 **2×P0 + 1×P1 + 4×P2 全部落地**，且经 SE 逐条推演/实核确认修订自洽（非仅文档声明）：

- **P0-1（r2-1 插值链路）**：`_tick` step **前**保存 `_prev_snap`（§4.5 代码顺序：acc 递减 → 保存快照 → step，OVER 分支置 None）+ alpha 公式 `(acc % tick_ms)/tick_ms` 方向正确（acc=0 → alpha=0 显示 prev；acc→tick → alpha→1 显示 cur，连续衔接下一 step）——与 renderer 锁定契约 `_interpolate_position(prev, cur, alpha)`（alpha=0→prev / alpha=1→cur / alpha≥1.0 瞬移，实核 renderer.py 第 303-362 行）语义对齐；INTERP-2 示例推演通过（prev=[(5,5),(5,6),(5,7)] → cur=[(6,5),(5,5),(5,6)]，逐节 Chebyshev ≤1 → 返 InterpolationState(alpha=0.5, prev_snake_body=((5,5),(5,6),(5,7)), prev_food=(10,10))），INTERP-3/10 断言与实现一致；
- **P0-2（r2-2 事件源契约）**：设计侧修订到位——依赖契约（G3-6/§0/§2.2/§4.4/§4.7/§4.10/附录 B/附录 F）显式声明"Renderer 窗口必须带 RESIZABLE 标志（VIDEORESIZE 事件源）"、附录 F 实核清单新增该条目、§6.7 步骤 6 增补 gui-renderer 独立 UT + 真窗口手工验证、issue-003 跟踪落实。**实核确认**：gui-renderer iter-3 当前仍无 RESIZABLE（grep 无命中）——此为跨模块落实项（gui-renderer 模块所有者职责），不阻塞 game-app 设计 PASS，但 **FR-09 真窗口验收依赖其闭环**（见 P1-1 跟踪项）；
- **P1-1（r2-3 生命周期）**：`_new_game` 首行重置 `_prev_snap = None` + `_interpolation_state` 实现真实 Chebyshev 距离防御（逐节 `max(|dx|,|dy|) > 1 → None`，与 renderer 内部 `_grid_distance` 一致，消除 docstring 与实现偏差）+ INTERP-11/12 UT 新增；
- **P2-1~4（r2-4/5/6/7）**：皮肤名派生统一 `skin_names()[_skin_index]`（grep 全文验证 `SKIN_REGISTRY_NAMES` 仅存于修订说明，无残留错误引用）；InputAction 总数 18 明确；`_interpolation_state` 改 snap 参数防御 + INTERP-13；`prev_food` 始终传、renderer `_grid_distance` 兜底语义补注。

## 一、通过项（架构遵循度 + 可落地性实核）

- **依赖单向向下 + 接口先行** ✓：仅调 gui-renderer 公开 API（构造/`init`/`shutdown`/`render(interp=)`/`set_skin`/`handle_resize`/`skin_names`/`current_skin_name`/`fps_metric`），不碰 `_screen`/`_skin`/`_cell_size` 私有（R3-2 沿用 get_surface 自绘）；契约逐条实核通过（`SkinNotFoundError(name, available)`、`skin_names()` → `tuple(SKIN_REGISTRY.keys())`、`current_skin_name` → `self._skin.name`、`handle_resize` 类型校验 + MIN_PLAYABLE_W/H → RenderError、`InterpolationState(alpha, prev_snake_body, prev_food=None)`、SKIN_REGISTRY 3 套含形状/纹理字段——均与设计附录 F 一致）；
- **数据流** ✓：事件 → `_map_event` 归一化（VIDEORESIZE 分支在 KEYDOWN 过滤之前，顺序正确）→ `_drain_events` 屏态分发（SET_SKIN 按屏态：MENU 同步处理 continue / 其他态透传 MOVE_*；RESIZE 同步处理 continue 不入 dispatch）→ `_dispatch_*`；R3-1 MENU 屏态兜底与新增分支无冲突（SET_SKIN/RESIZE 在兜底前 continue）；
- **迭代边界** ✓：本迭代 = FR-07/09/10/NFR-04，与架构迭代 3 出口 + 分工表一致；FR-14/15/16、NFR-01 明确留迭代 4；K_LEFT/K_RIGHT 在 MENU 态由"START 兜底"变更为"切皮肤"属有意识决策（提示行已加"← → 切皮肤"，FR-10 MENU 是配置入口），PLAYING 态透传 MOVE_* 保留对局控制（FR-10 对局不中断）✓；
- **最小侵入** ✓：增量入口 4 处（`_switch_skin`/`_handle_resize`/`_interpolation_state`/`AppConfigV3`），不新建 iter-3 代码目录（同 v2.0.0 一个发布单元，G3-7 与架构一致）；
- **iter-2 遗留消化** ✓：G3-R-P1-A/B/C/D/E + 13×P2 全部落地（fixture 注入顺序、create_storage monkeypatch、GameStatus 导入、AST 级断言、方案 A 表述统一、死代码清理等）；issue-001（platform-storage 裸 OSError）标注待 MDE 开 issue；
- **可落地性（FO TDD）** ✓：UT 矩阵 SK-1~11 / RS-1~7 / INTERP-1~13 / V3-1~7 全部给出输入-断言（含 r2-1 alpha 断言修订、r2-3 INTERP-11/12、r2-6 INTERP-13）；conftest fixture 注入顺序自洽（先 monkeypatch create_storage/Renderer 再 `_init_pygame`，真实 IO 断绝）；5 阶段 TDD 步骤（V3 → skin → resize → interp → e2e）顺序合理；`AppConfigV3` frozen dataclass 继承合法性确认（父类字段全带默认值 + 新字段 `enable_high_dpi: bool = True` 有默认值，无 non-default-after-default 问题；V3-1~7 可落地）。

## 二、P1（不阻塞 PASS，FO/后续环节必须闭环）

### P1-1：gui-renderer RESIZABLE 落实为 FR-09 端到端验收前置（跨模块跟踪项）

**位置**：issue-003（设计附录 E）；附录 F 实核表 r2-2 新增条目。

**实核**：`code/gui-renderer/iter-3/gui_renderer/renderer.py` 当前 `init()` flags = 0 + `flags |= getattr(pygame, "SCALED", 0)`，`handle_resize` 沿用 `self._flags`——**无 RESIZABLE**，grep 全目录无命中。设计已正确将其声明为契约前置并开 issue-003 跟踪（gui-renderer 模块所有者职责，game-app 侧无降级路径——RS-1~7 UT 用 fake 事件注入只能验证 app 侧处理逻辑）。

**要求**：
1. gui-renderer 模块所有者落实 `init()`/`handle_resize` flags 增加 `getattr(pygame, "RESIZABLE", 0)`（与 SCALED 同法防御），并补独立 UT（§6.5 r2-2 已声明覆盖）；
2. **game-app 模块 code/review 检视门禁时核查**：若 RESIZABLE 仍未落实，FR-09 验收项标记挂起（真窗口手工验证清单 §6.7 步骤 16 同样依赖此）；
3. issue-003 闭环前，ST/QA 阶段 FR-09 验收不可达，需在 release_st_v2/release_qa 前确认闭环。

## 三、P2（文档/视觉级，FO 落地时一并处理，不阻塞）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P2-1 | §3.4 `AppConfigV3` docstring vs §4.7 `_init_pygame` 实现 | "isinstance False → **不传** enable_high_dpi"与实现"**总是传**（AppConfig 时兜底 True）"表述不一致（功能等价——True 即 Renderer 默认值，V3-5 断言两种表述均通过） | 文档统一为"总是传，AppConfig 时兜底 True" |
| P2-2 | §3.7/§4.9 draw_menu 皮肤行 y=315 | 难度最后一行 y=292 + CJK 字体高 ~22 → 底边 ≈314，皮肤行 y=315 仅 ~1px 间距，实际渲染可能重叠 | 皮肤行下移至 y=320 或按窗口高度计算（FR-08 美观基线） |
| P2-3 | §6.4 INTERP-6 | 断言"interp 为 None **或** InterpolationState"为弱断言（or 语义），无法区分首帧/正常帧 | 收敛为两条：首帧（`_prev_snap=None`）→ interp is None；正常帧 → interp 非 None 且 `alpha ∈ [0,1]` |
| P2-4 | §4.4 `_handle_resize` / §5.5 | FR-09"小于最小尺寸时给出提示"当前为 **stderr 提示**——`--windowed` 打包（迭代 4）无控制台，发布态用户不可见 | 迭代 3 即可用窗口标题/屏内一行文字提示（不阻塞——"维持尺寸不画面错乱"已满足主验收；迭代 4 A.1 错误提示完善已预告） |

## 四、修订要求（无需复审，FO 落地时按 P2-1~4 处理；P1-1 由 gui-renderer 模块所有者 + code/review 门禁闭环）

1. P2-1：§3.4 与 §4.7 表述统一（"总是传 enable_high_dpi，AppConfig 时兜底 True"）；
2. P2-2：皮肤行 y 坐标调整，避免与难度行重叠；
3. P2-3：INTERP-6 断言收敛（首帧 None / 正常帧 InterpolationState）；
4. P2-4：缩放失败提示渠道（windowed 可见性）在迭代 3 或迭代 4 明确；
5. P1-1：issue-003 跟踪 gui-renderer RESIZABLE 落实，game-app code/review 门禁核查闭环。
