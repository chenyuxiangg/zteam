# 功能模块设计：game-app（snake-linux v2.0.0 迭代 3）r1（首发）

> MDE r1 · 跨迭代复用基线：迭代 2 设计 `snake-linux/design/game-app/设计-iter2-r2.md`（SE 评审 PASS）+ 迭代 2 实际代码 `snake-linux/code/game-app/iter-1/`（沿用 iter-2 r2 SE 评审已 P0/P1 落地的代码：P0-1 方案 A 屏态同步、P0-2 INV-13 实例字段写回、P1-1 双类型 OSError 捕获、P1-2 ESC/Q 语义分离、P1-3 `_init_pygame` 内 `if None` 守卫）
> 依据：架构设计 `snake-linux/arch/v2.0.0/架构设计.md` §迭代计划迭代 3 + 功能模块分工表（"skin 切换 UI 接入"/"窗口缩放 UI 接入"/"平滑插值动画接入"）+ 需求规格 `snake-linux/analysis/snake-gui-r1.md`（FR-07/FR-09/FR-10/NFR-04 已固化）
> 依赖模块实际契约（**全部 it_passed，契约已锁定**）：
>   - game-core **迭代 2** `code/game-core/iter-2/game_core/`（state.py）—— `Snapshot(snake_body: Tuple[Point,...], food: Point, score: int, length: int, status: GameStatus, difficulty: Difficulty, tick_ms: int)`
>   - gui-renderer **迭代 3** `code/gui-renderer/iter-3/gui_renderer/`（renderer.py + types.py + errors.py + constants.py）——
>     - `Renderer((W,H), *, skin=None, vsync=True, cell_size=..., grid_cols=..., grid_rows=..., enable_high_dpi=True)` 构造
>     - `init()` / `shutdown()` / `render(snap, hud, *, interp=None)`（interp 非 None 时按 alpha 插值绘制，None=瞬移向后兼容）
>     - **`set_skin(name)`**（不在 SKIN_REGISTRY 抛 `SkinNotFoundError(name, available)`；**迭代 3 修订 P3-1**：构造签名携带 `available` 列表供 game-app UI 提示）
>     - **`handle_resize(w, h)`**（< MIN_PLAYABLE_W/H 抛 `RenderError`，重算 cell_size+字体+set_mode 保留 SCALED 标志）
>     - **`current_skin_name`** 属性 / **`skin_names()`** 返注册表 key tuple / **`fps_metric()`**
>     - **`InterpolationState(alpha, prev_snake_body: Tuple[Tuple[int,int],...], prev_food: Optional[Tuple[int,int]]=None)`**（迭代 3 修订 P2-1：prev_food=None 语义 = 吃食节拍食物瞬移渲染）
>     - **`SKIN_REGISTRY`** = `{"classic": DEFAULT_SKIN, "dark": DARK_SKIN, "colorblind_friendly": COLORBLIND_FRIENDLY_SKIN}`（**3 套，经典/深色/色盲友好**；色盲方案叠加形状/纹理辨识，不以颜色为唯一区分——`food_pattern`/`snake_pattern` 字段）
>     - `enable_high_dpi=True` 默认：`pygame.SCALED` 标志（pygame 1.x 无 `SCALED` 属性时降级 flags=0；getattr 防御）
>   - platform-storage **迭代 2** `code/platform-storage/iter-2/platform_storage/`（不调用，本迭代无新增）
> **目标**：FO 拿到本文即可 TDD 开发；迭代 3 在迭代 2 既有代码（iter-1 源码目录 `code/game-app/iter-1/`）上**增量修改**（不新建 iter-3 代码目录——同 v2.0.0 一个发布单元）；同时消化 iter-2 r2 SE 评审遗留的 5×P1（**测试基建级**，不改变实现方案）+ 13×P2（不阻塞 PASS，FO 落地时一并修）
> **关键决策**：
> 1. **新增 skin UI**：← → 方向键在 MENU 态循环切皮肤；游戏对局不中断（FR-10）；皮肤名 + 当前选中通过 Renderer.skin_names() / current_skin_name 派生，**不**在 App 内维护 `_skin_name` 字段
> 2. **窗口缩放接入**：`_drain_events` 内识别 `pygame.VIDEORESIZE` 事件 → 调 `Renderer.handle_resize(w, h)`；RenderError 兜底（< 最小尺寸给提示）
> 3. **平滑插值动画**：`App` 维护 `_prev_snap` 字段记录上一节拍前的 snap；_render PLAYING 路径构造 `InterpolationState(prev_snake_body, prev_food, alpha)` → 传入 `Renderer.render(snap, hud, interp=...)`；**alpha 计算 = (dt_ms - 已消费时长) / tick_ms**（已消费时长取模 tick_ms）；OVER 态不插值（瞬移）
> 4. **AppConfig 不变，AppConfigV3 子类扩展**：保留 iter-2 `AppConfig` 签名（向后兼容），新增 `AppConfigV3(AppConfig)` 子类加 `enable_high_dpi: bool = True` 字段 + `__post_init__` 校验；App.__init__ 用 `isinstance(config, AppConfigV3)` 判定并把 `enable_high_dpi` 传入 Renderer 构造
> 5. **迭代 3 文件组织**：**不**新建 `code/game-app/iter-3/` 目录；增量落在 iter-1 源码目录；新增 `test_app_iter3_*.py` 测试；`tests/test_game_app/conftest.py` 加 `app_with_mock_renderer_v3` fixture（P1-A/P1-B 修订后）

---

## 0. 修订摘要（相对 iter-2 设计 r2）

### 迭代 3 增量（核心目标，对应需求 FR-07/FR-09/FR-10/NFR-04）

| ID | 级别 | 修订内容 | 章节 |
|----|------|----------|------|
| **G3-1** | 应实现 | **皮肤切换 UI（MENU 态内）**：`_dispatch_menu` 新增 SET_SKIN_PREV/SET_SKIN_NEXT 两个 action（←/→ 方向键）；调 `Renderer.set_skin(name)`；失败 `SkinNotFoundError`（防御）→ `_render` MENU 时捕获并维持上一可用皮肤。**循环索引在 App 内维护**：`App._skin_index: int = 0`（默认 classic 对应 SKIN_REGISTRY 索引 0）；←/→ 在 `[0, len(SKIN_REGISTRY))` 内循环；SET_SKIN_* 只在 MENU 态生效，PLAYING/PAUSED/GAME_OVER 透传为方向 MOVE_*（保持原有行为，**游戏对局不中断**——FR-10） | §1.2 §3.3 §4.4 §6.4 |
| **G3-2** | 应实现 | **窗口等比缩放**：`_drain_events` 新增 `pygame.VIDEORESIZE` 事件分支 → 调 `Renderer.handle_resize(ev.w, ev.h)`；`RenderError` 兜底（最小尺寸）→ 提示并维持当前尺寸（不抛异常退出）；`_drain_events` 在游戏运行期持续接收 VIDEORESIZE 事件，PLAYING/PAUSED 态直接处理（**不影响对局、不打断游戏**——FR-09）；event 仍按原顺序归一化为 InputAction **之外的**特殊事件，扩展 `InputAction` 加 `RESIZE`（但 `RESIZE` 不入主循环 dispatch 列表——在 `_drain_events` 内同步处理） | §3.3 §4.4 §6.4 |
| **G3-3** | 应实现 | **平滑插值动画**：`_render` PLAYING 路径构造 `InterpolationState(alpha, prev_snake_body, prev_food)`；app 维护 `_prev_snap: Optional[Snapshot]` 字段（每节拍 step 前 snapshot → step 后写入；本帧 _render 使用 `_prev_snap` 与当前 snap 构造 InterpolationState）；**alpha 计算**：`alpha = 1.0 - (_tick_accumulator_ms % tick_ms) / tick_ms`（已消费时长占整节拍比例 → 下一节拍未到前持续补间；OVER 态不插值 alpha=1.0）；OVER 态、PAUSED 态、MENU/GAME_OVER 自绘路径不走插值（仅 PLAYING 路径插值）；首帧无 `_prev_snap` → alpha=1.0（瞬移渲染，向后兼容） | §1.2 §3.4 §4.5 §4.6 §6.4 |
| **G3-4** | 应实现 | **AppConfigV3 子类扩展**：`AppConfigV3(AppConfig)` 加 `enable_high_dpi: bool = True`（**NFR-04 高分屏清晰**）；`__post_init__` 不增校验（bool 无非法值）；`App.__init__` 用 `isinstance(self.config, AppConfigV3)` 判定，把 `enable_high_dpi` 传给 `Renderer(...)` 构造；iter-2 `AppConfig` 实例仍可用（`isinstance` False → 不传，Renderer 默认 `enable_high_dpi=True`——向后兼容，无破坏） | §1.2 §3.1 §3.4 §6.4 |
| **G3-5** | 应实现 | **MENU 屏态皮肤行展示**：`_render` MENU 路径在 `draw_menu` 自绘中**新增** `current_skin_name` 一行（在难度选项与最高分行之间 / 之下，根据窗口高度自适应）；`draw_menu` 形参新增 `current_skin_name: str = "classic"`；←/→ 切皮肤后下一帧立即生效（仅换 `_skin_index` + 调 `Renderer.set_skin`，无需重 render——`Renderer.render` 每帧读 `_skin`，FR-10 对局不中断） | §3.7 §4.6 §6.4 |
| **G3-6** | 文档 | **依赖契约更新**：依赖 gui-renderer iter-3 全部新接口（`set_skin`/`handle_resize`/`render(interp=)`/`skin_names()`/`current_skin_name`/`InterpolationState`/`enable_high_dpi` 参数）；game-core iter-2 沿用（不变）；platform-storage iter-2 沿用（不调用） | §0 §附录 B |
| **G3-7** | 文档 | **新文件组织决策**：迭代 3 **不**新建 `code/game-app/iter-3/` 目录（同 v2.0.0 一个发布单元）；增量修改 iter-1 源码目录（`app.py` / `input.py` / `config.py` / `menu.py` / `__init__.py` / `_constants.py`）；新增 `tests/test_game_app/test_app_iter3_{skin,resize,interp,config_v3}.py`；`tests/test_game_app/conftest.py` 调整 `app`/`app_in_playing` fixture 注入顺序（**P1-A/P1-B 消化**） | §4.1 §6.2 §附录 A |
| **G3-8** | 文档 | **跨迭代复用声明**：iter-3 不改 `_drain_events` MENU 屏态兜底语义（**R3-1 沿用**）；不改 `_tick` 循环内重读 tick_ms（**R3-8 沿用**）；不改 AppConfig 字段命名（**R3-4 沿用**）；不改退出码 0/1/2 语义（**R3-15 沿用**）；iter-3 增量**仅**新增 skin UI / 缩放 / 插值 / AppConfigV3 子类，4 项功能落在 4 处新代码，**最小侵入** | §附录 C |

### iter-2 r2 SE 评审遗留 5×P1 + 13×P2 同步消化（FO 落地修订，不阻塞本次 SE）

| ID | 级别 | 修订内容 | 章节 |
|----|------|----------|------|
| **G3-R-P1-A** | UT/fixture | **fixture 注入顺序彻底修正**：`app`/`app_in_playing` 等 fixture 改为先注入 fake_storage 再 `_init_pygame()`；配合 `_init_pygame` 内 `if self._storage is None` 守卫，**真实 create_storage 不再触发**（彻底避免触碰真实用户目录）；同步删除 iter-1 UT 中破坏性断言（`test_pause_hint_shown_is_false`/`test_renderer_is_none_at_init` 等已通过 iter-2 fixture 化重写不依赖，**此处仅文档一致性确认**） | §6.2 |
| **G3-R-P1-B** | UT/fixture | `app_with_storage` fixture 改 monkeypatch `game_app.storage.create_storage` 返回 tmp_path 实例（而非 fixture 内先 `_init_pygame()` 再覆盖 fake_storage——顺序与 P1-A 一致）；UT 触碰真实目录彻底断绝 | §6.2 |
| **G3-R-P1-C** | UT/fixture | `app_in_game_over` fixture 补 `from game_core import GameStatus`（P1-C iter-2 评审遗留；iter-3 沿用，无新增 GameStatus.OVER 引用点） | §6.2 |
| **G3-R-P1-D** | UT | P-8 改为**语句级 AST 断言**（`ast.parse(inspect.getsource(app._tick))` 后遍历 `ast.If`/`ast.If.body`/`elif` 节点，断言不存在 `GameStatus.PAUSED` 节点）；iter-3 沿用 | §6.4 |
| **G3-R-P1-E** | 文档 | §6.7 步骤 7/§4.10 注意点 3 已 iter-2 沿用方案 A 权威表述；iter-3 §6.7 步骤描述**不再引入**任何"自动转屏/方案 B"残语；§4.10 注意点 3 在 iter-3 章节内显式保留 PAUSED 同步切屏 INV-11 | §4.5 §4.10 §6.7 |
| **G3-R-P2-1** | 文档 | §5.6 错误矩阵"HighScoreStore mkdir 失败"行补 OSError（iter-2 §5.6 漏 OSError，iter-3 沿用补正） | §5.6 |
| **G3-R-P2-2** | 文档 | §5.5 鲁棒性表 Q/ESC 任意态行改写（iter-2 §5.5 已改；iter-3 沿用，新增 SkinNotFoundError 不中断游戏一行） | §5.5 |
| **G3-R-P2-3** | 文档 | §3.7 draw_pause_overlay docstring 与 §4.8 实现对齐（iter-2 已修；iter-3 沿用） | §3.7 |
| **G3-R-P2-4** | 实现 | 删 §4.3 模块级常量 `_PAUSE_KEY`/`_RESTART_KEY`/`_QUIT_KEY`/`_ESCAPE_KEY`/`_RESET_HIGHSCORE_KEY`/`_BACK_TO_MENU_KEY`/`_GAME_OVER_RESERVED_ACTIONS` 死代码（**iter-2 已删部分**；iter-3 §4.3 全面重写时一并清**残留**的 `_MENU_RESERVED_ACTIONS`/`_GAME_OVER_RESERVED_ACTIONS` 的文档/常量分离说明——保留 _MENU_RESERVED_ACTIONS/_GAME_OVER_RESERVED_ACTIONS frozenset 是必要的代码，删除其文档化的"模块级常量定义后未引用"的描述） | §4.3 |
| **G3-R-P2-5** | 实现 | 删 `translate_storage_error(func_name)` 死函数（iter-2 §3.8 标识；iter-3 沿用删除）；`storage.py` 仅保留 `create_storage(path)` 公开函数 | §3.8 §4.7 |
| **G3-R-P2-6** | UT/fixture | fake_pygame 替换列表补 fonts 模块（iter-2 §6.2 已补；iter-3 沿用 fixture 化文案） | §6.2 |
| **G3-R-P2-7** | UT/文档 | 测试事件构造统一沿用 iter-1 `FakeEvent`/`make_keydown` 辅助类（iter-2 §6.2 已提供；iter-3 §6.4 沿用） | §6.4 |
| **G3-R-P2-8** | 文档 | §6.7 步骤 1 引用 `test_storage.py` 改为 `test_app_iter2_storage.py`（iter-2 已修；iter-3 §6.7 沿用） | §6.7 |
| **G3-R-P2-9** | UT | H-1/H-2/H-3/H-4 断言实现方式改为 `font.render.call_args[0][0] == "最高分：100"`（iter-2 已修；iter-3 §6.4 沿用） | §6.4 |
| **G3-R-P2-10** | 文档 | §3.4 vs §4.4 `_dispatch_playing` 双版本描述统一——§3.4 为 docstring 概览、§4.4 为权威代码（iter-2 §3.4 与 §4.6 合并；iter-3 §3.4 与 §4.6 沿用同一模式：§3.4 仅 docstring 引用 §4.6） | §3.4 §4.4 |
| **G3-R-P2-11** | 文档 | §4.7 表述补 platform-storage issue（iter-2 已标识；iter-3 沿用——issue 由 MDE 后续开，**本轮不阻塞**） | §4.7 §附录 E |
| **G3-R-P2-12** | 文档 | §4.4 `_dispatch_menu` 注释补正：MENU 态 `MOVE_*` 在 `_drain_events` 已转 START 不会进 dispatch；`TOGGLE_PAUSE`/`RESTART` 在 `_MENU_RESERVED_ACTIONS` 内会进 dispatch 但被显式忽略（**iter-2 已补正**；iter-3 §4.4 沿用同表述，并**新增** SET_SKIN_PREV/NEXT 分支不进 `_MENU_RESERVED_ACTIONS`——由 `_drain_events` 在 MENU 态直接处理 SET_SKIN_PREV/NEXT，**不进 dispatch**，见 G3-1） | §4.4 |
| **G3-R-P2-13** | UT | P-4 描述改述为"app 层 `_dispatch_paused` 不处理 MOVE_*"（iter-2 已修；iter-3 §6.4 沿用） | §6.4 |

