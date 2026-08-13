#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zteam 流水线状态控制与上下半部调度（方案 B 唯一实现）

职责划分：
- 上半部（cron no_agent 触发）：analyst_tick / reviewer_tick / weekly_tick —— 只做
  秒级确定性操作（注册、stale 恢复、原子认领、spawn 下半部 worker），零 token。
- 下半部（worker 内调用）：release_analyze / release_review —— worker 完成产物后
  调用，负责原子状态落定（含 max_rounds 强制归档、artifacts 归档、告警写入）。
- 人工/调试：register / stale / next / claim / setpid / rollback / requeue / list / get。

设计依据：docs/state-machine.md（状态机、迁移表、claim 字段、失败处理）。
用法：python3 scripts/statectl.py <子命令> [参数...]
"""

import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

# ---------------- 路径与常量 ----------------

WORKDIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # zteam/（realpath：兼容 ~/.hermes/scripts/ 下的符号链接调用）
WORKSPACE_DIR = os.path.join(WORKDIR, "workspace")  # 运行数据层（固定资产在根目录，数据全部收进 workspace/）
LOG_DIR = os.path.join(WORKSPACE_DIR, "logs")       # 全局日志（跨项目审计流）
SCRIPTS_DIR = os.path.join(WORKDIR, "scripts")
STATUS_FILE = os.path.join(WORKSPACE_DIR, "status.json")  # 兼容引用（实际按项目分文件，见 read_status）
LOCK_FILE = os.path.join(WORKSPACE_DIR, "status.lock")    # 全局锁（register/聚合扫描用）
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")
ALARM_FILE = os.path.join(LOG_DIR, "alarms.txt")

DEFAULT_PROJECT = "default"  # 未指定项目时的兜底项目

# ---- 项目分层：workspace/<project>/{input,analysis,...,logs,status.json,status.lock} ----
def project_dir(project: str) -> str:
    return os.path.join(WORKSPACE_DIR, project)


def project_status_file(project: str) -> str:
    return os.path.join(project_dir(project), "status.json")


def project_lock_file(project: str) -> str:
    return os.path.join(project_dir(project), "status.lock")


def project_log_dir(project: str) -> str:
    return os.path.join(project_dir(project), "logs")


def ensure_project(project: str) -> None:
    """确保项目目录骨架存在（幂等；由 register/写路径自动调用）。"""
    os.makedirs(project_dir(project), exist_ok=True)
    for sub in ("input", "analysis", "review", "plans", "testplans", "code", "tests",
                "quality", "security", "release", "artifacts", "archive", "logs"):
        os.makedirs(os.path.join(project_dir(project), sub), exist_ok=True)
    if not os.path.exists(project_status_file(project)):
        with open(project_status_file(project), "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)


def split_key(key: str):
    """status key → (project, req_id)。key 格式为 '<project>/<req_id>'；兼容旧格式（无 '/' → default 项目）。"""
    if "/" in key:
        p, r = key.rsplit("/", 1)
        return (p, r) if p else (DEFAULT_PROJECT, r)
    return DEFAULT_PROJECT, key


def rel_input(project: str, rid: str) -> str:
    return f"{project}/input/{rid}.md"


def rel_analysis(project: str, rid: str, n: int) -> str:
    return f"{project}/analysis/{rid}-r{n}.md"


def rel_review(project: str, rid: str, n: int) -> str:
    return f"{project}/review/{rid}-r{n}.md"


def rel_artifact(project: str, rid: str) -> str:
    return f"{project}/artifacts/{rid}.md"


def rel_stage_product(cfg: dict, project: str, rid: str, n: int) -> str:
    """阶段产出物路径（相对 workspace/）：file → {project}/{dir}/{rid}-r{n}.md；dir → {project}/{dir}/{rid}-r{n}/（文件集）"""
    base = f"{project}/{cfg['dir']}/{rid}-r{n}"
    return base + (".md" if cfg.get("kind", "file") == "file" else "/")


def rel_stage_review(cfg: dict, project: str, rid: str, n: int) -> str:
    """阶段评审意见路径：{project}/{dir}/{rid}-r{n}-review.md"""
    return f"{project}/{cfg['dir']}/{rid}-r{n}-review.md"


def stage_cfg(name: str):
    """阶段名 → 配置 dict（STAGES/GATES/RELEASE）。"""
    for stg in STAGES:
        if stg["name"] == name:
            return stg
    for g in GATES:
        if g["name"] == name:
            return g
    if name == RELEASE["name"]:
        return RELEASE
    return None


def stage_after(name: str):
    """返回 name 阶段的下一阶段配置（dict）或 None（已是终态）。"""
    names = [stg["name"] for stg in STAGES] + [g["name"] for g in GATES] + [RELEASE["name"]]
    if name not in names:
        return None
    idx = names.index(name)
    if idx + 1 >= len(names):
        return None
    return stage_cfg(names[idx + 1])


def next_action(e: dict):
    """根据当前状态返回下一步动作 (role, stage, phase) 或 None。
    phase ∈ design / review / gate / release；stage ∈ req / plan / testplan / code / test / quality / security / release。"""
    s = e.get("status")
    if s == "waiting":
        return None  # 依赖/迭代前置未满足，等待调度（不 spawn 不烧 token）
    if s in ("awaiting_user_confirm", "dispatched"):
        return None  # v2：等用户评审规格 / 已分发等模块开发（人工/架构师环节）
    if s == "approved":
        return None  # v2：规格锁定 → 等 SE 架构设计（版本级），不再直接进需求级方案
    if s in ("pending", "needs_fix"):
        return ("req-analyst", "req", "design")
    if s == "analyzing":
        # 执行中（含已认领）或评审 FAIL 打回待重做（无 claim）——动作一致，认领与否由 claim 的 claimed_by 校验把关
        return ("req-analyst", "req", "design")
    if s == "analyzed":
        return ("req-reviewer", "req", "review")
    if s == "reviewing":
        # 评审中（已认领）——build_worker_query 在 claim 后调用需要此映射
        return ("req-reviewer", "req", "review")
    if s == "approved":
        stg = STAGES[0]
        return (stg["designer"], stg["name"], "design")
    for stg in STAGES:
        if s == f"{stg['name']}_designing":
            return (stg["designer"], stg["name"], "design")
        if s == f"{stg['name']}_reviewing":
            return (stg["reviewer"], stg["name"], "review")
        if s == f"{stg['name']}_done":
            if stg["name"] == "test":
                return None  # v2 截断：UT（需求级测试）完成 → 等迭代集成（it），不再进需求级质量/安全/发布
            nxt = stage_after(stg["name"])
            if nxt is RELEASE:
                return (RELEASE["role"], RELEASE["name"], "release")
            if nxt:
                return (nxt["designer"] if "designer" in nxt else nxt["role"], nxt["name"],
                        "design" if "designer" in nxt else "gate")
            return None
    for g in GATES:
        if s == f"{g['name']}_gating":
            return (g["role"], g["name"], "gate")
        if s == f"{g['name']}_done":
            nxt = stage_after(g["name"])
            if nxt is RELEASE:
                return (RELEASE["role"], RELEASE["name"], "release")
            if nxt:
                return (nxt["designer"] if "designer" in nxt else nxt["role"], nxt["name"],
                        "design" if "designer" in nxt else "gate")
            return None
    if s == "releasing":
        return (RELEASE["role"], RELEASE["name"], "release")
    return None


def abs_input(project: str, rid: str) -> str:
    return os.path.join(project_dir(project), "input", rid + ".md")


def abs_artifact(project: str, rid: str) -> str:
    return os.path.join(project_dir(project), "artifacts", rid + ".md")


def worker_log_name(project: str, rid: str, n: int, role: str = None) -> str:
    """worker 日志名（含角色，排查不再混写）：worker-{rid}-r{n}-{role}.log"""
    return f"worker-{rid}-r{n}" + (f"-{role}" if role else "") + ".log"

STALE_AFTER_MIN = int(os.environ.get("STALE_AFTER_MIN", "20"))   # 中间态超时（分钟）
MAX_FAILURES = int(os.environ.get("MAX_FAILURES", "2"))          # 连续失败上限
DEFAULT_MAX_ROUNDS = int(os.environ.get("DEFAULT_MAX_ROUNDS", "3"))

# 下半部 worker 模型绑定（不同角色不同模型；可用环境变量覆盖）
# 当前 API（api.deepseek.com）可用模型：deepseek-v4-flash（快/便宜）、deepseek-v4-pro（强推理）
ANALYST_MODEL = os.environ.get("ANALYST_MODEL", "deepseek-v4-flash")
ANALYST_PROVIDER = os.environ.get("ANALYST_PROVIDER", "deepseek")
REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", "deepseek-v4-pro")
REVIEWER_PROVIDER = os.environ.get("REVIEWER_PROVIDER", "deepseek")
# 阶段角色模型（设计/产出类 = flash 快；评审/门禁类 = pro 把关）
PLAN_DESIGNER_MODEL = os.environ.get("PLAN_DESIGNER_MODEL", "deepseek-v4-flash")
PLAN_REVIEWER_MODEL = os.environ.get("PLAN_REVIEWER_MODEL", "deepseek-v4-pro")
TESTPLAN_DESIGNER_MODEL = os.environ.get("TESTPLAN_DESIGNER_MODEL", "deepseek-v4-flash")
TESTPLAN_REVIEWER_MODEL = os.environ.get("TESTPLAN_REVIEWER_MODEL", "deepseek-v4-pro")
CODE_DEVELOPER_MODEL = os.environ.get("CODE_DEVELOPER_MODEL", "MiniMax-M3")
CODE_REVIEWER_MODEL = os.environ.get("CODE_REVIEWER_MODEL", "MiniMax-M3")
CODE_PROVIDER = os.environ.get("CODE_PROVIDER", "minimax-cn")  # MiniMax（中国站，Anthropic 兼容 endpoint）
TEST_DEVELOPER_MODEL = os.environ.get("TEST_DEVELOPER_MODEL", "MiniMax-M3")
TEST_REVIEWER_MODEL = os.environ.get("TEST_REVIEWER_MODEL", "MiniMax-M3")
TEST_PROVIDER = os.environ.get("TEST_PROVIDER", "minimax-cn")  # MiniMax（中国站，Anthropic 兼容 endpoint）
QUALITY_REVIEWER_MODEL = os.environ.get("QUALITY_REVIEWER_MODEL", "deepseek-v4-pro")
SECURITY_REVIEWER_MODEL = os.environ.get("SECURITY_REVIEWER_MODEL", "deepseek-v4-pro")
RELEASER_MODEL = os.environ.get("RELEASER_MODEL", "deepseek-v4-flash")
IT_DESIGNER_MODEL = os.environ.get("IT_DESIGNER_MODEL", "deepseek-v4-flash")
IT_REVIEWER_MODEL = os.environ.get("IT_REVIEWER_MODEL", "deepseek-v4-pro")
ST_TESTER_MODEL = os.environ.get("ST_TESTER_MODEL", "deepseek-v4-flash")
ST_REVIEWER_MODEL = os.environ.get("ST_REVIEWER_MODEL", "deepseek-v4-pro")

# ---- 阶段流水线定义（需求 approved 后按序推进）----
# 成对阶段（产出者 + 评审者）；kind: file=md 文档产物 / dir=文件集产物（代码/测试目录）
STAGES = [
    {"name": "plan",     "designer": "dev-plan-designer",  "reviewer": "dev-plan-reviewer",  "dir": "plans",     "kind": "file"},
    {"name": "testplan", "designer": "test-plan-designer", "reviewer": "test-plan-reviewer", "dir": "testplans", "kind": "file"},
    {"name": "code",     "designer": "code-developer",     "reviewer": "code-reviewer",      "dir": "code",      "kind": "dir"},
    {"name": "test",     "designer": "test-developer",     "reviewer": "test-reviewer",      "dir": "tests",     "kind": "dir"},
]
# 单角色门禁阶段（评审不通过不前进；连续失败达上限 → blocked）
GATES = [
    {"name": "quality",  "role": "quality-reviewer",  "dir": "quality"},
    {"name": "security", "role": "security-reviewer", "dir": "security"},
]
# 终态阶段（产出发布说明；released = 完整交付物归档 + 通知）
RELEASE = {"name": "release", "role": "releaser", "dir": "release", "kind": "dir"}

# 角色 → (模型, provider) 映射（含需求阶段两个角色）
ROLE_MODELS = {
    "req-analyst": (ANALYST_MODEL, ANALYST_PROVIDER),
    "req-reviewer": (REVIEWER_MODEL, REVIEWER_PROVIDER),
    "dev-plan-designer": (PLAN_DESIGNER_MODEL, ANALYST_PROVIDER),
    "dev-plan-reviewer": (PLAN_REVIEWER_MODEL, ANALYST_PROVIDER),
    "test-plan-designer": (TESTPLAN_DESIGNER_MODEL, ANALYST_PROVIDER),
    "test-plan-reviewer": (TESTPLAN_REVIEWER_MODEL, ANALYST_PROVIDER),
    "code-developer": (CODE_DEVELOPER_MODEL, CODE_PROVIDER),
    "code-reviewer": (CODE_REVIEWER_MODEL, CODE_PROVIDER),
    "test-developer": (TEST_DEVELOPER_MODEL, TEST_PROVIDER),
    "test-reviewer": (TEST_REVIEWER_MODEL, TEST_PROVIDER),
    "quality-reviewer": (QUALITY_REVIEWER_MODEL, ANALYST_PROVIDER),
    "security-reviewer": (SECURITY_REVIEWER_MODEL, ANALYST_PROVIDER),
    "releaser": (RELEASER_MODEL, ANALYST_PROVIDER),
    "it-designer": (IT_DESIGNER_MODEL, ANALYST_PROVIDER),
    "it-reviewer": (IT_REVIEWER_MODEL, ANALYST_PROVIDER),
    "st-tester": (ST_TESTER_MODEL, ANALYST_PROVIDER),
    "st-reviewer": (ST_REVIEWER_MODEL, ANALYST_PROVIDER),
}
# 角色 → 角色文件（worker 指令阅读文件）
ROLE_FILES = {
    "req-analyst": "roles/req-analyst.md",
    "req-reviewer": "roles/req-reviewer.md",
    "dev-plan-designer": "roles/dev-plan-designer.md",
    "dev-plan-reviewer": "roles/dev-plan-reviewer.md",
    "test-plan-designer": "roles/test-plan-designer.md",
    "test-plan-reviewer": "roles/test-plan-reviewer.md",
    "code-developer": "roles/code-developer.md",
    "code-reviewer": "roles/code-reviewer.md",
    "test-developer": "roles/test-developer.md",
    "test-reviewer": "roles/test-reviewer.md",
    "quality-reviewer": "roles/quality-reviewer.md",
    "security-reviewer": "roles/security-reviewer.md",
    "releaser": "roles/releaser.md",
    "it-designer": "roles/it-designer.md",
    "it-reviewer": "roles/it-reviewer.md",
    "st-tester": "roles/st-tester.md",
    "st-reviewer": "roles/st-reviewer.md",
}
# 角色 → 中文名（worker 指令措辞）
ROLE_CN = {
    "req-analyst": "需求分析师", "req-reviewer": "需求评审师",
    "dev-plan-designer": "开发方案设计者", "dev-plan-reviewer": "开发方案评审者",
    "test-plan-designer": "测试方案设计者", "test-plan-reviewer": "测试方案评审者",
    "code-developer": "代码开发者", "code-reviewer": "代码评审者",
    "test-developer": "测试开发者", "test-reviewer": "测试评审者",
    "quality-reviewer": "质量评审者", "security-reviewer": "安全红线评审者",
    "releaser": "发布者",
    "it-designer": "集成测试设计执行者", "it-reviewer": "集成测试评审者",
    "st-tester": "系统测试执行者", "st-reviewer": "系统测试评审者",
}
# 所有中间态（stale 恢复/回滚适用）
def _mid_states() -> set:
    s = {"analyzing", "reviewing", "releasing"}
    for stg in STAGES:
        s |= {f"{stg['name']}_designing", f"{stg['name']}_reviewing"}
    for g in GATES:
        s.add(f"{g['name']}_gating")
    return s
MID_STATES = _mid_states()
# 所有合法状态
def _all_states() -> set:
    s = {"pending", "analyzing", "analyzed", "reviewing", "needs_fix", "approved", "blocked", "released",
         "awaiting_user_confirm", "dispatched"}
    for stg in STAGES:
        s |= {f"{stg['name']}_designing", f"{stg['name']}_reviewing", f"{stg['name']}_done"}
    for g in GATES:
        s |= {f"{g['name']}_gating", f"{g['name']}_done"}
    return s
STATE_SET = _all_states()

# ---------------- 基础工具 ----------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(line: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{now_iso()} {line}\n")


def read_status(project: str = None) -> dict:
    """读状态。project 指定 → 只读该项目 status.json；None → 聚合全部项目（key 仍 '<project>/<req_id>'）。
    兼容旧单文件：workspace/status.json 存在（迁移前）时优先读它。"""
    if project is not None:
        try:
            with open(project_status_file(project), encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    # 聚合全部项目
    merged = {}
    if os.path.isfile(STATUS_FILE):  # 迁移前的单文件（读后由 write_status 分发到项目文件）
        try:
            with open(STATUS_FILE, encoding="utf-8") as f:
                merged.update(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    if os.path.isdir(WORKSPACE_DIR):
        for proj in sorted(os.listdir(WORKSPACE_DIR)):
            sf = project_status_file(proj)
            if os.path.isfile(sf):
                try:
                    with open(sf, encoding="utf-8") as f:
                        data = json.load(f)
                    for k, v in data.items():
                        merged.setdefault(k, v)  # 单文件优先（避免覆盖未迁移数据）
                except (FileNotFoundError, json.JSONDecodeError):
                    continue
    return merged


def write_status(st: dict, project: str = None) -> None:
    """写状态。project 指定 → 写该项目文件；None → 按 key 分发到各项目文件。
    迁移兼容：workspace/status.json 仍存在时同步写它（保证旧读路径可见），迁移完成后由 migrate 删除。"""
    if project is not None:
        ensure_project(project)
        tmp = project_status_file(project) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, project_status_file(project))
        return
    by_proj = {}
    for key, e in st.items():
        p, _ = split_key(key)
        by_proj.setdefault(p, {})[key] = e
    for p, sub in by_proj.items():
        ensure_project(p)
        tmp = project_status_file(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sub, f, ensure_ascii=False, indent=2)
        os.replace(tmp, project_status_file(p))
    if os.path.isfile(STATUS_FILE):  # 迁移兼容
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)


def acquire_lock(timeout: float = 10.0, project: str = None):
    """flock 写锁。project 指定 → 项目锁（workspace/<proj>/status.lock，项目间并发的基础）；
    None → 全局锁（workspace/status.lock，register/聚合扫描用）。"""
    lockf = open(project_lock_file(project) if project else LOCK_FILE, "w")
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lockf
        except BlockingIOError:
            if time.time() > deadline:
                lockf.close()
                raise RuntimeError("状态锁获取超时（另一进程持有锁）")
            time.sleep(0.2)


def clear_claim(e: dict) -> None:
    e.pop("claimed_by", None)
    e.pop("claimed_at", None)
    e.pop("worker_pid", None)


def pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False  # 0/None = 认领后尚未 spawn，视为已死（防 os.kill(0,0) 误判进程组存活）
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存在但无权限 → 视为存活


# ---------------- 版本管理（v2 P1-01：项目 → 语义化版本 → 需求归属） ----------------

VERSIONS_FILE = "versions.json"


def versions_path(project: str) -> str:
    return os.path.join(project_dir(project), VERSIONS_FILE)


def ensure_versions(project: str) -> dict:
    """项目版本清单：不存在则初始化（v1.0.0 planning + current）。
    结构：{"versions": [{"name","status","iterations":[{"n","status","reqs","it_product","it_reviews"}],
                          "reqs","st_product","released_at"}], "current": "v1.0.0"}
    版本状态：planning → in_dev → st_pending → st_passed → quality_pending → released
    迭代状态：pending → it_pending → it_passed"""
    p = versions_path(project)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                vd = json.load(f)
            # 旧格式迁移：迭代列表 [1,2] → 对象 [{n:1, status:pending, ...}]（迁移后立即落盘，防只内存迁移）
            migrated = False
            for v in vd.get("versions", []):
                its = v.get("iterations")
                if its and isinstance(its[0], int):
                    v["iterations"] = [{"n": i, "status": "pending", "reqs": [], "it_product": None, "it_reviews": []} for i in its]
                    migrated = True
                for it in v.get("iterations", []):
                    it.setdefault("reqs", [])
                    it.setdefault("it_product", None)
                    it.setdefault("it_reviews", [])
                v.setdefault("st_product", None)
                # v2 模块中心扩展字段
                v.setdefault("architecture", None)   # 架构设计产物（SE，PM 评审）
                v.setdefault("module_plan", None)    # 功能模块分工表（SE，PM 评审；含迭代计划）
                v.setdefault("test_plan", None)      # 整体测试方案（TE，SE 评审）
                v.setdefault("qa_report", None)      # QA 评审结论
                v.setdefault("release_pkg", None)    # release 包
            if migrated:
                write_versions(project, vd)
            return vd
        except (json.JSONDecodeError, IOError):
            pass
    vd = {"versions": [{"name": "v1.0.0", "status": "planning",
                        "iterations": [{"n": 1, "status": "pending", "reqs": [], "it_product": None, "it_reviews": []}],
                        "reqs": [], "st_product": None, "released_at": None}],
          "current": "v1.0.0"}
    write_versions(project, vd)
    return vd


def read_versions(project: str) -> dict:
    return ensure_versions(project)


def write_versions(project: str, vd: dict) -> None:
    os.makedirs(project_dir(project), exist_ok=True)
    tmp = versions_path(project) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(vd, f, ensure_ascii=False, indent=2)
    os.replace(tmp, versions_path(project))


def _parse_req_meta(path: str) -> dict:
    """解析需求文件头元数据：version:/iteration:/depends_on:（frontmatter 或注释行）。
    未指定 → version 用项目 current，iteration/depends_on 后续期自动排。"""
    meta = {"version": None, "iteration": None, "depends_on": []}
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(2000)
        for line in head.splitlines()[:20]:
            line = line.strip().lstrip("#-* ").strip()
            if not line or ":" not in line:
                continue
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "version" and v:
                meta["version"] = v
            elif k == "iteration" and v:
                try:
                    meta["iteration"] = int(v)
                except ValueError:
                    pass
            elif k == "depends_on" and v:
                meta["depends_on"] = [x.strip() for x in v.split(",") if x.strip()]
    except Exception:
        pass
    return meta


def advance_versions(project: str, st: dict) -> None:
    """版本状态推进：版本下全部需求 released → 版本 released（惰性，查看/调度时调用）。"""
    vd = read_versions(project)
    changed = False
    for v in vd.get("versions", []):
        if v.get("status") == "released":
            continue
        reqs = v.get("reqs") or []
        if reqs and all(st.get(f"{project}/{r}", {}).get("status") == "released" for r in reqs):
            v["status"] = "released"
            v["released_at"] = now_iso()
            changed = True
            log(f"VERSION {project}/{v['name']} -> released (all reqs done)")
    if changed:
        write_versions(project, vd)


def _it_inputs(project: str, reqs: list, st: dict) -> str:
    """迭代 it 的输入清单：迭代内各需求的代码/测试产物路径。"""
    lines = []
    for r in reqs:
        e = st.get(f"{project}/{r}") or {}
        stages = e.get("stages") or {}
        code_p = (stages.get("code") or {}).get("product")
        test_p = (stages.get("test") or {}).get("product")
        lines.append(f"- {r}：代码={code_p or '?'}，UT={test_p or '?'}，状态={e.get('status', '?')}")
    return "\n".join(lines)


def _schedule_it_st(project: str, vd: dict, st: dict, alarms: list) -> None:
    """迭代/版本级测试调度（v2 第 4 期）：
    - 迭代内全部需求 test_done/released → it 阶段（spawn it-designer，产物 {项目}/it/iter-{N}/）
    - 全部迭代 it_passed → 版本 st 阶段（spawn st-tester，产物 {项目}/st/v{版本}/）
    认领记在迭代/版本对象（it_claimed/st_claimed）防重复 spawn。"""
    for v in vd.get("versions", []):
        if v.get("status") == "released":
            continue
        iters = v.get("iterations") or []
        # ---- 迭代 IT ----
        for it in iters:
            if it.get("status") != "pending" or it.get("it_claimed"):
                continue
            reqs = it.get("reqs") or []
            if not reqs:
                continue
            if all(st.get(f"{project}/{r}", {}).get("status") in ("test_done", "released") for r in reqs):
                it["it_claimed"] = True
                it["status"] = "it_pending"
                out = f"{project}/it/iter-{it['n']}/"
                query = (
                    f"你是本流水线的【集成测试设计执行者】。严格遵循 roles/it-designer.md "
                    f"为项目 {project} 版本 {v['name']} 的迭代 {it['n']} 执行集成测试（IT）。\n"
                    f"启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {project}/__it{it['n']} test working（幂等，标记集成测试执行中）；\n"
                    f"迭代内需求（UT 均已通过）：\n{_it_inputs(project, reqs, st)}\n"
                    f"任务：1. 按 roles/it-designer.md 在 {out} 目录内产出集成测试（用例+报告+结论 PASS/FAIL）；\n"
                    f"2. 运行 python3 scripts/statectl.py release_it {project} {v['name']} {it['n']} {out} 完成状态更新；\n"
                    f"3. 完成后无需汇报。"
                )
                pid = spawn_worker("it-designer", f"{project}/__it{it['n']}", 1, query)
                log(f"SPAWN-IT {project}/{v['name']} iter-{it['n']} worker=it-designer pid={pid}")
                alarms.append(f"迭代 {v['name']}/iter-{it['n']} 进入集成测试（it-designer pid={pid}）")
        # ---- 版本 ST ----
        if v.get("status") == "st_pending" and not v.get("st_claimed"):
            v["st_claimed"] = True
            out = f"{project}/st/{v['name']}/"
            query = (
                f"你是本流水线的【系统测试执行者】。严格遵循 roles/st-tester.md "
                f"为项目 {project} 版本 {v['name']} 执行系统测试（ST，全部迭代 IT 已通过）。\n"
                f"启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {project}/__st{''.join(v['name'].split('.'))} test working（幂等）；\n"
                f"迭代集成测试产物：\n" + "\n".join(
                    f"- iter-{it['n']}：{it.get('it_product') or '?'}" for it in iters)
                + f"\n任务：1. 按 roles/st-tester.md 在 {out} 目录内产出系统测试（用例+报告+结论 PASS/FAIL）；\n"
                f"2. 运行 python3 scripts/statectl.py release_st {project} {v['name']} {out} 完成状态更新；\n3. 完成后无需汇报。"
            )
            pid = spawn_worker("st-tester", f"{project}/__st{v['name']}", 1, query)
            log(f"SPAWN-ST {project}/{v['name']} worker=st-tester pid={pid}")
            alarms.append(f"版本 {v['name']} 进入系统测试（st-tester pid={pid}）")
    write_versions(project, vd)  # 调度改动（迭代/版本状态/claim）落盘


def _advance_v2(project: str, vd: dict, st: dict, alarms: list) -> None:
    """v2 版本/迭代状态机推进：迭代 it_passed 累计 → 版本 st_pending；版本 st_passed → 标记待门禁。"""
    for v in vd.get("versions", []):
        if v.get("status") in ("released", "st_passed", "quality_pending"):
            continue
        iters = v.get("iterations") or []
        if not iters or not any(it.get("reqs") for it in iters):
            continue
        all_it = all(it.get("status") == "it_passed" for it in iters if it.get("reqs"))
        if all_it and v.get("status") in ("planning", "in_dev"):
            v["status"] = "st_pending"
            v["st_claimed"] = False
            log(f"VERSION {project}/{v['name']} -> st_pending (all iterations IT passed)")
            write_versions(project, vd)  # 状态推进落盘


def release_it(project: str, version: str, iter_n: str, product: str, conclusion: str) -> int:
    """迭代集成测试评审：release_it {project} {version} {iter} {产物} PASS|FAIL。
    PASS → 迭代 it_passed；FAIL → 迭代回 it_pending（重做）。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print(f"release_it: conclusion 必须为 PASS 或 FAIL，收到 {conclusion!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        it = next((x for x in v.get("iterations", []) if str(x.get("n")) == str(iter_n)), None)
        if not it:
            print(f"迭代 {iter_n} 不存在", file=sys.stderr)
            return 1
        full = os.path.join(WORKSPACE_DIR, norm_product(product))
        if not os.path.exists(full):
            print(f"产物不存在: {full}", file=sys.stderr)
            return 1
        it["it_product"] = norm_product(product)
        it["it_reviews"] = it.get("it_reviews", []) + [norm_product(product)]
        if conclusion == "PASS":
            it["status"] = "it_passed"
        else:
            it["status"] = "it_pending"
            it["it_claimed"] = False  # 打回重做
        write_versions(project, vd)
        log(f"RELEASE_IT {project}/{version} iter-{iter_n} {conclusion} product={it['it_product']}")
    return 0


def release_st(project: str, version: str, product: str, conclusion: str) -> int:
    """版本系统测试评审：release_st {project} {version} {产物} PASS|FAIL。
    PASS → 版本 st_passed（下一步门禁/release 第 4b 期）；FAIL → 版本回 st_pending 重做。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print(f"release_st: conclusion 必须为 PASS 或 FAIL，收到 {conclusion!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        full = os.path.join(WORKSPACE_DIR, norm_product(product))
        if not os.path.exists(full):
            print(f"产物不存在: {full}", file=sys.stderr)
            return 1
        v["st_product"] = norm_product(product)
        if conclusion == "PASS":
            v["status"] = "st_passed"
        else:
            v["status"] = "st_pending"
            v["st_claimed"] = False  # 重做
        write_versions(project, vd)
        log(f"RELEASE_ST {project}/{version} {conclusion} product={v['st_product']}")
    return 0


def cmd_confirm(rid: str) -> int:
    """用户确认需求规格：confirm {req_id} → awaiting_user_confirm → approved（规格锁定）。
    用户是规格唯一拍板人；脚本校验规格产物真实存在。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        if e.get("status") != "awaiting_user_confirm":
            print(f"confirm 仅对 awaiting_user_confirm 状态有效（当前 {e.get('status')}）", file=sys.stderr)
            return 1
        if not e.get("analysis") or not os.path.exists(os.path.join(WORKSPACE_DIR, norm_product(e["analysis"]))):
            print(f"规格产物不存在或未登记: {e.get('analysis')}", file=sys.stderr)
            return 1
        e["status"] = "approved"
        e["approved_at"] = now_iso()
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"USER_CONFIRM {rid} -> approved (规格锁定)")
    return 0


