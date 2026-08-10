# 代码评审：pacman（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：方案逐条落地，编译/CLI/FR-02/FR-07/FR-08/FR-09/FR-10/FR-11/FR-12/FR-13 端到端抽测全数命中，2 条建议级意见不阻塞。
- 评审轮次：r1

## 1. 检查清单核对表
| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | 模块/接口/数据模型与方案 §3.1/§3.2/§4.2/§5.1 一致（`Dir`/`Kind`/`Mode` 枚举、`Pos`/`Mover`/`Player`/`Ghost`/`GameState`/`FinalScore`/`Status`、`target_cell` 按 kind 分派 4 个分支、`choose_dir` 曼哈顿+`DIR_PRIORITY` 平局、`ModeController` 交替）；8 模块均落盘（`__init__/__main__/config/map/entities/ghost_ai/game/input/main/renderer` + `data/map_classic.txt` + `requirements.txt` + `run.py`），无未实现项；方案 §5.4 难度公式（`ghost_speed_for_level`/`power_duration_for_level`/`scatter_duration_for_level`/`elroy_threshold_for_level`/`inky_release_dots_for_level`/`clyde_release_dots_for_level`）逐函数实现，公式与表一致 |
| 2 | 可运行 | PASS | `python3 -m compileall pacman/` 0 退出；`python3 -m pacman --help` 正常输出全部选项；三个入口（`__main__`/`main.py`/`run.py`）一致指向 `main_cli`；非 TTY/非法地图/参数越界均明确报错退出（exit 1/2）；逻辑层（config/map/entities/ghost_ai/game/input）grep 无 curses 依赖，可独立单测（FR-19/NFR-02/NFR-05） |
| 3 | 功能正确性 | PASS | 逐 FR 抽测如下——**FR-02** 地图 `load_map('pacman/data/map_classic.txt')` → 19×22 / `initial_dots=216` / `player_spawn=(12, 9)` 与方案 §4.3 一致；**FR-06** `_handle_dot_eating()` 普通豆 `score +=10` 验证；**FR-07** 吃能量豆 `score=50`/`power_timer=6.0`、全部幽灵→`FRIGHTENED`、连吃 4 只依次 +200/+400/+800/+1600、第 5 只封顶 1600、限时结束恢复 `CHASE`、保护期内撞幽灵不判定；**FR-08** `dots_left=1 → 0` 触发 `_next_level` level+1、tiles 恢复、`dots_left=initial_dots`；**FR-09** 撞 `CHASE` 幽灵 lives-1、保护期不判定、命归零→`Status.GAME_OVER`+结算 `FinalScore(score, level, ghosts_eaten)`；**FR-10** 同局面四幽灵 `target_cell` 互异集合 `{(5,5), (5,9), (7,11), (18,1)}`（规则实现互异），Pinky UP-bug `(1,1)` 与 Dossier 期望（前方 4 格 + UP 左偏 4）完全一致，Clyde 远（≥8）追玩家 / 近（<8）撤回家角落 双态正确 |
| 4 | 边界与异常 | PASS | 终端 <80×24 触发 `_draw_too_small()` 居中提示并按任意键退（`main.py` `_game_loop` + `Renderer._draw_too_small`）；非 TTY `_check_tty()` 报错 exit 1；暂停时 `Game.tick()` 直接 `return`；地图校验覆盖行宽不一致、非法字符、缺 P、能量豆 <4、缺 H、缺 -、鬼屋未封闭、鬼屋门未连通、`load_map` 任意 `--map` 均走 `_parse_grid`→`_check_basic`→`_check_house_enclosed`→`_validate_connectivity`（FR-03 三项离线判定 + 加载期强制执行）；`--ghosts 1/5 --speed 0/3 --lives 0/10 --level 0` 全部拒绝（`_parse_args` 自定义校验 + argparse） |
| 5 | 安全与合规 | PASS | `grep -E "^(import\|from) (socket\|urllib\|requests\|http\.client\|httpx\|aiohttp)"` 8 模块均「无」；不读写用户文件（README §1/§8 明示 Q7 不做持久化）；不 import curses 进入逻辑层；权限无需提升（无 sudo/特权调用） |
| 6 | 可读可维护 | PASS | 所有模块顶部 docstring 标注「职责/依赖/对应方案节」；命名与方案同构（`target_cell`/`choose_dir`/`phase_duration` 等）；实体数据类 `dataclass` + `Enum`；关键逻辑（`target_cell` 分派 4 分支、Pinky UP-bug、Elroy、出场阈值、状态机）有行内注释指向 §5.1 / §5.4 / §4.4；`tile_char_color`/`ghost_char_color` 与 tile 语义一一对应 |
| 7 | 错误处理 | PASS | `main_cli` 捕获 `KeyboardInterrupt`/`Exception` 统一退出；`Renderer._safe_add` 包装 `curses.error`（continue 不中断主循环）；地图加载 `MapError` 含行/列定位（`_load_map_file`/`_parse_grid`/`_check_basic`/`_check_house_enclosed`/`_validate_connectivity` 全部 raise `MapError(msg, line, col)`）；非法 CLI 报错带合法范围提示。**建议 1**（见下） |
| 8 | 性能与资源 | PASS | 主循环 `time.monotonic` + `screen.timeout(20)` + `time.sleep(剩余)` 避免累积漂移（`main.py` `_game_loop`）；`Mover.add_motion` 速度累积封顶 4 格防调试器停顿后跳帧（`entities.py`）；无文件/线程/句柄持有（FRIGHTENED 用模块级 `random.choice`，可注入见 `game._random_ghost_dir`）；暂停相位补偿 `Game._pause_accum`（`game.py`）保证计时器不漂移 |
| 9 | 不越界 | PASS | 代码目录 `code/pacman-r1/` 仅含源码/README/requirements/run.py/`__pycache__`，**无 `tests/` 目录**，符合 code 阶段红线（test 阶段独立）；未修改 `analysis/`、`plans/`、`testplans/`、`input/`；CLI 输出仅 stderr 中文错误，不写用户数据 |
| 10 | 可审计 | PASS | 产物路径为 `code/pacman-r1/`（本轮新目录，与 archive 中 requeue 前产物 `code-pacman-r1-pre-requeue/` 隔离）；`requirements.txt` 仅注释行（声明空依赖，与方案 NFR-05 一致）；README §10「验收对照」逐项指向真实存在的函数/方法（grep `def load_map`/`def consume_turn`/`def target_cell`/`def apply_mode_transition`/`def _draw_map` 全部命中）；修改回应表留空（首轮） |

