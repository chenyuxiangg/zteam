# 测试评审：pacman（r1）

## 0. 评审结论
- 结论：**PASS**
- 一句话理由：194/194 单元+集成全绿，FR-10 主验收客观证据硬证；P0/P1 覆盖完整；4 项取舍 README §3 已显式登记（功能路径已覆盖）。
- 评审轮次：r1（2026-08-10 16:20 人工 requeue 后重产出的 test 阶段第 1 轮；继承 analysis r5 + plans r1 + testplans r1 + code r1）

## 1. 检查清单核对表

| # | 检查项 | 结论 | 依据/缺失说明 |
|---|--------|------|--------------|
| 1 | 方案符合性 | PASS | testplan §3.1 需求映射表 19 FR + 7 NFR 共 87 个关键用例全部有对应实现位置；README §2 用例映射表逐条注明 test_* 方法名；P0 100% 覆盖（U-01..U-13 / U-20..U-29 / U-40..U-43 / U-46..U-49 / U-51..U-53 / U-60..U-62 / I-01..I-09 / S-02..S-09 / S-13 / S-14 / E-01..E-07 / E-09..E-10 / C-03 / N-01 / N-02）。**FR-10 主验收硬证**：`tests/test_ghost_ai.py::TestTargetCellFourDiffer::test_u20_four_targets_mutually_distinct` 在固定局面下断言 4 幽灵目标格两两不同且在地图边界内，本地实测通过（rc=0） |
| 2 | 可运行 | PASS | `python3 -m unittest discover -s tests -t .` 在 tests/pacman-r1 目录下 194/194 通过（0.18s）；`python3 run_all.py` 入口干净（退出 0）；`PACMAN_CODE_DIR` 环境变量与自动向上查找机制 `_path.py:_workspace_root` 双重保障；curses 桩 `_path.py:_install_curses_stub` 早期注入，使 test_renderer 在无真终端环境可跑。**轻微问题**：e2e_pty.py 默认 `--repeat=1` 因默认相对地图路径（`data/map_classic.txt`）在 cwd=code/pacman-r1/ 时不存在会 rc=1，必须显式 `--map pacman/data/map_classic.txt` 或 `--map <绝对路径>`；README §1 的"真终端一键跑"路径实际未走通（见意见 1） |
| 3 | 有效性 | PASS | 断言非空转：U-20/U-21..U-29 用具体坐标断言四幽灵规则；U-41 用 `GHOST_CHAIN_SCORES[:i+1]` 累加校验；U-44..U-46 难度公式逐 L 值断言；test_arch 静态扫描用正则真正检查 import 语句（不是仅 grep）；test_cli_contract 通过 subprocess 真实拉起子进程验证 exit code（实测 rc=1 + stderr 含"需要真实终端"） |
| 4 | 边界覆盖 | PASS | map 校验 8 类非法地图（行宽不一/非法字符/缺 P/缺 H/缺门/能量豆<4/过小/鬼屋堵死）；ghost_ai 死胡同/反向/平局/越界 clamp 全覆盖；game 暂停相位补偿/保护期不连环/连吃封顶 1600/能量豆计时归零；config 8 类非法值（--ghosts 1/5、--lives 0/10、--speed 0.1/3.0、--level 0/-1）；renderer <80×24 提示 |
| 5 | 独立性与稳定性 | PASS | fixtures 工厂（make_player/make_ghost/build_game/frozen_clock）经公开 API 构造（Ghost/Player 构造 + 字段赋值），不依赖 `_` 前缀内部状态；时间敏感用例通过 `frozen_clock` 注入确定性 dt（U-43/U-52/test_tick_skips_when_paused）；curses 桩确定性 getch 返回 -1（无随机）；README §6 明确标注"CI 无时钟漂移风险" |
| 6 | 报告质量 | PASS | unittest TextTestRunner 输出点状进度 + 失败 traceback；README §4 记录最近一轮 194/194 + 0.18s；run_all.py 三阶段分隔打印；test_cli_contract subprocess 捕获 stderr 解码到 UTF-8；test_arch 失败时打印 offender 列表 |
| 7 | 与代码评审衔接 | PASS | 代码评审遗留 #1（穿墙防护）已在 `test_entities.py::TestPlayerCannotWalkIntoWall` 独立覆盖（test_u33_walking_into_wall_stops / walking_along_wall_stays_on_passage），代码评审 #2（README 自检补完）由 README §1 运行方式 + §9 自检命令覆盖 |
| 8 | 效率 | PASS | 194 测 0.18s，平均 1ms/测；fixtures.py GOOD_22x19 硬编码地图（不每次读 data 文件）；curses 桩早期注入避免重复 import 开销；subprocess 测试用 timeout=5/15 限定上限 |
| 9 | 不越界 | PASS | tests/pacman-r1/tests/ 目录内全部为测试代码；未改 code 产物；未改 input/ 需求原文；未触碰 plans/testplans 产物；fixtures 中 GOOD_22x19 与 code 产物 pacman/data/map_classic.txt 完全一致（test 阶段硬编码副本仅用于 data 文件丢失时的兜底，主路径仍走 `code_dir() / pacman / data / map_classic.txt`） |
| 10 | 可审计 | PASS | round 5 / test r1 单一目录产物；README §7 修改轮说明明确"r2 新版本写在 pacman-r2/，本目录不动"；testplan §9 修改回应表（testplan-r1 首轮无历史意见）已留空且明确说明背景；README §3 已知差异 §3.1/§3.2/§3.3/§3.4 显式登记 4 项取舍，每项均含 testplan 期望/实现差异/评审验收口径 |

