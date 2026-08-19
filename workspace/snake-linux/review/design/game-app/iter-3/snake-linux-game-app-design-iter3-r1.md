# SE 评审意见：game-app 迭代 3 功能模块设计（设计-iter3-r1）

> 评审人：SE · 2026-08-14
> 评审对象：`snake-linux/design/game-app/设计-iter3-r1.md`（MDE r1 首发）
> 评审基线：架构 `snake-linux/arch/v2.0.0/架构设计.md` + `功能模块分工表.md`；依赖契约实核 `code/game-core/iter-2/game_core/`（it_passed）、`code/gui-renderer/iter-3/gui_renderer/`（it_passed）、`code/platform-storage/iter-2/`（it_passed）；代码基线 `code/game-app/iter-1/`（it_passed）；需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）；iter-2 r2 SE 评审（PASS，`snake-linux-game-app-design-iter2-r2.md`）

## 结论：FAIL

r1 对 iter-2 遗留（5×P1 + 13×P2）的消化完整、依赖契约实核到位、迭代边界与最小侵入原则执行良好（以下"通过项"）。**但存在 2×P0，均直接导致需求验收项不可达，FO 照文 TDD 必产出错误行为**：

- **P0-1（G3-3 平滑插值）**：`_prev_snap` 赋值时机与 alpha 公式两处互相矛盾的逻辑错误，实现后插值恒无效或反向滑动 → **FR-07（平滑动画）验收不可达**；
- **P0-2（G3-2 窗口缩放）**：gui-renderer iter-3 窗口未开 `pygame.RESIZABLE` 标志，系统不产生 VIDEORESIZE 事件 → game-app `_drain_events` 缩放分支永不可达 → **FR-09（窗口自适应）验收不可达**（模块间契约断裂，设计依赖契约未显式声明事件源前提）。

---

## 一、P0（必须修订，修订后复审）

### P0-1：G3-3 插值链路自相矛盾——`_prev_snap` 赋值时机 + alpha 公式方向双错，FR-07 必失效

**位置**：§1.2（运行期状态表）、§4.5（`_tick`）、§4.6（`_interpolation_state`）、§6.4（INTERP-2/3/10）。

**实核与推演**（基于 renderer 锁定契约 `code/gui-renderer/iter-3/gui_renderer/renderer.py`）：

1. renderer 插值语义（实核 `_interpolate_position`）：`pos = prev + alpha * (cur - prev)`，**alpha=0 → prev（旧位置）、alpha=1 → current（新位置）**。
2. §4.5 `_tick` 代码：`self._prev_snap = self.game_state.snapshot()` 写在 `step()` **之后** → `_prev_snap` 恒为"step 后位置"。
3. §4.6 `_render` PLAYING 路径：`snap = self.game_state.snapshot()`（当前逻辑位置）→ `_interpolation_state(snap)` 用 `_prev_snap` 作 prev。
   - **同一帧内 prev 与 cur 恒相等**（`_prev_snap` 是 step 后位置 = 当前 snap）→ `_interpolate_position(prev, cur, alpha)` 无位移 → **插值恒无效，蛇仍是整格跳变**。§1.2"step 之前 snapshot → step 后写入"与 §4.5 代码互相矛盾；§4.5 注释"step 前 snapshot 用于下一帧插值"与实际代码（step 后保存）不符。
4. 即便把赋值时机修正为 step 前保存（prev=旧位置、cur=新位置），§4.6 alpha 公式 `alpha = 1.0 - (acc % tick_ms)/tick_ms` 仍错：
   - step 刚完成（elapsed≈0）→ alpha≈1.0 → 显示 current（新位置）；
   - 节拍推进（elapsed→tick_ms）→ alpha→0 → 显示 prev（旧位置）——**蛇从新位置滑回旧位置（反向滑动）**；
   - 下一 step 瞬间 alpha 跳回 1 → 又瞬移。视觉 = "每节拍瞬移 + 反向滑行"，FR-07"无整格跳变、视觉连贯"必败。
   - 正确公式应为 `alpha = (acc % tick_ms) / tick_ms`（0→1，从旧位置滑向新位置，step 完成帧 alpha≈0 显示旧位置，elapsed=tick 时 alpha→1 恰好衔接下一 step，连续）。

**修法（两处必须同时改）**：
- `_tick`：`self._prev_snap = self.game_state.snapshot()` 移到 `step()` **之前**（保存 step 前快照；OVER 分支仍置 None）；
- `_interpolation_state`：alpha 改为 `(acc % tick_ms) / tick_ms`；
- §6.4 配套修正：INTERP-2 期望 alpha=0.5 不变（80/160 与 1-80/160 同值，但语义要按新公式重述）；**INTERP-3** 断言 `acc=0 → alpha=1.0（瞬移）` 为反向公式固化，应改为 `acc=0 → alpha=0.0（显示 prev）`、`acc=tick_ms → alpha≈1.0（显示 cur）`；**INTERP-10** 断言 `_prev_snap.snake_body == 当前 snap.snake_body` 固化了错误赋值时机，应改为 `_prev_snap.snake_body == step 前位置`（与 step 后不同）。

