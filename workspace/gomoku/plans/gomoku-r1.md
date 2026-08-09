# 开发方案：gomoku（r1）

## 0. 元信息
- 需求：gomoku/gomoku｜依据：workspace/gomoku/analysis/gomoku-r2.md（approved 终版）｜轮次：r1（本轮首轮）
- 方案要点一句话：纯终端人机五子棋成品——rich 渲染、模式评估+Alpha-Beta 分级 AI（弱/中/强）、禁手可配置、坐标输入、干净退出。

## 1. 方案概述

### 目标
交付一个可在 Linux 终端开箱即玩、通过 FR-01~FR-12 与 NFR-01~NFR-07 验收的五子棋人机对战成品：
- 默认 15×15 棋盘（可选 13×13），人类执黑先行，可配置难度（弱/中/强）与禁手开关；
- 中/强档 AI 能识别并阻止玩家双三/冲四/活三威胁，强档主动构造进攻（FR-06 验收）；
- 胜负判定横/竖/斜五连无遗漏，禁手规则（双三/双四/长连）与成五优先级符合连珠规则（FR-07/09）；
- Ctrl+C 任意时刻安全退出并恢复终端原始状态（FR-11）；
- README 覆盖运行方式/依赖安装/键位输入/配置选项/AI 算法说明（FR-12）。

### 范围
**做什么**：
- 单机人机对战（人类 vs AI）、终端渲染（rich 彩色棋盘 + 坐标标注）、坐标输入落子（`A8` / `8,8` 双格式）；
- AI 三档棋力：弱（合法且不送死）/ 中（评估函数 + 威胁封堵）/ 强（Alpha-Beta 深度搜索 + 进攻构造）；
- 棋盘 15×15（默认）/ 13×13 两档；禁手开关（黑双三/双四/长连，成五优先判黑胜）；
- 上一步标记与提示、胜负/平局判定、对局重开、安全退出（Ctrl+C / 退出命令）；
- 单元测试（胜负/禁手/AI 封堵）、README、pyproject 打包（pip 可安装）。

**不做什么**（与分析文档 §2.2 一致）：
- 不联机、不做 GUI/Web、不做棋谱/存档/开局库、不做账号排行榜；
- 不实现连珠完整开局规则（五手交换/三手交换等），只做核心禁手判定；
- 不追求竞赛级棋力（威胁空间搜索工程化，见 §2 选型与 §8 Q2）；
- 首版不做悔棋/双人同屏/胜负统计（分析文档 Q6/Q7/Q8，均列为后续增强）。

### 关键假设
- H1~H6 沿用需求分解文档假设（Python ≥3.10；ANSI 彩色优先、无彩色降级字符；个人娱乐/学习用途；人类默认执黑；AI 定位娱乐级偏强；依赖可选、零依赖可玩）；
- H7（新增，技术层）：终端输入采用标准库 `input()` 而非 prompt_toolkit——坐标输入格式简单（`A8`/`8,8`），rich 已覆盖渲染，避免第二个硬依赖，符合 H6；
- H8（新增）：AI 强档搜索深度 4 层 + 候选点剪枝 + 时间预算 2s 即可满足 NFR-01（15×15 中盘 ≤2s）——依据：同规模 Python 实现（Mgla96/GomokuAI、pygomoku）在候选剪枝下深度 4 均能亚秒级落子，深度 2/4 已能覆盖"阻止双三/冲四"所需的战术视野（来源见 §2 选型表；时间预算与降级策略见 §5.3/§5.4）。

## 2. 技术选型

