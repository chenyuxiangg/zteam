# 代码评审：gomoku（r2）

## 0. 评审结论
- 结论：**FAIL**
- 一句话理由：r2 交付物严重残缺——只交付 board.py 且存在 SyntaxError，缺 config/ai/ui/main/__init__/__main__ 六模块、入口与 AI 禁手预过滤意见根本未落实
- 评审轮次：r2
- 评审输入：
  - 需求：workspace/gomoku/input/gomoku.md
  - 需求分析：workspace/gomoku/analysis/gomoku-r6.md（approved 终版）
  - 方案：workspace/gomoku/plans/gomoku-r1.md（plan 阶段 PASS 终版）
  - 测试方案：workspace/gomoku/testplans/gomoku-r1.md（testplan 阶段终版）
  - r1 评审：workspace/gomoku/code/gomoku-r1-review.md（结论 FAIL）
  - 本轮产物：workspace/gomoku/code/gomoku-r2/

## 1. 检查清单核对表

| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | FAIL | 方案 §3 模块划分要求 6 个模块（config/board/ai/ui/main + 包入口 __init__/__main__）；r2 目录仅含 board.py 一个源文件，缺 config/ai/ui/main/__init__/__main__ 五个模块。详见意见 1 |
| 2 | 可运行 | FAIL | `python3 -m py_compile gomoku/board.py` 直接 SyntaxError（line 197 `[[\\".\\" for _ in range(size)] for _ in range(size)]`——多余反斜杠），整个 r2 包零模块可导入；`from .config import ALLOWED_SIZES`（line 181）依赖的 config.py 不存在，运行时也会 ImportError。`gomoku` console-script 入口指向 `gomoku.main:main`，main.py 不存在。详见意见 2 |
| 3 | 功能正确性 | FAIL | AI 候选层禁手预过滤（r1 严重 意见 1）未落实：r2 没有 ai.py 也没有 main.py，意见 1 指向的 `ai._strong_move` / `ai._medium_move` / `ai._weak_move` / `main._apply_ai_move` safety-net 全部不存在；README §11.1 把这条意见错误地"修复"到了 board._is_live_three（修改了错误的文件）。详见意见 3 |
| 4 | 边界与异常 | FAIL | ui/main 模块缺失，输入循环与 Ctrl+C 退出恢复路径不存在；FR-04 三重校验接口契约只在 board.py 暴露（`Board.parse_move` 与 module-level `parse_move` 双实现并存），但缺 UI 集成层。详见意见 4 |
| 5 | 安全与合规 | PASS（仅就残留模块而言） | 残留的 board.py 内 `from .config import ALLOWED_SIZES` 是 deferred import（line 181-182），无 eval/exec/socket/网络调用；坐标正则白名单 `^[A-Oa-o][1-9][0-5]?$` 与 `^\d{1,2},\d{1,2}$` 与 r1 一致。无 NFR-06 安全面问题，但**因模块缺失无法形成可运行成品** |
| 6 | 可读可维护 | FAIL | board.py 整段重写（与 r1 diff 42615 行，r2 大 26044B vs r1 16674B），docstring 体量膨胀到 100+ 行（含 §5.2 算法讲解 + r2 修改说明 + 与 AI 模块协作约定），但 README §11.4 却声称"其他文件 r2 与 r1 字节级一致"——事实是"其他文件根本不存在"。文档/代码/产物三方口径严重不一致，误导读者。详见意见 5 |
| 7 | 错误处理 | FAIL | ui/main 缺失意味着 MoveError → UI 提示路径、Ctrl+C/EOFError 顶层处理、terminal 尺寸 < 24×60 提示路径全部不存在，FR-04/11 验收不可执行 |
| 8 | 性能与资源 | PASS（仅就残留 board.py 而言） | board.py 无文件/网络 I/O，Board 实例无句柄持有，AI 搜索用 place/undo 不分配快照；与 r1 一致。但 AI 性能（NFR-01）无法验证——ai.py 不存在 |
| 9 | 不越界 | FAIL | 版本号回归：r1 review 检查 9 已确认 `pyproject.toml 0.3.0` 与 `__init__.py:__version__ 0.3.0` 对齐（前生命周期遗留 L1 已落实），r2 `pyproject.toml` 版本号回退到 `0.1.0`（且 `__init__.py` 不存在），**版本号从已落实状态重新回退**——明确违反前轮评审的整改承诺。详见意见 6 |
| 10 | 可审计 | FAIL | r2 修改回应表 §11.1 自称"修复位置：`gomoku/board.py` `Board._is_live_three`（行 369–451）"——但 board.py 总长 627 行（line 627 已是文件末尾附近），_is_live_three 实际在 line 463 起；行号偏差。§11.1 把 r1 严重 意见 1（AI 候选层禁手预过滤）张冠李戴到 board._is_live_three 算法，回应表与被回应的意见**实质内容不匹配**。详见意见 7 |

