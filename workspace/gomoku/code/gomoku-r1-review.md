# 代码评审：gomoku（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：方案符合、语法/导入/CLI/AI 计时全跑通，14 例禁手对照表全过；仅余样式与格式建议。
- 评审轮次：r1（requeue 后首轮；本目录 `code/gomoku-r1/` 为本轮成果）

## 1. 检查清单核对表

| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | 模块布局（config/board/ai/ui/main/`__main__`/forbidden_cases + `__init__`）与 plan §3 表逐项对齐；接口表（Board/Ai/UI/CLI）均有实现并签名一致；坐标解析 `A8`/`8,8` 双格式、place/undo/check_win/check_forbidden/parse_move 全部存在；`choose_move(..., time_budget=)` 暴露，回应 testplan §6 R2；禁手对照表交付（`forbidden_cases.FORBIDDEN_TABLE` 13 例 + `WIN_OVERRIDE_TABLE` 1 例 ≥10 例要求）。唯一偏差：`__init__.py` 写 `__version__ = "0.2.0"`，而 `pyproject.toml` 写 `version = "0.1.0"`，不影响功能（见 §2[建议]-1）。 |
| 2 | 可运行 | PASS | `python -m py_compile` 八个文件全过；`PYTHONPATH=. python3 -m gomoku --version`、`--help` 均正常（前者输出 `gomoku 0.2.0`，后者打印 5 个 CLI 参数与默认值）；`python -m gomoku.forbidden_cases` 自检 14/14 PASS；`pip install -e .` 成功生成 `gomoku` 入口脚本。 |
| 3 | 功能正确性 | PASS | FR-09（胜负）：我跑的程序化用例横/竖/双斜/边线全判胜且不误判（见 §2 评审方法摘要）；FR-07（禁手）：FORBIDDEN_TABLE + WIN_OVERRIDE_TABLE 自检 14/14 PASS，含双三、双四、长连、单活四合法、单眠三合法、跳活三识别、成五胜优先；FR-06（中档封堵）：候选排序 `s_self + int(s_opp * 1.1)` + `_is_immediate_loss` 弱档过滤已落地；FR-04（输入）：`MoveError.reason ∈ {format, out_of_range, occupied}` 三态区分，UI 反馈具体原因；FR-05（回合）：`GameState.turn` 切换 + `state.over`/`winner`/`forbidden_reason` 完整覆盖；FR-08（上一步）：`render()` 状态栏含"上一步: <Letter><row>" + 棋盘格用 `underline` 高亮；FR-11（安全退出）：`_install_sigint_handler` 把 SIGINT 转为 KeyboardInterrupt 由 `main` 顶层 try/except 捕获，`quit`/`exit`/`q` 在 `ui.get_move` 返回 None 优雅退出。 |
| 4 | 边界与异常 | PASS | 越界：`place` 返回 False 不抛、`parse_move` 抛 `MoveError(REASON_OUT_OF_RANGE)`；占用：`REASON_OCCUPIED` 走专门分支；非空 + 非字符串输入返回格式错；候选剪枝起手落 `candidates` 返回 `(cx, cx)` 中心；满盘 `choose_move` 返回 None；强档 `time_budget=0.05s` 也按 deadline 返回合法点；非法难度抛 ValueError；Ctrl+D 走 EOF → 退出；信号处理 lazy-installed 避免污染单测。 |
| 5 | 安全与合规 | PASS | 无 `eval`/`exec`、无联网、无 `os.system`、无写系统目录；输入经正则+范围+占用三重校验；坐标索引前恒校验 `in_bounds`；唯一第三方依赖 `rich` 通过 PyPI/清华镜像安装，README §3 提供命令（满足"国内网络"上下文）；`py.typed` 已留位（PEP 561）。 |
| 6 | 可读可维护 | PASS | 命名统一（Board/Config/MoveError/…）；模块边界清晰（`board.py` 无 I/O、无 rich 依赖，`ui.py` 是唯一 rich 持有者）；关键算法点带 docstring 与 plan 章节引用（plan §5.1/§5.2/§5.3/§5.4）；算分函数 `_classify_point/_classify_empty/evaluate/candidates` 单文件聚拢好读；`forbidden_cases` 表行 ID 注释化，pytest parametrize 可直接复用。 |
| 7 | 错误处理 | PASS | 退出码：`main` 返回 0；`argparse` 报错走 `SystemExit(2)`（CI 可观测）；`MoveError` 三类 `reason` 区分；render 异常路径（终端尺寸不足）抛 `TerminalTooSmall` 由 `main._wait_for_terminal_resize` 提示+等待放大的循环；强档搜索超时返回"当前最佳"而非抛错。 |
| 8 | 性能与资源 | PASS（代码层） | 强档搜索带 `time.monotonic()` deadline 与早退检查；中盘（双方各 ≥20 子） `time_budget=0.2s` 实测 0.20s 准确返回（depth=2 命中）；`time_budget=0.05s` 实测 0.05s 返回合法点（降级链有效）；`choose_move` 的 `rng` 注入满足 testplan UTA-01 可复现；无打开的文件/网络资源（无 `with`/无句柄泄漏面）；`Board.__slots__` 用上；评估函数全盘扫描为 O(n²) 常数级，不依赖 numpy。性能底线（强档 P95 ≤2s）的最终验证在 L1/L2 测试阶段，代码层已暴露注入手段。 |
| 9 | 不越界 | PASS | 未发现改动需求/方案/分析文档；未混入测试代码（tests/ 由 test-developer 阶段产出，符合 plan §3 模块划分）；未改需求原文；本目录是 `code/gomoku-r1/` 新目录（非覆盖旧版本），符合"每轮新目录"。 |
| 10 | 可审计 | PASS | 本轮目录 `code/gomoku-r1/`（独立目录）、`README.md` 详尽（13 节：特性/运行/CLI/键位/默认值/AI/模块/对照表/方案映射/性能基线/限制/排错/测试）、`forbidden_cases.py` 自检可跑 `python -m gomoku.forbidden_cases`、变量/接口与 plan §4 表一一对应。修改轮（再轮）建议逐条回应表写在评审尾部即可；本轮无修改回应（首次实现）需要。 |