### 选型表
| 技术栈 | 用途 | 选择理由 | 替代方案对比 | 来源 |
|--------|------|----------|--------------|------|
| Python 3.10+ | 实现语言 | 需求指定 Python；rich 生态要求现代 Python；Linux 发行版默认版本满足 | — | 需求原文；NFR-03 |
| rich | 终端渲染（棋盘/状态栏/胜负横幅） | 终端富文本事实标准（57k★），纯输出渲染 API 简单可靠；无彩色终端自动降级，字符模式可区分黑白子；不接管终端 raw 模式（比 curses 安全） | curses（标准库）：需手动管理 raw/cbreak/回显恢复，跨终端差异大，FR-11 退出恢复风险高；prompt_toolkit：交互输入强但渲染层与输入耦合、依赖更重 | https://github.com/Textualize/rich（PyPI 检索 2026-08-09） |
| 标准库 input() | 坐标输入 | 格式校验简单（长度/字符集/范围/占用），无需行编辑/历史等高级能力；零依赖 | prompt_toolkit：编辑体验好，但为简单输入引入第二个硬依赖，违背 H6 | 推断（H7） |
| 模式评估函数 + Alpha-Beta 剪枝 | AI 核心算法（中/强档） | Python 五子棋 AI 的主流成熟路线：5 个代表性开源项目全部采用 Minimax+Alpha-Beta+评估函数，实现量适中、棋力可调（深度/评分表） | 威胁空间搜索（threat-space search，Allis 1993）：Gomocup 顶级引擎方法，可证明必胜，但工程复杂度数量级上升，超出娱乐级定位；MCTS：需大量模拟（≥千次/步）才具棋力，终端场景响应慢，且对威胁识别（FR-06 验收）不直观 | https://github.com/husus/gomokuAI-py；https://github.com/Mgla96/GomokuAI；https://pypi.org/project/pygomoku/；https://deepwiki.com/hibouwu/Gomoku-IA/4.3-alpha-beta-pruning-ai-(level-3)；https://www.baeldung.com/cs/gomoku-threat-space-search（均 2026-08-09 检索验证） |
| numpy | 棋盘表示/加速（可选） | 不采用：15×15 二维 list 足够，模式扫描为 O(方向×长度) 常数级，numpy 无收益且制造硬依赖 | — | 推断（H6） |
| pytest | 单元测试 | Python 测试事实标准；覆盖 FR-06/07/09 验收用例 | unittest（标准库）可作退化 | 推断 |
| pyproject.toml + setuptools | 打包/安装 | 标准打包方式，支持 `pip install .` 与 `pip install -e .`，满足 README 依赖安装要求 | — | 推断 |

### 选型结论
采用 **rich（唯一第三方运行时依赖）+ 标准库输入 + 模式评估函数与 Alpha-Beta 剪枝** 的组合：渲染交给成熟库保证 FR-03/11，输入与棋盘逻辑零依赖保证 H6 退化可玩，AI 走 Python 社区验证过的主流路线保证 FR-06 可达成；放弃 curses（退出恢复风险）、prompt_toolkit（依赖冗余）、numpy（无收益）、威胁空间搜索与 MCTS（超出娱乐级定位）。依赖面收敛为 `rich` + `pytest`（开发依赖），与需求"允许第三方库"及 H6"零依赖可玩"双向兼容。

## 3. 架构设计

### 架构图
```
                     ┌─────────────────────────────────────┐
                     │           main.py（主控）             │
                     │  回合循环 / 难度与规则装配 / 重开 / 退出 │
                     └───────┬───────────┬───────────┬─────┘
                             │           │           │
                 ┌───────────▼───┐ ┌─────▼─────┐ ┌───▼──────────┐
                 │   board.py    │ │   ai.py   │ │    ui.py     │
                 │ 棋盘·规则层     │ │ AI 决策层   │ │ 终端交互层    │
                 │ 落子/胜负/禁手  │ │ 评估/搜索   │ │ rich 渲染/输入│
                 │ 坐标转换/满盘  │ │ 三档难度    │ │ 退出恢复      │
                 └───────────┬───┘ └─────┬─────┘ └───┬──────────┘
                             │           │           │
                      ┌──────▼───────────▼───────────▼──────┐
                      │            config.py（配置）           │
                      │ 棋盘规格/难度/禁手/执色（CLI 参数+默认值） │
                      └─────────────────────────────────────┘
```

### 模块划分
| 模块 | 职责 | 依赖 |
|------|------|------|
| main.py | 主控：解析 CLI 配置（argparse）、装配 Board/AI/UI、驱动回合循环、处理重开/退出信号 | config, board, ai, ui |
| board.py | 纯逻辑无 I/O：落子合法性、胜负判定（4 方向五连）、禁手判定（长连/双三/双四）、满盘判定、坐标解析（`A8`/`8,8`）、棋盘快照与 undo（供 AI 搜索回溯） | 无（仅标准库） |
| ai.py | AI 决策：模式评估函数（全盘扫描）、候选点生成（邻域剪枝）、Alpha-Beta 搜索（迭代加深+时间预算）、三档难度策略、禁手规避 | board |
| ui.py | rich 渲染（棋盘/状态栏/胜负横幅）、上一步落子高亮标记（last_move 用 rich Style 反色/加粗或背景色区分，满足 FR-08）、坐标输入循环（错误提示重输）、Ctrl+C 与退出命令处理、终端恢复（rich console 生命周期） | rich, board |
| config.py | 配置模型与默认值：size（15/13）、difficulty（weak/medium/strong）、forbidden（on/off）、human_color（black，预留 white） | 无 |
| tests/ | 单元测试：test_board（胜负/禁手/坐标）、test_ai（FR-06 封堵用例/禁手规避/时限） | pytest, board, ai |

