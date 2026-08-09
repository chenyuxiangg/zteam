# 代码评审：gomoku（r1）

## 0. 评审结论
- 结论：**FAIL**
- 一句话理由：FR-07 禁手双三判定使用 5 格固定窗口策略，漏算"前方已延伸"的活三形态，导致双三局面被错判为合法——核心规则失效。
- 评审轮次：r1

## 1. 检查清单核对表

| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | 模块划分（main/board/ai/ui/config）与 plan §3 一致；CLI 参数、Board API、choose_move 接口、状态机均符合 plan §4 |
| 2 | 可运行 | PASS | `python3 -m py_compile` 7 个模块全绿；`python3 -m gomoku --help` 正常输出；`import gomoku` 成功；依赖 rich 已安装可解析 |
| 3 | 功能正确性 | **FAIL** | FR-09 胜负判定 4 方向 + 边界 + 长连 + 满盘 10 个用例全过；FR-04 坐标解析 18 类输入（含极端/全角/控制字符/超长/占用）全过；**FR-07 禁手双三漏判**：见 §2 意见 1 |
| 4 | 边界与异常 | PASS | parse_move 抛 MoveError 带 reason（format/out_of_range/occupied）；Board.place 越界/非 int 返回 False 不抛（UTB-27）；AI 强档时间预算超时返回当前最优（实测 5 次 ≤800ms，远低于 NFR-01 2s） |
| 5 | 安全与合规 | PASS | 无网络/无系统目录写入/无 eval；坐标输入白名单正则先于范围校验，杜绝越界访问 |
| 6 | 可读可维护 | PASS | 模块职责单一（board 纯规则/ai 决策/ui 渲染/main 主控/config 配置）；关键函数有 docstring；命名清晰；`__slots__` 与 frozen dataclass 防意外状态泄漏 |
| 7 | 错误处理 | PASS | MoveError 三种 reason 显式区分；get_move 捕获 EOFError/KeyboardInterrupt/quit 字符串三种退出路径；post_game_prompt 循环校验 y/n 不吞输入 |
| 8 | 性能与资源 | PASS | 强档中盘 P95 ≤ 757ms（5 次采样 max），远低于 NFR-01 2s；UI 渲染用 Table.grid 一次性绘制；undo 不分配新棋盘 |
| 9 | 不越界 | PASS | 仅产出代码 + README + pyproject；未混入 tests/（test-developer 阶段产物）；未改方案/需求原文 |
| 10 | 可审计 | PASS | 每文件顶注 plan §X.Y 引用；board/ai 关键函数 docstring 标注 UTB-XX/UTA-XX/FR-XX 验收条目；`gomoku-r1/` 新目录未覆盖旧版本 |

## 2. 评审意见列表

### **[严重] 意见 1：FR-07 双三禁手漏判，核心规则失效**
- 依据：plan §5.2（"双三 = 落子后该点在 4 方向上形成的'活三'计数 ≥ 2"）、FR-07（禁手开关开启后黑双三判负）、testplan UTB-10/UTB-15
- 位置：`gomoku/board.py` `Board._is_live_three`（行 369–418）
- 缺陷：`_is_live_three` 使用固定 5 格窗口策略，只识别三种模式
  - `[0,1,1,1,0]` `.XXX.`
  - `[1,0,1,1,0]` `X.XX.`
  - `[0,1,1,0,1]` `.XX.X`

  当落子点**前方已存在同色延伸**（如 `..XXX_` 形态，sig=[1,1,1,0,0]）时，5 窗口首格已是 1，三种模式全不匹配，**活三被错判为非活三**。
- 复现：
  ```python
  b = Board(15)
  b.place(7, 7, 'B'); b.place(6, 7, 'B')   # 横 .XX_ 延伸
  b.place(8, 6, 'B'); b.place(8, 5, 'B')   # 纵 .XX_ 延伸
  fb, reason = b.check_forbidden(8, 7, 'B') # 落 (8,7) = 横 .XXX_ + 纵 .XXX_
  # fb == False, reason is None   ← 期望 True, "double_three"
  ```
- 影响：
  1. **核心功能错误**：黑棋可在形成双三（甚至实际双三+更严重局面）的点被判合法，导致黑棋直接"穿帮"下出禁手位置，违反 Renju 规则；
  2. testplan UTB-10（双三棋局 AI/人类黑方落子后正确判负）会 FAIL；
  3. testplan UTB-15（跳活三 `XX_X` 形态）仅覆盖"两侧都有空"窗口——开发可能针对该用例做了特殊处理，但**真实棋局中双三常以"延伸+延伸""延伸+跳""跳+跳"等多种组合出现**，本实现对延伸型无法识别。
- 修复方向（任选其一）：
  1. **改造活三检测**：用 `_line_open_ends` 的 `run + open_ends` 判定（与 `_classify_point` 一致），与禁手判定语义对齐；
  2. **滑动窗口扫描**：枚举 (x±2*dx, y±2*dy) 起始的所有 5 窗口，取最长/最严格匹配；
  3. **拆解为"延伸/跳/连"三子形态枚举**：识别 `_XXX_`/`_X_XX_`/`_XX_X_` 等所有 Renju 标准活三模式（不依赖 5 窗口的位置对齐）。
- 优先级：**P0**，必须修复后重提评审。

## 3. 遗留事项（仅 PASS 时）
（本轮 FAIL，无此节）

## 4. 修改回应表（仅修改轮）
首轮评审，无上轮意见，本表留空。