### 沿用 iter-2 r2（不修订，本轮已 PASS）

- 模块定位 / Python 3.8 兼容 / 零配置 / 无网络 / 无音效 / 不写系统目录
- 跨迭代复用（主循环骨架 / 状态机 / 输入映射 / 错误处理框架）
- **R3-1** 唯一屏态兜底（None→START 在 `_drain_events`）
- **R3-2** menu 不读 renderer 私有（走 `pygame.display.get_surface()`）
- **R3-4** 字段命名统一（`_difficulty` / `_high_score`）
- **R3-5** `_running: bool = True`（iter-3 在 dispatch 内部**仍未用**——G3-1 skin 切换不写 `_running`，仅换 `_skin_index`+调 `Renderer.set_skin`；保留字段供 iter-4 扩展）
- **R3-7** 删除 `_quit()` 死代码 + dispatch QUIT 分支
- **R3-8** `_tick` 循环内重读 tick_ms
- **R3-9** InvalidStateError 理论不可达不包装
- **R3-10** App.__init__ 不构造 Renderer / 不构造 HighScoreStore
- **R3-11** `_render` 共享一次 snap（G3-3 iter-3 在 PLAYING 路径需要 snap 两次：一次取 snap 给 `_build_hud`/插值构造 / 一次取 snap 给 Renderer.render？——**iter-3 修正**：snap 在 `_render` PLAYING 入口取一次，存 snap_local 复用：构造 `_build_hud(snap_local)` + 构造 `InterpolationState`（读 `_prev_snap`） + `Renderer.render(snap_local, hud, interp=...)`，**仍是一次 snap**）
- **R3-12** CJK 字体回退链
- **R3-14** `app_in_playing` fixture
- **R3-15** 退出码 2 shutdown 兜底
- **G2-1** PAUSED 状态机 INV-10/11（P0-1 方案 A 单点同步切屏）
- **G2-2** HighScoreStore 接入（INV-12）
- **G2-3** score_callback 写入（INV-13，P0-2 直接写实例字段）
- **G2-4** 失焦自动暂停（INV-14 失焦仅 PLAYING 追加 UNFOCUS）
- **G2-5** 暂停遮罩 `draw_pause_overlay`
- **G2-6** 最高分展示（`draw_menu`/`draw_game_over` 加 `high_score` 形参）
- **G2-7** BACK_TO_MENU + ESC/Q 语义分离（INV-15）

---

## 0. 模块定位与迭代边界

| 项 | 值 |
|----|---|
| 模块 | game-app |
| 类型 | 上层应用 |
| 依赖 | game-core（纯逻辑，迭代 2 **it_passed — 接口以 iter-2 落地为准**）、gui-renderer（迭代 3 **it_passed — 接口以 iter-3 落地为准**，iter-3 game-app 首次调用 `set_skin`/`handle_resize`/`render(interp=)`/`skin_names()`/`current_skin_name`/`InterpolationState`/`enable_high_dpi`）、platform-storage（迭代 2 接入，沿用不调用） |
| 被依赖 | 无（顶层装配） |
| 承载需求 | snake-gui **主体**（FR-01~16 中除 gui-renderer 子集外的全部）—— 本迭代 3 范围 = FR-07 平滑动画 + FR-09 窗口缩放 + FR-10 皮肤系统 + NFR-04 高分屏清晰 |
| 迭代 | 3（视觉增强） |
| 不引入 | 第三方除 pygame 外任何依赖；不引入音效；不引入网络；不引入 config 文件；不写系统目录 |
| 跨迭代复用 | 主循环骨架 / 界面状态机 / 输入映射 / 错误处理框架 / AppConfig 字段 / 字段命名 / CJK 字体 / 退出码语义 跨 1-4 迭代复用；迭代 3 通过**新增 _skin_index/_prev_snap 字段 + InputAction.SET_SKIN_PREV/NEXT/RESIZE + _dispatch_menu 新分支 + _render 新路径**接入，不重写主循环 |
| PyInstaller 入口 | `snake-gui.py`（包根 `__main__.py`，`if __name__ == "__main__": main()`） |

### 迭代 3 出口（与架构 §迭代计划对齐）

- ✅ **皮肤切换 UI**（G3-1）：MENU 态 ←/→ 切皮肤，循环索引 `App._skin_index`，调用 `Renderer.set_skin(name)`；切换后对局不中断（仅 PLAYING/PAUSED 态透传，**不打断游戏**——FR-10）
- ✅ **皮肤 ≥3 套**（沿用 gui-renderer iter-3 SKIN_REGISTRY）：经典/深色/色盲友好（**色盲方案叠加形状/纹理辨识**，不以颜色为唯一区分——food_pattern="ringed"/"checkered" + snake_pattern="solid"/"striped"）
- ✅ **窗口等比缩放**（G3-2）：`pygame.VIDEORESIZE` → `Renderer.handle_resize(w, h)`；< 最小尺寸 → 维持当前尺寸 + stderr 提示（不中断）；无变形/无裁切（FR-09）
- ✅ **平滑插值动画**（G3-3）：`_render` PLAYING 路径调 `Renderer.render(snap, hud, interp=InterpolationState(alpha, prev_snake_body, prev_food))`；无整格跳变/无闪烁（FR-07）
- ✅ **高分屏清晰**（G3-4）：`AppConfigV3` 子类 + `enable_high_dpi=True` → `Renderer.__init__(enable_high_dpi=True)` → `pygame.SCALED` 标志（NFR-04）
- ✅ **MENU 屏态皮肤名展示**（G3-5）：`draw_menu` 加 `current_skin_name: str` 形参；MENU 自绘新增 "当前皮肤：xxx" 行
- ❌ 三平台打包（FR-14/15，迭代 4）
- ❌ 性能调优 ≥60FPS（NFR-01，迭代 4 落 profile 脚本）
- ❌ 完善错误提示 + 用户指南（FR-16，迭代 4）

### 迭代 3 已知技术约束（FO 实现必读）

1. **Python 3.8 兼容**：与架构 §代码风格约定一致；frozen dataclass + `__post_init__` 3.7+ 特性沿用。
2. **零配置**：不读 ini/env/YAML/JSON 配置；皮肤通过游戏内 UI 选择（←/→）即时生效。
3. **无网络**：全模块不 `import socket` / `import urllib` / `import http` / `import requests`；UT 不发起网络。
4. **无音效**：不 `import pygame.mixer` 或任何音频模块。
5. **依赖边界**：game-app **可** import pygame（事件循环 + 字体 + 自绘菜单/结束画面/暂停遮罩 + VIDEORESIZE 处理）；**不可**侵入 game-core 内部（仅公开 API：`Point`/`Direction`/`Difficulty`/`GameStatus`/`GameState`/`Snapshot`）；**不可**侵入 gui-renderer 内部（仅公开 API：`Renderer((W,H), *, skin, ..., enable_high_dpi)` 构造、`init()`/`shutdown()` 生命周期、`render(snap, hud, *, interp)` 帧绘制、`set_skin(name)`、`handle_resize(w, h)`、`skin_names()`/`current_skin_name`/`fps_metric()`；**不**碰 `_screen` / `_skin` / `_cell_size` 等下划线私有——R3-2 沿用）。
6. **platform-storage 沿用 iter-2 接入**：iter-3 不新增 storage 调用；HighScoreStore 仅 `_high_score` 字段在 HUD/菜单/结束画面展示。
7. **不读 gui-renderer 私有属性**：自绘菜单/结束画面/暂停遮罩通过 `pygame.display.get_surface()` 取得 renderer 已创建的窗口 surface（**R3-2 沿用**）；皮肤名通过 `Renderer.current_skin_name` 公开属性读；皮肤列表通过 `Renderer.skin_names()` 公开方法读；**不**碰 `Renderer._skin.name` / `Renderer._initialized` 等私有。
8. **AppConfigV3 与 AppConfig 共存**：`App.__init__` 用 `isinstance(self.config, AppConfigV3)` 判定 `enable_high_dpi` 是否传入 Renderer；iter-2 `AppConfig` 实例保持兼容（isinstance False → 默认 `enable_high_dpi=True` 由 Renderer 默认值兜底——向后兼容，无破坏）。
9. **迭代 3 不新建 iter-3 代码目录**：所有增量落在 `snake-linux/code/game-app/iter-1/` 源码目录（同 v2.0.0 一个发布单元）；PyInstaller `--collect-submodules` 不变。

---

## 1. 数据结构

### 1.1 界面状态枚举（app 层级，沿用 iter-2）

| 类型 | 字段 | 说明 |
|------|------|------|
| `AppScreen`（Enum） | `MENU` / `PLAYING` / `PAUSED` / `GAME_OVER` | app 顶层界面状态机；iter-2 加 `PAUSED`；iter-3 不再加 |
| `InputAction`（Enum，**G3-1/G3-2 新增**） | 沿用 iter-2 11 个 + **`SET_SKIN_PREV`** + **`SET_SKIN_NEXT`** + **`RESIZE`** | iter-3 新增 3 个：SET_SKIN_PREV = "skin_prev"（← 键）；SET_SKIN_NEXT = "skin_next"（→ 键）；RESIZE = "resize"（pygame.VIDEORESIZE 事件） |
| `AppConfig`（dataclass, frozen，**沿用 iter-2**） | `window_w: int = 640` / `window_h: int = 480` / `fps_cap: int = 60` / `min_window_w: int = 512` / `min_window_h: int = 472` | 不可变运行期常量；iter-3 字段不变 |
| **`AppConfigV3`**（**dataclass(frozen), G3-4 新增**，继承 AppConfig） | 父类字段 + **`enable_high_dpi: bool = True`** | 不可变运行期常量；iter-3 新增 enable_high_dpi；**App.__init__ 用 isinstance 判定并把 enable_high_dpi 传给 Renderer 构造** |

### 1.2 运行期状态（G3-1/G3-3 新增字段；其余沿用 iter-2）

| 字段 | 类型 | 说明 |
|------|------|------|
| `_skin_index: int` | 皮肤循环索引 | `0` 默认（经典皮肤，对应 SKIN_REGISTRY 第 0 个）；`Renderer.set_skin(name)` 通过 `_skin_index` 派生：`SKIN_REGISTRY_NAMES[_skin_index]`；← 减 1（取模 len），→ 加 1（取模 len） |
| `_prev_snap: Optional[Snapshot]` | 上一节拍前快照（**G3-3 新增**） | `None` 初始；每节拍 `_tick` 在 step 之前 snapshot → step 后写入 `self._prev_snap = self.game_state.snapshot()`；`_render` PLAYING 路径读 `_prev_snap` 构造 `InterpolationState`；**OVER 态 step 后 `self._prev_snap = None`**（下一帧 `_render` PLAYING 已切 GAME_OVER 不读），`PAUSED` 态 step 未发生，`_prev_snap` 不变（下一帧 _render PAUSED 不走插值） |

### 1.3 难度选择状态 / 菜单子状态（沿用 iter-2）

| 类型 | 字段 | 说明 |
|------|------|------|
| `Difficulty`（enum） | EASY / MEDIUM / HARD | 难度档（继承 game-core） |

### 1.4 运行期字段汇总（iter-2 + G3-1/G3-3 增量）

```python
# App.__init__ 完整字段列表（iter-2 §1.3 + iter-3 增量）
self.config: AppConfig  # 或 AppConfigV3 子类实例（iter-3 G3-4 判定）
self.screen: AppScreen = AppScreen.MENU
self._difficulty: Difficulty = Difficulty.MEDIUM  # R3-4 统一
self.game_state: Optional[GameState] = None
self._renderer: Optional[Renderer] = None
self._storage: Optional[Any] = None  # iter-2 沿用，默认 None 让 UT 不依赖磁盘
self._high_score: int = 0  # iter-2 沿用，_init_pygame 覆盖为 storage.load()
self._tick_accumulator_ms: int = 0
self._running: bool = True  # R3-5 + iter-2 G2-R-N2：主循环不读，保留供 iter-4 用
self._skin_index: int = 0  # G3-1 新增：皮肤循环索引（默认经典 SKIN_REGISTRY[0]）
self._prev_snap: Optional[Snapshot] = None  # G3-3 新增：上一节拍前快照（首帧 None → 瞬移渲染）
# 字体 / 时钟（iter-2 沿用）
self._menu_title_font: Optional[pygame.font.Font] = None
self._menu_body_font: Optional[pygame.font.Font] = None
self.clock: Optional[pygame.time.Clock] = None
```

---

## 2. 数据传递方式

### 2.1 App ↔ game-core（沿用 iter-2）

- **调用方向**：App → GameState（构造/查询/修改）；所有修改返回新对象，App 替换 `self.game_state`（frozen dataclass 模式，iter-1 R3-7 沿用）
- **查询**：App 调 `game_state.snapshot()` 获 `Snapshot`（含 `snake_body`/`food`/`score`/`length`/`status`/`difficulty`/`tick_ms`）
- **修改**：`set_direction(d)` / `toggle_pause()` / `step()` / `set_score_callback(cb)`（iter-2 已锁定签名）
- **迭代 3 增量**：**无**——iter-3 game-core 接口不变

### 2.2 App ↔ gui-renderer（G3-1/2/3/4 新增）

| 数据 | 方向 | 用途 |
|------|------|------|
| `enable_high_dpi: bool` | App → Renderer（构造） | G3-4 高分屏清晰（NFR-04） |
| `Renderer.skin_names()` | Renderer → App | G3-1 切皮肤循环索引派生；MENU 屏态展示 |
| `Renderer.current_skin_name` | Renderer → App | G3-5 MENU 屏态 "当前皮肤：xxx" 展示 |
| `Renderer.set_skin(name)` | App → Renderer | G3-1 切皮肤（仅换 `_skin` 引用，下一帧 render 即生效） |
| `Renderer.handle_resize(w, h)` | App → Renderer | G3-2 窗口缩放（重算 cell_size+字体+set_mode） |
| `InterpolationState(alpha, prev_snake_body, prev_food)` | App → Renderer.render(interp=...) | G3-3 平滑插值（alpha=1.0 瞬移向后兼容） |
| `Renderer.render(snap, hud, *, interp=None)` | App → Renderer | G3-3 PLAYING/PAUSED 帧绘制 |
| `Renderer.fps_metric()` | Renderer → App | iter-1 沿用（NFR-01 回归，iter-4 落 profile） |

### 2.3 App ↔ platform-storage（沿用 iter-2）

- **调用方向**：App → HighScoreStore（构造/查询/写入）；iter-3 不新增 storage 调用
- **场景**：仅 `_init_pygame` 构造 + `_dispatch_menu(RESET_HIGHSCORE)` 重置 + `_new_game` 注册 score_callback（G2-2/3）

### 2.4 事件队列 → InputAction 归一化（沿用 iter-2 + G3-1/G3-2 增量）

- **pygame 事件**：`pygame.event.get()` 返 list；iter-1 R3-1 沿用 MENU 屏态兜底
- **G3-1**：iter-3 新增 SET_SKIN_PREV/NEXT（←/→ KEYDOWN）；**MENU 态**`_drain_events` 检测 SET_SKIN_PREV/NEXT → **不进 dispatch**（与 MOVE_* 在 MENU 态转 START 不同——SET_SKIN 是 UI 操作而非"开始游戏"）；其他屏态（PLAYING/PAUSED/GAME_OVER）SET_SKIN_PREV/NEXT 透传为原方向 MOVE_*（保持 iter-2 行为）
- **G3-2**：`pygame.VIDEORESIZE` 事件在 `_drain_events` 内**直接同步处理**（不走 dispatch）：`self._renderer.handle_resize(ev.w, ev.h)`；`RenderError` 兜底（< MIN_PLAYABLE_W/H）→ stderr 提示 + 维持当前尺寸（不抛、不退）

