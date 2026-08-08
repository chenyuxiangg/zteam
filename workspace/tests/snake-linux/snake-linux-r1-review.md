# 测试评审：snake-linux/snake-linux（r1）

## 0. 评审结论
- 结论：**FAIL**
- 一句话理由：3 个一般问题——P0 集成用例假失败（MiniTerm 解析缺陷）+ 性能用例无实现 + P0 用例偶发失败。
- 评审轮次：r1

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据/缺失说明 |
|---|--------|------------------|--------------|
| 1 | 方案符合性 | PASS | 单元层 TC-U-01~12 全部实现（test_game_state/test_config/test_input 共 15 个用例对应）；集成层 TC-I-01~11 全部实现（e2e_snake.py 11 个用例函数）。系统层 TC-S-01~06 无独立可执行清单（仅 README "人工冒烟" 一句），但测试方案将系统层定性为「半自动：脚本 + 人工清单」，当前缺失清单文件；性能层 TC-P-01~03 无脚本实现（见意见 3）。 |
| 2 | 可运行 | FAIL | 单元层：31/31 PASS（pytest，0.07s）。集成层：8/11 PASS，2 FAIL（TC-I-05/TC-I-10，均为 P0），1 SKIP（TC-I-11）。详见意见 1/2。README 运行方式可复现（`pytest -q` + `python3 e2e_snake.py`）。 |
| 3 | 有效性 | PASS | 单元测试有真实断言：坐标/方向/长度/得分/状态/退出码——无空转（如 test_tc_u08_eat_grow_score 断言 len+score+蛇头坐标三重校验）。集成测试用 termios.tcgetattr 断言 ECHO/ICANON 恢复（非仅 exit code），退出码/屏幕内容/stderr 内容均有校验。 |
| 4 | 边界覆盖 | PASS | 非法 tick（49/1001/abc/-100/0）全部参数化覆盖（TC-U-11）；非法尺寸（0/-1/9/9×9/非整数）全部参数化覆盖（TC-U-12）；蛇占满判胜（TC-U-09/TC-U-10）；尾部让行（TC-U-05）；pending 单槽双重反向校验（TC-U-04）；非 TTY（TC-I-02）；终端过小启动/运行中 resize（TC-I-03/TC-I-11）；SIGINT/SIGTERM（TC-I-07/TC-I-08）。性能边界（NFR-01/NFR-02）无自动化覆盖——见意见 3。 |
| 5 | 独立性与稳定性 | FAIL | 单元层：确定性、独立（make_state 显式注入蛇身/食物/方向），无随机假阳性。集成层：TC-I-10 持续失败（MiniTerm 终端模拟器对 curses 清屏序列处理不完整，与真实终端行为偏差 → 假失败，见意见 1）；TC-I-05 偶发失败（BFS 贪吃机器人寻路策略限制，见意见 2）。测试与被测代码无过度耦合（通过 snake.py 公共 API 与 PTY 接口测试）。 |
| 6 | 报告质量 | PASS | pytest 输出完整明细（31 passed in 0.07s）；e2e_snake.py 输出结构化结果表（PASS/FAIL/SKIP、优先级、detail 信息、汇总 PASS=8/FAIL=2/SKIP=1）。无 HTML/JUnit 报告，但对当前规模可接受。 |
| 7 | 与代码评审衔接 | PASS | 代码评审 r1 结论 PASS（2 条建议，无阻塞/重要事项）。代码评审「遗留事项」声明「正式测试应由 test 阶段按 testplans 独立执行」——当前测试确实独立于代码评审执行。 |
| 8 | 效率 | PASS | 单元 31 例 0.07s（极快）；集成 11 例约 30s（含 PTY 启动/按键/超时等待），TC-I-05 最长 60s 但属正常范围；无无谓等待/重复。 |
| 9 | 不越界 | PASS | 测试仅导入被测代码（conftest.py sys.path.insert CODE_DIR），不修改 snake.py/README；不写业务功能；e2e 通过 pexpect 驱动独立进程。 |
| 10 | 可审计 | PASS | 新目录 tests/snake-linux/snake-linux-r1/；首轮无上轮评审意见需回应；pytest cache 与 __pycache__ 在目录内（建议 .gitignore 排除）。 |

## 2. 评审意见列表

