# 测试评审：tetris/tetris（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：自动化测试全绿（72 单元 + 16 集成 + 5 系统脚本 + 2 性能），覆盖完备有效，仅人工清单待填写。
- 评审轮次：r1（test 阶段第 1 轮，依据上游 testplan r2 / code r2）

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据/缺失说明 |
|---|--------|------------------|--------------|
| 1 | 方案符合性 | PASS | 测试方案 §3.2 用例表全部实现：TC-U-01~20（单元/模型层）、TC-I-01~16（集成/PTY 层）、TC-S-01~06（系统验收层）、TC-P-01~03（性能层）；P0 用例逐条勾对无遗漏。每个测试函数头部注释标注了对应的测试方案用例编号与关联 FR |
| 2 | 可运行 | PASS | 单元：72/72 passed (0.09s)；集成：16/16 passed (54.6s)；系统脚本：5/5 passed；性能：2/2 passed。实测结果见 results/r2-regression.log。README 运行方式可复现（pytest / bash e2e_tetris.sh / python3 sys_acceptance.py / bash perf_tetris.sh） |
| 3 | 有效性 | PASS | 测试均使用真实行为断言——TC-U-01 逐方块逐格对照方案 §4.2 占格坐标表；TC-U-02 旋转 4 次还原 + I/O/T 特定断言；TC-U-03~20 通过构造确定性 GameState（first_type 参数）注入 board 场景验证碰撞/消行/计分/等级/撞顶/暂停等；集成层用 pyte 屏幕仿真做文本/颜色/termios 断言（TC-I-08/16），非空转 |
| 4 | 边界覆盖 | PASS | 测试方案 §3.3 边界汇总全覆盖：非法 tick（49/2001/abc/-100，TC-U-16）、非 TTY（TC-I-02/TC-S-04）、过小终端（TC-I-03）、旋转碰撞拒绝（TC-U-06）、贴壁移动拒绝（TC-U-05）、多行同消 1/2/4（TC-U-09）、差一格不满不消（TC-U-18）、撞顶（TC-U-12）、负 y/出界坐标不越界（TC-U-19）、O 方块旋转不变（TC-U-02）、暂停期间冻结（TC-U-15）、计分多轮累计（TC-U-20）、信号三时机退出（TC-I-08）、SIGTERM（TC-I-09）、运行中 resize（TC-I-13） |
| 5 | 独立性与稳定性 | PASS | 单元层通过构造确定性 GameState（first_type 参数 + 手工填 board）避免对随机序列的依赖，全部可复现。conftest.py 干净注入被测代码路径（sys.path.insert）。集成层使用 expect 屏幕轮询 + 超时重试替代固定 sleep。无 mock 框架依赖（逻辑层无外部依赖可 mock） |
| 6 | 报告质量 | PASS | 运行结果记录清晰：results/r2-regression.log 含每层汇总（PASS/FAIL/耗时）与单用例详情。退出码正确：全 PASS = 0，任一 FAIL = 1。性能层记录测量方法与开销分离说明 |
| 7 | 与代码评审衔接 | PASS | code r1 评审结论为 **PASS**，2 条建议（keypad 注释冗余标注、O 方块置中注释）已在 code r2 采纳（见 code/README.md §八 修改回应表）。测试代码通过 conftest.py 指向 code r2，已实测 72/72 + 16/16 + 5/5 + 2/2 全绿，行为一致性验证通过（code r2 与 code r1 核心逻辑一致） |
| 8 | 效率 | PASS | 单元：0.09s（72 用例）；集成：54.6s（16 用例，含 PTY 启动/屏幕等待）；系统脚本：< 5s；性能：~70-90s。全量 < 3 分钟，无无谓等待（PTY 用例使用 wait_frame 轮询而非固定大 sleep） |
| 9 | 不越界 | PASS | 测试代码只做测试：导入被测模块 + 断言 + 屏幕/信号注入。未修改被测代码（tetris.py），未写业务功能。conftest.py 只调整 sys.path 不改变被测模块行为 |
| 10 | 可审计 | PASS | 新目录 tetris-r1，独立 results/ 子目录。文件命名规范（test_tetrominoes.py / test_game_state.py / test_config.py / test_input.py / e2e_tetris.py / sys_acceptance.py / perf_tetris.py）。每测试函数以用例 ID 命名（test_tc_u01_*）。README 含完整运行方式与判定标准。修改回应（r1→r2 增量）在 README 中记录 |

## 2. 评审意见列表
- **[一般]** 人工清单 `system_checklist.md` 全部未填写（TC-S-01 P0 / TC-S-03 P2 / TC-S-05 P2 / TC-S-06 P2 / TC-P-03 P2 均为 `[ ]` 未勾选）
  - 依据：测试方案 §2 通过标准——「系统层：人工清单逐项打勾，无『未验证』项遗留」；当前 system_checklist.md 所有勾选框均未打勾，系统层完整通过标准未满足
  - 说明：人工清单项需真实终端 + 人工操作（完整一局试玩/终端矩阵实机/代码可读性走查/多版本实机冒烟/渲染流畅度目测），测试开发者无法自行完成，属正常分工边界；应在质量门禁前由验收人逐项操作并回填
  - 注：本条为一般问题（仅 1 条 < 3 条），不阻塞 PASS

## 3. 遗留事项（仅 PASS 时）
- **人工清单待填写**：`system_checklist.md` 中 TC-S-01（P0，完整一局跑通）、TC-S-03（P2，终端矩阵 4 环境）、TC-S-05（P2，代码可读性走查）、TC-S-06（P2，Python 3.6/3.8/3.12 实机验证）、TC-P-03（P2，渲染流畅度目测）需在质量门禁前由验收人逐项完成并打勾；自动化部分（单元 72/72、集成 16/16、系统脚本 5/5、性能 2/2）已全部通过
- **TC-I-05 偶发性超时风险**：连续硬降堆叠至撞顶需最长 25s（硬编码 deadline），在极端情况（初始方块连续 I 方块竖放）可能不够——当前 r2 实测通过，后续长稳运行关注；单元层 TC-U-12（撞顶判定）已精确覆盖逻辑面，即使集成超时也不漏检
- **性能指标标注已完成**：NFR-01/02（输入延迟 ≤50ms P95、CPU ≤5%/RSS ≤50MB）已按 analysis r2 R1-04 标注为建议项；实测 TC-P-01（avg=13.2ms P95=14.0ms）与 TC-P-02（avg_cpu=1.81% peak_rss=17.3MB）全部远优于阈值，即使需求方移除也不影响交付质量