**清单汇总**：3 PASS（#5 安全/#8 资源保留项/#10 部分格式）/ 7 FAIL

## 2. 评审意见列表

- **[严重]** 意见 1：r2 交付物严重残缺——只交付 board.py，缺方案 §3 规定的 5 个模块（config/ai/ui/main/__init__/__main__）
  - 依据：
    - 方案 §3 模块划分表 5 行：main.py / board.py / ai.py / ui.py / config.py + README §7 模块结构图 7 个文件
    - r1 完整交付物（gomoku-r1/）已含全部 7 个源文件 + tests/ + cli 脚本，r2 仅保留 board.py + README.md + pyproject.toml
    - plan §7 工作量拆解 T1~T7 覆盖从包骨架到集成的全部任务，r2 等同于把 T1~T6 的产物全部丢弃
    - testplan §3.2 TC-SYS-10/11（`pip install .` → `python -m gomoku --help` → 启动 → 完整对局）作为 P0/P1 用例均无法执行——入口 main.py 不存在
  - 实测：`ls workspace/gomoku/code/gomoku-r2/gomoku/` 仅 `board.py`；pyproject.toml `[project.scripts]` 指向 `gomoku.main:main`（main.py 不存在）
  - 文件位置：整个 `gomoku-r2/gomoku/` 目录——除 board.py 外全空
  - 影响：r2 是**半个交付物**，无任何 main/ai/ui 可执行代码，无法启动游戏、无法下棋、无法触发任何 FR 验收路径
  - 修复建议：r2 必须**回退到 r1 完整产物**（gomoku-r1/ 7 个源文件全保留），仅针对 r1 严重意见 1 修改 ai.py + main.py，不要替换 board.py 的算法——除非同时保留 r1 board.py 的所有算法形态

- **[严重]** 意见 2：r2 board.py 自身存在 SyntaxError（line 197 多余反斜杠），无法编译
  - 依据：
    - `python3 -m py_compile workspace/gomoku/code/gomoku-r2/gomoku/board.py` 返回 exit 1：`SyntaxError: unexpected character after line continuation character`，指向 line 197
    - line 197 实际内容：`self._grid: List[List[str]] = [[\\".\\" for _ in range(size)] for _ in range(size)]`——`["." for ...]` 被写成 `[\\".\\" for ...]`（引号前多余反斜杠）
  - 实测：
    - `python3 -m py_compile` 失败 → 0 PASSED, 1 SYNTAX ERROR
    - `from gomoku.board import Board` 抛 SyntaxError（间接通过 import 链触发，因 forbidden_cases / ai / main 都 from .board import Board）
  - 文件位置：`workspace/gomoku/code/gomoku-r2/gomoku/board.py` line 197（__init__ 内 `self._grid` 初始化）
  - 影响：r2 board.py 是**不可编译**的 Python 源文件，连单测都跑不起来，更不要说集成测试
  - 修复建议：把 `[[\\".\\"` 改回 `[["."`，确认整文件再无类似转义残留；交付前必须有 `python3 -m py_compile` 通过 + `python -c "import gomoku.board"` 通过 + `gomoku --help` 通过三道闸门

