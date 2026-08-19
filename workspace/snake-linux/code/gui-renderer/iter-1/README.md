# gui-renderer（snake-linux v2.0.0 迭代 1）

> pygame 渲染模块：基础绘制闭环（蛇/食物/背景/HUD）。迭代 1 范围；迭代 3 增量（平滑插值、皮肤系统 ≥3 套、窗口等比缩放、高分屏清晰）通过扩展接入，不修改本模块迭代 1 签名。

## 依赖

- game-core（迭代 1 已 it_passed；本模块通过 Snapshot 字段读取游戏状态，不直接 import Point/Direction）
- pygame（pygame 2.x 自动处理 HiDPI）
- pytest（仅 UT）

## 安装

```bash
uv pip install pygame pytest pytest-cov
```

## 运行 UT

```bash
cd workspace/snake-linux/code/gui-renderer/iter-1
pytest tests/ -v --cov=gui_renderer --cov-branch
```

当前覆盖率：100%（≥90% 目标达成）。

## 使用示例（game-app 集成）

```python
from game_core import Difficulty, GameStatus, GameState
from gui_renderer import Renderer, HudData, DEFAULT_SKIN

with Renderer((640, 480), skin=DEFAULT_SKIN) as renderer:
    state = GameState(20, 15, Difficulty.MEDIUM)
    while True:
        snap = state.snapshot()
        hud = HudData(
            score=snap.score,
            high_score=0,                  # 迭代 2 起从 platform-storage 读
            length=snap.length,
            difficulty_label=snap.difficulty.name,
            status_label=snap.status.name,
        )
        renderer.render(snap, hud)
        # pygame.display.flip()            # game-app 自行调用
        metric = renderer.fps_metric()    # NFR-01 性能验证依据
```

## 对外接口（设计 §3.1 / §3.3）

```python
from gui_renderer import (
    Renderer,                 # 主控类
    Color, Rect,              # 值对象
    Skin, HudData, FpsMetric, # 数据结构
    DEFAULT_SKIN,             # 经典皮肤
    WINDOW_WIDTH, WINDOW_HEIGHT,  # 布局常量
    HUD_HEIGHT, CELL_SIZE,
    GRID_COLS, GRID_ROWS,
    RenderError, SkinNotFoundError,  # 异常
)
```

### Renderer 生命周期

```python
r = Renderer((640, 480), skin=None, vsync=True)
r.init()                      # pygame.init() + set_mode + font
r.shutdown()                  # 幂等；FR-11 退出无残留
# 或上下文管理器：
with Renderer((640, 480)) as r:
    ...
```

### 一帧绘制

```python
r.render(snapshot, hud)       # 副作用：写 pygame 后台缓冲；末尾采样 fps
r.fps_metric()                # FpsMetric(p95_frame_ms, fps)
```

## 迭代 3 扩展点（接口预告，不在本迭代实现）

- `set_skin(name: str) -> None`：切皮肤；从 SkinRegistry 字典查；不在 → SkinNotFoundError
- `handle_resize(w: int, h: int) -> None`：保持 grid_cols/rows 不变，重算 CELL_SIZE
- `draw_animated(snapshot, prev_snapshot, alpha) -> None`：平滑插值；render() 内部按 alpha=1.0 调用保持兼容
- `SkinRegistry: Dict[str, Skin]`：模块级字典；DEFAULT_SKIN 已注册；迭代 3 加 "dark" / "colorblind_friendly"

扩展原则：**迭代 3 只新增方法 + 新增 Skin 注册项，不修改 `render(snapshot, hud)` / `fps_metric()` 签名**。

## 设计文档

完整功能模块设计：`workspace/snake-linux/design/gui-renderer/设计-r1.md`

## 模块文件

```
gui_renderer/
├── __init__.py         # 对外 re-export
├── types.py            # Color, Rect, Skin, HudData, FpsMetric
├── constants.py        # DEFAULT_SKIN + 布局常量
├── renderer.py         # Renderer 类
└── errors.py           # RenderError, SkinNotFoundError
```

## 约束

- **构造期不调 `pygame.init()`**：让 `Renderer(...)` 在 import 时无副作用；UT 在 headless 环境直接 `Renderer(...)` 不触发 SDL
- **pygame 调用走模块顶层 import**：`monkeypatch.setattr(gui_renderer.renderer, "pygame", fake_pygame)` 替换
- **不访问 platform-storage**：high_score 由 game-app 主循环注入
- **不引入 socket/urllib/http/requests**（NFR-06）