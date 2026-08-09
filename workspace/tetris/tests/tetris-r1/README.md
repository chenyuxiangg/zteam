# tetris test 文件集（test 阶段第 1 轮产出，依据上游终版 testplan r2 / code r2）

- 需求：`tetris/tetris`｜依据测试方案：`workspace/testplans/tetris/tetris-r2.md`（终版）
- 被测代码：`workspace/code/tetris/tetris-r2/tetris.py`（终版，只读，本文件集不修改被测代码）
- 轮次说明：本目录为 **test 阶段第 1 轮产出**（目录名 `-r1`）；上游 plan/testplan/code 均已在多轮评审后
  落定为 r2 终版（code r2 与 code r1 核心逻辑一致、接口未变，README 自测记录佐证 71/71 回归通过），
  本文件集按 **testplan r2 口径**（时间类验收绝对值化：tick 偏差 / 软降 ×4 / 锁定与 HUD ≤100ms /
  按键 ≤50ms P95 / 暂停不吞时间）实现并实测。
- 测试要点：单元（模型层纯逻辑）+ PTY 集成（pexpect+pyte 屏幕仿真）+ 系统验收（脚本+人工清单）+ 性能，
  覆盖测试方案 TC-U-01~20 / TC-I-01~16 / TC-S-01~06 / TC-P-01~03。

## 一、运行方式

```bash
# 单元测试（pytest，无 TTY 依赖，可全量确定性自动化）
python3 -m pytest tests/tetris/tetris-r1/test_*.py -v

# 集成测试（PTY 端到端，16 个用例；需真实/伪终端分配能力）
bash tests/tetris/tetris-r1/e2e_tetris.sh        # 或 python3 e2e_tetris.py

# 系统验收（半自动：脚本部分 5 项 + 人工清单 system_checklist.md）
python3 tests/tetris/tetris-r1/sys_acceptance.py

# 性能测试（TC-P-01 输入延迟 / TC-P-02 资源占用，约 70-90 秒）
bash tests/tetris/tetris-r1/perf_tetris.sh       # 或 python3 perf_tetris.py

# 人工清单（TC-S-01 完整一局 / TC-S-02 README 走查 / TC-S-03 终端矩阵 /
#           TC-S-05 可读性 / TC-S-06 多版本 / TC-P-03 目测）
# 打开 system_checklist.md 逐项勾选留痕
```

说明：集成/性能脚本需 `pexpect` 与 `pyte`（仅测试侧依赖，安装于测试环境，不影响交付物「运行时零第三方依赖」）；本机已装（pytest 9.1.1 / pexpect 4.9.0 / pyte 0.8.2）。

## 二、依赖

| 依赖 | 用途 | 性质 |
|------|------|------|
| python3（3.6+ 语义） | 运行被测代码与全部脚本 | 系统自带 |
| pytest | 单元测试运行器 | 测试侧依赖 |
| pexpect | PTY 驱动（按键注入/信号/termios） | 测试侧依赖 |
| pyte | 终端屏幕仿真（文本/颜色断言） | 测试侧依赖 |

安装（国内镜像）：`python3 -m pip install pytest pexpect pyte --index-url https://pypi.tuna.tsinghua.edu.cn/simple`
（pyte 清华镜像暂缺时：`python3 -m pip install pyte`）

## 三、结果判定标准（对齐测试方案 §2 通过标准，r2 口径）

1. 单元层：pytest 全绿、无跳过（本目录 test_*.py，含 TC-U-01~20）；
2. 集成层：`e2e_tetris.py` 全部 16 用例 PASS（TC-I-01~16），其中
   `termios.tcgetattr` 退出前后关键项（ECHO/ICANON）恢复为开启（TC-I-08/16）；
3. 系统层：`sys_acceptance.py` 5 项 PASS（含 TC-S-02 的 r2 增量核对：
   README 选型结论 / 42×26 推导 / 单文件分层声明）+ `system_checklist.md` 人工清单逐项打勾，
   无「未验证」项遗留；
