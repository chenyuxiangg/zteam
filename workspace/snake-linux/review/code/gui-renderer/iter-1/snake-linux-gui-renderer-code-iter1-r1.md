# 代码检视意见：gui-renderer（snake-linux v2.0.0 迭代 1）r1

> MDE 检视（模块内实现视角）· 依据：模块设计 `snake-linux/design/gui-renderer/设计-r1.md` + 设计评审意见 `snake-linux/review/design/gui-renderer/iter-1/snake-linux-gui-renderer-design-iter1-r1.md`（PASS）+ game-core 已 it_passed 代码
> 检视日期：2026-08-14

## 0. 检视结论

- **结论：PASS**
- 一句话理由：实现与设计逐字段一致（接口/数据结构/绘制流程/帧率采样/鲁棒性矩阵全绿）；53 条 UT 全绿 + 覆盖率 100%（远超设计 §7.2 ≥90% 目标）；fake_pygame headless 方案生效。发现 2 项 P3 建议（非阻塞），0 项阻塞级问题。

## 1. 检视范围

```
workspace/snake-linux/code/gui-renderer/iter-1/
├── gui_renderer/
│   ├── __init__.py           (35 行)
│   ├── constants.py          (60 行)
│   ├── errors.py             (25 行)
│   ├── types.py              (75 行)
│   └── renderer.py           (200 行)
├── tests/
│   ├── conftest.py           (130 行，fake_pygame 完整桩)
│   ├── test_constants.py     (5 用例)
│   ├── test_types.py         (12 用例)
│   ├── test_renderer_init.py (14 用例)
│   ├── test_renderer_render.py (10 用例)
│   ├── test_renderer_fps.py  (8 用例)
│   └── test_renderer_lifecycle.py (6 用例)
└── README.md
```

合计 53 测试用例（设计 §7.6 必含 39 条 + 实际增补 14 条：异常场景 5 条 + FpsMetric 边界 4 条 + Init 边界 5 条）。

## 2. 检视清单 4 项核对

### 清单 1 — 实现与模块设计一致（数据结构/接口/流程）

| 设计条款 | 实装位置 | 结果 |
|---|---|---|
| §3.1 `Renderer(window_size, *, skin=None, vsync=True, cell_size, grid_cols, grid_rows)` 签名 | `renderer.py:73-83` | ✅ 完整实装 |
| §3.1 `init/shutdown/__enter__/__exit__` 生命周期 | `renderer.py:117-150` | ✅ `__enter__` 调 init、`__exit__` 调 shutdown；幂等通过测试验证 |
| §4.4 绘制 6 步：fill→snake→food+outline→HUD→fps采样 | `renderer.py:158-184` | ✅ 与设计 §4.4 流程完全对齐 |
| §4.5 grid_to_pixel 接受 `Tuple[int,int]` 而非 Point（避免循环依赖） | `renderer.py:228-235` | ✅ 与设计评审 P3-A 修订一致 |
| §4.6 HUD 5 行（Score/High/Length/Difficulty/Status），OVER 用 accent | `renderer.py:189-225` | ✅ `test_render_hud_status_over_uses_accent_color` 验证 |
| §4.7 fps 采样 render 末尾 + samples 容量 120 + P95 < 20 降级 mean | `renderer.py:182-184` + `types.py:50-66` | ✅ 与设计完全一致 |
| §1.2 DEFAULT_SKIN 8 字段 | `constants.py:40-50` | ✅ 完整 |
| §1.3 布局常量 8 项 | `constants.py:11-18` | ✅ 完整（含 PLAYFIELD_X/Y 内部细节） |
| §3.3 模块导出 13 项 | `__init__.py:6-33` | ✅ `__all__` 与设计表 1:1 对应 |
| §5.5 鲁棒性矩阵 7 场景 | 全部覆盖 | ✅ 见 §3 详表 |
| §5.7 不 import socket/urllib/http/requests | `renderer.py`/`types.py` 仅 stdlib + pygame + 同包 | ✅ |
| §9 迭代 3 接口（set_skin/handle_resize/draw_animated）不实装 | `renderer.py` 未出现 | ✅ |
| §4.1 模块文件组织 | 与设计 §4.1 tree 完全一致 | ✅ |
| §7.8 README 覆盖声称 100% | 实测 100%（见 §4） | ✅ |

