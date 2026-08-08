# 开发方案：snake-linux（r1）

## 0. 元信息
- 需求：snake-linux/snake-linux｜依据：analysis/snake-linux/snake-linux-r2.md（approved 终版）｜轮次：r1
- 方案要点一句话：Python 标准库 curses 单文件实现 40×20 固定画布经典贪吃蛇，模型/渲染/输入分层，tick 可配置，wrapper 保证终端干净退出。

## 1. 方案概述
- 目标：交付一个在 Linux TTY 中单命令（`python3 snake.py`）启动、零第三方依赖、可玩性完整（方向控制/吃食增长/碰撞结束/HUD/结束画面）、退出后终端状态完全恢复的经典贪吃蛇；通过 FR-01~FR-17 与 NFR-01~NFR-06 全部验收。
- 范围：
  - 做什么：固定 40×20 格画布（含可见边框，采纳 Q-10 默认）；WASD 与方向键控制（FR-06）；反向移动禁止（FR-07）；食物生成/吃食增长得分（FR-08/FR-09）；撞墙/撞自身结束（FR-10）；结束画面（FR-11）；q/Ctrl+C 安全退出（FR-13）；终端状态恢复（FR-14）；HUD 得分栏（FR-17）；tick 可配置 50–1000ms（FR-03）；非 TTY 明确报错（FR-02）；终端尺寸检查（FR-04）；README 四节齐全（FR-15）。
  - 不做什么：不做暂停/继续（Q-04 默认不纳入，代码留扩展点）；不做分数持久化/最高分（Q-02）；不做速度随长度加快（Q-03）；不做「再来一局」（Q-08 默认结束画面按任意键退出）；不做多食物/道具（Q-01 默认单一食物每食 +1）；不做穿墙/环绕地图（A-04）；不做图形/联网/音效（需求范围外）。
- 关键假设（来源均为需求分解文档的待确认默认值，若需求方拍板不同则以回改单处理）：
  - A-01/Q-06：单文件 snake.py 交付，内部按职责分层；Q-06 若拍板多文件再拆包（见 §8）。
  - A-03：初始蛇长 3、向右，初始蛇头位于画布中央偏左区域。
  - Q-05：最低 Python 3.6+，代码避免 3.7+ 语法（不用 dataclass、walrus、f-string 调试细节之外的特性，见 §5 兼容性）。
  - Q-09：选型论证（curses vs ANSI）由本方案完成，结论与取舍记录于 README「已知限制」（路径①）。
  - Q-10：固定 40×20 格画布，撞墙 = 撞画布边框（含边框字符所在格）。

