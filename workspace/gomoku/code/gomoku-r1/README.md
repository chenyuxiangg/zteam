# gomoku — Linux 终端五子棋人机对战

> 五子棋（人机对战）终端成品。需求 `gomoku/gomoku` 第 1 轮 code 阶段产物。

## 1. 简介

- **形态**：纯终端（Linux x86-64，Python ≥3.10）
- **第三方依赖**：仅 `rich`（终端富文本渲染）。棋盘/AI/规则逻辑均无运行时依赖，可作退化基线
- **对弈模式**：人机对战。人类执黑（默认） / 执白（实验性，--human white）
- **棋盘**：15×15（默认） / 13×13
- **AI 难度**：weak / medium / strong 三档
- **禁手规则**（renju）：默认关闭，开启时黑方双三 / 双四 / 长连即判负；成五优先判胜

## 2. 安装与运行

### 2.1 干净环境（pip 安装）

```bash
cd <本目录>
pip install .
# 或开发模式：
pip install -e .
```

安装成功后可执行 `gomoku` 命令，或 `python -m gomoku`。

### 2.2 直接运行（无需安装）

```bash
cd <本目录>
PYTHONPATH=. python3 -m gomoku
```

### 2.3 CLI 参数

```
python -m gomoku [--size 15|13] [--difficulty weak|medium|strong] [--forbidden on|off] [--human black|white]
```

- `--size 13|15`：棋盘规格（默认 15）
- `--difficulty weak|medium|strong`：AI 难度（默认 medium）
- `--forbidden on|off`：黑方禁手规则开关（默认 off）
- `--human black|white`：人类执色（默认 black；执白为实验性，因禁手关闭时黑先手优势明显）

### 2.4 运行示例

```bash
# 15×15 棋盘，中档 AI，无禁手
python -m gomoku

# 13×13 棋盘，强档 AI，开启禁手
python -m gomoku --size 13 --difficulty strong --forbidden on
```

## 3. 键位 / 输入

- **坐标输入**：
  - 字母列 + 数字行：`A8`（A 列 8 行，0-index 即 (0, 7)）；大小写均接受
  - 数字对：`8,8` 或 `8 8`（行,列 → 0-index）
  - 13×13 棋盘允许 `A–M` / `1–13`；15×15 允许 `A–O` / `1–15`
- **非法输入**：自动重输，提示具体原因（格式 / 越界 / 已占用）
- **退出**：输入 `quit` / `q` / `exit` 或按 `Ctrl+C` / `Ctrl+D`，终端恢复原始状态
- **重开**：终局后提示 `重开？(y/n)`，默认 y

## 4. 配置选项（FR-01/02/05/07）

| 配置 | 取值 | 默认 | 备注 |
|------|------|------|------|
| 棋盘规格 (size) | 13 / 15 | 15 | 19×19 排除（分析 Q3） |
| AI 难度 (difficulty) | weak / medium / strong | medium | 三档棋力（见 §5） |
| 禁手规则 (forbidden) | on / off | off | 仅黑方；on 时黑双三/双四/长连即输 |
| 人类执色 (human) | black / white | black | 执白为实验性 |

## 5. AI 算法说明

### 5.1 三档棋力

| 难度 | 算法 | 验收底线 |
|------|------|----------|
| weak | 候选邻域剪枝 + 评估函数取最大 | 合法落子 + 不破坏己方已有三/四（FR-06③） |
| medium | 评估函数 + 1 层威胁封堵（必堵对手"下一步成五/冲四/活三/活四"） | 玩家"下一步可成冲四/活四"必堵；"玩家已有活三"必堵其一端或形成更大威胁（FR-06①②） |
| strong | Alpha-Beta 迭代加深（最大深度 4）+ 候选剪枝（20 点）+ 时间预算（默认 2s，可降级） | medium 全过 + 主动构造活四/冲四进攻（FR-06③进攻侧） |

### 5.2 评估函数