**清单 1 结论：PASS**

### 清单 2 — 实现细节质量（边界/异常/资源释放）

| 失败场景 | 实现处理 | 设计条款 | 结果 |
|---|---|---|---|
| 窗口尺寸过小 | `__init__` 校验 min_w/min_h → RenderError | §5.5 | ✅ |
| window_size 非 tuple | `__init__` isinstance 校验 → RenderError | 设计未明确但合理 | ✅ |
| cell_size/grid_cols/grid_rows <=0 | `__init__` 校验 → RenderError | 设计未明确但合理 | ✅ |
| 颜色 RGB 越界（含负值） | `_validate_skin` 校验 → RenderError | §5.5 | ✅ |
| snapshot 为 None | `render()` 显式 raise | §5.5 | ✅ |
| snapshot.snake_body 为空 | `render()` 显式 raise | §5.5 | ✅ |
| init 重复调用 | `if self._initialized: return` | §3.1 幂等 | ✅ |
| shutdown 重复调用（含未 init） | 依赖 pygame 库幂等（display/font/pygame.quit） | §3.1 幂等 + §5.6 | ✅ |
| render 中 init 未完成 | `assert screen is not None` | 未在设计承诺 | ⚠️ P3-1（见 §5） |
| pygame.quit 失败（如已退出） | `shutdown` 不吞异常但 fake_pygame/真实 pygame 均幂等 | §5.6 | ✅ |
| `fps_metric()` 样本为空 | p95=0, fps=0（types.py:53-56） | §4.7 降级 | ✅ |
| fps samples 全 0 | mean=0 → fps 仍为 0（除零保护） | §4.7 | ✅ |

**清单 2 结论：PASS**

### 清单 3 — 可测试性（UT 可写可跑）

| 设计条款 | 实装 | 结果 |
|---|---|---|
| §7.2 pytest + fake_pygame headless 方案 | `tests/conftest.py` 完整 fake_pygame 模块（display/draw/font/time 全 fake） + `monkeypatch.setattr(rmod, "pygame", _pg_module)` 替换模块顶层 import | ✅ |
| §7.2 覆盖率目标 ≥90%（render ≥95%） | **实测 100%**（见 §4） | ✅ 远超目标 |
| §7.4 不依赖真实显示器 | conftest.py 完整 fake；真实 pygame 仅在 `import pygame` 处由 monkeypatch 替换 | ✅ |
| §7.5 断言规范 | draw_calls 列表 + font.render_calls 列表 + Surface.fill_calls/blit_calls + deque 容量断言 | ✅ |
| 跨模块契约验证 | `test_renderer_render.py` 直接 `from game_core import Difficulty, GameStatus, Point, Snapshot` 构造真实 Snapshot | ✅ |
| 几何自洽用例 | `test_constants.py` 验证 WINDOW ≥ grid + 边距 | ✅ |
| sys.path 注入 | conftest.py L15-22 `_GAMECORE_ROOT` 注入（解决了设计评审 P3-D 提出的问题） | ✅ |
| HUD 状态高亮口径 | `test_render_snake_len_3_calls_draw_rect_3_times` 用"按 y 坐标过滤"避开食物冲突（规避了 P3-E 口径问题） | ✅ |

**清单 3 结论：PASS**

### 清单 4 — 代码风格符合架构约定

| 约定 | 实装 | 结果 |
|---|---|---|
| Python 3.8+ 兼容（无 PEP 604/内置泛型下标） | dataclass/frozen + `Optional`/`Tuple` typing，未用 `X \| Y` 联合语法 | ✅ |
| dataclass 可用（与 game-core 一致，P2-3 修订已落地） | Color/Rect/Skin/HudData 全 frozen；FpsMetric 非 frozen（含 deque 字段） | ✅ |
| 模块 < 250 行/文件 | renderer.py 200 行；其他均 < 100 行 | ✅ |
| 类型注解完备 | renderer.py 所有公开方法/属性均带注解 | ✅ |
| 无 socket/urllib/http/requests（NFR-06） | grep 验证 renderer.py/types.py 仅 stdlib + pygame + 同包 | ✅ |
| 构造期不调 pygame.init()（§4.3 可测性） | `__init__` 仅校验参数与皮肤；pygame 调用推迟到 `init()` | ✅ |
| pygame 走模块顶层 import（§4.2 可测性） | `import pygame` 在 renderer.py 顶部；UT 用 monkeypatch 替换 | ✅ |
| 不复用 game-core Point（§1.1 设计原则） | `grid_to_pixel(cell: Tuple[int, int])` 接受 tuple；renderer 内部无 `from game_core import Point` | ✅ |
| README 与设计 §3.3 对齐 | README 列出全部 13 项导出 + 使用示例 | ✅ |

