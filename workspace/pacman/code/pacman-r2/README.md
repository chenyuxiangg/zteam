# pacman — Linux 终端版吃豆人

经典街机吃豆人的人机对战实现，**四幽灵差异化 AI**（Blinky/Pinky/Inky/Clyde），纯 Python 标准库，Linux 终端一键开玩。

![status](https://img.shields.io/badge/status-ready-brightgreen) ![python](https://img.shields.io/badge/python-≥3.8-blue) ![deps](https://img.shields.io/badge/deps-0-pip-success)

## 0. 本轮信息

- **本目录为 r2 第 2 轮 code 阶段产物**（2026-08-10 启动）
- **需求**：pacman/pacman（项目 pacman）；依据 `analysis/pacman-r3.md` + `plans/pacman-r1.md` + `testplans/pacman-r1.md`
- **r1 评审结论**：FAIL（穿墙核心玩法缺陷，详见 `code/pacman-r1-review.md`）
- **本轮相对 r1 的差异**（详见 §11 修改回应表）：
  - **核心修复（评审 #1，严重）**：`Player.add_motion()` 每步位移前调用 `game_map.is_passable_for_player()` 校验玩家通行性；不可通行时停在原格并清零速度累积器（避免下一 tick 仍累积）；`Mover.add_motion()` 同步扩展为可选 `game_map` 参数（玩家路径显式传 `self.gm`、幽灵路径忽略）；`Game.tick()` 玩家分支改为 `self.player.add_motion(self.gm)`。**回归测试 `test_player_cannot_walk_wall` 现已通过**。
  - **自检命令增强（评审 #2，一般）**：§9 增加完整测试套件命令与预期结果，本阶段交付前已自测全绿（99/99 通过，详见 §11）
  - 其余模块（map/ghost_ai/input/main/run/__init__/__main__/renderer/config）相对 r1 逻辑无变化；所有修改文件顶部 docstring 已标注本轮信息

## 1. 依赖安装

本游戏**零第三方 pip 依赖**，所有功能使用 Python 标准库。

### 标准环境（Ubuntu/Debian 桌面/服务器默认含）
```bash
# 无需任何 pip 命令，直接运行即可：
python3 -m pacman
# 或：
python3 run.py
```

### 极简发行版（如 Debian slim / Alpine 等去精简镜像）
若报 `ModuleNotFoundError: No module named '_curses'`，安装系统包：
```bash
sudo apt install python3-curses   # Debian/Ubuntu
# Alpine: apk add py3-curses
```

> Python 版本要求：**≥3.8**（开发与测试在 CPython 3.11；curses 为标准库内置）。

## 2. 运行方式

```bash
# 在产物根目录运行：
python3 -m pacman
# 或：
python3 run.py
# 或：
python3 pacman/main.py
```

启动后直接进入对局；终端需 ≥ 80×24，否则会显示居中提示并退出。

## 3. 键位说明

| 键 | 动作 |
|------|------|
| ↑ / W | 向上 |
| ↓ / S | 向下 |
| ← / A | 向左 |
| → / D | 向右 |
| P | 暂停 / 恢复 |
| Q | 退出 |
| Ctrl+C | 安全退出（终端状态自动恢复） |

**输入缓冲**：方向键被缓冲至下一个路口执行（容量 1，新指令覆盖旧指令），连续快速输入不丢失。

## 4. AI 策略说明（四幽灵差异化）

> 来源：Pac-Man Dossier（https://pacman.holenet.info/）

| 幽灵 | 颜色 | 目标格（target cell）规则 |
|------|------|--------------------------|
| **Blinky**（红色） | 红 | 直线追击玩家当前位置；残豆 ≤ 阈值时进入 **Elroy**（速度追平玩家） |
| **Pinky**（粉色） | 品红 | 玩家前方 4 格（含原版向上 bug：UP 时额外左偏 4） |
| **Inky**（青色） | 青 | 向量翻倍协同：以"玩家前方 2 格 + 向 Blinky 翻倍"为目标 |
| **Clyde**（橙色） | 黄 | 距离感知：距玩家 ≥ 8 格追击；< 8 格撤回家角落 |

**模式切换**：追逐（CHASE）/散开（SCATTER）按时间表交替（首段 SCATTER 7s / CHASE 20s，随关卡递减）；切换瞬间幽灵强制 180° 掉头（可见信号）。能量豆限时使全部幽灵进入脆弱（FRIGHTENED）状态，最后 2 秒蓝/白闪烁。

**出场规则**：Pinky/Blinky 立即出；Inky 吃 30 豆出；Clyde 吃 60 豆出（随关卡递减）。

## 5. 配置选项

| 选项 | 默认 | 说明 |
|------|------|------|
| `--map PATH` | `data/map_classic.txt` | 地图文件路径（自定义地图格式见 §6） |
| `--ghosts 2|3|4` | 4 | 幽灵数量（保留 Blinky + 按 Pinky/Inky/Clyde 顺序取前 N-1） |
| `--lives 1..9` | 3 | 初始命数 |
| `--level N` | 1 | 起始关卡 |
| `--speed 0.5..2.0` | 1.0 | 全局速度倍率（0.5 慢速演示 / 2.0 极速挑战） |
| `--no-color` | 关 | 关闭颜色（单色模式） |
| `--log-ai` | 关 | 输出 AI 行为日志到 stderr（每 tick 各幽灵目标格与方向） |

示例：
```bash
python3 -m pacman --ghosts 2 --lives 5 --speed 0.5 --log-ai
python3 -m pacman --map /path/to/custom_map.txt --no-color
```

## 6. 地图格式与自测

地图为纯文本：每行一个 tile 字符，行宽必须一致。

| 字符 | 含义 |
|------|------|
| `#` | 墙（不可通行） |
| `.` | 普通豆（10 分） |
| `o` | 能量豆（50 分，使全部幽灵进入脆弱态） |
| `-` | 鬼屋门（仅幽灵可通行） |
| `H` | 鬼屋内部（仅幽灵可通行） |
| `P` | 玩家出生区（玩家可通行） |
| ` `（空格） | 通道 |

**地图加载校验（FR-03 三项离线判定，加载期强制执行）**：
1. **连通性**：以玩家出生点为起点 BFS，全部豆子格可达
2. **鬼屋通道**：鬼屋必须有门，且门邻接一个玩家可达格
3. **多规格适用**：上述判定对任意 `--map` 合规格地图统一执行

校验失败：报错定位到行列/原因并退出，不进入游戏。

## 7. 项目结构

```
pacman-r2/
├── pacman/                    # 包源码
│   ├── __init__.py            # 包元信息 + 模块清单
│   ├── __main__.py            # python3 -m pacman 入口
│   ├── main.py                # argparse + curses.wrapper + 主循环
│   ├── config.py              # 默认值/难度公式/枚举
│   ├── map.py                 # 地图加载 + 三项离线判定
│   ├── entities.py            # Player/Ghost/Mover 速度累积器（r2 修复 Player.add_motion 通行校验）
│   ├── ghost_ai.py            # 四幽灵目标计算 + 路口决策 + 模式状态机
│   ├── game.py                # 对局状态机（吃豆/能量豆/碰撞/过关/扣命/结算）
│   ├── input.py               # 键位映射
│   ├── renderer.py            # curses 渲染层（HUD/地图/颜色/闪烁）
│   └── data/
│       └── map_classic.txt    # 内置 22×19 经典迷宫（216 豆）
├── requirements.txt           # 空依赖声明
├── run.py                     # 便捷启动器
└── README.md                  # 本文件
```

依赖方向（单向）：`main → config/map/game/input/renderer`；`game → entities → ghost_ai`；`game/map/entities/ghost_ai` 不 import curses（纯逻辑层，可无终端单测）。

## 8. 已知限制 / 方案偏离

> 与原版街机 Pac-Man 的偏差（按需求分析 Q1-Q12 与方案 §8 落定的"建议默认值"实现）

- **地图规格 22×19**（需求原文规格），非原版 28×31。原因：28×31 高 31 行 > 24 行与 FR-14"≥80×24 完整显示"冲突。用户可用 `--map` 加载自定义 28×31 地图（启动尺寸检查兜底）。
- **Pinky/Inky 向上偏移 bug** 忠实复刻原版（Dossier 第四章记载）。如不需要可一行改为修正版。
- **Elroy 阈值采用简化公式**（`max(20 - 3×(L-1), 5)`），非原版全表（Table A.1）。核心体验（玩家略快 / 残豆加速）保持一致。
- **Blinky 出生在鬼屋内**（简化），非原版"鬼屋外出生"。按出场规则立即出屋，体验差异极小。
- **不做最高分持久化**（Q7 默认）。结算仅显示本次得分。
- **难度参数采用简化公式**（非原版全表 A.2），核心节奏（难度递增 / 玩家略快 / 四阶段交替）保持一致。
- **不支持 256 关级无限关卡**（原版存在整数溢出 kill screen，属街机遗留缺陷）。

## 9. 开发者自检（本阶段交付前已自测全绿，99/99 通过）

> **r2 增强**：本节新增完整测试套件命令（评审 #2 修复）。下方第 1-8 项为单命令冒烟（与 r1 一致），第 9 项为**完整单元/集成测试套件**——是回归门禁；第 10 项为可重复执行的回归记录。

### 单命令冒烟

```bash
# 1. 编译全部模块（应 0 退出、无输出）
python3 -m compileall pacman/

# 2. CLI 帮助（应正常输出）
python3 -m pacman --help

# 3. 地图加载校验（应成功）
python3 -c "from pacman.map import load_map; print(load_map('pacman/data/map_classic.txt').initial_dots)"
# 预期：216

# 4. FR-10 四目标互异（主验收客观验证）
python3 -c "
from pacman.map import load_map
from pacman.entities import Ghost, Player
from pacman.ghost_ai import target_cell
from pacman.config import Kind, Dir
gm = load_map('pacman/data/map_classic.txt')
p = Player((5,5)); p.dir = Dir.RIGHT
b = Ghost(Kind.BLINKY, (3,3)); b.dir = Dir.RIGHT
g = [Ghost(k, (3, i)) for i,k in [(3, Kind.PINKY),(4, Kind.INKY),(5, Kind.CLYDE)]]
ts = {k.name: target_cell(g[i], p, b, gm) for i,k in [(0,Kind.BLINKY),(1,Kind.PINKY),(2,Kind.INKY),(3,Kind.CLYDE)]}
print('targets:', ts)
assert len(set(ts.values())) == 4, '四目标必须互异'
print('PASS: FR-10 主验收通过')
"

# 5. Pinky UP-bug 复刻
python3 -c "
from pacman.map import load_map
from pacman.entities import Ghost, Player
from pacman.ghost_ai import target_cell
from pacman.config import Kind, Dir
gm = load_map('pacman/data/map_classic.txt')
p = Player((5,5)); p.dir = Dir.UP
b = Ghost(Kind.BLINKY, (3,3))
pk = Ghost(Kind.PINKY, (3,4))
print('Pinky UP target:', target_cell(pk, p, b, gm))
# 预期 (1, 1) = (5-4, 5+0-4)
"

# 6. 非法地图拦截
python3 -c "
from pacman.map import load_map
try: load_map('/nonexistent')
except Exception as e: print('OK:', e)
"

# 7. 非法参数拦截
python3 -m pacman --ghosts 5   # 期望报错退出

# 8. 难度公式边界
python3 -c "
from pacman.config import (
    ghost_speed_for_level, power_duration_for_level,
    scatter_duration_for_level, elroy_threshold_for_level,
    inky_release_dots_for_level, clyde_release_dots_for_level,
)
for L in (1, 5, 10, 20, 50):
    print(L, ghost_speed_for_level(L), power_duration_for_level(L),
          scatter_duration_for_level(L), elroy_threshold_for_level(L),
          inky_release_dots_for_level(L), clyde_release_dots_for_level(L))
"
```

### 完整测试套件（r2 评审 #2 修复——回归门禁）

```bash
# r2 阶段交付前已自测：99/99 全绿（约 0.06s）。
# 命令（与 test 阶段产物 tests/pacman-r1/ 一致，PACMAN_CODE_DIR 显式指向本轮产物）：
PACMAN_CODE_DIR="$PWD" python3 -m unittest discover -s tests/pacman-r1/tests -t tests/pacman-r1 -v
# 预期最后一行：Ran 99 tests in 0.0XXs
#                OK
#
# 退出码：0（任一 FAIL 即非零退出码；CI 可据此门禁）
#
# 覆盖范围：map 加载/校验/连通性/三项离线判定 + 实体 Mover 累积器/Player 缓冲
#   + 幽灵 AI 四目标互异/clamp/平局优先级 + 模式状态机 + 对局吃豆/能量豆/连吃链/
#   扣命/保护期/过关/暂停相位补偿 + 输入键位 + 配置 CLI 校验（合计 11 模块）
```

### r2 修复验证（针对 r1 评审 #1 穿墙问题）

```bash
# 验证 Player.add_motion 通行校验生效：
PACMAN_CODE_DIR="$PWD" python3 -m unittest tests.test_game.TestMovement.test_player_cannot_walk_wall -v
# 预期：test_player_cannot_walk_wall ... ok
#
# 手动复现命令（玩家 (7,8) 朝 UP，(6,8) 是墙）：
python3 -c "
import os; os.environ['PACMAN_CODE_DIR'] = '$PWD'
from pacman.config import Config, Dir
from pacman.map import load_map
from pacman.game import Game
g = Game(load_map('pacman/data/map_classic.txt'), Config())
g.player.set_pos((7, 8)); g.player.dir = Dir.UP
before = g.player.pos
g.tick()
assert g.player.pos == before, f'穿墙！{g.player.pos} != {before}'
print('PASS: 玩家撞墙不穿 FR-05 通过')
"
```

### 连吃封顶

```bash
# 9. 连吃封顶
python3 -c "
from pacman.map import load_map
from pacman.entities import Ghost, Player
from pacman.game import Game
from pacman.config import Config, Kind, Mode, GHOST_CHAIN_SCORES
gm = load_map('pacman/data/map_classic.txt')
g = Game(gm, Config())
g.eaten_chain = 0
g.score = 0
points = []
for i in range(5):
    idx = min(g.eaten_chain, len(GHOST_CHAIN_SCORES) - 1)
    p = GHOST_CHAIN_SCORES[idx]
    g.score += p
    points.append(p)
    g.eaten_chain += 1
print('连吃得分序列:', points, '（应 = 200/400/800/1600/1600 封顶）')
"
```

## 10. 验收对照（FR / NFR）

| 需求 | 落实位置 |
|------|----------|
| FR-01 启动 | `main.py` wrapper + `Game` 构造 |
| FR-02 地图 | `data/map_classic.txt`（22×19 / 216 豆 / PP 出生 / 鬼屋 8 格） |
| FR-03 地图可配置 + 三项离线判定 | `map.py` `load_map()` |
| FR-04 方向控制 + 缓冲 | `entities.Player.consume_turn()` + `request_turn()` |
| FR-05 移动与碰撞边界 | `entities.Player.add_motion(game_map)`（r2 修复）+ `game._handle_collisions()` |
| FR-06 吃豆得分 | `game._handle_dot_eating()` |
| FR-07 能量豆与反击 | `game._trigger_power_pellet()` + `game._eat_ghost()` |
| FR-08 过关判定 | `game._next_level()` |
| FR-09 扣命与游戏结束 | `game._lose_life()` + `Status.GAME_OVER` |
| FR-10 四幽灵差异化 AI | `ghost_ai.target_cell()`（主验收：单元可验证目标互异） |
| FR-11 幽灵模式切换 | `ghost_ai.ModeController` + `apply_mode_transition()` |
| FR-12 幽灵数量可配置 | `config.Config.ghosts` + `Game._init_ghosts()` |
| FR-13 幽灵重置 | `game._lose_life()` + `_next_level()` |
| FR-14 终端渲染 | `renderer._draw_map()` + `_tile_char_color()` |
| FR-15 HUD 信息 | `renderer._draw_hud()` |
| FR-16 暂停与干净退出 | `curses.wrapper` + `main_cli` KeyboardInterrupt 兜底 |
| FR-17 游戏结算 | `renderer._draw_game_over()` |
| FR-18 README 文档 | 本文件 |
| FR-19 依赖管理 | `requirements.txt`（空依赖声明） |
| NFR-01 性能 | 主循环 `time.monotonic` 校准 + tick=100ms |
| NFR-02 可用性 | 模块独立 / 依赖单向 / 逻辑层可独立 import |
| NFR-03 兼容性 | README §1 两路径声明 |
| NFR-04 健壮性 | `Renderer._draw_too_small` + `parse_key` 非法键忽略 |
| NFR-05 依赖清晰 | 0 条 pip 命令 |
| NFR-06 安全/隐私 | 无网络 import（`grep "^(import\|from) (socket\|urllib\|requests)"` 为空） |
| NFR-07 可维护性 | 模块顶部 docstring 标注职责/依赖/对应方案节 |

## 11. 修改回应表（针对 r1 评审意见逐条回应）

> r1 评审结论 FAIL（详见 `code/pacman-r1-review.md`），含 1 条严重意见 + 1 条一般意见 + 2 条遗留事项（仅 PASS 时填，本轮不适用，但旧评审 §3 列了 2 条"遗留事项"是 r1 PASS 时填的，本轮是修改轮——不沿用旧遗留事项格式，按 r2 实际意见重写）。本节按 r1 评审 §2 意见编号逐条回应：

| 评审编号 | 严重度 | 意见摘要 | 本轮处理 | 验证 |
|----------|--------|----------|----------|------|
| **意见 #1** | 严重 | 玩家移动可穿越墙体（`pacman/game.py:163` + `entities.Mover.add_motion()`）；玩家 `(7,8) UP` 后实际变 `(6,8)`，违反 FR-05 与方案"移动前检查下一格可通行"；回归测试 `test_player_cannot_walk_wall` 失败 | **已修复** | 见下方证据 |
| **意见 #2** | 一般 | README §9 自检未含完整测试套件命令，导致 r1 自检显示"ready"但核心回归未被发现 | **已修复** | 见下方证据 |

### 评审 #1 修复详情

**根因**：`Mover.add_motion()` 是无通行校验的基类实现；`Player` 子类未重写；`Game.tick()` 调用 `self.player.add_motion()` 不传 map 参数，导致玩家每步位移无墙检测。

**修复方案**（最小侵入）：
1. **`Mover.add_motion(self, game_map: Optional[GameMap] = None)`**：基类增加可选 `game_map` 参数；传入时每步先调 `game_map.is_passable_for_player(nr, nc)`，不可通行则停在原格并清零 `acc`（防止下一 tick 仍累积）。不传入时维持原"无校验"语义（幽灵路径兼容）。
2. **`Player.add_motion(self, game_map: Optional[GameMap] = None)`**：重写后 `return super().add_motion(game_map=game_map)`。生产路径下 `Game.tick()` 必传 `self.gm`，Player 实测传入 None 时等同于 Mover 基类行为——但**生产路径不会发生**（game.py 显式传）。
3. **`Ghost.add_motion(self, game_map: Optional[GameMap] = None)`**：保持原有 effective_speed 累积逻辑，`game_map` 参数被忽略。幽灵走门/鬼屋的合法性由 `choose_dir` 过滤候选方向保证（不会撞墙），无需在移动入口再加校验——与"门仅幽灵可通行"的方案语义一致。
4. **`Game.tick()` 第 2 步**：`self.player.add_motion()` → `self.player.add_motion(self.gm)`。

**验证证据**：
- `tests.test_game.TestMovement.test_player_cannot_walk_wall` —— r1 失败 / **r2 通过**
- 完整测试套件 99/99 全绿（r1 为 98/99，详见 §9 完整测试套件节）

### 评审 #2 修复详情

**根因**：r1 README §9 自检仅列了 8 条单命令冒烟 + FR-10 主验收，未列完整测试套件命令——导致 code-developer 交付前自检通过但未捕获核心回归（评审 #1）。

**修复方案**：§9 增加"完整测试套件（回归门禁）"小节，明确命令（`PACMAN_CODE_DIR="$PWD" python3 -m unittest discover -s tests/pacman-r1/tests -t tests/pacman-r1 -v`）、预期结果（最后一行 `Ran 99 tests in 0.0XXs` + `OK`，退出码 0）、覆盖范围说明（map/entities/ghost_ai/game/input/config 等 11 模块）。同时新增"r2 修复验证"小节，提供评审 #1 的针对性验证命令。

**验证证据**：本轮交付前实际运行结果——
```
Ran 99 tests in 0.053s
OK
```
退出码 0；评审 #1 修复后回归测试通过。

### 本轮未涉及项

- 评审 #1 中提到的 FR-03 地图三项离线判定、FR-04 输入缓冲、FR-10 四目标互异、FR-16 干净退出等，r1 已通过——r2 不重做，测试套件证据保留。
- 旧评审建议（pre-requeue 旧版的死代码清理，r1 已落实）——见 r1 README §11，本轮不重复。

## 12. 许可

本项目按需求方授权交付；如需开源可自由选择许可协议。