## 2. 评审意见列表
- **[严重]** 无
- **[一般]** 无
- **[建议]** 2 条
  1. `pacman/renderer.py:72` 颜色初始化行存在嵌套 `if False else` 死代码样式：
     `curses.init_pair(COLOR_CLYDE, curses.COLOR_YELLOW | curses.COLOR_RED if False else 208, -1) if False else curses.init_pair(COLOR_CLYDE, curses.COLOR_YELLOW, -1)`。实质等价于 `curses.init_pair(COLOR_CLYDE, curses.COLOR_YELLOW, -1)`，功能正确（Clyde 渲染黄色），但可读性差——推测为开发者中途编辑残留。建议下次清理为一行直白调用，便于维护与静态分析。
  2. `pacman/config.py:140-143` `SCATTER_CHASE_SCHEDULE` 常量定义但**未被任何模块引用**（grep 仅 config.py 自身一处）。模式切换实由 `ModeController.step()` + `PHASE_COUNT` + `scatter_duration_for_level`/`chase_duration_for_level` 驱动，功能完整。建议删除该常量或加注释说明其为「方案原版全表参考、未启用」（避免误以为存在但未被发现的切换表）。

## 3. 遗留事项（仅 PASS 时）
- 方案已声明的简化项（README §8）需在 release 阶段的 release notes 中再给一次用户视角说明：Blinky 同屋出生、Elroy 阈值采用简化公式、能量时长下限 1s、计分采用原版序列、Pinky/Inky 向上偏移 bug 忠实复刻、不做最高分持久化。
- 自动化测试代码不在本 code 阶段产物内（按角色红线交由 test-developer 落地）；本次评审以可独立 import 的逻辑层做了抽测断言（FR-10 主验收 + FR-07 能量豆闭环 + FR-08 过关 + FR-09 扣命 + FR-11 模式状态机 + FR-12/FR-13 数量与重置），完整 FR-N 映射见 `testplans/pacman-r1.md`，待 test 阶段补齐。
- renderer.py:72 `if False else` 死代码样式 + config.py:140 `SCATTER_CHASE_SCHEDULE` 死代码（建议 1/2）作为后续清理点登记，不阻塞。