def cmd_reject(rid: str, reason: str) -> int:
    """用户驳回需求规格：reject {req_id} <理由> → 回到 analyzing（PM 带理由重细化）。"""
    if not reason.strip():
        print("reject 需要理由: reject {req_id} <理由>", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        if e.get("status") != "awaiting_user_confirm":
            print(f"reject 仅对 awaiting_user_confirm 状态有效（当前 {e.get('status')}）", file=sys.stderr)
            return 1
        e["status"] = "analyzing"
        e["reject_reason"] = reason.strip()
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"USER_REJECT {rid} -> analyzing (reason={reason.strip()[:80]})")
    return 0


# ---------------- 模块管理（v2 模块中心：SE 抉择组织形态） ----------------

MODULES_FILE = "modules.json"
MODULE_TYPES = ("基础平台", "中间件", "上层应用")


def modules_path(project: str) -> str:
    return os.path.join(project_dir(project), MODULES_FILE)


def ensure_modules(project: str) -> dict:
    p = modules_path(project)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    md = {"modules": []}
    write_modules(project, md)
    return md


def read_modules(project: str) -> dict:
    return ensure_modules(project)


def write_modules(project: str, md: dict) -> None:
    os.makedirs(project_dir(project), exist_ok=True)
    tmp = modules_path(project) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(md, f, ensure_ascii=False, indent=2)
    os.replace(tmp, modules_path(project))


