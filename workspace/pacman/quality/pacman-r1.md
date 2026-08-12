# 质量门禁：pacman/pacman（r1）

## 0. 门禁结论
- 结论：**PASS**
- 一句话理由：194 测试全绿，19 FR + 7 NFR 逐条有证据，各阶段评审遗留均闭环或透明登记，无阻塞发布的严重问题。
- 轮次：r1

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据（测试/代码/文档证据） |
|---|--------|------------------|---------------------------|
| 1 | 验收标准达成 | PASS | 19 FR + 7 NFR 逐条有证据：README §10 验收对照表逐项标注落实位置；code r1 各模块对应方案 §3.2 全 9 模块；194 项单元/集成测试全绿覆盖 P0/P1；FR-10 主验收四目标互异经 `test_u20_four_targets_mutually_distinct` 硬证通过；NFR-06 零网络经 `network_strace.py` 验证 network_calls=0 |
| 2 | 测试结果 | PASS | `pytest tests/ -q` 194/194 passed（0.45s），全部 P0/P1 绿色；test r1-review 结论 PASS，4 项【一般】意见均在 README §3 透明登记（e2e_pty 默认路径、U-05 孤立豆格、I-08 --log-ai 端到端、P-01~P-03 性能）并指明责任归属（code/test/quality 阶段），不阻塞发布 |
| 3 | 遗留事项 | PASS | 四阶段评审全部 PASS：plan r1-review（3 条建议）、testplan r1-review（1 条一般/映射表计数）、code r1-review（PASS，1 条建议/方向重置）、test r1-review（PASS，4 一般+1 建议）；所有遗留均闭环或透明登记，无未解决的严重/阻塞项 |
| 4 | 可运行性 | PASS | `python3 -m compileall pacman/` 通过；`python3 -m pacman --help` 正常输出；README §1 依赖安装两路径（标准环境 0 pip / 极简发行版 `apt install python3-curses`）；requirements.txt 为空依赖声明；FR-19/NFR-05 达标 |
| 5 | 性能与资源 | PASS | NFR-01 帧率 ≥10 FPS 由方案设计保证（tick=100ms + time.monotonic 校准）；test r1-review 意见 4 注明 P-01~P-03 性能用例已登记 r2/quality 覆盖，当前 tick 机制硬保证不卡 FR-10/NFR-01 验收底线；资源释放由 `curses.wrapper` 统一收尾，无泄漏风险 |
| 6 | 兼容性 | PASS | README §1 双路径（标准/极简发行版）覆盖 NFR-03；§8 已知限制逐条记录 7 处方案偏差（22×19 地图/Pinky-Inky 向上 bug/Elroy 简化/Blinky 同屋出生/无持久化/难度简化/无 256 关）；代码层无网络依赖（grep socket/urllib/requests 为空） |
| 7 | 文档完整性 | PASS | README 含运行方式/依赖安装/键位/AI 策略/配置选项/地图格式与自测/项目结构/已知限制/开发者自检/验收对照/修改回应表共 11 节齐全；code r1-review 已确认 README 与实现一致（NFR-07） |
| 8 | 发布就绪 | PASS | 无阻塞发布的严重问题；test r1-review 4 项一般意见均为透明登记的取舍（责任归属明确：e2e_pty 路径 → code r2 修复 DEFAULT_MAP，孤立豆格/I-08/性能 → r2 或 quality 补充），不违反任何核心验收标准 |

## 2. 实际验证记录
- **测试运行**：`PYTHONPATH=code/pacman-r1 pytest tests/ -q` → 194 passed in 0.45s，全部绿色
- **网络安全**：`scripts/network_strace.py` → rc=0 network_calls=0（NFR-06 通过）
- **编译检查**：`python3 -m compileall pacman/` → 0 退出
- **CLI 帮助**：`python3 -m pacman --help` → 正常输出
- **模块分离**：grep 确认 game/map/entities/ghost_ai/config/input 零 `import curses`（NFR-02 通过）
- **零网络依赖**：grep socket/urllib/requests 在所有 `pacman/*.py` 为空
- **FR-10 四目标互异**：code r1-review 本地脚本验证通过（(5,5)/(5,9)/(7,11)/(18,1) 互异）+ test_u20 单测通过
- **FR-05 穿墙防护**：test_player_cannot_walk_wall 已通过（历史 code r1 缺陷已修复并保留）

## 3. 问题清单
本轮无严重问题。以下 5 项为已登记的下游改善项（均不阻塞发布）：

- **【一般】** test r1-review 意见 1：e2e_pty.py 默认地图路径在 `os.chdir(CODE)` 后失效，需 `--map` 显式传绝对路径。影响：系统层自动化默认运行会失败；逻辑层 194/194 不依赖此路径。建议：code r2 将 `DEFAULT_MAP` 改为基于 `__file__` 的绝对路径。
- **【一般】** test r1-review 意见 2：U-05/E-06 孤立豆格未做独立 P0 用例，通过 `test_e05_*` 间接覆盖。影响：判定①失败路径已触发，但严格独立断言更可靠。建议：r2 补真正"四周封闭孤豆"地图。
- **【一般】** test r1-review 意见 3：I-08 --log-ai stderr 两遍一致性比对未做端到端自动化。影响：FR-10 差异证据已有 U-20 硬证，--log-ai 可复现维度待补。建议：r2 锁定输出格式后补 subprocess 比对。
- **【一般】** test r1-review 意见 4：P-01/P-02/P-03 性能用例本轮未做。影响：性能维度无自动化断言（仅 tick=100ms 设计保证）。已在 README §3.4 透明登记，建议 quality 阶段或 r2 补。
- **【建议】** code r1-review 建议：`_lose_life` 方向硬编码 LEFT，重生后方向被重置。影响：P2 体验细节，不影响 FR-05/FR-09 通过。建议：保留玩家当前方向或 U-48 用例显式定义。

## 4. 门禁判定
- PASS：全部 8 项检查通过。19 FR + 7 NFR 逐条有可验证证据（代码落实 + 测试全绿 + 文档齐备）；四阶段评审全部 PASS，所有遗留均已闭环或透明登记（责任归属明确）；无阻塞发布的严重问题；test r1-review 4 项一般意见为已登记取舍（非新缺陷），不违反任何核心验收标准。可进入安全门禁。
