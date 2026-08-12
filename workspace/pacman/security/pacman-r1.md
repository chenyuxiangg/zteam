# 安全红线门禁：pacman/pacman（r1）

## 0. 门禁结论
- 结论：**PASS**
- 一句话理由：零第三方依赖/零网络/零文件写入/输入全面校验，8 项红线全部通过，无安全问题。
- 轮次：r1

## 1. 红线清单核对表
| # | 红线项 | 结论（PASS/FAIL） | 依据（代码位置/依赖/配置） |
|---|--------|------------------|---------------------------|
| 1 | 注入类（命令/路径/代码） | PASS | 无 shell 命令执行（grep subprocess/os.system 为空）；`--map` 路径由 argparse 接收并仅用于 `open(path)`，合法性由 map.py 校验链拦截（load_map → _parse_grid → _check_basic → _check_house_enclosed → _validate_connectivity），非法路径/格式/内容均 exit 1 报错不进入游戏；无 eval/exec；sys.exit 仅用整数码 |
| 2 | 敏感数据（密钥/Token/日志泄露） | PASS | 零硬编码凭据（全代码 grep 无 token/key/secret/password 字样）；--log-ai 输出仅含游戏状态（玩家坐标/方向、幽灵名/模式/目标格），无个人信息；NFR-06 零网络设计（零 connect/sendto）；无持久化文件写入（Q7 不做最高分） |
| 3 | 权限与越权 | PASS | 单机本地游戏，无用户认证/授权模型；无 sudo/setuid；不创建/修改系统文件；仅读取 `--map` 指定的地图文件 |
| 4 | 输入校验 | PASS | CLI 参数全量校验：--ghosts 2/3/4、--lives 1-9、--level ≥1、--speed 0.5-2.0，非法值 exit 2（main.py:69-80）；`--map` 路径经 map.py 完整校验链（文件存在/行宽一致/字符集合法/出生点/能量豆≥4/豆总数≥100/连通性 BFS/鬼屋封闭/门连通）→ 不通过 exit 1；键盘输入经 keycode_to_str + parse_key 白名单映射，非法键返回 Action.NONE 静默忽略（input.py）；终端尺寸 <80×24 居中提示退出不崩溃（renderer.py:191-194）；非 TTY 报错退出（main.py:96-101） |
| 5 | 资源安全 | PASS | curses.wrapper 保障异常路径终端状态恢复（main.py:216-217 + renderer.py -- 异常/KeyboardInterrupt/正常返回均恢复）；主循环 sleep(max(0, 0.1-dt)) 防 CPU 空转（main.py:188-190）；Mover 速度累积 acc 上限 4.0 + 单 tick 最多 4 步（entities.py:68/79-80）；地图尺寸由 BFS 自然上限（map.py:230-253）；文件操作均 with 语句（map.py:145）；无无限循环/递归无界 |
| 6 | 依赖安全 | PASS | 零 pip 第三方依赖（requirements.txt 空列表）；全部使用 Python 标准库（curses/argparse/collections/dataclasses/enum/time/random/os/sys）；curses 缺失会提前报错退出（main.py:102-106 / renderer.py:34-40） |
| 7 | 执行环境 | PASS | 无 rm/format/系统级修改；无 os.system/subprocess/shell；无文件删除操作；仅标准库文件读取 + 终端渲染；无权限提升 |
| 8 | 供应链 | PASS | 产物无凭据/内部路径泄露；DEFAULT_MAP 为相对路径 "data/map_classic.txt"（config.py:181）；README 无敏感信息；发布物将在 release 阶段产出（security 门禁时点无打包产物需检查） |

## 2. 审查范围
审查了 code 阶段全部 9 个源文件 + 1 个数据文件 + 1 个依赖声明：
- `pacman/main.py`（入口/CLI/主循环）
- `pacman/config.py`（常量/默认值/难度公式）
- `pacman/map.py`（地图加载/三项离线判定）
- `pacman/entities.py`（Player/Ghost/Mover）
- `pacman/ghost_ai.py`（四幽灵目标/决策/模式状态机）
- `pacman/game.py`（对局状态机/碰撞/计分）
- `pacman/input.py`（键位映射）
- `pacman/renderer.py`（curses 渲染）
- `pacman/__main__.py` / `run.py`（入口薄壳）
- `pacman/data/map_classic.txt`（内置地图）
- `requirements.txt`（依赖声明）

审查方法：逐文件阅读全部源码（~2300 行）+ grep 安全关键字（socket/urllib/requests/subprocess/os.system/shutil/eval/exec）+ 依赖面核查。

## 3. 问题清单
本轮无安全问题。以下为信息项（非问题，不阻塞发布）：
- **【信息】** `--map` 参数允许用户加载任意本地文件路径（含绝对路径/.. 穿越）。此为单机本地游戏设计意图（FR-03 地图可配置），加载前经 map.py 校验链拦截非法地图，不存在通过地图文件实现代码注入的向量。用户需自行管理地图文件来源可信性。
- **【信息】** `--log-ai` 输出写入 stderr，格式为游戏数据（玩家坐标/幽灵目标格），不涉及用户隐私。stderr 不可写时降级静默（main.py:180-182）。
- **【信息】** requirements.txt 为空（零 pip 依赖），curses 为 Python 标准库。极简发行版缺少 _curses 时 `apt install python3-curses` 为系统包安装（非 pip，不影响依赖安全面）。

## 4. 门禁判定
- PASS：8 项安全红线全部通过。代码不含网络行为（NFR-06 已验证 network_calls=0）、不含 shell 执行、不含硬编码凭据、不含危险文件操作；输入面（CLI 参数/地图文件/键盘）均有完整校验链；终端状态恢复由 curses.wrapper 保证；零第三方依赖消除供应链风险。可进入发布阶段。