### 关键流程时序（主循环）
```
启动: main 解析参数 → config 装配 → ui 初始化(rich console) → board 新建(size)
回合循环:
  1. ui.render(board, state)          # 渲染棋盘+状态栏(当前玩家/上一步/上一步高亮)
  2. 若轮到人类: ui.get_move(board)   # 坐标输入循环,非法输入提示重输
     若轮到 AI:   ai.choose_move(board, color, difficulty)   # 带时间预算
  3. board.place(x, y, color)         # 落子(禁手开启且黑方: 先判禁手, 禁手则判黑负)
  4. 胜负判定: board.check_win(x,y) → 五连: 终局横幅+胜方, 询问重开/退出
     满盘无五连 → 平局
  5. 切换回合 color = 对方
中断: 任意时刻 Ctrl+C → ui 捕获 KeyboardInterrupt → 恢复终端 → 礼貌退出(exit 0)
重开: 终局选择重开 → board.reset() 保持当前配置 → 回到步骤 1
```

## 4. 接口与数据设计

### 对外接口（模块 API）
| 接口 | 入参 | 出参 | 错误语义 |
|------|------|------|----------|
| `Board(size=15)` | 棋盘边长 13/15 | — | size 非法 → ValueError |
| `Board.place(x, y, color)` | 坐标 0-index (x,y)，color 'B'/'W' | bool 成功 | 越界/已占用 → False（不抛异常，由 UI 提示） |
| `Board.undo(x, y)` | 坐标 0-index (x,y) | bool 成功 | 该点无子/越界 → False（仅 AI 搜索回溯调用，UI 不调用；place 的反操作，恢复该点为 '.' 并维护快照） |
| `Board.check_win(x, y)` | 最后落子坐标 | color 或 None | 无 |
| `Board.check_forbidden(x, y, color)` | 拟落子坐标 + 黑方标记 | (is_forbidden, reason) | 仅 color='B' 有意义；白方恒 False |
| `Board.is_full()` | — | bool | 无 |
| `Board.parse_move(text, size)` | 用户输入字符串（`A8`/`8,8`/`a8`） | (x, y) | 格式/范围非法 → 抛 `MoveError`（含原因：格式/越界/已占用） |
| `ai.choose_move(board, color, difficulty)` | 棋盘、执色、难度 | (x, y) | 无合法点 → 返回 None（调用方判平局） |
| `ui.render(board, state)` | 棋盘 + 状态（当前玩家/上一步/消息） | None | 无 |
| `ui.get_move(board)` | 棋盘（用于占用校验） | (x, y) | 内部循环捕获 MoveError 与 KeyboardInterrupt |
| CLI：`python -m gomoku [--size 15|13] [--difficulty weak|medium|strong] [--forbidden on|off] [--human black|white]` | argparse | — | 非法参数 → argparse 报错退出 |

### 数据结构/数据模型
```python
# board.py 核心状态
Board = list[list[str]]        # '.' 空 / 'B' 黑 / 'W' 白; 索引 board[y][x], 0-index
State = {
  'turn': str,                  # 'B'/'W' 当前回合
  'last_move': tuple|None,      # 上一步 (x,y)
  'message': str,               # 状态栏提示（上一步/禁手警告等）
  'over': bool,                 # 终局标志
  'winner': str|None,           # 'B'/'W'/None(平局)
}
```
```python
# ai.py 评分表（模式 → 分值, 经验值可调）
SCORE = { 'FIVE':1_000_000, 'LIVE_FOUR':100_000, 'RUSH_FOUR':10_000,
          'LIVE_THREE':5_000, 'SLEEP_THREE':500, 'LIVE_TWO':200,
          'SLEEP_TWO':20 }
# 模式识别: 以落子点为中心, 沿 4 方向(横/竖/双斜)取 9 窗口(前后各4)做连子计数,
# 按 连续同色数 + 两端是否开放 归类为 FIVE/LIVE_FOUR/RUSH_FOUR/LIVE_THREE/...
```

