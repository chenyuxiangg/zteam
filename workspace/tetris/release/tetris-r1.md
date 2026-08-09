# 发布说明：tetris（v1.0.0）

## 0. 发布信息
- 版本：v1.0.0｜日期：2026-08-09 04:35 UTC｜状态：released
- 需求：tetris/tetris｜全链路完成：是
- 发布轮次：r1（第 1 轮发布）｜上游终版：analysis r2 / plan r2 / testplan r2 / code r2 / tests r1

## 1. 变更摘要
- 一句话：交付一个 **Linux 终端俄罗斯方块游戏**——Python 标准库从零实现、单命令启动、零第三方依赖，7 种标准方块 + 完整玩法闭环（下落/移动/旋转/软硬降/消行计分/等级速度/撞顶结束/next 预览/HUD/暂停），退出后终端状态完全恢复。
- 全链路：需求 → 分析（r2 approved，26 FR + 6 NFR，Q 表 14 项按建议默认值落地）→ 方案 → 测试方案 → 代码 → 测试 → 质量/安全门禁双 PASS → 本次发布。

## 2. 交付内容
- 代码：`workspace/code/tetris/tetris-r2/`
  - `tetris.py`（687 行）：单文件实现，内部按逻辑分层（Config/GameState 模型/InputHandler/Renderer/main），模型层不依赖 curses 可独立验证；含 7 方块 4×4 矩阵坐标注释、42×26 尺寸推导注释、SIGTERM/Ctrl+C/q 三路干净退出
  - `README.md`（184 行）：五节齐全（运行方式/依赖/键位表/配置项/已知限制），含 curses vs ANSI 选型论证结论、42×26 推导、单文件分层声明、绝对值验收口径自检
- 测试：`workspace/tests/tetris/tetris-r1/`（pytest 单元 + pexpect/pyte PTY 集成 + 系统验收 + 性能），测试结果全绿：
  - 单元 72/72 passed（0.09s）——模型层纯逻辑全覆盖（TC-U-01~20）
  - 集成 16/16 PASS（54.6s）——PTY 端到端（TC-I-01~16），含 termios 退出前后一致性、SIGINT/SIGTERM、resize
  - 系统 5/5 PASS（TC-S-01/02/04/05/06 脚本部分）
  - 性能 2/2 PASS——TC-P-01 输入延迟 avg=13.2ms P95=14.0ms（阈值 ≤50ms P95）；TC-P-02 avg_cpu=1.81%、peak_rss=17.3MB（阈值 CPU≤5%/RSS≤50MB）
- 文档索引：
  - 需求原文：`workspace/input/tetris/tetris.md`
  - 需求分解（approved 终版）：`workspace/analysis/tetris/tetris-r2.md`
  - 方案终版：`workspace/plans/tetris/tetris-r2.md`
  - 测试方案终版：`workspace/testplans/tetris/tetris-r2.md`
  - 测试结果留痕：`workspace/tests/tetris/tetris-r1/results/r2-regression.log`

## 3. 质量与安全结论
- 质量门禁：**PASS**（`workspace/quality/tetris/tetris-r1.md`）——8 项检查全部通过，自动化测试全绿（72 单元 + 16 集成 + 5 系统 + 2 性能），分析 r2 全部验收标准（FR-01~FR-26 活跃项 / NFR-01~NFR-06）逐条有证据，各阶段评审（plan/testplan/code/tests）全部 PASS。仅 1 个一般问题（人工清单未填写，< 3 条阈值，不阻塞）。
- 安全门禁：**PASS**（`workspace/security/tetris/tetris-r1.md`）——8 项安全红线全部 PASS：零第三方依赖、无网络/文件 I/O、无凭据；输入面（--tick 范围校验、键盘白名单映射、终端尺寸检查、绘制越界捕获、碰撞边界检查）均有校验；无命令注入/路径穿越/权限提升/资源耗尽面；供应链风险为零。

## 4. 使用方式
- 安装/运行：**无需安装**。在 Linux 终端（TTY）中直接运行：
  ```bash
  python3 tetris.py                  # 默认 500ms 下落间隔，颜色开启
  python3 tetris.py --tick 300       # 自定义下落间隔（50–2000ms）
  python3 tetris.py --no-color       # 单色模式（以形状辨识方块）
  ```
