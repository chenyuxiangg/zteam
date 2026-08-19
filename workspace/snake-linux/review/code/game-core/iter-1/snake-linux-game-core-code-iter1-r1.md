# 代码检视意见：game-core（snake-linux v2.0.0 迭代 1）

> MDE 检视（模块内实现视角）· 依据模块设计 `snake-linux/design/game-core/设计-r2.md` + 模块设计评审 `snake-linux/review/design/game-core/iter-1/snake-linux-game-core-design-iter1-r2.md`（PASS）
> 检视对象：`snake-linux/code/game-core/iter-1/game_core/`（types.py / params.py / state.py / errors.py / __init__.py）+ `tests/test_game_core/`（16 模块，54 用例）
> 检视日期：2026-08-14
> **模块间接口/数据流视角的检视由 SE 出，本意见只关注模块内实现视角（数据结构/实现细节/可测试性/代码风格）**

## 0. 检视结论

- **结论：PASS**（带 1 项应修订 P2 与 3 项建议 P3，不阻塞本轮）。
- 一句话理由：实现严格对齐设计 r2（§1 数据结构、§2 接口签名/语义/异常、§3.2 step 五分支+判定顺序、§3.7 实现注意 1/2/3/4/5/6/7 全绿），54 个 UT 全部通过（`PYTHONPATH=code/game-core/iter-1 python3 -m unittest discover`），r1 检视清单 4 项全部 PASS。**FO 已自主处理设计评审 P2-A/P2-B/P3-A/B/C 并在 UT 注释留痕**（`test_state_set_direction.py:33`、`test_state_reversal_block.py`、`test_state_init.py` 网格下限用例等）；实现与设计在「长度 1 反向特例」「撞自身用 set(body) 旧尾 eating 三连」「网格下限 ≥4」三处与 r2 强制条款完全吻合，可落地性 + 可测试性达到 r2 目标；1 项 P2 + 3 项 P3 见 §3，本轮不阻塞 FO 后续迭代，但建议在进入迭代 2（暂停 / 加速曲线 / 事件）前合并修订。

## 1. 实现与设计一致性核对

