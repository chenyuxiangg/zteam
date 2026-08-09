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


def worker_log_name(project: str, rid: str, n: int) -> str:
    return f"worker-{rid}-r{n}.log"

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
CODE_DEVELOPER_MODEL = os.environ.get("CODE_DEVELOPER_MODEL", "deepseek-v4-flash")
CODE_REVIEWER_MODEL = os.environ.get("CODE_REVIEWER_MODEL", "deepseek-v4-pro")
TEST_DEVELOPER_MODEL = os.environ.get("TEST_DEVELOPER_MODEL", "deepseek-v4-flash")
TEST_REVIEWER_MODEL = os.environ.get("TEST_REVIEWER_MODEL", "deepseek-v4-pro")
QUALITY_REVIEWER_MODEL = os.environ.get("QUALITY_REVIEWER_MODEL", "deepseek-v4-pro")
SECURITY_REVIEWER_MODEL = os.environ.get("SECURITY_REVIEWER_MODEL", "deepseek-v4-pro")
RELEASER_MODEL = os.environ.get("RELEASER_MODEL", "deepseek-v4-flash")

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
    "code-developer": (CODE_DEVELOPER_MODEL, ANALYST_PROVIDER),
    "code-reviewer": (CODE_REVIEWER_MODEL, ANALYST_PROVIDER),
    "test-developer": (TEST_DEVELOPER_MODEL, ANALYST_PROVIDER),
    "test-reviewer": (TEST_REVIEWER_MODEL, ANALYST_PROVIDER),
    "quality-reviewer": (QUALITY_REVIEWER_MODEL, ANALYST_PROVIDER),
    "security-reviewer": (SECURITY_REVIEWER_MODEL, ANALYST_PROVIDER),
    "releaser": (RELEASER_MODEL, ANALYST_PROVIDER),
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
    s = {"pending", "analyzing", "analyzed", "reviewing", "needs_fix", "approved", "blocked", "released"}
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


# ---------------- 状态机操作 ----------------

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
                log(f"REGISTER {key} status=pending round=0 project={proj}")
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
            e["status"] = "approved"
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
    logf = open(os.path.join(project_log_dir(project), worker_log_name(project, rid, round_n)), "ab")
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
            alarms += stale_recovery(pst)
            alarms += guard_recovery(pst)  # 巡检：worker 漏设状态/卡死的自动补正
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
        e["status"] = "analyzed"
        e["analysis"] = product
        e["round"] = int(e.get("round", 0))  # round 在评审时递增
        clear_claim(e)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"ANALYZE {rid} round={e['round']} file={product}")
        log(f"STATE  {rid} analyzing->analyzed")
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


def cmd_requeue(rid: str) -> int:
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        e["status"] = "pending"
        e["failures"] = 0
        clear_claim(e)
        # 重跑 = 全链重来：重置各阶段四态与轮次引用（产物文件保留，仅清状态），
        # 否则残留 done/reviewing 会卡死 set_status 迁移（tetris/tetris requeue 后 plan 阶段实测）。
        # 注意：顶层 round 保留（req 重跑产出 r{round+1} 的连续性依赖它）。
        for name, s in (e.get("stages") or {}).items():
            s["state"] = None
            s["state_since"] = None
            s["round"] = 0
            s["product"] = None
            s["reviews"] = []
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"REQUEUE {rid} -> pending (manual, stages reset)")
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
        if cmd == "resume":
            return cmd_resume(rest[0], rest[1], rest[2])
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
