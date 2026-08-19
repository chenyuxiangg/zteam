# 功能模块设计评审意见：gui-renderer（snake-linux v2.0.0 迭代 1）r1

> SE 评审 · 依据：模块设计 `snake-linux/design/gui-renderer/设计-r1.md` + 架构设计 `snake-linux/arch/v2.0.0/架构设计.md` + 功能模块分工表 + 需求规格 `snake-linux/analysis/snake-gui-r1.md`（approved）+ game-core 已落地代码 `snake-linux/code/game-core/iter-1/`（Snapshot 契约实核）
> 评审日期：2026-08-14

## 0. 评审结论

- **结论：PASS**
- 一句话理由：架构遵循性（依赖方向/数据流/迭代边界）全绿，与 game-core 实际 Snapshot 契约逐字段核对一致；可落地性优秀（39 条 UT 用例 + fake_pygame headless 方案 + 九步 TDD 步骤，FO 可无歧义开工）。发现 3 项 P2 应修订（含 1 项架构接口同步）与 5 项 P3 建议，均不阻塞本轮 PASS。

## 1. 架构符合性核对（接口 / 数据流 / 模块间契约）

| 架构契约（设计期定义） | 设计落点 | 结果 |
|---|---|---|
| 模块类型：中间件，依赖 game-core | §0 中间件/依赖 game-core/被 game-app 依赖 | ✅ |
| 迭代排期：迭代 1, 3（分工表） | §0 迭代 1 = 基础渲染闭环；FR-07/08/09/10 明确放迭代 3，迭代 3 扩展点只预告不实装 | ✅ |
| 迭代 1 范围 = 基础渲染（蛇/食物/背景/HUD 静态绘制） | §0 出口清单 6 项 ✅ 对齐（窗口创建/蛇/食物/背景/HUD/单皮肤） | ✅ |
| `Renderer(skin_name)` 构造 + `render(snapshot)` | 偏离：`Renderer(window_size, skin=None)` + `render(snapshot, hud)` —— **见 P2-1 架构接口同步** | ⚠️ |
| `set_skin(name)` / `handle_resize(w, h)` | 迭代 3 扩展点预告（§9 附录），迭代 1 不实装，签名保留 | ✅ |
| `fps_metric()` 帧率统计（P95 帧时间） | §1.5/§3.1：FpsMetric（P95 + FPS + 120 样本 deque），samples<20 降级 mean | ✅ |
| 皮肤注册表 ≥3 套（经典/深色/色盲友好） | Skin dataclass 完整设计；迭代 1 仅 DEFAULT_SKIN；迭代 3 SkinRegistry 预告 | ✅ |
| 数据流：core snapshot → renderer 只读 | §2.1：renderer 只读 snapshot 不可变视图，不感知 core 可变状态；不访问 platform-storage，high_score 由 game-app 注入 | ✅ |
| 坐标约定：Point(x,y) y 向下，0,0 左上 | §4.5 grid_to_pixel 语义一致；渲染侧独立 Color/Rect 不复用 game-core Point（避免隐式耦合，合理） | ✅ |
| 语法兼容 Python 3.8 | **冲突：架构 §代码风格「不用 dataclass」vs 设计大量 @dataclass(frozen=True)** —— game-core 已落地代码同样全量用 dataclass 且已过评审，见 P2-3 | ⚠️ |
| 无网络（NFR-06） | §5.7 不 import socket/urllib/http/requests + grep 校验 | ✅ |
| 无音效（R-04） | §0 明确不引入音效 | ✅ |
| NFR-05 核心可脱离 GUI 测试 | §5.1 构造期不调 pygame.init、pygame 走模块顶层 import 可 monkeypatch | ✅ |
| NFR-01 帧率 ≥60FPS / P95 ≤25ms 验证 | fps_metric() 提供 P95 帧时间，§6 资源评估富余 16× | ✅ |
| NFR-04 高分屏清晰 | §5.3/§6：pygame 2.x SDL 自动 HiDPI，迭代 1 验证 | ✅ |

### 1.1 与 game-core 实际契约核对（代码实核，非纸面对纸面）