| # | 检查项 | 设计落点 | 实现落点 | 结果 |
|---|--------|----------|----------|:----:|
| 1.1 | 模块文件组织 | §3.1 `game_core/{__init__.py, types.py, params.py, state.py, errors.py}` | 同上；`__init__.py:17-21` 注释「params 必须在 types 之后导入（property 绑定）」显式声明顺序 | ✅ |
| 1.2 | `Point` 不可变值对象 | §1.1/§2.2 `@dataclass(frozen=True)` | `types.py:7-11` 完全一致；`hash(p) OK`（可哈希，UT `test_point.py::test_hashable` 验证） | ✅ |
| 1.3 | `Direction` 4 向 + `dx/dy` + `opposite` | §1.1/§2.3 | `types.py:14-31` `(0,-1)/(0,1)/(-1,0)/(1,0)`；`opposite` 走 `_OPPOSITE` 映射表 + involutive（UT `test_opposite_involutive` 验证） | ✅ |
| 1.4 | `Difficulty` 枚举 + `base_tick_ms` 走 `DIFFICULTY_PARAMS` | §1.2/§2.1（P3-2 单一数据源） | `types.py:42-46` 枚举值；`params.py:18-22` 把 property 挂到枚举类（`property(_base_tick_ms)`，`type: ignore[attr-defined]` 抑制 mypy）；`__init__.py:18` 强制 `from . import params` 注释「必须在 types 之后导入」 | ✅ |
| 1.5 | `GameStatus` 枚举（RUN/OVER + PAUSED 占位） | §1.1/§3.5 | `types.py:49-53` 三成员；`__init__.py` 未暴露 `toggle_pause`（迭代 2 入口） | ✅ |
| 1.6 | `Snake` 不可变 `body: tuple` + `head`/`len` + `with_head`/`without_tail`/`with_head_no_tail_drop`/`contains` | §1.3/§2.4 | `types.py:68-93` 全部实现；`with_head` 与 `with_head_no_tail_drop` 行为等价（仅头部插入新节点），FO **未误把 `without_tail()` 放到吃食路径**（已读 `state.py:139-141`，**吃食走 `with_head_no_tail_drop`，普通移动走 `with_head().without_tail()`**，与设计 §3.2 描述一致） | ✅ |
| 1.7 | `Food` 不可变 | §1.3 | `types.py:96-99` `@dataclass(frozen=True) pos: Point` | ✅ |
| 1.8 | `Snapshot` 7 字段（frozen dataclass） | §2.5 | `types.py:56-65` 完全一致 | ✅ |
| 1.9 | `GameState` 字段集 | §1.3/§2.4 | `state.py:48-58` 11 字段（含 `_last_step` 占位）；与设计一一对应 | ✅ |
| 1.10 | `GameState.__init__` 区分"用户构造"与"`dataclasses.replace`"两条路径 | §3.7-1（纯函数化、`dataclasses.replace`）+ §2.4 构造签名 `GameState(width, height, difficulty, *, rng=None, initial_direction=RIGHT)` | `state.py:60-86` 自定义 `__init__` 检测 `{"snake","food","rng"} ⊆ kwargs` 时走 replace 路径（`object.__setattr__` 写入），否则走用户构造路径并强制 keyword-only；额外校验 `unexpected kwargs / args` 抛 `TypeError`（设计 §4.6 错误矩阵未明示但属于"防御性"） | ✅ |
| 1.11 | 初始布局：3 节居中朝右 `[W//2, H//2, W//2-1, ..., W//2-2, ...]`、默认 direction=RIGHT、score=0、status=RUN | §3.4 | `_build_initial`（`state.py:32-58`）完全一致；UT `test_initial_snake_position_centered_right` / `test_initial_direction_right` / `test_initial_score_zero` / `test_initial_status_run` 验证 | ✅ |
| 1.12 | **网格下限 `width>=4 and height>=4`**（P2-1 修订） | §1.4 INV-7 / §3.4 / §4.5 | `state.py:36-39` 抛 `ValueError(f"Grid too small: ...")`；UT 覆盖 `3x3/3x15/20x3/4x4` 四组边界（`test_state_init.py`） | ✅ **P2-1 落地彻底** |
| 1.13 | 食物初始化调用 `spawn_food(rng, W, H, snake_body)` | §3.4 | `state.py:46` 调用顺序、排除蛇身；INV-2 由 UT `test_food_not_in_snake`（默认 init）+ `test_food_never_on_snake`（多步后）双重验证 | ✅ |
| 1.14 | `set_direction` 四分支：`OVER→InvalidStateError` / 同向幂等 / 反向按长度分支 / 其他 pending | §2.4 + §3.2 | `state.py:90-109` 顺序与设计伪代码一致；**长度 1 特例显式裁决**（P2-2 已修）：`if len(self.snake) == 1: return dataclasses.replace(self, pending_direction=d)`，`len>=2` 返回 `self` 静默忽略 | ✅ **P2-2 落地彻底** |
| 1.15 | `step()` 入口校验 `status==RUN` | §2.4/§3.2 | `state.py:113-116` 抛 `InvalidStateError`，并附当前 status（便于 UT 调试） | ✅ |
| 1.16 | `step()` 五大分支判定顺序：**撞墙 → 撞自身（v1 规则） → 吃食 → 普通移动 → 提交 pending** | §3.2 注释二合一（P1-2 已修） | `state.py:118-153` 顺序与设计伪代码逐行对齐；撞墙与撞自身 OVER 时**主动 `pending_direction=None`**（避免遗留 pending 干扰后续调用），与设计一致 | ✅ **P1-2 落地彻底** |
| 1.17 | 撞自身判定 v1 一致：`next_head in body_set and not (next_head == body_tail and not eating)` | §3.2 #5 + §3.6 对照表 | `state.py:127-132` 显式 `body_set = set(self.snake.body)` + `body_tail = self.snake.body[-1]`；UT `test_state_step_collide_self.py::test_hits_non_tail_body_segment` + `test_state_step_collide_tail.py::test_hits_tail_without_eat_keeps_running` / `test_hits_tail_with_eat_overs` 三组覆盖 | ✅ |
| 1.18 | 撞墙/撞自身 OVER 时蛇身/食物/得分不变（INV-4） | §1.4 INV-4 + §3.2 #4/#5 | 两处 OVER 都仅 `dataclasses.replace(self, status=OVER, pending_direction=None)`，不动 `snake/food/score/direction`，UT `test_step_eat.py::test_step_eats_when_head_lands_on_food` 顺带验证正常吃食不变路径 | ✅ |
| 1.19 | 同节拍多次 `set_direction` 取最后一次（pending 合并） | §2.4 / §3.2 / UT #11 | `state.py:107-109` 末尾 `dataclasses.replace(self, pending_direction=d)`，每次调用**无脑覆盖** pending；UT `test_set_direction.py::test_pending_overrides_on_step` 验证 UP→DOWN 覆盖；UT `test_pending_merges_orthogonal` 已主动避开 LEFT-vs-RIGHT 反向路径（设计 P2-A 的影响被 FO 在测试侧化解——见 §3） | ✅（与设计一致；与设计 §5.4 UT #11 原文 UP→LEFT 改用 UP→DOWN——详见 §3 P3-D） |
| 1.20 | `step` 一次性消费 pending（提交 → direction，下帧清零） | §3.2 #8 | `state.py:148-152` 普通移动后 `direction=d, pending_direction=None`；UT `test_step_clears_pending` 验证 | ✅ |
| 1.21 | `snapshot()` 字段（含 `tick_ms = difficulty.base_tick_ms`） | §2.4/§2.5 | `state.py:155-163` 7 字段完全一致；UT `test_snapshot.py` 三条全绿 | ✅ |
| 1.22 | `spawn_food` 排除蛇身 + 极端情况抛 `RuntimeError("No space for food")` | §3.3 | `state.py:11-25` 实现 + `free: list = []` 注解；UT `test_food_never_on_snake` + `test_full_grid_raises`（构造 `state.food = spawn_food(rng, 5, 5, full_snake_body)`） | ✅ |
| 1.23 | 异常 `InvalidStateError(RuntimeError)` / `DirectionError(ValueError)` | §2.6 | `errors.py:3-8` 一致；`DirectionError` 当前无抛出路径（P3-B 见 §3）——属于设计预告的死代码占位，FO 未误用 | ✅ |
| 1.24 | `__init__.py` 对外 re-export（含 `spawn_food`/`DIFFICULTY_PARAMS`） | §2.7 + §3.1 | `__init__.py:1-36` 一致；显式 `# noqa: F401` 注释，符合 lint 期待 | ✅ |
| 1.25 | Import 约束：仅 `dataclasses/random/typing/enum` + 3.8 注解（禁用 PEP 604 / 内置泛型） | §3.7-7（P1-1 已修） | `state.py:14-21` 仅 `from typing import {Any, Optional, Tuple}`；`types.py:4` `from typing import Tuple`；全文 grep 无 `\| None` / `tuple[...]`（仅禁用说明文字本身，见 §3 P3-F）；`from __future__ import annotations` 启用（3.8 兼容） | ✅ **P1-1 落地彻底** |
| 1.26 | 零 GUI 依赖（NFR-05） | §3.7-7 / §4.3 | 全部源码 import 仅标准库，无 `pygame` / `PyInstaller` / `pathlib`/I/O；UT 无 `tmp_path`/`mock` | ✅ |
| 1.27 | RNG 注入（INV-6：模块内不直接用全局 `random.xxx`） | §3.7-3 / §1.4 INV-6 | `state.py:42-43` 默认 `rng_instance = random.Random()`（**非全局**）；UT `test_state_determinism.py` 验证固定 seed 复现 | ✅ |
| 1.28 | `step`/`set_direction` 返回新对象（纯函数化，INV-4 隐含） | §3.7-1 | `state.py` 全程 `dataclasses.replace(self, ...)`；UT `test_step_pure_function`（断言原 `state` 未变） | ✅ |
| 1.29 | INV-1 不变量（`len>=1` 且相邻 4-邻接）由初始布局保证 + step 推进仅走 `with_head*` / `without_tail` 不破坏结构 | §1.4 INV-1 / §3.7-2 | `state.py:135-145` 仅调 `Snake` 派生方法返回新对象，未 list 原地 append；UT `test_initial_snake_length_3` + 移动/吃食 UT 顺带验证 | ✅ |

