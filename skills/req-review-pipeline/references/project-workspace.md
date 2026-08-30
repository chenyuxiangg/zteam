# 项目工作路径解耦（项目映射表机制）——专项参考

> 合并自原 skill `zteam-project-workspace`。zteam 资产层（scripts/roles/docs，git 仓）与**项目数据层**物理解耦：项目数据在**用户指定工作路径**（默认 `~/project/{项目}/`）。**项目映射表 `zteam/projects.json` 是唯一真理源**——项目存在性/工作路径/最新版本都查它。

## 触发场景

- zbot/用户要**登记新项目、换工作路径、设默认项目、查项目信息**；
- 报「项目未登记」「需求投放没反应」「路径不对」类问题；
- 新需求投放前确认项目已登记（register 只扫映射表项目，未登记=静默不扫=强制先 add）；
- 版本 released 后确认 latest_version 已同步。

## 映射表结构（唯一真理源，写权限铁律）

```json
{"projects": [{"name": "snake-linux", "created_at": "ISO", "latest_version": "v2.0.0",
               "work_path": "/home/zyzs/project/snake-linux", "default": true}],
 "updated_at": "ISO"}
```

- **AI 禁止直接改 projects.json**；写操作只能经 `statectl project ...`（全局锁 + 审计 pipeline.log）；
- **用户明确**语义：zbot 场景必须用户确认后执行；命令行 = 用户直接执行（本身即明确）；
- 审计事件：`PROJECT_ADD / PROJECT_SETPATH / PROJECT_DEFAULT / PROJECT_RM / PROJECT_VERSION`。

## 命令族（statectl project）

| 命令 | 用途 | 备注 |
|---|---|---|
| `project list` | 全部项目（`{name} \| 最新 {v} \| {work_path} [默认]`）| **zbot /new 第一步必跑** |
| `project info {name}` | 单项目详情（成立/版本/路径/默认）| 只读 |
| `project add {name} {path?}` | 登记；路径缺省 `~/project/{name}` | 用户确认 |
| `project setpath {name} {path}` | 迁移工作路径 | 用户确认 |
| `project default {name}` | 设全局默认（唯一，自动清其他）| 用户确认 |
| `project rm {name}` | 仅解除登记，**不删数据** | 用户确认 |

校验（脚本强制）：项目名 `[A-Za-z0-9_-]`；work_path 必须**绝对路径**且**不能在 zteam 内部**（防污染 git 仓）。

## 路径解析（核心改造，方案 A 后：workspace/ 已移除）

```
project_dir(project) = 查 projects.json → work_path
                       未登记 → 回退 workspace/{project}（存量兼容路径，已无真实数据）
product_path(product) = 产物绝对路径查表解析（核心！）：
   '{project}/{dir}/...' → project_dir(project)/{dir}/...（release_*/产物校验全部走它）
   norm_product 先规范化（去 workspace/ 前缀/去绝对路径）再查表
register_new_inputs = 遍历映射表项目扫 {work_path}/input/*.md（未登记项目不扫 = 强制先 add）
                      + 存量兼容扫 workspace/{项目}/input（workspace 不存在时自然跳过）
confirm_guide 收口 → 自动 _sync_project_version 更新 latest_version（脚本守护）
```