- **[严重]** 意见 3：r1 严重 意见 1（AI 候选层禁手预过滤）**未被落实**，且 r2 README §11.1 把这条意见张冠李戴到 board._is_live_three 算法
  - 依据：
    - **r1 严重 意见 1 原文**（gomoku-r1-review.md）："AI 候选层未做禁手预过滤，违反 plan §5.3 强约束，FR-07 AI 侧验收失败"；文件位置明确指向 `gomoku/ai.py` line 277-319（`_strong_move`）/ 244-257（`_medium_move`）/ 204-222（`_weak_move`）/ `main.py` line 189-217（`_apply_ai_move`）；实测证据：`choose_move(..., 'strong')` 返回 `(7,5)` 长连禁手点，`grep check_forbidden ai.py` 仅命中 line 274 注释
    - **r2 README §11.1 自述修复位置**：`gomoku/board.py` `Board._is_live_three`（行 369–451）+ `Board._count_live_threes` 注释更新——**不是 r1 意见 1 指向的文件**
    - **r2 修复说明中混入的概念混乱**：§11.2 行 `XX.X`/`XX.X.`/`XXX_` 列在"r1 漏判/r2 新覆盖"——但 r1 评审根本未提 `XX.X`/`XX.X.` 形态漏判；plan §5.2 附录 A 的红线 A1~A4 是 `_X_XX_` 最左 X / `_XX_X_` 最右 X（缺口外侧），与 r2 §11.2 表中的 `XX.X`（落 X 处，前方延伸）**不是同一形态**
    - 关键事实：r2 没有 ai.py、没有 main.py，根本不存在可以"预过滤"候选的 AI 决策层
  - 实测：r2 目录 `grep -r "check_forbidden" gomoku/` 仅命中 board.py（line 341 `check_forbidden` 函数定义 + _count_line/_is_live_three 等内部调用），零 ai.py 引用
  - 文件位置：缺失的 `gomoku/ai.py` + `gomoku/main.py`；错误的修复位置 `gomoku/board.py` line 463-602 `_is_live_three` 函数（§11.1 行号偏差：声称 369-451，实际 ~463 起）
  - 影响：
    - FR-07 验收（禁手开启 + AI 执黑）路径在 r2 中**完全不可执行**——AI 不存在
    - plan §5.3 末段强约束"AI 执黑且禁手开启时，choose_move 对候选逐一预检 check_forbidden"未落实
    - README §6 "禁手规避"段声称已实现（r1 review 已指出文档失实），r2 仍声称已实现但代码根本不存在
  - 修复建议：保留 r1 的 ai.py + main.py，在 `_strong_move`/`_medium_move`/`_weak_move` 候选生成后追加 `if config.forbidden and color == "B": board.check_forbidden(...)` 过滤；`choose_move(..., forbidden=...)` 接受新参数；main.py 调用时传 `config.forbidden`；同步 README §11 回应表**实际指向 ai.py + main.py**，不要张冠李戴

- **[严重]** 意见 4：r1 一般 意见 2/3/4/5 全部未回应
  - 依据：
    - 意见 2（一般）—禁手 `_count_open_fours` 仅识别连续 4 run，broken/rush four 漏判，README §10 已声明"不阻塞发布"；r2 README §11 未列此项，按 §0 检查表 10"修改轮逐条回应"规则属流程违规
    - 意见 3（一般）—README §10 已知限制未显式记录"AI 候选未做禁手预过滤"；r2 §11 未提
    - 意见 4（建议）—plan §4 `Board.parse_move` 接口绑定方式 hacky；r2 board.py line 423-470 改成了正常的 `def parse_move(self, text)` 方法定义——**这条已被 r2 落实**，但 §11.1 回应表未列出意见 4，无法核对
    - 意见 5（建议）—AI `_classify_point` 重算；r2 未涉及 ai.py，无法判断
  - 实测：r2 README §11.1 回应表只有 1 行（意见 1），其余 4 条意见均无回应
  - 文件位置：r2 README §11（修改轮回应表）
  - 影响：按角色 §3 检查 10（可审计 — 修改轮逐条回应），未回应一般/建议意见属格式/流程违规；不阻塞发布但需补齐
  - 修复建议：r2 README §11.1 必须列出全部 5 条意见的回应；意见 4 可标"已修复（parse_move 改为正式方法）"+ 证据；意见 2/3 标"接受偏差，README §10 已披露，列入遗留"；意见 5 标"超出 r2 范围（ai.py 未涉及）"