- 键位：W/↑ 旋转、A/← 左移、D/→ 右移、S/↓ 软降、空格 硬降、P 暂停/继续、q 退出；Ctrl+C 安全中断（同一干净恢复路径）。
- 玩法：填满整行消除得分（1/2/3/4 行 = 100/300/500/800），每消 10 行升 1 级，下落间隔每级 ×0.9（下限 100ms），堆叠撞顶游戏结束。
- 依赖：Python 3.6+（仅标准库：argparse/curses/os/random/signal/sys/time），Linux 终端（GNOME Terminal/Konsole/xterm/SSH 均可），无需 root、无需编译。
- 环境边界：非 TTY → 可读错误 + exit 1；无 TERM → 可读错误 + exit 1；终端 < 42×26 → 尺寸提示 + exit 3；非法 tick → 可读错误 + exit 2。均无裸 traceback。

## 5. 已知限制与风险
- **人工验收清单未填写**（质量门禁唯一遗留，一般问题）：`tests/tetris/tetris-r1/system_checklist.md` 中 TC-S-01 人工「完整玩一局」（P0）、TC-S-03 终端矩阵 4 环境实机（P2）、TC-S-05 代码可读性走查（P2）、TC-S-06 Python 多版本实机（P2）、TC-P-03 渲染流畅度目测（P2）未勾选。自动化部分已覆盖（TC-S-01 脚本部分 PASS + 72 单元 + 16 集成全绿），不阻塞发布，但建议需求方在真实终端体验确认。
- **软降速度依赖 OS 键盘重复率**（FR-10）：事件式下移设计默认满足「≥ 自动下落 ×4」，但极端低重复率键盘下集成层仅做粗粒度检查；如需兜底可加「按住计时软降」局部增强（README 已登记）。
- **纯随机生成**（Q-03 默认）：可能出现连续同方块，无 7-bag 公平性保障（增强项，见 §7）。
- **单文件物理形态**：tetris.py 687 行单文件交付（Q-06 默认），与 NFR-05「职责单一」的关系按 README 声明口径理解（逻辑分层为职责边界、物理单文件为交付形态）。
- **简化旋转**（Q-02 默认）：旋转碰撞即拒绝、无 wall kick（SRS 为增强项）。
- **性能指标为建议项**（NFR-01/02，analysis r2 R1-04 标注）：实测已远优于阈值，但非强制验收，需求方确认不关注可取消。
- **无分数持久化/最高分、无「再来一局」自动重开**（Q-12/Q-13 默认），结束画面按任意键退出。

## 6. 回滚方案
- 本需求为纯本地单进程游戏，无服务、无数据持久化、无外部状态——**运行侧无需回滚**。
- 交付物版本回滚：zteam 工作区已纳入 git（远程 origin=git@github.com:chenyuxiangg/zteam.git），代码/文档全部有 git 历史。回滚方式：
  1. 查看历史：`git log -- workspace/code/tetris/ workspace/release/tetris/`
  2. 回退：`git restore --source=<上一版本 commit> workspace/code/tetris/tetris-r2/ workspace/release/tetris/`（或 checkout 指定 commit）
  3. 若需重跑流水线：`python3 scripts/statectl.py requeue tetris/tetris` 重新走阶段链（产物文件永不覆盖，历史轮次保留可查）
- 备份要点：`workspace/status.json` 为状态机唯一事实来源，回滚前建议备份；发布归档已生成于 `workspace/artifacts/tetris/tetris.md`（含全链路产物与评审历史）。

## 7. 后续建议
- **Q 表待需求方拍板项**（当前均按建议默认值落地，拍板变更成本 ≤1 小时）：Q-02 升级 SRS 旋转系统（wall kick）、Q-03 7-bag 随机策略、Q-01 软硬降加分、Q-12 分数持久化/最高分、Q-13 「再来一局」。
- 体验增强（非需求范围）：软降按住计时兜底增强、游戏结束重开快捷键、多文件包结构拆分（Q-06 备选，README 已注明 `python3 -m tetris` 入口方案）。
- 补验事项：填写 system_checklist.md 人工清单（真实终端完整玩一局 + 终端矩阵 + 多 Python 版本实机），形成完整验收留痕。
- 复刻参考：本需求与 snake-linux 同构（终端游戏 + 标准库 + 干净退出），后续同类终端游戏需求可直接复用「分析 r2 绝对值验收口径 + curses 选型论证 + PTY 集成测试模式」这一已验证链路。
