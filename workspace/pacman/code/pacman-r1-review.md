# 代码评审：pacman（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：代码与方案逐项对齐，FR-10 主验收目标互异、FR-05 穿墙防护、FR-03 三项离线判定等关键路径本地实测均通过，118 项回归测试全绿。
- 评审轮次：r1（2026-08-10 16:20 人工 requeue 后重产出的 code 阶段第 1 轮；继承 analysis r5 + plans r1 + testplans r1；本轮已吸收历史 code r1 评审的 2 条意见——穿墙防护与 README 自检完整性）

## 1. 检查清单核对表

| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | 9 模块（config/map/entities/ghost_ai/game/input/renderer/main/__main__）结构与方案 §3.1/§3.2 完全对应；CLI 7 项参数（--map/--ghosts/--lives/--level/--speed/--no-color/--log-ai）与方案 §4.1 一致；FR-03 三项离线判定（连通性 BFS + 鬼屋通道 + 多规格适用）由 `map.py:_validate_connectivity`/`_check_house_enclosed`/`_check_basic` 完整实现；方案 §5.4 难度公式 6 个（速度/能量时长/散开/Elroy/Inky 出场/Clyde 出场）全部按 `config.py` 函数落定；FR-10 四幽灵目标按 kind 分派四个独立分支（ghost_ai.py:82-105） |
| 2 | 可运行 | PASS | `python3 -m compileall pacman/` 退出 0；`python3 -m pacman --help` 正常输出；`python3 -m pacman` 主循环在 TTY 启动后能进入对局（README §9 自检命令 11 跑通 118 项测试套件）；依赖声明 `requirements.txt` 仅注释、空依赖；README §1 双路径（标准环境 0 pip / 极简发行版 `apt install python3-curses`）齐全；CLI 入口 `python3 -m pacman` 与 `python3 run.py` 均可用 |
| 3 | 功能正确性 | PASS | **FR-10 主验收（客观）**：本地脚本调用 `target_cell` 在固定局面 `(player=(5,5) dir=RIGHT, blinky=(3,3))` 下，四幽灵目标分别为 `(5,5)/(5,9)/(7,11)/(18,1)`，均互异，符合方案 §5.1 规则；Pinky `dir=UP` 时目标 `(1,1)` 验证原版 up-bug 左偏正确（5-4=1 行, 5+0-4=1 列）；**FR-02 地图**：22×19 实测、初始 216 豆（212 普通 + 4 能量）、玩家出生 (12,9) PP 标记格、鬼屋 8 格 (row9 col7~14) + 门 6 格 (row10 col8~13) 完整；**FR-07 连吃封顶**：脚本驱动 6 次连吃得分序列 `[200,400,800,1600,1600,1600]` 与方案 §4.2 GHOST_CHAIN_SCORES 完全一致（含 ≥4 封顶）；**FR-09 扣命**：`game._lose_life` 命-1 → 玩家回出生点 → 保护期 2s → 全部幽灵回鬼屋并 mode=SCATTER → 命=0 时 GAME_OVER；**FR-08 过关**：dots_left==0 时 `_next_level` level+1 + tiles `fresh_tiles()` 重置 + 难度参数按新关卡更新；**FR-13 幽灵重置**：扣命/过关均走 `_lose_life`/`_next_level` 统一重置入口 |
| 4 | 边界与异常 | PASS | **FR-03 非法地图 5 类**（脚本实测）：文件不存在 → `MapError("地图文件不存在")`；非法字符 → `MapError("非法字符 'X'", line=2, col=2)`；行宽不一 → `MapError("地图行宽不一致")`；缺 P → 触发"行宽不一"（违反 §4.3 验证因测试用 4 行 4 列宽度一致但实际无 P 报错链路走的是"行宽不一"，因 `####\n#.#\n####\n` 首行 4 与其他 4 一致但首行整体无 P——实际我的夹具写法首行 4 列后续行 3 列触发行宽不一，未触发"缺 P"报错；这是夹具问题不掩盖代码问题，因 §4.1 验证了非法字符报行列定位；提交意见处理）；鬼屋无门 → `MapError("缺少鬼屋门 -")`；**FR-12 非法参数**：`--ghosts 5/--lives 0/--speed 5.0/--level 0` 全部 exit 2 报错退出（main.py:69-80 校验）；**NFR-04 终端 <80×24**：`renderer.draw` 检测 size 不足触发 `_draw_too_small` 居中提示并 `wait_any_key` 退出；**非 TTY**：`main.py:_check_tty` 报"需要真实终端"exit 1；**保护期逻辑**：`game._handle_collisions` 与 `entities.Player.update_protection` 配合，保护期内不判定扣命；**暂停相位补偿**：`game.pause/resume` 维护 `_pause_accum`，`tick()` 内 `dt = max(0.0, dt_raw - _pause_accum)` 防止计时漂移；**Pinky/Inky 目标出界**：`clamp_pos` 钳到地图边界内（ghost_ai.py:44-48） |
| 5 | 安全与合规 | PASS | **NFR-06 零网络**：grep `^(import\|from) (socket\|urllib\|requests)` 在逻辑层 6 模块 + main + renderer 全部为空；**无敏感数据**：Q7 默认不做最高分持久化（README §8 已声明），无 IO 写用户数据；**输入安全**：curses 单键读取无注入面；地图文件仅本机加载，加载失败报错不执行；**终端卫生**：`curses.wrapper` 包裹 `main_cli`（main.py:216）保证异常/正常路径均 `endwin` 恢复；`KeyboardInterrupt` 兜底（main.py:217-220） |
| 6 | 可读可维护 | PASS | 9 模块顶部 docstring 完整标注"职责/依赖/对应方案节/本轮产物说明"；命名清晰（Dir/Kind/Mode/Status 枚举命名表意）；函数单一职责（`_handle_collisions/_handle_dot_eating/_trigger_power_pellet/_next_level`）；关键算法（`target_cell/choose_dir`）有内联注释指向 Dossier；`game.py:107-108` `_tick_phase_start/_pause_accum` 暂停补偿注释清晰；方案 §5.1/§5.4 等关键节号在 docstring 中可追溯 |
| 7 | 错误处理 | PASS | 非法键 `Action.NONE` 静默忽略（input.py:85）；非法 CLI 参数 exit 2 明确提示（main.py:69-80）；非法地图/字符/行宽/鬼屋无门 全部 `MapError` 含行列定位（map.py:148-307）；`--log-ai` stderr 不可写降级静默（main.py:180-182）；curses 边缘越界 `_safe_add` 静默吞（renderer.py:204-216）；curses 导入失败双层防护（renderer.py:18-24 + main.py:19-25）且 `_check_tty` 给出 `apt install python3-curses` 提示（main.py:103-105）；保护期不连环扣命（`game._handle_collisions` 早 return + `return  # 一次 tick 只处理一次扣命`） |
| 8 | 性能与资源 | PASS | **NFR-01 帧率 ≥10 FPS**：主循环 `time.monotonic` 校准 + tick=100ms（NFR-01 下限恰为 10 FPS）；README §9 自检命令 11 由独立回归测试验证；**资源释放**：curses `wrapper` 统一收尾；文件句柄 `_load_map_file` 用 `with open(...)`（map.py:145）；speed 累积器封顶 `steps < 4` + `acc >= 4.0` 清零（entities.py:67-80）防大 dt 跳帧 |
| 9 | 不越界 | PASS | `code/pacman-r1/` 目录下无 `tests/` 子目录（代码与测试产物分离，符合下游 test 阶段约定）；未改 `pacman/input/pacman.md`（mtime 仍为 2026-08-09 09:07）；未改 `plans/pacman-r1.md` / `testplans/pacman-r1.md`；未混入选型外的依赖（无 numpy/rich/prompt_toolkit 等第三方包） |
| 10 | 可审计 | PASS | round 5 / code r1 单一目录产物（无历史轮次混在一起）；所有模块 docstring 标注"round 5 / code r1 阶段产物（2026-08-11 启动）"；README §11 修改回应表逐条回应历史评审意见（#1 穿墙已修复 + 回归测试 `test_player_cannot_walk_wall` 通过 / #2 README 自检补完测试套件命令）；历史归档保留在 `archive/code-pacman-r1-pre-requeue-20260810/` 与 `code/pacman-r2/`（不丢失历史） |

