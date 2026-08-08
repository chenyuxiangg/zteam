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
INPUT_DIR = os.path.join(WORKSPACE_DIR, "input")
ANALYSIS_DIR = os.path.join(WORKSPACE_DIR, "analysis")
REVIEW_DIR = os.path.join(WORKSPACE_DIR, "review")
ARTIFACT_DIR = os.path.join(WORKSPACE_DIR, "artifacts")
LOG_DIR = os.path.join(WORKSPACE_DIR, "logs")
SCRIPTS_DIR = os.path.join(WORKDIR, "scripts")
STATUS_FILE = os.path.join(WORKSPACE_DIR, "status.json")
LOCK_FILE = os.path.join(WORKSPACE_DIR, "status.lock")
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")
ALARM_FILE = os.path.join(LOG_DIR, "alarms.txt")

DEFAULT_PROJECT = "default"  # 未指定项目时的兜底项目


def split_key(key: str):
    """status key → (project, req_id)。key 格式为 '<project>/<req_id>'；兼容旧格式（无 '/' → default 项目）。"""
    if "/" in key:
        p, r = key.rsplit("/", 1)
        return (p, r) if p else (DEFAULT_PROJECT, r)
    return DEFAULT_PROJECT, key


def rel_input(project: str, rid: str) -> str:
    return f"input/{project}/{rid}.md"


def rel_analysis(project: str, rid: str, n: int) -> str:
    return f"analysis/{project}/{rid}-r{n}.md"


def rel_review(project: str, rid: str, n: int) -> str:
    return f"review/{project}/{rid}-r{n}.md"


def rel_artifact(project: str, rid: str) -> str:
    return f"artifacts/{project}/{rid}.md"


def rel_stage_product(cfg: dict, project: str, rid: str, n: int) -> str:
    """阶段产出物路径（相对 workspace/）：{dir}/{project}/{rid}-r{n}.md"""
    return f"{cfg['dir']}/{project}/{rid}-r{n}.md"


def rel_stage_review(cfg: dict, project: str, rid: str, n: int) -> str:
    """阶段评审意见路径：{dir}/{project}/{rid}-r{n}-review.md"""
    return f"{cfg['dir']}/{project}/{rid}-r{n}-review.md"


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
    if s == "analyzed":
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
    return os.path.join(INPUT_DIR, project, rid + ".md")


def abs_artifact(project: str, rid: str) -> str:
    return os.path.join(ARTIFACT_DIR, project, rid + ".md")


def worker_log_name(project: str, rid: str, n: int) -> str:
    return f"worker-{project}-{rid}-r{n}.log"

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
# 成对阶段（产出者 + 评审者）；产物：{dir}/{project}/{req_id}-r{N}.md（产出）/ {dir}/{project}/{req_id}-r{N}-review.md（评审）
STAGES = [
    {"name": "plan",     "designer": "dev-plan-designer",  "reviewer": "dev-plan-reviewer",  "dir": "plans"},
    {"name": "testplan", "designer": "test-plan-designer", "reviewer": "test-plan-reviewer", "dir": "testplans"},
    {"name": "code",     "designer": "code-developer",     "reviewer": "code-reviewer",      "dir": "code"},
    {"name": "test",     "designer": "test-developer",     "reviewer": "test-reviewer",      "dir": "tests"},
]
# 单角色门禁阶段（评审不通过不前进；连续失败达上限 → blocked）
GATES = [
    {"name": "quality",  "role": "quality-reviewer",  "dir": "quality"},
    {"name": "security", "role": "security-reviewer", "dir": "security"},
]
# 终态阶段（产出发布说明；released = 完整交付物归档 + 通知）
RELEASE = {"name": "release", "role": "releaser", "dir": "release"}

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


def read_status() -> dict:
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_status(st: dict) -> None:
    tmp = STATUS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATUS_FILE)


def acquire_lock(timeout: float = 10.0):
    """flock 写锁（跨进程串行化 status.json 读改写）。"""
    lockf = open(LOCK_FILE, "w")
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lockf
        except BlockingIOError:
            if time.time() > deadline:
                lockf.close()
                raise RuntimeError("status.lock 获取超时（另一进程持有锁）")
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
    """workspace/input/ 下未登记文件自动注册为 pending（按项目子目录）。
    结构：input/<project>/<req_id>.md（推荐）；兼容 input/<req_id>.md 平铺 → default 项目。
    返回新注册的 key（'<project>/<req_id>'）列表。"""
    registered = []
    if not os.path.isdir(INPUT_DIR):
        return registered
    # 项目子目录 input/<project>/*.md
    for proj in sorted(os.listdir(INPUT_DIR)):
        pdir = os.path.join(INPUT_DIR, proj)
        if not os.path.isdir(pdir):
            continue
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
            log(f"REGISTER {key} status=pending round=0 project={proj}")
    # 兼容：input/<req_id>.md 平铺文件 → default 项目
    for name in sorted(os.listdir(INPUT_DIR)):
        full = os.path.join(INPUT_DIR, name)
        if os.path.isfile(full) and name.endswith(".md"):
            rid = name[:-3]
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
            log(f"REGISTER {key} status=pending round=0 project={DEFAULT_PROJECT}")
    return registered


