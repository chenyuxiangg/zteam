# 安全红线门禁：gomoku/gomoku（r1）

## 0. 门禁结论
- 结论：**PASS**
- 一句话理由：纯本地单机应用，无注入面/无硬编码凭据/输入三重校验/依赖仅 rich，8 条红线全 PASS。
- 轮次：r1

## 1. 红线清单核对表
| # | 红线项 | 结论（PASS/FAIL） | 依据（代码位置/依赖/配置） |
|---|--------|------------------|---------------------------|
| 1 | 注入类 | PASS | 无 `os.system`/`subprocess`/`eval`/`exec` 调用；用户输入仅经 `parse_move()` 正则解析（board.py:68-103）后做索引，无 shell 拼接、无路径操作、无代码注入面；CLI 参数由 `argparse` choices 约束（config.py:76-113） |
| 2 | 敏感数据 | PASS | 全量代码搜索无硬编码密钥/Token/密码；无日志输出（无 logging 模块使用）；纯本地运行无敏感数据传输/存储需求 |
| 3 | 权限与越权 | PASS | 无认证/授权体系；无 `sudo`/`os.setuid`/提权调用；无系统目录写入；单用户单进程模型，无越权访问面 |
| 4 | 输入校验 | PASS | 坐标输入三重校验：正则格式匹配→范围检查（board.py:68-103, MoveError）→占用检查（ui.py:202-207）；CLI 参数 `argparse` choices 白名单约束（config.py:76-113）；Board size 5..25 校验（board.py:129-133）；100 次 fuzz 无崩溃（quality 门禁已验证） |
| 5 | 资源安全 | PASS | AI 搜索 1.5s 时间硬约束（ai.py:56-66, `_SearchBudget.is_expired`）+ 迭代加深降级链（候选 20→12、深度 4→1）；所有循环均受棋盘 size 边界限制（最大 25×25=625 格）；无文件句柄/网络连接；单线程无泄漏风险 |
| 6 | 依赖安全 | PASS | 唯一运行时依赖 `rich>=13.0`（Textualize 维护，57k+★，PyPI 官方源）；开发依赖 `pytest>=7.0`/`pexpect>=4.8` 仅 dev extras；无来历不明/不可信依赖；rich 为终端渲染库，攻击面极小且无已知高危 CVE |
| 7 | 执行环境 | PASS | 无 `rm -rf`/格式化/系统级修改；不提权；`Ctrl+C` → `KeyboardInterrupt` 顶层捕获安全退出（main.py:55-57）；`SystemExit(0)` 处理 quit 命令（ui.py:197-198）；无需沙箱（纯 Python 进程） |
| 8 | 供应链 | PASS | pyproject.toml 干净：MIT 许可证、Homepage 指向实际 GitHub repo、依赖声明清晰；包仅含 .py 纯源码（无二进制 blob/预构建产物）；`__version__="0.4.0"` 显式声明；无内部路径/凭据泄露 |

## 2. 审查范围
- **源码**（逐文件审查）：
  - `gomoku/__init__.py` / `__main__.py` — 包入口，无安全面
  - `gomoku/config.py` — CLI 参数白名单约束，无注入
  - `gomoku/board.py` — 纯逻辑引擎：坐标解析（正则+范围）、落子校验（bounds+color+occupied）、胜负/禁手判定，无 I/O/无注入面
  - `gomoku/ai.py` — AI 决策：时间预算约束、禁手预过滤、Alpha-Beta 搜索，无外部调用
  - `gomoku/ui.py` — rich 终端渲染+输入循环：三重输入校验、Ctrl+C 安全退出、终端恢复
  - `gomoku/main.py` — 主控：回合循环、异常捕获、安全退出
- **依赖清单**：`pyproject.toml` — 仅 `rich>=13.0`（运行时），`pytest`/`pexpect`（dev）
- **配置/打包**：`pyproject.toml`、`py.typed` — 标准打包，无多余内容
- **测试代码**（抽查）：
  - `tests/gomoku-r1/tests/` — test_board/test_forbidden/test_ai/test_ui/test_integration，未发现测试代码引入安全风险

## 3. 问题清单
- **[建议]** `ui.py:227` 使用 `shutil.get_terminal_size()` 确定终端尺寸，该值为环境/OS 提供，非用户可控路径——无路径穿越风险，仅做提示用途。
- **[建议]** `ai.py` 中 `_evaluate_color` 的 over-counting 为有意设计（quality 门禁已记录），不影响安全。
- 无严重/一般安全问题。

## 4. 门禁判定
- PASS：8 条安全红线逐项审查全部通过。本需求为纯本地单机五子棋游戏，无网络通信、无外部 API、无用户数据持久化、无认证鉴权体系——攻击面天然极小。代码实现严格遵守 plan §5.5 安全承诺：不联网、不写系统目录、不提权、不 eval/exec 用户输入、坐标输入三重校验后才索引棋盘。依赖面仅 rich 一个成熟终端渲染库。放行进入发布阶段。
