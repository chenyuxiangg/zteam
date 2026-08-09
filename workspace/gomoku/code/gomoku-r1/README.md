# Gomoku — Linux Terminal 五子棋（人机对战）

一个 Python 实现的、可在 Linux 终端开箱即玩的五子棋（人机对战）成品。
计划与设计依据见工作区 `workspace/gomoku/plans/gomoku-r1.md` 与
`workspace/gomoku/testplans/gomoku-r1.md`；本目录是该计划的**代码实现**。

## 1. 特性一览

* **标准规则**：黑白轮流落子，横/竖/斜五连即胜；满盘无五连判平局。
* **可选禁手**（Renju）：黑方长连/双三/双四判负（成五优先，判黑胜）。
* **三档 AI**：
  * `weak` — 合法且不送死的随机落子（毫秒级）。
  * `medium` — 模式评估函数（活二/活三/冲四/活四）选最优（中盘 50–200 ms）。
  * `strong` — 候选点 + Alpha-Beta 搜索 + 迭代加深 + 时间预算
    （中盘 ≤ 1.5 s，NFR-01 要求 P95 ≤ 2 s）。
* **可配置棋盘**：15×15（默认）/ 13×13。
* **可配置先手**：人类执黑（默认）/ 执白（`--human white`，AI 先行）。
* **坐标输入双格式**：`A8` 或 `8,8`，任选其一。
* **干净退出**：Ctrl+C 任意时刻安全退出并恢复终端；输入 `quit` / `exit` 礼貌退出。
* **小终端降级**：终端 < 24×60 时提示放大后再继续；`NO_COLOR=1` 或 `TERM=dumb`
  时降级为字符模式（黑白子仍可区分）。

## 2. 运行方式

### 2.1 通过 pip 安装后运行

```bash
# 干净 Linux venv，Python 3.10+
python3 -m venv .venv
source .venv/bin/activate
pip install -e .               # 开发模式（推荐，代码改动即时生效）
# 或：pip install .             # 普通安装
gomoku                          # 启动 15×15 中档，禁手关，人类执黑
```

### 2.2 不安装直接跑

```bash
cd /path/to/this/dir
PYTHONPATH=. python3 -m gomoku
```

### 2.3 CLI 参数

| 参数 | 取值 | 默认 | 说明 |
|------|------|------|------|
| `--size` | `13` / `15` | `15` | 棋盘边长 |
| `--difficulty` | `weak` / `medium` / `strong` | `medium` | AI 棋力 |
| `--forbidden` | `on` / `off` | `off` | Renju 禁手开关（仅黑方受约束） |
| `--human` | `black` / `white` | `black` | 人类执色 |
| `--version` | — | — | 打印版本号 |
| `--help` | — | — | 打印帮助 |

示例：

```bash
python3 -m gomoku --size 13 --difficulty strong --forbidden on
python3 -m gomoku --human white --difficulty weak
```

## 3. 依赖安装

* **运行时**：`rich >= 13.0`（终端富文本渲染）。
* **开发/测试**（可选）：`pytest`、`pexpect`。