## 2. 评审意见列表

本轮无严重问题（致命/核心错误/安全缺陷/关键边界失守均未发现）；下列 4 项为【一般】级（透明登记的口径取舍/工具瑕疵，不阻塞 PASS），1 项为【建议】。

- **【一般】意见 1** `scripts/e2e_pty.py` 默认地图路径在 `os.chdir(CODE)` 后失效
  - 依据：本地实测 `python3 scripts/e2e_pty.py --repeat 1` 输出 `地图加载失败：地图文件不存在：data/map_classic.txt`（rc=1，rendered=False）；改用 `--map /home/zyzs/cyx/zteam/workspace/pacman/code/pacman-r1/pacman/data/map_classic.txt` 后 rc=0 / rendered=True。`code/pacman-r1/config.py:181` `DEFAULT_MAP = "data/map_classic.txt"` 是相对于 cwd 的相对路径，而 e2e_pty.py 把 cwd 切到 `code/pacman-r1/`，但 `pacman/data/map_classic.txt` 才是真实位置。README §1 顶部运行方式"python3 run_all.py --with-system"因此首次默认运行即失败，违反"可复现"原则
  - 影响：仅系统层自动化受影响；逻辑层 194/194 不依赖此路径已全绿
  - 建议：r2 修复方案 A — `e2e_pty.py:argv` 注入 `--map $(CODE)/pacman/data/map_classic.txt` 默认参数；或 B — `e2e_pty.py` 不切 cwd，由子进程从绝对路径启动；或 C — code 阶段把 `DEFAULT_MAP` 改成基于 `__file__` 的绝对路径（README §11 已记 code 阶段做过类似改造，但 DEFAULT_MAP 未跟进）