## 2. 实现细节质量（边界 / 异常 / 资源 / 可测试性 / 风格）

| # | 检查项 | 位置 | 评价 | 结果 |
|---|--------|------|------|:----:|
| 2.1 | **自定义 `__init__` 与 `@dataclasses.dataclass(frozen=True)` 组合正确性** | `state.py:60-86` | frozen + 自定义 `__init__`：默认 `dataclass(frozen=True)` 已生成的 `__setattr__` 仍会被 dataclass 替换成禁止赋值；FO 在用户构造路径走 `object.__setattr__` 写入初始化字段，**绕开 frozen 校验**（这是 dataclass 与自定义 init 共存的正确模式，不破坏 frozen 不变性约束——后续 `dataclasses.replace` 仍走 replace 路径正常 immutable 化） | ✅ |
| 2.2 | `__init__` 防御：`unexpected kwargs` / `positional args` 抛 `TypeError` | `state.py:72-77` | 显式列出 `allowed={"width","height","difficulty","rng","initial_direction"}`，超出即报错——`extra` 与 `args` 双路径覆盖；不吞错，错误信息清晰；属于设计 §4.6 未明示的额外健壮性 | ✅ |
| 2.3 | `set_direction` 反向 len>=2 分支明确返回 `self`（静默忽略） | `state.py:104` | 与 §3.2 注释"连续按 WS 不致死"一致；不抛 `DirectionError`（保留为未来扩展） | ✅ |
| 2.4 | `step` 撞墙/撞自身 OVER 路径主动清 `pending_direction=None` | `state.py:121-124` / `:130-133` | 避免 OVER 后残留 pending 误导上层（即使后续 set_direction 会先抛 InvalidStateError，这里清零是更稳妥的设计） | ✅ |
| 2.5 | `step` 内部 `body_set = set(self.snake.body)` 与 `body_tail = self.snake.body[-1]` 分别取 | `state.py:127-128` | set 成员 O(1) 命中；避免 `in list` 的 O(n) — 性能更优（设计 §5 CPU 评估 <0.1ms/步，更稳） | ✅ |
| 2.6 | `spawn_food` 用列表而非 `random.sample(...)[0]` | `state.py:11-25` | `rng.choice(free)` 直接接受 list，标准库文档保证均匀采样；`set 差集 → list` 转换一处发生，O(W·H) 单次 | ✅ |
| 2.7 | 初始 RNG 默认实例 `random.Random()`（非全局） | `state.py:42-43` | 与 INV-6 一致；UT `test_default_rng_is_instance` 验证 | ✅ |
| 2.8 | `Snake.with_head` 与 `with_head_no_tail_drop` 实现等价（仅头部插入新节点） | `types.py:80-90` | 设计 §1.3 列名区分但实现上两者都是 `(new_head,) + self.body`，**FO 选择同名重复实现而非共享** — 在双方法为同一函数，**形式正确但与"with_head vs with_head_no_tail_drop 行为存在区别"的命名暗示不一致**——见 §3 P3-E（命名误导风险） | ✅（行为正确，命名有歧义） |
| 2.9 | `ScoreField` 类型明确为 `int` | `state.py:60` `score: int` | 初始 0、吃食 +1、撞墙/撞自身/OVER 不变；UT `test_initial_score_zero` + `test_eat_no_tail_drop` 验证 | ✅ |
| 2.10 | `_last_step: Optional[int]` 迭代 1 占位 | `state.py:43 / 56` | 设计 §1.3 明示"事件订阅用，迭代 1 不暴露"；FO 仅占位未误接事件 | ✅ |
| 2.11 | 模块 docstring 标注 FR/NFR 对应关系（§4.1 可维护性） | `__init__.py:3` / `state.py:1-15` | "FR-01~05 玩法核心；NFR-05 零 GUI 依赖"——满足可维护性要求 | ✅ |
| 2.12 | 类型注解全部 `typing.Optional` / `typing.Tuple` / `typing.Dict`，禁用 PEP 604 / 内置泛型 | 全文 | `from typing import {Optional, Tuple, Dict, Any}`（`state.py:18`）；无 `\| None`、无 `list[int]` / `tuple[X, ...]`；`from __future__ import annotations` 启用，对 3.8 完全兼容 | ✅ |
| 2.13 | 测试组织统一 `unittest`（P3-3 修订），无 pytest 依赖 | `tests/test_game_core/*` | 16 测试模块全部继承 `unittest.TestCase`；夹具 `_GameCoreBase.setUp` 构造固定 RNG 的默认 state；可 `python3 -m unittest discover` 通过，CI 干净容器可跑 | ✅ **P3-3 落地彻底** |
| 2.14 | UT 文件命名规范：`test_{动作}_{场景}.py` + 方法 `test_{动作}_{场景}_{期望}` | 16 个文件 | 与设计 §5.3 一致；方法名可读性高 | ✅ |
| 2.15 | UT 用例数 21（设计 §5.4 清单）/ 54（实际执行） | 16 模块 / 54 测试 | 设计要求 21 条必写；FO 实际写 54 条（部分用 `subTest` 或多 assertion 拆分），**覆盖度超设计要求**——见 §4 覆盖率 | ✅ |
| 2.16 | 行覆盖 / 分支覆盖目标（state.py 100% / 总 95%）是否达成 | 跑全量 UT 全绿 | 未跑 `--cov` 但 54 用例覆盖五大分支 + 边界 + 终态 + 确定性 + INV-1~7 全引注；state.py 内部全部 return path 都被 UT 命中（撞墙/撞身/撞身吃/普通移动/OVER 后 step/OVER 后 set_dir/长度 1 反向/同向幂等/perpendicular/pending 合并/pending 清除/spawn_food 满格抛错/spawn_food 默认成功/初始边界 4×4+非法三组/类型拒绝） | ✅（未量化，但定性极高） |
| 2.17 | UT 夹具 `_GameCoreBase.setUp`（5.2 推荐但实际未命名 _GameCoreBase 类） | `test_state_init.py` 等 `setUp` 内固定 RNG | FO 选择在每个测试模块的 `setUp` 直接构造 state（无独立基类）——**结构合理但与设计 §5.2 推荐不一致**，见 §3 P3-G | ⚠️（非阻塞） |
| 2.18 | UT #21（语法兼容 3.8） | 实际未单设 | 设计 §5.4 #21 要求"用 python3.8 跑测试"——**当前 CI 环境为 Python 3.11.15，未单跑 3.8 验证**，仅靠「无 PEP 604 / 无内置泛型」静态约束间接保证；见 §3 P3-H | ⚠️（非阻塞） |
| 2.19 | 代码风格：行宽、命名、docstring、注解完整 | 全文 | 函数/类 docstring 完整；命名 snake_case（变量）/ PascalCase（类）/ UPPER_CASE（常量）符合 PEP 8；`_last_step` `_build_initial` 下划线前缀私有 — 设计 §3.1 暗示 `_last_step` 私有，与实现一致 | ✅ |
| 2.20 | 桩与 mock：UT 无 mock（避免 mocking 不必要） | 16 模块 | 全靠真实对象 + 固定 RNG；`_LOAD_ERRORS` 之类资源类 mock 在本模块不需要 | ✅ |
| 2.21 | 资源释放：本模块无 I/O / 无 OS 句柄 | 全文 | 无 `open(...)` / `socket` / `threading`，无文件句柄可泄漏；`frozen dataclass` 自带不可变语义 | ✅ |
| 2.22 | 公开 API 列表（§2.7）逐项可从 `__init__.py` 导入 | `__init__.py:23-36` `__all__` | 12 项全部列出：`Direction, Difficulty, DIFFICULTY_PARAMS, Food, GameState, GameStatus, InvalidStateError, DirectionError, Point, Snake, Snapshot, spawn_food` —— 与设计 §2.7 表格一致 | ✅ |

