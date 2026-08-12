# 代码评审：gomoku（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：方案符合、24 例禁手对照表全过、AI 禁手预过滤已落实、NFR-01/02 实测达标、安全与边界闭环。
- 评审轮次：r1

## 1. 检查清单核对表

| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | 模块划分与 plan §3 完全一致（config/board/ai/ui/main + forbidden_cases + ai_self_check）；接口签名与 plan §4 一致（Board.place/undo/check_win/check_forbidden/is_full/parse_move、ai.choose_move、ui.render/get_move、CLI 参数）；CLI 参数 `--size/--difficulty/--forbidden/--human/--debug-timing` 与方案 §4 CLI 表一致；评分常量、Alpha-Beta 迭代加深 1..4 与候选剪枝 12、1.5 s 时间预算等核心算法参数均在 ai.py 中显式声明。 |
| 2 | 可运行 | PASS | `python3 -m py_compile` 9 个 .py 全过；`import gomoku` 成功，版本 0.4.0 与 pyproject 一致；`python3 -m gomoku --help`/`--version` 正常；`scripts/smoke.sh` 全 5 步通过（import / 24 例禁手 / AI 自检 / CLI / 端到端胜局 / 非法输入 fuzz）；`gomoku.egg-info` 已生成。 |
| 3 | 功能正确性 | PASS | FR-09 胜负：横/竖/双斜/边界行/边界列/角部/长连 6 子全部判胜（实测 8 例）；FR-06 AI 三档：weak/medium/strong 在随机中盘均返回合法 cell；FR-06 封堵 10/10 + 活三响应 10/10 + 弱档合法性 10/10 + 禁手规避 1/1（ai_self_check 输出）；FR-07 禁手 24/24 对照表全过（含红线 A1~A4）；FR-07 AI 侧永不主动走禁手（_filter_legal + main._recheck_forbidden 双重兜底）；FR-04 坐标三重校验（format/out_of_range/occupied）实测覆盖 14 例边界输入均返回正确 reason；FR-11 Ctrl+C/EOFError/SystemExit 顶层捕获均 exit 0。 |
| 4 | 边界与异常 | PASS | FR-04 边界：越界 `P1`/`A16`/`16,16`/`A0`/`Z9`/`14,14` 实测全部 reason=out_of_range；非法格式 `""`/`"abc"`/`"8 8"`/`"8,8,8"`/`"A-1"`/`"   "` 全部 reason=format；NFR-06 越界访问 `place(15,0)`/`(-1,0)`/`(0,15)` 全返 False 不抛异常；满盘 `is_full()` 正确；非法 size 接受 5..25（board 内部宽容，CLI 仍限制 13/15）；满盘无五连 `winner=None`；终局重开 `board.reset()` 清空状态并保留 config。 |
| 5 | 安全与合规 | PASS | NFR-06 全模块源码无 `eval(`/`exec(`/urllib/requests/socket；纯本地运行无网络/系统目录/提权；坐标正则 `^([A-Za-z])([0-9]{1,2})$` + `^(\d{1,2})\s*,\s*(\d{1,2})$` 严格白名单；依赖仅 `rich>=13.0`（PyPI 官方源）；`Config` dataclass 不可变（frozen=True 实测 FrozenInstanceError）；输入解析失败抛 MoveError 不产生越界索引。 |
| 6 | 可读可维护 | PASS | 模块职责清晰（board 纯规则零 I/O 依赖、ai 决策、ui rich 渲染、main 主控、forbidden_cases/ai_self_check 数据驱动自检）；docstring 完整且引用 plan 章节号；命名规范（snake_case 函数、UPPER_CASE 常量）；函数单一职责；Board.__slots__ 使用节省内存；算法逻辑附内联解释（_classify_window、_filter_legal、_recheck_forbidden）。 |
| 7 | 错误处理 | PASS | 错误路径有明确反馈：MoveError.reason 区分 format/out_of_range/occupied，UI 按 reason 分类提示"invalid move (format)"等；MoveError 携带原始 text 便于排查；Ctrl+C/EOFError 顶层捕获返 exit 0；terminal 尺寸 < 24×60 提示并等待放大（main 路径通过 ensure_terminal_size）；rich Console 在 pipe 模式自动 no_color 降级；非法 color 输入 `place(x, y, "X")` 返回 False 不抛异常。 |
| 8 | 性能与资源 | PASS | NFR-01：strong AI 在 30 子密集中盘实测 1.52s ≤ 2s；ai_self_check 报告 20 子中盘 1504 ms ≤ 2s；NFR-02：render 计时钩子（`--debug-timing` / `GOMOKU_TIMING=1`）实测单帧 2.6ms << 200ms；资源无句柄泄漏（Board 无打开文件，rich Console 单例无 I/O 持有）；Board.__slots__ 优化内存；评分表/候选剪枝/迭代加深 + 时间预算保障 worst-case 落子 ≤2.5s（plan §5.4 降级链）。 |
| 9 | 不越界 | PASS | 未混入 tests/ 目录（test-developer 阶段产物）；未修改 plans/testplans/input/analysis/review；未写 status.json（worker 只调 statectl）；每轮新目录 `code/gomoku-r1/` 干净；版本号 `pyproject.toml` 0.4.0 与 `gomoku/__init__.py:__version__` 0.4.0 对齐；README §11 修改回应表声明本轮无 prior code review；前生命周期 code r1 FAIL 的"AI 禁手预过滤"已在 README §5.4 显式追溯并落实（_filter_legal + _recheck_forbidden 双层）。 |
| 10 | 可审计 | PASS | r1 目录干净，无旧轮次残留；README §11 修改回应表清晰；24 例禁手对照表与 plan §5.2 附录 A 100% 对齐（A1~A15 全在 + B6~B12 7 例扩充覆盖）；自检命令 `python -m gomoku.forbidden_cases` 与 `python -m gomoku.ai_self_check` 可独立复现且均在 smoke.sh 中串联运行；本轮无 prior code review（README §11 明示）。 |