def new_stages() -> dict:
    """初始化阶段链子状态（每阶段：round/product/reviews/status）。"""
    d = {}
    for stg in STAGES:
        d[stg["name"]] = {"round": 0, "product": None, "reviews": [], "status": "pending"}
    for g in GATES:
        d[g["name"]] = {"round": 0, "product": None, "reviews": [], "status": "pending"}
    d[RELEASE["name"]] = {"round": 0, "product": None, "reviews": [], "status": "pending"}
    return d


def ensure_stages(e: dict) -> dict:
    """兼容旧 entry（阶段化改造前无 stages 字段）：缺失时初始化。"""
    if "stages" not in e or not isinstance(e.get("stages"), dict):
        e["stages"] = new_stages()
    return e["stages"]


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
    """回收卡死的 worker 认领（超时 + pid 存活检查）。返回新告警列表。"""
    alarms = []
    for rid, e in list(st.items()):
        if e.get("status") not in MID_STATES:
            continue
        claimed_at = e.get("claimed_at")
        age_min = STALE_AFTER_MIN + 1  # 无 claim 时间戳视为超时
        if claimed_at:
            try:
                t = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
                age_min = (datetime.now(timezone.utc) - t).total_seconds() / 60.0
            except ValueError:
                pass
        if age_min < STALE_AFTER_MIN:
            continue
        pid = e.get("worker_pid")
        if pid and pid_alive(pid):
            log(f"SKIP  {rid} worker pid={pid} 仍存活（慢任务，等待）")
            continue
        rollback_entry(st, rid, alarms, reason="no-claim" if not claimed_at else "stale")
    return alarms


_ROLE_ALIAS = {"analyst": "req-analyst", "reviewer": "req-reviewer"}