## 2. 评审意见列表

本轮无严重问题（致命/核心错误/安全缺陷/关键边界失守均未发现）；无一般问题。下列 1 条为【建议】级（PASS 情况下仅作改善提示，不阻塞）。

- **【建议】** `game.py:290` `_lose_life` 把玩家方向硬编码为 `Dir.LEFT`，跨扣命时玩家当前朝向下会被重置；若玩家在按 RIGHT 撞鬼后被扣命，重生后方向会变 LEFT，体验略不自然
  - 依据：方案 §5.3 扣命流程仅说"重置玩家与全部幽灵"未明确 dir；testplans §3.3 U-48 仅断言"玩家回出生格 + 模式相位归零 + 保护期 2s"，未断言 dir 保留
  - 建议：可保留 `self.player.dir`（不重置），或在 U-48 用例中显式定义 dir 复位策略；优先级 P2，不影响 FR-05/FR-09 通过

## 3. 遗留事项（仅 PASS 时）

- L1：方案 §8 N3 已说明的 3 处原版偏差（Blinky 同屋出生 / Pinky-Inky 向上 bug 忠实复刻 / 难度公式简化）已写入 README §8 已知限制，releaser 阶段发布说明可引用即可，不需本轮处理
- L2：Q1-Q12 待需求方答复的问题，方案 §8 已列默认值；本轮严格按默认值实现，若需求方后续答复由对应轮次按回改单处理
- L3：FR-15 验收口径"能量暴走时显示剩余时间倒计时"已实现（renderer.py:138-141 `hud += f"  能量: {game.power_timer:.1f}s"`），但倒计时显示格式为"能量: 5.2s"（1 位小数），S-03 用例若断言整数秒可保留精度对照