---

## 3. 对外接口

### 3.1 `AppConfig` / `AppConfigV3`（**G3-4 新增 AppConfigV3**）

```python
from dataclasses import dataclass
from .errors import ConfigError


@dataclass(frozen=True)
class AppConfig:
    """运行期不可变常量。FR-09/NFR-01/NFR-02。

    iter-3 沿用：字段不变。G3-4 通过子类化 AppConfigV3 扩展 enable_high_dpi（NFR-04 高分屏清晰）。
    """
    window_w: int = 640
    window_h: int = 480
    fps_cap: int = 60
    min_window_w: int = 512
    min_window_h: int = 472

    def __post_init__(self) -> None:
        """iter-2 G2-R-N1 沿用：构造期校验字段合法性，非法抛 ConfigError。"""
        if self.fps_cap <= 0:
            raise ConfigError(f"fps_cap 必须 > 0，收到 {self.fps_cap}")
        if self.window_w < self.min_window_w or self.window_h < self.min_window_h:
            raise ConfigError(
                f"窗口尺寸 ({self.window_w}, {self.window_h}) 小于最小可玩 "
                f"({self.min_window_w}, {self.min_window_h})"
            )


@dataclass(frozen=True)  # G3-4 新增
class AppConfigV3(AppConfig):
    """iter-3 扩展：增加 enable_high_dpi 字段（NFR-04 高分屏清晰）。

    字段：父类全部 + enable_high_dpi: bool = True。
    __post_init__ 不重写（继承父类校验 + bool 字段无非法值）。
    App.__init__ 用 isinstance(config, AppConfigV3) 判定并把 enable_high_dpi 传给 Renderer 构造。
    """
    enable_high_dpi: bool = True  # G3-4 新增
    # __post_init__ 继承父类，不重写
```

### 3.2 `AppScreen`（Enum，沿用 iter-2）

```python
from enum import Enum


class AppScreen(Enum):
    """app 顶层界面状态机。FR-11 + FR-12 入口。iter-3 不再加。"""
    MENU = "menu"
    PLAYING = "playing"
    PAUSED = "paused"
    GAME_OVER = "over"
```

### 3.3 `InputAction`（Enum，**G3-1/G3-2 新增 SET_SKIN_PREV/NEXT/RESIZE**）

```python
class InputAction(Enum):
    """pygame 事件归一化结果。FO 只需实现 _map_event() 即可。

    iter-3 新增（G3-1/G3-2）：
    - SET_SKIN_PREV = "skin_prev"    # ← 键：切上一皮肤（G3-1）
    - SET_SKIN_NEXT = "skin_next"    # → 键：切下一皮肤（G3-1）
    - RESIZE = "resize"              # pygame.VIDEORESIZE 事件（G3-2）—— 不进主循环 dispatch 列表
                                     # _drain_events 内同步处理（直接调 Renderer.handle_resize）
                                     # 其他动作维持原行为
    """
    QUIT = "quit"
    START = "start"
    MOVE_UP = "up"
    MOVE_DOWN = "down"
    MOVE_LEFT = "left"
    MOVE_RIGHT = "right"
    TOGGLE_PAUSE = "pause"
    RESTART = "restart"
    SELECT_EASY = "sel_easy"
    SELECT_MEDIUM = "sel_med"
    SELECT_HARD = "sel_hard"
    RESET_HIGHSCORE = "reset_hs"
    BACK_TO_MENU = "back"
    ESCAPE = "escape"
    UNFOCUS = "unfocus"
    # ---- iter-3 增量（G3-1/G3-2）----
    SET_SKIN_PREV = "skin_prev"     # G3-1 ← 键：MENU 态切上一皮肤
    SET_SKIN_NEXT = "skin_next"     # G3-1 → 键：MENU 态切下一皮肤
    RESIZE = "resize"               # G3-2 pygame.VIDEORESIZE 事件
```

### 3.4 `App` 主类（**G3-1/2/3/4/5 增量**；iter-2 全量沿用）

```python
class App:
    """snake-gui 顶层装配；PyInstaller 入口。

    iter-3 增量（G3-1/2/3/4/5）：
    - 新增 _skin_index: int 字段（G3-1，皮肤循环索引）
    - 新增 _prev_snap: Optional[Snapshot] 字段（G3-3，平滑插值）
    - AppConfigV3 子类支持：isinstance 判定 + enable_high_dpi 传入 Renderer（G3-4）
    - _drain_events 同步处理 VIDEORESIZE（G3-2，不入 dispatch）
    - _drain_events MENU 态处理 SET_SKIN_PREV/NEXT（G3-1，不入 dispatch）
    - _render PLAYING 路径走 interp=InterpolationState（G3-3）
    - _tick step 后维护 _prev_snap（G3-3）
    - _render MENU 自绘加 current_skin_name 形参（G3-5）

    沿用 iter-2（不修订）：None→START 屏态兜底 / menu 用 get_surface / _tick 循环内重读
                            / App.__init__ 不构造 Renderer / CJK 字体回退链 / 退出码 2 兜底
                            / 字段命名 _difficulty / _high_score / PAUSED 屏态 INV-10/11
                            / HighScoreStore 接入 INV-12 / score_callback 实例字段写回 INV-13
    """

    def __init__(self, config: AppConfig = AppConfig()) -> None:
        """仅置字段，不开窗、不调 pygame.init、不构造 Renderer、不构造 HighScoreStore。

        默认参数 config: AppConfig = AppConfig() 在 import 期求值一次（frozen 不可变）。
        iter-3 增量：新增 _skin_index=0 / _prev_snap=None 字段。
        """
        self.config = config
        self.screen: AppScreen = AppScreen.MENU
        self._difficulty: Difficulty = Difficulty.MEDIUM
        self.game_state: Optional[GameState] = None
        self._renderer: Optional[Renderer] = None
        self._storage: Optional[Any] = None
        self._high_score: int = 0
        self._tick_accumulator_ms: int = 0
        self._running: bool = True
        # ---- iter-3 增量（G3-1/G3-3）----
        self._skin_index: int = 0            # G3-1：皮肤循环索引（默认经典 SKIN_REGISTRY[0]）
        self._prev_snap: Optional[Snapshot] = None  # G3-3：上一节拍前快照
        # 字体 / 时钟（iter-2 沿用）
        self._menu_title_font: Optional[pygame.font.Font] = None
        self._menu_body_font: Optional[pygame.font.Font] = None
        self.clock: Optional[pygame.time.Clock] = None

    # ---- 公开入口（iter-2 沿用，G3-4 仅扩展 _init_pygame）----
    def run(self) -> int: ...
    def _init_pygame(self) -> None: ...  # iter-3 G3-4：构造 Renderer 时根据 config 类型传 enable_high_dpi
```

### 3.5 公开 API 列表

| 名称 | 类型 | 用途 |
|------|------|------|
| `AppConfig` | dataclass(frozen) + `__post_init__` | 运行期常量；iter-2 沿用 |
| **`AppConfigV3`** | **dataclass(frozen), G3-4 新增** | **iter-3 扩展 enable_high_dpi 字段；子类化 AppConfig 不破坏向后兼容** |
| `AppScreen` | Enum（4 态） | app 界面状态机 |
| `InputAction` | Enum（**14** 个，**G3-1/2 加 3 个**） | 输入归一化 |
| `App` | class | 主装配类 |
| `main()` | function | 入口函数：`App().run()`，捕获 `ConfigError`/`AppError` |
| `AppError` 子类 | 异常类 | iter-2 沿用 |
| `HudData` | 来自 gui_renderer | HUD 5 字段 dataclass（沿用 iter-1） |

### 3.6 异常（iter-2 沿用 + G3-2 新增 RenderError 兜底语义）

```python
# errors.py — iter-2 沿用 + iter-3 显式声明 GUI 错误已包装 GraphicsUnavailableError
class AppError(RuntimeError):
    """app 顶层错误基类。"""

class GraphicsUnavailableError(AppError):
    """Renderer.init() / pygame.display.set_mode 失败 → 退出码 2。"""

class ConfigError(AppError):
    """AppConfig / AppConfigV3 字段非法 → 启动时抛。G2-R-N1：构造期 __post_init__ 校验。"""

class StorageUnavailableError(AppError):
    """HighScoreStore.save/reset 失败 → 退出码 1（iter-2 G2-2）。"""

# iter-3 G3-2 新增语义：RenderError（来自 gui_renderer）在 VIDEORESIZE 路径捕获后 stderr 提示 + 维持当前尺寸；
# 不包装为 GraphicsUnavailableError（避免退出码 2）；不包装为 AppError（避免退出码 1）—— 仅 stderr 提示并继续游戏。
# 实现位置：§4.4 _drain_events 内的 VIDEORESIZE 分支
```

### 3.7 `menu` 模块自绘接口（**G3-5 增量**；iter-2 G2-5/6 沿用）

```python
# menu.py — iter-3 G3-5：draw_menu 加 current_skin_name 形参；draw_game_over / draw_pause_overlay 不变

def draw_menu(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    difficulty: Difficulty,
    high_score: int = 0,                # iter-2 G2-6
    current_skin_name: str = "classic",  # G3-5 iter-3 新增
) -> None:
    """MENU 态自绘。G3-5：current_skin_name 形参（默认 "classic" 保持向后兼容）。

    自绘内容（iter-3）：
    1. 标题 "Snake GUI v2.0.0"（沿用 iter-1）
    2. 难度选项三行（沿用 iter-1）
    3. **当前皮肤行**（G3-5 新增）：body_font 渲染 "当前皮肤：<current_skin_name>"（居中）
       位置：难度选项与最高分行之间（或根据窗口高度自适应）；iter-2 难度选项 y=220~292，
       最高分行 y=340；G3-5 皮肤行 y=315（在难度选项 y=292 与最高分行 y=340 之间留 23px）
    4. 最高分行（iter-2 G2-6 沿用，high_score > 0 时显示）
    5. 提示行 + Q 退出提示（iter-2 G2-R-N3 沿用，**iter-3 新增 ← → 切皮肤提示**）
    """


def draw_game_over(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    score: int,
    high_score: int = 0,                # iter-2 G2-6
) -> None:
    """GAME_OVER 态自绘。iter-3 不变。"""


def draw_pause_overlay(
    surface: pygame.Surface,
    body_font: pygame.font.Font,
) -> None:
    """PAUSED 遮罩自绘。iter-3 不变。"""
```

### 3.8 `storage` 模块（iter-2 沿用，G3-R-P2-5 删除 translate_storage_error 死函数）

```python
# storage.py — iter-3 仅保留 create_storage(path) 公开函数；iter-2 §3.8 的 translate_storage_error
# 死函数（G2-R-P2-5 修订要求）已删除
from typing import Optional
from pathlib import Path
from platform_storage import HighScoreStore


def create_storage(path: Optional[Path] = None) -> HighScoreStore:
    """构造 HighScoreStore 实例。iter-2 G2-2 沿用，无 iter-3 增量。"""
    return HighScoreStore(path)


__all__ = ["create_storage"]
```

---

## 4. 实现细节/步骤

### 4.1 模块文件组织（G3-7 决策；iter-2 文件结构沿用）

```
snake-linux/code/game-app/iter-1/                       # iter-3 不新建目录（G3-7 决策）
├── game_app/
│   ├── __init__.py             # 对外 re-export（**G3-4 加 AppConfigV3**）
│   ├── __main__.py             # PyInstaller 入口（沿用 iter-1）
│   ├── config.py               # AppConfig + __post_init__ 校验（沿用 iter-2）
│   │                           # **新增** AppConfigV3 子类（G3-4）
│   ├── screens.py              # AppScreen 4 态（iter-2 沿用）
│   ├── input.py                # InputAction 加 SET_SKIN_PREV/NEXT/RESIZE（G3-1/G3-2）；
│   │                           # _map_event 新增 ←/→ 映射；_map_event 新增 VIDEORESIZE 映射
│   │                           # G3-R-P2-4 删除文档中"模块级常量定义后未引用"的描述
│   ├── app.py                  # 主装配类（G3-1/2/3/4/5 全部修改；详见 §4.2-4.6）
│   ├── menu.py                 # draw_menu 加 current_skin_name 形参（G3-5）；
│   │                           # draw_game_over / draw_pause_overlay 不变
│   ├── fonts.py                # _load_cjk_font（沿用 R3-12）
│   ├── storage.py              # create_storage（G2-R-P2-5 删除 translate_storage_error 死函数）
│   ├── errors.py               # AppError / GraphicsUnavailableError / ConfigError；
│   │                           # StorageUnavailableError（iter-2 沿用）
│   └── _constants.py           # 颜色常量 + WINDOW_TITLE（iter-2 沿用）
└── tests/
    └── test_game_app/
        ├── __init__.py
        ├── conftest.py                 # iter-2 fixtures + G3 fixture 调整（G3-R-P1-A/B/C）
        ├── test_config.py              # iter-2 沿用 + **G3-R-V3-1/2/3**（AppConfigV3 校验）
        ├── test_input_map.py           # iter-2 沿用 + G3 SK-1/2/3 SET_SKIN/RESIZE 映射
        ├── test_drain_events.py        # iter-2 沿用 + G3 SK 屏态处理 + RS-1 VIDEORESIZE
        ├── test_app_init.py            # iter-2 沿用 + G3-R-V3 init 时 enable_high_dpi 判定
        ├── test_app_menu.py            # iter-2 沿用
        ├── test_app_playing.py         # iter-2 沿用
        ├── test_app_game_over.py       # iter-2 沿用
        ├── test_app_tick.py            # iter-2 沿用
        ├── test_app_exit.py            # iter-2 沿用
        ├── test_app_error.py           # iter-2 沿用
        ├── test_app_hud.py             # iter-2 沿用
        ├── test_app_render_dispatch.py # iter-2 沿用 + **G3-3 INTERP** 测试
        ├── test_app_iter2_pause.py     # iter-2 沿用
        ├── test_app_iter2_storage.py   # iter-2 沿用
        ├── test_app_iter2_unfocus.py   # iter-2 沿用
        ├── test_app_iter2_overlay.py   # iter-2 沿用
        ├── test_app_iter3_skin.py      # **G3-1 新增**：皮肤切换 UI 测试
        ├── test_app_iter3_resize.py    # **G3-2 新增**：窗口缩放测试
        ├── test_app_iter3_interp.py    # **G3-3 新增**：平滑插值测试
        └── test_app_iter3_config_v3.py # **G3-4 新增**：AppConfigV3 子类测试
```

### 4.2 主循环骨架（iter-2 沿用 + G3-1/2 增量）

```python
def run(self) -> int:
    """主循环。iter-3 不变；iter-2 R3-15 退出码 2 路径 shutdown 兜底。"""
    self._renderer = None
    try:
        try:
            self._init_pygame()  # G3-4：根据 config 类型传 enable_high_dpi
        except GraphicsUnavailableError as e:
            print(f"[错误] 无法初始化图形界面: {e}\n请确认系统有可用的图形环境。",
                  file=sys.stderr)
            return 2
        return self._run_loop()
    finally:
        try:
            if self._renderer is not None:
                self._renderer.shutdown()
        except Exception:
            pass


def _run_loop(self) -> int:
    """主事件循环。iter-2 沿用 + iter-3 G3-1/2 在 _drain_events 内处理。

    G3-1：SET_SKIN_PREV/NEXT 在 _drain_events 内同步处理（不进 dispatch）；
    G3-2：VIDEORESIZE 在 _drain_events 内同步处理（不进 dispatch）。
    主循环结构不变：while True + actions 列表 + QUIT 优先 break。
    """
    try:
        while True:
            assert self.clock is not None
            dt_ms = self.clock.tick_busy_loop(self.config.fps_cap)
            actions = self._drain_events()
            if InputAction.QUIT in actions:
                break
            for a in actions:
                self._dispatch(a)
            if self.screen == AppScreen.PLAYING:
                self._tick(dt_ms)  # G3-3：_tick step 后维护 self._prev_snap
            self._render()        # G3-3：_render PLAYING 路径走 interp
        return 0
    except AppError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 1
```

### 4.3 输入映射（_map_event，**G3-1/G3-2 新增**；iter-2 全量沿用）

