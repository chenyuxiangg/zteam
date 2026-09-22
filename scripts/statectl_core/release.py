"""下半部 release_* 系列（worker 完成产物后调用）。

每个函数都做：取锁 → 校验状态/产物 → 推进状态机 → 写审计日志。
产物缺失 → 自动 rollback_entry（让 stale 兜底或人工 requeue 重做）。
强制归档（max_rounds）→ 写 ALARM_FILE 提示人工复核。

调用方：worker（hermes chat 内通过 set_status / release_* 命令触发）。
"""
from __future__ import annotations

import os
import sys

from . import paths as _paths
from .model_config import DEFAULT_MAX_ROUNDS
from .paths import now_iso, rel_artifact, split_key
from .pipeline import (
    RELEASE,
    ensure_stages,
    norm_product,
    product_path,
    rollback_entry,
    set_stage_state,
    write_artifact,
)
from .status import (
    acquire_lock,
    clear_claim,
    log,
    read_status,
    write_status,
)

__all__ = [
    "release_analyze", "release_review",
    "release_stage_design", "release_stage_review",
    "release_gate", "release_release",
]


def release_analyze(rid: str, product: str) -> int:
    """worker 完成分析后调用：校验产物 → analyzing→analyzed，清 claim。"""
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e or e["status"] != "analyzing":
            print(f"release_analyze: {rid} 状态不是 analyzing，拒绝", file=sys.stderr)
            return 1
        full = product_path(product)
        if not os.path.exists(full):
            # 产物缺失 → 视为失败：自动回滚，交由重试/stale 兜底
            alarms: list = []
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
        full = product_path(product)
        if not os.path.exists(full):
            alarms: list = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_review: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        e["round"] = int(e.get("round", 0)) + 1
        e["reviews"] = e.get("reviews", []) + [product]
        if conclusion == "PASS":
            e["status"] = "approved"
            # 同步写 stages.req.state=done，让 _find_block_stage 能识别 req 已通过。
            # 这里不用 set_stage_state：它的 done 校验要求 cur=reviewing，但 req 评审走的是顶层 reviewing
            # （stages.req 可能从未 working），我们只在 done 字段上写一个事实标记（_find_block_stage
            # 只读这个字段判断是否 done）。
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
                with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
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
        if not os.path.exists(product_path(product)):
            alarms: list = []
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
        if not os.path.exists(product_path(product)):
            alarms: list = []
            rollback_entry(st, rid, alarms, reason="missing-product")
            write_status(st)
            print(f"release_stage_review: 产物 {product} 不存在，已回滚", file=sys.stderr)
            return 1
        s = ensure_stages(e)[stage]
        s["reviews"] = s.get("reviews", []) + [product]
        s["round"] = int(s.get("round", 0)) + 1  # 评审完成：轮次递增
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
                with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
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
        if not os.path.exists(product_path(product)):
            alarms: list = []
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
                with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
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
        if not os.path.exists(product_path(product)):
            alarms: list = []
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