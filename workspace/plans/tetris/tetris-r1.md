# 开发方案：tetris（r1）

## 0. 元信息
- 需求：tetris/tetris｜依据：analysis/tetris/tetris-r1.md（approved 终版）｜轮次：r1
- 方案要点一句话：Python 标准库 curses 单文件实现 10×20 固定场地经典俄罗斯方块，模型/渲染/输入分层，纯随机+简化旋转+Guideline 计分，wrapper 保证终端干净退出。

## 1. 方案概述
- 目标：交付一个在 Linux TTY 中单命令（`python3 tetris.py`）启动、零第三方依赖、玩法完整（7 方块/下落/移动/旋转/软硬降/消行/计分/等级速度/撞顶结束/next 预览/HUD/暂停）、退出后终端状态完全恢复的经典俄罗斯方块；通过 FR-01~FR-16、FR-18~FR-26 与 NFR-01~NFR-06 全部验收（FR-17 按 Q-01 默认作废，见下）。
- 范围：
  - 做什么（MECE，按需求分解文档 FR 分组全覆盖）：
    - 启动与初始化：单命令启动（FR-01）；非 TTY 明确报错 exit 1（FR-02）；`--tick` 配置 50–2000ms（FR-03）；启动终端尺寸检查（FR-04）；
    - 方块生命周期：7 种标准方块 I/O/T/S/Z/J/L（FR-05）；10×20 固定场地、顶部生成（FR-06）；tick 自动下落（FR-07）；左/右移（FR-08）；简化旋转（FR-09，无 wall kick，Q-02 默认）；软降（FR-10）；硬降（FR-11）；锁定与堆叠（FR-12）；撞顶结束（FR-13）；
    - 消除与计分：消行判定与整行消除、一次多行全消（FR-14）；1/2/3/4 行计分 100/300/500/800（FR-15，Q-01 默认）；等级随消行提升、速度随等级加快（FR-16，Q-04 默认）；
    - 输入控制：WASD+方向键+空格+P+q 全键位（FR-18）；暂停/继续（FR-19）；q/Ctrl+C 安全退出（FR-20）；
    - 界面显示：next 预览（FR-21）；HUD 得分/等级/消行（FR-22）；终端状态恢复（FR-23）；结束画面含最终得分（FR-24）；
    - 交付物：README 五节齐全含选型论证结论（FR-25）；颜色开关 `--no-color`，单色模式以形状辨识（FR-26，Q-11 默认纳入）。
  - 不做什么：软降/硬降加分（FR-17，Q-01 默认「不加分」→该 FR 作废）；SRS 旋转系统与 wall kick（Q-02 默认简化旋转）；7-bag 随机与 lock delay（Q-03 默认纯随机、无 lock delay）；分数持久化/最高分（Q-12）；「再来一局」自动重开（Q-13，结束画面按任意键退出）；键位自定义配置（Q-08 固定键位）；多文件包结构（Q-06 默认单文件）；图形/联网/音效/多人（需求范围外，对照 vitetris netplay 明确排除）。
- 关键假设（来源均为需求分解文档待确认默认值；若需求方拍板不同以回改单处理）：
  - Q-06：单文件 tetris.py 交付，内部按职责分层（§3.2）；若拍板多文件再拆包。
  - Q-05：最低 Python 3.6+，代码避免 3.7+ 语法（dataclass/walrus 等，见 §5.3 兼容性）。
  - Q-09：选型论证（curses vs ANSI）由本方案完成，结论与取舍记录于 README「已知限制」（路径①）。
  - Q-10：固定 10×20 格场地（不含边框），撞顶/边界判定以该场地坐标为准；每格渲染占 2 字符宽。
  - A-04/Q-02：旋转为 90° 顺时针、各方块绕自身形状矩阵旋转；旋转后碰撞即拒绝（无踢墙）。
  - A-05/Q-03：方块生成顺序纯随机（`random.choice` 七种）；无 lock delay（锁定即时生效）。
  - Q-04：初始 tick 500ms；每消 10 行升 1 级；每级 tick 缩短 10%（下限 100ms）。