def cmd_module(project: str, action: str, rest: list) -> int:
    """模块管理（SE 使用）：module {project} add <name> <类型> [desc] / rm <name> /
    dep <name> <dep1,dep2> / dispatch <name> <req_id1,req_id2> / list"""
    action = action.lower()
    with acquire_lock() as _:
        md = read_modules(project)
        mods = md.setdefault("modules", [])
        if action == "list":
            for m in mods:
                print(f"  {m['name']} [{m.get('type','?')}] alive={m.get('alive', True)} "
                      f"deps={m.get('depends_on', [])} reqs={len(m.get('reqs', []))}")
            return 0
        if action == "add":
            if len(rest) < 2:
                print("module add <name> <类型(基础平台/中间件/上层应用)> [desc]", file=sys.stderr)
                return 1
            name, mtype = rest[0], rest[1]
            if mtype not in MODULE_TYPES:
                print(f"类型必须为 {'/'.join(MODULE_TYPES)}", file=sys.stderr)
                return 1
            if any(m["name"] == name for m in mods):
                print(f"模块 {name} 已存在", file=sys.stderr)
                return 1
            mods.append({"name": name, "type": mtype, "desc": " ".join(rest[2:]) or "",
                         "depends_on": [], "reqs": [], "design": {"product": None, "reviews": []},
                         "iterations": [], "alive": True})
            write_modules(project, md)
            log(f"MODULE_ADD {project}/{name} type={mtype}")
            return 0
        if action == "rm":
            if not rest:
                print("module rm <name>", file=sys.stderr)
                return 1
            m = next((x for x in mods if x["name"] == rest[0]), None)
            if not m:
                print(f"模块 {rest[0]} 不存在", file=sys.stderr)
                return 1
            m["alive"] = False  # 下线（保留历史，需求需重新分发）
            write_modules(project, md)
            log(f"MODULE_RM {project}/{rest[0]} (下线)")
            return 0
        if action == "dep":
            if len(rest) < 2:
                print("module dep <name> <dep1,dep2>", file=sys.stderr)
                return 1
            m = next((x for x in mods if x["name"] == rest[0]), None)
            if not m:
                print(f"模块 {rest[0]} 不存在", file=sys.stderr)
                return 1
            m["depends_on"] = [x.strip() for x in rest[1].split(",") if x.strip()]
            write_modules(project, md)
            log(f"MODULE_DEP {project}/{rest[0]} -> {m['depends_on']}")
            return 0
        if action == "dispatch":
            if len(rest) < 2:
                print("module dispatch <name> <req_id1,req_id2>", file=sys.stderr)
                return 1
            m = next((x for x in mods if x["name"] == rest[0]), None)
            if not m:
                print(f"模块 {rest[0]} 不存在", file=sys.stderr)
                return 1
            st = read_status()
            for rid in [x.strip() for x in rest[1].split(",") if x.strip()]:
                key = f"{project}/{rid}"
                if key not in st:
                    print(f"需求 {key} 不存在", file=sys.stderr)
                    continue
                if rid not in m.setdefault("reqs", []):
                    m["reqs"].append(rid)
                if st[key].get("status") == "approved":
                    st[key]["status"] = "dispatched"
                    st[key]["module"] = rest[0]
                    st[key]["updated_at"] = now_iso()
            write_modules(project, md)
            write_status(st)
            log(f"MODULE_DISPATCH {project}/{rest[0]} <- {rest[1]}")
            return 0
        print(f"未知 module 动作: {action}（add/rm/dep/dispatch/list）", file=sys.stderr)
        return 1


# ---------------- 问题单（v2：提单人复测闭环） ----------------


def issues_dir(project: str) -> str:
    d = os.path.join(project_dir(project), "issues")
    os.makedirs(d, exist_ok=True)
    return d


def _issue_path(project: str, iid: str) -> str:
    return os.path.join(issues_dir(project), f"{iid}.md")


def cmd_issue(project: str, action: str, rest: list) -> int:
    """问题单（MTO/STO 提单，FO 修复，提单人复测关闭）：
    issue {project} open <iid> <严重级> <描述...> / fix <iid> / close <iid> / list [open]"""
    action = action.lower()
    if action == "list":
        filt = rest[0].lower() if rest else ""
        for f in sorted(os.listdir(issues_dir(project))):
            if not f.endswith(".md"):
                continue
            content = open(os.path.join(issues_dir(project), f), encoding="utf-8").read()
            status = "open"
            if "状态：closed" in content:
                status = "closed"
            elif "状态：fixed" in content:
                status = "fixed"
            if filt and status != filt:
                continue
            first = content.splitlines()[1] if len(content.splitlines()) > 1 else ""
            print(f"  {f[:-3]:20s} [{status}] {first.strip()}")
        return 0
    if not rest:
        print(f"issue {action} 参数不足", file=sys.stderr)
        return 1
    iid = rest[0]
    p = _issue_path(project, iid)
    if action == "open":
        if len(rest) < 2:
            print("issue open <iid> <严重级> <描述>", file=sys.stderr)
            return 1
        if os.path.exists(p):
            print(f"问题单 {iid} 已存在", file=sys.stderr)
            return 1
        content = (f"# 问题单 {iid}\n\n状态：open\n严重级：{rest[1]}\n"
                   f"提单人：{os.environ.get('ISSUE_REPORTER', '?')}\n时间：{now_iso()}\n\n描述：{' '.join(rest[2:]) or ''}\n\n"
                   f"## 修复记录\n\n## 复测记录\n")
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"ISSUE_OPEN {project}/{iid} sev={rest[1]}")
        return 0
    if not os.path.exists(p):
        print(f"问题单 {iid} 不存在", file=sys.stderr)
        return 1
    content = open(p, encoding="utf-8").read()
    if action == "fix":
        if "状态：open" not in content:
            print(f"问题单 {iid} 非 open 状态", file=sys.stderr)
            return 1
        content = content.replace("状态：open", "状态：fixed", 1)
        content += f"- {now_iso()} FO 修复完成\n"
    elif action == "close":
        if "状态：fixed" not in content:
            print(f"问题单 {iid} 非 fixed 状态（需 FO 先修复）", file=sys.stderr)
            return 1
        content = content.replace("状态：fixed", "状态：closed", 1)
        content += f"- {now_iso()} 提单人复测通过，关闭\n"
    else:
        print(f"未知 issue 动作: {action}（open/fix/close/list）", file=sys.stderr)
        return 1
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"ISSUE_{action.upper()} {project}/{iid}")
    return 0


def open_issues(project: str) -> list:
    """项目当前 open/fixed 问题单（门禁条件：>0 时模块/版本不进下一阶段）。"""
    out = []
    for f in sorted(os.listdir(issues_dir(project))):
        if not f.endswith(".md"):
            continue
        content = open(os.path.join(issues_dir(project), f), encoding="utf-8").read()
        if "状态：open" in content or "状态：fixed" in content:
            out.append(f[:-3])
    return out


def cmd_versions(project: str = None) -> int:
    """版本聚合视图：statectl versions [project]（无参 = 全部项目）。"""
    projects = [project] if project else [p for p in sorted(os.listdir(WORKSPACE_DIR))
                                          if os.path.isdir(os.path.join(WORKSPACE_DIR, p))
                                          and p not in ("logs",) and not p.startswith(".")]
    st = read_status()
    for proj in projects:
        vd = read_versions(proj)
        advance_versions(proj, st)
        vd = read_versions(proj)  # 推进后重读
        print(f"== 项目 {proj}（当前开发版本: {vd.get('current')}） ==")
        for v in vd.get("versions", []):
            reqs = v.get("reqs") or []
            done = sum(1 for r in reqs if st.get(f"{proj}/{r}", {}).get("status") == "released")
            print(f"  {v.get('name'):10s} {v.get('status'):9s} 迭代={v.get('iterations')} 需求 {done}/{len(reqs)}"
                  + (f"  released_at={v.get('released_at')}" if v.get("released_at") else ""))
            for r in reqs:
                print(f"      - {r}: {st.get(f'{proj}/{r}', {}).get('status', '?')}")
    return 0