### 状态机（对局级）
```
        ┌─────────────── 重开(保持配置) ───────────────┐
        ▼                                             │
   PLAYING ──人类/AI落子──► 落子校验 ──五连──► BLACK_WIN / WHITE_WIN
      ▲                      │                       │
      │                      ├──禁手(黑)──► WHITE_WIN │
      │                      └──满盘无五连──► DRAW    │
      └──────────────────────────┬───────────────────┘
                                 └─► 终局: 询问 重开/退出 → QUIT
   任意时刻: Ctrl+C / 输入 quit → QUIT(恢复终端后 exit 0)
```
迁移守卫：五连判定优先于禁手判定（成五+禁手同时发生判黑胜，FR-07）；落子合法性校验（越界/占用）不进入终局分支。

## 5. 关键实现要点

### 5.1 胜负判定（FR-09）
```python
def check_win(board, x, y):
    color = board[y][x]
    for dx, dy in ((1,0),(0,1),(1,1),(1,-1)):        # 横/竖/两斜
        cnt = 1
        for s in (1, -1):                            # 正反两个方向
            nx, ny = x+dx*s, y+dy*s
            while 0<=nx<len(board) and 0<=ny<len(board) and board[ny][nx]==color:
                cnt += 1; nx += dx*s; ny += dy*s
        if cnt >= 5: return color                    # ≥5 即胜（freestyle 允许长连胜）
    return None
```
边界：坐标在棋盘内由 place() 保证；角部/边线方向扫描自动终止于边界，无越界访问（NFR-06）。

### 5.2 禁手判定（FR-07，仅黑方）
三个独立判定，任一命中即禁手（`reason` 区分）：
1. **长连**：check_win 中 cnt ≥ 6；
2. **双四**：落子后该点在 4 方向上形成的"四"（活四或冲四）计数 ≥ 2；
3. **双三**：落子后该点形成的"活三"计数 ≥ 2。**活三定义（与 Wikipedia Renju 对齐）**：三连且两端均开放；**含跳活三形态（如 `XX_X`，两端均开放）**——跳活三按"若补中间空位可成两端开放的活四"判定，具体棋形→结论以 T2 交付的"禁手判定对照表"为准（输入棋形 → 预期结论，供单测与评审核对）。

优先级：**先查成五（cnt==5 且无长连）→ 判黑胜，跳过禁手**（禁手与成五同时发生判黑胜，FR-07）；其余情况命中任一禁手 → 黑负、白胜。
对齐来源：Wikipedia Renju 禁手定义（分析文档 §5.1）。

### 5.3 AI 评估函数与候选点生成（FR-06）
```python
def evaluate(board, color):
    score = 0
    for each empty-or-occupied point p:             # 全盘扫描（中档同样全盘，见 §7 T3）
        for each of 4 directions:
            pattern = classify(p, board)            # 用 5.1 同款方向扫描归类
            score += SCORE[pattern] if owner==color else -SCORE[pattern]*1.1
    return score    # 己方为正; 对方威胁权重略高(防守倾向)

def candidates(board):
    pts = {neighbors of occupied stones within Chebyshev distance 2}
    return sorted(pts, key=evaluate_single, reverse=True)[:20]   # 邻域剪枝+排序
```
- 中档：`evaluate` **全盘扫描（15×15=225 点 × 4 方向）** + 候选点排序后取最优（隐式含威胁识别：冲四/活三分值高，玩家形成即被高分反制——封堵 = 玩家落点同样进入候选且己方对应位置得分最高）；
- 强档：Alpha-Beta 深度 4 + 迭代加深 + 时间预算（默认 1.5s，超时返回当前最优）：
```python
def alpha_beta(board, depth, alpha, beta, color, time_budget):
    if depth == 0 or time expired: return evaluate(board, color)
    for (x, y) in candidates(board)[:10]:           # move ordering 已按分值排序
        board.place(x, y, color)
        v = -alpha_beta(board, depth-1, -beta, -alpha, opponent(color))
        board.undo(x, y)
        alpha = max(alpha, v)
        if alpha >= beta: break                     # 剪枝
    return alpha
```
- 弱档：候选点随机加权（避开己方眼位/送死点：落点后己方不形成任何被连吃局面），合法优先中心区。

