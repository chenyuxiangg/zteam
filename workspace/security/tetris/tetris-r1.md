# 安全红线门禁：tetris/tetris（r1）

## 0. 门禁结论
- 结论：**PASS**
- 一句话理由：8 项安全红线全部 PASS，零第三方依赖、无网络/文件 I/O、无凭据，攻击面极小。
- 轮次：r1

## 1. 红线清单核对表
| # | 红线项 | 结论（PASS/FAIL） | 依据（代码位置/依赖/配置） |
|---|--------|------------------|---------------------------|
| 1 | 注入类 | PASS | 命令行仅 `--tick`（argparse type=int + [50,2000] 范围校验，tetris.py:173）和 `--no-color`（store_true 布尔，tetris.py:168-171）。无 shell 命令拼接（未使用 os.system/subprocess），无路径拼接（零文件 I/O），无 eval/exec。键盘输入经 InputHandler.KEYMAP 字典白名单映射（tetris.py:403-418），无效键直接忽略返回 None，不存在注入面。 |
| 2 | 敏感数据 | PASS | 无网络通信、无文件读写、无凭据。代码中无硬编码密钥/Token/密码（全文搜索 zero hits）。仅 stderr 输出可读错误信息（`_write_stderr`，tetris.py:141-146），无敏感信息泄露风险。 |
| 3 | 权限与越权 | PASS | 纯本地单用户终端游戏，无用户系统、无鉴权、无角色。仅需普通用户终端权限（stdin/stdout isatty），不要求 root/sudo，不访问系统路径或特权文件。无越权面。 |
| 4 | 输入校验 | PASS | ①命令行：`--tick` argparse int 类型校验 + [50,2000] 范围校验（tetris.py:173-174），越界/非数字 → argparse.error 可读提示 exit 2；②终端尺寸：`Renderer.size_ok()` 检查 COL≥42 与 LINES≥26（tetris.py:468-471），不足则提示退出 exit 3；③键盘：InputHandler.KEYMAP 白名单映射，无效键返回 None 被主循环忽略（tetris.py:403-418）；④绘制越界：`_put_cell` 捕获 curses.error 防 resize 竞态崩溃（tetris.py:488-490）；⑤碰撞检测：`collides` 对 x<0、x≥cols、y≥rows、wy≥0 全面边界检查（tetris.py:219-228），无 IndexError 面。 |
| 5 | 资源安全 | PASS | 单线程、无后台任务。场地固定 10×20（tetris.py:111-112），board 尺寸恒定无动态增长。主循环 timeout(25) 非阻塞轮询，无忙等（tetris.py:583）。`hard_drop` while 循环上限 20 次（场地高度），可证明终止（tetris.py:359-360）。无文件句柄/网络 socket 泄漏面（全程零 open/socket 调用）。内存占用恒定（RSS r1 实测峰值 17.3MB，远低于 50MB）。 |
| 6 | 依赖安全 | PASS | **零第三方依赖**，仅 Python 3.6+ 标准库：argparse, curses, os, random, signal, sys, time, collections.namedtuple（tetris.py:34-41）。curses 是 CPython 官方标准库自带模块（Python HOWTO 认证），无供应链风险。test 侧依赖（pytest/pexpect/pyte）仅安装于测试环境，不影响交付物。 |
| 7 | 执行环境 | PASS | 无危险系统操作：未使用 os.system/subprocess/rm/shutil.rmtree，未访问 /dev、/proc、/sys 等系统路径。唯一系统调用为 `os.write(2, ...)` 写 stderr（tetris.py:144）和 `os.environ.get('TERM')` 读环境变量（tetris.py:191），均为只读/安全操作。`signal.signal(SIGTERM, ...)` 注册 handler 抛 KeyboardInterrupt 走同一干净退出路径（tetris.py:568-569, 674），无残留风险。`curses.wrapper()` 提供 finally 级终端状态恢复（tetris.py:678）。全过程无需 root，无需沙箱。 |
| 8 | 供应链 | PASS | 交付物仅 tetris.py + README.md（code r2 目录）。源码中无凭据、无内部 IP/主机名、无构建产物残留。README 中引用的工作区路径（如 `plans/tetris/tetris-r2.md`）均为相对文档引用，非代码执行路径。`__pycache__/` 目录含 .pyc 编译缓存（CPython 标准行为），无信息泄露。 |

## 2. 审查范围
- 源码：`code/tetris/tetris-r2/tetris.py`（687 行，逐文件审查：配置解析/终端检查/方块定义/旋转/碰撞/消行/游戏状态机/输入映射/渲染/主循环/信号处理/入口）
- 文档：`code/tetris/tetris-r2/README.md`（184 行）
- 需求/分析/方案/测试方案/质量门禁：全量通读（核实无安全相关遗漏项）
- 依赖清单：从 import 语句与 README「依赖」节核实（仅标准库，零第三方）
- 测试文件：抽查 `test_game_state.py`/`test_tetrominoes.py`/`test_config.py`/`test_input.py`（确认测试代码本身无安全风险）

## 3. 问题清单
无问题。8 项红线全部 PASS。

质量门禁遗留的 1 个一般问题（system_checklist.md 人工清单未填写，TC-S-01 人工部分）属测试完备性范畴，不涉及安全，不阻塞安全门禁。

## 4. 门禁判定
- PASS：本需求为纯本地终端游戏，零网络、零文件 I/O、零第三方依赖、零凭据，攻击面极小。代码中所有外部输入面（命令行参数、键盘输入、终端尺寸）均有白名单/范围校验或安全忽略处理；无任何命令注入、路径穿越、权限提升、资源耗尽面；依赖全部来自 Python 标准库（供应链风险为零）；进程退出路径全面覆盖（q/Ctrl+C/SIGTERM）且终端状态由 `curses.wrapper()` 保证恢复。可进入发布阶段。
