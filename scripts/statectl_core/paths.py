"""路径常量与项目映射。

本模块只负责：路径常量定义、项目映射表读写（projects.json）、
key 解析（split_key）、相对路径工具。所有依赖 STAGES 配置的阶段
流转函数（stage_cfg/stage_after/next_action）见 pipeline.py。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# ---- 路径常量（zteam 根 = 本文件的父的父；realpath：兼容 ~/.hermes/scripts/ 符号链接调用） ----
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))       # scripts/statectl_core/
_SCRIPTS_DIR = os.path.dirname(_THIS_DIR)                    # scripts/
WORKDIR = os.path.dirname(_SCRIPTS_DIR)                      # zteam/
WORKSPACE_DIR = os.path.join(WORKDIR, "workspace")           # 兼容回退（未登记/旧数据）
LOG_DIR = os.path.join(WORKDIR, "logs")                      # 全局日志（跨项目审计）
SCRIPTS_DIR = _SCRIPTS_DIR                                   # 别名（保留原拼写）
STATUS_FILE = os.path.join(WORKSPACE_DIR, "status.json")     # 兼容引用（实际按项目分文件）
LOCK_FILE = os.path.join(WORKDIR, "status.lock")             # 全局锁（映射表/register）
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")
ALARM_FILE = os.path.join(LOG_DIR, "alarms.txt")

DEFAULT_PROJECT = "default"                                  # 未指定项目时的兜底
PROJECTS_FILE = os.path.join(WORKDIR, "projects.json")       # 项目映射表唯一真理源

__all__ = [
    # 常量
    "WORKDIR", "WORKSPACE_DIR", "LOG_DIR", "SCRIPTS_DIR",
    "STATUS_FILE", "LOCK_FILE", "LOG_FILE", "ALARM_FILE",
    "DEFAULT_PROJECT", "PROJECTS_FILE",
    # 项目映射
    "read_projects", "write_projects", "project_work_path", "project_default",
    # 项目分层
    "project_dir", "project_status_file", "project_lock_file", "project_log_dir",
    "ensure_project",
    # key 解析
    "split_key",
    # 相对路径工具
    "rel_input", "rel_analysis", "rel_review", "rel_artifact",
    "rel_stage_product", "rel_stage_review", "worker_log_name",
    # 绝对路径工具
    "abs_input", "abs_artifact",
    # 时间
    "now_iso",
]


def now_iso() -> str:
    """UTC ISO8601 字符串（秒精度，Z 后缀）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- 项目映射表 ----

def read_projects() -> dict:
    """读项目映射表；不存在或损坏返回空表。"""
    if os.path.exists(PROJECTS_FILE):
        try:
            return json.load(open(PROJECTS_FILE, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"projects": []}
    return {"projects": []}


def write_projects(pj: dict) -> None:
    """原子写项目映射表（自动写 updated_at）。"""
    pj["updated_at"] = now_iso()
    tmp = PROJECTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROJECTS_FILE)


def project_work_path(project: str):
    """查表取项目工作路径；未登记返回 None。"""
    pj = read_projects()
    for p in pj.get("projects", []):
        if p["name"] == project:
            return p.get("work_path")
    return None


def project_default():
    """当前默认项目名（无 → None）。"""
    pj = read_projects()
    for p in pj.get("projects", []):
        if p.get("default"):
            return p["name"]
    return None


# ---- 项目分层路径（经映射表 work_path，未登记回退 workspace/<project>） ----

def project_dir(project: str) -> str:
    wp = project_work_path(project)
    return wp if wp else os.path.join(WORKSPACE_DIR, project)


def project_status_file(project: str) -> str:
    return os.path.join(project_dir(project), "status.json")


def project_lock_file(project: str) -> str:
    return os.path.join(project_dir(project), "status.lock")


def project_log_dir(project: str) -> str:
    return os.path.join(project_dir(project), "logs")


def ensure_project(project: str) -> None:
    """确保项目目录骨架存在（幂等；register/写路径时自动调用）。"""
    os.makedirs(project_dir(project), exist_ok=True)
    for sub in ("input", "analysis", "review", "plans", "testplans", "code", "tests",
                "quality", "security", "release", "artifacts", "archive", "logs"):
        os.makedirs(os.path.join(project_dir(project), sub), exist_ok=True)
    if not os.path.exists(project_status_file(project)):
        with open(project_status_file(project), "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)


# ---- key 解析 ----

def split_key(key: str):
    """status key → (project, req_id)。key 格式 '<project>/<req_id>'；兼容旧（无 '/' → default 项目）。"""
    if "/" in key:
        p, r = key.rsplit("/", 1)
        return (p, r) if p else (DEFAULT_PROJECT, r)
    return DEFAULT_PROJECT, key


# ---- 相对路径工具 ----

def rel_input(project: str, rid: str) -> str:
    return f"{project}/input/{rid}.md"


def rel_analysis(project: str, rid: str, n: int) -> str:
    return f"{project}/analysis/{rid}-r{n}.md"


def rel_review(project: str, rid: str, n: int) -> str:
    return f"{project}/review/{rid}-r{n}.md"


def rel_artifact(project: str, rid: str) -> str:
    return f"{project}/artifacts/{rid}.md"


def rel_stage_product(cfg: dict, project: str, rid: str, n: int) -> str:
    """阶段产出物路径（相对 workspace/）：file → {project}/{dir}/{rid}-r{n}.md；dir → {project}/{dir}/{rid}-r{n}/（文件集）。"""
    base = f"{project}/{cfg['dir']}/{rid}-r{n}"
    return base + (".md" if cfg.get("kind", "file") == "file" else "/")


def rel_stage_review(cfg: dict, project: str, rid: str, n: int) -> str:
    """阶段评审意见路径：{project}/{dir}/{rid}-r{n}-review.md。"""
    return f"{project}/{cfg['dir']}/{rid}-r{n}-review.md"


def worker_log_name(project: str, rid: str, n: int, role: str = None) -> str:
    """worker 日志名（含角色，排查不再混写）：worker-{rid}-r{n}-{role}.log。"""
    return f"worker-{rid}-r{n}" + (f"-{role}" if role else "") + ".log"


def abs_input(project: str, rid: str) -> str:
    """需求输入文件绝对路径（解耦后查表）。"""
    return os.path.join(project_dir(project), "input", rid + ".md")


def abs_artifact(project: str, rid: str) -> str:
    """归档文件绝对路径（解耦后查表）。"""
    return os.path.join(project_dir(project), "artifacts", rid + ".md")