# snake-linux 测试集（r1）

针对 `workspace/code/snake-linux/snake-linux-r1/` 的自动化测试。

## 运行方式

```bash
cd workspace/tests/snake-linux/snake-linux-r1
python3 -m pytest -q          # 单元测试（test_game_state / test_config / test_input）
python3 e2e_snake.py          # 端到端冒烟（TTY 环境）
```

## 覆盖（对照测试方案 testplan/snake-linux/snake-linux-r1.md）

| 文件 | 覆盖用例 |
|------|---------|
| test_game_state.py | 蛇移动/碰撞/食物生成/得分/状态机（RUNNING→OVER/WIN） |
| test_config.py | 命令行参数解析（tick/尺寸/非法值） |
| test_input.py | 键位输入映射（方向/退出/非法键） |
| e2e_snake.py | 非 TTY 降级、启动参数端到端冒烟 |

## 结果判定

- `pytest -q` 全部通过 = P0/P1 用例通过；
- 端到端在真实 TTY 下运行 `python3 snake.py` 人工冒烟（自动化仅覆盖非交互路径）。