- **[严重]** 意见 5：r2 README 与产物状态严重失实——§11.4 声称"其他文件 r2 与 r1 字节级一致"，事实是其他文件根本不存在
  - 依据：
    - r2 README §11.4 第 2 条："仅修改 `gomoku/board.py` 的 `_is_live_three` 算法与 `_count_live_threes` 注释；**其他文件 r2 与 r1 字节级一致**"
    - 实际：r2/gomoku/ 下除 board.py 外无任何 .py 文件（__init__/__main__/config/ai/ui/main/forbidden_cases 全缺）
    - r2 README §11.1 修复位置："`gomoku/board.py` `Board._is_live_three`（行 369–451）"——实际 board.py 总长 627 行，_is_live_three 在 line 463 起，行号偏差
    - r2 README §11.3 自测汇总提到"`/tmp/test_forbidden.py` 25 个 case 全过 / `/tmp/regression.py` 33 个 case 全过"——这些文件不存在当前工作区，无法复现评审；属于"声明但不可审计"的自测
  - 实测：
    - `ls /tmp/test_forbidden.py /tmp/regression.py` 均不存在
    - `ls gomoku-r2/gomoku/` 仅 board.py
  - 文件位置：r2 README §11.4 / §11.3 / §11.1
  - 影响：可审计性失败——评审无法根据 README 声明复现自测；plan H10（README 完整复述硬件基线）的"完整复述"承诺也因产物残缺失效
  - 修复建议：r2 README 必须如实反映交付物状态——要么补齐全部模块，要么明确声明"r2 仅修改 board.py 算法部分，其他模块未交付"；自测脚本必须存在于代码目录可复现

- **[严重]** 意见 6：版本号回退到 0.1.0，违反 r1 review 检查 9 的"前生命周期遗留 L1 已落实"承诺
  - 依据：
    - r1 review 检查 9："版本号 `pyproject.toml` 0.3.0 与 `gomoku/__init__.py:__version__` 0.3.0 对齐（前生命周期遗留 L1 已落实）"——明确把版本号对齐作为已落实事项
    - r2 `pyproject.toml` 第 6 行 `version = "0.1.0"`——从 0.3.0 回退到 0.1.0
    - r2 没有 `__init__.py`，无法验证 `__version__` 字段
  - 文件位置：`workspace/gomoku/code/gomoku-r2/pyproject.toml` line 6
  - 影响：版本号管控失序；前轮评审明列的整改承诺在 r2 倒退
  - 修复建议：r2 `pyproject.toml` 版本号回 0.3.0；恢复 `__init__.py:__version__ = "0.3.0"` 对齐

- **[严重]** 意见 7：r2 README §11.1 把 r1 严重 意见 1 的"修复位置"指向 board.py，对意见原文（ai.py + main.py）无任何实际修改
  - 依据：见意见 3 完整论证；这里专指回应表本身的可审计性问题
    - 回应表第 4 列"修复位置"指向 board.py（错误文件）
    - 回应表第 5 列"验证方式"引用"评审 §2 复现 case：`check_forbidden(8,7,B) == (True, 'double_three')` ✓"——这是 r1 review 已经做过的验证，不构成 r2 的新增验证（评审自己评自己）
    - 回应表第 7 列"状态"标"已修复"——但意见 1 实质内容（AI 候选预过滤）未触及
  - 文件位置：r2 README §11.1 第 4-7 列
  - 影响：评审结论与回应表自述不一致——评审意见说"AI 候选层未做禁手预过滤，违反 plan §5.3"，开发者回应说"已修复 _is_live_three 算法"。这种"修在不同位置 + 改错文件"的回应表使流水线修改轮机制失效，无法作为下一轮评审的依据
  - 修复建议：r2 回应表必须真实反映修改内容——如 r2 实际改了 board.py 但未改 ai.py，回应表必须标"部分修复"并说明 ai.py 未触及原因；不能虚构"已修复"以绕过 r1 FAIL