def cmd_assign(rid: str, spec: str) -> int:
    """人工干预需求归属（v2）：assign <req_id> version=v1.1.0 [iteration=2] [depends_on=a,b]。
    覆盖自动排期（用户拍板：自动排 + 保留人工干预途径）。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        project, _ = split_key(rid)
        vd = ensure_versions(project)
        updates = {}
        for kv in spec.split():
            if "=" not in kv:
                continue
            k, _, v = kv.partition("=")
            k = k.strip().lower()
            v = v.strip()
            if k == "version":
                if v not in [x["name"] for x in vd["versions"]]:
                    vd["versions"].append({"name": v, "status": "planning",
                                           "iterations": [], "reqs": [], "released_at": None})
                updates["version"] = v
            elif k == "iteration":
                try:
                    updates["iteration"] = int(v)
                except ValueError:
                    print(f"iteration 必须为数字: {v}", file=sys.stderr)
                    return 1
            elif k == "depends_on":
                updates["depends_on"] = [x.strip() for x in v.split(",") if x.strip()]
        if "version" in updates:
            old_v = e.get("version")
            e["version"] = updates["version"]
            # 维护 versions.json 的 reqs 归属（旧版本移除、新版本加入）
            for x in vd["versions"]:
                if x["name"] == old_v and rid.split("/", 1)[1] in x.get("reqs", []):
                    x["reqs"] = [r for r in x["reqs"] if r != rid.split("/", 1)[1]]
            for x in vd["versions"]:
                if x["name"] == updates["version"]:
                    rid_short = rid.split("/", 1)[1]
                    if rid_short not in x.get("reqs", []):
                        x.setdefault("reqs", []).append(rid_short)
        for k, val in updates.items():
            if k != "version":
                e[k] = val
        write_versions(project, vd)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"ASSIGN {rid} {updates} (manual)")
    return 0




def register_new_inputs(st: dict) -> list:
    """扫描各项目 input/ 下未登记文件自动注册为 pending（项目目录自动创建）。
    结构：workspace/<project>/input/<req_id>.md（每个项目独立 input/）。
    兼容旧结构：workspace/input/<project>/<req_id>.md 与平铺 workspace/input/<req_id>.md（迁移前数据仍可注册）。
    返回新注册的 key（'<project>/<req_id>'）列表。"""
    registered = []
    # 新结构：workspace/<project>/input/*.md
    if os.path.isdir(WORKSPACE_DIR):
        for proj in sorted(os.listdir(WORKSPACE_DIR)):
            if proj in ("logs",) or proj.startswith("."):
                continue
            pdir = os.path.join(WORKSPACE_DIR, proj)
            idir = os.path.join(pdir, "input")
            if not os.path.isdir(idir):
                continue
            for name in sorted(os.listdir(idir)):
                if not name.endswith(".md"):
                    continue
                rid = name[:-3]
                key = f"{proj}/{rid}"
                if key in st:
                    continue
                vd = ensure_versions(proj)
                meta = _parse_req_meta(os.path.join(idir, name))
                ver = meta["version"] or vd.get("current", "v1.0.0")
                if ver not in [x["name"] for x in vd["versions"]]:
                    vd["versions"].append({"name": ver, "status": "planning",
                                           "iterations": [], "reqs": [], "released_at": None})
                for x in vd["versions"]:
                    if x["name"] == ver and rid not in x.get("reqs", []):
                        x.setdefault("reqs", []).append(rid)
                write_versions(proj, vd)
                st[key] = {
                    "status": "pending",
                    "round": 0,
                    "max_rounds": DEFAULT_MAX_ROUNDS,
                    "forced": False,
                    "analysis": None,
                    "reviews": [],
                    "failures": 0,
                    "version": ver,
                    "iteration": meta["iteration"],
                    "depends_on": meta["depends_on"],
                    "stages": new_stages(),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
                registered.append(key)
                log(f"REGISTER {key} status=pending round=0 project={proj} version={ver}")
    # 兼容旧结构：workspace/input/<project>/*.md 与平铺 input/<req_id>.md（迁移前）
    legacy_input = os.path.join(WORKSPACE_DIR, "input")
    if os.path.isdir(legacy_input):
        for proj in sorted(os.listdir(legacy_input)):
            pdir = os.path.join(legacy_input, proj)
            if os.path.isdir(pdir):
                for name in sorted(os.listdir(pdir)):
                    if not name.endswith(".md"):
                        continue
                    rid = name[:-3]
                    key = f"{proj}/{rid}"
                    if key in st:
                        continue
                    st[key] = {
                        "status": "pending",
                        "round": 0,
                        "max_rounds": DEFAULT_MAX_ROUNDS,
                        "forced": False,
                        "analysis": None,
                        "reviews": [],
                        "failures": 0,
                        "stages": new_stages(),
                        "created_at": now_iso(),
                        "updated_at": now_iso(),
                    }
                    registered.append(key)
                    log(f"REGISTER {key} status=pending round=0 project={proj} (legacy input/)")
            elif pdir.endswith(".md"):
                rid = proj[:-3]
                key = f"{DEFAULT_PROJECT}/{rid}"
                if key in st:
                    continue
                st[key] = {
                    "status": "pending",
                    "round": 0,
                    "max_rounds": DEFAULT_MAX_ROUNDS,
                    "forced": False,
                    "analysis": None,
                    "reviews": [],
                    "failures": 0,
                    "stages": new_stages(),
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
                registered.append(key)
                log(f"REGISTER {key} status=pending round=0 project={DEFAULT_PROJECT} (legacy flat)")
    return registered


def new_stages() -> dict:
    """初始化阶段链子状态（每阶段：state 四态机 + product/reviews + 审计时间线）。
    四态：claimed（tick 认领）→ working（执行者启动）→ reviewing（产出落盘/评审者启动）→ done（评审 PASS）。
    每阶段独立 round/product/reviews/state_since/timeline。"""
    d = {}
    for stg in STAGES:
        d[stg["name"]] = {"round": 0, "product": None, "reviews": [], "state": None,
                          "state_since": None, "timeline": []}
    for g in GATES:
        d[g["name"]] = {"round": 0, "product": None, "reviews": [], "state": None,
                        "state_since": None, "timeline": []}
    d[RELEASE["name"]] = {"round": 0, "product": None, "reviews": [], "state": None,
                          "state_since": None, "timeline": []}
    # req 阶段：顶层 status 表达（pending→analyzing→analyzed→approved），无 dir/角色，
    # 但为统一四态机/巡检（active_stage、guard_recovery 访问 stages['req']）保留占位子记录
    d["req"] = {"round": 0, "product": None, "reviews": [], "state": None,
                "state_since": None, "timeline": []}
    return d


def ensure_stages(e: dict) -> dict:
    """兼容旧 entry（阶段化改造前无 stages 字段）：缺失时初始化。"""
    if "stages" not in e or not isinstance(e.get("stages"), dict):
        e["stages"] = new_stages()
    for stg in STAGES + GATES + [RELEASE]:
        s = e["stages"].setdefault(stg["name"], {"round": 0, "product": None, "reviews": []})
        s.setdefault("state", None)
        s.setdefault("state_since", None)
        s.setdefault("timeline", [])
    # req 占位子记录（同 new_stages 注释：顶层 status 表达，四态/巡检统一访问）
    s = e["stages"].setdefault("req", {"round": 0, "product": None, "reviews": []})
    s.setdefault("state", None)
    s.setdefault("state_since", None)
    s.setdefault("timeline", [])
    return e["stages"]


# ---- 阶段四态迁移校验表（set_status 严格强制）----
# state 迁移：claimed → working → reviewing → done；reviewing → working（FAIL 打回）
def _stage_state(st, rid, stage):
    e = st.get(rid)
    if not e:
        return None
    return ensure_stages(e)[stage]["state"]


def norm_product(p: str) -> str:
    """规范化产物路径：统一为相对 WORKSPACE_DIR 的路径（去 workspace/ 前缀、去绝对路径）。
    防 worker 传参不规范（如带 workspace/ 前缀）导致归档/展示路径风格不一致。"""
    if not p:
        return p
    p = p.strip()
    if os.path.isabs(p):
        try:
            p = os.path.relpath(p, WORKSPACE_DIR)
        except ValueError:
            pass
    for prefix in ("workspace/", "./"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p


def set_stage_state(st: dict, rid: str, stage: str, state: str, product: str = None) -> tuple:
    """设置阶段状态（统一入口，严格迁移校验）。返回 (ok, err_msg)。
    state ∈ working / reviewing / done；claimed 由 claim() 内部设置，不对外开放。
    同步派生顶层 status；记录 timeline 与 product。"""
    e = st.get(rid)
    if not e:
        return False, f"{rid} 不存在"
    stages = ensure_stages(e)
    if stage not in stages:
        return False, f"未知阶段 {stage}"
    s = stages[stage]
    cur = s.get("state")
    now = now_iso()
    # ---- 严格迁移校验 ----
    if state == "working":
        # None = 老 entry 缺 stages 子记录（ensure_stages 补出的占位）→ 视为 claimed 放行
        if cur not in ("claimed", "reviewing", None):
            return False, f"{stage} 阶段当前状态 {cur!r} 不允许进入 working（仅 claimed/reviewing 可）"
    elif state == "reviewing":
        # 幂等豁免 product：req 阶段产出走 release_analyze（自带校验）；阶段链评审者启动（cur 已 reviewing）无产物
        if product is None and stage != "req" and cur != "reviewing":
            return False, "reviewing 必须携带产物路径（product）"
        if cur not in ("working", "reviewing"):
            return False, f"{stage} 阶段当前状态 {cur!r} 不允许进入 reviewing（仅 working 可；reviewing 幂等）"
        if product:
            s["product"] = norm_product(product)
    elif state == "done":
        if cur != "reviewing":
            return False, f"{stage} 阶段当前状态 {cur!r} 不允许进入 done（仅 reviewing 可）"
    else:
        return False, f"未知状态 {state!r}（working/reviewing/done）"
    # ---- 应用状态 ----
    s["state"] = state
    s["state_since"] = now
    s["timeline"] = s.get("timeline", []) + [{"t": now, "to": state}]
    # 注：round 在评审完成时递增（release_stage_review/巡检），进入 reviewing 不递增——
    # 保证阶段产物 r{N} 与评审产物 r{N}-review 轮次一致
    # ---- 派生顶层 status（兼容现有体系） ----
    if stage == "req":
        if state == "working":
            e["status"] = "analyzing"
        elif state == "reviewing":
            # 评审者启动幂等（顶层已是 reviewing，claim 置）→ 保持；仅旧体系分析师产出路径（analyzing）置 analyzed 等待评审
            if e.get("status") not in ("reviewing",):
                e["status"] = "analyzed"
        elif state == "done":
            e["status"] = "awaiting_user_confirm"  # v2：规格细化完成 → 用户评审（唯一拍板人）
    elif stage == RELEASE["name"]:
        e["status"] = "released" if state == "done" else "releasing"
    elif any(g["name"] == stage for g in GATES):
        e["status"] = f"{stage}_done" if state == "done" else f"{stage}_gating"
    else:
        if state == "done":
            e["status"] = f"{stage}_done"
        elif state == "reviewing":
            e["status"] = f"{stage}_reviewing"
        else:
            e["status"] = f"{stage}_designing"
    e["updated_at"] = now
    return True, ""


def prev_done_state(e: dict) -> str:
    """当前中间态所属阶段的上一完成态（回滚目标）。"""
    s = e["status"]
    if s == "analyzing":
        return "pending"
    if s == "reviewing":
        return "analyzed"
    if s == "releasing":
        last = [stg["name"] for stg in STAGES] + [g["name"] for g in GATES]
        return f"{last[-1]}_done" if last else "approved"
    # 阶段中间态：{stage}_{designing|reviewing|gating}
    stage, phase = s.rsplit("_", 1)
    if phase == "reviewing":
        return f"{stage}_designing"  # 评审卡死 → 重新产出
    # designing/gating → 该阶段之前的完成态
    prev_name = stage
    order = [stg["name"] for stg in STAGES] + [g["name"] for g in GATES]
    if prev_name in order:
        idx = order.index(prev_name)
        if idx == 0:
            return "approved"
        return f"{order[idx - 1]}_done"
    return "approved"


def rollback_entry(st: dict, rid: str, alarms: list, reason: str) -> None:
    """中间态回滚：回到该阶段的上一完成态；failures+1；达上限置 blocked。"""
    e = st[rid]
    was = e["status"]
    if was not in MID_STATES:
        return
    prev = prev_done_state(e)
    e["status"] = prev
    e["failures"] = int(e.get("failures", 0)) + 1
    clear_claim(e)
    e["updated_at"] = now_iso()
    log(f"RECOVER {rid} {was}->{prev} reason={reason} failures={e['failures']}")
    if e["failures"] >= MAX_FAILURES:
        e["status"] = "blocked"
        e["updated_at"] = now_iso()
        log(f"BLOCKED {rid} failures={e['failures']}")
        alarms.append(
            f"[BLOCKED] 需求 {rid} 连续失败 {e['failures']} 次，已停止流转。"
            f"排查：logs/worker-*.log 与 logs/pipeline.log；修复后运行 "
            f"python3 scripts/statectl.py requeue {rid} 重新入队。"
        )


def stale_recovery(st: dict) -> list:
    """回收卡死的 worker 认领（超时 + pid 存活检查）。返回新告警列表。
    仅处理"有 claim 字段"的中间态——release 后清 claim 的中间态是等待认领（正常），不回滚。"""
    alarms = []
    for rid, e in list(st.items()):
        if e.get("status") not in MID_STATES:
            continue
        claimed_at = e.get("claimed_at")
        if not claimed_at:
            continue  # 无 claim = 等待认领（阶段链的正常等待态），不是卡死
        try:
            t = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - t).total_seconds() / 60.0
        except ValueError:
            age_min = STALE_AFTER_MIN + 1  # 无法解析时间戳视为超时
        if age_min < STALE_AFTER_MIN:
            continue
        pid = e.get("worker_pid")
        if pid and pid_alive(pid):
            log(f"SKIP  {rid} worker pid={pid} 仍存活（慢任务，等待）")
            continue
        rollback_entry(st, rid, alarms, reason="stale")
    return alarms


_ROLE_ALIAS = {"analyst": "req-analyst", "reviewer": "req-reviewer"}


def find_claimable(st: dict, role: str = None):
    """找最老（updated_at 最早）的可认领需求。返回 (req_id, entry, action) 或 None。
    role 为 None = 任意角色；支持短名（analyst/reviewer → req-analyst/req-reviewer）。"""
    role = _ROLE_ALIAS.get(role, role)
    cands = []
    for rid, e in st.items():
        # 已认领（含等待评审/执行中）不参与认领竞争——next_action 已覆盖已认领态（供 build_worker_query 用），
        # 认领资格必须在此显式过滤，否则已认领需求会被再次返回导致 claim 失败
        if e.get("claimed_by") or e.get("claimed_at"):
            continue
        act = next_action(e)
        if not act:
            continue
        if role and act[0] != role:
            continue
        cands.append((e.get("updated_at", ""), rid, e, act))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    rid, e, act = cands[0][1], cands[0][2], cands[0][3]
    return rid, e, act


def claim(st: dict, rid: str, role: str) -> bool:
    """原子认领（compare-and-swap）：仅当 role 匹配 next_action 时迁入中间态并写 claim 字段。"""
    e = st.get(rid)
    if not e:
        return False
    role = _ROLE_ALIAS.get(role, role)
    act = next_action(e)
    if not act or act[0] != role:
        return False
    if e.get("claimed_by") or e.get("claimed_at"):
        return False  # 已有认领（等待/处理中）——阶段链 {stage}_reviewing 等状态 claim 后状态不变，必须查 claim 字段防重复认领
    _, stage, phase = act
    # req 阶段同样写 stages['req'] 四态（claimed），保证 set_status 迁移校验/巡检统一可用
    cur_state = ensure_stages(e)[stage].get("state")
    # 首次认领（None）设 claimed；重跑场景（requeue 后旧 done 终态残留，顶层已回到 {stage}_designing）
    # 同样重置为 claimed——否则残留 done 会被 set_status 严格迁移校验拒绝（done→working ❌，tetris requeue 实测）。
    # working/reviewing（等待/重做/评审 FAIL 打回）不覆盖。
    if cur_state is None or (phase == "design" and cur_state == "done"):
        s = ensure_stages(e)[stage]
        s["state"] = "claimed"
        s["state_since"] = now_iso()
        s.setdefault("timeline", []).append({"t": now_iso(), "to": "claimed"})
    if phase == "design":
        new_state = "analyzing" if stage == "req" else f"{stage}_designing"
    elif phase == "review":
        new_state = "reviewing" if stage == "req" else f"{stage}_reviewing"
    elif phase == "gate":
        new_state = f"{stage}_gating"
    else:  # release
        new_state = "releasing"
    log(f"CLAIM {rid} by={role} from={e['status']}")
    e["status"] = new_state
    e["claimed_by"] = role
    e["claimed_at"] = now_iso()
    e["worker_pid"] = 0  # spawn 后由 setpid 填充
    e["updated_at"] = now_iso()
    return True


def build_worker_query(role: str, key: str, e: dict):
    """构造下半部 worker 的启动指令。返回 (round_n, query)。key 格式 '<project>/<req_id>'。"""
    project, rid = split_key(key)
    role = _ROLE_ALIAS.get(role, role)
    act = next_action(e)
    if not act or act[0] != role:
        raise RuntimeError(f"角色 {role} 与需求 {key} 当前状态 {e.get('status')} 不匹配")
    _, stage, phase = act
    ensure_stages(e)
    cn = ROLE_CN.get(role, role)
    rolefile = ROLE_FILES.get(role, f"roles/{role}.md")
    # ---- 需求阶段（向后兼容：round 在顶层） ----
    if stage == "req":
        if phase == "design":
            n = int(e["round"]) + 1
            out = rel_analysis(project, rid, n)
            q = [
                f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 完成需求 {key}（项目 {project}）的第 {n} 轮分析/修改。",
                "启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {key} req working（标记执行中）；",
                "输入文件：",
                f"- 需求原文：{rel_input(project, rid)}",
            ]
            if e.get("analysis"):
                q.append(f"- 上一版分析（修改轮必读）：{e['analysis']}")
            if e.get("reviews"):
                q.append(f"- 最新评审意见（修改轮必须逐条回应）：{e['reviews'][-1]}")
            q += [
                "任务：",
                "1. 按角色文件的输出模板与工作原则产出本轮分析报告；",
                f"2. 写入 {out}；",
                f"3. 运行 python3 scripts/statectl.py release_analyze {key} {out} 完成状态更新（该命令会校验产物存在并置为等待评审）；",
                "4. 完成后无需汇报，过程留痕在 worker 日志即可。",
            ]
            return n, "\n".join(q)
        else:  # review
            n = int(e["round"]) + 1
            out = rel_review(project, rid, n)
            analysis_file = e.get("analysis") or rel_analysis(project, rid, n)
            q = [
                f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 评审需求 {key}（项目 {project}）的第 {n} 轮分析。",
                "启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {key} req reviewing（标记评审中，幂等）；",
                "输入文件：",
                f"- 需求原文：{rel_input(project, rid)}",
                f"- 分析报告：{analysis_file}",
                f"注意：本需求 max_rounds={e.get('max_rounds', DEFAULT_MAX_ROUNDS)}，第 {n} 轮仍 FAIL 将由状态机自动强制归档，你无需关心。",
                "任务：",
                "1. 按角色文件的检查清单与输出模板评审；",
                f"2. 结论 PASS 或 FAIL，写入 {out}；",
                f"3. 运行 python3 scripts/statectl.py release_review {key} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
                "4. 完成后无需汇报。",
            ]
            return n, "\n".join(q)
    # ---- 阶段链（plan/testplan/code/test/quality/security/release） ----
    cfg = stage_cfg(stage)
    assert cfg is not None, f"未知阶段 {stage}"
    n = int(e["stages"].get(stage, {}).get("round", 0)) + 1
    prev_products = stage_inputs(e)  # 本阶段的输入产物（需求原文 + 上游终版）
    if phase == "design":
        out = rel_stage_product(cfg, project, rid, n)
        prev_review = e["stages"].get(stage, {}).get("reviews") or []
        if cfg.get("kind") == "dir":
            task1 = f"1. 按角色文件的输出模板与工作原则产出本阶段成果；在 {out} 目录内创建全部源码/产物文件（文件集，含 README 说明）；"
        else:
            task1 = "1. 按角色文件的输出模板与工作原则产出本阶段成果；"
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 完成需求 {key}（项目 {project}）的【{stage}】阶段第 {n} 轮产出。",
            f"启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {key} {stage} working（标记执行中）；",
            "输入文件：",
            *[f"- {desc}：{p}" for desc, p in prev_products],
        ]
        if prev_review:
            q.append(f"- 本阶段上一轮评审意见（修改轮必须逐条回应）：{prev_review[-1]}")
        q += [
            "任务：",
            task1,
            f"2. 产物写入 {out}；",
            f"3. 运行 python3 scripts/statectl.py set_status {key} {stage} reviewing {out} 完成状态更新（标记待评审，命令会校验产物存在并严格校验状态迁移）；",
            "4. 完成后无需汇报，过程留痕在 worker 日志即可。",
        ]
        return n, "\n".join(q)
    if phase == "review":
        out = rel_stage_review(cfg, project, rid, n)
        product = e["stages"].get(stage, {}).get("product")
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 评审需求 {key}（项目 {project}）的【{stage}】阶段第 {n} 轮成果。",
            f"启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {key} {stage} reviewing（标记评审中，幂等）；",
            "输入文件：",
            f"- 本阶段成果：{product}",
            *[f"- {desc}：{p}" for desc, p in prev_products],
            "任务：",
            "1. 按角色文件的检查清单与输出模板评审；",
            f"2. 结论 PASS 或 FAIL，写入 {out}；",
            f"3. 运行 python3 scripts/statectl.py release_stage_review {key} {stage} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报。",
        ]
        return n, "\n".join(q)
    if phase == "gate":
        out = rel_stage_product(cfg, project, rid, n)
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 对需求 {key}（项目 {project}）执行【{stage}】门禁评审（第 {n} 轮）。",
            f"启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {key} {stage} working（标记门禁执行中）；",
            "输入文件：",
            *[f"- {desc}：{p}" for desc, p in prev_products],
            "任务：",
            "1. 按角色文件的检查清单与输出模板完成门禁评审；",
            f"2. 结论 PASS 或 FAIL，写入 {out}；",
            f"3. 运行 python3 scripts/statectl.py release_gate {key} {stage} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报。",
        ]
        return n, "\n".join(q)
    # release（终态：打包交付）
    out = rel_stage_product(RELEASE, project, rid, n)
    q = [
        f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 为需求 {key}（项目 {project}）执行发布（第 {n} 轮）。",
        f"启动时（第 0 步）：运行 python3 scripts/statectl.py set_status {key} {RELEASE['name']} working（标记发布执行中）；",
        "输入文件：",
        *[f"- {desc}：{p}" for desc, p in prev_products],
        "任务：",
        f"1. 在 {out} 目录内创建完整发布包（目录自动创建）：发布说明.md（版本/变更/质量安全结论/已知限制/回滚方案）+ 用户指南.md（安装/运行/使用）+ 打包产物 {rid}-v{{版本}}.tar.gz（代码文件集压缩，含 README 与依赖说明）+ SHA256SUMS（校验和）+ 可用性自检记录（如环境允许实际运行测试/启动冒烟）；",
        f"2. 运行 python3 scripts/statectl.py release_release {key} {out} 完成状态更新（该命令校验产物目录存在并生成最终交付物归档）；",
        "3. 完成后无需汇报。",
    ]
    return n, "\n".join(q)


def stage_inputs(e: dict) -> list:
    """当前状态阶段的输入产物清单 [(描述, 相对路径), ...]（需求原文 + 上游各阶段终版）。"""
    s = e["status"]
    outs = []
    if e.get("analysis"):
        # analysis/{project}/{rid}-r{N}.md → input/{project}/{rid}.md
        parts = e["analysis"].split("/")
        if len(parts) >= 3 and parts[0] == "analysis":
            outs.append(("需求原文", f"input/{parts[1]}/{parts[2].rsplit('-', 1)[0]}.md"))
        elif e.get("reviews"):
            rp = e["reviews"][0].split("/")
            if len(rp) >= 3:
                outs.append(("需求原文", f"input/{rp[1]}/{rp[2].rsplit('-', 1)[0]}.md"))
    if e.get("analysis"):
        outs.append(("需求分析（approved 终版）", e["analysis"]))
    for stg in STAGES:
        prod = (e.get("stages") or {}).get(stg["name"], {}).get("product")
        if prod:
            outs.append((f"{stg['name']} 阶段终版", prod))
    for g in GATES:
        prod = (e.get("stages") or {}).get(g["name"], {}).get("product")
        if prod:
            outs.append((f"{g['name']} 门禁结论", prod))
    return outs


def spawn_worker(role: str, key: str, round_n: int, query: str) -> int:
    """setsid 拉起下半部 worker（独立会话，脱离 cron 进程组，不受 3 分钟限制）。"""
    project, rid = split_key(key)
    role = _ROLE_ALIAS.get(role, role)
    model, provider = ROLE_MODELS.get(role, (ANALYST_MODEL, ANALYST_PROVIDER))
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(project_log_dir(project), exist_ok=True)  # 项目日志目录（it/st 迭代级 spawn 时可能尚未建）
    logf = open(os.path.join(project_log_dir(project), worker_log_name(project, rid, round_n, role)), "ab")
    cmd = ["hermes", "chat", "-q", query, "-m", model, "-Q"]
    if provider:
        cmd += ["--provider", provider]
    p = subprocess.Popen(
        cmd,
        cwd=WORKDIR,
        stdin=subprocess.DEVNULL,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # 新会话：父进程（cron）被杀不影响 worker
    )
    log(f"SPAWN {key} worker={role} pid={p.pid} model={model} round={round_n}")
    return p.pid


def drain_alarms(new_alarms: list) -> str:
    """读取待投递告警（含 worker 侧写入的），输出并清空。返回要打印的文本。"""
    lines = list(new_alarms)
    if os.path.exists(ALARM_FILE):
        with open(ALARM_FILE, encoding="utf-8") as f:
            lines += [l.strip() for l in f if l.strip()]
    with open(ALARM_FILE, "w", encoding="utf-8") as f:
        f.write("")
    return "\n".join(lines)


def write_artifact(key: str, e: dict) -> None:
    """归档：approved（需求评审）或 released（完整交付物）。
    key 格式 '<project>/<req_id>' → artifacts/<project>/<req_id>.md。"""
    project, rid = split_key(key)
    os.makedirs(os.path.join(project_dir(project), "artifacts"), exist_ok=True)
    reviews = e.get("reviews") or []
    forced = e.get("forced", False)
    status = e.get("status", "approved")
    stg_done = [n for n, s in (e.get("stages") or {}).items() if s.get("status") == "done"]
    is_released = status == "released"
    parts = [f"# 需求交付归档：{rid}", "",
             f"> 项目：{project} ｜ 归档：{rel_artifact(project, rid)}", ""]
    # 结论摘要区（快速全貌：接手开发 / 审计核对的第一屏）
    parts += ["## 结论摘要", "",
              f"- 状态：**{status}**（{'⚠️ 达到轮次上限强制归档，需人工复核' if forced and not is_released else '完整交付' if is_released else '正常评审通过'}）",
              f"- 需求评审轮次：r{e.get('round', 1)}（共 {len(reviews)} 轮评审）",
              f"- 阶段进度：{' → '.join(stg_done) if stg_done else '（未进入阶段链）'}"
              + (f" ｜ 最终发布：`{e['stages']['release']['product']}`" if is_released and e.get('stages', {}).get('release', {}).get('product') else ""),
              f"- 归档时间：{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
              ""]
    if is_released:
        parts += [f"- 最终分析：`{e.get('analysis', '')}`",
                  "- 阶段产物：" + ("；".join(f"{n}=`{s.get('product')}`" for n, s in (e.get('stages') or {}).items() if s.get("product")) or "（无）"),
                  "- 发布说明：`" + e["stages"]["release"]["product"] + "`", ""]
    parts += ["> 接手开发请以【需求原文 + 最终分析 + 各阶段终版产物 + 门禁结论】为准；过程轮次意见为过程记录（已解决或已驳回）。",
              ""]
    orig = abs_input(project, rid)
    if os.path.exists(orig):
        with open(orig, encoding="utf-8") as f:
            parts += ["## 需求原文", "", f.read().strip(), ""]
    if e.get("analysis"):
        ap = os.path.join(WORKSPACE_DIR, e["analysis"])
        if os.path.exists(ap):
            with open(ap, encoding="utf-8") as f:
                parts += [f"## 最终分析（{e['analysis']}）", "", f.read().strip(), ""]
    if reviews:
        parts += [f"## 需求评审历史（{len(reviews)} 轮）", ""]
        for rp in reviews:
            full = os.path.join(WORKSPACE_DIR, rp)
            if os.path.exists(full):
                with open(full, encoding="utf-8") as f:
                    parts += [f"### {rp}", "", f.read().strip(), ""]
    # 阶段产物与评审（完整交付物）
    for stg in STAGES + GATES:
        s = (e.get("stages") or {}).get(stg["name"], {})
        prod = s.get("product")
        if prod:
            full = os.path.join(WORKSPACE_DIR, prod)
            if os.path.isdir(full):  # 文件集产物（代码/测试目录）：列出文件树并嵌入文本文件
                files = sorted(os.listdir(full))
                parts += [f"## {stg['name']} 阶段终版（{prod}）", "",
                          "文件清单：`" + "`, `".join(files) + "`", ""]
                for fn in files:
                    fp = os.path.join(full, fn)
                    if os.path.isfile(fp):
                        try:
                            with open(fp, encoding="utf-8") as f:
                                parts += [f"### {prod}{fn}", "", f.read().strip(), ""]
                        except (UnicodeDecodeError, OSError):
                            parts += [f"### {prod}{fn}", "", "（二进制文件，仅列清单）", ""]
            elif os.path.exists(full):
                with open(full, encoding="utf-8") as f:
                    parts += [f"## {stg['name']} 阶段终版（{prod}）", "", f.read().strip(), ""]
        for rp in s.get("reviews", []):
            full = os.path.join(WORKSPACE_DIR, rp)
            if os.path.exists(full):
                with open(full, encoding="utf-8") as f:
                    parts += [f"### {stg['name']} 评审（{rp}）", "", f.read().strip(), ""]
    if forced:
        parts += ["## 备注", "本需求达到轮次上限被强制归档（forced=true），仍有未解决意见，请人工复核。"]
    with open(abs_artifact(project, rid), "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    log(f"ARCHIVE {key} file={rel_artifact(project, rid)} status={status}")


# ---------------- 上半部 tick ----------------

def _tick_common() -> int:
    """通用 tick（P4 并发核心）：全局锁注册（只注册不写盘）→ 每项目锁调度。
    项目间并发（不同项目由不同 tick/进程并行处理），同项目串行（项目锁 + claim 防重复）。
    注册的新条目随各项目锁合并写入（避免阶段 1 全量写覆盖其他 tick 的项目更新——并发安全）。"""
    alarms = []
    # 手动暂停检查：halt 标记存在 → 整体跳过调度（不认领不 spawn，静默；已 spawn 的 worker 不受影响）。
    # 注意：guard 只管 cron job enabled，不干预此标记——halt 是流水线唯一暂停方式（cron pause 会被 guard 自动恢复）。
    if os.path.exists(PAUSE_FILE):
        return 0
    # 阶段 1：全局锁注册（扫描全部项目 input/，仅内存注册；新条目随项目锁落盘）
    with acquire_lock() as _:
        st_all = read_status()
        register_new_inputs(st_all)
    # 阶段 2：每项目锁调度（项目间并行；注册增量合并写入）
    projects = [p for p in sorted(os.listdir(WORKSPACE_DIR))
                if os.path.isdir(os.path.join(WORKSPACE_DIR, p))
                and p not in ("logs",) and not p.startswith(".")]
    for proj in projects:
        with acquire_lock(project=proj) as _:
            ensure_project(proj)  # 新建项目：先建骨架（spawn_worker 需要项目 logs/ 存在）
            pst = read_status(proj)
            if not pst:
                pst = {}
            # 合并本项目的新注册条目（阶段 1 的内存注册，不覆盖已存在）
            for key, e in st_all.items():
                if key.startswith(proj + "/") and key not in pst:
                    pst[key] = e
            if not pst:
                continue
            _apply_deps(pst, proj)  # 依赖调度：waiting 挂起 / 依赖满足转 pending
            alarms += stale_recovery(pst)
            alarms += guard_recovery(pst)  # 巡检：worker 漏设状态/卡死的自动补正
            vd = read_versions(proj)
            _advance_v2(proj, vd, pst, alarms)  # 版本/迭代状态机推进
            _schedule_it_st(proj, vd, pst, alarms)  # 迭代 IT / 版本 ST 调度
            found = find_claimable(pst)  # 任意角色（一次认领一个，防唤醒风暴）
            if found:
                rid, e, act = found
                role = act[0]
                if claim(pst, rid, role):
                    n, query = build_worker_query(role, rid, e)
                    pid = spawn_worker(role, rid, n, query)
                    pst[rid]["worker_pid"] = pid
            write_status(pst, project=proj)
    out = drain_alarms(alarms)
    if out:
        print(out)  # 非空才输出（no_agent：空 stdout = 静默）
    return 0


def analyst_tick() -> int:
    """分析师 tick（兼容保留）：与 worker_tick 同质调度，项目锁保证无竞态。"""
    return _tick_common()


def reviewer_tick() -> int:
    """评审 tick（兼容保留）：与 worker_tick 同质调度，项目锁保证无竞态。"""
    return _tick_common()


def parse_conclusion(path: str) -> str:
    """从评审/门禁产物解析结论（PASS/FAIL/UNKNOWN）。查文件头部结论区。"""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(3000)
    except OSError:
        return "UNKNOWN"
    up = head.upper()
    # 结论标记（优先匹配"结论：**PASS**"类明确标记，避免核对表里的 PASS/FAIL 字样误判）
    if "结论" in head:
        zone = head[head.index("结论"): head.index("结论") + 200]
        if "PASS" in zone.upper() or "通过" in zone:
            return "PASS"
        if "FAIL" in zone.upper() or "不通过" in zone:
            return "FAIL"
    if "**PASS**" in up or "PASS" in up[:200]:
        return "PASS"
    if "**FAIL**" in up or "FAIL" in up[:200]:
        return "FAIL"
    return "UNKNOWN"


def active_stage(e: dict) -> tuple:
    """由顶层 status 反推当前活动阶段 (stage, 四态 state)。四态存 stages[stage].state（真值），顶层仅显示。"""
    s = e.get("status")
    if s in ("pending", "needs_fix", "analyzed", "approved", "blocked", "released"):
        return None, None
    stages = ensure_stages(e)
    if s == "analyzing":
        return "req", stages["req"].get("state") or "working"
    if s == "reviewing":
        return "req", stages["req"].get("state") or "reviewing"
    if s == "releasing":
        return "release", stages["release"].get("state") or "working"
    for stg in STAGES + GATES:
        name = stg["name"]
        if s in (f"{name}_designing", f"{name}_gating"):
            return name, stages[name].get("state") or "working"
        if s == f"{name}_reviewing":
            return name, stages[name].get("state") or "reviewing"
        if s == f"{name}_done":
            return name, "done"
    return None, None


def guard_recovery(st: dict) -> list:
    """巡检兜底（核心可靠性机制）：worker 漏设状态的自动补正，不依赖 worker 进程。
    - 阶段 claimed/working/reviewing 超时（state_since > STALE_AFTER_MIN）：
      - claimed/working：阶段产物存在 → 补 reviewing（干完没设状态）；不存在 → worker 存活则等待，否则回滚
      - reviewing：评审产物存在 → 解析结论（PASS→done / FAIL/UNKNOWN→working 重做）；不存在 → worker 存活则等待，否则回滚
    返回新告警列表。"""
    alarms = []
    for rid, e in list(st.items()):
        stage, state = active_stage(e)
        if not stage or state not in ("claimed", "working", "reviewing"):
            continue
        s = ensure_stages(e)[stage]
        since = s.get("state_since")
        age = None
        if since:
            try:
                t = datetime.fromisoformat(since.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - t).total_seconds() / 60.0
            except ValueError:
                age = STALE_AFTER_MIN + 1
        if age is None or age < STALE_AFTER_MIN:
            continue
        project, rid2 = split_key(rid)
        n = int(s.get("round", 0)) + 1
        cfg = stage_cfg(stage)
        pid = e.get("worker_pid")
        if state == "reviewing":
            rp = rel_stage_review(cfg, project, rid2, n) if cfg else rel_review(project, rid2, n)
            full_rp = os.path.join(WORKSPACE_DIR, rp)
            if os.path.exists(full_rp):
                conclusion = parse_conclusion(full_rp)
                s["round"] = int(s.get("round", 0)) + 1  # 评审完成：轮次递增
                if conclusion == "PASS":
                    ok, err = set_stage_state(st, rid, stage, "done")
                    log(f"GUARD {rid} {stage} reviewing->done (auto, PASS)")
                    if stage in ("req", RELEASE["name"]):
                        write_artifact(rid, st[rid])  # 终态自动归档
                else:
                    if int(s.get("round", 0)) >= int(e.get("max_rounds", DEFAULT_MAX_ROUNDS)):
                        e["status"] = "blocked"
                        with open(ALARM_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[BLOCKED] 需求 {rid} 的【{stage}】阶段第 {s['round']} 轮仍未通过（巡检判定），已达 max_rounds，请人工介入（requeue {rid} 重跑）。\n")
                        log(f"GUARD {rid} {stage} -> blocked (auto, max_rounds)")
                    else:
                        ok, err = set_stage_state(st, rid, stage, "working")
                        log(f"GUARD {rid} {stage} reviewing->working (auto, conclusion={conclusion})")
            else:
                if pid and pid_alive(pid):
                    log(f"GUARD {rid} {stage} reviewing 超时但 worker 存活（等待）")
                    continue
                rollback_entry(st, rid, alarms, reason="guard-timeout")
        else:  # claimed / working：查阶段产物
            prod = rel_stage_product(cfg, project, rid2, n) if cfg else rel_analysis(project, rid2, n)
            if os.path.exists(os.path.join(WORKSPACE_DIR, prod)):
                ok, err = set_stage_state(st, rid, stage, "reviewing", prod)
                log(f"GUARD {rid} {stage} {state}->reviewing (auto, product exists)")
            else:
                if pid and pid_alive(pid):
                    log(f"GUARD {rid} {stage} {state} 超时但 worker 存活（等待）")
                    continue
                rollback_entry(st, rid, alarms, reason="guard-timeout")
    return alarms


def worker_tick() -> int:
    """通用阶段 tick（主调度）：全局锁注册 → 每项目锁 stale/巡检/认领/spawn。
    项目间并发、同项目串行；一次认领一个（最老优先，防唤醒风暴）。"""
    return _tick_common()


def weekly_tick() -> int:
    issues = []
    with acquire_lock() as _:
        st = read_status()
        for key, e in sorted(st.items()):
            project, rid = split_key(key)
            s = e.get("status")
            if s in ("approved", "released"):
                if not os.path.exists(abs_artifact(project, rid)):
                    issues.append(f"[AUDIT] 需求 {key} 已 {s} 但缺 {rel_artifact(project, rid)}")
                if e.get("forced"):
                    issues.append(f"[AUDIT] 需求 {key} 为强制归档（forced），请人工复核 {rel_artifact(project, rid)}")
            elif s == "blocked":
                issues.append(f"[AUDIT] 需求 {key} 处于 blocked，需人工介入（python3 scripts/statectl.py requeue {key}）")
            elif s in MID_STATES:
                issues.append(f"[AUDIT] 需求 {key} 滞留 {s}（中间态不应跨周存在）")
        # 未登记 input 检查（新结构 workspace/<proj>/input/ + 兼容旧 input/）
        for proj in sorted(os.listdir(WORKSPACE_DIR)):
            if proj in ("logs",) or proj.startswith(".") or not os.path.isdir(os.path.join(WORKSPACE_DIR, proj)):
                continue
            idir = os.path.join(WORKSPACE_DIR, proj, "input")
            if os.path.isdir(idir):
                for name in sorted(os.listdir(idir)):
                    if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                        issues.append(f"[AUDIT] {proj}/input/{name} 未登记（下个 tick 会自动注册）")
        legacy_input = os.path.join(WORKSPACE_DIR, "input")
        if os.path.isdir(legacy_input):
            for proj in sorted(os.listdir(legacy_input)):
                pdir = os.path.join(legacy_input, proj)
                if os.path.isdir(pdir):
                    for name in sorted(os.listdir(pdir)):
                        if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                            issues.append(f"[AUDIT] input/{proj}/{name} 未登记（下个 tick 会自动注册）")
                elif pdir.endswith(".md") and f"{DEFAULT_PROJECT}/{proj[:-3]}" not in st:
                    issues.append(f"[AUDIT] input/{proj} 未登记（下个 tick 会自动注册）")
    if issues:
        print("\n".join(issues))
    return 0


# ---------------- 配额巡检 tick（cron no_agent，每 30 分钟） ----------------

QUOTA_SCRIPT = os.path.join(SCRIPTS_DIR, "check_minimax_quota.py")


def _format_beijing(ts_ms: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.utcfromtimestamp(ts_ms / 1000) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def quota_tick() -> int:
    """调用 check_minimax_quota.py，根据退出码生成告警；脚本不可用或调用失败时静默（避免与上游重复告警）。

    退出码语义（脚本约定）：
      0 = 健康（5h 窗口 ≥ 30% 且 周配额 ≥ 50%）
      1 = 紧张（5h 窗口 < 30% 或 周配额 < 50%）
      2 = 严重受限（5h 窗口 < 10%）
      3 = 调用失败（凭据/网络/格式）
    """
    if not os.path.exists(QUOTA_SCRIPT):
        return 0
    try:
        r = subprocess.run([sys.executable, QUOTA_SCRIPT, "--json"], capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, Exception):
        return 0
    code = r.returncode
    if code == 0:
        return 0  # 健康：不输出
    if code == 3:
        # 调用失败：静默（凭据可能没配，不刷屏）
        return 0
    # code 1 (紧张) 或 2 (严重受限)：解析 JSON 取关键数值
    try:
        import json as _json
        data = _json.loads(r.stdout)
        general = next((m for m in data.get("model_remains", []) if m.get("model_name") == "general"), None)
    except Exception:
        general = None
    if general is None:
        return 0
    interval_pct = general.get("current_interval_remaining_percent", 0)
    weekly_pct = general.get("current_weekly_remaining_percent", 0)
    reset_bj = _format_beijing(general.get("end_time", 0))
    if code == 2:
        level = "🔴 严重受限"
        hint = "建议暂停流水线（hermes cron pause <job_id>）避免无意义消耗 5h 窗口"
    else:
        level = "🟡 紧张"
        hint = "流水线跑 code/test 阶段密集调用时可能触发 429；持续 BLOCKED 模式 C 时优先排除配额"
    print(
        f"[QUOTA] minimax {level}\n"
        f"  5h 窗口剩余: {interval_pct}%\n"
        f"  周配额剩余:   {weekly_pct}%\n"
        f"  5h 窗口重置: {reset_bj}（北京时间）\n"
        f"  建议: {hint}"
    )
    return 0


# ---------------- 下半部 release（worker 内调用） ----------------

def release_analyze(rid: str, product: str) -> int:
    """worker 完成分析后调用：校验产物 → analyzing→analyzed，清 claim。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e or e["status"] != "analyzing":
            print(f"release_analyze: {rid} 状态不是 analyzing，拒绝", file=sys.stderr)
            return 1
        full = os.path.join(WORKSPACE_DIR, product)
        if not os.path.exists(full):
            # 产物缺失 → 视为失败：自动回滚，交由重试/stale 兜底
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_analyze: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        e["status"] = "awaiting_user_confirm"  # v2：分析产出 → 用户评审（唯一拍板人）
        e["analysis"] = product
        e["round"] = int(e.get("round", 0))  # round 在评审时递增
        clear_claim(e)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"ANALYZE {rid} round={e['round']} file={product}")
        log(f"STATE  {rid} analyzing->awaiting_user_confirm")
    return 0


