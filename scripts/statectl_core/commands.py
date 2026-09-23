"""人工/调试子命令 + 主循环 main()。

所有 `cmd_*` 系列人工命令 + `main()` 派发表都在本模块。commands 是 CLI 入口的
唯一实现（commit 6 起 statectl.py 退化为 5 行 thin shim，仅做入口转发）。

子命令分类：
- tick: analyst_tick / reviewer_tick / worker_tick / weekly_tick / quota_tick
- release: release_analyze / release_review / release_stage_design / release_stage_review /
           release_gate / release_release / release_it / release_st / release_arch /
           release_testplan_v2 / release_module / release_qa / release_st_v2 / release_st_case
- 人工: register / stale / next / claim / setpid / rollback / requeue / list / get /
        confirm / reject / change_request / project / versions / assign / resume /
        set_status / record_product / notify / halt / unhalt
- 诊断: diagnose
- 模块/版本命令: module / issue / unblock / confirm_guide / reject_guide
- 子命令 detail: 每个命令接受 positional + remaining args，main() 解析后转发
"""
from __future__ import annotations

import json
import os
import sys

from .diagnose import diagnose
from .issues import cmd_issue
from .model_config import DEFAULT_MAX_ROUNDS
from .modules import (
    MODULE_TYPES,
    _module_unblock,
    cmd_module,
    release_module,
    release_st_v2,
)
from .paths import (
    CONFIRM_REMINDED,
    DEFAULT_PROJECT,
    LOG_DIR,
    NOTIFY_MARKER,
    PAUSE_FILE,
    WORKDIR,
    WORKSPACE_DIR,
    abs_artifact,
    now_iso,
    project_dir,
    read_projects,
    rel_artifact,
    rel_input,
    split_key,
)
from .pipeline import (
    MID_STATES,
    STAGES,
    ensure_stages,
    find_claimable,
    norm_product,
    product_path,
    rollback_entry,
    set_stage_state,
    stale_recovery,
    stage_cfg,
    drain_alarms,
)
from .qa import (
    confirm_guide,
    reject_guide,
    release_qa,
    release_st_case,
)
from .resources import _version_unblock
from .status import (
    acquire_lock,
    clear_claim,
    log,
    read_status,
    write_status,
)
from .ticks import (
    analyst_tick,
    quota_tick,
    reviewer_tick,
    weekly_tick,
    worker_tick,
)
from .versions import (
    cmd_assign,
    cmd_change_request,
    cmd_confirm,
    cmd_project,
    cmd_reject,
    cmd_versions,
    read_versions,
    release_arch,
    release_it,
    release_st,
    release_testplan_v2,
)
from .release import (
    release_analyze,
    release_gate,
    release_release,
    release_review,
    release_stage_design,
    release_stage_review,
)

__all__ = [
    # cmd_*
    "cmd_register", "cmd_stale", "cmd_next", "cmd_claim", "cmd_setpid",
    "cmd_rollback", "cmd_record_product", "cmd_requeue", "cmd_set_status",
    "cmd_resume", "cmd_list", "cmd_get", "cmd_notify",
    "cmd_halt", "cmd_unhalt",
    # 私有 helper
    "_find_block_stage", "_spec_summary", "_stage_order",
    # 入口
    "main",
]


# ---------------- 人工/调试子命令 ----------------

def cmd_register() -> int:
    from .versions import register_new_inputs
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
    from .pipeline import claim
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
        full = product_path(product)
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
    return ["req"] + [s["name"] for s in STAGES] + [g["name"] for g in __import__("statectl_core.pipeline", fromlist=["GATES"]).GATES] + [__import__("statectl_core.pipeline", fromlist=["RELEASE"]).RELEASE["name"]]


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
            continue
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
            block_stage = "req"
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
            pass
        elif state == "reviewing" and stage != "req" and before != "reviewing":
            clear_claim(e)
        else:
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

def cmd_halt(reason: str = "") -> int:
    """手动暂停流水线：touch {PAUSE_FILE}（可带原因）。
    暂停后 tick 整体跳过调度（不认领不 spawn），已运行 worker 不受影响；
    恢复：unhalt。暂停期间告警/notify cron 仍运行（job 未 pause），只是不调度新工作。"""
    with acquire_lock() as _:
        if os.path.exists(PAUSE_FILE):
            print(f"流水线已处于暂停状态（{PAUSE_FILE}）", file=sys.stderr)
            return 1
        os.makedirs(os.path.dirname(PAUSE_FILE), exist_ok=True)
        with open(PAUSE_FILE, "w", encoding="utf-8") as f:
            f.write(f"halted at {now_iso()} by manual\nreason: {reason or '(未说明)'}\n")
        log(f"HALT pipeline paused (manual, reason={reason or 'unspecified'})")
    return 0


def cmd_unhalt() -> int:
    """恢复流水线：删除 PAUSE_FILE 标记，下个 tick 恢复调度。"""
    with acquire_lock() as _:
        if not os.path.exists(PAUSE_FILE):
            print("流水线未处于暂停状态", file=sys.stderr)
            return 1
        os.remove(PAUSE_FILE)
        log("UNHALT pipeline resumed (manual)")
    return 0


def _spec_summary(e: dict) -> str:
    """规格摘要（用户评审推送用）：规格文件头部 + 需求原文头部。"""
    parts = []
    try:
        if e.get("analysis"):
            full = product_path(e["analysis"])
            if os.path.exists(full):
                head = " ".join(open(full, encoding="utf-8").read().splitlines()[:8])[:200]
                parts.append(f"规格：{head}")
    except Exception:
        pass
    return " | ".join(parts) if parts else "（规格文件缺失）"