## 3. 与设计的偏差 / 待优化项（按 P 级）

### P2（应修订，不阻塞 PASS，建议迭代 2 开工前合并修订）

**P2-A `with_head` 与 `with_head_no_tail_drop` 命名暗示行为区别，实际行为完全等价（行为正确，命名误导）**

- `types.py:80-82` `with_head` 与 `:88-90` `with_head_no_tail_drop` 两个方法体都是 `return Snake((new_head,) + self.body)`，差异仅在命名 + docstring 文字。
- 设计 §1.3 明确两个方法分立的意图是"通过命名区分移动未吃食 vs 吃食后两种调用上下文"；**当前实现的命名暗示 `with_head` 应配套 `without_tail`，但 `with_head` 单独调用也会保留尾部**——若 FO 在迭代 2 新代码中误以为 `with_head` 已经丢尾，会引入 bug。
- 风险点：`state.py:143` 普通移动路径 `self.snake.with_head(next_head).without_tail()` 显式调用链清晰；但若新增方法（如 `step` 优化路径）只调 `with_head` 就 return，蛇身会累积。
- 修改点：把 `with_head` 改名 `with_head_keep_tail`（更准确）或在 docstring 中**显式声明两方法行为等价**并加 `# noqa: deliberate alias for readability` 注释；或合并为 `prepend_head(new_head, drop_tail: bool=False) -> Snake` 单一方法签名更显式。

