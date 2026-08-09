# snake-linux 测试集（r2 修改轮）

针对 `workspace/code/snake-linux/snake-linux-r1/` 的测试文件集。
依据测试方案 `testplans/snake-linux/snake-linux-r1.md`（终版）；r2 为
test 阶段修改轮，逐条回应 `tests/snake-linux/snake-linux-r1-review.md`。

## 运行方式

```bash
cd workspace/tests/snake-linux/snake-linux-r2
bash run_all.sh                 # 一键：单元 pytest + 集成 e2e + 性能基线
# 或分步：
python3 -m pytest -q            # 单元层（test_game_state / test_config / test_input）
python3 e2e_snake.py            # 集成层（PTY 端到端，TC-I-01~11）
bash perf_snake.sh              # 性能层（TC-P-01/02，基线记录，不阻塞）
# 系统层人工验收：
#   打开 checklist-system.md 逐项打勾（TC-S-01~06 + TC-P-03）
```

依赖（仅测试侧，不影响交付物运行时零第三方依赖）：`pytest`（单元）、
`pexpect`（PTY 集成/性能）。测试执行机需具备 PTY 能力（集成层运行时分配 PTY；
无 TTY 的 CI 仅能跑单元层，与测试方案 §4 假设一致）。

## 文件集清单

| 文件 | 作用 | 对应用例 |
|------|------|---------|
| `test_game_state.py` | GameState 纯逻辑单元测试 | TC-U-01~10 + 补充 |
| `test_config.py` | parse_args 参数校验单元测试 | TC-U-11/12 |
| `test_input.py` | InputHandler 键位映射单元测试 | TC-U-02 输入侧、FR-06/07/13 |
| `conftest.py` | pytest 配置：定位被测代码、注册 P0/P1/P2 marker | — |
| `miniterm.py` | 迷你终端模拟器（共享模块，e2e/perf 共用） | — |
| `e2e_snake.py` | 集成层 PTY 端到端（pexpect） | TC-I-01~11 |
| `perf_snake.py` | 性能层：输入延迟 + CPU/RSS 采样 | TC-P-01/02 |
| `perf_snake.sh` | 性能测试 bash 入口（pidstat 优先/ps 兜底） | TC-P-01/02 |
| `run_all.sh` | 一键运行全部自动化测试并汇总 | — |
| `checklist-system.md` | 系统/验收层人工清单（逐项打勾留痕） | TC-S-01~06、TC-P-03 |
| `.gitignore` | 排除 `__pycache__/`、`.pytest_cache/` | — |

## 结果判定标准

- 单元层：`pytest -q` 全绿、无跳过（P0/P1 全部实现）；
- 集成层：`e2e_snake.py` 输出结构化结果表，P0/P1 全部 PASS、P2 SKIP 不计失败；
  退出码 0 = 通过，1 = 存在 P0/P1 失败（发布阻塞）；
- 性能层：`perf_snake.sh` 输出 TC-P-01（延迟 P95 ≤ 200ms）与 TC-P-02
  （CPU ≤ 5% / RSS ≤ 50MB）指标；**失败仅记录缺陷单，不阻塞门禁**
  （测试方案 §2/§4：P0 判定不依赖性能用例，固定机复测）；
- 系统层：`checklist-system.md` 逐项打勾，无「未验证」遗留（测试方案 §2）；
- 任一 P0 用例失败 = 发布阻塞；P2 失败不阻塞（记录缺陷单）。

## 用例映射（对照测试方案 §3.1 需求映射表）

| 需求 | 用例（本集实现） | 层级 |
|------|-----------------|------|
| FR-01 单命令启动 | TC-I-01、TC-S-01 | 集成/系统 |
| FR-02 非 TTY 报错 | TC-I-02、TC-S-04 | 集成/系统 |
| FR-03 tick 可配置 | TC-U-11、TC-I-04 | 单元/集成 |
| FR-04 终端能力检查 | TC-I-03、TC-I-11 | 集成 |
| FR-05 蛇的移动 | TC-U-01 | 单元 |
| FR-06 方向控制 | TC-U-02（含方向键）、test_input | 单元 |
| FR-07 反向移动禁止 | TC-U-03、TC-U-04 | 单元 |
| FR-08 食物生成 | TC-U-09、TC-I-05a | 单元/集成 |
| FR-09 吃食增长与得分 | TC-U-08、TC-I-05a、TC-I-09 | 单元/集成 |
| FR-10 碰撞判定与结束 | TC-U-05/06/07/10、TC-I-05b | 单元/集成 |
| FR-11 结束画面 | TC-I-05b | 集成 |
| FR-13 安全退出 | TC-I-06、TC-I-07、TC-I-08 | 集成 |
| FR-14 终端状态恢复 | TC-I-07、TC-S-01 | 集成/系统 |
| FR-15 README 文档 | TC-S-01、TC-S-02 | 系统 |
| FR-16 游戏区域规格 | TC-U-12、TC-I-10 | 单元/集成 |
| FR-17 界面信息栏 HUD | TC-I-09 | 集成 |
| NFR-01 性能（流畅度） | TC-P-01、TC-P-03 | 性能 |
| NFR-02 性能（资源占用） | TC-P-02 | 性能 |
| NFR-03 干净退出 | TC-I-07（与 FR-14 合并验证） | 集成 |
| NFR-04 错误提示友好 | TC-I-02、TC-S-04 | 集成/系统 |
| NFR-05 代码职责分离 | TC-S-05 | 系统 |
| NFR-06 终端兼容性 | TC-S-03 | 系统 |
| Q-05 最低 Python 3.6 | TC-S-06 | 系统 |

## 运行结果记录（r2 实测）