| 设计引用 | game-core 落地（state.py / types.py） | 结果 |
|---|---|---|
| `snapshot.snake_body`（Tuple[Point,...]） | Snapshot.snake_body 同签名 | ✅ |
| `snapshot.food` | Snapshot.food: Point | ✅ |
| `snapshot.score` / `snapshot.length` | 同字段存在 | ✅ |
| `snapshot.status.name` → "RUN"/"PAUSED"/"OVER" | GameStatus 枚举 name 一致（PAUSED 迭代 1 占位） | ✅ |
| `snapshot.difficulty.name` → "EASY"/"MEDIUM"/"HARD" | Difficulty 枚举 name 一致 | ✅ |
| `snapshot.tick_ms`（fps 对照） | Snapshot 含 tick_ms（迭代 2 speed_curve 扩展点） | ✅ |
| HUD 五行（score/high/length/difficulty/status） | 全部字段可自 snapshot + 注入取得 | ✅ |

## 2. 可落地性（FO 可否据其 TDD）

- **headless 可测性方案成立**：fake_pygame（§7.3 完整模板：display/draw/font/time/surface 全 fake）+ `monkeypatch.setattr(renderer, "pygame", FakePygame)` 替换模块顶层 import；构造期不调 pygame.init() → UT 可在 CI 容器零显示器跑通。核心风险点（真实 set_mode 失败）已被设计规避 ✅
- **UT 框架完备**：test_types 8 + test_constants 5 + test_renderer_init 6 + test_renderer_render 10 + test_renderer_fps 5 + test_renderer_lifecycle 5 = **39 条必写用例**；覆盖率目标 ≥90%（render 主体 ≥95%）；TDD 九步顺序合理（types→constants→errors→init→lifecycle→render 骨架→HUD→fps）✅
- **接口签名/语义/异常完整**：§3.1 含 docstring 语义、§2.2 异常矩阵（RenderError/SkinNotFoundError）、§5.5 鲁棒性 7 场景 ✅
- **模块边界清晰**：不 import platform-storage（§1.4/§5.4）；不 import game_core.types.Point（§4.5 避免循环依赖）；与 game-app 对接契约 §8 有伪代码 ✅
- **受 P2-A/P2-B/P2-C 轻微影响**（见 §3）：均为文档自洽/登记类问题，不阻塞 FO 开工主流程。

## 3. 问题清单

### P2（应修订，不阻塞 PASS）

**P2-1 架构接口签名偏离，需架构文档同步（SE 侧）**
- 架构接口清单定义 `Renderer(skin_name)` / `render(snapshot)`；设计改为 `Renderer(window_size, skin=None)` / `render(snapshot, hud)`。
- **偏离有理且必要**：架构 `render(snapshot)` 无法满足 FR-08「HUD 显示最高分」——snapshot 不含 high_score（最高分在 platform-storage），架构数据流也未给 renderer 提供 high_score 入口。设计的 `render(snapshot, hud)` 把 high_score 归入 HudData 由 game-app 注入，是正确补全。
- **处置**：本评审 PASS 以设计为准；建议 SE 在架构文档接口清单同步修订（`render(snapshot, hud)` + 构造注入 window_size），避免 code 检视时以旧架构为准产生二次争议。skin 参数形态（对象 vs 名字）同理随架构同步。

**P2-2 窗口尺寸常量自相矛盾（640×480 vs 512×472）**
- §1.3 常量表：`WINDOW_WIDTH = 640, WINDOW_HEIGHT = 480`；同节「不变量」算式：`WINDOW_WIDTH = 16 + 20*24 + 16 = 512`、`WINDOW_HEIGHT = 80 + 16 + 15*24 + 16 = 472`——两处数值不一致（640≠512、480≠472），且 §1.3 又允许 FO「微调后登记」，三处表述冲突。
- **修改点**：明确窗口尺寸 = 游戏区 + 边距的**唯一**公式与最终常量（建议 512×472 或给出 640×480 的构成分解），删除「可微调」的模糊授权；§7.5 断言 4/5 的几何自洽用例依赖此定值。

