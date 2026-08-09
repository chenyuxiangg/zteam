# 代码评审：tetris/tetris（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：方案完全落地，语法通过，核心逻辑逐 FR 勾对正确，边界与错误处理齐全，可运行可交付。
- 评审轮次：r1

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据/缺失说明 |
|---|--------|------------------|--------------|
| 1 | 方案符合性 | PASS | 模块分层（parse_args/TETROMINOES+rotate_cw/GameState/InputHandler/Renderer/main/wrapper）与方案 §3.2 一致；数据结构（Point/TETROMINOES/GameState 字段）与方案 §4.2 一致；接口（python3 tetris.py / --tick / --no-color / 键位全集）与方案 §4.1 一致；关键算法（collides/clear_lines/hard_drop/暂停相位补偿）与方案 §5.1 一致。clear_lines 采用 reversed(full) 修正方案片段中「自上而下删除导致行号错位」的隐患，并在注释中说明，属正向改进。 |
| 2 | 可运行 | PASS | `python3 -m py_compile` 通过；入口 `python3 tetris.py` 明确；README「运行方式」可复现；PTY 冒烟启动并干净退出成功；--help / --tick 越界 / 非 TTY 三条路径错误处理实测通过。 |
| 3 | 功能正确性 | PASS | FR-05（7 方块定义与旋转还原）✓；FR-06/07/08/09（spawn/下落/移动/旋转）✓；FR-10/11（软降/硬降）✓；FR-12（锁定→消行→计分→next 接续）✓；FR-13（撞顶 spawn 重叠→OVER）✓；FR-14（多行同消、上方下移）✓；FR-15（计分 100/300/500/800）✓；FR-16（level=lines//10+1、tick_ms=max(100, base*0.9^(level-1))）✓；FR-18（WASD+方向键+空格+P+q）✓；FR-19（暂停切换+相位补偿）✓；FR-20（q/Ctrl+C/SIGTERM 全路径）✓；FR-21/22（next/HUD 渲染）✓；FR-23（wrapper 终端恢复）✓；FR-24（结束画面 得分+任意键退出）✓；FR-25（README 五节齐全含选型论证）✓；FR-26（--no-color + 颜色自动降级）✓。共 23 项 FR（FR-17 按 Q-01 作废）全部覆盖。 |
| 4 | 边界与异常 | PASS | 对照方案 §5.2 边界表逐项核对：（非 TTY→exit 1+可读提示）✓；（终端过小→尺寸提示+exit 3）✓；（旋转阻挡→碰撞拒绝）✓；（快速连按→单线程事件驱动）✓；（撞顶→状态 OVER）✓；（Ctrl+C/SIGTERM→同恢复路径）✓；（绘制闪烁→全量重绘）✓。额外覆盖：TERM 环境变量缺失、游戏中 resize 尺寸重查、C locale 中文 stderr 安全写入（_write_stderr 用 os.write 绕开 UnicodeEncodeError）。 |
| 5 | 安全与合规 | PASS | 输入校验（--tick [50,2000]，越界 exit 2 + argparse 出错信息）✓；无敏感数据（无网络/文件读写/凭据）✓；无需 root 权限 ✓；curses.error 启动失败兜底为可读错误（非 traceback）✓；NFR-04 所有可预见失败场景输出人类可读提示 ✓。 |
| 6 | 可读可维护 | PASS | 文件头注释完整（职责声明+方案章节映射）✓；模块间以 `# ---` 分隔线+标题清晰划分 ✓；关键函数含 docstring ✓；变量命名清晰（SCORE_TABLE/MIN_TICK_MS/LINES_PER_LEVEL 等常量集中声明）✓；GameState 模型层纯逻辑不依赖 curses（方案 §2 选型结论）✓；关键算法（collides/clear_lines/硬降/相位补偿）有注释说明 ✓。单文件 ~660 行但按职责严格分层，方案 §6 已就该张力做预案（评审不认可时拆包成本 < 1h）。 |
| 7 | 错误处理 | PASS | 退出码常量集中声明（EXIT_OK=0/EXIT_NOT_TTY=1/EXIT_BAD_ARGS=2/EXIT_TOO_SMALL=3/EXIT_INTERRUPTED=130）✓；非 TTY + 缺 TERM → exit 1 ✓；tick 非法 → exit 2 ✓；终端过小 → exit 3 ✓；curses 启动失败 → 捕获 curses.error 输出可读错误 ✓；KeyboardInterrupt → 友好退出 ✓；_put_cell 渲染越界 → 静默忽略（防 resize 竞态崩溃）✓。全部错误路径有明确语义无非静默吞掉。 |
| 8 | 性能与资源 | PASS | 单线程 ✓；每帧全量重绘（10×20=200 格，性能充裕）✓；timeout(25) 轮询（输入响应 ≤25ms ≪ 500ms tick）✓；固定大小 board（无动态增长）✓；无文件句柄/网络连接泄漏 ✓；collides 与 clear_lines 为 O(rows×cols) 常数级 ✓。NFR-01/02 指标预算满足。 |
| 9 | 不越界 | PASS | 未混入测试代码 ✓；未修改需求原文 ✓；未修改方案/需求分解文档 ✓。 |
| 10 | 可审计 | PASS | 新目录 `workspace/code/tetris/tetris-r1/` ✓；README §8 修改回应表（首轮为空）✓；代码文件头与 README §6 含方案章节映射 ✓。 |

## 2. 评审意见列表
- **[建议]** `main()` 中调用了 `stdscr.keypad(True)` 但 `curses.wrapper()` 已自动设置 keypad（CPython 3.x 实现确认），虽有冗余但无副作用。建议在注释中标注 "wrapper 已设置，此处显式调用为文档化意图"，增强可读性。（位置：tetris.py 第 554 行）

- **[建议]** O 方块（2×2 田字）放置于 4×4 矩阵的中部（行 1-2、列 1-2），是正确的设计——保证了旋转 4 次不变（标准表现）。建议在 TETROMINOES 定义的注释中显式说明「O 方块置中保证旋转不变性」，与 rotate_cw 的 docstring（第 184 行）形成交叉引用。（位置：tetris.py 第 52-57 行）

## 3. 遗留事项（仅 PASS 时）
- 软降手感依赖 OS 键盘重复率（FR-10 验收口径「明显快于自动下落 + 松开恢复」已满足，方案 §6 风险对策已记录增强方案「按住计时软降」，暂无阻塞）。
- 单文件 ~660 行 vs NFR-05「源文件职责单一」的张力——方案 §6 已就此事做预案、README §5.3 已声明，当前分层清晰；若测试开发者反馈职责分离不足，可按方案 §8 Q-06 拆为 `tetris/` 包（成本 < 1h）。
- 纯随机连续出同型方块：Q-03 默认纯随机，README §5.3 已记录增强项（7-bag），无阻塞。