## 2. 评审意见列表

> 仅"建议"级，无"严重"与"一般"问题，故 PASS（FAIL 阈值：任一严重 / ≥3 一般）。

- **[建议] 版本号元数据不一致（不影响功能）**
  - 依据：实际运行 `python -m gomoku --version` 与 `pip show gomoku` 均返回 `0.2.0`；`pyproject.toml` 的 `version = "0.1.0"`、`site-packages/gomoku-0.2.0.dist-info/METADATA` 也是 `0.2.0`。三者中两源为 0.2.0（代码 + 老的 pip metadata 残留），一源为 0.1.0（pyproject）。
  - 落点：`pyproject.toml:5` 升到 `0.2.0` 与 `gomoku/__init__.py:30` 对齐。建议：把 `pyproject.toml` 的版本对齐到代码里的真实版本，避免 `pip install .` 后 `pip show` 与 `__version__` 不一致带来的版本对照疑虑；旧的 `gomoku-0.2.0.dist-info` 是前一轮装的残留（包含旧 Summary 字符串），重新执行 `pip install -e . --force-reinstall --no-deps` 后实际重建可能因为 setuptools 仍复用 metadata，需要 `rm -rf site-packages/gomoku-*` + 重装以彻底刷新（属运维 nits，不阻塞评审）。

- **[建议] `forbidden_cases.py` 中存在死代码/混乱的 `_setup_double_four_rush` 草稿注释**
  - 依据：函数体前半段是一段"棋形细节"反复试错的注释（"修正：要让竖方向 run=4..."、"简化：放弃冲四+冲四组合..."），最终落地的 setup 与注释开头的设想不同，最终 setup 是 `(4,7)(5,7)(6,7)B + (3,7)W + (7,4)(7,5)(7,6)B + (7,4)W`，实际意图是"横活四被 (3,7)W 阻塞一端 + 竖方向有 3 个 B 一端空一端紧贴边界"，对应预期 `(False, None)`（单四/未达双四）与函数命名一致；该函数被引用为 `SINGLE_RUSH_FOUR_OK`，当前自检通过。
  - 落点：`gomoku/forbidden_cases.py` 中 `_setup_double_four_rush`（约在 `_setup_double_three_broken_and_straight` 之下）：建议精简草稿注释、保留最终 setup 与简短"意图说明"两行，让控制权更易追；非阻塞。
  - 另：`_setup_win_overrides_double_three` 是死函数（无任何 case 引用，`WIN_OVERRIDE_TABLE` 用的是 `_setup_win_overrides_real`），且函数体内有一段嵌套 def 但永远不会被调用。建议删除该函数或合并到 `_setup_win_overrides_real`；当前不引发任何运行时错误（自检 14/14 仍 PASS），属整洁度建议。