- **[一般] 意见 1：TC-I-10（P0，FR-16）持续假失败——MiniTerm 终端模拟器缺陷**
  - 现象：集成测试 TC-I-10「边框与坐标范围」持续失败，输出「顶边框异常: ''（有效帧 25/30）」。
  - 根因定位：自研 MiniTerm 终端模拟器（e2e_snake.py:42-133）对 curses 的 `ESC[2J` 等清屏转义序列处理不完整——约第 25 帧时收到清屏序列后将屏幕网格错误清空，导致后续帧读取到空边框。被测代码 snake.py 的渲染逻辑无缺陷：单元层边界坐标断言（test_game_state.py:228-236 `test_u_extra_invariants_inside_canvas`）全部通过，代码评审 r1 检查项 3（功能正确性）逐 FR 勾对通过。
  - 修复建议：①将 MiniTerm 中对 `_csi(params, 'J')` 的清屏行为改为仅清可视区域而不重置 grid（或加帧同步锁）；②或改用 pexpect 内置的 `child.expect('Score:')` / `child.expect('GAME OVER')` 字符串匹配替代屏幕网格重建做基础验证，网格重建仅用于坐标断言时开启；③降低 30 帧采样循环内对 MiniTerm 完整性的依赖，改为「检测到 GAME OVER 后采样停止」加「进行中帧数 ≥ 25 即 PASS」的宽松判定。
  - 依据：测试方案 TC-I-10 验收标准「30 帧内蛇身与食物坐标恒在边框内」；被测代码 snake.py Renderer.draw():196-207 每帧全量重绘边框。

- **[一般] 意见 2：TC-I-05（P0，FR-05~FR-11）偶发失败——BFS 寻路机器人策略限制**
  - 现象：集成测试 TC-I-05「吃食→撞墙→结束画面全流程」偶发失败，输出「60s 内未吃到 3 个食物（贪吃寻路失败或提前结束）」。重跑可 PASS。
  - 根因定位：autoplay_to_score()（e2e_snake.py:216-240）的 BFS 寻路在蛇身增长后（>4 节）可能被自身身体阻挡，60s 超时不足以让蛇自然绕开自己撞墙结束。这属于机器人策略限制，非被测代码缺陷（单元层 TC-U-08 吃食增长+TC-U-06 撞墙判定均通过）。
  - 修复建议：①将「吃 3 个食物」降为「吃 1 个食物即视为验证通过」（吃食增长逻辑在单元层 TC-U-08 已验证）；或②延长 max_seconds 至 120s 并增加 BFS 无法到达时随机方向选择的 fallback（模拟「乱走等撞墙」），确保最终能进入结束画面；或③将「吃食→撞墙」拆为两个独立用例（吃食验证 + 撞墙触发结束画面验证）。
  - 依据：测试方案 TC-I-05 验收标准「吃食后蛇变长得分增加；撞墙后进入结束状态」。

- **[一般] 意见 3：性能用例 TC-P-01~03（NFR-01/NFR-02）无实现**
  - 现象：测试方案 §5 要求 `bash tests/perf_snake.sh`（pidstat 采样 + 延迟计时）验证输入延迟 ≤ 200ms、CPU ≤ 5%、RSS ≤ 50MB，但 tests 目录中无 `perf_snake.sh` 或等价脚本。NFR-01/NFR-02 的自动化验证完全缺失。
  - 修复建议：创建 `tests/snake-linux/snake-linux-r1/perf_snake.sh`，实现：①用 `pidstat` 记录 30s 运行期 CPU/RSS（均值），断言 ≤5% / ≤50MB（TC-P-02）；②PTY 中按键并记录屏幕转向生效时间差，采样 20 次取 P95（TC-P-01）。或将性能用例降级为「仅记录基线，不阻塞门禁」（测试方案已声明 P0 判定不依赖性能用例——则至少需要基线记录脚本）。
  - 依据：测试方案 TC-P-01/P-02/P-03 用例定义；NFR-01/NFR-02 可验证指标。

- **[建议] 意见 4：系统验收用例 TC-S-01~06 无可执行清单**
  - 测试方案将系统层定性为「半自动：脚本 + 人工清单」，但 tests 目录中无终端矩阵清单文件（如 `checklist-system.md`）或验收脚本。README 仅声明「端到端在真实 TTY 下运行 python3 snake.py 人工冒烟」，无法逐项打勾留痕。
  - 修复建议：创建 `tests/snake-linux/snake-linux-r1/checklist-system.md`，逐项列出 TC-S-01（README 走查）/TC-S-02（README 四节齐全）/TC-S-03（GNOME Terminal/Konsole/xterm/SSH 四种终端）/TC-S-04（非 TTY/过小/非法参数 stderr 中文提示）/TC-S-05（代码职责走查）/TC-S-06（Python 3.6/3.8/3.11/3.12 冒烟）。不阻塞——测试方案 §2 已声明「系统/验收层：半自动」，但清单是合格的半自动实现所必需。

- **[建议] 意见 5：集成测试建议改用 pexpect 内置 expect 匹配降低脆弱性**
  - 当前 e2e_snake.py 依赖自研 MiniTerm 对 curses 输出做完整屏幕网格解析，带来维护成本与假失败风险（见意见 1）。建议核心验证改用 pexpect 内置的 `child.expect('Score:')` / `child.expect(r'GAME OVER|YOU WIN')` 等字符串匹配——这些是 curses 输出中的纯文本部分，不依赖 CSI 序列解析。仅在需要坐标断言（如 TC-I-10 边框内坐标验证）时才启用网格重建，且加「帧数 ≥ 25 即 PASS」的宽松判定。

## 3. 遗留事项（仅 PASS 时）
（本轮 FAIL，无遗留事项）
