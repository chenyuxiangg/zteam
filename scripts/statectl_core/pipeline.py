"""流水线核心引擎。

- 状态机定义：STAGES / GATES / RELEASE + 中间态/全状态集合
- 阶段流转：stage_cfg / stage_after / next_action
- 阶段四态机：new_stages / ensure_stages / set_stage_state / prev_done_state
- 中间态恢复：rollback_entry / stale_recovery
- 认领 + spawn：find_claimable / claim / build_worker_query / spawn_worker
- 调度前置：_stage_order / _deps_satisfied / _iterations_prev_done / _find_block_stage
- 派生辅助：active_stage / parse_conclusion / norm_product / product_path / write_artifact / drain_alarms

依赖版本/迭代系统（ensure_versions 等）的 _apply_deps/_assign_iteration 放在 versions.py。
下半部 release_* 见 release.py。
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone

from . import paths as _paths
from .model_config import (
    ANALYST_MODEL,
    ANALYST_PROVIDER,
    DEFAULT_MAX_ROUNDS,
    ROLE_CN,
    ROLE_FILES,
    ROLE_MODELS,
    STALE_AFTER_MIN,
)
from .paths import (
    LOG_DIR,
    WORKDIR,
    abs_artifact,
    abs_input,
    project_dir,
    project_log_dir,
    rel_analysis,
    rel_artifact,
    rel_input,
    rel_review,
    rel_stage_product,
    rel_stage_review,
    split_key,
    worker_log_name,
)
from .status import clear_claim, log, pid_alive, read_status, write_status

__all__ = [
    # 状态机常量
    "STAGES", "GATES", "RELEASE", "MID_STATES", "STATE_SET",
    # 流转
    "stage_cfg", "stage_after", "next_action",
    # 阶段四态机
    "new_stages", "ensure_stages",
    "norm_product", "product_path",
    "set_stage_state", "prev_done_state",
    "rollback_entry", "stale_recovery",
    # 认领 + spawn
    "_ROLE_ALIAS", "find_claimable", "claim",
    "build_worker_query", "stage_inputs", "spawn_worker",
    # 调度前置
    "_stage_order", "_deps_satisfied", "_iterations_prev_done", "_find_block_stage",
    # 派生辅助
    "active_stage", "parse_conclusion",
    "write_artifact", "drain_alarms",
]


# ---- 状态机定义 ----

# 成对阶段（产出者 + 评审者）；kind: file=md 文档产物 / dir=文件集产物（代码/测试目录）
STAGES: list[dict] = [
    {"name": "plan",     "designer": "dev-plan-designer",  "reviewer": "dev-plan-reviewer",  "dir": "plans",     "kind": "file"},
    {"name": "testplan", "designer": "test-plan-designer", "reviewer": "test-plan-reviewer", "dir": "testplans", "kind": "file"},
    {"name": "code",     "designer": "code-developer",     "reviewer": "code-reviewer",      "dir": "code",      "kind": "dir"},
    {"name": "test",     "designer": "test-developer",     "reviewer": "test-reviewer",      "dir": "tests",     "kind": "dir"},
]
# 单角色门禁阶段（评审不通过不前进；连续失败达上限 → blocked）
GATES: list[dict] = [
    {"name": "quality",  "role": "quality-reviewer",  "dir": "quality"},
    {"name": "security", "role": "security-reviewer", "dir": "security"},
]
# 终态阶段（产出发布说明；released = 完整交付物归档 + 通知）
RELEASE: dict = {"name": "release", "role": "releaser", "dir": "release", "kind": "dir"}


# 所有中间态（stale 恢复/回滚适用）
def _mid_states() -> set[str]:
    s = {"analyzing", "reviewing", "releasing"}
    for stg in STAGES:
        s |= {f"{stg['name']}_designing", f"{stg['name']}_reviewing"}
    for g in GATES:
        s.add(f"{g['name']}_gating")
    return s


MID_STATES = _mid_states()


# 所有合法状态
def _all_states() -> set[str]:
    s = {"pending", "analyzing", "analyzed", "reviewing", "needs_fix", "approved", "blocked", "released",
         "awaiting_user_confirm", "dispatched", "removed"}
    for stg in STAGES:
        s |= {f"{stg['name']}_designing", f"{stg['name']}_reviewing", f"{stg['name']}_done"}
    for g in GATES:
        s |= {f"{g['name']}_gating", f"{g['name']}_done"}
    return s


STATE_SET = _all_states()


# ---- 流转 ----

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
        return None  # v2：等用户评审规格 / 已分发等模块开发
    if s == "approved":
        return None  # v2：规格锁定 → 等 SE 架构设计
    if s in ("pending", "needs_fix"):
        return ("pm", "req", "design")  # v2：PM 细化
    if s == "analyzing":
        return ("pm", "req", "design")
    if s == "analyzed":
        return ("pm", "req", "design")  # reject 重细化后 PM 继续
    if s == "reviewing":
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
                return None  # v2 截断：UT 完成 → 等迭代集成（it）
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


# ---- 阶段四态机 ----

def new_stages() -> dict:
    """初始化阶段链子状态（每阶段：state 四态机 + product/reviews + 审计时间线）。
    四态：claimed（tick 认领）→ working（执行者启动）→ reviewing（产出落盘/评审者启动）→ done（评审 PASS）。"""
    d: dict = {}
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
    s = e["stages"].setdefault("req", {"round": 0, "product": None, "reviews": []})
    s.setdefault("state", None)
    s.setdefault("state_since", None)
    s.setdefault("timeline", [])
    return e["stages"]


def norm_product(p: str) -> str:
    """规范化产物路径：统一为相对路径（去 workspace/ 前缀、去绝对路径）。
    防 worker 传参不规范（如带 workspace/ 前缀）导致归档/展示路径风格不一致。"""
    if not p:
        return p
    p = p.strip()
    if os.path.isabs(p):
        try:
            p = os.path.relpath(p, _paths.WORKSPACE_DIR)
        except ValueError:
            pass
    for prefix in ("workspace/", "./"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p


def product_path(p: str) -> str:
    """产物绝对路径（解耦后查表）：'{project}/{dir}/...' → project_dir(project)/{dir}/...（未登记回退 workspace）。"""
    p = norm_product(p)
    if p and "/" in p:
        proj, rest = p.split("/", 1)
        return os.path.join(project_dir(proj), rest)
    return os.path.join(_paths.WORKSPACE_DIR, p or "")


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
    now = _paths.now_iso()
    # ---- 严格迁移校验 ----
    if state == "working":
        if cur not in ("claimed", "reviewing", None):
            return False, f"{stage} 阶段当前状态 {cur!r} 不允许进入 working（仅 claimed/reviewing 可）"
    elif state == "reviewing":
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
    # ---- 派生顶层 status（兼容现有体系） ----
    if stage == "req":
        if state == "working":
            e["status"] = "analyzing"
        elif state == "reviewing":
            if e.get("status") not in ("reviewing",):
                e["status"] = "analyzed"
        elif state == "done":
            e["status"] = "awaiting_user_confirm"  # v2：规格细化完成 → 用户评审
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
    from .model_config import MAX_FAILURES  # 局部 import 避免顶层循环（model_config 不依赖本模块）
    e = st[rid]
    was = e["status"]
    if was not in MID_STATES:
        return
    prev = prev_done_state(e)
    e["status"] = prev
    e["failures"] = int(e.get("failures", 0)) + 1
    clear_claim(e)
    e["updated_at"] = _paths.now_iso()
    log(f"RECOVER {rid} {was}->{prev} reason={reason} failures={e['failures']}")
    if e["failures"] >= MAX_FAILURES:
        e["status"] = "blocked"
        e["updated_at"] = _paths.now_iso()
        log(f"BLOCKED {rid} failures={e['failures']}")
        alarms.append(
            f"[BLOCKED] 需求 {rid} 连续失败 {e['failures']} 次，已停止流转。"
            f"排查：logs/worker-*.log 与 logs/pipeline.log；修复后运行 "
            f"python3 {WORKDIR}/scripts/statectl.py requeue {rid} 重新入队。"
        )


def stale_recovery(st: dict) -> list:
    """回收卡死的 worker 认领（超时 + pid 存活检查）。返回新告警列表。
    仅处理"有 claim 字段"的中间态——release 后清 claim 的中间态是等待认领（正常），不回滚。"""
    alarms: list = []
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


# ---- 认领 + spawn ----

_ROLE_ALIAS: dict[str, str] = {"analyst": "req-analyst", "reviewer": "req-reviewer"}


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
        return False  # 已有认领（等待/处理中）
    _, stage, phase = act
    cur_state = ensure_stages(e)[stage].get("state")
    # 首次认领（None）设 claimed；重跑场景（requeue 后旧 done 终态残留）同样重置为 claimed
    if cur_state is None or (phase == "design" and cur_state == "done"):
        s = ensure_stages(e)[stage]
        s["state"] = "claimed"
        s["state_since"] = _paths.now_iso()
        s.setdefault("timeline", []).append({"t": _paths.now_iso(), "to": "claimed"})
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
    e["claimed_at"] = _paths.now_iso()
    e["worker_pid"] = 0  # spawn 后由 setpid 填充
    e["updated_at"] = _paths.now_iso()
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
                f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {key} req working（标记执行中）；",
                "输入文件：",
                f"- 需求原文：{product_path(rel_input(project, rid))}",
            ]
            if e.get("analysis"):
                q.append(f"- 上一版分析（修改轮必读）：{e['analysis']}")
            if e.get("reviews"):
                q.append(f"- 最新评审意见（修改轮必须逐条回应）：{e['reviews'][-1]}")
            q += [
                "任务：",
                "1. 按角色文件的输出模板与工作原则产出本轮分析报告；",
                f"2. 写入 {out}；",
                f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_analyze {key} {out} 完成状态更新（该命令会校验产物存在并置为等待评审）；",
                "4. 完成后无需汇报，过程留痕在 worker 日志即可。",
            ]
            return n, "\n".join(q)
        else:  # review
            n = int(e["round"]) + 1
            out = rel_review(project, rid, n)
            analysis_file = e.get("analysis") or rel_analysis(project, rid, n)
            q = [
                f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 评审需求 {key}（项目 {project}）的第 {n} 轮分析。",
                f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {key} req reviewing（标记评审中，幂等）；",
                "输入文件：",
                f"- 需求原文：{product_path(rel_input(project, rid))}",
                f"- 分析报告：{analysis_file}",
                f"注意：本需求 max_rounds={e.get('max_rounds', DEFAULT_MAX_ROUNDS)}，第 {n} 轮仍 FAIL 将由状态机自动强制归档，你无需关心。",
                "任务：",
                "1. 按角色文件的检查清单与输出模板评审；",
                f"2. 结论 PASS 或 FAIL，写入 {out}；",
                f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_review {key} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
                "4. 完成后无需汇报。",
            ]
            return n, "\n".join(q)
    # ---- 阶段链 ----
    cfg = stage_cfg(stage)
    assert cfg is not None, f"未知阶段 {stage}"
    n = int(e["stages"].get(stage, {}).get("round", 0)) + 1
    prev_products = stage_inputs(e)
    if phase == "design":
        out = rel_stage_product(cfg, project, rid, n)
        prev_review = e["stages"].get(stage, {}).get("reviews") or []
        if cfg.get("kind") == "dir":
            task1 = f"1. 按角色文件的输出模板与工作原则产出本阶段成果；在 {out} 目录内创建全部源码/产物文件（文件集，含 README 说明）；"
        else:
            task1 = "1. 按角色文件的输出模板与工作原则产出本阶段成果；"
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 完成需求 {key}（项目 {project}）的【{stage}】阶段第 {n} 轮产出。",
            f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {key} {stage} working（标记执行中）；",
            "输入文件：",
            *[f"- {desc}：{p}" for desc, p in prev_products],
        ]
        if prev_review:
            q.append(f"- 本阶段上一轮评审意见（修改轮必须逐条回应）：{prev_review[-1]}")
        q += [
            "任务：",
            task1,
            f"2. 产物写入 {out}；",
            f"3. 运行 python3 {WORKDIR}/scripts/statectl.py set_status {key} {stage} reviewing {out} 完成状态更新（标记待评审，命令会校验产物存在并严格校验状态迁移）；",
            "4. 完成后无需汇报，过程留痕在 worker 日志即可。",
        ]
        return n, "\n".join(q)
    if phase == "review":
        out = rel_stage_review(cfg, project, rid, n)
        product = e["stages"].get(stage, {}).get("product")
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 评审需求 {key}（项目 {project}）的【{stage}】阶段第 {n} 轮成果。",
            f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {key} {stage} reviewing（标记评审中，幂等）；",
            "输入文件：",
            f"- 本阶段成果：{product}",
            *[f"- {desc}：{p}" for desc, p in prev_products],
            "任务：",
            "1. 按角色文件的检查清单与输出模板评审；",
            f"2. 结论 PASS 或 FAIL，写入 {out}；",
            f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_stage_review {key} {stage} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报。",
        ]
        return n, "\n".join(q)
    if phase == "gate":
        out = rel_stage_product(cfg, project, rid, n)
        q = [
            f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 对需求 {key}（项目 {project}）执行【{stage}】门禁评审（第 {n} 轮）。",
            f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {key} {stage} working（标记门禁执行中）；",
            "输入文件：",
            *[f"- {desc}：{p}" for desc, p in prev_products],
            "任务：",
            "1. 按角色文件的检查清单与输出模板完成门禁评审；",
            f"2. 结论 PASS 或 FAIL，写入 {out}；",
            f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_gate {key} {stage} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报。",
        ]
        return n, "\n".join(q)
    # release（终态：打包交付）
    out = rel_stage_product(RELEASE, project, rid, n)
    q = [
        f"你是本流水线的【{cn}】下半部 worker。严格遵循 {rolefile} 为需求 {key}（项目 {project}）执行发布（第 {n} 轮）。",
        f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {key} {RELEASE['name']} working（标记发布执行中）；",
        "输入文件：",
        *[f"- {desc}：{p}" for desc, p in prev_products],
        "任务：",
        f"1. 在 {out} 目录内创建完整发布包（目录自动创建）：发布说明.md（版本/变更/质量安全结论/已知限制/回滚方案）+ 用户指南.md（安装/运行/使用）+ 打包产物 {rid}-v{{版本}}.tar.gz（代码文件集压缩，含 README 与依赖说明）+ SHA256SUMS（校验和）+ 可用性自检记录（如环境允许实际运行测试/启动冒烟）；",
        f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_release {key} {out} 完成状态更新（该命令校验产物目录存在并生成最终交付物归档）；",
        "3. 完成后无需汇报。",
    ]
    return n, "\n".join(q)


def stage_inputs(e: dict) -> list:
    """当前状态阶段的输入产物清单 [(描述, 相对路径), ...]（需求原文 + 上游各阶段终版）。"""
    s = e["status"]
    outs: list = []
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
    os.makedirs(_paths.LOG_DIR, exist_ok=True)
    os.makedirs(project_log_dir(project), exist_ok=True)
    os.makedirs(project_dir(project), exist_ok=True)
    logf = open(os.path.join(project_log_dir(project), worker_log_name(project, rid, round_n, role)), "ab")
    cmd = ["hermes", "chat", "-q", query, "-m", model, "-Q"]
    if provider:
        cmd += ["--provider", provider]
    _env = dict(os.environ)
    _env["ISSUE_REPORTER"] = role.upper()
    p = subprocess.Popen(
        cmd,
        cwd=project_dir(project),
        env=_env,
        stdin=subprocess.DEVNULL,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log(f"SPAWN {key} worker={role} pid={p.pid} model={model} round={round_n}")
    return p.pid


# ---- 调度前置（不依赖 versions 系统的部分；_apply_deps/_assign_iteration 见 versions.py） ----

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


def _find_block_stage(e: dict):
    """找 block/中断发生阶段：stages 中第一个 state != done 的阶段。
    该阶段及其后续需重做；之前的阶段已通过（done），产物与结论复用。
    req 阶段特殊处理：顶层状态已越过需求阶段（approved/released/任一阶段态）即视为 req 已通过。
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


