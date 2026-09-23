"""zteam 流水线状态机核心包。

按职能切分为多个子模块：
    paths        — 路径常量、项目映射 CRUD、相对路径工具
    status       — 状态文件读写、flock、日志、now_iso
    model_config — 角色模型/文件/中文名 + *_MODEL 环境变量
    pipeline     — 状态机 STAGES/GATES/RELEASE + 阶段流转/claim/spawn
    release      — 下半部 release_analyze/release_review/...
    versions     — versions.json + release_it/release_st/...
    modules      — modules.json + cmd_module/release_module/...
    qa           — release_qa/release_st_case/confirm_guide/...
    issues       — issue 文件 CRUD + cmd_issue
    resources    — 资源解阻 + 配额检查
    ticks        — 上半部 quota_tick + analyst/worker/weekly 等
    diagnose     — 一键健康检查
    commands     — 人工命令 cmd_* + main() 派发表（commit 6 完成）

`scripts/statectl.py` 是 5 行 thin shim，转发到 `main()`；外部入口不变。
"""

from .commands import main
from .ticks import quota_tick
from .diagnose import diagnose

__all__ = ["main", "quota_tick", "diagnose"]