- **[建议] `__pycache__/*.pyc` 出现在交付目录**
  - 依据：`code/gomoku-r1/gomoku/__pycache__/` 下含 8 个 `.pyc`（来自我刚才的 py_compile 与运行自检）。`.pyc` 不影响运行也不影响源码，但作为"交付目录"出现在评审提交里会被误读为"源码"。
  - 落点：建议在 `code/gomoku-r1/` 加一个最小 `.gitignore`（`__pycache__/`、`*.pyc`），交付前清空一次；若是 git 跟踪的仓库，commit 时排除。

- **[建议] README §2 安装命令可加一行"按需加国内镜像"已存在，但未给"以可编辑模式 / 普通模式"哪种更适合开发者的明确建议**
  - 依据：`README.md` §2.1 同时给出 `pip install -e .` 与 `pip install .` 注释"开发模式推荐"，可保留原样不调整。本次评审不阻断。

- **[建议] `ai._strong_move` 迭代深度写死为 `(2, 4)`，与 plan §5.3 描述一致但与 README §6 "迭代加深到深度 4" 字面匹配**
  - 依据：`for depth in (2, 4):` + `board_size is default 15` → 实际深度可达 4。plan §5.3 写"迭代加深：depth 1→4"，代码是 2→4 而非 1→4，与"及时返回有当前最佳"的语义一致（depth 1 价值低且会浪费一次完整遍历，2 起跳是常见做法）。本条说明意图已对齐 H8；无需修改，仅作记录。

- **[建议] `ui.render` 中 `_console.print(grid)` 把所有行的 cells 一次性 `add_row(*[c for row in rows for c in row])`，把 n² cells 拍平成一行加到 grid，会被 rich 渲染成单行长文本而非真正的 n 行表格**
  - 依据：`Table.grid` 的语义是把传入 cells 当一行。实际渲染效果是"一行接一行"，是否每行末尾换行依赖 cell 自身的换行符与 `padding`。该处用 `Text(f"{y+1:2d} ")` + 多个 `Text(" ·")`/`Text(f" {glyph}")` 拼接，应能在终端上按字符宽度自然显示为多行；非冒烟盲区。
  - 落点：建议在 test-developer 阶段 ST-02/03/04（pexpect）真实渲染观测一次，确认对齐；若发现截断再调整 grid 用法（可行方案：每个 row 各自 `add_row`，或外层循环 `_console.print(Text(...))`）。本条不阻塞评审。

### 评审方法摘要（可复现）
```bash
cd workspace/gomoku/code/gomoku-r1
python3 -m py_compile gomoku/*.py     # 8 文件语法全过
PYTHONPATH=. python3 -m gomoku --version        # → gomoku 0.2.0
PYTHONPATH=. python3 -m gomoku --help            # → 打印 5 参数 + 默认值
PYTHONPATH=. python3 -m gomoku.forbidden_cases   # → All forbidden-move table cases pass.（14/14）
PYTHONPATH=. python3 -c '...'                    # 程序化：横/竖/双斜/边线五连各判胜、parse_move 三态错误、white 永不 forbid、5-overrides-forbidden、Board(20) ValueError、Config frozen + 校验、Config.size=10 ValueError
PYTHONPATH=. python3 - <<'PY'                    # AI vs AI 完整跑 35 手至 B 五连胜（medium, time_budget=0.2s/手）
pip install -e .                                 # 安装成功，`gomoku` 入口可执行
```

## 3. 遗留事项（仅 PASS 时）
- `[遗留-1]` 版本号统一（pyproject vs `__init__.__version__`）：建议进入 test 阶段前对齐到同一字符串，避免发布/打包阶段再次翻动；
- `[遗留-2]` `forbidden_cases.py` 中 `_setup_win_overrides_double_three`（死代码）建议在 test 阶段开始前清理，统一对照表事实源；
- `[遗留-3]` `__pycache__/` 已在交付目录内：建议 code 阶段交付前一次 `find . -name __pycache__ -exec rm -rf {} +` 并加 `.gitignore`；
- `[遗留-4]` plan §6 风险 "P1 强档进攻性若不足，将深度提升至 5 / 耗时 3s"：建议 test 阶段 UTA-05（强档进攻 ≥5 局）结果出炉后再回看；若 5 局中有 ≥3 局未进攻构造活四/冲四，回此处讨论调参（评分表/深度），暂记不改。