**方案 A（workspace 彻底移除，2026-08-20 实测定稿）**：
- `workspace/` 已删除；`LOG_DIR = zteam/logs`（审计 pipeline.log/alarms.txt）、`LOCK_FILE = zteam/status.lock`（全局锁）——常量全在 zteam 根，`.gitignore` 忽略（`logs/`、`status.lock`）；
- `WORKSPACE_DIR` 常量保留仅为未登记项目回退路径（不再有真实数据）；
- **9 处产物存在性校验**（release_module/release_arch/release_testplan_v2/release_st_v2/release_qa/set_stage_state 等）从 `os.path.join(WORKSPACE_DIR, norm_product(product))` 改为 `product_path(product)`（查表）——**漏改会导致解耦后产物校验找错位置**（旧 workspace 路径不存在 → 校验误拒绝）；
- `cmd_versions`/diagnose 项目遍历改映射表；**所有 `os.listdir(WORKSPACE_DIR)` 必须加 `if os.path.isdir(...) else []` 保护**（workspace 不存在时直接 FileNotFoundError 崩溃，实测踩过 **6 处**）：diagnose D2/D9（2 处）+ **tick 全族**——`_tick_common` 阶段 2 项目遍历（**worker_tick 主循环，cron 每 5 分钟崩的根因**——用户收到 "Cronjob Response: ... Script exited with code 1" 失败通知即此信号）、`weekly_tick` 未登记 input 检查、`notify` 段 1.5（均改为映射表项目 + isdir 保护，循环体内路径用 `project_dir(proj)` 查表而非 workspace 拼接）；改完跑全部 `scripts/watchdog-*.py` 复测（worker/weekly/notify/quota/analyst/reviewer 全 exit=0）——**注意真实命令名是 `weekly_tick`/`notify`/`worker_tick`**（不是 weekly_audit 之类）；
- 产物路径存相对形式（`{project}/release/{version}/`、`{project}/design/...`），绝对路径解析统一走 product_path。

## 诊断语义（diagnose，方案 A 实测定稿）

| 检查项 | 判定 |
|---|---|
| D1 status.json | 无全局 status.json 属正常：映射表项目全未投放 → **INFO**「首次投放自动创建」；有已投放项目却缺 → FAIL |
| D2 work_path 不存在（未投放）| **WARN**「工作路径未创建——首次投放需求时自动创建」|
| D2 有 input 但缺其他标准目录 | **FAIL**（结构损坏）|
| D2 标准目录全建 | PASS |
| D2 logs | 检查 `LOG_DIR`（zteam/logs），不是旧 `workspace/logs` |
| 遍历 workspace 的任何循环 | workspace 不存在必须不崩（isdir 保护）|

## zbot 交互铁律（bot.md 已固化）

1. **/new 新会话第一步（强制）**：执行 `project list` 获取全部项目（含默认/版本/路径）供用户选择——禁止跳过；
2. **用户未指定项目**：必须提示默认项目——"当前默认项目是 {name}（最新 v{version}），在该项目下开发吗？"；无默认则列全部项目请用户选；
3. **项目操作需用户明确确认后执行**，执行后报告脚本返回；
4. **需求投放路径**：`{work_path}/input/{req_id}.md`（查 project list/info，不得用 workspace 旧路径）。

## worker cwd 改造（2026-08-20，解耦后 spawn 正确性关键）

- **`spawn_worker` cwd = `project_dir(project)`（work_path）**——worker 的相对产物路径自动落在项目工作路径（原 cwd=zteam 根会把产物写进 zteam/ 污染资产层——解耦后必须改）；
- **worker 指令模板全部绝对引用**（worker cwd 已不在 zteam）：`遵循/按 roles/{角色}.md` → `遵循 {WORKDIR}/roles/{角色}.md`（f-string 展开，19 处）、`scripts/statectl.py` → `{WORKDIR}/scripts/statectl.py`（40 处）；`ROLE_FILES` 值单独绝对化（`f"{WORKDIR}/roles/pm.md"`）；
- **批量 replace 的污染坑**：`roles/x.md` 子串同时出现在 ROLE_FILES 值和指令模板里——用带上下文的模式替换（"遵循 roles/" / "按 roles/" 前缀），ROLE_FILES 单独处理，避免二次替换；
- **非 f-string 帮助文本会留 `{WORKDIR}` 字面**（不展开）——replace_all 后必须检查（含 `{WORKDIR}` 且行首不是 `f"` 的行），转 f-string 或还原相对路径；
- 验证：mock Popen 捕获 cmd——**query 在 `cmd[3]`**（`["hermes","chat","-q",query,...]`，`cmd[2]` 是 `-q`）；直接调 `spawn_worker` 传自组 query 是**误导**（绝对化发生在调度指令模板里，spawn_worker 不改 query）——要走**真实调度链路**（构造触发状态如 planning+approved → 调 `_schedule_arch_te` → 断言 `cmd[3]` 含绝对引用）+ 源码级断言（count 绝对引用、无字面残留）。

## 并发会话改坏 work_path 数据 → 伪 pending 调度（实测排查模式）