- **[一般]** 意见 8：board.py 模块顶部 docstring 体量膨胀（~100 行），混入 r2 修改说明、与 AI 协作约定、未来 TODO 等元信息
  - 依据：r2 board.py 第 1-100 行 docstring 含："Changes vs code r1" 段落（含 r1 review 意见 4 引用）、"Coordination with the AI module" 段落（含对 ai._filter_forbidden / choose_move(..., forbidden=...) 的接口期望声明 + forbidden_cases.run_ai_filter_self_check 的 12 case 引用）、第 100-180 行又重写一遍 __init__/size/snapshot/move_count/get/is_empty/in_bounds/neighbors 等 8 个方法
  - 文件位置：`gomoku/board.py` line 1-180（docstring + __init__）
  - 影响：docstring 中对不存在的模块（ai._filter_forbidden, forbidden_cases.run_ai_filter_self_check）的引用是死引用——读者按图索骥会撞墙；模块文档应聚焦本模块契约，不应包含跨模块协作约定
  - 修复建议：board.py docstring 删除"Changes vs code r1"段落（变更说明放 README/CHANGELOG，不放源码顶部）；"Coordination with the AI module"段落删除（属 ai.py 文档职责）；只保留 plan §5.2 算法引用与本模块接口契约

- **[建议]** 意见 9：r2 README §11.2 表中"r1 判定"列引用错误——把 r1 review 未提的形态（`XX.X`/`XX.X.`/`XXX_`）说成"r1 漏判"，但 r1 评审实际未对 board._is_live_three 提出意见
  - 依据：r1 review 10 项检查中只对 board._is_live_three 提了一般 意见 2（连续 4 run 漏判 broken four），未提活三漏判；§11.2 表"XX.X (落 X 处，前方延伸) r1: ❌ 漏判"无法在 r1 review 中找到出处
  - 文件位置：r2 README §11.2 表第 6-8 行
  - 影响：自测汇总不可信——表格无证据链支撑
  - 修复建议：删除 §11.2 表中无 r1 review 出处的"漏判"声明；只保留对照表驱动断言能复现的形态（plan §5.2 附录 A 的 A1~A15）

## 3. 遗留事项（仅 PASS 时）

本轮 FAIL，不列遗留；下列作为下次评审的复查项：

1. 意见 1 修复后必须补：r2/gomoku/ 7 个源文件（__init__/__main__/config/board/ai/ui/main）全部恢复，且 ai.py 含 `choose_move(..., forbidden=...)` 预过滤逻辑，main.py `_apply_ai_move` 在 safety-net 之外另有预过滤；附 12-case 强制对照（forbidden_cases.run_ai_filter_self_check 可独立运行）
2. 意见 2 修复后必须补：`python3 -m py_compile gomoku/board.py` 退出码 0；`python -c "from gomoku.board import Board; b=Board(15); print(b.size)"` 通过；`gomoku --help` 退出码 0 且 help 文本含全部 4 项 CLI 参数
3. 意见 3/7 修复后必须补：r2 README §11.1 回应表的"修复位置"列必须指向实际修改的文件（ai.py + main.py），不能继续指向 board.py；自测汇总引用脚本路径必须可独立运行（不放 /tmp，放 r2/ 自检脚本）
4. 意见 4 修复后必须补：r2 README §11.1 必须列出 r1 review 全部 5 条意见的回应（意见 2/3/4/5），不能只回应意见 1
5. 意见 5 修复后必须补：r2 README §11.4 改为如实描述——要么声明"r2 仅交付 board.py + 自检，其他模块 r1 已交付可直接复用"，要么补齐全部模块；自测汇总脚本路径必须在 r2/ 目录下可访问
6. 意见 6 修复后必须补：`pyproject.toml version` 与 `__init__.py:__version__` 统一为 0.3.0（不倒退）
7. test-developer 阶段启动前应核对：r2 全部模块就位 + r2 回应表与实际修改一致，再启动 testplan §3.2 用例编写（避免在残缺代码上写测试再发现集成不工作）