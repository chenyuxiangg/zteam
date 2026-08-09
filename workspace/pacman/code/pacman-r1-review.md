# 代码评审：pacman（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：方案逐条落地，编译通过，FR-10 四目标互异与 Pinky up-bug 实测命中 Dossier 期望，FR-07 能量豆反击正确闭环，可运行可审计可独立单测。
- 评审轮次：r1

## 1. 检查清单核对表
| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | 模块/接口/数据模型与方案 §3.1/§3.2/§4.2/§5.1 一致（`config.Map*`/Mover/GhostMode 枚举、`GameStatus`、target_cell 分派）；8 个模块均落盘（`__init__/__main__/config/map/entities/ghost_ai/game/input/main/renderer`+`data/map_classic.txt`），无未实现项 |
| 2 | 可运行 | PASS | `python3 -m compileall pacman/` 0 退出；`python3 -m pacman --help` 正常；三个入口（`__main__`/`main.py`/`run.py`）均导入一致（README §2）；非 TTY/非法地图/参数越界均明确报错退出 1；逻辑层（config/map/entities/ghost_ai/game/input）grep 无 curses 依赖，可独立单测（README §7、NFR-02/05） |
| 3 | 功能正确性 | PASS | 逐 FR 抽测如下——FR-02 地图 22×19 / 216 豆 / 玩家 (12,9–10) / 鬼屋中点 (9,11) / 门 (10,11) 全数命中；FR-06 吃豆 score+10 验证；FR-07 吃能量豆全体 FRIGHTENED + 撞 FRIGHTENED score+200/eaten_chain+1/模式→EYES；FR-08 全清豆触发 `_next_level`；FR-09 扣命 `protection_timer=2.0`；FR-10 同一局面四目标 4/4 互异（Blinky=玩家位、Pinky=(6,6)、Inky=(13,6)、Clyde=角落）；Pinky up-bug 实测 (6,6) 与 Dossier 期望完全一致（up=前方 4 格 + 左偏 4） |
| 4 | 边界与异常 | PASS | 终端 <80×24 触发 `TerminalTooSmall` 居中提示并按任意键退（main.py + renderer.py）；非 TTY 报错 exit 1；暂停时 `update` 直接 `return`；地图校验覆盖 5×5 下限 / 行宽 / 非法字符 / 缺 P / 能量豆不足 / 缺 H / 缺 - / 豆 <100 / 鬼屋未封闭 / 通道不连通（全在 `map.py`）；`--ghosts 1/5 --speed 0/3 --lives 0/10` 全部拒绝（argparse + custom type） |
| 5 | 安全与合规 | PASS | `grep "^\\s*(import\\|from) (socket\|urllib\|requests\|...)"` 8 模块均「无」；不读写用户文件（README §1/§8）；不 import curses 进入逻辑层；权限无需提升（README §1） |
| 6 | 可读可维护 | PASS | 所有模块顶部有 docstring 标注「职责/依赖/对应方案节」；命名与方案同构（target_cell/choose_direction/phase_duration 等）；实体数据类 dataclass + Enum；关键逻辑（target_cell/Pinky bug/Elroy/出场阈值/状态机）有注释指向 §5.1 / §5.4 |
| 7 | 错误处理 | PASS | `main_cli` 捕获 `KeyboardInterrupt`/curses.error 统一退出；`Renderer._safe_add` 包装 `curses.error`（continue 不中断）；地图加载 `MapError` 行列定位；非法 CLI 报错带 help 提示。**建议**：`_safe_add` 当前仅 passthrough，可追加 WARN 日志（建议级，不阻塞） |
| 8 | 性能与资源 | PASS | 主循环 `time.monotonic` + `screen.timeout(20)` + `time.sleep(剩余)`，避免累积漂移；`player/ghost.add_motion` 返回 0~4 步封顶防调试器停顿后跳帧（`entities.py`）；无文件/线程/句柄持有（FRIGHTENED 随机游走用 `random.Random(seed)` 可注入） |
| 9 | 不越界 | PASS | 代码目录 `pacman/pacman-r1/` 仅含源码/README/requirements/run.py/`__pycache__`，**无 `tests/` 目录**，符合 code 阶段红线（test 阶段独立）；未修改 `analysis/`、`plans/`、`testplans/`、`input/`；CLI 输出仅 stderr 中文错误，不写用户数据 |
| 10 | 可审计 | PASS | 产物路径为 `code/pacman-r1/`（首轮新目录，未覆盖）；requirements.txt 仅注释行（声明空依赖，与方案 NFR-05 一致）；README §9「开发者自检」给出本阶段可运行验证命令；修改回应表留空（首轮） |

## 2. 评审意见列表
- **[严重]** 无
- **[一般]** 无
- **[建议]** 1 条
  1. `pacman/renderer.py:165` `Renderer._safe_add` 当前对 `curses.error` 仅 pass 不画，建议下次迭代加一条 `logging.warning(...)` 或 stderr 一行（仅在 dev/debug 模式可启用），便于追踪终端渲染异常。当前不影响正确性，仅影响可观测性。

## 3. 遗留事项（仅 PASS 时）
- 方案已声明的简化项（README §5/§8）需在 release 阶段的 release notes 中再给一次用户视角说明：Blinky 同屋出生、Elroy 阈值采用简化公式、能量时长下限 1s、计分采用原版序列。
- 自动化测试代码不在本 code 阶段产物内（按角色红线交由 test-developer 落地）；本次评审仅以可独立 import 的逻辑层做了抽测断言（产物一致性 + FR-10 + 公式边界 + 异常），完整 FR-N 映射见 `testplans/pacman-r1.md`，待 test 阶段补齐。
- `_safe_add` 静默吞 `curses.error`（建议 1）作为后续改进点登记，不阻塞。