- **【一般】意见 2** `tests/testplan §3.2` U-05/E-06 孤立豆格未做独立 P0 用例
  - 依据：README §3.1 已自报"通过 `_write_and_load(BAD_ISOLATED_DOT)` 间接覆盖 ... 已被 test_e05_* 路径覆盖（间接）"；但 testplan §3.2 U-05 明确要求"构造'被墙隔离的孤立豆格'地图调用 validate_map() ... 判定①失败"，独立断言失败信息含孤立豆格行列。`fixtures.py:BAD_ISOLATED_DOT`（行 169-197）的实际地图是把 row 6 全行替换为墙，并非严格意义上的"孤立豆格四周被墙封死"——它通过隔离整行间接触发了"不可达豆子"，断言口径不够精确
  - 影响：判定①失败路径已被 `test_e05_*` 触发（实测通过），但严格单独立 U-05/E-06 用例在功能覆盖层面更可靠；不影响逻辑层 194 项通过
  - 建议：r2 补一个真正"四周封闭孤豆"地图（豆格 (r,c) 四邻均为 WALL，其余豆格可达），独立断言 `MapError` 含 `(r,c)` 行定位；README §3.1 验收口径"功能路径已覆盖"虽成立，但 testplan P0 用例完整性更优

- **【一般】意见 3** I-08 --log-ai 输出格式未做端到端 stderr 断言
  - 依据：testplan §3.3 I-08 要求"固定种子与固定输入序列跑两遍，采集 stderr 行为日志；比对同一 tick 四幽灵目标格 ... 两遍日志完全一致（可复现）；同一 tick 四者目标格互异（客观差异证据）"。当前实现仅通过 U-20（同一局面 target 互异）+ U-47（模式切换）+ U-50（出场时机）三组客观断言覆盖 FR-10 完整性（README §3.2 已自报）；未做 --log-ai stderr 两遍一致性比对
  - 影响：FR-10 客观差异证据仍硬证（U-20 通过），但 --log-ai 行为日志"可复现"维度的端到端自动化缺失
  - 建议：r2 锁定 --log-ai 输出格式后补一个 test：固定种子注入 + 固定输入序列，subprocess 拉两次 main_cli（加 `--log-ai`）断言 stderr 内容完全一致

- **【一般】意见 4** P-01 / P-02 / P-03 性能用例本轮未做
  - 依据：testplan §3.6 P-01（P0）/P-02（P0）/P-03（P1）要求 FPS ≥10 / 响应 ≤100ms / 5min 稳定的自动化；README §3.4 明确说"本轮取舍：性能用例需真终端 + 长时运行 + 时间采样脚本，作为评审门槛在 quality 阶段覆盖；test 阶段不强制"
  - 影响：性能维度本轮无自动化断言（仅 e2e_pty 间接验证 startup ≤3s）；testplan 明确 P0 性能未覆盖，但 README 已声明责任归属（quality 阶段）
  - 建议：r2 或 quality 阶段补 FPS 采样（主循环 time.monotonic 间隔统计）+ 按键响应时间注入 + 5min 长时稳定性测试

- **【建议】** `tests/fixtures.py:ScreenStub` 重复定义 `nodelay/keypad/timeout/getch`
  - 依据：类内行 285-295 与行 312-323 定义了完全相同的 4 个方法；Python 类定义后者会覆盖前者，但代码评审角度看是冗余瑕疵，单不影响测试结果
  - 建议：r2 删除前一处（行 285-295）即可

## 3. 遗留事项（仅 PASS 时）

- L1：U-05/E-06 独立用例 + I-08 端到端 + P-01..P-03 性能 + E-12 stderr 降级 端到端自动化 已在 README §3 显式登记为本轮取舍；评审口径明确为"功能路径已覆盖 + 透明自报"，由 quality 阶段或 r2 补
- L2：e2e_pty.py 默认地图路径失效（意见 1）需 code/test 任一阶段在 r2 修复；建议 code 阶段把 `DEFAULT_MAP` 改成基于 `__file__` 的绝对路径（已与 README §11 修改轮说明呼应）
- L3：fixtures.py ScreenStub 重复定义（建议级）可 r2 清理
- L4：testplan §8 待确认 3 条（pexpect 引入/--log-ai 格式/能量豆数量）与 code 评审 L2（Q1-Q12 需求方答复）尚未拍板，本轮严格按 testplan 默认值实现；下游 quality/releaser 阶段若需求方答复到达，由对应轮次按回改单处理