### P0-2：FR-09 事件源断裂——gui-renderer 窗口无 RESIZABLE 标志，VIDEORESIZE 分支永不可达

**位置**：G3-2（§3.3/§4.4/§4.6/§6.4 RS-1~RS-7）、依赖契约（G3-6/附录 B）、附录 F 实核表。

**实核**（`code/gui-renderer/iter-3/gui_renderer/renderer.py`）：
- `init()`：`flags = 0`；`if self._enable_high_dpi: flags |= getattr(pygame, "SCALED", 0)`；`set_mode(self._window_size, flags)`——**无 `pygame.RESIZABLE`**；
- `handle_resize(w, h)`：`set_mode((w, h), self._flags)`——沿用同一 flags，同样无 RESIZABLE；
- 全仓库 grep `RESIZABLE`：gui-renderer iter-3 与 game-app iter-1 均无任何引用。

**pygame 行为**：窗口未带 RESIZABLE 标志时，窗口管理器禁止拖拽缩放，**pygame 不产生 VIDEORESIZE 事件**。因此 game-app G3-2 的 `_drain_events` VIDEORESIZE 分支（以及 RS-1~RS-7 全部 UT）在真实运行时**永不可达**——FR-09"拖拽改变窗口大小后等比缩放"验收不可达。gui-renderer 提供 `handle_resize` 却无事件来源，属模块间契约断裂（gui-renderer iter-3 代码检视仅核对接口签名与 UT，未核对运行时事件源，此缺口漏网）。

**修法**：
- gui-renderer `init()` flags 增加 `getattr(pygame, "RESIZABLE", 0)`（与 SCALED 同法 getattr 防御）——窗口职责在 renderer（架构分工表"gui-renderer 窗口等比缩放自适应"），由 renderer 补齐最合理；
- game-app 设计依赖契约（G3-6/附录 B/附录 F）显式声明前置前提："Renderer 窗口必须带 RESIZABLE 标志（VIDEORESIZE 事件源）"，并将该条纳入契约实核清单；
- 修订后需在真实窗口环境手工验证拖拽缩放事件流（UT 用 fake 事件注入无法暴露此缺口）。

---

## 二、P1（不阻塞 PASS 判定，但 FO 落地必须处理）

### P1-1：`_prev_snap` 生命周期缺口——`_new_game` 未重置，新局开局蛇身漂移

**位置**：§1.2（`_prev_snap` 字段说明）、§4.6（`_interpolation_state` 防御）、§4.4（`_dispatch_over` BACK_TO_MENU）/`_new_game`（设计未提及）。

**问题**：`_prev_snap` 仅在 `__init__` 初始化为 None、OVER 时置 None。`_new_game`（MENU 开始 / GAME_OVER 重开）不重置 → 新局首帧 PLAYING 路径 `_interpolation_state` 用**上一局残留快照**作 prev。若旧局蛇身长度与新局初始长度恰好相同（如旧局 3 节、新局 3 节），且 `_interpolation_state` 只有长度检查、**无距离检查**（§4.6 docstring 声称"距离 > 1 格 → 返回 None（防御）"，但实现仅 `len(prev_body) != len(cur_body)`，无坐标距离判断——文档与代码不符），则插值从旧局位置漂移到新局初始位置，**每局开局蛇身可见漂移**。

**修法**（二选一，建议都做）：
1. `_new_game` 内 `self._prev_snap = None`（首帧瞬移，与 `__init__` 语义一致）；
2. `_interpolation_state` 实现真实的 Chebyshev 距离防御（`max(|dx|, |dy|) > 1 → None`，与 renderer 内部 `_grid_distance` 一致），消除 docstring 与实现的偏差；UT 补一条"新旧局蛇身长度相同但位置不同 → 返回 None"。

---

## 三、P2（文档级，不阻塞，MDE 修订时一并修）