- 模式分类（FIVE / LIVE_FOUR / RUSH_FOUR / LIVE_THREE / SLEEP_THREE / LIVE_TWO / SLEEP_TWO / ONE）
- 评分表见 `gomoku/ai.py` SCORE 常量（FIVE=1,000,000；LIVE_FOUR=100,000；RUSH_FOUR=10,000；LIVE_THREE=5,000；…）
- 单点评估 `evaluate_point(x, y, color)`：模拟落子后读 4 方向形态分（`我方 - 对手`）
- 全局评估 `evaluate(board, color)`：对所有已落子按 4 方向累加形态分（差值）

### 5.3 Alpha-Beta 搜索

- 候选点：邻域剪枝（半径 2）+ 按邻近子数启发排序取前 20
- 搜索：迭代加深（depth 2 → 4），每层 `time.monotonic()` 检查 deadline
- 静态评估：`evaluate(board, color)` 作为叶子/中止时的评分
- 落子顺序：按候选分排序提升剪枝效率

### 5.4 禁手规避

- AI 执黑 + 禁手开启时，对每个候选点预检 `Board.check_forbidden`
- 命中禁手的候选点直接从候选列表剔除（搜索内部以 `-inf` 处理）
- 保证 AI 永不主动走禁手（FR-07 对 AI 侧成立）

## 6. 规则层

- **胜负判定**：`Board.check_win(x, y)` 沿 4 方向扫描连续同色，≥5 即胜（含长连，freestyle 允许）
- **禁手判定**：`Board.check_forbidden(x, y, color='B')`
  - 优先级：成五（连五）→ 黑胜，跳过禁手
  - 其他禁手命中其一 → 黑负、白胜
  - 长连（≥6 子）/ 双四 / 双三
  - 跳活三 / 跳四：5 长度子窗 + 11 长度 9 字符识别
- **满盘判定**：`Board.is_full()` + 回合切换前检查，平局判 `None`

## 7. 性能与限制

- **参考硬件基线**（NFR-01）：x86-64 四核及以上 CPU（i5-12400 / 同档）、≥8GB RAM、Python 3.10+
- **强档 15×15 中盘（双方各 ≥20 子）AI 落子耗时**：<2s（降级链兜底 <2.5s）
- **启动到可下棋**：<2s
- **棋盘刷新**：<200ms
- **依赖可降级**：核心对局逻辑不依赖 rich；如需零依赖运行，可去掉 ui.py 改用 print 重写

## 8. 文件结构

```
code/gomoku-r1/
├── pyproject.toml          # 打包配置
├── README.md               # 本文件
└── gomoku/
    ├── __init__.py         # 版本声明
    ├── __main__.py         # python -m gomoku 入口
    ├── config.py           # Config 数据类 + 默认值 + 校验
    ├── board.py            # 棋盘与规则层（落子/胜负/禁手/坐标/undo/reset）
    ├── ai.py               # AI 决策层（评估函数/候选/Alpha-Beta/三档）
    ├── ui.py               # 终端 UI（rich 渲染/输入循环/退出）
    ├── main.py             # 主控（CLI 解析/回合循环/重开/退出）
    ├── forbidden_cases.py  # 禁手判定对照表（16 例棋形→结论）
    └── py.typed            # PEP 561 标记
```

## 9. 与方案对应关系

| 方案章节 | 实现 |
|----------|------|
| §3 模块划分 | `gomoku/{config,board,ai,ui,main}.py` |
| §4 接口表 | `Board` / `ai.choose_move` / `UI.render/get_move` / `parse_args` |
| §5.1 胜负 | `Board.check_win`（4 方向直连扫描） |
| §5.2 禁手 | `Board.check_forbidden`（9 字符窗口严格判活三/四） |
| §5.3 AI | `ai.evaluate` / `evaluate_point` / `candidates` / `_alpha_beta` / `choose_move` |
| §5.4 边界 | 输入校验 (`Board.parse_move`)、AI 时限降级（`time.monotonic`）、退出恢复（rich） |
| §5.5 安全 | 纯本地、正则校验、不 eval/exec、rich 官方源 |
| §7 T3 禁手对照表 | `forbidden_cases.py`（16 例） |

## 10. 已知限制（与方案 §6 风险行一致）

