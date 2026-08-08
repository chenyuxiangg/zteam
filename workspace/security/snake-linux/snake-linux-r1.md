# 安全红线门禁：snake-linux（r1）

## 0. 门禁结论
- 结论：**PASS**
- 一句话理由：纯本地终端游戏，零网络/文件/凭据/第三方依赖，8 条红线全部 PASS
- 轮次：r1

## 1. 红线清单核对表
| # | 红线项 | 结论（PASS/FAIL） | 依据（代码位置/依赖/配置） |
|---|--------|------------------|---------------------------|
| 1 | 注入类 | PASS | 无 shell 命令执行（无 os.system/subprocess/eval/exec）；CLI 参数经 argparse + _tick_type/_dim_type 类型校验（snake.py L202-L221），不接受任意字符串拼接；无文件路径构造与外部输入拼接 |
| 2 | 敏感数据 | PASS | 无硬编码密钥/Token/密码；无文件读写（无凭据持久化）；无网络通信；stderr 输出为固定中文提示（snake.py L227-L229），不含用户数据或凭据 |
| 3 | 权限与越权 | PASS | 普通用户权限运行，无需 root；仅操作 stderr/stdout + curses 终端控制，不写系统路径；无授权检查面（无账户/无访问控制需求） |
| 4 | 输入校验 | PASS | CLI：tick 严格限制 50–1000 整数（_tick_type，L202-L211），宽/高 ≥ 10 整数（_dim_type，L214-L221），非法参数 argparse 以 exit 2 + 中文报错退出；键盘输入：InputHandler.direction_for 对未知键返回 None（L138-L140），不崩溃；渲染：_safe_add 捕获 curses.error 防止 resize 竞态崩溃（L190-L193）；turn() 方向校验（L85-L96）含反向/双键禁止 |
| 5 | 资源安全 | PASS | 食物生成：空闲格列表方案，空闲为空置 WIN 状态（_spawn_food，L125-L136），无死循环风险；主循环：state.status != RUNNING 即退出（L260）；_handle_resize：尺寸不足待恢复循环含 q 退出路径（L245-L257）；内存：蛇身 deque 上限 = 画布格数（max 40×20=800），无界增长 |
| 6 | 依赖安全 | PASS | 仅 Python 标准库（argparse/curses/random/signal/sys/time/collections），零第三方依赖（snake.py L28-L31）；标准库随 Python 发行版维护，无独立 CVE 面 |
| 7 | 执行环境 | PASS | 无 rm -rf/格式化/系统级修改操作；sys.exit 仅退出自身进程（exit 0/1/2/3/130）；curses.wrapper 保证 finally 恢复终端（FR-14），SIGTERM handler 走与 Ctrl+C 同路径（_sigterm_handler，L260-L262）；无需沙箱（无网络/文件 I/O） |
| 8 | 供应链 | PASS | 交付物仅 snake.py + README.md（code/snake-linux/snake-linux-r1/）；代码无硬编码路径/凭据/内网地址；README 为纯文档无敏感信息；__pycache__ 为编译缓存不含源码级机密 |

## 2. 审查范围
- **代码**：`workspace/code/snake-linux/snake-linux-r1/snake.py`（380 行，全部类/函数逐行审查）
- **文档**：`workspace/code/snake-linux/snake-linux-r1/README.md`
- **依赖清单**：Python 标准库 argparse / curses / random / signal / sys / time / collections（deque, namedtuple）——零第三方依赖
- **参考产物**（非审查对象，用于理解上下文）：
  - 需求原文：`workspace/input/snake-linux/snake-linux.md`
  - 需求分析（approved）：`workspace/analysis/snake-linux/snake-linux-r2.md`
  - 开发方案：`workspace/plans/snake-linux/snake-linux-r1.md`
  - 测试方案：`workspace/testplans/snake-linux/snake-linux-r1.md`
  - 质量门禁：`workspace/quality/snake-linux/snake-linux-r1.md`

## 3. 问题清单
- 无。全部 8 条红线 PASS，未发现任何注入/敏感数据泄露/越权/依赖漏洞/资源泄露等安全问题。

## 4. 门禁判定
- PASS：本需求为纯本地 Linux 终端游戏，零网络通信、零文件读写、零第三方依赖、零凭据面，攻击面极小。代码输入校验充分（argparse 类型校验 + 键盘安全映射 + 渲染越界防护），资源使用有界（deque 上限为画布格数，食物生成无死循环），退出路径经 curses.wrapper 保证终端恢复。无任何红线命中，可以进入发布阶段。