## 2. 技术选型
| 技术栈/框架/中间件 | 用途 | 选择理由 | 替代方案对比 | 来源 |
|------|------|----------|--------------|------|
| Python 标准库 curses | 终端渲染 + 输入 + 终端状态管理 | ① 标准库自带模块，天然满足 FR-01「零第三方依赖」；② `wrapper()` 自动保存/恢复终端原始状态（noecho/cbreak/光标），是 FR-23/NFR-03 干净退出的现成保障；③ `keypad(True)` 后 `getch()` 直接返回 KEY_UP/DOWN/LEFT/RIGHT，免手工解析方向键多字节转义序列；④ `has_colors/init_pair` 支撑 7 方块 7 色（FR-26 颜色开关）；⑤ 内置 KEY_RESIZE 事件，支撑 FR-04 尺寸检查；⑥ terminfo 抽象终端能力差异，利于 NFR-06 兼容性 | 裸 ANSI 转义序列：字节级可控、依赖更少，但需自行实现 termios 原始模式、终端状态保存/恢复（且要信号安全）、ESC[ 方向键序列解析（含 ESC 键与序列的时序歧义）、SIGWINCH 处理与各终端能力表——复杂度全部落在 FR-23/NFR-04 的雷区；本需求（10×20 小场地、每 tick 全量重绘）ANSI 无收益。**本结论与 snake-linux 已通过评审的方案 §2 一致**（需求原文点名参考），本方案按 tetris 特性（颜色对/next 侧栏渲染）补充论证 | https://docs.python.org/3/howto/curses.html（wrapper/nodelay/timeout/keypad/cbreak/noecho/has_colors/init_pair 语义，实测 200 可达）；https://docs.python.org/3/library/curses.html（KEY_RESIZE/KEY_UP 等/box/savetty/resetty） |
| argparse（标准库） | `--tick`/`--no-color` 参数解析 | 标准库自带，满足 FR-03「至少一种配置方式」；类型校验内建 | 手写 sys.argv 解析：易错；配置文件：单参数场景过重，破坏「单命令启动」体验 | Python 标准库文档（argparse 内置模块） |
| random（标准库） | 方块随机生成 | 标准库自带；`random.choice` 满足纯随机（Q-03 默认） | 7-bag 洗牌：Q-03 默认不纳入（防「连续同方块」的公平性增强，列入 §8 承接点） | Python 标准库文档（random）；tetris.wiki/Tetris_Guideline（Random Generator「7 bag」定义，实测 200 可达） |
| time.monotonic（标准库） | tick 计时与暂停相位补偿 | 单调时钟不受系统时间跳变影响，tick 精度稳定（NFR-01） | time.time()：受系统时钟调整影响 | Python 标准库文档（time.monotonic） |

- 选型结论：渲染/输入层采用 **curses**——需求硬约束（仅标准库、干净退出、纯终端）与 curses 内置能力一一对应，且官方 HOWTO 明确 wrapper 负责「restore the original terminal settings」，是 FR-23 的最短实现路径（与 snake-linux 已通过结论一致，直接继承）；放弃裸 ANSI，因其「自由度」对本需求无实际收益（10×20 小场地、全量重绘即可），却把终端卫生（状态恢复/方向键解析/resize/颜色对管理）全部变成自研风险。游戏逻辑层（模型）刻意**不依赖 curses**，纯 Python 数据结构实现，保证 FR-05~FR-16 可脱离终端独立验证（对齐 NFR-05 职责分离，与 snake-linux 同构）。

## 3. 架构设计
### 3.1 架构图（单文件 tetris.py 内部逻辑分层 + 界面布局）
```
┌────────────────────────────── tetris.py ──────────────────────────────┐
│                                                                       │
│  ┌──────────────┐   ┌────────────────────┐   ┌────────────────────┐  │
│  │  Config      │──▶│  GameState         │◀──│  InputHandler      │  │
│  │ (argparse)   │   │  (纯逻辑模型)       │   │  (键位→动作/退出)   │  │
│  │ tick/no-color│   │  board/活动方块/next│   │  WASD/方向键/空格   │  │
│  └──────────────┘   │  step()/旋转/消行   │   │  /P/q              │  │
│                      │  计分/等级/撞顶     │   └────────────────────┘  │
│  ┌──────────────┐   └───────┬────────────┘                           │
│  │ TETROMINOES  │            │ 每 tick 读状态                          │
│  │ (7 方块定义)  │   ┌───────▼────────────┐   ┌────────────────────┐  │
│  │ + 旋转函数    │──▶│  Renderer          │◀──│  GameLoop(main)    │  │
│  └──────────────┘   │  (curses 封装)      │   │  timeout(25) 轮询   │  │
│                      │  边框/场地/next/HUD │   │  tick 计时推进      │  │
│                      │  /颜色/结束画面     │   └────────────────────┘  │
│                      └────────────────────┘                          │
│  wrapper(main) 包裹全程：异常/正常返回均恢复终端（FR-23）                │
└──────────────────────────────────────────────────────────────────────┘

界面布局（固定画布 + 右侧信息栏，最小 42 列 × 26 行）：
  +--------------------+   +--------+
  |                    |   | NEXT:  |   ← next 预览区（FR-21）
  |   10×20 场地        |   |  [][]  |
  |   (每格 2 字符宽)   |   |  [][]  |
  |                    |   +--------+
  +--------------------+   | SCORE  |   ← HUD 信息栏（FR-22）
                           | LEVEL  |     得分/等级/消行
                           | LINES  |     暂停时叠加 PAUSED（FR-19）
                           +--------+
```

### 3.2 模块划分（单文件内的类/函数分层，每层职责单一，对齐 NFR-05）
| 模块 | 职责 | 依赖 |
|------|------|------|
| `parse_args()` | 解析 `--tick`（毫秒，50–2000，默认 500）、`--no-color`；tick 越界报错退出（FR-03/FR-26） | argparse |
| `check_terminal()` | 启动时 `sys.stdin/stdout.isatty()` 检查，非 TTY 打印明确提示并以非零码退出（FR-02） | sys |
| `TETROMINOES` 常量 + `rotate_cw()` | 7 种方块基础形状矩阵（4×4）定义 + 顺时针 90° 旋转函数（FR-05/FR-09） | 无（纯数据/函数） |
| `GameState` | 10×20 board、活动方块（type/rotation/pos）、next、得分/等级/消行、状态机；`step()/move/rotate/soft_drop/hard_drop/lock/clear_lines/spawn`（FR-06~FR-16，FR-18~FR-20） | random, 常量 |
| `InputHandler` | 键位映射：W/↑ 旋转、A/← 左移、S/↓ 软降、D/→ 右移、空格 硬降、P 暂停、q 退出、KEY_RESIZE（FR-18~FR-20，FR-04） | curses 常量 |
| `Renderer` | curses 封装：边框（box）、锁定格/活动方块（含颜色）、next 预览、HUD、PAUSED 提示、结束画面（FR-21/22/24，FR-19）；全量重绘 | curses |
| `main(stdscr)` | 初始化序列（noecho/cbreak/keypad/curs_set(0)/颜色对）、尺寸检查（FR-04）、tick 驱动主循环、结束收尾 | 以上全部 |
| 顶层 `wrapper(main)` | 终端状态保存与恢复（FR-23/NFR-03） | curses.wrapper |

### 3.3 关键流程时序（主循环）
```
启动:  check_terminal() → wrapper(main) → initscr → noecho/cbreak/keypad(True)/curs_set(0)
      → 颜色初始化(has_colors && !--no-color → init_pair 7 色) → 尺寸检查(COLS≥42 且 LINES≥26,
        不足则提示退出 FR-04) → GameState(随机首方块 + next)
循环:  每轮:  ch = stdscr.getch()          # timeout(25)，无输入返回 -1
              InputHandler 处理 ch         # 旋转/左右/软硬降/P 暂停/q 退出/KEY_RESIZE
              if PAUSED and 按 P: 恢复(补偿 tick 相位); 跳过 step
              now = time.monotonic()
              if now - last >= state.tick_ms/1000:  state.step(); last = now
              renderer.draw(state)          # 全量重绘（含 PAUSED 叠加）
结束:  state 非 RUNNING → draw_game_over(最终得分) → 等任意键 → 返回 → wrapper 恢复终端
```

## 4. 接口与数据设计
### 4.1 对外接口（命令行）
| 接口 | 入参 | 出参 | 错误语义 |
|------|------|------|----------|
| `python3 tetris.py` | 无 | 进入游戏 | 非 TTY：stderr 明确中文提示 + exit 1（FR-02） |
| `python3 tetris.py --tick 300` | tick 毫秒 | 300ms 下落间隔 | tick 不在 [50,2000]：stderr 提示 + exit 2（FR-03 边界） |
| `python3 tetris.py --no-color` | 无 | 单色模式游戏 | 正常进入；单色模式以形状辨识方块（FR-26） |
| `python3 tetris.py --help` | 无 | 参数说明 | 正常 exit 0 |
| 游戏内键位 | W/↑、A/←、S/↓、D/→、空格、P、q | 见 FR-18~FR-20 | 无效键忽略；旋转/移动碰撞被拒绝（FR-08/09） |

### 4.2 数据结构
```
Point = namedtuple('Point', 'x y')            # 场地坐标，y 向下；0 ≤ x < 10, 0 ≤ y < 20

TETROMINOES: Dict[str, List[List[int]]]       # 7 种方块 4×4 基础矩阵（1=占格）
    I: [[0,0,0,0],[1,1,1,1],[0,0,0,0],[0,0,0,0]]   # 其余方块按标准形状定义，O 为 2×2 田字
    旋转: rotate_cw(m) = [list(r) for r in zip(*m[::-1])]，顺时针 90°；rot 0~3 对应旋转次数

GameState:
    cols, rows: int                            # 10 × 20（Q-10）
    board: List[List[int]]                     # rows 行 × cols 列；0=空，非 0=已锁定方块类型
    piece_type: str                            # 活动方块类型（I/O/T/S/Z/J/L）
    rotation: int                              # 0~3
    pos: Point                                 # 活动方块锚点（形状矩阵左上角对应的场地坐标）
    next_type: str                             # next 预览方块（FR-21）
    score, level, lines: int                   # 得分/等级/累计消行（FR-15/16/22）
    status: 'RUNNING' | 'PAUSED' | 'OVER'      # 游戏状态机（FR-13/19/24）
    tick_ms: int                               # 当前等级下落间隔 = max(100, int(500*0.9**(level-1)))（Q-04）
```
- 方块移动语义：`pos` 在场地坐标空间内移动（x 左/右 ±1，y 下落 +1）；旋转即 `rotation = (rotation+1) % 4` 后按当前矩阵做碰撞检测，碰撞则保持原姿态（简化旋转，Q-02）。
- 显示语义：场地每格渲染 2 字符宽（如 `[]`）；颜色开启时锁定格与活动方块按类型着色（7 色 init_pair），关闭时统一普通色靠形状辨识（FR-26）。

### 4.3 状态机（游戏内）
```
RUNNING --撞顶（新方块生成位置被占用）--> OVER（显示最终得分，任意键退出）   FR-13/FR-24
RUNNING --P--> PAUSED（下落/计时冻结，画面叠加提示）--P--> RUNNING（相位补偿后继续） FR-19
任意状态 --q/Ctrl+C--> 退出（wrapper 恢复终端，进程 1 秒内结束）           FR-20/FR-23
```

## 5. 关键实现要点
### 5.1 核心算法
碰撞检测与消行（关键片段，≤20 行；模型层纯逻辑可独立单测）：
```python
def collides(gs, shape, pos):
    for y, row in enumerate(shape):
        for x, v in enumerate(row):
            if not v: continue
            wx, wy = pos.x + x, pos.y + y
            if wx < 0 or wx >= gs.cols or wy >= gs.rows: return True
            if wy >= 0 and gs.board[wy][wx]: return True     # 与锁定格重叠
    return False

def clear_lines(gs):
    full = [y for y in range(gs.rows) if all(gs.board[y])]
    for y in full:
        del gs.board[y]; gs.board.insert(0, [0] * gs.cols)  # 整行消除、上方下移（FR-14）
    return len(full)      # 0/1/2/3/4 → 计分 0/100/300/500/800（FR-15，Q-01）
```
等级与速度联动（Q-04）：
```python
gs.level = gs.lines // 10 + 1
gs.tick_ms = max(100, int(500 * (0.9 ** (gs.level - 1))))    # 下限 100ms，FR-16
```
硬降与软降（FR-10/FR-11，Q-01 默认不加分）：
```python
# 硬降：垂直下探到碰撞前最后一格，直接锁定 → 消行 → 生成 next（耗时 ≪100ms，纯计算）
def hard_drop(gs):
    while not collides(gs, shape(gs), Point(gs.pos.x, gs.pos.y + 1)): gs.pos.y += 1
    lock_and_spawn(gs)          # 锁定 → clear_lines → 计分 → 撞顶判定 → 新方块
# 软降：按下 S/↓ 事件立即尝试下移 1 格（键盘重复率 ≫ tick 率 → 按住期间明显快于自动下落；
#       松开即无事件、恢复自动下落，满足 FR-10 验收口径，且无需 lock delay）
```
暂停相位补偿（FR-19）：
```python
# 暂停时记录 paused_at；恢复时 last_tick += (now - paused_at)，使恢复后 tick 相位连续、
# 暂停期间不吞时间、不跳变（对齐 FR-19「从暂停瞬间状态继续，无跳变」）
```

### 5.2 边界与异常处理
| 场景 | 处理 |
|------|------|
| 非 TTY（管道/重定向/cron） | 启动即检查 isatty，stderr 输出「请在终端中运行本游戏」类提示，exit 1，无 traceback（FR-02/NFR-04） |
| 终端过小（< 42×26 含边框+侧栏） | 启动时提示所需最小尺寸并退出（FR-04）；游戏中收到 KEY_RESIZE 后重查，不足则暂停显示提示，恢复后继续 |
| 旋转被阻挡（贴墙/贴堆叠） | 简化旋转：旋转后 collides → 拒绝并保持原姿态（FR-09，Q-02）；不做 wall kick |
| 快速连按/键位风暴 | 单线程事件驱动：每轮 getch 只消费 1 个键；动作立即生效但 step 仍按 tick 推进，输入不会造成跳变（FR-18「1 个 tick 内生效」）；软降为事件式下移不设累计状态，无并发竞态 |
| 撞顶 | spawn 时新方块与锁定格/边界重叠 → status=OVER（FR-13）；立即停止下落并进入结束画面流程 |
| Ctrl+C / SIGINT | wrapper 的 finally 恢复终端后，捕获 KeyboardInterrupt 输出友好退出信息；进程无残留子进程（FR-20） |
| SIGTERM | 注册 handler 抛 KeyboardInterrupt，走同一恢复路径（增强项，防 systemd/kill 场景终端残留，对齐 snake-linux） |
| 绘制闪烁/残影 | 每 tick 全量重绘 + 一次 refresh；10×20 场地刷新耗时 ≪ 25ms 轮询周期，满足 NFR-01 |
| 并发/线程 | 单线程实现；curses 非线程安全，不引入线程（Q 表无并发需求） |
| 超时/重试 | 不适用：本地单进程、无网络 I/O；输入超时由 timeout(25) 轮询机制天然覆盖 |

### 5.3 安全与合规
- 输入校验：tick 必须为 [50,2000] 内整数，越界给出可读错误；所有参数错误走 stderr 提示 + 非零退出，不抛裸 traceback（NFR-04）。
- 敏感数据：无网络、无文件读写、无凭据，无数据安全面。
- 权限：仅需普通用户终端权限；不写系统路径，不要求 root。
- Python 3.6 兼容性（Q-05）：避免 dataclass（3.7+）、海象运算符（3.8+）、`str.removeprefix`（3.9+）、f-string 调试格式（3.8+）；类型注解使用 typing 兼容写法或省略；curses 在 3.6 长期可用（来源：Python 官方 HOWTO）。

## 6. 风险与对策
| 风险 | 影响 | 概率 | 对策/缓解 |
|------|------|------|----------|
| 终端兼容性长尾（SSH/老旧终端对字符、颜色支持差异，NFR-06） | 界面乱码/错位 | 中 | 边框用纯 ASCII 字符（`+ - |`），方块用 ASCII `[]` 双字符格，不用 Unicode 制表符；颜色仅用 curses 8 基础色（has_colors 检测，不支持则自动降级单色）；覆盖矩阵（GNOME Terminal/Konsole/xterm/SSH）在测试阶段实测（Q-07 默认） |
| 旋转/消行逻辑缺陷（简化旋转边界、多行同消、上方下移） | 规则错误，验收 FAIL | 中 | 模型层纯逻辑（不依赖 curses），消行/碰撞/计分全部可脱离终端用 pytest 单测覆盖（对齐 snake-linux 测试模式）；测试方案阶段细化用例 |
| 纯随机连续出同型方块（Q-03 默认） | 可玩性略降 | 中 | 接受（需求方拍板默认）；7-bag 作为增强项记录于 README 已知限制与 §8 承接点，纳入成本低（改 spawn 一处） |
| 软降手感依赖键盘重复率（OS 级） | 软降速度在不同键盘配置下不一致 | 低 | FR-10 验收口径为「明显快于自动下落 + 松开恢复」，事件式下移天然满足；若实测手感不佳，可在 InputHandler 内做「按住计时软降」（记录 S/↓ 最后按下时间，tick 内额外下移），为局部增强不改变架构 |
| 游戏中终端 resize | 渲染越界/崩溃 | 低 | KEY_RESIZE → resizeterm + 尺寸重查，不足则暂停提示（FR-04）；curses 自动处理刷新 |
| Ctrl+C 时机与 curses 状态竞争 | 终端残留脏状态（FR-23 失效） | 低 | 全程 wrapper 包裹（finally 恢复），SIGTERM 同路径；测试阶段脚本反复 Ctrl+C 验证 `stty -a` 前后一致（对齐 snake-linux 已验证路径） |
| 需求方待确认项拍板变更（Q-01~Q-14） | 返工 | 中 | 方案已按默认值落地并标注承接点（§8）；7-bag/软降手感/分数持久化等均为局部修改，变更成本 ≤ 1 小时 |
| 单文件 500+ 行与 NFR-05「源文件职责单一」的张力 | 评审争议 | 中 | 单文件内以类/函数严格分层（§3.2），README 说明分层结构；若评审认为不满足，按 Q-06 拆包成本低（§8） |

## 7. 工作量与任务拆解
### 7.1 任务拆解
| 任务 | 依赖 | 预估 |
|------|------|------|
| T1 Config（--tick/--no-color）+ 非 TTY/尺寸检查 | 无 | 0.5h |
| T2 TETROMINOES 定义 + rotate_cw + 碰撞检测（模型层） | 无 | 1h |
| T3 GameState 核心：spawn/移动/旋转/软硬降/锁定/消行/计分/等级/撞顶/暂停相位 | T2 | 2h |
| T4 InputHandler + tick 主循环 + 全部退出路径（q/Ctrl+C/SIGTERM） | T3 | 1h |
| T5 Renderer：边框/场地/颜色/next/HUD/PAUSED/结束画面 | T1/T3 | 1h |
| T6 README（运行方式/依赖/键位/配置/已知限制含选型论证）+ FR 验收场景自测走查 | T4/T5 | 1h |
| 合计 | | 约 6.5 小时（1 人日内） |

### 7.2 里程碑
| 阶段 | 交付物 | 验收点 |
|------|--------|--------|
| M1 可玩闭环 | 模型层 + 主循环 + 基础渲染 | 7 方块生成/移动/旋转/软硬降正确；消行/计分/等级生效；撞顶结束 |
| M2 完整界面与终端卫生 | next/HUD/颜色/暂停/结束画面/全部退出路径 | FR-19/21/22/23/24/26 通过；Ctrl+C 后 `stty -a` 与退出前一致 |
| M3 交付完备 | tetris.py + README.md | 按 README 在干净环境跑通（FR-01/FR-25）；--tick/--no-color 生效（FR-03/FR-26） |

## 8. 待确认问题（承接需求分解文档 Q 表，均按建议默认值落地，无新增需求级疑问）
| 问题 | 影响决策 | 建议默认值（已按此设计） |
|------|----------|--------------------------|
| Q-01 计分数值/软硬降加分 | score 累计规则 | 1/2/3/4 行 = 100/300/500/800；软硬降不加分（FR-17 作废，不验收） |
| Q-02 旋转系统 | rotate 是否带踢墙 | 简化旋转：碰撞即拒绝、无 wall kick（SRS 为增强项） |
| Q-03 随机策略/lock delay | spawn 顺序与锁定时机 | 纯随机（random.choice）；无 lock delay（锁定即时生效） |
| Q-04 初始 tick/升级曲线 | 速度模型 | 初始 500ms；每 10 行升 1 级；每级 tick ×0.9，下限 100ms |
| Q-05 最低 Python 版本 | 语法特性范围 | 3.6+（§5.3 兼容性约束） |
| Q-06 单文件 vs 多文件 | 交付物结构 | 单文件 tetris.py；若拍板多文件，按 §3.2 分层拆为 `tetris/` 包（model.py/render.py/main.py），README 注明 `python3 -m tetris` 入口，改动成本 < 1h |
| Q-07 终端覆盖矩阵 | 测试范围 | GNOME Terminal / Konsole / xterm / SSH 实测 |
| Q-08 键位自定义 | 输入层范围 | 固定键位（FR-18），不做配置化 |
| Q-09 选型论证归属 | 交付物范围 | 本方案已完成论证（§2），结论写入 README「已知限制」 |
| Q-10 场地规格 | 画布与边界判定 | 固定 10×20（不含边框），每格 2 字符宽；最小终端 42×26 |
| Q-11 颜色开关 | Renderer 颜色路径 | 需要（FR-26）：`--no-color` 关闭，单色模式以形状辨识 |
| Q-12 最高分持久化 | 是否引入文件 I/O | 不做（第一版） |
| Q-13 结束后交互 | 结束流程 | 显示最终得分后按任意键退出，不自动重开 |
| Q-14 退出键 | 退出路径 | q 退出 + Ctrl+C 兜底（对齐 snake-linux 惯例） |

## 9. 修改回应表
（首轮，无上轮评审意见。）