```python
# input.py — G3-1/G3-2 增量；iter-2 G2-3/7/P1-2 沿用；G3-R-P2-4 删除"模块级常量定义后未引用"描述

# 模块级常量（仅保留必要的 frozenset；删除原 G2 中 _PAUSE_KEY/_RESTART_KEY/_QUIT_KEY 等死字符串常量）
_MENU_RESERVED_ACTIONS = frozenset({
    InputAction.QUIT,
    InputAction.SELECT_EASY, InputAction.SELECT_MEDIUM, InputAction.SELECT_HARD,
    InputAction.TOGGLE_PAUSE,
    InputAction.RESET_HIGHSCORE,
    InputAction.RESTART,
    # ESCAPE 不在（MENU 态下 ESCAPE 由 _drain_events 兜底转 START，与 iter-1 "ESC 视为开始"一致）
    # UNFOCUS 不在（内部信号）
    # SET_SKIN_PREV/NEXT 不在（G3-1：MENU 态下由 _drain_events 同步处理；其他屏态透传为 MOVE_*，不进 _MENU_RESERVED_ACTIONS）
    # RESIZE 不在（G3-2：_drain_events 同步处理）
})

_GAME_OVER_RESERVED_ACTIONS = frozenset({
    InputAction.QUIT,
    InputAction.RESTART,
    InputAction.BACK_TO_MENU,
    InputAction.ESCAPE,
})


def _map_event(event) -> Optional[InputAction]:
    """单键归一化；不感知屏态；返回 None 表示未映射。

    iter-3 增量（G3-1/G3-2）：
    - ← 键 → SET_SKIN_PREV（G3-1）—— 仅 K_LEFT；MENU 态 _drain_events 同步处理，其他屏态由 _drain_events 兜底
      （iter-3 选择**：SET_SKIN_PREV/NEXT 在 _drain_events 内按屏态分发**，不在 _map_event 层做屏态判定——
      保持 _map_event"不感知屏态"原则；屏态兜底/同步处理由 _drain_events 完成）
    - → 键 → SET_SKIN_NEXT（G3-1）
    - pygame.VIDEORESIZE 事件 → RESIZE（G3-2）—— _drain_events 同步处理
    """
    QUIT_TYPE = _pygame_attr("QUIT")
    KEYDOWN_TYPE = _pygame_attr("KEYDOWN")
    VIDEORESIZE_TYPE = _pygame_attr("VIDEORESIZE")  # G3-2 新增
    K_q = _pygame_attr("K_q")
    K_ESCAPE = _pygame_attr("K_ESCAPE")
    K_BACKSPACE = _pygame_attr("K_BACKSPACE")

    if event.type == QUIT_TYPE:
        return InputAction.QUIT
    # G3-2 新增：VIDEORESIZE 事件 → RESIZE
    if event.type == VIDEORESIZE_TYPE:
        return InputAction.RESIZE
    if event.type != KEYDOWN_TYPE:
        return None
    k = event.key
    if k == K_q:
        return InputAction.QUIT
    if k == K_ESCAPE:
        return InputAction.ESCAPE
    if k == K_BACKSPACE:
        return InputAction.BACK_TO_MENU
    if k == _pygame_attr("K_p"):
        return InputAction.TOGGLE_PAUSE
    if k == _pygame_attr("K_r"):
        return InputAction.RESTART
    if k == _pygame_attr("K_h"):
        return InputAction.RESET_HIGHSCORE
    if k == _pygame_attr("K_1"):
        return InputAction.SELECT_EASY
    if k == _pygame_attr("K_2"):
        return InputAction.SELECT_MEDIUM
    if k == _pygame_attr("K_3"):
        return InputAction.SELECT_HARD
    # G3-1 新增：←/→ 映射 SET_SKIN_PREV/NEXT
    if k == _pygame_attr("K_LEFT"):
        return InputAction.SET_SKIN_PREV  # iter-3：在 _drain_events 内按屏态分发
    if k == _pygame_attr("K_RIGHT"):
        return InputAction.SET_SKIN_NEXT  # iter-3：在 _drain_events 内按屏态分发
    # 原有 WASD 方向键（iter-2 沿用）—— 其他屏态下 SET_SKIN_PREV/NEXT 由 _drain_events 兜底转为 MOVE_*
    if k == _pygame_attr("K_w") or k == _pygame_attr("K_UP"):
        return InputAction.MOVE_UP
    if k == _pygame_attr("K_s") or k == _pygame_attr("K_DOWN"):
        return InputAction.MOVE_DOWN
    if k == _pygame_attr("K_a"):
        return InputAction.MOVE_LEFT  # iter-3 注意：K_a 不再映射 SET_SKIN_PREV（仅 K_LEFT/方向键 ← 触发；K_a 保持 MOVE_LEFT 行为）
    if k == _pygame_attr("K_d"):
        return InputAction.MOVE_RIGHT  # iter-3 注意：K_d 不再映射 SET_SKIN_NEXT
    return None  # 未映射
```

> **iter-3 设计决策说明（用户审阅重点）**：
> 1. ←/→ 方向键在 **MENU 态**触发皮肤切换（`SET_SKIN_PREV`/`SET_SKIN_NEXT`）；
> 2. **PLAYING/PAUSED/GAME_OVER 态**下 ←/→ 行为：**保持原 MOVE_LEFT/MOVE_RIGHT 行为**（避免影响对局控制）—— 由 `_drain_events` 内按屏态分发实现（见 §4.4）；
> 3. **K_a/K_d**（WASD 方案）始终为 MOVE_LEFT/MOVE_RIGHT，不映射皮肤（**避免**WASD 用户意外触发皮肤切换）；
> 4. **FR-10"游戏中对局不中断"**语义：在 PLAYING 态下玩家按 ←/→ 切方向**不会**意外换皮肤；
> 5. 皮肤切换 UI 入口**仅**在 MENU 态（MENU 是玩家配置入口）；若用户想要"游戏中切皮肤"，需 ESC/Backspace 返 MENU 后再切（与 iter-2 BACK_TO_MENU 模式一致）。

### 4.4 状态机 dispatch 表 + G3-1/2 屏态分发

```python
# app.py — G3-1 SET_SKIN 按屏态分发 + G3-2 VIDEORESIZE 同步处理；iter-2 G2-1/3/4/7 沿用

def _drain_events(self) -> List[InputAction]:
    """本帧所有 pygame 事件归一化；QUIT 优先 break；iter-3 增量：

    G3-2：VIDEORESIZE 事件在循环内**同步处理**（调 Renderer.handle_resize），
          然后**不**进入 actions 列表（不入 dispatch）。
    G3-1：SET_SKIN_PREV/NEXT 在 MENU 态**同步处理**（调 Renderer.set_skin + 更新 _skin_index），
          然后**不**进入 actions 列表（不入 dispatch）；其他屏态透传为 MOVE_LEFT/MOVE_RIGHT。

    iter-2 沿用：
    - R3-1 屏态兜底（MENU 态除保留键外 → START）
    - G2-4 失焦检测（PLAYING 态追加 UNFOCUS）
    - G2-7 GAME_OVER 态 ESCAPE → BACK_TO_MENU
    - P1-2 Q/ESC 语义分离
    """
    raw = pygame.event.get()
    actions: List[InputAction] = []
    for ev in raw:
        action = _map_event(ev)
        # G3-2 增量：VIDEORESIZE 同步处理（不入 actions）
        if action == InputAction.RESIZE:
            self._handle_resize(ev)  # 见下方；RenderError 兜底
            continue
        # G3-1 增量：SET_SKIN_PREV/NEXT 按屏态分发
        if action in (InputAction.SET_SKIN_PREV, InputAction.SET_SKIN_NEXT):
            if self.screen == AppScreen.MENU:
                # MENU 态：同步处理皮肤切换
                self._switch_skin(direction=action)
                continue  # 不入 actions
            else:
                # 其他屏态（PLAYING/PAUSED/GAME_OVER）：透传为 MOVE_LEFT/MOVE_RIGHT（保持原行为）
                action = (InputAction.MOVE_LEFT if action == InputAction.SET_SKIN_PREV
                          else InputAction.MOVE_RIGHT)
        # iter-2 屏态兜底 + ESC 覆盖（沿用）
        if self.screen == AppScreen.MENU:
            if action is None:
                action = InputAction.START
            elif action not in _MENU_RESERVED_ACTIONS:
                action = InputAction.START
        elif self.screen == AppScreen.GAME_OVER:
            if action == InputAction.ESCAPE:
                action = InputAction.BACK_TO_MENU
        if action is not None:
            actions.append(action)

    # G2-4 失焦检测（iter-2 沿用，仅 PLAYING 态）
    if self.screen == AppScreen.PLAYING:
        try:
            focused = pygame.key.get_focused()
        except Exception:
            focused = True
        if not focused:
            actions.append(InputAction.UNFOCUS)
    return actions


def _switch_skin(self, direction: InputAction) -> None:
    """G3-1：皮肤切换（仅 MENU 态调用）。

    步骤：
    1. 调 Renderer.skin_names() 获当前注册表所有皮肤名 tuple
    2. 计算新索引：(direction==SET_SKIN_PREV) ? (_skin_index - 1) % len : (_skin_index + 1) % len
    3. 调 self._renderer.set_skin(skin_names[new_index])
    4. 更新 self._skin_index = new_index
    5. SkinNotFoundError 兜底：理论上不会发生（skin_names() 返注册表内的所有 key），
       但若 set_skin 抛 SkinNotFoundError（防御），维持 _skin_index 不变 + stderr 提示
    """
    assert self._renderer is not None, "MENU 态 _renderer 必须已 init"
    skin_names = self._renderer.skin_names()
    if not skin_names:
        return  # 防御：注册表为空不切
    if direction == InputAction.SET_SKIN_PREV:
        new_index = (self._skin_index - 1) % len(skin_names)
    else:  # SET_SKIN_NEXT
        new_index = (self._skin_index + 1) % len(skin_names)
    try:
        self._renderer.set_skin(skin_names[new_index])
        self._skin_index = new_index
    except SkinNotFoundError as e:
        # 理论不可达（skin_names() 返注册表内的所有 key）；防御性 stderr 提示
        print(f"[警告] 切换皮肤失败: {e}", file=sys.stderr)


def _handle_resize(self, event) -> None:
    """G3-2：窗口缩放处理（_drain_events 内同步调用）。

    步骤：
    1. 调 self._renderer.handle_resize(event.w, event.h)
    2. RenderError 兜底（< MIN_PLAYABLE_W/H 或类型错误）：
       stderr 提示 + 不更新（renderer 内部维持原尺寸）—— 不抛异常，不退游戏
    """
    assert self._renderer is not None, "_handle_resize 前 renderer 必须 init"
    try:
        self._renderer.handle_resize(event.w, event.h)
    except RenderError as e:
        # G3-2 兜底：尺寸过小/类型错误 → stderr 提示 + 维持当前尺寸（不抛、不退）
        # INV-15（新增）：缩放失败不中断游戏
        print(f"[警告] 窗口缩放失败: {e}", file=sys.stderr)


def _dispatch(self, action: InputAction) -> None:
    """按当前 screen 分发。iter-3 不变。"""
    if self.screen == AppScreen.MENU:
        self._dispatch_menu(action)
    elif self.screen == AppScreen.PLAYING:
        self._dispatch_playing(action)
    elif self.screen == AppScreen.PAUSED:
        self._dispatch_paused(action)
    elif self.screen == AppScreen.GAME_OVER:
        self._dispatch_over(action)


def _dispatch_menu(self, action: InputAction) -> None:
    """MENU 态分发。G3-1：SET_SKIN_PREV/NEXT 在 _drain_events 内处理不进 dispatch。

    iter-3 沿用 iter-2 全部分支（SELECT_*/RESET_HIGHSCORE/START）；G3-1 SET_SKIN_* 不进 dispatch。
    G3-R-P2-12 注释补正：MENU 态下 MOVE_* 在 _drain_events 已转 START 不会进 dispatch；
    TOGGLE_PAUSE/RESTART/RESET_HIGHSCORE 在 _MENU_RESERVED_ACTIONS 内会进 dispatch 但被显式忽略。
    """
    if action == InputAction.SELECT_EASY:
        self._difficulty = Difficulty.EASY
    elif action == InputAction.SELECT_MEDIUM:
        self._difficulty = Difficulty.MEDIUM
    elif action == InputAction.SELECT_HARD:
        self._difficulty = Difficulty.HARD
    elif action == InputAction.RESET_HIGHSCORE:
        if self._storage is not None:
            try:
                self._storage.reset()
            except StorageError as e:
                raise StorageUnavailableError(f"重置最高分失败: {e}") from e
            self._high_score = 0
    elif action == InputAction.START:
        self._new_game(self._difficulty)
    # MOVE_*/TOGGLE_PAUSE/RESTART/RESET_HIGHSCORE 理论上进不来（_drain_events 保留键透传）
    # 但 RESET_HIGHSCORE 显式处理；其余显式忽略保持防御性


def _dispatch_playing(self, action: InputAction) -> None:
    """PLAYING 态分发。iter-3 沿用 iter-2 G2-1 P0-1 方案 A 同步切屏。"""
    if action in (
        InputAction.MOVE_UP, InputAction.MOVE_DOWN,
        InputAction.MOVE_LEFT, InputAction.MOVE_RIGHT,
    ):
        d = {
            InputAction.MOVE_UP: Direction.UP,
            InputAction.MOVE_DOWN: Direction.DOWN,
            InputAction.MOVE_LEFT: Direction.LEFT,
            InputAction.MOVE_RIGHT: Direction.RIGHT,
        }
        self.game_state = self.game_state.set_direction(d[action])
    elif action == InputAction.TOGGLE_PAUSE:
        self.game_state = self.game_state.toggle_pause()
        self.screen = AppScreen.PAUSED  # P0-1 同步切屏（INV-11）
    elif action == InputAction.UNFOCUS:
        if self.game_state.status == GameStatus.RUN:
            self.game_state = self.game_state.toggle_pause()
            self.screen = AppScreen.PAUSED  # P0-1 同步切屏（INV-11）


def _dispatch_paused(self, action: InputAction) -> None:
    """PAUSED 态分发。iter-3 沿用 iter-2 G2-1 P0-1 方案 A 同步切屏。"""
    if action == InputAction.TOGGLE_PAUSE:
        self.game_state = self.game_state.toggle_pause()
        self.screen = AppScreen.PLAYING
    elif action == InputAction.UNFOCUS:
        pass  # PAUSED 态再失焦不变


def _dispatch_over(self, action: InputAction) -> None:
    """GAME_OVER 态分发。iter-3 沿用 iter-2 G2-7。"""
    if action == InputAction.RESTART:
        self._new_game(self._difficulty)
    elif action == InputAction.BACK_TO_MENU:
        self.screen = AppScreen.MENU
        self.game_state = None  # INV-7 重置
```

### 4.5 节拍推进（_tick，**G3-3 维护 _prev_snap**；iter-2 G2-1/R3-8 沿用）

```python
def _tick(self, dt_ms: int) -> None:
    """PLAYING 态累加节拍。iter-3 G3-3 增量：每节拍 step 后维护 self._prev_snap。

    iter-3 G3-3：
    - 每节拍 step 前 snapshot（pre_snap = self.game_state.snapshot()）—— 用于下一帧 _render 构造 InterpolationState
    - step 后写入 self._prev_snap = self.game_state.snapshot()（下一帧 _render 读）
    - OVER 自动转 GAME_OVER（G2-1）；OVER 态 _prev_snap = None（下一帧 _render GAME_OVER 不读）
    - 首帧 _prev_snap=None → _render PLAYING 路径 alpha=1.0（瞬移渲染，向后兼容）
    - PAUSED 态不进入此函数（主循环判断）；_prev_snap 不变
    """
    assert self.screen == AppScreen.PLAYING  # G2-1 INV-10/11 入口断言
    assert self.game_state is not None
    assert self.game_state.status == GameStatus.RUN  # INV-1 入口断言
    self._tick_accumulator_ms += dt_ms
    while True:
        tick_ms = self.game_state.snapshot().tick_ms
        if self._tick_accumulator_ms < tick_ms:
            break
        self._tick_accumulator_ms -= tick_ms
        # G3-3：step 前 snapshot 用于下一帧插值
        self.game_state = self.game_state.step()
        new_status = self.game_state.status
        if new_status == GameStatus.OVER:
            self.screen = AppScreen.GAME_OVER
            self._prev_snap = None  # G3-3：OVER 态 _prev_snap 清空（_render GAME_OVER 不读）
            break
        # G3-3：step 后写入 _prev_snap（下一帧 _render 读）
        self._prev_snap = self.game_state.snapshot()
```

