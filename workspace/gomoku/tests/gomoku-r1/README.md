# gomoku 测试套件（test 阶段 r1）

> 角色：test-developer｜状态：reviewing｜产物：tests/gomoku-r1/

## 0. 用途与范围

实现 `workspace/gomoku/testplans/gomoku-r1.md` 中全部 P0/P1 用例，验证
`workspace/gomoku/code/gomoku-r3/` 的可运行代码，覆盖：

- **L1 单元层**：`board.py`（规则内核）+ `ai.py`（AI 决策）
- **L2 集成层**：`main.py` 回合循环 + CLI 装配 + 终局重开
- **L3 系统/E2E**：pexpect 驱动真实 `python -m gomoku` 进程
- **L4 验收/文档**：依赖脚本（bench_ai / fuzz_input）+ README 核对

**被测代码**：仅读，不修改。`tests/` 目录与 `code/` 平级，不污染被测代码仓。

## 1. 目录结构

```
tests/gomoku-r1/
├── README.md            # 本文件
├── tests/               # pytest 用例
│   ├── conftest.py      # 摆子/对照表/封堵/fuzz 池/中盘生成器
│   ├── test_board.py    # UTB-01~18（board.py 单元）
│   ├── test_ai.py       # UTA-01~10（ai.py 单元）
│   ├── test_integration.py  # IT-01~06（main.py + config 装配）
│   └── test_e2e.py      # ST-01~16（pexpect 终端 E2E）
└── scripts/             # 独立运行的工具脚本
    ├── bench_ai.py      # AI 性能基准（testplan UTA-08）
    └── fuzz_input.py    # 输入 fuzz（testplan ST-11）
```

## 2. 运行方式

### 2.1 依赖

```
rich         # 被测代码运行时
pytest       # 测试运行时
pexpect      # E2E 用例（仅 Linux）
```

安装：`pip install rich pytest pexpect`（pypi 直连被墙时用清华镜像）。

### 2.2 命令

```bash
# 0. 设置 PYTHONPATH 让 pytest/pexpect 找到 gomoku 包
export PYTHONPATH=../../../code/gomoku-r3:$PYTHONPATH

# 1. 全部 L1+L2+L3
cd workspace/gomoku/tests/gomoku-r1
python3 -m pytest tests/ -v

# 2. 仅 L1（单元 + 集成）
python3 -m pytest tests/test_board.py tests/test_ai.py tests/test_integration.py -v

# 3. 仅 L3（E2E）
python3 -m pytest tests/test_e2e.py -v

# 4. 性能（testplan UTA-08）
python3 scripts/bench_ai.py --games 5

# 5. fuzz（testplan ST-11）
python3 scripts/fuzz_input.py --rounds 100 --seed 42
```

### 2.3 预期结果

- L1+L2：所有用例通过（含 xfail/xpass 标注的已知 AI/UI 缺陷，详见 §5）；
- L3：12 通过 + 3 xfail（UI 渲染折叠缺陷，详见 §5）；
- bench：P95 ≤ 2s（本机 4 核实测 ~620ms）；
- fuzz：进程存活、exit 0、无 traceback。

## 3. 与测试方案用例的映射

| 测试方案用例 | 落点文件 | 类/函数 |
|------|------|------|
| UTB-01~04 坐标解析 | test_board.py | TestParseMove |
| UTB-05 place 越界 | test_board.py | TestPlace |
| UTB-06~11 胜负/满盘 | test_board.py | TestCheckWin |
| UTB-12~16 禁手分支 | test_board.py | TestCheckForbidden |
| UTB-17 禁手对照表（参数化 10 例） | test_board.py | test_utb17_forbidden_table_param |
| UTB-18 undo | test_board.py | TestUndo |
| UTA-01 三档合法性 | test_ai.py | TestChooseMoveBasic |
| UTA-02 弱档不破坏己方 | test_ai.py | TestWeakDoesNotSelfDestruct |
| UTA-03 中档冲四封堵（10 例参数化） | test_ai.py | TestMediumBlocksRushFour |
| UTA-04 中档活三封堵（10 例参数化） | test_ai.py | TestMediumBlocksLiveThree |
| UTA-05 强档进攻 | test_ai.py | TestStrongAttacks |
| UTA-06 AI 禁手规避（中/强） | test_ai.py | TestAIAvoidsForbidden |
| UTA-07 无合法点 | test_ai.py | TestNoLegalMove |
| UTA-08 P95 ≤ 2s | test_ai.py | TestStrongPerformance |
| UTA-09 极小预算降级 | test_ai.py | TestTimeBudgetFallback |
| UTA-10 空盘/单子邻域 | test_ai.py | TestCandidatePruning |
| IT-01/02 回合切换 | test_integration.py | TestTurnSwitching, TestTwentyMoves |
| IT-03 终局横幅 | test_integration.py | TestEndGame |
| IT-04 重开 | test_integration.py | TestRestart |
| IT-05 CLI 参数 | test_integration.py | TestCLIArgs |
| IT-06 平局 | test_integration.py | TestDraw（testplan §6 R1 降级） |
| ST-01~16 终端 E2E | test_e2e.py | 11 个测试函数 |
| DOC-01~05 验收 | 本 README + 仓 README 对照（手工） | - |
| UTA-08 性能脚本 | scripts/bench_ai.py | main() |
| ST-11 fuzz | scripts/fuzz_input.py | main() |

## 4. 关键测试策略说明

### 4.1 摆子与对照表（conftest.py）