## 2. 技术选型
| 技术栈/框架/中间件 | 用途 | 选择理由 | 替代方案对比 | 来源 |
|------|------|----------|--------------|------|
| Python 标准库 curses | 终端渲染 + 输入 + 终端状态管理 | ① 标准库自带模块，天然满足 FR-01「零第三方依赖」；② wrapper() 自动保存/恢复终端原始状态（noecho/cbreak/光标），是 FR-14/NFR-03 干净退出的现成保障；③ keypad(True) 后 getch() 直接返回 KEY_UP/DOWN/LEFT/RIGHT，免手工解析方向键多字节转义序列；④ 内置 KEY_RESIZE 事件，支撑 FR-04 尺寸检查；⑤ terminfo 抽象终端能力差异，利于 NFR-06 兼容性 | 裸 ANSI 转义序列：字节级可控、依赖更少，但需自行实现 termios 原始模式、终端状态保存/恢复（且要信号安全）、ESC[ 方向键序列解析（含 ESC 键与序列的时序歧义）、SIGWINCH 处理与各终端能力表——复杂度全部落在 FR-14/NFR-04 的雷区，对本需求（小画布全量重绘）无收益 | https://docs.python.org/3/howto/curses.html（wrapper/nodelay/halfdelay/keypad/cbreak/noecho 语义）；https://docs.python.org/3/library/curses.html（KEY_RESIZE/KEY_UP 等/box/savetty/resetty/resizeterm） |
| argparse（标准库） | tick/尺寸等参数解析 | 标准库自带，满足 FR-03「至少一种配置方式」 | 手写 sys.argv 解析：代码冗余易错；配置文件：对单参数场景过重，且「单命令启动」体验更差 | Python 标准库文档（argparse 为内置模块） |
| collections.deque（标准库） | 蛇身坐标序列 | 头尾 O(1) 增删，天然匹配「头进尾出」的蛇移动语义 | list + pop(0)：尾部删除 O(n)；自写链表：过度设计 | Python 标准库文档（collections.deque） |
| random（标准库） | 食物随机生成 | 标准库自带；配合空闲格列表方案（见 §5）无死循环风险 | 随机重试采样：蛇占满时可能空转 | Python 标准库文档（random） |
| time.monotonic（标准库） | tick 计时 | 单调时钟不受系统时间跳变影响，tick 精度稳定（NFR-01） | time.time()：受系统时钟调整影响 | Python 标准库文档（time.monotonic） |

- 选型结论：渲染/输入层采用 **curses**——需求硬约束（仅标准库、干净退出、纯终端）与 curses 内置能力一一对应，且官方 HOWTO 明确 wrapper 负责「restore the original terminal settings」，是 FR-14 的最短实现路径；放弃裸 ANSI，因其「自由度」对本需求无实际收益（40×20 小画布、全量重绘即可），却把终端卫生（状态恢复/方向键解析/resize）全部变成自研风险。游戏逻辑层（模型）刻意**不依赖 curses**，纯 Python 数据结构实现，保证 FR-05~FR-10 可脱离终端独立验证（对齐 NFR-05 职责分离）。

## 3. 架构设计
### 3.1 架构图（单文件 snake.py 内部逻辑分层）
```
┌────────────────────────────── snake.py ──────────────────────────────┐
│                                                                      │
│  ┌──────────────┐   ┌──────────────────┐   ┌─────────────────────┐  │
│  │  Config      │──▶│  GameState       │◀──│  InputHandler       │  │
│  │ (argparse)   │   │  (纯逻辑模型)     │   │  (键位→方向/退出)    │  │
│  │ tick/尺寸/…  │   │  snake/food/方向  │   │  WASD/方向键/q      │  │
│  └──────────────┘   │  step()/碰撞判定  │   └─────────────────────┘  │
│                     └───────┬──────────┘                            │
│                             │ 每 tick 读状态                          │
│                     ┌───────▼──────────┐   ┌─────────────────────┐  │
│                     │  Renderer        │   │  GameLoop(main)     │  │
│                     │  (curses 封装)    │◀──│  halfdelay 轮询      │  │
│                     │  边框/蛇/食物/HUD │   │  tick 计时推进       │  │
│                     └──────────────────┘   └─────────────────────┘  │
│                                                                      │
│  wrapper(main) 包裹全程：异常/正常返回均恢复终端（FR-14）               │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 模块划分（单文件内的类/函数分层，每层职责单一，对齐 NFR-05）
| 模块 | 职责 | 依赖 |
|------|------|------|
| `parse_args()` | 解析 `--tick`（毫秒，50–1000，默认 200）、`--width/--height`（默认 40×20）；tick 越界报错退出 | argparse |
| `check_terminal()` | 启动时 `sys.stdin/stdout.isatty()` 检查，非 TTY 打印明确提示并以非零码退出（FR-02） | sys |
| `GameState` | 蛇身 deque、方向与待定方向、食物坐标、得分、状态（RUNNING/OVER/WIN）；`step()` 执行移动/吃食/碰撞/胜利判定（FR-05~FR-10） | collections.deque, random |
| `Renderer` | 画边框（box）、蛇、食物、HUD 行（FR-17）、结束画面（FR-11）；全量重绘（无残影） | curses |
| `InputHandler` | 键位映射：WASD/方向键→方向（含反向禁止 FR-07）、q→退出、KEY_RESIZE→尺寸重查（FR-04） | curses 常量 |
| `main(stdscr)` | 初始化序列（noecho/cbreak/keypad/隐藏光标）、尺寸检查、tick 驱动主循环、结束收尾 | 以上全部 |
| 顶层 `wrapper(main)` | 终端状态保存与恢复（FR-14/NFR-03） | curses.wrapper |

### 3.3 关键流程时序（主循环）
```
启动:  check_terminal() → wrapper(main) → initscr → noecho/cbreak/keypad(True)
      → 尺寸检查(COLS≥W+2 且 LINES≥H+4, 不足则提示退出 FR-04) → 构造 GameState
循环:  每轮:  ch = stdscr.getch()            # halfdelay/tick 粒度阻塞轮询
              InputHandler 处理 ch           # 方向(反向禁止)/q/KEY_RESIZE
              若 now-last_tick ≥ tick:  state.step() → Renderer.draw(state)
结束:  state 非 RUNNING → draw_game_over → 等待任意键 → 返回 → wrapper 恢复终端
```

## 4. 接口与数据设计
### 4.1 对外接口（命令行）
| 接口 | 入参 | 出参 | 错误语义 |
|------|------|------|----------|
| `python3 snake.py` | 无 | 进入游戏 | 非 TTY：stderr 明确中文提示 + exit 1（FR-02） |
| `python3 snake.py --tick 100` | tick 毫秒 | 100ms 帧间隔游戏 | tick 不在 [50,1000]：stderr 提示 + exit 2（FR-03 边界） |
| `python3 snake.py --width 40 --height 20` | 画布宽/高 | 指定尺寸游戏 | 尺寸导致终端不足：FR-04 提示 + exit 3 |
| `python3 snake.py --help` | 无 | 参数说明 | 正常 exit 0 |
| 游戏内键位 | q/Q、WASD、方向键 | 见 FR-06/FR-13 | 反向输入被忽略（FR-07）；无效键忽略 |

### 4.2 数据结构
```
Point = namedtuple('Point', 'x y')                 # 画布内坐标，y 向下，0 ≤ x < W, 0 ≤ y < H
GameState:
    width, height: int                             # 画布尺寸（不含边框）
    snake: deque[Point]                            # 蛇身，头在右端；初始长度 3、向右
    direction: (dx, dy)                            # 当前移动方向
    pending: (dx, dy) | None                       # 本 tick 内未消费的转向（单槽，防快速连按）
    food: Point                                    # 食物坐标，恒不与蛇身重叠
    score: int                                     # 每食 +1（Q-01）
    status: 'RUNNING' | 'OVER' | 'WIN'             # WIN = 蛇占满画布（理论边界）
    tick_ms: int                                   # 帧间隔，来自配置
```
- 蛇移动语义：不吃食时「头进尾出」（append 头 + popleft 尾），长度不变；吃食时仅 append，长度 +1。

### 4.3 状态机（游戏内）
```
RUNNING --撞墙/撞自身--> OVER（显示最终得分，任意键退出）
RUNNING --蛇占满画布--> WIN（显示胜利与得分，任意键退出）
任意状态 --q/Ctrl+C--> 退出（wrapper 恢复终端，进程 1 秒内结束 FR-13）
```

## 5. 关键实现要点
### 5.1 核心算法
tick 驱动主循环（halfdelay 粒度 100ms，tick 任意值由时间戳判定，兼顾 50ms 最小 tick 与低 CPU 占用 NFR-02）：
```
stdscr.timeout(50)                     # getch 最多阻塞 50ms，非忙等
last = time.monotonic()
while state.status == 'RUNNING':
    ch = stdscr.getch()                # 无输入返回 -1
    handle_input(state, ch)            # 方向/退出/KEY_RESIZE
    now = time.monotonic()
    if now - last >= state.tick_ms / 1000:
        state.step(); last = now
    renderer.draw(state)
```
蛇移动与碰撞（关键片段 ≤20 行，含「尾部让行」严格判定）：
```
def step(self):
    self._apply_pending()                          # 消费单槽转向
    head = self.snake[-1]
    nh = Point(head.x + self.direction[0], head.y + self.direction[1])
    if not (0 <= nh.x < self.width and 0 <= nh.y < self.height):
        self.status = 'OVER'; return               # 撞墙 FR-10
    body = set(self.snake)
    if nh in body and not (self._will_eat(nh) is False and nh == self.snake[0]):
        self.status = 'OVER'; return               # 撞自身；不吃食时旧尾将移走，允许让行
    self.snake.append(nh)
    if nh == self.food:
        self.score += 1; self._spawn_food()        # 吃食 FR-08/FR-09
    else:
        self.snake.popleft()                       # 头进尾出
```
食物生成（空闲格列表，无死循环）：
```
def _spawn_food(self):
    occupied = set(self.snake)
    free = [Point(x, y) for x in range(self.width) for y in range(self.height)
            if Point(x, y) not in occupied]
    if not free: self.status = 'WIN'; return       # 占满判胜（理论边界）
    self.food = random.choice(free)
```

### 5.2 边界与异常处理
| 场景 | 处理 |
|------|------|
| 非 TTY（管道/重定向/cron） | 启动即检查 isatty，stderr 输出「请在终端中运行本游戏」类提示，exit 1，无 traceback（FR-02/NFR-04） |
| 终端过小（< 42×24 含边框+HUD） | 启动时提示所需最小尺寸并退出（FR-04）；游戏中收到 KEY_RESIZE 后重查，不足则暂停显示提示，恢复后继续 |
| 快速连按两键（如 ↑ 后立刻 ←） | pending 单槽：新转向覆盖未消费转向，且转向时同时校验与当前方向、待定方向均不相反，杜绝「反向自杀」（FR-07） |
| Ctrl+C / SIGINT | wrapper 的 finally 恢复终端后，捕获 KeyboardInterrupt 输出友好退出信息；进程无残留子进程（FR-13） |
| SIGTERM | 注册 handler 抛 KeyboardInterrupt，走同一恢复路径（增强项，防 systemd/kill 场景终端残留） |
| 蛇占满画布 | 空闲格列表为空 → WIN 状态，正常结束流程（防 random 死循环） |
| 绘制闪烁/残影 | 全量重绘 + 每 tick 一次 refresh；40×20 画布刷新耗时 ≪ 50ms，满足 NFR-01 |
| 并发 | 单线程实现；curses 非线程安全，不引入线程（Q 表无并发需求） |
| 超时/重试 | 不适用：本地单进程、无网络 I/O；输入超时由 tick 机制天然覆盖 |

### 5.3 安全与合规
- 输入校验：tick 必须为 [50,1000] 内整数，越界给出可读错误；尺寸参数为正整数且 ≥ 最小可玩值（如 10×10），越界报错——所有参数错误走 stderr 提示 + 非零退出，不抛裸 traceback（NFR-04）。
- 敏感数据：无网络、无文件读写、无凭据，无数据安全面。
- 权限：仅需普通用户终端权限；不写系统路径，不要求 root。
- Python 3.6 兼容性（Q-05）：避免 dataclass（3.7+）、海象运算符（3.8+）、`str.removeprefix`（3.9+）；类型注解使用 typing 兼容写法或省略。

## 6. 风险与对策
| 风险 | 影响 | 概率 | 对策/缓解 |
|------|------|------|----------|
| 终端兼容性长尾（SSH/老旧终端对边框字符、颜色支持差异，NFR-06） | 界面乱码/错位 | 中 | 边框用纯 ASCII 字符（`+ - |`），不用 Unicode 制表符；不依赖 256 色，用默认前景色；覆盖矩阵（GNOME Terminal/Konsole/xterm/SSH）在测试阶段实测（Q-07 默认） |
| 快速按键反向自杀（输入缓冲窗口） | 非预期死亡，可玩性受损 | 中 | pending 单槽 + 与当前/待定方向双重反向校验（§5.2） |
| 游戏中终端 resize | 渲染越界/崩溃 | 低 | KEY_RESIZE → resizeterm + 尺寸重查，不足则暂停提示（FR-04） |
| 蛇占满导致食物生成死循环 | 进程挂死 | 低 | 空闲格列表 + WIN 判胜（§5.1） |
| Ctrl+C 时机与 curses 状态竞争 | 终端残留脏状态（FR-14 失效） | 低 | 全程 wrapper 包裹（finally 恢复），SIGTERM 同路径；测试阶段用脚本反复 Ctrl+C 验证 `stty -a` 前后一致 |
| 需求方待确认项拍板变更（Q-04 暂停、Q-06 多文件、Q-10 尺寸） | 返工 | 中 | 方案已按默认值落地并标注承接点；暂停留 pending 槽扩展点，尺寸/文件结构均为局部修改，变更成本 ≤ 1 小时 |
| 单文件 400+ 行与 NFR-05「源文件职责单一」的张力 | 评审争议 | 中 | 单文件内以类/函数严格分层（§3.2），README 说明分层结构；若评审认为不满足，按 Q-06 拆包成本低（见 §8） |

## 7. 工作量与任务拆解
### 7.1 任务拆解
| 任务 | 依赖 | 预估 |
|------|------|------|
| T1 参数解析 + 非 TTY/尺寸检查（Config 层） | 无 | 0.5h |
| T2 GameState 模型：移动/吃食/碰撞/胜利/食物生成 | 无 | 1.5h |
| T3 Renderer：边框/蛇/食物/HUD/结束画面（curses） | T1 | 1h |
| T4 InputHandler + tick 主循环 + 退出路径 | T2/T3 | 1h |
| T5 README（运行方式/键位表/配置/已知限制，含选型论证结论） | T4 | 0.5h |
| T6 自测走查：FR-01~FR-17 验收场景 + 终端恢复验证 | T4 | 0.5h |
| 合计 | | 约 5 小时（1 人日内） |

### 7.2 里程碑
| 阶段 | 交付物 | 验收点 |
|------|--------|--------|
| M1 可玩闭环 | GameState + 主循环 + 基础渲染 | 蛇可移动、吃食增长、撞墙/撞身结束 |
| M2 完整界面与终端卫生 | HUD/结束画面/全部退出路径 | FR-11/13/14/17 通过；Ctrl+C 后终端状态与退出前一致 |
| M3 交付完备 | snake.py + README.md | 按 README 在干净环境跑通（FR-01/FR-15）；tick 50–1000 生效（FR-03） |

## 8. 待确认问题（承接需求分解文档 Q 表，均为默认值落地，无新增需求级疑问）
| 问题 | 影响决策 | 建议默认值（已按此设计） |
|------|----------|--------------------------|
| Q-01 得分/食物类型 | 模型 score 与食物生成 | 每食 +1、单一食物 |
| Q-02 最高分持久化 | 是否引入文件 I/O | 不做 |
| Q-03 速度随长度加快 | tick 是否动态变化 | 不加快，固定 tick |
| Q-04 暂停/继续 | 主循环与 HUD 是否含暂停态 | 不纳入；pending 单槽已留扩展点，纳入时新编号补回 |
| Q-05 最低 Python 版本 | 语法特性范围 | 3.6+（§5.3 兼容性约束） |
| Q-06 单文件 vs 多文件 | 交付物结构 | 单文件 snake.py；若拍板多文件，按 §3.2 分层拆为 `snake/` 包（model.py/render.py/main.py），README 注明启动入口 `python3 -m snake`，改动成本 < 1h |
| Q-07 终端覆盖矩阵 | 测试范围 | GNOME Terminal / Konsole / xterm / SSH 实测 |
| Q-08 结束画面交互 | 结束流程 | 显示得分后按任意键退出 |
| Q-09 选型论证归属 | 交付物范围 | 本方案已完成论证（§2），结论写入 README「已知限制」 |
| Q-10 游戏区域语义/尺寸 | 边框与撞墙判定 | 固定 40×20 格画布，撞墙 = 撞画布边框 |

## 9. 修改回应表
（首轮，无上轮评审意见）
