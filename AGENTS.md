# zteam 流水线约定（下半部 worker 自动加载）

你是本流水线的**下半部 worker**：执行已被上半部认领的需求分析、阶段产出或评审任务。

## 开工前必读

1. 你的启动指令（`hermes chat -q` 的 query）会指明：角色（分析师/评审师/方案设计者/代码开发者/…）、需求 id（`<project>/<req_id>`）、阶段与轮次（`N`）；
2. 先阅读对应角色文件（`roles/*.md`，指令里会给出路径），**严格遵循**其中的输出模板与工作原则；
3. 文件布局、状态机、命名规则、claim 字段语义：`docs/state-machine.md`。

## 目录结构（资产层 / 数据层）

```
zteam/                     # 资产层（git 跟踪）
├── roles/  docs/  scripts/     # 角色定义 / 文档 / 代码
└── workspace/                  # 数据层（运行数据，按项目组织）
    ├── status.json             # 状态机（唯一事实来源；key = <project>/<req_id>）
    ├── input/<project>/<req_id>.md        # 需求投放区
    ├── analysis/ review/                 # 需求分析与评审
    ├── plans/ testplans/ code/ tests/    # 阶段链产物（方案/测试方案/代码/测试）
    ├── quality/ security/ release/       # 门禁结论 / 发布说明
    ├── artifacts/<project>/<req_id>.md   # 归档（结论摘要 + 最终分析 + 阶段产物 + 评审历史）
    └── logs/                   # pipeline.log（审计）+ worker-*.log（下半部明细）
```

## 完成标志（三件套，缺一不可）

1. **产物落盘**：按指令写 `workspace/{阶段目录}/{project}/{req_id}-r{N}.md`（每轮新文件，不覆盖旧版本）；
2. **调用状态机 release 命令**（状态迁移由 `scripts/statectl.py` 完成，禁止手改 status.json）：
   - 需求分析：`release_analyze {key} {产物}`（`analyzing → analyzed`）；
   - 需求评审：`release_review {key} {产物} PASS|FAIL`（`reviewing → approved|needs_fix`）；
   - 阶段产出：`release_stage_design {key} {stage} {产物}`（`{stage}_designing → {stage}_reviewing`）；
   - 阶段评审：`release_stage_review {key} {stage} {产物} PASS|FAIL`（`{stage}_reviewing → {stage}_done` / 重做）；
   - 门禁评审：`release_gate {key} {stage} {产物} PASS|FAIL`（quality/security）；
   - 发布：`release_release {key} {发布说明}`（`releasing → released`，生成最终交付物归档）；
   - release 会自动清空 claim 字段、写审计日志、按 max_rounds 处理强制归档/blocked；
3. **审计日志**：release 命令自动写入 `workspace/logs/pipeline.log`（格式见 `docs/state-machine.md` 第 10 节），无需手动追加。

## 失败时

- 若在写产物前决定放弃本轮：运行 `python3 scripts/statectl.py rollback {project}/{req_id}`（自动 `failures + 1` 并回到该阶段可认领状态）；
- 若进程直接崩溃、没来得及处理：保持中间态原样即可——上半部 stale 恢复会自动兜底（见 `docs/state-machine.md` §7.2）；
- 无论何种失败，把你的 stdout 留在 `workspace/logs/worker-{project}-{req_id}-r{N}.log` 中供人工排查。

## 禁止

- 不得修改需求原文（`workspace/input/` 下的文件）；
- 产出者不得评审自己的产物；评审者不得修改产物；
- 不得跳过状态（如直接 `pending → approved`）。
