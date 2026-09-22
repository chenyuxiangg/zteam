"""zteam 流水线状态机核心包。

按职能切分为多个子模块：
    paths        — 路径常量、项目映射 CRUD、相对路径工具
    status       — 状态文件读写、flock、日志、now_iso
    model_config — 角色模型/文件/中文名 + *_MODEL 环境变量
    pipeline     — 状态机 STAGES/GATES/RELEASE + 阶段流转/claim/spawn
    release      — 下半部 release_analyze/release_review/...
    versions     — versions.json + release_it/release_st/...
    modules      — modules.json + cmd_module/release_module/...
    issues       — issue 文件 CRUD + cmd_issue
    qa           — release_qa/release_st_case/confirm_guide/...
    resources    — 资源解阻 + 配额检查
    commands     — 人工命令 cmd_*
    ticks        — 上半部 analyst_tick/reviewer_tick/worker_tick/...
    diagnose     — 一键健康检查

`scripts/statectl.py` 是薄 CLI shim，转发到 `main()`；外部入口不变。
"""

__all__: list[str] = []