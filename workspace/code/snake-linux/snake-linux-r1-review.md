# 代码评审：snake-linux/snake-linux（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：代码完整实现方案全部模块与接口，逐 FR 勾对通过，py_compile 通过，边界/退出路径/终端卫生均到位。
- 评审轮次：r1

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据/缺失说明 |
|---|--------|------------------|--------------|
| 1 | 方案符合性 | PASS | 模块（parse_args/check_terminal/GameState/InputHandler/Renderer/main）划分与方案 §3.2 一致；数据结构（Point namedtuple/deque 蛇身/pending 单槽/score/status）对齐方案 §4.2；ASCII 边框/HUD/结束画面对齐方案 §5.2；tick 50ms 切片+monotonic 计时对齐方案 §5.1；MIN_DIM=10 对齐方案 §5.3。偏差：方案伪代码提了 halfdelay 但代码用 timeout(50)（毫秒级），更精细，属改进而非违背。 |
| 2 | 可运行 | PASS | `python3 -m py_compile` 通过；入口 `__name__ == '__main__'` 调用 `run()` 明确；README 四节齐全（运行方式/键位表/配置项说明/已知限制），「运行方式」含完整启动命令与退出说明、终端要求、非 TTY 报错与退出码语义；零第三方依赖（仅 argparse/curses/random/signal/sys/time/collections）。 |
| 3 | 功能正确性 | PASS | 逐 FR 勾对：FR-01 单命令启动（snake.py 零依赖）✓；FR-02 非 TTY 报错（check_terminal/isatty/stderr+exit 1）✓；FR-03 tick 50–1000 可配（_tick_type 校验+argparse）✓；FR-04 终端能力检查（启动 COLS≥W+2/LINES≥H+4+KEY_RESIZE 暂停提示）✓；FR-05 蛇自动前移（step 每 tick 头进 1 格）✓；FR-06 WASD/方向键（InputHandler 双映射）✓；FR-07 反向禁止（_is_opposite 校验当前+待定双向）✓；FR-08 食物生成（空列表选点、不与蛇身重叠）✓；FR-09 吃食增长得分（eating 时仅 append 不 popleft+score+1）✓；FR-10 撞墙/撞自身（坐标越界+body set 含尾部让行判定）✓；FR-11 结束画面（draw_game_over 居中显示得分+退出提示）✓；FR-13 q/Ctrl+C/SIGTERM 退出（is_quit→break/KeyboardInterrupt/_sigterm_handler）✓；FR-14 终端恢复（curses.wrapper finally 自动恢复）✓；FR-15 README（四节齐全+选型论证）✓；FR-16 游戏区域（ASCII +-| 边框，40×20 画布）✓；FR-17 HUD（顶部固定行持续显示 Score/tick）✓。核心算法（尾部让行、pending 单槽、空闲格列表食物生成）无逻辑错误。 |
| 4 | 边界与异常 | PASS | 对照方案 §5.2 边界表逐项核对：非 TTY→exit 1 ✓；终端过小启动→exit 3 ✓；KEY_RESIZE 不足→暂停提示+q 可退出 ✓；快速连按→pending 单槽+双向反向校验 ✓；Ctrl+C→wrapper 恢复+exit 130 ✓；SIGTERM→同路径 ✓；蛇占满→WIN ✓；全量重绘无残影 ✓；单线程无并发面 ✓；_safe_add 防 resize 越界崩溃 ✓。tick 越界（49/1001/abc/-100）与尺寸非法（0/负数/9×9）均触发 argparse 中文报错+exit 2（对齐 TC-U-11/TC-U-12）。 |
| 5 | 安全与合规 | PASS | 输入校验：tick 50–1000、尺寸≥10、非整数报错（_tick_type/_dim_type）；无网络/无文件读写/无凭据，无数据安全面；仅需普通用户权限，不写系统路径；Python 3.6 兼容：无 dataclass/海象/str.removeprefix（对齐方案 §5.3）。 |
| 6 | 可读可维护 | PASS | 命名清晰（GameState/InputHandler/Renderer/Point）；类/函数职责单一（模型层不依赖 curses、渲染/输入/配置分层）；关键逻辑有中文注释（尾部让行/pending 单槽/空闲格列表意图）；文件头有模块映射表（类→方案章节→FR）。单文件 ~290 行，长度适中。 |
| 7 | 错误处理 | PASS | 非 TTY→stderr 中文提示+exit 1；终端过小→stderr 提示+exit 3；参数非法→argparse 中文报错+exit 2；KeyboardInterrupt→stderr 友好信息+exit 130；通用异常→stderr 提示+exit 1（无裸 traceback，NFR-04）。无静默吞错误路径；退出码语义一致（1=非TTY/异常，2=参数，3=尺寸，0=正常/退出，130=中断）。 |
| 8 | 性能与资源 | PASS | 50ms getch 切片非忙等（NFR-02）；time.monotonic() 单调时钟避免系统时间跳变（NFR-01）；40×20 全量重绘耗时远小于 50ms；单线程无资源竞争；curses.wrapper finally 保证终端状态恢复（无资源泄漏）。 |
| 9 | 不越界 | PASS | 代码仅含游戏实现（snake.py+README.md），未混入测试代码；未修改需求原文（workspace/input/）；未修改 plan/analysis 文档。 |
| 10 | 可审计 | PASS | 新目录 code/snake-linux/snake-linux-r1/ 独立存放本轮交付；首轮无上轮评审意见需回应。 |

## 2. 评审意见列表
- **[建议]** snake.py:269（`run()` 中 `sys.exit(code)`）：当 `main()` 返回 `3`（终端尺寸不足）时，`curses.wrapper` 已调用 `curses.endwin()` 做终端恢复，此后 `sys.exit(3)` 恰当。但若未来主循环返回其他非零退出码（如新增的配置校验），建议在 `run()` 的 except 分支中统一退出码语义并在 README 退出码表中记录。当前轮次不阻塞。
  - 依据：方案 §4.1 退出码表仅定义了 0/1/2/3/130，现有实现完全对齐。
- **[建议]** snake.py:248（`_handle_resize` 中 `while True` 循环）：尺寸不足暂停期间 `stdscr.getch()` 以 50ms 超时轮询，CPU 占用极低但并非零。可考虑在循环中加入 `time.sleep(0.1)` 降低轮询频率，或在非 resize 的 getch 中提高超时值。当前不影响 NFR-02 指标，建议后续优化。
  - 依据：方案 §5.2 边界表「终端过小」处理已正确实现。

## 3. 遗留事项（仅 PASS 时）
- README 中「自测记录」声明了开发期自测 17 项通过，正式测试应由 test 阶段按 `testplans/snake-linux/snake-linux-r1.md` 独立执行——此非代码缺陷，为流水线职责边界提醒。
- 若 Q-04（暂停/继续）后续确认纳入，代码 `pending` 单槽已留扩展点，主循环与 HUD 加暂停态改动量约 30 行。
- 若 Q-06 拍板从单文件改为多文件包，按 §3.2 分层拆为 `snake/` 包代价低（模型层不依赖 curses 使得 model.py 可独立拆出）。
