# 代码评审：tetris/tetris（r2）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：r2 为注释/文档级修改轮，方案 r2 增量全部落地，核心逻辑零改动，r1 评审 2 条建议已采纳，回归验证通过。
- 评审轮次：r2

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据/缺失说明 |
|---|--------|------------------|--------------|
| 1 | 方案符合性 | PASS | 方案 r2 全部增量已落地：①TETROMINOES 注释新增 7 方块占格坐标表（tetris.py L49-57，与方案 §4.2 逐格一致）；②MIN_COLS/MIN_LINES 注释补全 42×26 完整推导（L114-121）；③README §5.3 新增单文件分层声明（方案 §3.2）；④soft_drop/_lock_and_spawn/tick 推进/main timeout 注释补绝对值口径（L341-343/L363-365/L583/L654-657）；⑤README §5.3 新增 NFR-01/02 建议项标注（方案 §5.3）；⑥文件头与 README §四 落注 tick 术语定义（L29-31）。架构/数据结构/接口/算法与 r1 完全一致（r1 评审已 PASS）。 |
| 2 | 可运行 | PASS | `python3 -m py_compile tetris.py` 通过；入口 `python3 tetris.py` 明确；README「运行方式」可复现；r1 单元测试全集回归（71/71）对 r2 代码通过（README §七）。 |
| 3 | 功能正确性 | PASS | 核心逻辑零改动（README §8「核心逻辑零改动」+ 71/71 回归通过佐证）；7 方块定义与方案 §4.2 坐标表逐格一致（本地验证：每方块恰 4 格、O 方块旋转不变、4 次旋转还原、I 方块横竖翻转正确）；全部 FR-05~FR-16/FR-18~FR-26 覆盖与 r1 一致（r1 评审逐 FR 勾对已 PASS）。 |
| 4 | 边界与异常 | PASS | 与 r1 一致：非 TTY（check_terminal→exit 1 ✓）、终端过小（size_ok+draw_size_error→exit 3 ✓）、旋转阻挡（collides 拒绝 ✓）、撞顶（spawn 重叠→OVER ✓）、Ctrl+C/SIGTERM（wrapper+signal handler 同路径 ✓）、C locale（_write_stderr os.write 安全写入 ✓）、游戏中 resize（KEY_RESIZE→resizeterm+尺寸重查 ✓）；无 r2 引入的退化。 |
| 5 | 安全与合规 | PASS | 输入校验（--tick [50,2000]，越界 exit 2+argparse 出错信息 ✓）；无敏感数据/网络/文件读写/凭据 ✓；无需 root ✓；curses.error 启动失败兜底可读错误 ✓；全部可预见失败场景输出人类可读提示（NFR-04 ✓）。 |
| 6 | 可读可维护 | PASS | r1 基础（分层清晰/注释齐全/常量集中）保持 ✓；r2 增量增强可读性：7 方块坐标表消除 J/L 方向与 T/S/Z 朝向歧义（评审建议 2）✓；O 方块置中设计注释与 rotate_cw 交叉引用 ✓；main() keypad 调用注释标注"wrapper 已设置，显式调用为文档化意图"（评审建议 1）✓；42×26 推导代码级注释 ✓。 |
| 7 | 错误处理 | PASS | 与 r1 一致：退出码常量集中 ✓；非 TTY+缺 TERM→exit 1 ✓；tick 非法→exit 2 ✓；终端过小→exit 3 ✓；curses 启动失败→捕获 curses.error ✓；KeyboardInterrupt→友好退出 ✓；渲染越界→静默忽略 ✓。全部错误路径语义明确。 |
| 8 | 性能与资源 | PASS | 与 r1 一致：单线程 ✓；全量重绘 200 格 ✓；timeout(25) 轮询 ✓；固定 board 无动态增长 ✓；无文件/网络句柄泄漏 ✓；碰撞/消行 O(rows×cols) 常数级 ✓。r2 无性能退化。 |
| 9 | 不越界 | PASS | 未混入测试代码 ✓；未修改需求原文 ✓；未修改方案/需求分解文档 ✓。 |
| 10 | 可审计 | PASS | 新目录 `workspace/code/tetris/tetris-r2/` ✓；README §8 修改回应表逐条回应 r1 评审 2 条建议+plan r2 6 项增量 ✓；代码文件头与 README §六 含方案章节映射 ✓；r2 相对 r1 代码变更清单完整（README §8 末段）✓。 |

## 2. 评审意见列表
本轮为修改轮（r2），上轮评审（r1）结论 PASS，2 条建议均已在 r2 采纳落地：

- **[r1 建议 1，已采纳]** `main()` 中 `stdscr.keypad(True)` 冗余调用：已在 tetris.py L579-581 新增注释"curses.wrapper() 已自动设置 keypad，此处显式调用为文档化意图"。

- **[r1 建议 2，已采纳]** O 方块置中设计与 rotate_cw 交叉引用：TETROMINOES 注释 L51 新增"置中保证旋转不变性，见 rotate_cw"；rotate_cw docstring L203-204 新增"O 方块因置中于 4×4 中部，旋转后矩阵不变——标准表现"并回指 TETROMINOES。

r2 无新增严重或一般问题。

## 3. 遗留事项（仅 PASS 时）
- 软降手感依赖 OS 键盘重复率（FR-10 绝对值口径 ≥4× 已通过键盘重复率天然满足，方案 §6 风险对策已记录增强方案"按住计时软降"，非阻塞）。
- 单文件物理形态与 NFR-05 的张力：README §5.3 已显式声明逻辑分层为职责边界，方案 §8 Q-06 拆包预案成本 < 1h，非阻塞。
- 纯随机连续同型方块：Q-03 默认纯随机，README §5.3 已记录增强项（7-bag），非阻塞。