| # | 位置 | 问题 |
|---|------|------|
| P2-1 | §1.2 运行期状态表、§1.4 注释 | 引用 `SKIN_REGISTRY_NAMES[_skin_index]` / `SKIN_REGISTRY[0]`——gui-renderer **无 `SKIN_REGISTRY_NAMES` 导出**（`SKIN_REGISTRY` 为 dict）；§4.4 已正确用 `Renderer.skin_names()`，文档表述应统一为 `skin_names()` 派生 |
| P2-2 | §3.5 公开 API 表 | "InputAction Enum（**14** 个，G3-1/2 加 3 个）"——iter-2 基线已是 15 个（含 BACK_TO_MENU/ESCAPE/UNFOCUS），iter-3 新增 3 个应为 **18** 个 |
| P2-3 | §4.6 `_interpolation_state` | `if self.game_state is None: return None` 检查实例字段而非传入的 `snap` 参数（冗余防御；建议改为对 snap 参数做一致性检查或删除） |
| P2-4 | §4.6 / §6.4 INTERP-4 | app 侧吃食节拍直接返回 None，未使用 `InterpolationState.prev_food=None` 的"吃食节拍食物瞬移"语义（renderer 已支持该语义）——功能无缺口，建议文档注明"app 侧选择更保守防御，prev_food=None 语义由 renderer 单独兜底" |

---

## 四、架构遵循度核对（通过项）

- **依赖单向向下** ✓：game-app → gui-renderer/platform-storage/game-core；不读任何下划线私有（仅公开 API：`Renderer` 构造/`init`/`shutdown`/`render(interp=)`/`set_skin`/`handle_resize`/`skin_names`/`current_skin_name`/`fps_metric`），R3-2（get_surface 自绘）沿用 ✓
- **接口先行** ✓：依赖契约逐条实核通过（附录 F 与锁定代码一致：`enable_high_dpi` 参数、`SkinNotFoundError(name, available)`、`InterpolationState(alpha, prev_snake_body, prev_food=None)`、`SKIN_REGISTRY` 3 套含色盲形状/纹理、`HudData` 5 字段、`Snapshot` 7 字段、`GameState` frozen 命令式接口）
- **迭代边界** ✓：本迭代范围 = FR-07/FR-09/FR-10/NFR-04，与架构 §迭代计划迭代 3 出口（验收 3 GUI 呈现）对齐；FR-14/15/16、NFR-01 明确留迭代 4 ✓
- **数据流** ✓：事件 → `_map_event` 归一化（不感知屏态）→ `_drain_events` 屏态分发（SET_SKIN/RESIZE 同步处理不入 dispatch）→ `_dispatch_*`；snapshot → `_build_hud` + `_interpolation_state` → `render(interp=)`；皮肤经 `skin_names()`/`set_skin` 公开 API，不维护 App 内 `_skin_name` 副本 ✓
- **零配置/无网络/无音效/不写系统目录** ✓；`_map_event` 沿用 `_pygame_attr` 延迟读取（UT 友好）✓
- **最小侵入** ✓：4 处增量入口（`_switch_skin`/`_handle_resize`/`_interpolation_state`/`AppConfigV3`），主循环骨架不重写；不新建 iter-3 代码目录、增量落 iter-1 源码目录，与架构"同 v2.0.0 一个发布单元"一致 ✓
- **iter-2 遗留消化** ✓：G3-R-P1-A/B/C/D/E（fixture 注入顺序、create_storage monkeypatch、GameStatus 导入、AST 级断言、方案 A 表述统一）修订到位；13×P2 全部落地或文档化；issue-001（platform-storage mkdir 裸 OSError）标注待 MDE 开 issue ✓

## 五、可落地性（FO TDD 依据）

- UT 矩阵完整可执行：SK-1~11 / RS-1~7 / INTERP-1~10 / V3-1~7 全部给出输入-断言；conftest 的 `fake_renderer_iter3`/`app_with_config_v3` fixture 与 `_init_pygame` 注入顺序（P1-A/B 修订）自洽；5 阶段 TDD 步骤（V3 → skin → resize → interp → e2e）顺序合理。
- **但 P0-1/P0-2 不修，FO 照文实现将产出：FR-07 无动画（或反向滑动）+ FR-09 缩放分支死代码**。两处均为"设计文档内部矛盾/契约缺口"，非 FO 可实现层面问题，必须先由 MDE 修订设计。

---

## 六、修订要求（复审重点）

1. P0-1：`_tick` step 前保存 `_prev_snap` + alpha 公式改 `(acc % tick_ms)/tick_ms` + INTERP-3/10 断言同步修正，给出全文一致的插值链路（§1.2/§4.5/§4.6/§6.4）；
2. P0-2：与 gui-renderer 契约对齐——明确 RESIZABLE 标志归属（建议 renderer `init()` 补 `getattr(pygame, "RESIZABLE", 0)`），并将"VIDEORESIZE 事件源存在"写入依赖契约与附录 F 实核清单；
3. P1-1：`_new_game` 重置 `_prev_snap = None` + `_interpolation_state` 补真实距离防御（或删除 docstring 中的虚假声称）。

修订后提交复审，复审重点 = P0-1 插值链路全链推演 + P0-2 事件源契约。