国内网络建议使用清华镜像：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple rich
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pytest pexpect
```

## 4. 键位与输入

* **落子坐标**：两种格式任选
  * 字母 + 行号（不区分大小写）：`A8` = A 列 8 行 = (1, 8)；
    `O15` = 角点；`a1` = 左上角。
  * 数字 `x,y`：`8,8` = 第 8 行第 8 列 = (8, 8)。
* **退出**：输入 `quit` / `exit` / `q`，或按 `Ctrl+C`，或 `Ctrl+D`。
* **非法输入**：格式错误、越界、已被占用都会给出**具体原因**的提示，
  并允许重新输入，不会崩溃。
* **坐标约定**（自检/调试参考）：0-indexed ``(x, y)``，``x`` 是列
  （`A`=0, `O`=14），`y` 是行（`1`=0, `15`=14）。

## 5. 配置选项默认值表

| 配置项 | 默认值 | 取值范围 | 含义 |
|--------|--------|----------|------|
| 棋盘边长 (`size`) | `15` | `13` / `15` | 13×13 / 15×15 |
| AI 难度 (`difficulty`) | `medium` | `weak` / `medium` / `strong` | 三档棋力 |
| 禁手 (`forbidden`) | `off` | `on` / `off` | Renju 禁手是否生效（仅黑方） |
| 人类执色 (`human`) | `black` | `black` / `white` | 默认人类先手 |

## 6. AI 算法说明

* **Weak 档**：候选点（已有棋子 Chebyshev 距离 ≤ 2 的空位）随机排序，
  过滤掉"让对手下一手形成活四"的送死点，再随机取一个。
* **Medium 档**：对所有候选点用模式评估函数评分（活二/活三/冲四/
  活四/五连各自不同分值），按"己方最大威胁 + 对方最大威胁×1.1"排序
  取最高分。
* **Strong 档**：候选点上限 12（按浅层评估排序以利剪枝），从深度 2
  起步迭代加深到深度 4，alpha-beta 搜索；带 `time.monotonic()` 截止
  时间（默认 1.5 s），超时则返回当前已算出的最优解。强档中盘落子
  P95 ≤ 2 s（见 NFR-01）。

## 7. 模块结构

```
gomoku/
├── __init__.py        # 包入口、版本号
├── __main__.py        # `python -m gomoku` 入口
├── config.py          # 不可变配置（dataclass + 校验）
├── board.py           # 纯逻辑棋盘：落子/胜负/禁手/坐标解析
├── ai.py              # 评估函数 / 候选点 / Alpha-Beta / 三档策略
├── ui.py              # rich 渲染 / 输入循环 / 退出恢复 / 降级
└── main.py            # CLI 解析 / 回合循环 / 重开 / Ctrl+C
```

各模块对应 plan §3 的模块划分；详细接口与数据契约见
`workspace/gomoku/plans/gomoku-r1.md` §4。

## 8. 已知限制

* **不联机**、**不做 GUI/Web**、**不做棋谱/存档/开局库**、**不做悔棋
  /双人同屏/胜负统计**（Q6/Q7/Q8 列为后续增强）。
* **不实现连珠完整开局规则**（五手交换/三手交换等），只做核心禁手判定。
* **AI 棋力定位娱乐级偏强**（深度 4 alpha-beta + 候选剪枝），不达
  Gomocup 竞赛级；如需上调棋力另立迭代项。
* **跨平台**：本项目仅在 Linux 终端下保证通过；Windows / macOS
  的 rich 行为未做覆盖。

## 9. 故障排查

| 现象 | 原因 / 处置 |
|------|------------|
| 启动报 `ModuleNotFoundError: No module named 'rich'` | 未安装依赖：`pip install rich` |
| 终端过小提示放大 | 窗口 < 24×60，按提示放大后回车继续 |
| 黑白子看不出区别 | 终端不支持彩色：设置 `NO_COLOR=1` 后会自动用 `●` / `○` 字符 |
| 落子报"格式错误" | 检查坐标格式：`A8` / `8,8`（不要带空格或中文标点） |
| 落子报"越界" | 13×13 棋盘最大 `M13` / `13,13`；15×15 最大 `O15` / `15,15` |
| 落子报"已被占用" | 该位置已有棋子，输入其他空位 |
| Ctrl+C 之后终端花屏 | 极少数终端会保留 ANSI 状态；输入 `reset` 回车可恢复 |
| 强档落子慢 | 默认时间预算 1.5 s；候选点超过 12 时按估值排序剪枝 |

## 10. 测试

测试代码（`tests/test_board.py` / `tests/test_ai.py` / `tests/e2e/`）由
test-developer 阶段产出；本 README 不包含测试代码。

开发者在改动本目录代码后可手动跑（test-developer 阶段产出后启用）：

```bash
pip install -e '.[dev]'
pytest -q
```