# ---- 派生辅助 ----

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
        ap = product_path(e["analysis"])
        if os.path.exists(ap):
            with open(ap, encoding="utf-8") as f:
                parts += [f"## 最终分析（{e['analysis']}）", "", f.read().strip(), ""]
    if reviews:
        parts += [f"## 需求评审历史（{len(reviews)} 轮）", ""]
        for rp in reviews:
            full = product_path(rp)
            if os.path.exists(full):
                with open(full, encoding="utf-8") as f:
                    parts += [f"### {rp}", "", f.read().strip(), ""]
    for stg in STAGES + GATES:
        s = (e.get("stages") or {}).get(stg["name"], {})
        prod = s.get("product")
        if prod:
            full = product_path(prod)
            if os.path.isdir(full):  # 文件集产物
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
            full = product_path(rp)
            if os.path.exists(full):
                with open(full, encoding="utf-8") as f:
                    parts += [f"### {stg['name']} 评审（{rp}）", "", f.read().strip(), ""]
    if forced:
        parts += ["## 备注", "本需求达到轮次上限被强制归档（forced=true），仍有未解决意见，请人工复核。"]
    with open(abs_artifact(project, rid), "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    log(f"ARCHIVE {key} file={rel_artifact(project, rid)} status={status}")


def drain_alarms(new_alarms: list) -> str:
    """读取待投递告警（含 worker 侧写入的），输出并清空。返回要打印的文本。"""
    lines = list(new_alarms)
    if os.path.exists(_paths.ALARM_FILE):
        with open(_paths.ALARM_FILE, encoding="utf-8") as f:
            lines += [l.strip() for l in f if l.strip()]
    with open(_paths.ALARM_FILE, "w", encoding="utf-8") as f:
        f.write("")
    _ALERT_KW = ("blocked", "卡死", "停滞", "STUCK", "FAIL", "失败", "异常", "失控")
    _INFO_KW = ("死亡已重置", "已重置", "补挂", "再激活", "启动", "进入", "闭环", "通过")
    out = []
    for l in lines:
        if any(k in l for k in _ALERT_KW):
            out.append("🔴 " + l)
        elif any(k in l for k in _INFO_KW):
            out.append("ℹ️ " + l)
        else:
            out.append("· " + l)
    return "\n".join(out)