### 4.6 渲染分发（**G3-3/G3-5 增量**；iter-2 G2-1/5/6/R3-11 沿用）

```python
def _build_hud(self, snap: Snapshot) -> HudData:
    """iter-2 沿用。R3-11 共享 snap（G3-3 沿用：snap 在 _render 入口取一次复用）。"""
    assert self._menu_body_font is not None
    return HudData(
        score=snap.score,
        high_score=self._high_score,
        length=snap.length,
        difficulty_label=_DIFFICULTY_LABEL[self._difficulty],
        status_label=_STATUS_LABEL[snap.status],
    )


def _interpolation_state(self, snap: Snapshot) -> Optional[InterpolationState]:
    """G3-3：构造 InterpolationState（仅 PLAYING 路径调用）。

    返回：
    - 若 _prev_snap is None → 返回 None（首帧，Renderer 走瞬移渲染）
    - 若 _prev_snap.snake_body 与 snap.snake_body 距离 > 1 格 → 返回 None（防御：避免跳变插值）
      —— 实核：renderer 内部也有 _grid_distance 兜底（r3 P2-1），app 侧同样兜底
    - 否则返回 InterpolationState(alpha, prev_snake_body, prev_food)
      - alpha = 1.0 - (_tick_accumulator_ms % tick_ms) / tick_ms
        # 已消费时长占整节拍比例 → 下一节拍未到前持续补间
        # 注：tick_ms 在 _render 内取一次避免漂移
      - prev_snake_body = tuple((p.x, p.y) for p in _prev_snap.snake_body)
      - prev_food = (_prev_snap.food.x, _prev_snap.food.y) if _prev_snap.food else None
    """
    if self._prev_snap is None:
        return None
    if self.game_state is None:
        return None
    # 防御：上一帧到当前帧蛇身坐标距离 > 1 格 → 跳变，不插值
    prev_body = self._prev_snap.snake_body
    cur_body = snap.snake_body
    if len(prev_body) != len(cur_body):
        return None  # 蛇身长度变化（吃食）→ renderer 兜底
    # alpha 计算（与 _tick 循环内重读 tick_ms 一致——避免漂移）
    tick_ms = snap.tick_ms
    if tick_ms <= 0:
        return None  # 防御：tick_ms 异常
    elapsed_in_tick = self._tick_accumulator_ms % tick_ms
    alpha = 1.0 - elapsed_in_tick / tick_ms
    alpha = max(0.0, min(1.0, alpha))  # clip
    return InterpolationState(
        alpha=alpha,
        prev_snake_body=tuple((p.x, p.y) for p in prev_body),
        prev_food=(self._prev_snap.food.x, self._prev_snap.food.y),
    )


def _render(self) -> None:
    """按 screen 分发。G3-3 PLAYING 路径走 interp；G3-5 MENU 加 current_skin_name。

    iter-3 增量（G3-3/G3-5）：
    - PLAYING 路径：snap 在 _render 入口取一次 snap_local；构造 _build_hud(snap_local) +
      _interpolation_state(snap_local) → Renderer.render(snap_local, hud, interp=...)
      —— R3-11 共享一次 snap 不变
    - MENU 路径：调 draw_menu 加 current_skin_name=Renderer.current_skin_name
    - GAME_OVER / PAUSED 路径不变（iter-2 沿用）
    """
    if self.screen == AppScreen.MENU:
        surface = pygame.display.get_surface()
        assert surface is not None, "MENU graphic not initialized"
        assert self._menu_title_font is not None and self._menu_body_font is not None
        current_skin = self._renderer.current_skin_name if self._renderer else "classic"
        draw_menu(  # G3-5 加 current_skin_name
            surface,
            self._menu_title_font,
            self._menu_body_font,
            self._difficulty,
            high_score=self._high_score,
            current_skin_name=current_skin,
        )
    elif self.screen == AppScreen.PLAYING:
        assert self._renderer is not None
        snap = self.game_state.snapshot()  # R3-11：取一次 snap
        hud = self._build_hud(snap)
        # G3-3：构造 InterpolationState 走平滑插值
        interp = self._interpolation_state(snap)
        self._renderer.render(snap, hud, interp=interp)
    elif self.screen == AppScreen.PAUSED:
        assert self._renderer is not None and self.game_state is not None
        snap = self.game_state.snapshot()
        hud = self._build_hud(snap)
        # PAUSED 态不走插值（保持暂停时定格感——插值让暂停画面看起来"在动"反而误导）
        self._renderer.render(snap, hud)
        surface = pygame.display.get_surface()
        assert surface is not None
        draw_pause_overlay(surface, self._menu_body_font)
    elif self.screen == AppScreen.GAME_OVER:
        surface = pygame.display.get_surface()
        assert surface is not None
        score = self.game_state.snapshot().score if self.game_state else 0
        assert self._menu_title_font is not None and self._menu_body_font is not None
        draw_game_over(
            surface,
            self._menu_title_font,
            self._menu_body_font,
            score,
            high_score=self._high_score,
        )
    pygame.display.flip()
```

### 4.7 初始化（**G3-4 增量 enable_high_dpi 判定**；iter-2 G2-2/P1-1/P1-3 沿用）

```python
def _init_pygame(self) -> None:
    """构造 renderer + HighScoreStore；CJK 字体回退链。

    iter-3 G3-4 增量：
    - 构造 Renderer 时根据 config 类型判定 enable_high_dpi：
      - isinstance(config, AppConfigV3) → enable_high_dpi=config.enable_high_dpi
      - 否则（AppConfig 或其子类无 enable_high_dpi）→ enable_high_dpi=True（默认，NFR-04）
    - iter-2 G2-2/P1-1/P1-3 全量沿用
    """
    # G3-4：构造 Renderer（enable_high_dpi 判定）
    enable_high_dpi = True  # 默认（NFR-04）
    if isinstance(self.config, AppConfigV3):
        enable_high_dpi = self.config.enable_high_dpi
    try:
        self._renderer = Renderer(
            (self.config.window_w, self.config.window_h),
            skin=DEFAULT_SKIN,
            enable_high_dpi=enable_high_dpi,  # G3-4
        )
        self._renderer.init()
    except (RenderError, pygame.error) as e:
        raise GraphicsUnavailableError(str(e)) from e

    # iter-2 G2-2 沿用：HighScoreStore 接入
    if self._storage is None:
        try:
            self._storage = create_storage()
            self._high_score = self._storage.load()
        except (StorageError, OSError) as e:
            raise AppError(f"用户数据目录不可写: {e}") from e

    # iter-2 沿用：CJK 字体回退链
    self._menu_title_font = _load_cjk_font(48, bold=True)
    self._menu_body_font = _load_cjk_font(22)

    self.clock = pygame.time.Clock()
```

### 4.8 状态机图（iter-3 G3-1/2 增量）

```
       ┌────────┐ Enter/空格/未映射键/方向键         ┌──────────┐
       │  MENU  │ ───────────────────────────▶ │ PLAYING  │
       │ (app   │   START (R3-1 屏态兜底)       │ (节拍     │
       │ 自绘)  │                                  │  step)    │
       └────────┘                                  └──────────┘
           ▲                                              │
           │  ESC (GAME_OVER) / Backspace               │ P 键 / UNFOCUS
           │  → BACK_TO_MENU (G2-7)                     │ → toggle_pause
           │                                              ▼
           │              ┌──────────┐  P 键            ┌──────────┐
           └──────────────│ GAME_OVER│ ◀──── toggle_pause ────│ PAUSED  │
              RESTART     │ (app 自绘)│                  │ (app 自绘│
                          │ +最高分行)│                  │  +遮罩)  │
                          └──────────┘                  └──────────┘
                                ▲                              │
                                │ status==OVER (R3-8 自动转)  │ P 键 → toggle_pause
                                │                              │ PAUSED→RUN
                                └──────────────────────────────┘
                                          _tick 检测 status

       MENU 态 ←/→  → SET_SKIN_PREV/NEXT（G3-1）
              → _switch_skin（_skin_index 循环，调 Renderer.set_skin）
              → 当前对局不中断（PLAYING/PAUSED/GAME_OVER 透传为 MOVE_LEFT/RIGHT）

       任意态 VIDEORESIZE → _handle_resize（G3-2）
              → Renderer.handle_resize(w, h)
              → RenderError 兜底（< 最小尺寸）→ stderr 提示 + 维持原尺寸（不中断）

       PLAYING 态 _render → InterpolationState 构造（G3-3）
              → Renderer.render(snap, hud, interp=...)
              → 平滑插值动画（FR-07）

       AppConfigV3 → enable_high_dpi=True → Renderer.enable_high_dpi=True（G3-4）
              → pygame.SCALED 标志 → 高分屏清晰（NFR-04）

       任意态：Q / 窗口关闭 → QUIT  → 主循环 'if QUIT in actions: break'
                            → finally renderer.shutdown()
       PLAYING 态：pygame.key.get_focused() == False → UNFOCUS → toggle_pause
```

### 4.9 menu.py 自绘实现（**G3-5 新增**）

```python
# menu.py — G3-5 新增 current_skin_name 形参；iter-2 G2-6 加 high_score；iter-1 R3-2 沿用 get_surface

def draw_menu(
    surface: pygame.Surface,
    title_font: pygame.font.Font,
    body_font: pygame.font.Font,
    difficulty: Difficulty,
    high_score: int = 0,                  # iter-2 G2-6
    current_skin_name: str = "classic",     # G3-5 新增
) -> None:
    """MENU 态自绘。G3-5：current_skin_name 形参（默认 "classic" 保持向后兼容）。"""
    surface.fill(MENU_BG)

    # 1. 标题（iter-1 沿用）
    title = title_font.render("Snake GUI v2.0.0", True, MENU_TITLE_COLOR)
    surface.blit(title, (surface.get_width() // 2 - title.get_width() // 2, 100))

    # 2. 难度选项（iter-1 沿用）
    lines = [
        ("按 1 键 = 简单", Difficulty.EASY),
        ("按 2 键 = 普通", Difficulty.MEDIUM),
        ("按 3 键 = 困难", Difficulty.HARD),
    ]
    for i, (text, diff) in enumerate(lines):
        color = MENU_DIFFICULTY_HIGHLIGHT if diff == difficulty else MENU_DIFFICULTY_DEFAULT
        surf = body_font.render(text, True, color)
        surface.blit(surf, (surface.get_width() // 2 - surf.get_width() // 2, 220 + i * 36))

    # 3. 当前皮肤行（G3-5 新增）—— 在难度选项与最高分行之间
    skin_line = body_font.render(f"当前皮肤：{current_skin_name}", True, MENU_DIFFICULTY_HIGHLIGHT)
    surface.blit(skin_line, (surface.get_width() // 2 - skin_line.get_width() // 2, 315))

    # 4. 最高分行（iter-2 G2-6 沿用）
    if high_score > 0:
        hs_line = body_font.render(f"最高分：{high_score}", True, MENU_DIFFICULTY_HIGHLIGHT)
        surface.blit(hs_line, (surface.get_width() // 2 - hs_line.get_width() // 2, 340))

    # 5. 提示行（G3-5 新增 ← → 切皮肤提示）
    hint = body_font.render(
        "Enter / 空格 / 其他键 开始（P 暂停 · H 重置最高分 · ← → 切皮肤 · Q 退出）",
        True, MENU_HINT_COLOR,
    )
    surface.blit(hint, (surface.get_width() // 2 - hint.get_width() // 2, 400))

    quit_hint = body_font.render("Q 退出", True, MENU_QUIT_HINT_COLOR)
    surface.blit(quit_hint, (surface.get_width() // 2 - quit_hint.get_width() // 2, 440))


# draw_game_over / draw_pause_overlay 沿用 iter-2 G2-5/6（不增 current_skin_name 形参）
```

### 4.10 实现注意点（**G3 增量**；iter-2 G2-1/2/3/4/5/7 沿用）

1. **无全局变量**：app 状态全部在 `App` 实例字段，UT 可通过构造多个 `App` 实例隔离测试。
2. **pygame 副作用隔离**：`pygame.init()` / `pygame.quit()` 调用次数在 UT 中通过 fake pygame 模块统计。
3. **不直接读 game_state 内部字段**：所有访问走 `snapshot()`；修改走 `set_direction` / `step` / `toggle_pause`；G2-1 PAUSED 态由 `_dispatch_*` 内显式切屏（G3 沿用）。
4. **不直接读 gui-renderer 私有属性**：仅 `Renderer((W,H), skin=DEFAULT_SKIN, enable_high_dpi=...)` 构造 + `init/shutdown` + `render(snap, hud, *, interp)` + `set_skin(name)` + `handle_resize(w, h)` + `skin_names()` / `current_skin_name` / `fps_metric()`；自绘菜单/结束画面/暂停遮罩走 `pygame.display.get_surface()`（R3-2 沿用）。
5. **不引入 `time.sleep`**：所有延迟靠 `clock.tick_busy_loop(fps_cap)` + `_tick_accumulator_ms`。
6. **iter-3 不写任何配置/日志文件**：仅 HighScoreStore.save() 写 highscore.json（用户数据目录，NFR-07）。
7. **退出码约定**：0 正常 / 1 app 异常（含 ConfigError / StorageUnavailableError） / 2 图形环境不可用。
8. **HUD `status_label` 必填**：renderer 第 2 行 `Status: ...` 必读；`_STATUS_LABEL[snap.status]` 在 RUN/PAUSED/OVER 三态均有值。
9. **G3-1 皮肤循环索引**：`_skin_index: int` 在 `[0, len(skin_names))` 内循环；初始化为 0（默认经典）；`Renderer.set_skin(name)` 内部更新 `Renderer._skin` 引用，下一帧 `render` 读 `_skin` 即生效（**对局不中断**）。
10. **G3-2 VIDEORESIZE 兜底**：`RenderError`（< MIN_PLAYABLE_W/H 或类型错误）→ stderr 提示 + 维持当前尺寸（**不抛、不退、不中断游戏**——INV-15）。
11. **G3-3 平滑插值 alpha**：`alpha = 1.0 - (_tick_accumulator_ms % tick_ms) / tick_ms`（已消费时长占整节拍比例）；clip [0, 1]；首帧 `_prev_snap=None` → alpha=1.0（瞬移渲染）；OVER/OVER→GAME_OVER 切换帧 `interp=None`（renderer 内部走瞬移路径）；PAUSED 态不走插值（保持暂停定格感）；吃食节拍 `len(prev_body) != len(cur_body)` → 防御性返回 None（renderer 内部 _grid_distance 兜底）。
12. **G3-4 AppConfigV3 兼容性**：`AppConfig` 实例保持兼容（isinstance(config, AppConfigV3) False → 默认 `enable_high_dpi=True` 由 Renderer 默认值兜底——向后兼容，无破坏）；`AppConfigV3` 子类继承父类 `__post_init__` 校验（不重写，bool 字段无非法值）。
13. **iter-3 不调 `_running`**：G3-1/G3-2/G3-3/G3-4/G3-5 均不修改 `_running` 字段；保留供 iter-4 使用。
14. **G2-R-N6**：`App.__init__` 默认参数 `config: AppConfig = AppConfig()` 在 import 期求值；UT 需不同 config 时显式传 `App(AppConfig(fps_cap=30))` 或 `App(AppConfigV3(enable_high_dpi=False))`。
15. **P0-1 屏态同步方案 A**：`_tick` 内**不**做屏态切换——PAUSED↔PLAYING 切屏由 `_dispatch_*` 内 toggle 后显式赋值（INV-11）。iter-3 沿用。

---

## 5. DFx / 可测试性 / 鲁棒性 / 韧性

### 5.1 可维护性（Maintainability）