信号：**已 released 的需求/版本又被 spawn worker**（如 snake-linux v1.0.0 已 released 却出现 PM worker）、`REGISTER` 连续重复（同 key 每 tick 注册）。

排查链（按序）：
1. `ps aux | grep "hermes chat"` 看活动 worker 指令（哪个需求/角色）；
2. `grep -E "REGISTER|SPAWN" logs/pipeline.log | tail`（重复 REGISTER = status.json 无此 key，每 tick 从 input 重新注册）；
3. **对照 work_path 数据**：`input/` 文件 vs `versions.json` reqs vs `status.json` 条目——**三者不一致 = 数据被外部改过**（实测：并发会话迁移旧数据时把 `versions.json` v1.0.0 改成 `planning` + 重挂已 released 需求、`status.json` 清空 → tick 把"伪 pending"当新需求调度）；
4. 处理：杀掉错误 worker（`kill <pid>`，**勿用 `pkill -f "hermes chat"`——模式过宽会误杀自己的 shell**）、数据从备份恢复（`~/cyx/zteam-workspace-backup-{日期}/`）或按用户意图重建、确认并发会话是否还会写。

根因：解耦后 work_path 在 zteam 外，**并发会话/tick 之外的写入方都可能改它**——版本/需求状态异常先查 work_path 数据一致性，别急着改调度逻辑。

## 目录/路径迁移全引用点扫描（含脚本骨架——两次踩坑）

删目录/改路径后**必须 grep 全部引用点**，且**不只代码——install/uninstall 脚本的骨架创建也要查**：
- 方案 A 删除 `workspace/` 后，`install.sh` 31-33 行仍 `mkdir -p "$WORKSPACE/workspace"/logs` + touch status.lock——**每次跑 install 都重建 workspace/**（用户问"为什么还有 workspace"才发现的漏网）；
- 同理 `_tick_common`（worker_tick 主循环）/`weekly_tick`/`notify`/diagnose 的 `os.listdir(WORKSPACE_DIR)` 无 isdir 保护 → cron 每 5 分钟崩（用户收到 "Script exited with code 1" 即此信号）；
- **grep 清单**：`listdir(WORKSPACE_DIR)`（全部）、`os.path.join(WORKSPACE_DIR`、`mkdir.*workspace`（install/uninstall）、文档中的 `workspace/` 路径描述；
- 改完复测全部 `watchdog-*.py` exit=0 + `bash -n install.sh uninstall.sh` + diagnose 全绿。

## 存量迁移流程（一次性，实测）

```
1. 备份：cp -a zteam/workspace/ → ~/cyx/zteam-workspace-backup-{日期}/（含未跟踪 logs/status.db）
2. 登记：project add {4 项目}（默认 ~/project/{name}）；latest_version 从备份 versions.json 读 released 版本补填
3. 清空：git rm -r workspace/{项目}（项目数据移出 git 仓）；rmdir 残留空目录（未跟踪 logs 等）
4. 验证：diagnose 全绿 + project list 正确 + 新投放走 work_path
```

## uninstall.sh --full 适配（方案 A 后）

- `--full` 不再 `rm -rf workspace/`：改为读 `projects.json` → 清空各项目 work_path 目录（`shutil.rmtree`，安全校验 isabs 且 != "/"）+ 登记清空（`{"projects": []}`）；保留 zteam/logs 审计与 status.lock；
- 内嵌 python 段做清空（heredoc），与 `statectl project` 命令族一致走 projects.json 读数据。

## 验证要点（零 token）

- 副本隔离：`cp -r $SRC w && rm -rf workspace && rm -f projects.json`（**必须删副本 projects.json**，否则真实映射表/路径被副本测试读到）；
- 场景隔离：**每组场景独立副本目录**（同副本多组场景时 projects.json 等共享状态跨 heredoc 持久，broken 项目会拖垮后组断言——先 `project rm` 或重建副本）；
- 断言：命令族增删改查/校验拒绝（zteam 内部/相对路径/非法名/重复/未登记）/审计事件/work_path 注册/confirm_guide 同步/诊断三态；
- 真实环境只读回归：诊断 0 严重 + 映射表字段断言。