**时间预算与降级（NFR-01 ≤2s 硬线）**：强档迭代加深按 `time.monotonic()` 预算检查（预算 1.5s，留 0.5s 余量给渲染与输入）；若实测中盘超 2s，**按序降级：候选点上限 20→15 → 深度上限 4→3**，降级策略写入代码常量并随 README 声明。

### 5.4 边界与异常处理（NFR-01/04/06）
- **输入校验**：`parse_move` 白名单正则（`^[A-Oa-o][1-9][0-5]?$` 或 `^\d{1,2},\d{1,2}$`），长度/字符集/范围三重校验；非法输入提示具体原因（格式/越界/已占用）并重输，永不崩溃；
- **AI 时限**：强档迭代加深 + `time.monotonic()` 预算检查，超时返回已算出的最优解；候选点上限 20 防止爆炸（降级链见 §5.3）；
- **并发/重入**：单线程程序，无共享状态；Board 提供 `undo()` 供搜索用（`place` 的反操作，见 §4 API 表），UI 层不并发访问；
- **降级**：rich 检测无彩色终端 → 自动用字符模式（`●`/`○` 或 `B`/`W` 标签）渲染，黑白子仍可区分（NFR-03）；
- **退出**：KeyboardInterrupt 在 main 顶层捕获 → ui 关闭 console（恢复光标/颜色）→ exit 0；终局/输入等待中同样生效（FR-11）；
- **终端尺寸**：启动时检查 `shutil.get_terminal_size()`，< 24×60 时提示"终端过小"并等待放大，不渲染错乱棋盘（NFR-03）。

### 5.5 安全与合规（NFR-06）
- 纯本地运行：无网络请求、无系统目录写入、无提权调用；
- 坐标输入全量校验后才索引棋盘，杜绝越界访问；
- 依赖仅 rich（渲染），不执行外部命令、不 eval 用户输入。

## 6. 风险与对策

| 风险 | 影响 | 概率 | 对策/缓解 |
|------|------|------|-----------|
| 强档 AI 中盘超 2s（NFR-01） | 体验卡顿、验收失败 | 中 | 候选点剪枝（≤20）+ 深度上限 4 + 迭代加深时间预算 1.5s，超时返回次优；仍超 2s 则按序降级（候选 20→15、深度 4→3，§5.3）；NFR-01 实测用例纳入验收（M3） |
| 先手必胜破坏娱乐性（分析 §5.3 风险 4） | 人类必败、不可玩 | 高（学术结论） | 默认人类执黑 + 三档难度 + 禁手开关平衡；AI 不追求必胜线路（深度受限天然缓解） |
| 禁手误判（双三/双四/跳活三定义模糊） | FR-07 验收失败 | 中 | 判定逻辑与 Wikipedia Renju 定义逐条对齐；T2 产出"禁手判定对照表"（输入棋形→预期结论）；构造 ≥1 例/类单测（双三/双四/长连/成五优先/跳活三）；评审环节专门核对 |
| 中/强 AI 不封堵（FR-06 验收失败） | 核心验收不通过 | 中 | 评估函数对方威胁权重 ×1.1 + 候选含玩家威胁点 + 中档全盘扫描（§7 T3 显式要求）；10 组封堵用例作为 test_ai 回归用例 |
| rich 在无彩色/SSH 终端渲染异常 | 不可玩 | 低 | 字符降级模式 + 24×60 尺寸检测；README 注明 SSH 可用 |
| Ctrl+C 后终端状态残留 | FR-11 失败 | 低 | rich Console 统一管理终端状态（context manager 保证恢复）；退出路径集中收敛，单测模拟 Ctrl+C |

## 7. 工作量与任务拆解

### 任务拆解
| 任务 | 依赖 | 预估 |
|------|------|------|
| T1 board.py：坐标/落子/胜负/满盘/undo + test_board | 无 | 0.5 人日 |
| T2 board.py 禁手判定（长连/双三/双四/成五优先/跳活三）+ **禁手判定对照表**（输入棋形→预期结论，与 Wikipedia Renju 对齐）+ 对应单测 | T1 | 0.5 人日 |
| T3 ai.py：模式识别与评估函数（**显式要求全盘扫描：中档评估覆盖 225 点 × 4 方向，不得缩为仅候选点**）+ 弱/中档策略 | T1 | 0.5 人日 |
| T4 ai.py：Alpha-Beta + 迭代加深 + 时间预算与降级链（候选 20→15、深度 4→3）+ 强档 + FR-06 封堵单测 | T3 | 0.5 人日 |
| T5 ui.py：rich 渲染（含 last_move 高亮）/输入循环/退出恢复/降级 | T1 | 0.5 人日 |
| T6 main.py 主控 + config.py + 重开/退出流程 | T2,T4,T5 | 0.5 人日 |
| T7 README + pyproject 打包 + **Docker `python:3.10-slim` 干净环境冒烟**（FR-12/NFR 验收） | T6 | 0.5 人日 |
| 合计 | — | 3.5 人日 |