**清单 4 结论：PASS**

## 3. 鲁棒性矩阵（设计 §5.5）逐项实装核对

| 失败场景 | 设计要求 | 实装位置 | 结果 |
|---|---|---|---|
| pygame 初始化失败（无图形环境） | init() 抛出 RenderError | 由 pygame 自身抛错，**未捕获**让上层处理 | ✅（与设计一致：NFR-03 由 game-app 友好提示） |
| 字体加载失败 | 回退 SDL 默认字体 | `pygame.font.SysFont` 在 pygame 内部回退；renderer 不显式 try | ✅（依赖 pygame 库行为） |
| 窗口尺寸过小 | `__init__` 校验 → RenderError | `renderer.py:90-95` | ✅ |
| 颜色 RGB 越界 | `__init__` 校验 → RenderError | `renderer.py:39-55` | ✅ |
| render 时 snapshot 为 None | 立即抛 RenderError（断言） | `renderer.py:165-167` | ✅ |
| fps 样本数 < 20 | P95 降级为 mean | `types.py:57-61` | ✅ |
| 蛇身坐标越界网格 | grid_to_pixel 仍返回像素值 | `renderer.py:228-235` 无边界检查 | ✅（设计明确"接受，由 game-core INV-3 保证不越界"） |

**鲁棒性 7 项全 PASS**

## 4. 测试结果实测

```
$ pytest tests/ -v
53 passed, 1 warning in 10.13s

$ pytest tests/ --cov=gui_renderer --cov-branch
gui_renderer/__init__.py        100%
gui_renderer/constants.py      100%
gui_renderer/errors.py          100%
gui_renderer/renderer.py       100%   (112 stmts, 24 branches)
gui_renderer/types.py           100%
TOTAL                          100%   (189 stmts, 32 branches)
```

- **53 测试全 PASS**（设计 §7.6 必含 39 条 + 实际增补 14 条）
- **覆盖率 100%**（远超设计 §7.2 ≥90% 目标；renderer.py 主体 100%，完全满足"render 主体 ≥95%"）
- **fake_pygame headless 方案生效**：CI 容器（无显示器）零障碍跑通

## 5. 问题清单

### P3（建议修订，不阻塞 PASS）

**P3-1 `renderer.py:118-119` `_min_window_size` docstring 注释冗余/误导**
- 注释：「高 = PLAYFIELD_Y + GRID_ROWS * CELL_SIZE + PLAYFIELD_X（PLAYFIELD_Y = HUD_HEIGHT + PLAYFIELD_Y_OFFSET；下边距 = PLAYFIELD_X 对齐）」
- 问题：注释里造的 "PLAYFIELD_Y_OFFSET" 是凭空名称，constants.py 实际是 `PLAYFIELD_Y = HUD_HEIGHT + 16` 直接定义，没有 PLAYFIELD_Y_OFFSET；读者会误以为存在两段拼装。
- 算式本身正确（已被 `test_renderer_rejects_too_small_window_height` 验证），纯注释问题。
- 修改点：删去"PLAYFIELD_Y_OFFSET"措辞，改为「高 = PLAYFIELD_Y + 网格高 + 下边距（=PLAYFIELD_X 对齐）」。

**P3-2 `renderer.py:138` `_fps.samples = deque(maxlen=FPS_SAMPLES_CAPACITY)` 冗余**
- 实现：`FpsMetric()` 自身已 `default_factory=lambda: deque(maxlen=120)`，FPS_SAMPLES_CAPACITY=120 与默认 120 等值，这次重建等价于 no-op。
- 潜在漂移风险：若有人改 FPS_SAMPLES_CAPACITY 而忘了同步重建点，或改 FpsMetric 默认值，行为会不一致；单点真相原则被破坏。
- 修改点：删除重建行（`FpsMetric()` 自身的 default_factory 已是权威来源）；FPS_SAMPLES_CAPACITY 保留供 §4.7 文档引用与未来微调。

