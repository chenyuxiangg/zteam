# game-core（snake-linux v2.0.0 迭代 2）

玩法核心纯逻辑模块。实现 FR-01~05（基础玩法）+ FR-12（暂停/继续）+ FR-13（得分事件回调入口）；满足 NFR-01（困难档节拍 ≤ 简单档 50%）与 NFR-05（零 GUI 依赖，可独立 UT）。

## 文件结构

```
game-core/iter-2/
├── game_core/
│   ├── __init__.py        # 对外 re-export
│   ├── types.py           # Point / Direction / Difficulty / GameStatus / Snake / Food / Snapshot
│   ├── params.py          # speed_curve + MIN_TICK_MS + Difficulty.base_tick_ms 运行时绑定
│   ├── state.py           # GameState（含 step / set_direction / toggle_pause / set_score_callback / snapshot）
│   └── errors.py          # InvalidStateError（DirectionError 已删除）
└── tests/test_game_core/  # 89 个 unittest 用例（迭代 1 基线 21 + 迭代 2 增量 68 落点；设计 UT #1~#41 + 辅助）
```

## 迭代 2 增量（vs 迭代 1）

| 增量 | API | 说明 |
|------|-----|------|
| 加速曲线 | `speed_curve(score, difficulty) -> int` | 公式 `max(MIN_TICK_MS[d], base - k*score)`；`Difficulty.base_tick_ms` 改为 `speed_curve(0, self)`；`Snapshot.tick_ms` 改走 `speed_curve(score, difficulty)` |
| 三档独立下限 | `MIN_TICK_MS: Dict[Difficulty, int]` | `EASY=100 / MEDIUM=80 / HARD=50`；满足 NFR-01 量化（HARD_MIN=50 ≤ EASY_MIN×0.5） |
| 暂停状态机 | `GameState.toggle_pause() -> GameState` | RUN ↔ PAUSED；OVER 抛 `InvalidStateError`；INV-8 恢复时清 `pending_direction`；INV-9 仅 status 翻转 |
| 得分事件回调 | `GameState.set_score_callback(cb) -> GameState` | 构造期或运行时注册；step 吃食时触发；异常不捕获（pure-function 语义） |

## 公开 API

```python
from game_core import (
    GameState, GameStatus, Direction, Difficulty,
    Point, Snake, Food, Snapshot,
    speed_curve, MIN_TICK_MS,
    ScoreCallback,
    InvalidStateError,
)

s = GameState(width=20, height=15, difficulty=Difficulty.MEDIUM, rng=random.Random(42))
s = s.set_score_callback(lambda score: print(f"score={score}"))
s = s.set_direction(Direction.UP)
paused = s.toggle_pause()
resumed = paused.toggle_pause()
s2 = resumed.step()
snap = s2.snapshot()  # 含 tick_ms = speed_curve(score, difficulty)
```

## 运行测试

```bash
cd snake-linux/code/game-core/iter-2
python3 -m unittest discover -s tests/test_game_core -v

# 覆盖率（应 ≥95%）
python3 -m coverage run --source=game_core --branch -m unittest discover -s tests/test_game_core
python3 -m coverage report --include="game_core/*"
```

## 与 app/GUI 的协作边界

- **窗口失焦自动暂停**：app 主循环监听 `pygame.WINDOWFOCUSLOST` 事件 → 调 `toggle_pause()`
- **P/ESC 键**：app 事件循环 → 调 `toggle_pause()`
- **最高分持久化**：app 在游戏开始前注册 `s.set_score_callback(lambda x: storage.save(max(x, storage.load())))`；core 不持有 storage 引用
- **节拍渲染定时**：app 按 `snapshot.tick_ms` 设定定时器
- **core 不知道"窗口/焦点/键盘"概念**（NFR-05 零 GUI 依赖）

## 关键不变量（INV）

| ID | 说明 |
|----|------|
| INV-1~7 | 迭代 1 沿用（蛇身/食物/边界/终态保护/反向禁止/RNG 注入/网格下限） |
| INV-8 | toggle_pause(PAUSED→RUN) 必须清 `pending_direction` |
| INV-9 | toggle_pause 自身不修改 snake/food/score/direction/pending_direction 之外的字段 |
| INV-10 | `speed_curve` 单调不增；`speed_curve(score, HARD) ≤ speed_curve(score, EASY) × 0.5` |

## 约束

- Python 3.8 语法兼容（无 PEP 604 / 内置泛型下标）
- 仅标准库 import（`enum` / `dataclasses` / `random` / `typing`）
- 纯函数语义：`step` / `set_direction` / `toggle_pause` / `set_score_callback` 全部返回新 GameState，不修改 self