### 里程碑
| 阶段 | 交付物 | 验收点 |
|------|--------|--------|
| M1 棋盘与规则 | board.py + test_board 全绿 + 禁手判定对照表 | 胜负 4 方向/边界/满盘用例通过；禁手 4 类用例通过（双三/双四/长连/成五优先），对照表与 Wikipedia Renju 逐条一致 |
| M2 弱/中 AI 可玩 | ai.py 弱/中档 + ui.py 最小渲染 | 终端可完成整局；中档通过 FR-06 封堵 10 例（全盘扫描评估） |
| M3 强档 AI + 禁手全量 | ai.py 强档 + 禁手开关接线 | FR-06 全通过；强档中盘 ≤2s（超时按降级链处理）；禁手开关生效 |
| M4 成品交付 | 完整 UI + README + 打包 | Docker `python:3.10-slim` 干净环境按 README 跑通整局（FR-12）；Ctrl+C 干净退出（FR-11） |

## 8. 待确认问题（沿用分析文档 Q 表，方案按建议默认值实施）
| 问题 | 影响决策 | 方案采用值 |
|------|----------|------------|
| Q2 AI 棋力上限 | 是否引入威胁空间搜索 | 娱乐级偏强：评估+Alpha-Beta 深度 4（不达竞赛级）；如需上调另立迭代项 |
| Q3 棋盘规格 | FR-01 范围 | 15×15 默认 + 13×13 可选；19×19 排除 |
| Q4 禁手默认值 | FR-02 默认体验 | 默认关（大众五子棋），开关可启用；只做核心禁手，不做五手交换 |
| Q5 先后手 | FR-05 回合管理 | 默认人类执黑；`--human white` 预留参数位（首版支持，成本极低） |
| Q6/Q7/Q8 悔棋/双人/统计 | FR 范围 | 首版不做，列为后续增强 |

## 9. 修改回应表
本轮为本运行轮次首轮（r1），无本轮上轮评审意见；**继承上一运行轮次（requeue 前）dev-plan-reviewer 的 PASS 评审意见（3 条建议 + 3 项遗留事项），已全部吸收**，逐条回应如下：

| 意见 | 处理（采纳/拒绝/部分） | 理由 | 落点章节 |
|------|----------------------|------|----------|
| [建议] §4 API 表缺 `Board.undo(x,y)`（Alpha-Beta 伪代码调用它） | 采纳 | 搜索回溯是核心路径，接口表必须完整可执行 | §4 API 表新增 undo 行（入参/出参/错误语义） |
| [建议] §3 ui.py 补充上一步落子高亮机制（FR-08） | 采纳 | State.last_move 已有数据，渲染细节补齐后 code-developer 可直接照做 | §3 模块划分 ui.py 行：rich Style 反色/加粗/背景色标记 |
| [建议] §7 T3 显式注明中档评估函数覆盖全盘点 | 采纳 | 避免实现时误缩为仅候选点评估导致棋力下降（FR-06 验收依赖） | §5.3 评估函数注释 + §7 T3 任务描述 |
| [遗留 M1] 禁手"活三"定义（含跳活三 `XX_X`）与 Wikipedia Renju 对齐并产出对照表 | 采纳 | 双三判定是全方案最易误判点，对照表供单测与评审核对 | §5.2 活三定义显式化 + §7 T2 交付物 + §6 风险表 |
| [遗留 M3] 强档 AI 超 2s 的降级路径 | 采纳 | NFR-01 ≤2s 是硬验收线，降级链需先于实现定死 | §5.3 时间预算与降级 + §7 T4 |
| [遗留 M4] README 干净环境冒烟建议用 Docker `python:3.10-slim` | 采纳 | 本机环境可能已有依赖残留，Docker 才能证明"干净环境可跑通"（FR-12） | §7 T7 + M4 验收点 |