- **强档进攻性**：评分表调参优先于深度/耗时放宽。如验收未达预期，方案 §8 P1 保留预案
- **先手必胜**：分析 H4 指出空 15×15 棋盘黑先有必胜策略。本实现不追求"AI 必求必胜"（人类默认执黑 + 难度分级缓解）
- **人类执白**：实验性；禁手关闭时黑先手优势明显，体验可能不公平
- **连珠开局规则**：未实现五手交换等完整开局规则，仅做核心禁手判定

## 11. 验证清单（自检命令）

```bash
# 1. CLI 工作
python3 -m gomoku --help

# 2. 禁手对照表自检
python3 -m gomoku.forbidden_cases
# 期望输出：Forbidden-move table: 16 pass, 0 fail, 0 skipped.

# 3. 整局冒烟（AI vs AI，弱档）
PYTHONPATH=. python3 -c "
import random
from gomoku.board import Board
from gomoku.ai import choose_move
b = Board(15)
turn = 'B'
for i in range(45):
    if b.is_full(): break
    move = choose_move(b, turn, difficulty='weak')
    if move is None: break
    x, y = move
    b.place(x, y, turn)
    winner = b.check_win(x, y)
    if winner:
        print(f'{winner} wins at step {i+1}')
        break
    turn = 'W' if turn == 'B' else 'B'
"

# 4. 禁手单测（r2 评审复现）
python3 -c "
import sys
sys.path.insert(0, '.')
from gomoku.board import Board
# r2 复现 1：_X_XX_ + _XX_
b = Board(15)
b.place(7, 7, 'B'); b.place(8, 7, 'B')
b.place(5, 5, 'B'); b.place(5, 6, 'B')
fb, reason = b.check_forbidden(5, 7, 'B')
assert (fb, reason) == (True, 'double_three'), f'FAIL: {(fb, reason)}'
print('r2 复现 1：', (fb, reason))
# r2 复现 2：_XX_X_ + _X_X_
b = Board(15)
b.place(5, 7, 'B'); b.place(6, 7, 'B')
b.place(8, 6, 'B'); b.place(8, 8, 'B')
fb, reason = b.check_forbidden(8, 7, 'B')
assert (fb, reason) == (True, 'double_three'), f'FAIL: {(fb, reason)}'
print('r2 复现 2：', (fb, reason))
print('All r2 reproduction tests PASSED')
"
```

## 12. 修改回应表

### R2 评审意见 1（严重）：FR-07 双三漏判，`_is_live_three` 算法修复不完整

- **位置**：`gomoku/board.py` `Board._is_live_three_including`（替代 r2 静态 5 窗策略）
- **修复方案**：重写为"以候选点为中心 9 字符 line，沿 4 方向各自在长度 3/5/7 窗口做严格活三判据"：
  1. 窗口含 3 B、且无 '*' 阻挡；
  2. 窗口首尾两端可为 '.' 或包含内部空位（`_X_XX_` / `_XX_X_`）；
  3. 窗口外侧左右各一格为 '.'（保证补子成活四）。
- **验证**：r2 复现 1/2 + 16 例对照表全过。

### R2 评审意见 2（一般）：`__pycache__/` 不应出现在交付目录

- **方案**：保留 `.gitignore` 内容（`__pycache__/`、`*.pyc`），交付前 `find . -name __pycache__ -exec rm -rf {} +` 清空。

### 角色文件 §3 [严重] 失败准则：≥1 严重 / ≥3 一般 → FAIL

- 本轮实现了 r2 复现的两组双三漏判，并在 §11 提供 4 条复现命令；连线后可一键验证。
- 修复算法同时不破坏 r1 已 PASS 的场景（见 `forbidden_cases.py` 中"单活三""单四""白方永不判禁"等控制例）。

## 13. 维护说明

- 修改 AI 评分表（`gomoku/ai.py` SCORE）时同步更新 README §5.2
- 修改禁手判定（`gomoku/board.py` `check_forbidden`）时同步更新对照表（`forbidden_cases.py`）并跑通 §11 第 2 项
- 新增难度档位时同步更新 `Config.difficulty` 类型、`parse_args` choices、AI 路由（`choose_move`）

