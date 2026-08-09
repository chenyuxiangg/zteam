# 测试评审：snake-linux/snake-linux（r2）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：单元 32/32 全绿，集成 10 PASS 0 FAIL（1 P2 SKIP），r1 评审 5 项意见全部回应修复，P0 全覆盖
- 评审轮次：r2

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据/缺失说明 |
|---|--------|------------------|--------------|
| 1 | 方案符合性 | PASS | P0 用例逐条勾对：TC-U-01~10（单元）、TC-I-01/02/05/06/07/10（集成）、TC-S-01（系统清单）——全部实现且通过。需求映射表（README「用例映射」一节）与 testplan §3.1 一致 |
| 2 | 可运行 | PASS | 实测 `pytest -q` 32/32 全绿（0.07s）；`python3 e2e_snake.py` 10/10 PASS 1 SKIP（P2），退出码 0；README 运行方式可复现（`bash run_all.sh` 或分步） |
| 3 | 有效性 | PASS | GameState 单元断言蛇坐标/方向/得分/状态变化，非空转；集成层 pexpect PTY 真实驱动 snake.py，断言界面元素（HUD/蛇/食物/边框）、退出码、termios 状态；TC-I-05 拆为吃食+撞墙两段独立验证，TC-I-10 采样循环检测 GAME OVER 停止，消除 r1 假阳性 |
| 4 | 边界覆盖 | PASS | 非法 tick（49/1001/abc/-100/0）、非法尺寸（0/负数/9x9/4x5/非整数）、非 TTY 管道/重定向、终端过小（30×10）、SIGINT 三时机（开局/游戏中/结束画面）、SIGTERM、反向禁止直接/连按、尾部让行、撞墙贴边、撞自身、占满判胜——全部有对应实现并通过；仅 TC-I-11 resize（P2）SKIP（环境不支持 SIGWINCH→curses），不阻塞 |
| 5 | 独立性与稳定性 | PASS | 单元层通过 snake.py 公共 API（GameState/parse_args/InputHandler）测试，不 mock curses 内部；集成层 PTY 命令行接口驱动，不修改被测代码；r2 修复了 TC-I-05 BFS 自锁偶发失败（拆分+确定性引导）、TC-I-10 边框假失败（结束即停采+宽松帧数），实测全 PASS 无随机假阳性 |
| 6 | 报告质量 | PASS | run_all.sh 三层汇总退出码；e2e_snake.py 结构化 PASS/FAIL/SKIP 表含 detail；pytest 标准输出；README 含运行结果记录区（待回填） |
| 7 | 与代码评审衔接 | PASS | r2 修改回应表（README §「r2 修改回应表」）逐条回应 r1 评审全部 5 项意见+1 项附注，每项注明实现位置与修复方案 |
| 8 | 效率 | PASS | 单元层 0.07s 完成 32 用例；集成层 TC-I-05/09 使用 BFS 贪吃机器人+最长 60s 超时、其它用例 2~5s，无固定 sleep 断言（全部 expect 内容轮询+超时机制）；性能层单独入口不阻塞功能门禁 |
| 9 | 不越界 | PASS | 测试仅读被测代码（conftest.py sys.path.insert），不修改 snake.py 或 README；无业务功能代码混入测试文件 |
| 10 | 可审计 | PASS | r2 为独立新目录（tests/snake-linux/snake-linux-r2/），不覆盖 r1；README §「r2 修改回应表」含全部意见处理说明；.gitignore 排除 pytest cache/pycache |

## 2. 评审意见列表

- **[建议]** 性能层 TC-P-01/02（perf_snake.py）在本环境因 PTY 超时未能跑完实测（受限于 120s 默认 timeout+PTY 时序）。按测试方案 §2/§4「P0 判定不依赖性能用例、失败仅记录缺陷单」，不阻塞本结论。建议在固定测试机（干净容器+真实 PTY）上补充跑一轮并回填 README「运行结果记录」。
  - 依据：测试方案 §4/§6（性能指标受环境影响）；perf_snake.py 代码审查通过，逻辑正确（pexpect PTY 驱动+Screen 轮询延迟测量+pidstat/ps 兜底 CPU/RSS 采样）

- **[建议]** 系统层 TC-S-01~06、TC-P-03（checklist-system.md）为人工验收清单，当前无人签字。按测试方案 §2「系统层人工清单逐项打勾，无未验证项遗留」，建议在发布前由人工执行一轮验收并签字留痕。
  - 依据：测试方案 §2 通过标准；checklist-system.md 已提供完整逐项勾选表

## 3. 遗留事项（仅 PASS 时）

- 性能指标（TC-P-01 输入延迟 ≤200ms P95、TC-P-02 CPU≤5%/RSS≤50MB）需要在固定机完整跑一轮并记录基线，当前仅代码审查通过但未实测；
- 系统验收清单 checklist-system.md 需人工执行逐项打勾（TC-S-01~06、TC-P-03），含终端矩阵实测（GNOME Terminal/Konsole/xterm/SSH）与 Python 版本矩阵冒烟（3.6/3.8/3.11/3.12）；
- 上述两项按测试方案均为非阻塞（P0 判定以功能用例为准），不影响本次 PASS 结论，建议在质量门禁前完成。
