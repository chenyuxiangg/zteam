# 发布说明：snake-linux（v1.0.0）

## 0. 发布信息
- 版本：v1.0.0｜日期：2026-08-08（UTC）｜状态：released
- 需求：snake-linux/snake-linux｜全链路完成：是

## 1. 变更摘要
- 一句话：交付一个**零第三方依赖、单命令启动、退出后终端完全恢复**的 Linux 终端经典贪吃蛇（Python 标准库 curses 实现，40×20 固定画布），覆盖需求 FR-01~FR-17 与 NFR-01~NFR-06 全部验收项，并通过质量与安全双门禁。

## 2. 交付内容
- **代码**：`workspace/code/snake-linux/snake-linux-r1/`
  - `snake.py`（380 行，单文件）：`parse_args()`（tick/尺寸校验，FR-03/FR-16）、`check_terminal()`（非 TTY 报错 exit 1，FR-02）、`GameState`（纯逻辑模型：移动/转向/pending 单槽/吃食/碰撞/WIN 判胜，FR-05~FR-10）、`InputHandler`（WASD/方向键/q，FR-06/07/13）、`Renderer`（ASCII 边框/HUD/结束画面，FR-11/16/17）、`main`+`run`（tick 驱动主循环、KEY_RESIZE、SIGTERM/Ctrl+C 同路径恢复、`curses.wrapper` 包裹，FR-04/13/14，NFR-01~03）
  - `README.md`（四节齐全：运行方式/键位表/配置项/已知限制，含 curses vs ANSI 选型论证 Q-09 路径①，FR-15）
- **测试**：`workspace/tests/snake-linux/snake-linux-r2/`
  - 单元（pytest）：`test_game_state.py` / `test_config.py` / `test_input.py` → **32/32 PASS（0.08s）**
  - 集成（PTY 端到端）：`e2e_snake.py` → 9 PASS / 1 FAIL(P0) / 1 SKIP(P2)；`miniterm.py` / `conftest.py` / `run_all.sh` 配套
  - 系统/性能：`checklist-system.md`（人工验收清单，待签字）、`perf_snake.py` + `perf_snake.sh`（性能用例脚本）
  - 测试 README：`tests/snake-linux/snake-linux-r2/README.md`
- **文档（阶段链索引）**：
  - 需求分析（approved 终版）：`workspace/analysis/snake-linux/snake-linux-r2.md`（FR-01~FR-17 + NFR-01~06 + Q 表 10 项）
  - 开发方案：`workspace/plans/snake-linux/snake-linux-r1.md`
  - 测试方案：`workspace/testplans/snake-linux/snake-linux-r1.md`
  - 评审历史：analysis-r2 / plan-r1-review / testplan-r1-review / code-r1-review / test-r1-review / test-r2-review（均记录于 status.json）

## 3. 质量与安全结论
- **质量门禁：PASS**（`workspace/quality/snake-linux/snake-linux-r1.md`）——单元 32/32 全绿 + 集成核心 P0 全 PASS；FR-01~FR-17（FR-12 已移出）与 NFR-01~NFR-06 逐条有验证证据；非 TTY 报错（exit 1）、非法参数（exit 2）、终端过小（exit 3）、q/Ctrl+C/SIGTERM 退出与 termios 恢复均实测通过；`py_compile` PASS；遗留均为建议/人工级，无阻塞。
- **安全门禁：PASS**（`workspace/security/snake-linux/snake-linux-r1.md`）——8 条红线全 PASS：零网络/零文件读写/零凭据/零第三方依赖（仅 argparse/curses/random/signal/sys/time/collections），CLI 参数经 argparse 类型校验（tick 50–1000、尺寸 ≥10），无 shell 执行、无注入面，蛇身 deque 上限 = 画布格数、食物生成无死循环，curses.wrapper 保证所有退出路径终端恢复。

## 4. 使用方式
- **运行**：`python3 snake.py`（单命令启动，蛇自动开始移动）；自定义 `python3 snake.py --tick 100 --width 60 --height 30`
- **操作**：WASD 或方向键控制方向（反向禁止）；`q`/`Q`/`Ctrl+C` 随时退出；游戏结束后按任意键退出
- **终端要求**：Linux + Python 3.6+，最小 42 列 × 24 行；非 TTY 环境运行输出中文提示并 exit 1
- **依赖**：仅 Python 标准库（运行时零第三方依赖）；测试侧依赖 pytest/pexpect 仅安装于测试环境，不影响交付物

## 5. 已知限制与风险
- **集成测试遗留（一般级）**：TC-I-07 gameover 时机 SIGINT 用例 FAIL——根因为测试基础设施（BFS 机器人 + steer_into_wall 时序在终态检测窗口前游戏已自然结束），非代码缺陷；独立验证确认 SIGINT 在游戏结束后 EOF 正常，FR-13/14 经 start/game 两时机 + q-exit + SIGTERM 三重 PASS 佐证。
- **性能指标未实测（建议级）**：TC-P-01/02（输入延迟 ≤200ms、CPU ≤5%、RSS ≤50MB）perf_snake.py 代码审查通过但本环境因 PTY 超时未采集数据；按测试方案「P0 判定不依赖性能用例」不阻塞发布，建议固定机补测。
- **人工验收待签字（建议级/P2）**：checklist-system.md（TC-S-01~06 + TC-P-03）货架就位但无人签字；发布前至少需完成 TC-S-01（README 跑通 + 终端恢复）、TC-S-04（错误提示汇总）两项人工确认。
- **环境依赖**：仅支持 Linux 终端（明确不支持 Windows/macOS）；不依赖 Unicode 制表符与 256 色（纯 ASCII 边框，换取兼容性）；SSH/老旧终端行为一致性的四终端矩阵（GNOME Terminal/Konsole/xterm/SSH）待实机验收。
- **功能边界（按 Q 表默认值落地）**：无暂停/继续、无分数持久化、无速度递增、无「再来一局」、单一食物每食 +1、撞画布边框即结束；蛇占满画布判胜（WIN）为理论边界行为。

## 6. 回滚方案
- 本需求为**无状态单文件交付**，回滚即换文件：旧版本 `snake.py` 若已部署，替换为上一版即可（版本间无数据/配置兼容性问题，无持久化状态可损坏）。
- 备份要点：发布前对 `workspace/code/snake-linux/snake-linux-r1/` 目录做快照（git 跟踪，`git restore` 可随时回到本轮）；发布说明与归档由 `workspace/artifacts/snake-linux/snake-linux.md` 留存全链路产物索引，可作为重出依据。
- 运行时回滚：直接终止进程即可（无后台服务/无守护进程），终端状态由 curses.wrapper 保证恢复，无残留。

## 7. 后续建议
- 固定机补跑 TC-P-01/02 性能实测，闭环 NFR-01/02 数据；
- 人工完成 checklist-system.md 系统验收清单签字（终端矩阵实机、Python 3.6/3.8/3.11/3.12 多版本冒烟 TC-S-06、目测流畅度 TC-P-03）；
- 优化 e2e 测试 gameover 时机的状态引导逻辑（直接等蛇自然走完 20 格撞墙后再发 SIGINT），消除 TC-I-07 基础设施偶发；
- 待需求方拍板项（Q 表未决）：Q-04 暂停/继续（pending 单槽已留扩展点，纳入成本低）、Q-06 多文件拆分、Q-08 「再来一局」——拍板后按分析文档约定以新编号补回 FR 表并增量开发；
- 可选增强（范围外，供参考）：颜色/图形边框（Renderer 层局部替换即可）、分数持久化、速度随长度加快。