def release_review(rid: str, product: str, conclusion: str) -> int:
    """worker 完成评审后调用：校验产物 → round+1 → approved / needs_fix / 强制归档。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print(f"release_review: conclusion 必须为 PASS 或 FAIL，收到 {conclusion!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e or e["status"] != "reviewing":
            print(f"release_review: {rid} 状态不是 reviewing，拒绝", file=sys.stderr)
            return 1
        full = os.path.join(WORKSPACE_DIR, product)
        if not os.path.exists(full):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_review: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        e["round"] = int(e.get("round", 0)) + 1
        e["reviews"] = e.get("reviews", []) + [product]
        if conclusion == "PASS":
            e["status"] = "approved"
            # 同步写 stages.req.state=done，让 _find_block_stage 能识别 req 已通过（避免 requeue 兜底回 req 全链重置）。
            # 这里不用 set_stage_state：它的 done 校验要求 cur=reviewing，但 req 评审走的是顶层 reviewing（stages.req 可能从未 working），
            # 我们只在 done 字段上写一个事实标记（_find_block_stage 只读这个字段判断是否 done）。
            try:
                stages = ensure_stages(e)
                req_s = stages.get("req") or {"round": 0, "product": None, "reviews": [], "timeline": []}
                req_s["state"] = "done"
                req_s["state_since"] = now_iso()
                req_s.setdefault("timeline", []).append({"t": now_iso(), "to": "done"})
                stages["req"] = req_s
            except Exception:
                pass  # 老数据兜底失败不阻塞主流程
        else:
            if e["round"] >= int(e.get("max_rounds", DEFAULT_MAX_ROUNDS)):
                e["status"] = "approved"
                e["forced"] = True
                project, _ = split_key(rid)
                with open(ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(
                        f"[FORCED] 需求 {rid} 第 {e['round']} 轮仍 FAIL，已达 max_rounds，"
                        f"已强制归档（{rel_artifact(project, rid)}），请人工复核未解决意见。\n"
                    )
            else:
                e["status"] = "needs_fix"
        clear_claim(e)
        e["updated_at"] = now_iso()
        if e["status"] == "approved":
            write_artifact(rid, e)
        write_status(st)
        log(f"REVIEW  {rid} round={e['round']} file={product} conclusion={conclusion}")
        log(f"STATE  {rid} reviewing->{e['status']}{' forced' if e.get('forced') else ''}")
    return 0


# ---------------- 阶段链 release（plan/testplan/code/test/quality/security/release） ----------------

def release_stage_design(rid: str, stage: str, product: str) -> int:
    """阶段产出完成后调用（兼容旧 worker/脚本）：内部 = set_status reviewing + product。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"release_stage_design: {rid} 不存在", file=sys.stderr)
            return 1
        ok, err = set_stage_state(st, rid, stage, "reviewing", product)
        if not ok:
            print(f"release_stage_design: {err}", file=sys.stderr)
            return 1
        if not os.path.exists(os.path.join(WORKSPACE_DIR, product)):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_stage_design: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        clear_claim(e)
        write_status(st)
        log(f"STAGE  {rid} {stage} design round={e['stages'][stage]['round']} file={product}")
    return 0