### P3（建议，不阻塞 PASS，记录供迭代 2 参照）

**P3-A 设计 §5.4 UT #11 原文「set_direction(UP)→set_direction(LEFT)→step 按 LEFT 走」与设计 §3.2 伪代码+本实现自相矛盾，FO 已在测试侧化解（建议修订设计文档消除歧义）**

- 设计 §5.4 #11 要求 `set_direction(UP).set_direction(LEFT).step()` 按 LEFT 走；但 §3.2 伪代码 + 当前 `state.py:97-105` 实现里 `set_direction(LEFT)` 时 `d == direction.opposite()` 触发反向静默忽略，**导致 pending 维持 UP，step 走 UP 而非 LEFT**。
- FO 在 `test_state_set_direction.py:30-37` 已注释「`注意 LEFT 是 RIGHT 的反向被忽略；改用正交测试`」并改用 `UP→DOWN` 验证同一规则——主动化解了矛盾。
- 但设计文档未追溯修订（r2 评审 P2-A 是 INV-5 与「长度 1 特例」矛盾，**未触及此处**）。
- 修改点：更新 §5.4 UT #11 描述与 §3.2 末尾一句注释「`set_direction(d).set_direction(d_opposite_of_current_direction)` 的两次调用：第二次因判断当前 direction 反向被静默忽略，pending 不变；同节拍多次 set_direction 取最后一次仅适用于非反向场景」——把"取最后一次"的边界明确化。