4. 性能层：`perf_tetris.py` 两项 PASS——
   TC-P-01 输入延迟 **≤ 50ms（P95，r2 绝对值口径）**，细粒度轮询 ≤10ms，测量含
   pyte 轮询/pexpect 调度/curses 渲染周期开销，以「含测量开销仍达标」为通过基准；
   TC-P-02 60s 内 CPU ≤ 5% 单核、RSS ≤ 50MB；TC-P-03 人工目测；
   **TC-P-01/02 为建议项（analysis r2 R1-04 标注，NFR-01/02），非发布阻塞**；
5. **任一 P0 用例失败 = 发布阻塞**；P2 失败不阻塞（记录缺陷单）。

## 四、与测试方案用例映射

| 测试文件 | 覆盖用例 | 关联需求 |
|----------|---------|---------|
| `test_tetrominoes.py` | TC-U-01（7 方块定义/格数/标准形状，§4.2 坐标表基准）、TC-U-02（旋转还原/I 横竖/O 不变/T 90°） | FR-05/FR-09 |
| `test_game_state.py` | TC-U-03~15、TC-U-18~20（生成/下落/移动/旋转/硬降/锁定/消行 1/2/4 行/计分表/等级速度/撞顶/软降/next/暂停/差一格不满/负 y 越界/计分累计；TC-U-15 为 r2 收紧确定断言：PAUSED 期间 step/move/rotate/soft_drop/hard_drop 全部无副作用） | FR-06~16、FR-19、FR-21 |
| `test_config.py` | TC-U-16（tick 50/2000/500 生效、49/2001/abc/-100 报错 exit 2、默认 500）、TC-U-17（--no-color） | FR-03、FR-26 |
| `test_input.py` | TC-I-06 单元面（WASD/方向键/空格/P/q 映射、无效键 None、KEY_RESIZE） | FR-18、FR-20、FR-04 |
| `e2e_tetris.py` | TC-I-01~16（单命令启动/非 TTY/小终端/tick 速度对比/玩法闭环/双键位/q 退出/SIGINT 三时机/SIGTERM/HUD/结束画面/暂停/Resize/next/--no-color/termios 恢复） | FR-01~24、NFR-01~04 |
| `sys_acceptance.py` | TC-S-01（子场景）/S-02（含 r2 增量核对）/S-04/S-05（结构部分）/S-06（本机部分） | FR-01/25、NFR-04/05、Q-05 |
| `system_checklist.md` | TC-S-01（完整一局）/S-02（README 走查）/S-03/S-05（人工走查）/S-06（多版本实机）/TC-P-03 | FR-01/25、NFR-05/06、Q-05、NFR-01 |
| `perf_tetris.py` | TC-P-01（输入延迟采样≥20，细粒度轮询≤10ms，≤50ms P95）、TC-P-02（60s CPU/RSS 每 5s 采样） | NFR-01/02（建议项） |

### 范围外（测试方案 §1 声明，本文件集不测）

- 软降/硬降加分（FR-17，Q-01 默认不加分 → 作废）；SRS/wall kick（Q-02 简化旋转）；
  7-bag 随机与 lock delay（Q-03 纯随机）；分数持久化/键位自定义/再来一局（Q-08/12/13）；
  图形/联网/多人/音效；Windows/macOS。
- 超时/重试/并发/资源耗尽：不适用（本地单进程、无网络 I/O、单线程无并发面；
  输入超时由 curses timeout(25) 轮询机制天然覆盖，方案 §3.3 已声明）。

## 五、运行结果记录（本轮实测，本机）