def release_stage_review(rid: str, stage: str, product: str, conclusion: str) -> int:
    """阶段评审完成后调用（兼容旧 worker/脚本）：PASS → set done；FAIL → set working（轮次上限 → blocked）。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print(f"release_stage_review: conclusion 必须为 PASS 或 FAIL，收到 {conclusion!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"release_stage_review: {rid} 不存在", file=sys.stderr)
            return 1
        if not os.path.exists(os.path.join(WORKSPACE_DIR, product)):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_stage_review: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        s = ensure_stages(e)[stage]
        s["reviews"] = s.get("reviews", []) + [product]
        s["round"] = int(s.get("round", 0)) + 1  # 评审完成：轮次递增（评审产物与阶段产物同轮）
        if conclusion == "PASS":
            ok, err = set_stage_state(st, rid, stage, "done")
            if not ok:
                print(f"release_stage_review: {err}", file=sys.stderr)
                return 1
            if stage == "req":
                write_artifact(rid, st[rid])
        else:
            if int(s.get("round", 0)) >= int(e.get("max_rounds", DEFAULT_MAX_ROUNDS)):
                e["status"] = "blocked"
                with open(ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[BLOCKED] 需求 {rid} 的【{stage}】阶段第 {s['round']} 轮评审仍 FAIL，已达 max_rounds，已停止流转，请人工介入（requeue {rid} 重跑）。\n")
            else:
                ok, err = set_stage_state(st, rid, stage, "working")
                if not ok:
                    print(f"release_stage_review: {err}", file=sys.stderr)
                    return 1
        clear_claim(e)
        write_status(st)
        log(f"REVIEW  {rid} {stage} round={s['round']} file={product} conclusion={conclusion}")
        log(f"STATE  {rid} {stage}->{e['status']}")
    return 0


def release_gate(rid: str, stage: str, product: str, conclusion: str) -> int:
    """门禁评审完成后调用（兼容旧 worker/脚本）：PASS → set done；FAIL → set working（轮次上限 → blocked）。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print(f"release_gate: conclusion 必须为 PASS 或 FAIL，收到 {conclusion!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"release_gate: {rid} 不存在", file=sys.stderr)
            return 1
        if not os.path.exists(os.path.join(WORKSPACE_DIR, product)):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_gate: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        s = ensure_stages(e)[stage]
        s["reviews"] = s.get("reviews", []) + [product]
        if conclusion == "PASS":
            ok, err = set_stage_state(st, rid, stage, "done")
            if not ok:
                print(f"release_gate: {err}", file=sys.stderr)
                return 1
        else:
            if int(s.get("round", 0)) >= int(e.get("max_rounds", DEFAULT_MAX_ROUNDS)):
                e["status"] = "blocked"
                with open(ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[BLOCKED] 需求 {rid} 的【{stage}】门禁第 {s['round']} 轮仍 FAIL，已达 max_rounds，已停止流转，请人工介入。\n")
            else:
                ok, err = set_stage_state(st, rid, stage, "working")
                if not ok:
                    print(f"release_gate: {err}", file=sys.stderr)
                    return 1
        clear_claim(e)
        write_status(st)
        log(f"GATE   {rid} {stage} round={s['round']} file={product} conclusion={conclusion}")
        log(f"STATE  {rid} {stage}->{e['status']}")
    return 0


def release_release(rid: str, product: str) -> int:
    """发布完成后调用（兼容旧 worker/脚本）：内部 = set_status done（released 终态 + 完整交付归档）。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"release_release: {rid} 不存在", file=sys.stderr)
            return 1
        ok, err = set_stage_state(st, rid, RELEASE["name"], "done")
        if not ok:
            print(f"release_release: {err}", file=sys.stderr)
            return 1
        if not os.path.exists(os.path.join(WORKSPACE_DIR, product)):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_release: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        e["stages"]["release"]["product"] = norm_product(product)
        clear_claim(e)
        write_artifact(rid, e)  # 完整交付物归档
        write_status(st)
        log(f"RELEASE {rid} round={e['stages']['release']['round']} file={product}")
        log(f"STATE  {rid} releasing->released")
    return 0


# ---------------- 人工/调试子命令 ----------------

def cmd_register() -> int:
    with acquire_lock() as _:
        st = read_status()
        reg = register_new_inputs(st)
        write_status(st)
    if reg:
        print("registered: " + ", ".join(reg))
    return 0


def cmd_stale() -> int:
    with acquire_lock() as _:
        st = read_status()
        alarms = stale_recovery(st)
        write_status(st)
        out = drain_alarms(alarms)
    if out:
        print(out)
    return 0


def cmd_next(role: str = None) -> int:
    with acquire_lock() as _:
        st = read_status()
        found = find_claimable(st, role)
    if found:
        rid, e, act = found
        print(f"{rid}\t{e['status']}\tnext={act[0]}（{act[1]}/{act[2]}）\tround={e['round']}\tmax_rounds={e.get('max_rounds')}")
    return 0


def cmd_claim(rid: str, role: str) -> int:
    with acquire_lock() as _:
        st = read_status()
        ok = claim(st, rid, role)
        write_status(st)
    print("claimed" if ok else f"claim 失败：{rid} 当前状态不可被 {role} 认领")
    return 0 if ok else 1


def cmd_setpid(rid: str, pid: str) -> int:
    with acquire_lock() as _:
        st = read_status()
        if rid in st:
            st[rid]["worker_pid"] = int(pid)
            write_status(st)
    return 0


def cmd_rollback(rid: str, reason: str = "manual") -> int:
    with acquire_lock() as _:
        st = read_status()
        if rid not in st or st[rid]["status"] not in MID_STATES:
            print(f"{rid} 不在中间态，无需回滚", file=sys.stderr)
            return 1
        alarms = []
        rollback_entry(st, rid, alarms, reason=reason)
        write_status(st)
        out = drain_alarms(alarms)
    if out:
        print(out)
    return 0


def cmd_record_product(rid: str, stage: str, product: str) -> int:
    """人工补记产物路径（合规替代直接改 status.json）：record_product {key} {stage} {产物路径}。
    仅补记 product（校验文件存在），不迁移状态——适用于评审已 PASS 但 product 漏记的场景。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        stages = e.get("stages") or {}
        s = stages.get(stage)
        if not s:
            print(f"阶段 {stage} 不存在（可选：req/plan/testplan/code/test/quality/security/release）", file=sys.stderr)
            return 1
        full = os.path.join(WORKSPACE_DIR, norm_product(product))
        if not os.path.exists(full):
            print(f"产物不存在: {full}", file=sys.stderr)
            return 1
        s["product"] = norm_product(product)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"RECORD_PRODUCT {rid} {stage} product={s['product']} (manual)")
    return 0


def _stage_order() -> list:
    """阶段链顺序（含需求阶段）：req → plan → testplan → code → test → quality → security → release。"""
    return ["req"] + [s["name"] for s in STAGES] + [g["name"] for g in GATES] + [RELEASE["name"]]


def _deps_satisfied(e: dict, st: dict) -> bool:
    """依赖满足判定：depends_on 全部需求处于 approved/released（需求确定即可解锁下游）。
    无依赖 / 依赖不存在（已删除）→ 视为满足。"""
    deps = e.get("depends_on") or []
    if not deps:
        return True
    project = e.get("_project") or ""
    for dep in deps:
        dep_key = f"{project}/{dep}" if project and "/" not in dep else dep
        de = st.get(dep_key) or st.get(dep)
        if de is None:
            continue  # 依赖需求已删除 → 不阻塞
        if de.get("status") not in ("approved", "released"):
            return False
    return True


def _assign_iteration(e: dict, st: dict, vd: dict) -> int:
    """惰性自动排迭代（用户拍板：自动排 + assign 可覆盖）：
    iteration=None 时按依赖拓扑分配（max(依赖迭代)+1），无依赖则版本内最大迭代 +1。
    已显式指定（文件头/assign）的不覆盖。"""
    if e.get("iteration") is not None:
        return e["iteration"]
    project = e.get("_project") or ""
    ver = e.get("version")
    dep_iters = []
    for dep in e.get("depends_on") or []:
        de = st.get(f"{project}/{dep}")
        if de and de.get("iteration") is not None:
            dep_iters.append(de["iteration"])
    if dep_iters:
        it = max(dep_iters) + 1
    else:
        it = 1  # 无依赖 → 迭代 1（迭代内需求并行；有依赖才排后续迭代）
    v = next((x for x in vd.get("versions", []) if x["name"] == ver), None)
    if v and it not in v.get("iterations", []):
        v.setdefault("iterations", []).append(it)
    e["iteration"] = it
    return it


def _iterations_prev_done(e: dict, st: dict) -> bool:
    """迭代间串行：需求所属迭代的前序迭代（同版本内 iteration < e.iteration）全部 released 才可调度。"""
    project = e.get("_project") or ""
    ver = e.get("version")
    it = e.get("iteration") or 0
    if it <= 1:
        return True
    for key, x in st.items():
        if not key.startswith(project + "/"):
            continue
        if x.get("version") == ver and (x.get("iteration") or 0) < it and x.get("status") != "released":
            return False
    return True


def _apply_deps(st: dict, project: str = None, vd: dict = None) -> None:
    """调度前置检查（每 tick 每项目锁内）：依赖 + 迭代间串行。
    pending 且前置未满足 → waiting；waiting 且前置满足 → pending。
    waiting 不 spawn 不烧 token。"""
    if vd is None and project:
        vd = ensure_versions(project)
    vd = vd or {"versions": []}
    for key, e in st.items():
        if project and not key.startswith(project + "/"):
            continue
        e["_project"] = key.split("/", 1)[0]
        s = e.get("status")
        if s not in ("pending", "waiting"):
            continue
        _assign_iteration(e, st, vd)
        ready = _deps_satisfied(e, st) and _iterations_prev_done(e, st)
        if s == "pending" and not ready:
            e["status"] = "waiting"
        elif s == "waiting" and ready:
            e["status"] = "pending"


def _find_block_stage(e: dict):
    """找 block/中断发生阶段：stages 中第一个 state != done 的阶段。
    该阶段及其后续需重做；之前的阶段已通过（done），产物与结论复用。
    req 阶段特殊处理：顶层状态已越过需求阶段（approved/released/任一阶段态）即视为 req 已通过，
    不依赖 stages.req.state 完整性（存量数据/评审路径可能不写 req 四态——曾致 requeue 兜底回 req 全链重跑）。
    返回阶段名；stages 缺失/全 done 时返回 None（兜底全链重跑）。"""
    stages = e.get("stages") or {}
    s = e.get("status", "")
    req_passed = (s in ("approved", "released")
                  or s.startswith(("plan_", "testplan_", "code_", "test_",
                                   "quality_", "security_", "release_", "releasing")))
    for name in _stage_order():
        if name == "req" and req_passed:
            continue  # 顶层状态证明 req 已通过
        stg = stages.get(name) or {}
        if stg.get("state") != "done":
            return name
    return None


def cmd_requeue(rid: str) -> int:
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        stages = e.get("stages") or {}
        block_stage = _find_block_stage(e)
        if block_stage is None:
            block_stage = "req"  # 兜底：全链重跑
        # 重置 block 阶段及其后续（保留已 done 阶段的状态/产物/评审历史——不重跑已通过部分，省 token）
        reset = False
        for name in _stage_order():
            s = stages.get(name)
            if not s:
                continue
            if not reset and name != block_stage:
                continue
            reset = True
            s["state"] = None
            s["state_since"] = None
            s["round"] = 0
            s["product"] = None
            s["reviews"] = []
        # 顶层状态回到该阶段可认领态（已 done 阶段自动衔接）；req 阶段保留顶层 round（产物 r{round+1} 连续性）
        if block_stage == "req":
            e["status"] = "pending"
            e["failures"] = 0
        else:
            e["status"] = f"{block_stage}_designing"
            e["failures"] = 0
        clear_claim(e)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"REQUEUE {rid} -> {e['status']} (manual, resume from stage={block_stage}, kept: "
            + ",".join(n for n in _stage_order() if (stages.get(n) or {}).get("state") == "done") + ")")
    return 0