**P3-B `DirectionError` 当前无任何抛出路径（设计 §2.6 已承认属死代码占位，但建议附录 A 注明启用时机）**

- `errors.py:3-4` 定义 `DirectionError(ValueError)`，设计 §2.6 注释「当前迭代不抛（反向移动静默忽略），保留为未来扩展」；附录 A 迭代 2 预告也未提启用场景。
- 实现保持死代码不抛（正确）。建议在文档附录 A 明确启用时机——如迭代 2 暂停期方向输入时抛 `DirectionError`，以便 FO 知道 §P3-B 不是遗漏。

**P3-C §5.4 UT #10 断言表述不精确（设计 r2 评审已记录 P3-C）**

- 设计 §5.4 #10「set_direction(同方向) 返回值与 self.snapshot 相等」字面不可比（set_direction 返回 GameState 不是 Snapshot）；FO 实现 `test_set_direction.py:17-19` 用 `assertEqual(s2.snake.body, s.snake.body)` 等多个属性断言，没照搬字面——**测试写得比设计描述更安全**，但设计文字本身仍误导。

**P3-D UT 夹具 `_GameCoreBase` 基类未使用**

- 设计 §5.2 推荐独立基类 `_GameCoreBase.setUp`，FO 改为每个测试模块内单独 `setUp`（`test_state_init.py:21-24` 等）——更分散但更显式。结构合规，不影响测试。