**清单汇总**：10/10 PASS。

## 2. 评审意见列表

- **[建议]** 意见 1：`_classify_window` 内有冗余分支
  - 依据：`gomoku/board.py` line 510–520 出现两段相同的 `if b_count == 4 and e_count == 1: return "four"`；第二段只是注释掉的同义重写，运行时不会执行但对读者造成"漏写条件"的误导。
  - 落点：`gomoku/board.py` `_classify_window`（line 484–555）内 510/519 行。
  - 建议：删去第二段冗余分支或合并为单一 return + 注释解释 BB.BB / B.BBB / XXX.X 跳形覆盖依赖"4 B + 1 E"形态而非显式枚举。

- **[建议]** 意见 2：`_evaluate_color` 的"按方向重复累加"在 README 中已显式声明但缺一行函数 docstring
  - 依据：`gomoku/ai.py` line 515–562 的 `_evaluate_color` 对每颗子按 4 方向各累加一次，会对 4 子 run 计 4 次 SCORE_OPEN_FOUR；README §9 第 2 条已承认此为已知限制（"over-counts stones"，评分表"相对量级决定选点，不在意绝对值"），但函数本身 docstring 仅描述"sum open-ended runs"，未提 over-counting 的语义意图，新人阅读会以为有 bug。
  - 落点：`gomoku/ai.py` line 515 函数 docstring。
  - 建议：在 docstring 增 2–3 行说明 over-counting 是有意为之（评分表绝对值非真实棋力信号，仅作相对排序用），并在测试阶段以注释形式固化"未来若做绝对分数解读需先修复此累加"的提示。

- **[建议]** 意见 3：README §5.4 "headline fix" 文案与本评审的实际发现一致性可再强化
  - 依据：README §5.4 与 §11 声称"已集成 r1 review 严重意见 1"——本评审独立验证 _filter_legal 在 _weak_move/_medium_move/_strong_move 三档均被调用，且 main._recheck_forbidden 兜底已实现，结论一致。但 README 未显式列出 ai.py 中 `_alpha_beta` 内部对 `root_color == BLACK` 时也做了禁手预过滤（line 459–461），这是搜索路径上的兜底，与候选层过滤互补。
  - 落点：`workspace/gomoku/code/gomoku-r1/README.md` §5.4 + §11 修改回应表。
  - 建议：README §5.4 第 2 步补一句"Alpha-Beta 搜索递归（`_alpha_beta`）在 root_color == BLACK 时同步过滤禁手候选（ai.py:459–461），与候选层 `_filter_legal` 形成双层兜底"。

- **[建议]** 意见 4：`pyproject.toml` 的 `[tool.pytest.ini_options].testpaths = ["tests"]` 当前不存在 tests/ 目录
  - 依据：`pyproject.toml` line 38 指定 `testpaths = ["tests"]`，但 `code/gomoku-r1/` 下并无 `tests/` 子目录（test-developer 阶段才会产出）。当前 `pytest` 在该目录运行会因找不到 testpaths 而报错或默默空跑。
  - 落点：`pyproject.toml` line 36–39；`scripts/smoke.sh` 未触发 pytest。
  - 建议：要么在 smoke.sh 显式跳过 pytest（"pytest 由 test-developer 阶段集成"），要么删去 `[tool.pytest.ini_options]` 至 test-developer 阶段再补；当前 smoke.sh 已涵盖核心算法自检，不影响交付。

## 3. 遗留事项（仅 PASS 时）

- [意见 1] `_classify_window` 冗余分支：非阻塞，留待后续维护清理。
- [意见 2] `_evaluate_color` over-counting：非阻塞，README §9 已声明；评分表按相对量级设计。
- [意见 3] README §5.4 描述完整性：非阻塞，行为已正确，仅文档微调。
- [意见 4] pyproject.toml 的 `[tool.pytest.ini_options]` 指向尚不存在的 `tests/`：非阻塞，smoke.sh 已自洽，建议 test-developer 阶段确认或在 PR 中微调。

无任何严重或一般问题；4 项建议均非阻塞、可在后续轮次或 test-developer 阶段一并处理。本轮交付满足 plan 与 testplan 全部验收点，进入 test 阶段。
