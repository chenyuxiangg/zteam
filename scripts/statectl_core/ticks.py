"""上半部 tick（cron no_agent 触发）。

- quota_tick：调 check_minimax_quota.py，根据退出码告警（commit 5）
- _format_beijing / _parse_zlog_message：quota_tick 辅助
- _tick_common：通用 tick 主体（全局锁注册 + 每项目锁调度）
- analyst_tick / reviewer_tick / worker_tick：兼容保留的入口（都委托 _tick_common）
- weekly_tick：周度审计（归档完整性、blocked 提醒、未登记 input）
- guard_recovery：worker 漏设状态的自动补正（核心可靠性机制）
- _apply_deps：依赖调度（pending/waiting 切换；其内部 _assign_iteration
  仍依赖 versions.ensure_versions，故放在 ticks 也是合理的）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from . import paths as _paths
from .issues import _schedule_arch_te
from .model_config import DEFAULT_MAX_ROUNDS
from .modules import (
    _issue_stale_watch,
    _module_stale_recovery,
    _schedule_module_iter,
    _version_stale_recovery,
    read_modules,
)
from .paths import (
    ALARM_FILE,
    DEFAULT_PROJECT,
    LOG_DIR,
    PAUSE_FILE,
    QUOTA_SCRIPT,
    WORKDIR,
    WORKSPACE_DIR,
    abs_artifact,
    ensure_project,
    now_iso,
    project_dir,
    read_projects,
    rel_artifact,
    rel_analysis,
    rel_input,
    rel_review,
    rel_stage_product,
    rel_stage_review,
    split_key,
)
from .pipeline import (
    MID_STATES,
    RELEASE,
    STAGES,
    STALE_AFTER_MIN,
    _deps_satisfied,
    _iterations_prev_done,
    _stage_order,
    active_stage,
    build_worker_query,
    claim,
    drain_alarms,
    ensure_stages,
    find_claimable,
    parse_conclusion,
    pid_alive,
    product_path,
    rollback_entry,
    set_stage_state,
    spawn_worker,
    stage_cfg,
    stale_recovery,
    write_artifact,
)
from .qa import _schedule_st_qa
from .resources import _resource_unblock
from .status import (
    acquire_lock,
    clear_claim,
    log,
    read_status,
    write_status,
)
from .versions import (
    _advance_v2,
    _assign_iteration,
    _schedule_it_st,
    _version_guard_watch,
    ensure_versions,
    read_versions,
    register_new_inputs,
)

__all__ = [
    "quota_tick", "_format_beijing", "_parse_zlog_message",
    "_tick_common", "analyst_tick", "reviewer_tick", "worker_tick", "weekly_tick",
    "guard_recovery", "_apply_deps",
]


def _format_beijing(ts_ms: int) -> str:
    return (datetime.utcfromtimestamp(ts_ms / 1000) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def _parse_zlog_message(line: str) -> str:
    """Extract the message field from a pipe-delimited zlog line.

    Format: ``{ts}|{level_name:8}|{func}:{lineno}|{role:10}|{message}|{kv}``
    """
    parts = line.rstrip("\n").split("|", 5)
    if len(parts) != 6:
        raise ValueError(f"unexpected zlog line shape: {line!r}")
    return parts[4]


def quota_tick() -> int:
    """调用 check_minimax_quota.py，根据退出码生成告警；脚本不可用或调用失败时静默。

    退出码语义（脚本约定）：
      0 = 健康（5h 窗口 ≥ 30% 且 周配额 ≥ 50%）
      1 = 紧张（5h 窗口 < 30% 或 周配额 < 50%）
      2 = 严重受限（5h 窗口 < 10%）
      3 = 调用失败（凭据/网络/格式）
    """
    if not os.path.exists(QUOTA_SCRIPT):
        return 0
    try:
        r = subprocess.run([sys.executable, QUOTA_SCRIPT, "--json"],
                           capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, Exception):
        return 0
    code = r.returncode
    if code == 0:
        return 0
    if code == 3:
        return 0
    try:
        _json = json.loads(_parse_zlog_message(r.stdout))
        general = next((m for m in _json.get("model_remains", []) if m.get("model_name") == "general"), None)
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


# ---------------- 上半部 tick ----------------

def _tick_common() -> int:
    """通用 tick（P4 并发核心）：全局锁注册（只注册不写盘）→ 每项目锁调度。
    项目间并发（不同项目由不同 tick/进程并行处理），同项目串行（项目锁 + claim 防重复）。
    注册的新条目随各项目锁合并写入（避免阶段 1 全量写覆盖其他 tick 的项目更新——并发安全）。"""
    alarms = []
    if os.path.exists(PAUSE_FILE):
        return 0
    # 阶段 1：全局锁注册
    with acquire_lock() as _:
        st_all = read_status()
        register_new_inputs(st_all)
    # 阶段 2：每项目锁调度
    projects = [p["name"] for p in read_projects().get("projects", [])]
    if os.path.isdir(WORKSPACE_DIR):
        projects += [p for p in sorted(os.listdir(WORKSPACE_DIR))
                     if os.path.isdir(os.path.join(WORKSPACE_DIR, p))
                     and p not in ("logs",) and not p.startswith(".") and p not in projects]
    for proj in projects:
        with acquire_lock(project=proj) as _:
            ensure_project(proj)
            pst = read_status(proj)
            if not pst:
                pst = {}
            for key, e in st_all.items():
                if key.startswith(proj + "/") and key not in pst:
                    pst[key] = e
            if not pst:
                continue
            _apply_deps(pst, proj)
            alarms += stale_recovery(pst)
            alarms += guard_recovery(pst)
            vd = read_versions(proj)
            _advance_v2(proj, vd, pst, alarms)
            _schedule_it_st(proj, vd, pst, alarms)
            _schedule_arch_te(proj, vd, pst, alarms)
            md = read_modules(proj)
            _module_stale_recovery(proj, md, alarms)
            _version_stale_recovery(proj, vd, alarms)
            _version_guard_watch(proj, vd, alarms)
            _issue_stale_watch(proj, alarms)
            _resource_unblock(proj, md, vd, alarms)
            _schedule_module_iter(proj, vd, md, pst, alarms)
            _schedule_st_qa(proj, vd, md, pst, alarms)
            found = find_claimable(pst)
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
        print(out)
    return 0


def analyst_tick() -> int:
    """分析师 tick（兼容保留）：与 worker_tick 同质调度，项目锁保证无竞态。"""
    return _tick_common()


def reviewer_tick() -> int:
    """评审 tick（兼容保留）：与 worker_tick 同质调度，项目锁保证无竞态。"""
    return _tick_common()


def worker_tick() -> int:
    """通用阶段 tick（主调度）：全局锁注册 → 每项目锁 stale/巡检/认领/spawn。
    项目间并发、同项目串行；一次认领一个（最老优先，防唤醒风暴）。"""
    return _tick_common()


def weekly_tick() -> int:
    """周度审计（归档完整性 / blocked 提醒 / 未登记 input）。"""
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
                issues.append(f"[AUDIT] 需求 {key} 处于 blocked，需人工介入（python3 {WORKDIR}/scripts/statectl.py requeue {key}）")
            elif s in MID_STATES:
                issues.append(f"[AUDIT] 需求 {key} 滞留 {s}（中间态不应跨周存在）")
        for proj in [p["name"] for p in read_projects().get("projects", [])] + \
                    ([x for x in sorted(os.listdir(WORKSPACE_DIR)) if os.path.isdir(os.path.join(WORKSPACE_DIR, x))
                      and x not in ("logs",) and not x.startswith(".")] if os.path.isdir(WORKSPACE_DIR) else []):
            if proj in ("logs",) or proj.startswith("."):
                continue
            idir = os.path.join(project_dir(proj), "input")
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
        pending_confirm = [k for k, e in sorted(st.items()) if e.get("status") == "awaiting_user_confirm"]
        for k in pending_confirm:
            issues.append(f"[AUDIT] 需求 {k} 处于 awaiting_user_confirm（用户评审待办）")
    for line in issues:
        print(line)
    return 0


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
        cfg = stage_cfg(stage) if stage != "req" else None
        pid = e.get("worker_pid")
        if state == "reviewing":
            rp = rel_stage_review(cfg, project, rid2, n) if cfg else rel_review(project, rid2, n)
            full_rp = product_path(rp)
            if os.path.exists(full_rp):
                conclusion = parse_conclusion(full_rp)
                s["round"] = int(s.get("round", 0)) + 1
                if conclusion == "PASS":
                    ok, err = set_stage_state(st, rid, stage, "done")
                    log(f"GUARD {rid} {stage} reviewing->done (auto, PASS)")
                    if stage in ("req", RELEASE["name"]):
                        write_artifact(rid, st[rid])
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
        else:
            prod = rel_stage_product(cfg, project, rid2, n) if cfg else rel_analysis(project, rid2, n)
            if os.path.exists(product_path(prod)):
                ok, err = set_stage_state(st, rid, stage, "reviewing", prod)
                log(f"GUARD {rid} {stage} {state}->reviewing (auto, product exists)")
            else:
                if pid and pid_alive(pid):
                    log(f"GUARD {rid} {stage} {state} 超时但 worker 存活（等待）")
                    continue
                rollback_entry(st, rid, alarms, reason="guard-timeout")
    return alarms


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
