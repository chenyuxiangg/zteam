# 代码评审：pacman（r1）

## 0. 评审结论
- 结论：**FAIL**
- 一句话理由：玩家移动未校验墙体，可直接穿墙，核心玩法不正确。
- 评审轮次：r1

## 1. 检查清单核对表
| # | 检查项 | 结论（PASS/FAIL） | 依据/缺失说明 |
|---|--------|------------------|--------------|
| 1 | 方案符合性 | FAIL | `pacman/game.py:159-164` 未落实方案的“移动前检查下一格可通行”；玩家移动直接调用 `add_motion()`。 |
| 2 | 可运行 | PASS | `python3 -m compileall -q workspace/pacman/code/pacman-r1` 退出码 0；`python3 -m pacman --help` 正常；内置地图成功加载为 19×22、216 豆。 |
| 3 | 功能正确性 | FAIL | FR-05“墙体碰撞/不可穿墙”失败；测试套件 99 项中 1 项失败：`tests.test_game.TestMovement.test_player_cannot_walk_wall`。 |
| 4 | 边界与异常 | FAIL | 墙体边界未在移动入口处理，玩家从 `(7,8)` 朝上可进入不可通行墙格 `(6,8)`。 |
| 5 | 安全与合规 | PASS | 纯本地标准库实现，未发现网络、敏感数据或权限操作；CLI 参数与地图加载存在显式校验。 |
| 6 | 可读可维护 | PASS | 模块职责、命名和文档较清晰；本轮已清理既有死代码样式。 |
| 7 | 错误处理 | PASS | CLI、非 TTY、curses 缺失和地图错误均有明确反馈及退出语义。 |
| 8 | 性能与资源 | PASS | 逻辑规模小，使用 `curses.wrapper` 恢复终端；未发现明显资源泄漏。 |
| 9 | 不越界 | PASS | code 目录未混入测试产物，未修改需求、方案和测试方案。 |
| 10 | 可审计 | PASS | 产物位于独立 r1 目录；README §11 对旧评审建议逐条回应。 |

## 2. 评审意见列表
1. **[严重]** 玩家移动可穿越墙体，违反核心移动规则（`pacman/game.py:159-164`、`pacman/entities.py:49-64`）。
   - 依据：需求 FR-05 要求玩家不能穿过墙体；开发方案要求移动前检查下一格可通行；自动化用例 `workspace/pacman/tests/pacman-r1/tests/test_game.py:251-260` 实测失败。
   - 复现：将玩家置于 `(7,8)`、方向设为 `Dir.UP`，`gm.is_passable_for_player(6,8)` 为 `False`，调用 `Game.tick()` 后位置却由 `(7,8)` 变为 `(6,8)`。
   - 修改要求：在玩家每一步位移前调用 `GameMap.is_passable_for_player(next_row, next_col)`；不可通行时保持原位置，不得先进入墙格再回退。若一次 tick 未来支持多步，应逐步校验每个中间格。修复后运行完整测试并确保 `test_player_cannot_walk_wall` 通过。

2. **[一般]** README 的开发者自检未包含完整测试套件命令，因此自检显示“ready”时无法发现上述核心回归（`README.md:155-240`）。
   - 依据：本次按正确测试入口 `PYTHONPATH=../code/pacman-r1:. python3 -m unittest discover -s tests -t . -v` 运行 99 项，结果 98 通过、1 失败。
   - 修改要求：代码修复后，在 README 自检节增加可复现的完整测试命令和预期结果，并避免仅用编译、CLI help、零散脚本替代回归测试。

## 3. 遗留事项（仅 PASS 时）
- 不适用（本轮结论 FAIL）。