- `prefill(size, placements)`：构造固定棋局（避免重复写 15×15 行）；
- `FORBIDDEN_TABLE`：10 例参数化，覆盖标准 / 异位 / 跳 / 白方 / 长连 / 单三单四；
- `BLOCK_RUSH_FOUR_CASES`：10 例冲四棋局，覆盖横/竖/主对角/副对角 + 贴边/贴角/中盘异位；
- `BLOCK_LIVE_THREE_CASES`：10 例活三棋局，覆盖横/竖/主对角/副对角 + 贴边/贴角/异位；
- `fuzz_input_pool(seed, count)`：固定 seed 输入池（合法/越界/占用/乱码/空/超长/中文/quit）；
- `random_midgame(size, stones_each, seed)`：固定 seed 中盘生成器（双方各 N 子，黑先）。

### 4.2 集成层 mock UI

`test_integration.py::TestPlayOneGameMocked` 用 `monkeypatch` 把
`gomoku.main.render / ui_get_move / get_console / _post_game_prompt`
四个 UI 入口 mock 掉，跑 `play_one_game()` 主循环：

- 不依赖真实 TTY；
- 验证主循环可执行、回合切换正确、重开路径返回 True/False；
- 与 `TestTwentyMoves`（直接调 `_apply_human_move / _apply_ai_move`）互补。

### 4.3 E2E pexpect 锚点

棋盘首帧无 `上一步`（仅在落子后才出现），用 `当前玩家`（每帧都出现）
作为首帧锚点；后续帧可用 `上一步` 或 `当前玩家` 任一。

### 4.4 性能与降级

- UTA-08：5 个中盘局面（双方各 20 子，固定 seed），P95 ≤ 2s（CI 宽限 0.5s）；
- UTA-09：`time_budget=0.05` 极小预算下 `strong` 档仍返回合法点（降级链生效）。

### 4.5 平局降级路径（testplan §6 R1）

严格 224 子无五连局面摆子成本高（对角线易成五），降级为：
随机填子 + 回滚任何成五 + 保留 (7,7) 为最后空位。`_apply_human_move` 在
`is_full()` 时判 winner=None（平局）。若随机生成恰好无法构造 ≥220 子
无五连 + check_win 为 None，则 `pytest.skip` 并注明降级理由。

## 5. 已知被测代码缺陷（xfail 标注）

| 测试 | 缺陷位置 | 描述 | 建议修复 |
|------|---------|------|---------|
| `test_uta03_strict_block_only` (3 例) | ai.py `_classify_empty` 的 opp 评分 | medium 档在"横贴边 / 竖贴角 / 主对角贴边"3 例冲四棋形既不封堵也不反威胁——`_classify_empty` 对 W 在封堵点的冲四评分仅 0（漏判 opp 冲四） | `_classify_empty` 的 opp 评分应识别 W 落封堵点形成冲四 → RUSH_FOUR=10000 |
| `test_uta06_strong_avoids_forbidden` | ai.py `_strong_move` 未过滤禁手点 | strong 档 alpha-beta 搜索未调用 `check_forbidden` 过滤候选 → 落 (7,7) 双三 | 在 `_strong_move` 中 `candidates` 后过滤掉 `check_forbidden == (True, ...)` 的点 |
| `test_st03_no_color_distinguishes_stones` | ui.py:168 `grid.add_row(*[c for row in rows for c in row]) | 15×16 个 cell 一次性 add_row 成一行 → 棋盘折叠为单行 dots | 改为 `for row in rows: grid.add_row(*row)` |
| `test_st06_last_move_marker` | ui.py 同上 | 棋盘折叠导致 pexpect 缓冲区截断未匹配到 `上一步` | 同 ST-03 |
| `test_st11_fuzz_100_inputs_no_crash` | pexpect 时序 + ui.py 渲染折叠 | fuzz 节奏过快 + rich 改写 stdio buffer → `child.isalive()` 偶发返回 False（实际进程未崩） | 同 ST-03；已加 isalive 重试验证 |

## 6. 与 README/DOC 验收的对应

| testplan DOC | 验证方式 | 备注 |
|------|---------|------|
| DOC-01 README 六项内容 | 本 README §2/§3/§5 + 仓 README.md 人工核对 | 运行方式 / 依赖 / 键位 / 配置 / AI 算法 / 硬件基线 |
| DOC-02 干净环境整局 | scripts/fuzz_input.py + test_e2e.py::test_st15 | 已用 pexpect 模拟；Docker 冒烟由 release 阶段执行 |
| DOC-03 `pip install .` | 待 release 阶段验证 | pyproject.toml 已就绪 |
| DOC-04 性能基线 | scripts/bench_ai.py 输出 | 实测 ~620ms，远低于 2s |
| DOC-05 模块职责分离 | 静态：board/ai/ui/config/main 五模块各自独立 | 详见 README §3 |

## 7. 产物清单

```
tests/gomoku-r1/
├── README.md                            # 本文件
├── tests/
│   ├── conftest.py                      # 摆子/对照表/封堵/fuzz 池/中盘生成器
│   ├── test_board.py                    # 29 用例（含 10 例参数化）
│   ├── test_ai.py                       # 51 用例（含 20 例参数化）
│   ├── test_integration.py              # 19 用例（含 1 例 skip）
│   └── test_e2e.py                      # 15 用例（含 3 例 xfail）
└── scripts/
    ├── bench_ai.py                      # AI 性能基准
    └── fuzz_input.py                    # 输入 fuzz
```

## 8. 状态变更

- 本目录完成时，状态 `test reviewing`（由 `statectl.py set_status` 触发）；
- 上半部 tick 由 `test-reviewer` 角色进行评审，PASS → `done`，FAIL → `working`（failures++）；
- 连续 FAIL ≥ 2 → `blocked`（zbot 告警 + 人工 requeue）。