def cmd_notify() -> int:
    """输出自上次以来新归档的 approved 需求 + 待用户评审的规格（Telegram 友好格式）；无新增则静默。
    首次运行只初始化标记，不输出（避免把历史归档全部推一遍）。"""
    with acquire_lock() as _:
        st = read_status()
        now = now_iso()
        out_lines = []
        reminded = set()
        if os.path.exists(CONFIRM_REMINDED):
            try:
                reminded = set(json.load(open(CONFIRM_REMINDED, encoding="utf-8")))
            except Exception:
                reminded = set()
        pending_confirm = [k for k, e in sorted(st.items()) if e.get("status") == "awaiting_user_confirm"]
        new_confirm = [k for k in pending_confirm if k not in reminded]
        if new_confirm:
            out_lines.append("🧾 规格待你评审（你是需求规格的唯一拍板人）：")
            for k in new_confirm:
                out_lines.append(f"  {k}：{_spec_summary(st[k])}")
                out_lines.append(f"    回复 confirm {k.split('/')[-1]} 或 reject {k.split('/')[-1]} <理由>")
            reminded |= set(new_confirm)
        reminded = {k for k in reminded if st.get(k, {}).get("status") == "awaiting_user_confirm"}
        os.makedirs(os.path.dirname(CONFIRM_REMINDED), exist_ok=True)
        json.dump(sorted(reminded), open(CONFIRM_REMINDED, "w", encoding="utf-8"))
        # 段 1.5：版本用户指南待确认
        for proj in [p["name"] for p in read_projects().get("projects", [])] + \
                    ([x for x in sorted(os.listdir(WORKSPACE_DIR)) if os.path.isdir(os.path.join(WORKSPACE_DIR, x))
                      and x not in ("logs",) and not x.startswith(".")] if os.path.isdir(WORKSPACE_DIR) else []):
            if proj in ("logs",) or proj.startswith("."):
                continue
            try:
                vd = read_versions(proj)
            except Exception:
                continue
            for v in vd.get("versions", []):
                if v.get("status") == "qa_reviewing":
                    out_lines.append(f"📦 版本 {proj}/{v['name']} 发布包待你确认：用户指南 {v.get('release_pkg') or '?'}（released 前最后一关）")
                    out_lines.append(f"    回复 confirm_guide {proj} {v['name']} 或 reject_guide {proj} {v['name']} <理由>")
        marker = ""
        if os.path.exists(NOTIFY_MARKER):
            with open(NOTIFY_MARKER, encoding="utf-8") as f:
                marker = f.read().strip()
        if not marker:
            with open(NOTIFY_MARKER, "w", encoding="utf-8") as f:
                f.write(now)
            if out_lines:
                print("\n".join(out_lines))
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
            out_lines.append(f"📋 流水线结果（新增 {len(new_items)} 项）")
            for key, e in new_items:
                project, rid = split_key(key)
                if e.get("status") == "released":
                    out_lines.append(f"🚀 {key} — 完整交付（{rel_artifact(project, rid)}）")
                else:
                    forced = " ⚠️强制归档（需人工复核）" if e.get("forced") else ""
                    out_lines.append(f"✅ {key} — 第 {e.get('round', '?')} 轮评审通过{forced}（{rel_artifact(project, rid)}）")
        with open(NOTIFY_MARKER, "w", encoding="utf-8") as f:
            f.write(now)
    if out_lines:
        print("\n".join(out_lines))
    return 0


# ---------------- 入口 ----------------

def main(argv) -> int:
    """CLI 入口（commit 6：本地化形态）。

    35 个子命令：tick / release / 人工 / 模块/版本 / 诊断。
    错误处理：IndexError/ValueError → 2（参数错），RuntimeError → 1（运行错），其他异常冒泡。
    """
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
        if cmd == "unblock":
            with acquire_lock() as _:
                return _version_unblock(rest[0], rest[1])
        if cmd == "confirm":
            return cmd_confirm(rest[0])
        if cmd == "reject":
            return cmd_reject(rest[0], " ".join(rest[1:]))
        if cmd == "change_request":
            return cmd_change_request(rest[0], rest[1], " ".join(rest[2:]))
        if cmd == "project":
            return cmd_project(rest[0], rest[1:])
        if cmd == "versions":
            return cmd_versions(rest[0] if rest else None)
        if cmd == "assign":
            return cmd_assign(rest[0], rest[1] if len(rest) > 1 else "")
        if cmd == "release_it":
            return release_it(rest[0], rest[1], rest[2], rest[3], rest[4])
        if cmd == "release_st":
            return release_st(rest[0], rest[1], rest[2], rest[3])
        if cmd == "release_arch":
            return release_arch(rest[0], rest[1], rest[2], rest[3])
        if cmd == "release_testplan_v2":
            return release_testplan_v2(rest[0], rest[1], rest[2], rest[3])
        if cmd == "release_module":
            return release_module(rest[0], rest[1], rest[2], rest[3], rest[4], rest[5] if len(rest) > 5 else "")
        if cmd == "release_st_v2":
            return release_st_v2(rest[0], rest[1], rest[2], rest[3])
        if cmd == "release_st_case":
            return release_st_case(rest[0], rest[1], rest[2], rest[3])
        if cmd == "release_qa":
            return release_qa(rest[0], rest[1], rest[2], rest[3])
        if cmd == "confirm_guide":
            return confirm_guide(rest[0], rest[1])
        if cmd == "reject_guide":
            return reject_guide(rest[0], rest[1], " ".join(rest[2:]))
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