def find_claimable(st: dict, role: str = None):
    """找最老（updated_at 最早）的可认领需求。返回 (req_id, entry, action) 或 None。
    role 为 None = 任意角色；支持短名（analyst/reviewer → req-analyst/req-reviewer）。"""
    role = _ROLE_ALIAS.get(role, role)
    cands = []
    for rid, e in st.items():
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
    _, stage, phase = act
    if stage != "req":
        ensure_stages(e)
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
                f"3. 运行 python3 scripts/statectl.py release_analyze {key} {out} 完成状态更新（该命令会校验产物存在）；",
                "4. 完成后无需汇报，过程留痕在 worker 日志即可。",
            ]
            return n, "\n".join(q)
        else:  # review
            n = int(e["round"]) + 1
            out = rel_review(project, rid, n)
            analysis_file = e.get("analysis") or rel_analysis(project, rid, n)
            q = [
                f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 评审需求 {key}（项目 {project}）的第 {n} 轮分析。",
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
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 完成需求 {key}（项目 {project}）的【{stage}】阶段第 {n} 轮产出。",
            "输入文件：",
            *[f"- {desc}：{p}" for desc, p in prev_products],
        ]
        if prev_review:
            q.append(f"- 本阶段上一轮评审意见（修改轮必须逐条回应）：{prev_review[-1]}")
        q += [
            "任务：",
            "1. 按角色文件的输出模板与工作原则产出本阶段成果；",
            f"2. 写入 {out}；",
            f"3. 运行 python3 scripts/statectl.py release_stage_design {key} {stage} {out} 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报，过程留痕在 worker 日志即可。",
        ]
        return n, "\n".join(q)
    if phase == "review":
        out = rel_stage_review(cfg, project, rid, n)
        product = e["stages"].get(stage, {}).get("product")
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 评审需求 {key}（项目 {project}）的【{stage}】阶段第 {n} 轮成果。",
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
            "输入文件：",
            *[f"- {desc}：{p}" for desc, p in prev_products],
            "任务：",
            "1. 按角色文件的检查清单与输出模板完成门禁评审；",
            f"2. 结论 PASS 或 FAIL，写入 {out}；",
            f"3. 运行 python3 scripts/statectl.py release_gate {key} {stage} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报。",
        ]
        return n, "\n".join(q)
    # release
    out = rel_stage_product(RELEASE, project, rid, n)
    q = [
        f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 为需求 {key}（项目 {project}）执行发布（第 {n} 轮）。",
        "输入文件：",
        *[f"- {desc}：{p}" for desc, p in prev_products],
        "任务：",
        "1. 按角色文件的输出模板产出发布说明；",
        f"2. 写入 {out}；",
        f"3. 运行 python3 scripts/statectl.py release_release {key} {out} 完成状态更新（该命令会校验产物存在并生成最终交付物归档）；",
        "4. 完成后无需汇报。",
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
    logf = open(os.path.join(LOG_DIR, worker_log_name(project, rid, round_n)), "ab")
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
    os.makedirs(os.path.join(ARTIFACT_DIR, project), exist_ok=True)
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
            if os.path.exists(full):
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

def analyst_tick() -> int:
    with acquire_lock() as _:
        st = read_status()
        alarms = []
        register_new_inputs(st)
        alarms += stale_recovery(st)
        found = find_claimable(st, "analyst")
        if found:
            rid, e, act = found
            if claim(st, rid, "analyst"):
                n, query = build_worker_query(act[0], rid, e)
                pid = spawn_worker(act[0], rid, n, query)
                st[rid]["worker_pid"] = pid
        write_status(st)
        out = drain_alarms(alarms)
    if out:
        print(out)  # 非空才输出（no_agent：空 stdout = 静默）
    return 0


def reviewer_tick() -> int:
    with acquire_lock() as _:
        st = read_status()
        alarms = stale_recovery(st)
        found = find_claimable(st, "reviewer")
        if found:
            rid, e, act = found
            if claim(st, rid, "reviewer"):
                n, query = build_worker_query(act[0], rid, e)
                pid = spawn_worker(act[0], rid, n, query)
                st[rid]["worker_pid"] = pid
        write_status(st)
        out = drain_alarms(alarms)
    if out:
        print(out)
    return 0


def worker_tick() -> int:
    """通用阶段 tick：注册 → stale 恢复 → 按 next_action 认领并 spawn 对应角色 worker。
    一次只认领一个（最老优先，防唤醒风暴 + 规避 3 分钟限制）。"""
    with acquire_lock() as _:
        st = read_status()
        alarms = []
        register_new_inputs(st)
        alarms += stale_recovery(st)
        found = find_claimable(st)  # 任意角色
        if found:
            rid, e, act = found
            role = act[0]
            if claim(st, rid, role):
                n, query = build_worker_query(role, rid, e)
                pid = spawn_worker(role, rid, n, query)
                st[rid]["worker_pid"] = pid
        write_status(st)
        out = drain_alarms(alarms)
    if out:
        print(out)
    return 0


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
        if os.path.isdir(INPUT_DIR):
            for proj in sorted(os.listdir(INPUT_DIR)):
                pdir = os.path.join(INPUT_DIR, proj)
                if not os.path.isdir(pdir):
                    continue
                for name in sorted(os.listdir(pdir)):
                    if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                        issues.append(f"[AUDIT] input/{proj}/{name} 未登记（下个分析师 tick 会自动注册）")
            for name in sorted(os.listdir(INPUT_DIR)):
                if os.path.isfile(os.path.join(INPUT_DIR, name)) and name.endswith(".md") and f"{DEFAULT_PROJECT}/{name[:-3]}" not in st:
                    issues.append(f"[AUDIT] input/{name} 未登记（下个分析师 tick 会自动注册）")
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
    """阶段产出完成后调用：校验产物 → {stage}_designing → {stage}_reviewing；记录 stages[stage].product。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        expect = f"{stage}_designing"
        if not e or e["status"] != expect:
            print(f"release_stage_design: {rid} 状态不是 {expect}，拒绝", file=sys.stderr)
            return 1
        ensure_stages(e)
        full = os.path.join(WORKSPACE_DIR, product)
        if not os.path.exists(full):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_stage_design: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        e["stages"][stage]["product"] = product
        e["stages"][stage]["status"] = "reviewing"
        e["status"] = f"{stage}_reviewing"
        clear_claim(e)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"STAGE  {rid} {stage} design round={e['stages'][stage]['round']} file={product}")
        log(f"STATE  {rid} {stage}_designing->{stage}_reviewing")
    return 0


def release_stage_review(rid: str, stage: str, product: str, conclusion: str) -> int:
    """阶段评审完成后调用：round+1 → {stage}_done(PASS) / {stage}_designing 重做(FAIL)。
    阶段评审 FAIL 达 max_rounds → blocked（质量门禁不放行，人工介入）。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print(f"release_stage_review: conclusion 必须为 PASS 或 FAIL，收到 {conclusion!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        expect = f"{stage}_reviewing"
        if not e or e["status"] != expect:
            print(f"release_stage_review: {rid} 状态不是 {expect}，拒绝", file=sys.stderr)
            return 1
        ensure_stages(e)
        full = os.path.join(WORKSPACE_DIR, product)
        if not os.path.exists(full):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_stage_review: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        s = e["stages"][stage]
        s["round"] = int(s.get("round", 0)) + 1
        s["reviews"] = s.get("reviews", []) + [product]
        if conclusion == "PASS":
            s["status"] = "done"
            e["status"] = f"{stage}_done"
        else:
            if s["round"] >= int(e.get("max_rounds", DEFAULT_MAX_ROUNDS)):
                e["status"] = "blocked"
                with open(ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(
                        f"[BLOCKED] 需求 {rid} 的【{stage}】阶段第 {s['round']} 轮评审仍 FAIL，"
                        f"已达 max_rounds，已停止流转，请人工介入（requeue {rid} 重跑）。\n"
                    )
            else:
                s["status"] = "pending"
                e["status"] = f"{stage}_designing"
        clear_claim(e)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"REVIEW  {rid} {stage} round={s['round']} file={product} conclusion={conclusion}")
        log(f"STATE  {rid} {stage}_reviewing->{e['status']}")
    return 0


def release_gate(rid: str, stage: str, product: str, conclusion: str) -> int:
    """门禁评审完成后调用：round+1 → {stage}_done(PASS) / 重试(FAIL)；达上限 → blocked。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print(f"release_gate: conclusion 必须为 PASS 或 FAIL，收到 {conclusion!r}", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        expect = f"{stage}_gating"
        if not e or e["status"] != expect:
            print(f"release_gate: {rid} 状态不是 {expect}，拒绝", file=sys.stderr)
            return 1
        ensure_stages(e)
        full = os.path.join(WORKSPACE_DIR, product)
        if not os.path.exists(full):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_gate: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        s = e["stages"][stage]
        s["round"] = int(s.get("round", 0)) + 1
        s["reviews"] = s.get("reviews", []) + [product]
        if conclusion == "PASS":
            s["product"] = product
            s["status"] = "done"
            e["status"] = f"{stage}_done"
        else:
            if s["round"] >= int(e.get("max_rounds", DEFAULT_MAX_ROUNDS)):
                e["status"] = "blocked"
                with open(ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(
                        f"[BLOCKED] 需求 {rid} 的【{stage}】门禁第 {s['round']} 轮仍 FAIL，"
                        f"已达 max_rounds，已停止流转，请人工介入。\n"
                    )
            else:
                s["status"] = "pending"
                e["status"] = f"{stage}_gating"
        clear_claim(e)
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"GATE   {rid} {stage} round={s['round']} file={product} conclusion={conclusion}")
        log(f"STATE  {rid} {stage}_gating->{e['status']}")
    return 0


def release_release(rid: str, product: str) -> int:
    """发布完成后调用：校验产物 → releasing → released；生成最终交付物归档。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e or e["status"] != "releasing":
            print(f"release_release: {rid} 状态不是 releasing，拒绝", file=sys.stderr)
            return 1
        ensure_stages(e)
        full = os.path.join(WORKSPACE_DIR, product)
        if not os.path.exists(full):
            alarms = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_release: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        s = e["stages"]["release"]
        s["round"] = int(s.get("round", 0)) + 1
        s["product"] = product
        s["status"] = "done"
        e["status"] = "released"
        clear_claim(e)
        e["updated_at"] = now_iso()
        write_artifact(rid, e)  # 完整交付物归档
        write_status(st)
        log(f"RELEASE {rid} round={s['round']} file={product}")
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
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"REQUEUE {rid} -> pending (manual)")
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

    # D2 目录完整性（资产层在根目录，数据层在 workspace/）
    missing = [d for d in ("roles", "scripts", "docs") if not os.path.isdir(os.path.join(WORKDIR, d))]
    missing += [d for d in ("input", "analysis", "review", "artifacts", "logs")
                if not os.path.isdir(os.path.join(WORKSPACE_DIR, d))]
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
    if os.path.isdir(INPUT_DIR):
        unreg = []
        for proj in sorted(os.listdir(INPUT_DIR)):
            pdir = os.path.join(INPUT_DIR, proj)
            if not os.path.isdir(pdir):
                continue
            for name in sorted(os.listdir(pdir)):
                if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                    unreg.append(f"{proj}/{name}")
        for name in sorted(os.listdir(INPUT_DIR)):
            if os.path.isfile(os.path.join(INPUT_DIR, name)) and name.endswith(".md") and f"{DEFAULT_PROJECT}/{name[:-3]}" not in st:
                unreg.append(name)
        if unreg:
            add("INFO", "D9", f"input/ 未登记文件 {unreg}（下个分析师 tick 会自动注册）")

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