**P2-3 架构「不用 dataclass」约定与设计/已落地代码冲突**
- 架构 §代码风格约定「不用 dataclass」；但设计 §1.1/1.2/1.4/1.5 全量使用 `@dataclass(frozen=True)`，**且 game-core 已落地代码（types.py 的 Point/Snapshot/Snake/Food、state.py 的 GameState）同样全量 dataclass 并已过 code 评审**——架构该条约定事实已被推翻。
- dataclass 是 Python 3.7+ 标准库特性，3.8 完全支持，不属「3.9+ 新语法」；架构本意应是禁 3.9+ 特性（PEP 604 等）。
- **修改点**：架构 §代码风格「不用 dataclass」改为「dataclass 可用（3.8 支持）；禁 3.9+ 新语法（PEP 604 联合类型/内置泛型下标等）」；设计无需改动，与 game-core 实践保持一致。

### P3（建议，顺手修订）

**P3-A §4.5 `grid_to_pixel(self, cell: Point)` 与「不 import Point」矛盾**
- 签名注解写 `Point` 但同节声明「不显式 import game_core.types.Point」。类型标注用了 Point 就必须有来源（除非字符串注解 + TYPE_CHECKING，设计未说明）。
- 修改点：注解改 `Tuple[int, int]`（即 `(x, y)`），正文已说明调用方显式拆包——语义一致且无 import 矛盾。

**P3-B `Rect` 类型迭代 1 无消费点**
- §1.1 定义 `Rect`（「用于 HUD 区域与绘制原语」），但 §4.4 绘制流程全部用裸 tuple `(px, py, CELL_SIZE-1, CELL_SIZE-1)`，HUD 布局也用常量——Rect 在本迭代无任何使用点，属死类型（且导出在 `__init__.py`）。
- 修改点：标注「迭代 3 预留」或给出迭代 1 的消费点（如 HUD 文本定位）。

**P3-C `__enter__` 是否自动调 `init()` 语义未定**
- §3.1 说「init 拆到 __enter__ 或显式 init()」，§4.3 示例 `with Renderer((640,480)) as r:` 后直接 render（暗示 __enter__ 调 init）；§7.3 fixture 却是 `r = Renderer(...); r.init()`（显式调，未用 with）。两处模式并存。
- 修改点：明确 __enter__ 语义 = 调 init()（或明确「调用方须先 init」），并补一条 lifecycle UT（with 进入后可直接 render）。

**P3-D renderer 测试如何 import game_core 未说明**
- §7.4 允许 UT 直接构造 Snapshot（game-core 类型），但 code 目录为 `code/game-core/iter-1/` 与 `code/gui-renderer/` 平级，pytest 运行时 sys.path 如何找到 game_core 未交代。
- 修改点：§7.1 conftest.py 注明 `sys.path.insert(0, 相对 game-core 路径)` 或顶层 pytest.ini pythonpath 配置。

**P3-E test_renderer_render 蛇身断言与食物绘制调用叠加关系未说明**
- 用例 2「蛇身长度 3 → draw.rect 被调用 3 次」、用例 4「食物 → draw.rect 1 次 + outline 1 次」——但一次 render 同时画蛇+食物，draw.rect 实际调用总数 = 3+1+1 = 5 次；用例 2/3 若断言「总调用数」会与用例 4 冲突，若断言「蛇相关子集」需说明过滤口径（按颜色？）。
- 修改点：明确断言口径（建议按颜色过滤蛇身 rect，或合并用例给出总数断言），避免 FO 写用例时自相矛盾。

## 4. 结论与后续

- **PASS**（阻塞级 0 项；架构符合性 14 项中 12 项全绿 + 2 项偏离均属「设计修复架构缺陷/实践推翻过时约定」且处置明确；可落地性受 P2-2 轻微影响但不阻塞）。
- 后续要求：
  1. **P2-1**：SE 同步修订架构文档接口清单（`render(snapshot, hud)` / 构造注入 window_size），随本评审结论一并落实；
  2. **P2-2**：MDE 修订窗口尺寸唯一公式与定值（FO 开工前）;
  3. **P2-3**：SE 修订架构 §代码风格 dataclass 条款（随 P2-1 同批）；
  4. P3-A~E 由 MDE 顺手修订；
  5. 本意见归档 `review/design/gui-renderer/iter-1/`，code 阶段检视（模块间接口/数据流视角）以此设计为基线。