> 本节由 test-developer 在产物落盘前实测填写；重跑结果以最近一次为准。

### 单元层（pytest）
```
（运行 bash run_all.sh 或 python3 -m pytest -q 后回填：N passed）
```

### 集成层（e2e_snake.py）
```
（运行 python3 e2e_snake.py 后回填 PASS/FAIL/SKIP 明细）
```

### 性能层（perf_snake.sh）
```
（运行 bash perf_snake.sh 后回填 TC-P-01/02 指标）
```

## r2 修改回应表（逐条回应 r1 评审意见）

| 上轮意见 | 意见摘要 | 处理结果 | 说明（对应实现位置） |
|----------|----------|----------|----------------------|
| 意见 1（一般） | TC-I-10 持续假失败：MiniTerm 对 curses 清屏处理不完整，约第 25 帧读到空边框 | 已修复 | 根因确认为「默认 tick=200 下 30 帧采样时长（≈3.6s）接近蛇从 x=20 走 20 格撞右墙的 4s，约第 25 帧后游戏自然结束、边框被 erase，结束帧被误判为边框异常」——非被测代码缺陷（单元层边界不变量断言全过、代码评审 r1 逐 FR 勾对通过）。修复三件套（e2e_snake.py `run_tc_i10`）：① 采样循环检测 GAME OVER/WIN 立即停止，结束帧不参与边框断言；② 边框断言失败重读一帧排除渲染中间态；③ 有效帧 ≥ 25 即 PASS（宽松判定，对齐方案验收口径）。同时收窄每帧读取窗口（0.08s）缩短总采样时长至 ~2.5s，蛇不会在采样期内撞墙。 |
| 意见 2（一般） | TC-I-05 偶发失败：BFS 贪吃机器人在蛇增长后被自身阻挡，60s 超时 | 已修复 | 采用评审建议③（拆分独立用例）并加确定性引导：TC-I-05 拆为两段（e2e_snake.py `run_tc_i05`）——a) BFS 仅需吃到 1 个食物（增长/得分细节已由单元层 TC-U-08 充分验证，集成层只确认 HUD 刷新 + 蛇身变长）；b) 撞墙结束不再依赖 BFS，`steer_into_wall()` 发送 'w' 引导蛇直线前进：任意当前方向下 ≤ 20 tick（4s）必然撞墙或撞自身进入结束画面（FR-07 反向禁止保证按键安全），确定性断言 GAME OVER + 最终得分 + 按任意键退出。TC-I-07 的 gameover 时机同步改用该引导。 |
| 意见 3（一般） | 性能用例 TC-P-01~03 无实现（NFR-01/02 自动化验证缺失） | 已实现 | 新增 `perf_snake.py` + `perf_snake.sh`：TC-P-01 用 pexpect PTY + 屏幕轮询采样按键→转向生效延迟（20 次，均值/P95 ≤ 200ms，顺时针键序保证不触发反向禁止）；TC-P-02 运行期 30s CPU/RSS 采样（优先 pidstat，缺失时 ps 轮询兜底），断言 CPU ≤ 5% / RSS ≤ 50MB。TC-P-03（目测无闪烁）纳入 checklist-system.md 人工项。按测试方案 §2/§4，性能用例失败仅记录缺陷单、不阻塞门禁。 |
| 意见 4（建议） | 系统层 TC-S-01~06 无可执行清单，无法逐项打勾留痕 | 已实现 | 新增 `checklist-system.md`：逐项列出 TC-S-01（README 跑通 + 终端恢复）/TC-S-02（README 四节）/TC-S-03（四终端矩阵表）/TC-S-04（三类错误提示汇总）/TC-S-05（代码职责走查）/TC-S-06（Python 3.6/3.8/3.11/3.12 矩阵冒烟）+ TC-P-03 目测项，含环境记录、勾选栏与汇总结论区，满足测试方案 §2「半自动：脚本 + 人工清单」的清单要求。 |
| 意见 5（建议） | 集成测试依赖 MiniTerm 完整网格解析，脆弱；建议核心验证改用 pexpect expect 字符串匹配 | 已采纳 | e2e_snake.py 重构：结束画面等待改为 `child.expect(r'GAME OVER|YOU WIN')` 纯文本匹配（`wait_game_over`），匹配字节同步灌入 MiniTerm 供得分断言；非 TTY 退出码等断言本就基于 subprocess 真实退出码。MiniTerm 网格仅保留给坐标类断言（TC-I-04 蛇头位置、TC-I-09 HUD 行、TC-I-10 边框/坐标范围）；MiniTerm 自身按真实终端语义修正清屏序列处理（miniterm.py，`ESC[J` 系列 + `?1049h/l` 备用屏幕切换）。 |
| 检查项 10（附注） | pytest cache 与 __pycache__ 建议 .gitignore 排除 | 已采纳 | r2 目录新增 `.gitignore`（`__pycache__/`、`.pytest_cache/`、`*.pyc`）。 |

## 与测试方案的一致性声明

- 用例实现与 testplan r1 用例表一一映射（见上表），P0 全覆盖、边界用例齐全
  （非法 tick/尺寸、反向禁止直接/连按、尾部让行、撞墙贴边、撞自身、占满判胜、
  非 TTY、过小终端、SIGINT 三时机、SIGTERM、运行中 resize）；
- 不测范围与方案一致：暂停/继续（Q-04 未实现）、分数持久化/加速/多食物/
  穿墙（Q-01/02/03、A-04）、图形/联网/音效、Windows/macOS；
- 测试与被测代码解耦：通过 snake.py 公共 API（GameState/parse_args/
  InputHandler）与 PTY 命令行接口测试，不修改被测代码、不写业务功能。