- 沿用 iter-1/iter-2 约定：每个公开类/方法有 docstring，标注对应 FR/NFR 编号。
- 不变量在代码中以 `# INV-N` 注释 + UT 用例双标注（iter-3 加 INV-15 缩放不中断 + INV-16 _skin_index 循环合法）。
- 单一职责：`storage.py` 只管 HighScoreStore 包装；`app.py` 仍只管装配；`menu.py` 加 `current_skin_name` 自绘形参（G3-5）；`config.py` 加 `AppConfigV3` 子类（G3-4）。
- 主循环 ≤ 30 行（`run()` + `_run_loop()` + `_drain_events` + `_dispatch` + `_tick`），便于一眼读完逻辑。
- **iter-3 增量入口**仅 4 处：`_switch_skin`（G3-1）/ `_handle_resize`（G3-2）/ `_interpolation_state`（G3-3）/ `AppConfigV3.__init__`（G3-4），**最小侵入**。

### 5.2 可扩展性（Extensibility）

- **皮肤注册表驱动**：gui-renderer iter-3 `SKIN_REGISTRY` 是 skin 切换的真理源；app 仅持 `_skin_index` 索引；iter-4 若加新皮肤只需在 renderer 注册表添加，**app 无需修改**。
- **AppConfigV3 子类化扩展**：iter-4 若加新运行期常量（如 `target_fps`），可继续子类化 `AppConfigV4(AppConfigV3)`，**不破坏 iter-1/2/3 既有 `AppConfig` 兼容性**。
- **G3-3 插值上下文**：`InterpolationState` 是 gui-renderer 公开 API；iter-4 若需更高帧率插值或非线性插值，仅在 renderer 修改插值算法，app 无需修改。
- **G3-2 缩放兜底**：`RenderError` 在 `_handle_resize` 内捕获；iter-4 若加自定义最小尺寸校验逻辑，仅在 renderer 修改，app 仅需保留兜底。

### 5.3 可部署性（Deployability）

- PyInstaller 单文件（沿用 iter-1）：`--onefile --windowed --name snake-gui --collect-submodules game_app --collect-submodules platform_storage`（iter-3 不变）。
- `game_app/` + `platform_storage/` + `gui_renderer/` 单一包目录，PyInstaller 自动发现。
- 无 C 扩展、无平台特定代码（pygame + platform_storage 自身跨平台）。
- 入口无副作用 import：`import game_app` 不开窗、不调 `pygame.init()`、不构造 `HighScoreStore`。

### 5.4 可测试性（Testability）

- **pygame 依赖可桩化**：UT 通过 `monkeypatch` 替换 `game_app.app + game_app.menu + game_app.storage + game_app.input + game_app.fonts + game_app.config` 内部的 pygame + platform_storage 模块为 fake。
- **HighScoreStore 依赖可桩化**：UT 用 `tmp_path` 注入 `path=tmp_path / "highscore.json"`（`create_storage(path)` 支持自定义路径）；或用 `FakeHighScoreStore` 完全替代。
- **`_drain_events` 屏态分发可独立测**：iter-2 沿用 + G3-1 SET_SKIN 屏态分发用 fake `InputAction.SET_SKIN_PREV/NEXT` 注入；G3-2 VIDEORESIZE 用 fake `pygame.event.Event(VIDEORESIZE, w=..., h=...)` 注入。
- **`_dispatch_*` 状态机可枚举**：每态（MENU/PLAYING/PAUSED/GAME_OVER） × 每 action 用 `pytest.mark.parametrize` 枚举（G3-1 SET_SKIN 不进 dispatch，仅 _drain_events 处理）。
- **`_interpolation_state` 可单测**：UT 直接调 `_interpolation_state(snap)`，断言返回的 InterpolationState 字段（alpha / prev_snake_body / prev_food）正确。
- **`_switch_skin` 可单测**：fake `_renderer.skin_names()` + `set_skin()` 注入，断言 `_skin_index` 循环正确 + SkinNotFoundError 兜底。
- **`_handle_resize` 可单测**：fake `event.w/h` + `_renderer.handle_resize` 注入 side_effect=RenderError → 断言 stderr 写入且不抛。
- **`_render` 4 态路径可测**：用 `app_in_playing`/`app_in_paused`/`app_in_game_over`/`app`（MENU）fixture 验证各路径调用对应接口。
- **错误路径可触发**：fake `set_skin.side_effect = SkinNotFoundError(...)` → `_switch_skin` 兜底；fake `handle_resize.side_effect = RenderError(...)` → `_handle_resize` 兜底。

### 5.5 鲁棒性 / 韧性（**G3-2 新增 + iter-2 沿用**）

| 场景 | 处理 |
|------|------|
| 图形环境缺失 | iter-2 沿用：`Renderer.init()` 抛 `RenderError` → `GraphicsUnavailableError` → 退出码 2 |
| 用户数据目录不可写 | iter-2 沿用：`HighScoreStore.__init__` mkdir 失败 → `OSError` → `_init_pygame` 捕获 `(StorageError, OSError)` → 包 `AppError("用户数据目录不可写")` → 退出码 1 |
| 最高分保存失败 | iter-2 沿用：`score_callback` 内 `storage.save` 抛 `StorageError` → 包 `StorageUnavailableError` → 主循环 except AppError → 退出码 1 |
| 同一帧多事件 | iter-2 沿用：`_drain_events` 返 list；主循环按序处理；QUIT 优先 break |
| 反向输入 | iter-2 沿用：透传到 `core.set_direction`；core 内静默忽略 |
| 撞墙/撞身 | iter-2 沿用：`core.step` 返回 `status=OVER`；`_tick` 检测后自动转 `GAME_OVER`（INV-2）+ `self._prev_snap = None`（G3-3） |
| 关窗 | iter-2 沿用：`pygame.QUIT` 事件 → `QUIT` action → 主循环 break → `renderer.shutdown()` |
| 窗口失焦 | iter-2 沿用：`pygame.key.get_focused() == False` + PLAYING 态 → 追加 `UNFOCUS` action → `toggle_pause()` → `screen=PAUSED` |
| 暂停期方向输入 | iter-2 沿用：`_tick` 在 PAUSED 态不进入；`set_direction` 在 PAUSED 态由 core 静默忽略；input.py `_dispatch_paused` 不处理 MOVE_* |
| OVER 态调 toggle_pause | iter-2 沿用：core iter-2 抛 `InvalidStateError`；app 不包装（R3-9） |
| Q/ESC 任意态 | iter-2 沿用：Q → QUIT（主循环 break）；ESC → ESCAPE（GAME_OVER 由 _drain_events 覆盖为 BACK_TO_MENU，MENU 态兜底转 START） |
| 节拍漂移 | iter-2 沿用：`_tick_accumulator_ms` 累加 + while 循环 + 循环内重读 tick_ms（R3-8） |
| 配置非法 | iter-2 沿用：`AppConfig.__post_init__` 抛 `ConfigError`；`main()` 捕获后 stderr + 退出码 1 |
| 中文字体缺失 | iter-2 沿用：`_load_cjk_font` 走 `match_font` 回退链，全失败 → SDL 默认字体 |
| 最高分文件损坏 | iter-2 沿用：`HighScoreStore.load` 自动备份为 `.corrupt-<ts>.json` 后返 0 |
| **皮肤切换失败**（G3-1） | `set_skin` 抛 `SkinNotFoundError`（防御性，理论不可达）→ `_switch_skin` 捕获 stderr 提示 + 维持 `_skin_index` 不变（不抛、不中断） |
| **窗口缩放过小**（G3-2） | `Renderer.handle_resize` 抛 `RenderError`（< MIN_PLAYABLE_W/H）→ `_handle_resize` 捕获 stderr 提示 + 维持当前尺寸（不抛、不中断——**INV-15**） |
| **插值帧吃食/跳变**（G3-3） | `_prev_snap.snake_body` 长度与 `snap.snake_body` 不一致 → `_interpolation_state` 返回 None（renderer 走瞬移渲染）；renderer 内部 `_grid_distance` 兜底 |

### 5.6 错误处理矩阵（iter-3 G3-2 新增 + iter-2 G2-2/G2-R-N5 沿用）

| 错误情形 | 行为 |
|----------|------|
| `Renderer.init()` 失败 | `RenderError` → `GraphicsUnavailableError` → 退出码 2 + shutdown 兜底 |
| `Renderer.__init__` 校验失败 | 同上 |
| `AppConfig(fps_cap=0)` | `ConfigError`（`__post_init__` 校验）→ `main()` 捕获 → 退出码 1 |
| `AppConfig(window_w < min_window_w)` | 同上 |
| `AppConfigV3(enable_high_dpi=...)` 非法 | **理论不可达**（bool 字段无非法值）；防御性 `__post_init__` 不重写（继承父类） |
| HighScoreStore mkdir 失败 | `StorageError` / **`OSError`（G3-R-P2-1 修订：iter-2 §5.6 漏 OSError，iter-3 补正）** → 包 `AppError("用户数据目录不可写")` → 退出码 1 |
| `_dispatch_menu(RESET_HIGHSCORE)` 失败 | `StorageError` → 包 `StorageUnavailableError` → 主循环 except AppError → 退出码 1 |
| `score_callback` 内 `storage.save` 失败 | `StorageError` → 包 `StorageUnavailableError` → 主循环 except AppError → 退出码 1 |
| **皮肤切换失败**（G3-1） | `SkinNotFoundError` → `_switch_skin` 兜底 stderr 提示 + 维持 `_skin_index` 不变（**不抛、不中断游戏**） |
| **窗口缩放过小**（G3-2） | `RenderError` → `_handle_resize` 兜底 stderr 提示 + 维持当前尺寸（**不抛、不中断游戏**） |
| `App.run()` 中 `core` 抛 `InvalidStateError` | iter-2 沿用：理论不可达，不包装；iter-3 真发生 → 视为 bug |
| 未捕获异常 | iter-2 沿用：走解释器默认行为（stderr traceback + 退出码 1） |

---

## 6. UT 框架（FO TDD 依据）

### 6.1 测试组织（见 §4.1 文件树）

### 6.2 桩与夹具（conftest.py，**G3-R-P1-A/B/C 修订**）

```python
# conftest.py — iter-2 fixtures + G3-R-P1-A/B/C 修订
# **G3-R-P1-A 修订**：app/app_in_playing 等 fixture 改为先注入 fake_storage 再 _init_pygame()，
#   配合 _init_pygame 内 `if self._storage is None` 守卫，真实 create_storage 不再触发
# **G3-R-P1-B 修订**：app_with_storage fixture 改 monkeypatch create_storage 返 tmp_path 实例
# **G3-R-P1-C 修订**：app_in_game_over fixture 补 from game_core import GameStatus
import sys
from typing import Optional
from unittest.mock import MagicMock
import pytest


_PYGAME_KEYS = {
    "QUIT": 256, "KEYDOWN": 768, "VIDEORESIZE": 16,  # G3-2 新增 VIDEORESIZE=16
    "K_w": 119, "K_s": 115, "K_a": 97, "K_d": 100,
    "K_UP": 1073741906, "K_DOWN": 1073741905,
    "K_LEFT": 1073741904, "K_RIGHT": 1073741903,
    "K_q": 113, "K_ESCAPE": 27, "K_p": 112, "K_r": 114,
    "K_h": 104, "K_BACKSPACE": 8,
    "K_RETURN": 13, "K_SPACE": 32,
    "K_1": 49, "K_2": 50, "K_3": 51,
}


def _build_fake_pygame() -> MagicMock:
    fake = MagicMock(name="fake_pygame")
    fake.error = RuntimeError
    for k, v in _PYGAME_KEYS.items():
        setattr(fake, k, v)
    fake.display.set_mode.return_value = MagicMock(name="screen")
    fake.display.get_surface.return_value = MagicMock(name="surface")
    fake.display.flip = MagicMock(name="flip")
    fake.display.quit = MagicMock(name="display_quit")
    fake.font.SysFont.return_value = MagicMock(name="sysfont")
    fake.font.Font.return_value = MagicMock(name="font")
    fake.font.match_font.return_value = None
    fake.font.init = MagicMock(name="font_init")
    fake.font.quit = MagicMock(name="font_quit")
    fake.draw.rect = MagicMock(name="draw_rect")
    fake.time.Clock.return_value = MagicMock(name="clock")
    fake.time.get_ticks = MagicMock(return_value=0)
    fake.event.get.return_value = []
    fake.init = MagicMock(name="pygame_init")
    fake.quit = MagicMock(name="pygame_quit")
    fake.key.get_focused.return_value = True
    fake.SRCALPHA = 65536
    return fake


@pytest.fixture
def fake_pygame(monkeypatch):
    """替换 game_app 内部所有 pygame 引用为可编程 fake。"""
    fake = _build_fake_pygame()
    monkeypatch.setitem(sys.modules, "pygame", fake)
    import game_app.input as input_mod
    import game_app.menu as menu_mod
    import game_app.app as app_mod
    import game_app.fonts as fonts_mod
    import game_app.config as config_mod  # G3-R-P2-6 补 config 模块
    monkeypatch.setattr(input_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(menu_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(app_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(fonts_mod, "pygame", fake, raising=False)
    monkeypatch.setattr(config_mod, "pygame", fake, raising=False)  # G3-R-P2-6
    try:
        import gui_renderer.renderer as gui_renderer_mod
        monkeypatch.setattr(gui_renderer_mod, "pygame", fake, raising=False)
    except Exception:
        pass
    return fake


@pytest.fixture
def fake_storage():
    """iter-2 G2-2 沿用：fake HighScoreStore。"""
    storage = MagicMock(name="fake_storage")
    storage.load.return_value = 0
    storage.save = MagicMock(name="fake_save")
    storage.reset = MagicMock(name="fake_reset")
    return storage


@pytest.fixture
def fake_renderer_iter3():
    """G3 新增：fake Renderer 含 iter-3 接口（set_skin/handle_resize/skin_names/current_skin_name/render(interp=)）。"""
    renderer = MagicMock(name="fake_renderer")
    renderer.skin_names.return_value = ("classic", "dark", "colorblind_friendly")
    renderer.current_skin_name = "classic"
    renderer.set_skin = MagicMock(name="set_skin")
    renderer.handle_resize = MagicMock(name="handle_resize")
    renderer.render = MagicMock(name="render")
    renderer.fps_metric = MagicMock(name="fps_metric")
    renderer.cell_size = 24
    renderer.grid_cols = 20
    renderer.grid_rows = 15
    return renderer


@pytest.fixture
def app_uninitialized(fake_pygame):
    """iter-2 沿用：构造 App 不调 _init_pygame；_renderer is None，_storage is None。"""
    from game_app import App
    return App()


@pytest.fixture
def app(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """G3-R-P1-A 修订：先注入 fake_storage + monkeypatch create_storage，再 _init_pygame。

    注入顺序：
    1. monkeypatch create_storage 返 fake_storage（避免真实 IO）
    2. monkeypatch Renderer 构造返 fake_renderer_iter3（避免真实 pygame init）
    3. _init_pygame() 内部：
       - self._renderer = fake_renderer_iter3
       - if self._storage is None: create_storage() → 返 fake_storage（已被 monkeypatch）
       - self._high_score = fake_storage.load() == 0
    """
    from game_app import App
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    return a


@pytest.fixture
def app_in_playing(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """G3-R-P1-A 修订：先注入 fake + monkeypatch，再 _init_pygame + _new_game。"""
    from game_app import App
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from game_core import Difficulty
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    return a


@pytest.fixture
def app_in_paused(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """iter-2 沿用 + G3-R-P1-A 修订。"""
    from game_app import App, InputAction, AppScreen
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from game_core import Difficulty
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    a._dispatch_playing(InputAction.TOGGLE_PAUSE)
    assert a.screen == AppScreen.PAUSED
    return a


@pytest.fixture
def app_in_game_over(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """G3-R-P1-C 修订：fixture 头部显式 from game_core import GameStatus。"""
    import dataclasses
    from game_app import App, AppScreen
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from game_core import Difficulty, GameStatus  # G3-R-P1-C 修订
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    a._difficulty = Difficulty.HARD
    a._new_game(Difficulty.HARD)
    a.game_state = dataclasses.replace(a.game_state, status=GameStatus.OVER)
    a.screen = AppScreen.GAME_OVER
    return a


@pytest.fixture
def app_with_storage(tmp_path, fake_pygame, fake_renderer_iter3, monkeypatch):
    """G3-R-P1-B 修订：monkeypatch create_storage 返 tmp_path 实例（替代 fake）。"""
    from game_app import App
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    from platform_storage import HighScoreStore
    real_storage = HighScoreStore(tmp_path / "highscore.json")
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: real_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App()
    a._init_pygame()
    return a


@pytest.fixture
def app_with_config_v3(fake_pygame, fake_storage, fake_renderer_iter3, monkeypatch):
    """G3 新增：使用 AppConfigV3(enable_high_dpi=True) 构造 App。"""
    from game_app import App, AppConfigV3
    from game_app import storage as storage_mod
    from game_app import app as app_mod
    monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
    monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
    a = App(AppConfigV3(enable_high_dpi=True))
    a._init_pygame()
    return a


class FakeEvent:
    """pygame.event.Event 替身，fake_pygame.event.get 注入用。"""
    __slots__ = ("type", "key", "w", "h")

    def __init__(self, type_: int, key: Optional[int] = None,
                 w: Optional[int] = None, h: Optional[int] = None) -> None:
        self.type = type_
        self.key = key
        self.w = w
        self.h = h


def make_keydown(key: int) -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["KEYDOWN"], key)


def make_quit_event() -> FakeEvent:
    return FakeEvent(_PYGAME_KEYS["QUIT"])


def make_resize_event(w: int, h: int) -> FakeEvent:  # G3-2 新增
    return FakeEvent(_PYGAME_KEYS["VIDEORESIZE"], w=w, h=h)
```