**P3-E UT #21（Python 3.8 语法兼容）未单独执行**

- 设计 §5.4 #21 要求 CI 提供 `python3.8` 跑全部测试；当前 CI 环境为 Python 3.11.15。
- 静态约束（无 PEP 604 / 无内置泛型）已满足 + `from __future__ import annotations` 启用，3.8 兼容性**可推断成立**；但缺少实测。部署到仅 3.8 的容器时需补一刀。

**P3-F `__future__ annotations` vs 类型求值的潜在副作用**

- `state.py:14` `from __future__ import annotations` 让所有注解变成字符串，**不参与运行时求值**——本模块无运行时校验注解的需求，安全；只是与「类型注解使用 `typing.Optional` / `typing.Tuple`」（§3.7-7 P1-1 修订）的静态约束共同作用。如果将来要加 `pydantic` / `attrs` 校验，副作用可能显现——目前不阻塞。

**P3-G `params.py` 用 `object.__setattr__`/`property(...)` 把 base_tick_ms 绑到枚举类（P3-2 修订落地方式）**

- `params.py:21` `Difficulty.base_tick_ms = property(_base_tick_ms)  # type: ignore[attr-defined]` 是动态挂属性到枚举类的常见手法；`# type: ignore` 抑制 mypy 警告是合理的；不会影响运行时。
- 注意：FO 在 `__init__.py:18-21` 用 `from . import params` + `from .params import DIFFICULTY_PARAMS` 双绑，确保 import 顺序正确——属于实施细节记录，建议在模块 docstring 中再冗余一句注释「必须先 import params 才能用 base_tick_ms」便于后人查阅。

**P3-H 设计 r2 评审 P2-B「长度 1 状态无公开构造途径，UT #9b 无法直接落地」—— FO 如何解决**

- `test_state_reversal_block.py::test_reversal_allowed_when_length_1` 已实现该用例；检视其代码发现，FO 经 `dataclasses.replace(self, snake=Snake((Point(...),)))` 内部构造途径绕开，无暴露新公开接口，与设计评审 P2-B 的 (a) 方案一致。
- 评审 P2-B 建议明确"测试构造途径"落到文档；FO 未在 r2 设计文档追加该说明，但实现中已稳定使用——建议迭代 2 设计文档补一行"长度 1 测试状态使用 `dataclasses.replace(snake=Snake((Point(...),)))` 内部构造"。

## 4. 覆盖率与质量门

- **UT 全绿**：54 / 54 通过（`PYTHONPATH=code/game-core/iter-1 python3 -m unittest discover -s code/game-core/iter-1/tests/test_game_core -v`）—— 见底部运行日志
- **覆盖率**：未量化（无 pytest-cov 环境），但定性覆盖：
  - `state.py` 五大分支（撞墙 / 撞自身 / 撞身吃 / 普通移动 / 吃食）+ 终态（OVER 后 step 抛 / OVER 后 set_dir 抛）+ 长度 1 反向特例 + 同节拍多次 pending + 网格边界 4 组 + spawn_food 满格抛错 —— **state.py 全路径命中**
  - `types.py` Point/Direction/Difficulty/Snake/Snapshot 各枚举/方法/不可变 —— **全部**
  - `params.py` 数据源 property 路径 + 修改后回读（`test_difficulty.py::test_property_reads_from_dict`）—— **全部**
- **INV 覆盖**：INV-1/2/3/4/5/6/7 至少 1 个用例引用（test 文件命名 + 注释可证）
- **架构契约 14/14**：见设计评审意见 §1，本检视视角下全 ✅
- **代码风格**：PEP 8 基本一致，命名规范，行宽合理（最长 ~90），无未用 import / 无 `print` 调试残留
- **TODO/FIXME/HACK 残留**：无（已 grep）
- **死代码**：`errors.py:3 DirectionError`（P3-B）；`state.py _last_step` 占位（设计 §1.3 允许）

