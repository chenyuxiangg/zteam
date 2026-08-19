# gui-renderer 迭代 3

> snake-linux v2.0.0 迭代 3：FR-07 平滑插值动画 + FR-09 窗口等比缩放 + FR-10 皮肤系统 ≥3 套 + NFR-04 高分屏清晰。
> 在迭代 1 已落地代码 `iter-1/gui_renderer/{types,constants,renderer,errors,__init__}.py`（已 it_passed）基础上增量接入。

## 文件组织

```
iter-3/
├── gui_renderer/
│   ├── __init__.py            # 对外 re-export（增量 InterpolationState / DARK_SKIN / COLORBLIND_FRIENDLY_SKIN / SKIN_REGISTRY / CELL_SIZE_MIN / MIN_PLAYABLE_W / MIN_PLAYABLE_H）
│   ├── types.py               # Color / Rect / Skin(+3字段：cell_gap/food_pattern/snake_pattern) / HudData / FpsMetric / InterpolationState
│   ├── constants.py           # DEFAULT_SKIN + DARK_SKIN + COLORBLIND_FRIENDLY_SKIN + SKIN_REGISTRY + CELL_SIZE_MIN + MIN_PLAYABLE_W/H
│   ├── renderer.py            # Renderer 类（增量 enable_high_dpi / SCALED 标志 / render(interp=...) / set_skin / handle_resize / skin_names / current_skin_name）
│   └── errors.py              # RenderError / SkinNotFoundError(name, available)
└── tests/                     # 迭代 1 既有 + 迭代 3 增量 UT
```

## 用法

```python
from gui_renderer import (
    Renderer, HudData, InterpolationState,
    DEFAULT_SKIN, DARK_SKIN, COLORBLIND_FRIENDLY_SKIN, SKIN_REGISTRY,
)

with Renderer((640, 480), enable_high_dpi=True) as r:
    # 切皮肤（游戏中不中断，下一帧生效）
    r.set_skin("dark")
    # 缩放窗口（game-app 监听 WINDOWEVENT_RESIZED 调 handle_resize）
    r.handle_resize(1024, 768)
    # 渲染一帧（interp=None 与迭代 1 兼容；interp=InterpolationState(...) 启用插值）
    r.render(snap, hud, interp=interp)
    metric = r.fps_metric()
    pygame.display.flip()
```

## 测试

```bash
cd workspace/snake-linux/code/gui-renderer/iter-3 && pytest tests/ -v
```

## 设计依据

- `snake-linux/design/gui-renderer/设计-r4.md`（MDE 增量设计；SE 评审第三轮意见已落实）
- `snake-linux/arch/v2.0.0/架构设计.md`（架构约束）
- `snake-linux/arch/v2.0.0/功能模块分工表.md`（模块接口契约）
- `snake-linux/analysis/snake-gui-r1.md`（需求规格，approved）