### 6.3 断言规范（沿用 iter-2 + G3 增量）

- **不变量优先**：每个 UT 至少断言一条 INV（1~16）；G3-1 加 INV-16（_skin_index 循环合法）；G3-2 加 INV-15（缩放不中断）。
- **纯函数性质**：调 `_tick` / `_dispatch` / `toggle_pause` / `_switch_skin` / `_handle_resize` / `_interpolation_state` 后断言 `app.game_state` / `app._skin_index` / `app._prev_snap` 已更新。
- **覆盖状态机矩阵**：每态（MENU/PLAYING/PAUSED/GAME_OVER） × 每 action 用 `pytest.mark.parametrize` 枚举；G3-1 SET_SKIN 在 MENU 态单独覆盖（不进 dispatch）。
- **fake_pygame 副作用统计**：`fake.init.call_count` / `fake.quit.call_count` / `fake.event.get.call_count` 用于验证 INV-5 / R3-15 / G3 事件流。
- **fake_renderer_iter3 副作用统计**：`fake_renderer_iter3.set_skin.call_args` 用于验证 G3-1 切皮肤；`fake_renderer_iter3.handle_resize.call_args` 用于验证 G3-2 缩放；`fake_renderer_iter3.render.call_args.kwargs["interp"]` 用于验证 G3-3 插值上下文。
- **退出码断言**：`App().run()` 返 int，对齐 0/1/2 语义。
- **UT 命名**：`test_{屏幕}_{动作}_{期望}`，如 `test_menu_skin_next_increments_index`。

### 6.4 必须覆盖的 UT 用例清单（FO 必写；**G3 标注**）

#### iter-2 沿用（**约 87 条**）

详见 `snake-linux/design/game-app/设计-iter2-r2.md` §6.4；G3 沿用全部 + G3-R 修订（无新增代码级 P0/P1）。

#### G3-1 新增（皮肤切换 UI）

| # | 场景 | 断言 |
|---|------|------|
| **SK-1** | MENU 态 → 键切下一皮肤 | `app._drain_events()` 注入 [SET_SKIN_NEXT] → 调用 `app._switch_skin(SET_SKIN_NEXT)` → `fake_renderer_iter3.set_skin("dark")` 调用 1 次 + `app._skin_index == 1` |
| **SK-2** | MENU 态 ← 键切上一皮肤 | 注入 [SET_SKIN_PREV]（初始 _skin_index=0 → 索引 (0-1)%3 = 2 → "colorblind_friendly"）→ `fake_renderer_iter3.set_skin("colorblind_friendly")` + `app._skin_index == 2` |
| **SK-3** | MENU 态循环边界 | 注入 [SET_SKIN_PREV, SET_SKIN_PREV, SET_SKIN_PREV] → _skin_index 在 [0, 2, 1, 0] 循环 |
| **SK-4** | PLAYING 态 ← 键 → 透传为 MOVE_LEFT | `app_in_playing._drain_events()` 注入 [SET_SKIN_PREV] → actions 含 [MOVE_LEFT]（不调 set_skin；_skin_index 不变） |
| **SK-5** | PLAYING 态 → 键 → 透传为 MOVE_RIGHT | 同 SK-4，反向 |
| **SK-6** | PAUSED 态 ← 键 → 透传为 MOVE_LEFT | 同 SK-4，PAUSED 态 |
| **SK-7** | GAME_OVER 态 ← 键 → 透传为 MOVE_LEFT | 同 SK-4，GAME_OVER 态（不影响对局，FR-10） |
| **SK-8** | SkinNotFoundError 兜底 | `fake_renderer_iter3.set_skin.side_effect = SkinNotFoundError(name="x", available=("classic",))` → `_switch_skin(SET_SKIN_NEXT)` 调用 → stderr 写入 + `app._skin_index` 不变 |
| **SK-9** | 皮肤注册表为空（防御） | `fake_renderer_iter3.skin_names.return_value = ()` → `_switch_skin(SET_SKIN_NEXT)` 调用 → 不调 set_skin + `app._skin_index` 不变 |
| **SK-10** | _render MENU 路径用 current_skin_name | `app._render()` → spy `draw_menu` 调用参数 `current_skin_name == fake_renderer_iter3.current_skin_name` |
| **SK-11** | 切换皮肤后 `_render` 下一帧使用新皮肤 | SK-1 后调 `_render` → spy `draw_menu` 调用参数 `current_skin_name == "dark"`（已切） |

#### G3-2 新增（窗口缩放）

| # | 场景 | 断言 |
|---|------|------|
| **RS-1** | VIDEORESIZE 事件 → handle_resize 调用 | `app._drain_events()` 注入 [VIDEORESIZE(w=1024, h=768)] → `fake_renderer_iter3.handle_resize(1024, 768)` 调用 1 次 + actions 列表不含 RESIZE |
| **RS-2** | 缩放过小 → 兜底 | `fake_renderer_iter3.handle_resize.side_effect = RenderError("尺寸过小")` → `_handle_resize(make_resize_event(100, 100))` 调用 → stderr 写入 + 不抛异常 |
| **RS-3** | PLAYING 态缩放不中断游戏 | `app_in_playing._drain_events()` 注入 [VIDEORESIZE] → actions 列表不含 RESIZE（不入 dispatch）+ handle_resize 调用 + `app.screen == PLAYING` 不变（INV-15） |
| **RS-4** | PAUSED 态缩放不中断 | 同 RS-3，PAUSED 态 |
| **RS-5** | GAME_OVER 态缩放不中断 | 同 RS-3，GAME_OVER 态 |
| **RS-6** | 同一帧多事件：RESIZE + KEYDOWN | 注入 [VIDEORESIZE, KEYDOWN K_q] → handle_resize 调 1 次 + actions 含 [QUIT]（QUIT 优先 break） |
| **RS-7** | 缩放后 _render 不变（_renderer.handle_resize 内部完成重绘） | `app._drain_events()` 注入 [VIDEORESIZE] → 下一帧 `_render` 调用 fake_renderer_iter3.render 与之前一致（缩放由 renderer 内部完成，app 无需重 render） |

#### G3-3 新增（平滑插值动画）

| # | 场景 | 断言 |
|---|------|------|
| **INTERP-1** | 首帧 `_prev_snap=None` → 返回 None | `app._interpolation_state(snap)` 在 `_prev_snap is None` 时返回 None |
| **INTERP-2** | 正常插值 alpha 计算 | 手动设 `_prev_snap = Snapshot(...snake_body=[P(5,5), P(5,6), P(5,7)], food=P(10,10), tick_ms=160)` + `_tick_accumulator_ms=80` + 当前 snap snake_body=[P(6,5), P(5,5), P(5,6)] + tick_ms=160 → `_interpolation_state(snap)` 返回 InterpolationState(alpha=0.5, prev_snake_body=((5,5),(5,6),(5,7)), prev_food=(10,10)) |
| **INTERP-3** | alpha clip [0, 1] | `_tick_accumulator_ms=0` → alpha=1.0（瞬移）；`_tick_accumulator_ms=160` → alpha=0.0（瞬移，下一帧 step 后更新） |
| **INTERP-4** | 吃食节拍防御：`len(prev_body) != len(cur_body)` → 返回 None | `_prev_snap.snake_body` 长度 3 vs 当前 snap.snake_body 长度 4 → 返回 None |
| **INTERP-5** | tick_ms=0 防御 | `_tick_accumulator_ms=0` + `snap.tick_ms=0` → 返回 None |
| **INTERP-6** | _render PLAYING 路径走 interp= | `app_in_playing._render()` → spy `fake_renderer_iter3.render.call_args.kwargs["interp"]` 为 None 或 InterpolationState |
| **INTERP-7** | _render PAUSED 路径 interp=None | `app_in_paused._render()` → spy `fake_renderer_iter3.render.call_args.kwargs["interp"] is None`（PAUSED 不走插值，保持暂停定格感） |
| **INTERP-8** | _render GAME_OVER 路径 interp=None | `app_in_game_over._render()` → spy `fake_renderer_iter3.render.call_args` 不含 interp 或 interp=None |
| **INTERP-9** | _tick OVER 后 `_prev_snap = None` | `app_in_playing._tick(足够 dt_ms 撞墙)` → `app._prev_snap is None` |
| **INTERP-10** | _tick 正常推进后 `_prev_snap` 更新 | `app_in_playing._tick(160)` → `app._prev_snap is not None` + `_prev_snap.snake_body == app.game_state.snapshot().snake_body` |

#### G3-4 新增（AppConfigV3）

| # | 场景 | 断言 |
|---|------|------|
| **V3-1** | `AppConfigV3(enable_high_dpi=True)` 默认构造 | 构造无异常 + `c.enable_high_dpi == True` |
| **V3-2** | `AppConfigV3(enable_high_dpi=False)` 构造 | `c.enable_high_dpi == False` |
| **V3-3** | `AppConfigV3(fps_cap=0)` 抛 ConfigError | 继承父类 `__post_init__` 校验 |
| **V3-4** | `App(AppConfigV3(enable_high_dpi=True))._init_pygame()` 调 Renderer(enable_high_dpi=True) | spy Renderer 构造调用 kwargs `enable_high_dpi == True` |
| **V3-5** | `App(AppConfig(enable_high_dpi=...))` 兼容（AppConfig 无 enable_high_dpi 字段，**注意**：AppConfig 不接受该字段，会报 dataclass 错误；V3-5 应改为 **`App(AppConfig())`** 验证向后兼容：构造无异常 + Renderer 构造 kwargs `enable_high_dpi == True`（默认） | **修订**：`App(AppConfig())` 不传 enable_high_dpi → isinstance False → 兜底 True |
| **V3-6** | `App(AppConfigV3(enable_high_dpi=False))._init_pygame()` 调 Renderer(enable_high_dpi=False) | spy Renderer 构造 kwargs `enable_high_dpi == False` |
| **V3-7** | `AppConfigV3` 字段继承 | `AppConfigV3.window_w == AppConfig().window_w == 640` |

### 6.5 覆盖率目标

- **行覆盖 ≥ 90%**（`app.py` 主循环 / dispatch / `_drain_events` / `_tick` 必须 100%；`input.py` 100%；`menu.py` ≥ 85%；`fonts.py` ≥ 85%；`storage.py` ≥ 90%；`config.py` 100% 含 AppConfigV3）
- **分支覆盖 ≥ 85%**（每屏 dispatch 分支、节拍 while 循环分支、错误处理分支、`_drain_events` 屏态兜底 4 分支 + 失焦检测分支 + VIDEORESIZE 分支 + SET_SKIN 屏态分发分支、`_render` 4 态分支 + interp 构造分支、`_switch_skin` 2 方向分支、`_handle_resize` RenderError 兜底分支）

### 6.6 UT 运行命令

```bash
python3 -m unittest discover -s tests/test_game_app -v
# 或
pytest tests/test_game_app -v --cov=game_app --cov-branch --cov-fail-under=90
```

### 6.7 FO TDD 实施步骤（建议，按 G3 增量分组）

**第一阶段（G3-4 AppConfigV3 子类）**：
1. 写 `test_app_iter3_config_v3.py`（UT V3-1/2/3/4/5/6/7） → 跑（红）→ 写 `config.py` 加 `AppConfigV3`（绿）
2. 改 `app.py.__init__` 加 `_skin_index=0` + `_prev_snap=None`（§1.2） → 跑 `test_app_init.py`（绿）

**第二阶段（G3-1 皮肤切换 UI）**：
3. 写 `test_input_map.py`（UT SK 键映射：K_LEFT → SET_SKIN_PREV / K_RIGHT → SET_SKIN_NEXT）→ 跑（红）→ 改 `input.py` 加 SET_SKIN_PREV/NEXT + _map_event 分支（绿）
4. 写 `test_app_iter3_skin.py`（UT SK-1/2/3/4/5/6/7/8/9/10/11）→ 跑（红）→ 改 `app.py._drain_events` 加 SET_SKIN 屏态分发 + `_switch_skin` 方法（绿）
5. 改 `menu.py.draw_menu` 加 `current_skin_name` 形参（§3.7/§4.9）→ 跑（绿）

**第三阶段（G3-2 窗口缩放）**：
6. 写 `test_input_map.py`（UT VIDEORESIZE → RESIZE 映射）→ 跑（红）→ 改 `input.py._map_event` 加 VIDEORESIZE 分支（绿）
7. 写 `test_app_iter3_resize.py`（UT RS-1/2/3/4/5/6/7）→ 跑（红）→ 改 `app.py._drain_events` 加 RESIZE 同步处理 + `_handle_resize` 方法（绿）

**第四阶段（G3-3 平滑插值动画）**：
8. 写 `test_app_iter3_interp.py`（UT INTERP-1/2/3/4/5）→ 跑（红）→ 写 `_interpolation_state` 方法（绿）
9. 改 `app.py._tick` step 后维护 `_prev_snap`（§4.5）→ 跑 UT INTERP-9/10（绿）
10. 改 `app.py._render` PLAYING 路径构造 `interp=...`（§4.6）→ 跑 UT INTERP-6（绿）

**第五阶段（端到端 + G3-R 修订）**：
11. 改 `conftest.py` 注入 fake_storage + fake_renderer_iter3 + monkeypatch create_storage/Renderer（§6.2）→ 跑全部 UT（绿）
12. 写 `test_app_iter3_e2e.py`：MENU 启动 → ←/→ 切皮肤 → START → 吃食 → P 暂停 → 拖拽窗口 → P 继续 → 撞墙 → GAME_OVER → ESC 返 MENU → Q 退出（端到端覆盖 SK/RS/INTERP/V3 全链路）
13. 跑覆盖率报告，确保 ≥ 90% 行 / ≥ 85% 分支

---

## 附录 A：迭代 3 → 迭代 4 增量接口预告（仅供 FO 留扩展点，不在本次实现）

### A.1 迭代 4 增量

- **PyInstaller 三平台打包**：Linux 构建机打 Linux ELF；Windows 构建机打 .exe；macOS 构建机打 .app（Intel + Apple Silicon 双架构）；`--onefile --windowed --name snake-gui --collect-submodules game_app --collect-submodules platform_storage --collect-submodules gui_renderer`
- **错误提示完善**：捕获所有 `AppError` 子类，按错误类型给可读建议（缺 SDL 库 / 驱动版本 / HiDPI 缩放提示）
- **性能 profile 脚本**：`scripts/bench_fps.py` 实测 NFR-01（≥60FPS）/ NFR-02（内存 ≤300MB）；`Renderer.fps_metric()` 已在 iter-1 暴露，iter-4 落 profile 脚本调用
- **用户指南** `USER_GUIDE.md`：下载与运行 / 键位表 / 难度 / 皮肤 / 暂停 / 平台差异 / 已知限制（FR-16）
- **发布物清单**：`dist/snake-gui{suffix}` + `SHA256SUMS` + `RELEASE_NOTES.md`
- **`_init_pygame` 加 SDL 驱动版本检查 + 友好降级**
- **`_load_cjk_font` 改为打包内置字体**（避免 Linux 字体版本差异）
- **`AppConfigV4` 子类**（iter-4）：继承 AppConfigV3 加 `target_fps: int = 60` / `window_w/h` 由 640×480 默认改为"上次窗口大小"（读 platform-storage）等扩展点