| 层 | 结果 | 备注 |
|----|------|------|
| 单元（pytest） | 72/72 PASS | 含 TC-U-01~20 全量 + r2 收紧新增 `test_tc_u15_paused_no_side_effects`；0.09s |
| 集成（e2e_tetris.py） | 16/16 PASS | 54.6s；TC-I-04 速度对比 tick1000=2 次 vs tick50=15 次；SIGINT/SIGTERM 三时机 termios 全部恢复；q 退出 0.06s |
| 系统（sys_acceptance.py） | 5/5 PASS | README 五节齐全 + r2 增量核对（选型结论/42×26 推导/单文件分层声明）全 True；非 TTY/非法参数无 traceback；分层结构齐全；py_compile 通过、无 3.7+ 语法 |
| 性能（perf_tetris.py） | 2/2 PASS | TC-P-01 n=20 avg=13.2ms p95=14.0ms ≤ 50ms（r2 细粒度轮询 ≤10ms 口径，含测量开销仍达标）；TC-P-02 avg_cpu=1.81%、peak_rss=17.3MB ≤ 50MB；均为建议项 |
| 人工清单 | 待验收人执行 | system_checklist.md（TC-S-01 完整一局/TC-S-02 README 走查/TC-S-03 终端矩阵/TC-S-05 走查/TC-S-06 多版本/TC-P-03 目测） |

### 本轮相对 r1 测试集的变更（对应 testplan r2 增量）

1. 被测代码指向 `code/tetris/tetris-r2/`（conftest/e2e/sys/perf 四处路径）；
2. TC-U-15 收紧为确定断言：PAUSED 期间 step/move/rotate/soft_drop/hard_drop 全部无副作用，
   状态/坐标/旋转/得分/消行/board 不变（方案 §3.2 TC-U-15 r2 口径，新增
   `test_tc_u15_paused_no_side_effects`）；
3. TC-P-01 按 r2 口径重写：`time.monotonic()` send 前 t0 → 屏幕内容确认生效后 t1 → 差值；
   细粒度轮询 ≤10ms（r1 为 50ms）；判定阈值 **≤50ms P95**（r1 为 ≤1 tick=500ms）；
   左右移交替发送避免贴壁拒绝无效采样；测量开销与真实延迟分离记录；
4. TC-S-02 增加 r2 增量核对（README 选型结论/42×26 推导/单文件分层声明）；
   system_checklist.md 新增 TC-S-02 走查项与 TC-S-05 第 5 项（单文件分层声明口径）；
5. TC-P-01/02 明确标注建议项（非发布阻塞，analysis r2 R1-04）。

### 发现的被测代码行为说明（供评审参考，非缺陷结论）

1. **尺寸不足提示为英文**：`Terminal too small: need at least 42x26...`（测试方案 TC-I-03 断言
   「可读提示 + 非零退出」，未要求中文；README 亦以英文描述。若评审要求 NFR-04「人类可读」
   严格中文口径，属可改进项）。
2. **输入延迟测量含测量开销**（pyte 轮询粒度 + pexpect 调度 + curses timeout(25) 渲染周期），
   实测数据为「含测量开销」口径，真实事件驱动延迟为毫秒级（r2 起细粒度轮询 ≤10ms 复测并留痕）。

## 六、文件清单

```
tests/tetris/tetris-r1/
├── README.md              本说明（运行方式/依赖/判定标准/用例映射/运行记录）
├── conftest.py            pytest 配置：被测代码路径注入（code r2）
├── test_tetrominoes.py    单元：TC-U-01/02（7 方块 + 旋转）
├── test_game_state.py     单元：TC-U-03~15、18~20（GameState 全逻辑，TC-U-15 r2 收紧）
├── test_config.py         单元：TC-U-16/17（parse_args）
├── test_input.py          单元：TC-I-06 单元面（InputHandler 键位映射）
├── e2e_tetris.py          集成：TC-I-01~16（pexpect+pyte，屏幕/termios/退出码断言）
├── e2e_tetris.sh          集成入口薄壳
├── sys_acceptance.py      系统验收脚本：TC-S-01~06 可自动化部分（含 r2 增量核对）
├── system_checklist.md    人工验收清单：TC-S/TC-P-03 逐项勾选
├── perf_tetris.py         性能：TC-P-01/02（r2 细粒度口径）
├── perf_tetris.sh         性能入口薄壳
└── results/               运行日志目录（r1-regression.log 为旧轮留痕，r2-regression.log 为本轮）
```