def cmd_set_status(rid: str, stage: str, state: str, product: str = None) -> int:
    """统一状态设置脚本（所有角色共用）：set_status {key} {stage} {working|reviewing|done} [product]。
    严格迁移校验：working（claimed/reviewing 可）→ reviewing（working 可，需 product）→ done（reviewing 可）。
    claimed 由 tick 认领设置，不对外开放。
    claim 生命周期（关键，防重复 spawn）：worker 启动（working）保留 claim；产出完成（reviewing 非幂等）与
    评审落定（done）清 claim——评审者启动（reviewing 幂等）保留 claim。曾无条件 clear_claim 导致
    worker 执行中 claim 被清、tick 重复认领同一需求并发 spawn 两个 worker 写同一产物（tetris/tetris 实测）。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"set_status: {rid} 不存在", file=sys.stderr)
            return 1
        before = ensure_stages(e)[stage].get("state")
        ok, err = set_stage_state(st, rid, stage, state, product)
        if not ok:
            print(f"set_status: {err}", file=sys.stderr)
            return 1
        e = st[rid]
        if state == "working":
            pass  # 执行中：保留 claim（防 tick 重复认领）
        elif state == "reviewing" and stage != "req" and before != "reviewing":
            clear_claim(e)  # 阶段链产出完成（working→reviewing）：清 claim 等待评审者认领
        else:  # req 评审者幂等（req 产出完成走 release_analyze，自带清 claim）、done
            if state == "done":
                clear_claim(e)
        write_status(st)
        log(f"STATE  {rid} {stage}={state} product={product or '-'}")
    return 0


def cmd_resume(rid: str, stage: str, phase: str) -> int:
    """人工恢复中间态：resume {key} {stage} {designing|reviewing|gating|releasing|done}。
    用于误回滚/数据修复后恢复到指定阶段状态（reviewing/done 需该阶段产物已存在）。"""
    if phase not in ("designing", "reviewing", "gating", "releasing", "done"):
        print(f"resume: phase 必须为 designing/reviewing/gating/releasing/done，收到 {phase!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        ensure_stages(e)
        if phase == "releasing":
            new_state = "releasing"
        elif phase == "done":
            if not e["stages"].get(stage, {}).get("product"):
                print(f"resume: {stage} 阶段无产物（product 为空），无法恢复完成态", file=sys.stderr)
                return 1
            new_state = f"{stage}_done"
        elif phase == "gating":
            new_state = f"{stage}_gating"
        else:
            new_state = f"{stage}_{phase}"
        if phase == "reviewing" and not e["stages"].get(stage, {}).get("product"):
            print(f"resume: {stage} 阶段无产物（product 为空），无法恢复评审态", file=sys.stderr)
            return 1
        e["status"] = new_state
        clear_claim(e)
        e["failures"] = 0
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"RESUME {rid} -> {new_state} (manual)")
    return 0


def cmd_list() -> int:
    with acquire_lock() as _:
        st = read_status()
    if not st:
        print("(空：还没有需求)")
        return 0
    print(f"{'REQ-ID':<32} {'STATUS':<10} {'ROUND':<6} {'FORCED':<7} {'FAIL':<5} UPDATED_AT")
    for key, e in sorted(st.items()):
        print(
            f"{key:<32} {e['status']:<10} {e['round']:<6} {str(e.get('forced', False)):<7} "
            f"{e['failures']:<5} {e.get('updated_at', '')}"
        )
    return 0


def cmd_get(rid: str) -> int:
    with acquire_lock() as _:
        st = read_status()
    e = st.get(rid)
    if not e:
        print(f"{rid} 不存在", file=sys.stderr)
        return 1
    print(json.dumps(e, ensure_ascii=False, indent=2))
    return 0


# ---------------- 通知（结果推送，no_agent cron 用） ----------------

NOTIFY_MARKER = os.path.join(LOG_DIR, ".notify_marker")
PAUSE_FILE = os.path.join(WORKSPACE_DIR, ".pause")  # 手动暂停标记：touch = 流水线整体停止调度（halt）


def cmd_halt(reason: str = "") -> int:
    """手动暂停流水线：touch workspace/.pause（可带原因）。
    暂停后 tick 整体跳过调度（不认领不 spawn），已运行 worker 不受影响；
    恢复：unhalt。暂停期间告警/notify cron 仍运行（job 未 pause），只是不调度新工作。"""
    with acquire_lock() as _:
        if os.path.exists(PAUSE_FILE):
            print(f"流水线已处于暂停状态（{PAUSE_FILE}）", file=sys.stderr)
            return 1
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(PAUSE_FILE, "w", encoding="utf-8") as f:
            f.write(f"halted at {now_iso()} by manual\nreason: {reason or '(未说明)'}\n")
        log(f"HALT pipeline paused (manual, reason={reason or 'unspecified'})")
    return 0


def cmd_unhalt() -> int:
    """恢复流水线：删除 workspace/.pause 标记，下个 tick 恢复调度。"""
    with acquire_lock() as _:
        if not os.path.exists(PAUSE_FILE):
            print("流水线未处于暂停状态", file=sys.stderr)
            return 1
        os.remove(PAUSE_FILE)
        log("UNHALT pipeline resumed (manual)")
    return 0


def cmd_notify() -> int:
    """输出自上次以来新归档的 approved 需求（Telegram 友好格式）；无新增则静默（空 stdout）。
    首次运行只初始化标记，不输出（避免把历史归档全部推一遍）。"""
    with acquire_lock() as _:
        st = read_status()
        now = now_iso()
        marker = ""
        if os.path.exists(NOTIFY_MARKER):
            with open(NOTIFY_MARKER, encoding="utf-8") as f:
                marker = f.read().strip()
        if not marker:
            with open(NOTIFY_MARKER, "w", encoding="utf-8") as f:
                f.write(now)
            return 0
        new_items = []
        for key, e in sorted(st.items()):
            if e.get("status") not in ("approved", "released"):
                continue
            upd = e.get("updated_at", "")
            if marker and upd <= marker:
                continue
            new_items.append((key, e))
        if new_items:
            lines = [f"📋 流水线结果（新增 {len(new_items)} 项）"]
            for key, e in new_items:
                project, rid = split_key(key)
                if e.get("status") == "released":
                    forced = " 🚀 已发布" if not e.get("forced") else " ⚠️强制发布（需人工复核）"
                    lines.append(f"🚀 {key} — 完整交付（{rel_artifact(project, rid)}）")
                else:
                    forced = " ⚠️强制归档（需人工复核）" if e.get("forced") else ""
                    lines.append(f"✅ {key} — 第 {e.get('round', '?')} 轮评审通过{forced}（{rel_artifact(project, rid)}）")
            out = "\n".join(lines)
        else:
            out = ""
        with open(NOTIFY_MARKER, "w", encoding="utf-8") as f:
            f.write(now)
    if out:
        print(out)
    return 0


# ---------------- 诊断（DFx：一键健康检查） ----------------

REQUIRED_FIELDS = ["status", "round", "max_rounds", "forced", "analysis",
                   "reviews", "failures", "created_at", "updated_at"]


def _sh(args, timeout=15) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def diagnose() -> int:
    """一键健康检查（DFx 落地）。任一 FAIL → 退出码 1。详细排查见 docs/troubleshooting.md。"""
    rows = []

    def add(level, code, msg):
        rows.append((level, code, msg))

    # D1 status.json
    try:
        st = read_status()
        add("PASS", "D1", "status.json 存在且 JSON 合法")
    except json.JSONDecodeError as e:
        st = {}
        add("FAIL", "D1", f"status.json JSON 损坏: {e} —— 需手工修复（见 docs/troubleshooting.md）")
    except FileNotFoundError:
        st = {}
        add("FAIL", "D1", "status.json 缺失")

    # D2 目录完整性（资产层在根目录，数据层按项目分层：workspace/<项目>/ 下含全部子目录）
    missing = [d for d in ("roles", "scripts", "docs") if not os.path.isdir(os.path.join(WORKDIR, d))]
    proj_dirs = [p for p in sorted(os.listdir(WORKSPACE_DIR))
                 if os.path.isdir(os.path.join(WORKSPACE_DIR, p))
                 and p not in ("logs",) and not p.startswith(".")]
    for proj in proj_dirs:
        miss_p = [d for d in ("input", "analysis", "review", "artifacts", "plans", "testplans",
                              "code", "tests", "quality", "security", "release", "archive", "logs")
                  if not os.path.isdir(os.path.join(WORKSPACE_DIR, proj, d))]
        if miss_p:
            missing.append(f"{proj}/{{{','.join(miss_p)}}}")
    if not os.path.isdir(os.path.join(WORKSPACE_DIR, "logs")):
        missing.append("logs")
    add("PASS" if not missing else "FAIL", "D2", "目录完整" if not missing else f"缺失目录: {missing}")

    # D3–D8 逐条目检查
    for key, e in st.items():
        miss_f = [f for f in REQUIRED_FIELDS if f not in e]
        if miss_f:
            add("WARN", "D3", f"{key} 缺字段 {miss_f}")
        s = e.get("status")
        if s not in STATE_SET:
            add("FAIL", "D4", f"{key} 非法状态 {s!r}（合法: {sorted(STATE_SET)}）")
        if s in MID_STATES:
            ca = e.get("claimed_at")
            if not ca:
                add("WARN", "D5", f"{key} 处于 {s} 但无 claimed_at（下个 tick 的 stale 恢复会处理）")
            else:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(ca.replace("Z", "+00:00"))).total_seconds() / 60.0
                except ValueError:
                    age = STALE_AFTER_MIN + 1
                if age >= 24 * 60:
                    add("WARN", "D5", f"{key} 滞留 {s} 已 {age:.0f} 分钟（>24h，异常，查 worker 日志）")
                elif age >= STALE_AFTER_MIN:
                    add("WARN", "D5", f"{key} 滞留 {s} 已 {age:.0f} 分钟（>{STALE_AFTER_MIN}min，将自动 stale 恢复；或 rollback {key}）")
        else:
            leftover = [k for k in ("claimed_by", "claimed_at", "worker_pid") if k in e]
            if leftover:
                add("WARN", "D6", f"{key} 非中间态却残留 claim 字段 {leftover}（可手动清理）")
        for k in (e.get("analysis"),) + tuple(e.get("reviews", [])):
            if k and not os.path.exists(os.path.join(WORKSPACE_DIR, k)):
                add("WARN", "D7", f"{key} 引用文件缺失: {k}")
        if s in ("approved", "released"):
            project, rid = split_key(key)
            if not os.path.exists(abs_artifact(project, rid)):
                add("WARN", "D8", f"{key} 已 {s} 但缺 {rel_artifact(project, rid)}")
            if e.get("forced"):
                add("WARN", "D8", f"{key} 为强制归档（forced），请人工复核未解决意见")

    # D9 input/ 未登记（项目子目录 + 平铺兼容）
    unreg = []
    for proj in sorted(os.listdir(WORKSPACE_DIR)):
        if proj in ("logs",) or proj.startswith(".") or not os.path.isdir(os.path.join(WORKSPACE_DIR, proj)):
            continue
        idir = os.path.join(WORKSPACE_DIR, proj, "input")
        if os.path.isdir(idir):
            for name in sorted(os.listdir(idir)):
                if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                    unreg.append(f"{proj}/{name}")
    legacy_input = os.path.join(WORKSPACE_DIR, "input")
    if os.path.isdir(legacy_input):
        for proj in sorted(os.listdir(legacy_input)):
            pdir = os.path.join(legacy_input, proj)
            if os.path.isdir(pdir):
                for name in sorted(os.listdir(pdir)):
                    if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                        unreg.append(f"{proj}/{name}")
            elif pdir.endswith(".md") and f"{DEFAULT_PROJECT}/{proj[:-3]}" not in st:
                unreg.append(proj)
    if unreg:
        add("INFO", "D9", f"input/ 未登记文件 {unreg}（下个 tick 会自动注册）")

    # D10 状态锁
    try:
        acquire_lock(timeout=2).close()
        add("PASS", "D10", "状态锁可获取（无进程持锁）")
    except RuntimeError:
        add("INFO", "D10", "状态锁被占用（可能有 tick/worker 正在运行，属正常）")

    # D11 gateway（cron 自动触发的前提）
    out = _sh(["hermes", "cron", "status"])
    if "Gateway is running" in out:
        add("PASS", "D11", "gateway 运行中，cron 会自动触发")
    else:
        add("FAIL", "D11", "gateway 未运行 → job 不会自动触发（hermes gateway start）")

    # D12 cron job 存在性
    out = _sh(["hermes", "cron", "list"])
    for name in ("req-analyst-top", "req-reviewer-top", "req-worker-top", "req-weekly-audit", "req-result-notify"):
        if f"Name:      {name}" not in out and f"Name: {name}" not in out:
            add("WARN", "D12", f"cron job {name} 缺失（重建命令见 README 快速开始）")

    # D13 worker 进程
    out = _sh(["ps", "-eo", "args"])
    n = sum(1 for ln in out.splitlines() if "hermes chat" in ln and " -q " in ln)
    add("INFO", "D13", f"当前下半部 worker 进程数: {n}")

    # D14 日志可写
    add("PASS" if os.access(LOG_DIR, os.W_OK) else "FAIL", "D14", "logs/ 目录可写")

    print("== zteam 诊断报告 ==")
    for level, code, msg in rows:
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "INFO": "ℹ️"}[level]
        print(f"  {icon} [{code}] {msg}")
    nfail = sum(1 for r in rows if r[0] == "FAIL")
    nwarn = sum(1 for r in rows if r[0] == "WARN")
    print(f"== 结论: {nfail} 个严重问题 / {nwarn} 个警告（详细排查见 docs/troubleshooting.md）==")
    return 1 if nfail else 0


# ---------------- 入口 ----------------

def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 0
    cmd, *rest = argv
    try:
        if cmd == "analyst_tick":
            return analyst_tick()
        if cmd == "reviewer_tick":
            return reviewer_tick()
        if cmd == "worker_tick":
            return worker_tick()
        if cmd == "weekly_tick":
            return weekly_tick()
        if cmd == "quota_tick":
            return quota_tick()
        if cmd == "diagnose":
            return diagnose()
        if cmd == "notify":
            return cmd_notify()
        if cmd == "release_analyze":
            return release_analyze(*rest)
        if cmd == "release_review":
            return release_review(*rest)
        if cmd == "release_stage_design":
            return release_stage_design(*rest)
        if cmd == "release_stage_review":
            return release_stage_review(*rest)
        if cmd == "release_gate":
            return release_gate(*rest)
        if cmd == "release_release":
            return release_release(*rest)
        if cmd == "set_status":
            return cmd_set_status(rest[0], rest[1], rest[2], rest[3] if len(rest) > 3 else None)
        if cmd == "register":
            return cmd_register()
        if cmd == "stale":
            return cmd_stale()
        if cmd == "next":
            return cmd_next(rest[0] if rest else None)
        if cmd == "claim":
            return cmd_claim(rest[0], rest[1])
        if cmd == "setpid":
            return cmd_setpid(rest[0], rest[1])
        if cmd == "rollback":
            return cmd_rollback(*rest)
        if cmd == "requeue":
            return cmd_requeue(rest[0])
        if cmd == "record_product":
            return cmd_record_product(rest[0], rest[1], rest[2])
        if cmd == "halt":
            return cmd_halt(" ".join(rest) if rest else "")
        if cmd == "unhalt":
            return cmd_unhalt()
        if cmd == "resume":
            return cmd_resume(rest[0], rest[1], rest[2])
        if cmd == "module":
            return cmd_module(rest[0], rest[1], rest[2:])
        if cmd == "issue":
            return cmd_issue(rest[0], rest[1], rest[2:])
        if cmd == "confirm":
            return cmd_confirm(rest[0])
        if cmd == "reject":
            return cmd_reject(rest[0], " ".join(rest[1:]))
        if cmd == "versions":
            return cmd_versions(rest[0] if rest else None)
        if cmd == "assign":
            return cmd_assign(rest[0], rest[1] if len(rest) > 1 else "")
        if cmd == "release_it":
            return release_it(rest[0], rest[1], rest[2], rest[3], rest[4])
        if cmd == "release_st":
            return release_st(rest[0], rest[1], rest[2], rest[3])
        if cmd == "list":
            return cmd_list()
        if cmd == "get":
            return cmd_get(rest[0])
        print(f"未知子命令: {cmd}\n{__doc__}", file=sys.stderr)
        return 2
    except (IndexError, ValueError) as exc:
        print(f"{cmd} 参数错误: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"运行错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