### A.2 接口扩展原则

- 默认参数 + 新增方法，**不破坏迭代 1/2/3 既有签名**
- `App` 公开方法（`run()` / `__init__()`）签名迭代 1~4 不变
- `AppConfig` 字段迭代 1 冻结默认值；迭代 3 通过子类化 `AppConfigV3` 扩展（不修改 `AppConfig`）；iter-4 继续子类化 `AppConfigV4`
- **`_running` 字段供 iter-4 扩展**：iter-3 不读，保留

---

## 附录 B：依赖与版本（G3-6 增量）

| 依赖 | 版本 | 约束来源 / 当前状态 |
|------|------|---------------------|
| Python | ≥3.8, <4 | 架构 §代码风格约定 |
| pygame | ≥2.0,<3 | gui-renderer 迭代 3 锁定（`code/gui-renderer/iter-3/gui_renderer/constants.py`） |
| **game-core** | **迭代 2** 接口为准 — 现状 `code/game-core/iter-2/game_core/` **it_passed，契约已锁定** | 引用接口：`Snapshot(snake_body, food, score, length, status, difficulty, tick_ms)` / `set_direction` / `step` / `snapshot` / `set_score_callback`；iter-3 不调用新接口 |
| **gui-renderer** | **迭代 3** `code/gui-renderer/iter-3/gui_renderer/` **it_passed，契约已锁定** | iter-3 game-app 调用：`Renderer((W,H), *, skin=DEFAULT_SKIN, enable_high_dpi=...)` 构造 + `init()` + `shutdown()` + `render(snap, hud, *, interp=None)`（G3-3 iterp 可选）+ `set_skin(name)`（G3-1）+ `handle_resize(w, h)`（G3-2）+ `skin_names()` + `current_skin_name` + `fps_metric()`；不调用 `_screen`/`_skin`/`_cell_size` 等私有 |
| platform-storage | 迭代 2 接入 | iter-3 沿用不调用 |
| PyInstaller | ≥5.0（迭代 4） | 架构 §技术选型 |

---

## 附录 C：与 v1 终端版差异（iter-3 增量 + iter-2 沿用）

| 项 | v1 终端版 | v2 game-app iter-3 |
|----|----------|--------------------|
| 主循环 | curses `getch` + `nodelay` 轮询 | pygame event pump + `clock.tick_busy_loop` |
| 输入缓冲 | 单字符 WASD 直接生效 | 事件队列 + InputAction 归一化 + R3-1 屏态兜底 |
| 节拍控制 | `curses.napms(tick_ms)` | `_tick_accumulator_ms` 累加 + while 追跑 + **循环内重读 tick_ms**（R3-8） |
| 状态机 | 仅 run/over | MENU / PLAYING / PAUSED / GAME_OVER |
| 难度切换 | 固定 160ms | 三档菜单选 + 游戏中不可改（FR-05） |
| 错误提示 | 终端字符 + 退出码 | pygame 异常包装 + 人类可读 stderr（NFR-03） |
| 退出 | main 返 0 | main 返 0/1/2 |
| 持久化 | 无 | iter-2 接入 HighScoreStore（FR-13） |
| 菜单/结束画面 | n/a | app 自绘（pygame.font + pygame.draw），走 `pygame.display.get_surface()` 不读 renderer 私有（R3-2） |
| **皮肤系统**（FR-10，iter-3 新增） | n/a | **3 套皮肤（经典/深色/色盲友好）+ ←/→ 在 MENU 态切 + 游戏中对局不中断 + SkinNotFoundError 兜底不中断** |
| **窗口缩放**（FR-09，iter-3 新增） | n/a | **pygame.VIDEORESIZE 事件 → Renderer.handle_resize + RenderError 兜底不中断** |
| **平滑动画**（FR-07，iter-3 新增） | n/a | **App 维护 _prev_snap + _interpolation_state 构造 InterpolationState(alpha, prev_snake_body, prev_food) → Renderer.render(interp=...)** |
| **高分屏清晰**（NFR-04，iter-3 新增） | n/a | **AppConfigV3 子类 + enable_high_dpi=True → pygame.SCALED 标志** |
| 窗口管理 | n/a | `Renderer.init()` 独占 set_mode（窗口职责统一） |
| 字体 | n/a | CJK 字体回退链（R3-12） |

---

## 附录 D：SE 评审 P0/P1/P2 修订对照（iter-2 r2 → iter-3 增量 + G3-R 消化）

| SE 评审 iter-2 r2 | 问题 | iter-3 修订 | 章节 |
|------------------|------|-------------|------|
| **G3-R-P1-A** | `app` fixture 改造为调 `_init_pygame` 后注入 fake，破坏 iter-1 既有 UT 轻量语义 + 真实 create_storage 触发 | **彻底修正**：fixture 改为先 `monkeypatch create_storage` + `monkeypatch Renderer` 再 `_init_pygame()`，**真实 IO 彻底断绝**；同步 fake_storage + fake_renderer_iter3 双桩 | §6.2 |
| **G3-R-P1-B** | `app_with_storage` fixture 先 `_init_pygame` 后注入 fake，触碰真实用户目录 | **彻底修正**：monkeypatch `game_app.storage.create_storage` 返 tmp_path 实例（与 P1-A 一致） | §6.2 |
| **G3-R-P1-C** | `app_in_game_over` fixture 缺 `GameStatus` 导入 | **补 `from game_core import GameStatus`**（与 iter-2 沿用一致） | §6.2 |
| **G3-R-P1-D** | P-8 子串断言与 §4.5 注释直接冲突 | **改为 AST 节点级断言**（ast.parse + 遍历 If/elif 节点） | §6.4 |
| **G3-R-P1-E** | §6.7 步骤 7 / §4.10 注意点 3 残留方案 B 表述 | **iter-3 §6.7 / §4.10 全面以方案 A 权威表述**；FO 步骤描述不引入"自动转屏"残语 | §4.5 §4.10 §6.7 |
| G3-R-P2-1 | §5.6 错误矩阵 HighScoreStore mkdir 失败漏 OSError | **iter-3 §5.6 同步补 OSError** | §5.6 |
| G3-R-P2-2 | §5.5 鲁棒性表 Q/ESC 任意态行未按 P1-2 修订改写 | **iter-3 §5.5 同步沿用 iter-2 P1-2 修订 + 新增 SkinNotFoundError 不中断游戏一行** | §5.5 |
| G3-R-P2-3 | §3.7 draw_pause_overlay docstring 与 §4.8 修订矛盾 | **iter-3 沿用 iter-2 修订**（docstring 与实现对齐） | §3.7 |
| G3-R-P2-4 | 模块级常量 `_PAUSE_KEY` 等定义后未被 `_map_event` 引用 | **iter-3 §4.3 重写时仅保留必要的 frozenset，删除文档中"模块级常量定义后未引用"的描述** | §4.3 |
| G3-R-P2-5 | §3.8 `translate_storage_error` 死函数 | **iter-3 §3.8 删除该函数，仅保留 `create_storage(path)`** | §3.8 |
| G3-R-P2-6 | fake_pygame 替换列表漏 fonts 模块 | **iter-3 §6.2 补 fonts + config 模块替换**（G3-R-P2-6 修订） | §6.2 |
| G3-R-P2-7 | 测试事件构造与 iter-1 FakeEvent/make_keydown 不一致 | **iter-3 §6.2 沿用 iter-1 FakeEvent/make_keydown/make_resize_event 辅助类** | §6.2 §6.4 |
| G3-R-P2-8 | §6.7 步骤 1 引用 `test_storage.py` 与实际文件名不符 | **iter-3 §6.7 改为引用 `test_app_iter2_storage.py`（iter-2 沿用）** | §6.7 |
| G3-R-P2-9 | H-1~H-4 断言实现方式（spy surface.blit 含文本）不可行 | **iter-3 §6.4 沿用 iter-2 修订：`font.render.call_args[0][0] == "最高分：100"`** | §6.4 |
| G3-R-P2-10 | §3.4 vs §4.4 `_dispatch_playing` 双版本不一致 | **iter-3 §3.4 仅 docstring 引用 §4.4（与 iter-2 模式一致）** | §3.4 §4.4 |
| G3-R-P2-11 | §4.7 声称已记 platform-storage issue 但 issue 未开 | **iter-3 §附录 E 显式标记 issue 未开（需 MDE 后续开）**；本轮不阻塞 | §附录 E |
| G3-R-P2-12 | §4.4 `_dispatch_menu` 注释矛盾（RESET_HIGHSCORE 在保留键内不进 dispatch） | **iter-3 §4.4 注释补正：MENU 态 MOVE_* 在 _drain_events 已转 START 不会进 dispatch；TOGGLE_PAUSE/RESTART/RESET_HIGHSCORE 在 _MENU_RESERVED_ACTIONS 内会进 dispatch 但被显式忽略；**新增**：G3-1 SET_SKIN_PREV/NEXT 在 _drain_events 内按屏态分发不进 _MENU_RESERVED_ACTIONS** | §4.4 |
| G3-R-P2-13 | P-4 断言描述"由 core iter-2 静默忽略保证"不准确 | **iter-3 §6.4 沿用 iter-2 修订**：改述为"app 层 `_dispatch_paused` 不处理 MOVE_*" | §6.4 |

### iter-2 r2 → iter-3 r1 累计修订一览

- iter-2 r2 SE 评审 PASS（2×P0 + 3×P1 + 7×P2 + 6×G2-R-N 已全部消化落地）
- iter-3 增量：**8×G3（G3-1/2/3/4/5/6/7/8 应实现 + 文档）+ 5×G3-R-P1（A/B/C/D/E 不阻塞 PASS 但 FO 落地必须修订）+ 13×G3-R-P2（文档/UT 级，不阻塞）**
- **iter-3 r1（本版）**：全部给出**全文一致**修订 + 依赖契约实核 + iter-2 r2 全部沿用

---

## 附录 E：已知 issue（iter-3 遗留，不阻塞 SE）

- **issue-001（platform-storage iter-2）**：`HighScoreStore.__init__` mkdir 失败抛**裸 OSError**，模块 docstring 声称"__init__ mkdir 失败抛 StorageError" 与实核代码不符；app 侧捕获 `(StorageError, OSError)` 双类型已兜住，但 platform-storage 内部应统一为 StorageError（G2-R-P2-11 修订要求，本轮未实际开 issue，由 MDE 后续开）
- **issue-002（gui-renderer iter-3 修订 P2-1 同步）**：`InterpolationState.prev_food=None` 语义为"吃食节拍食物瞬移"——r3 P2-1 已修订；app 侧 `_interpolation_state` 防御性返回 None（长度不一致）+ renderer 内部 `_grid_distance` 兜底，双重防御到位（本轮无需开 issue）

---

## 附录 F：依赖契约实核（对照锁定代码）

| 设计引用 | 实核结果（基于 `code/gui-renderer/iter-3/gui_renderer/`） |
|----------|----------|
| `Renderer((W,H), *, skin=None, vsync=True, cell_size=..., grid_cols=..., grid_rows=..., enable_high_dpi=True)` 构造 | ✅ `renderer.py` 第 118-148 行签名一致；iter-3 game-app 传 `enable_high_dpi`（G3-4 判定 isinstance AppConfigV3） |
| `init()` 建屏（`pygame.SCALED` 标志） | ✅ `renderer.py` 第 205-225 行；`enable_high_dpi=True` 时 `flags |= getattr(pygame, "SCALED", 0)`（pygame 1.x getattr 防御降级） |
| `render(snap, hud, *, interp=None)` | ✅ `renderer.py` 第 303+ 行；`interp` 非 None 且 `alpha<1.0` 时按 `_interpolate_position` 插值绘制；`interp=None` 或 `alpha>=1.0` 走瞬移渲染（向后兼容 iter-1/2） |
| `set_skin(name)` 不在 SKIN_REGISTRY 抛 SkinNotFoundError | ✅ `renderer.py` 第 241-253 行；`SkinNotFoundError(name=name, available=SKIN_REGISTRY.keys())` 携带可用列表（r3 P3-1 修订） |
| `handle_resize(w, h)` < MIN_PLAYABLE_W/H 抛 RenderError | ✅ `renderer.py` 第 255-290 行；MIN_PLAYABLE_W = `GRID_COLS * CELL_SIZE_MIN + 2 * PLAYFIELD_X = 20*8 + 32 = 192`；MIN_PLAYABLE_H = `GRID_ROWS * CELL_SIZE_MIN + PLAYFIELD_Y + PLAYFIELD_X = 15*8 + 96 + 16 = 232` |
| `skin_names()` 返注册表 key tuple | ✅ `renderer.py` 第 199-203 行；`tuple(SKIN_REGISTRY.keys())` |
| `current_skin_name` 属性 | ✅ `renderer.py` 第 195-197 行；`self._skin.name` |
| `InterpolationState(alpha, prev_snake_body, prev_food=None)` | ✅ `types.py` 第 101-114 行；frozen dataclass，prev_food=None 语义为"吃食节拍食物瞬移"（r3 P2-1 修订） |
| `SKIN_REGISTRY` = {"classic": DEFAULT_SKIN, "dark": DARK_SKIN, "colorblind_friendly": COLORBLIND_FRIENDLY_SKIN} | ✅ `constants.py` 第 90-95 行；3 套皮肤；色盲方案叠加形状/纹理（food_pattern="checkered" + snake_pattern="striped"） |
| `HudData(score, high_score, length, difficulty_label, status_label)` 5 字段 | ✅ `types.py` 第 60-69 行（沿用 iter-1/2） |
| `enable_high_dpi=True` 默认 | ✅ `renderer.py` 第 127 行；`enable_high_dpi: bool = True` |
| `DEFAULT_SKIN` / `DARK_SKIN` / `COLORBLIND_FRIENDLY_SKIN` / `RenderError` / `SkinNotFoundError` 导出 | ✅ `__init__.py` 全量 re-export |

---

> **本修订版提交 SE 复审前自查**：
> - [x] **G3-1** 皮肤切换 UI（MENU 态 ←/→ 切皮肤 + 游戏中对局不中断 + SkinNotFoundError 兜底）；`_skin_index` 循环索引 + `_switch_skin` 方法；MENU 自绘加 `current_skin_name`
> - [x] **G3-2** 窗口等比缩放（VIDEORESIZE → handle_resize + RenderError 兜底不中断）；`_handle_resize` 方法；任意态可缩放
> - [x] **G3-3** 平滑插值动画（`_prev_snap` 字段 + `_interpolation_state` 构造 InterpolationState + alpha 计算）；`_render` PLAYING 路径走 interp；`_tick` step 后维护 `_prev_snap`；OVER 后 `_prev_snap=None`
> - [x] **G3-4** AppConfigV3 子类（`enable_high_dpi=True`）；`App.__init__` 用 isinstance 判定并传入 Renderer；iter-2 `AppConfig` 向后兼容
> - [x] **G3-5** MENU 自绘加 `current_skin_name` 形参；提示行加 ← → 切皮肤提示
> - [x] **G3-R-P1-A/B/C/D/E** fixture 注入顺序彻底修正 + GameStatus 导入补 + AST 断言改 + 方案 A 表述统一
> - [x] **G3-R-P2-1~13** 文档/UT 级修订全部消化
> - [x] 依赖契约逐条实核通过（基于锁定代码）
> - [x] 沿用 iter-2 r2 全部修订（R3-1/2/4/5/7/8/9/10/11/12/14/15 + G2-1/2/3/4/5/6/7 + P0-1/P0-2/P1-1/P1-2/P1-3）
> - [x] iter-3 文件组织不新建 iter-3 代码目录（同 v2.0.0 一个发布单元）
> - [x] 跨迭代复用：主循环 ≤ 30 行 / 单一职责 / 4 处增量入口（G3-1/2/3/4），最小侵入