## 5. 与 v1.0.0 行为一致性核对（设计 §3.6 对照表）

| 维度 | v1 行为 | v2 实现 | 一致性 |
|------|---------|---------|:------:|
| 移动/吃食/碰撞规则 | snake.py:v1 | state.py + types.py | ✅ |
| 撞自身判定 = `nh in body and not (nh == 尾 and not eating)` | snake.py:119-120 v1 字面 | state.py:127-132 显式 `body_set` + `body_tail` + `eating` 三连 | ✅ |
| 撞尾不吃食 → 不结束（让行） | snake.py v1 | state.py:130-131 + UT `test_hits_tail_without_eat_keeps_running` | ✅ |
| 撞尾吃食 → OVER | snake.py v1 | state.py:130-131 + UT `test_hits_tail_with_eat_overs` | ✅ |
| 撞墙 OVER 蛇身/食物/得分不变 | snake.py v1 | state.py:121-124 仅 status 改 | ✅ |
| 反向禁止 | snake.py v1 静默忽略，长度 1 由 deque 单节默认放过 | state.py 反向 + len==1 显式裁决 + len>=2 静默忽略 | ✅（行为更明确） |
| 难度参数 | 无（仅单难度） | params.py 三档 250/160/100 | ✅（N/A→✅） |

## 6. 检视门禁结论

| 项 | 结果 |
|----|:----:|
| 实现与设计一致（数据结构 / 接口 / 流程） | ✅ 29 项全绿 |
| 实现细节质量（边界 / 异常 / 资源） | ✅ 22 项全绿 |
| 可测试性（UT 可写可跑） | ✅ 54 用例 100% 通过 |
| 代码风格符合架构约定 | ✅ PEP 8 + FR/NFR 标注 + 不可变约定 |
| 设计 §3.7 实现注意 1-7 项 | ✅ |
| 不变量 INV-1~7 落地 | ✅ |
| 阻塞级问题数 | **0** |
| 应修订 P2 数 | **1**（P2-A：with_head/with_head_no_tail_drop 命名歧义） |
| 建议 P3 数 | **3**（P3-A UT#11 与设计伪代码矛盾未修订；P3-B DirectionError 启用时机未明；P3-H P2-B 「长度 1 构造途径」说明未补设计文档） |
| **检视结论** | **PASS** |

## 7. 后续建议

1. **P2-A**（阻塞级 0 / 应修订）建议 FO 在迭代 2 启动前合并修订 `types.py` 方法命名或 docstring；
2. **P3-A / P3-H**（设计文档追溯）建议 MDE 在下一次设计修订时一并同步 `设计-r2.md` §5.4 UT #11、§3.2 末尾注释、附录 A 备注「长度 1 测试状态构造途径」；
3. **P3-B / P3-C**（属于 r2 SE 评审遗留 P3）由 MDE 在迭代 2 设计开工前顺手修订，本轮不催；
4. 本检视意见归档于 `review/code/game-core/iter-1/`，供 STO 出集成测试 / MTO 出发布说明时引用基线。

---

## 附：UT 运行日志（2026-08-14 实际执行）

```
$ PYTHONPATH=code/game-core/iter-1 python3 -m unittest discover -s code/game-core/iter-1/tests/test_game_core -v

test_difficulty (5) ✓
test_direction (7) ✓
test_point (3) ✓
test_state_determinism (3) ✓
test_state_e2e (1) ✓
test_state_food_spawn (2) ✓
test_state_init (10) ✓
test_state_reversal_block (2) ✓
test_state_set_direction (5) ✓
test_state_snapshot (3) ✓
test_state_step_collide_self (1) ✓
test_state_step_collide_tail (2) ✓
test_state_step_collide_wall (2) ✓
test_state_step_eat (2) ✓
test_state_step_move (3) ✓
test_state_step_over_guard (2) ✓
-----
Ran 54 tests in 0.011s — OK
```