### P4（仅记录，可不修）

- `renderer.py:164` `assert screen is not None` 在 `python -O` 下失效；可改 `if screen is None: raise RenderError("render 前必须先 init()")` 更鲁棒。但 pytest/生产均不用 -O，§5.5 也未承诺 assert 之外的鲁棒性，列为观察项。

## 6. 与设计评审 P2/P3 修订条目交叉核对

| 评审 P2/P3 | 设计侧修订 | 实现侧落地 | 结果 |
|---|---|---|---|
| P2-1 `render(snapshot, hud)` 偏离架构 `render(snapshot)` | 设计保留扩展签名 | `renderer.py:152` 签名 `def render(self, snapshot, hud: HudData)` | ✅ |
| P2-2 窗口尺寸公式定值 | 设计 §1.3 注释算式 512×472 / 16+20×24+16 = 512 | 实现 `__init__` 校验 min_w/min_h 与算式一致 | ✅ |
| P2-3 架构"不用 dataclass" → "dataclass 可用" | 修订架构约定 | 实装大量 dataclass（与 game-core 一致） | ✅ |
| P3-A `grid_to_pixel` 注解改 `Tuple[int,int]` | 修订设计 | `renderer.py:228` `cell: Tuple[int, int]` | ✅ |
| P3-B `Rect` 无消费点 | 标注"迭代 3 预留" | `types.py:18-22` 定义但本迭代无消费；仍导出以保迭代 3 兼容 | ✅（设计意图保留） |
| P3-C `__enter__` 是否自动 init | 修订：明确 __enter__ 调 init | `renderer.py:144-145` `__enter__: self.init()` + `test_context_manager_calls_init_and_shutdown` 验证 | ✅ |
| P3-D conftest sys.path 注入 | 修订 conftest.py | `tests/conftest.py:15-22` 显式 sys.path.insert | ✅ |
| P3-E 蛇身/食物 draw.rect 断言口径 | 明确按颜色/位置过滤 | `test_renderer_render.py` L46-52 用 y 坐标过滤（蛇身） + L64-69 按 width 区分食物 outline | ✅ |

**P2/P3 共 8 项修订全部落地**（FO 已修，code 检视角看 ✅）。

## 7. 结论

- **PASS**（阻塞级 0 项；检视清单 4 项全绿；鲁棒性矩阵 7 项全绿；设计评审 8 项 P2/P3 修订全部落地；测试 53/53 全绿 + 覆盖率 100%）
- **后续要求**：
 1. P3-1/P3-2 由 FO 顺手修订（不阻塞当前门禁，可在下一迭代合并前修）
 2. P4 观察项（assert 替代为 RenderError）作为可选改进
- 本意见归档 `review/code/gui-renderer/iter-1/`，作为 IT 阶段的代码基线。

---

> 本检视为模块内视角（数据结构/实现细节/可测试性/风格）。模块间接口/数据流视角由 SE 检视负责（已通过设计评审 P2-1 修订确认对齐）。

## 附：状态机执行留痕

- `release_module snake-linux gui-renderer 1 review snake-linux/review/code/gui-renderer/iter-1/ PASS` 被状态机严格校验拒绝：
  - 模块 iter1 当前 `status = it_working`（2026-08-14T02:21:53Z MODULE_REVIEW PASS -> it_working，上轮 MDE pid 1167246 已完成检视门禁 PASS）
  - `release_module review` 子命令仅允许从 `dev_reviewing` 状态迁移，**避免重复覆盖已完成 PASS 状态**
  - 审计：script exit_code=1 + stderr `review 需 dev_reviewing + PASS/FAIL（当前 it_working）`
- **处置**：本意见作为 r1 review PASS 之后的**附加观察记录**归档到同一目录（与上一轮意见并列），不调用 release_module 破坏状态机流水线。后续若需更新意见，应等模块回到 `dev_working`/`dev_reviewing` 后由对应轮次 MDE 重新检视（FAIL→FO 修订→再 spawn）。