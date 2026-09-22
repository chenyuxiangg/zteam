"""资源感知恢复 + 版本 unblock + blocked 原因判定。

- 版本 unblock：blocked 版本 → 回**被打断阶段**（blocked_from，缺省 planning），
  清 failures/claim。无锁纯逻辑（调用方持锁）。
- 资源感知自动恢复：blocked 且原因=resource:minimax（配额耗尽）或
  network（API 超时/连接失败）→ 配额检查通过后自动 unblock（写审计 + 通知）
- blocked 原因判定：扫描 worker 日志尾部关键词（429/quota/timeout 等）
- MiniMax 配额检查：调 check_minimax_quota.py（退出码 0=健康）

模块 unblock（_module_unblock）暂留 statectl.py——依赖 modules.py（未拆出），
待 commit 4c/d 拆 modules.py 时一并下沉到此处统一引用。
"""
from __future__ import annotations

import os
import subprocess
import sys

from . import paths as _paths
from .paths import LOG_DIR, project_dir
from .status import log
from .versions import read_versions, write_versions

__all__ = [
    "_version_unblock",
    "_resource_blocked_reason", "_resource_unblock",
    "_minimax_quota_ok", "_log_matches", "_mark_blocked_reason",
]


# ---- 版本 unblock（模块 unblock 暂留 statectl.py，见模块 docstring）----

def _version_unblock(project: str, version: str) -> int:
    """版本 unblock：blocked 版本 → 回**被打断阶段**（blocked_from，缺省 planning 兼容旧数据），清 failures/claim。无锁纯逻辑（调用方持锁）。"""
    vd = read_versions(project)
    v = next((x for x in vd["versions"] if x["name"] == version), None)
    if not v:
        print(f"版本 {version} 不存在", file=sys.stderr)
        return 1
    if v.get("status") != "blocked":
        print(f"版本 {version} 非 blocked（当前 {v.get('status')}）", file=sys.stderr)
        return 1
    for k in ("arch_claimed", "arch_claimed_pid", "arch_review_claimed", "arch_review_claimed_pid",
              "test_plan_claimed", "test_plan_claimed_pid", "testplan_review_claimed",
              "testplan_review_claimed_pid", "st_claimed", "st_claimed_pid",
              "qa_claimed", "qa_claimed_pid", "blocked_reason"):
        v.pop(k, None)
    back = v.pop("blocked_from", None) or "planning"
    v["status"] = back
    v["failures"] = 0
    write_versions(project, vd)
    log(f"VERSION_UNBLOCK {project}/{version} -> {back}（人工/资源恢复，回被打断阶段）")
    return 0


# ---- blocked 原因判定 + 资源感知自动恢复 ----

def _resource_blocked_reason(project: str, it_or_v: dict, key: str) -> str:
    """判定 blocked 原因：先看已标记 blocked_reason；未标 → 扫关联 worker 日志尾部（429/配额 → resource:minimax）。
    其他 → 'other'（人工介入）。"""
    r = it_or_v.get("blocked_reason") or ""
    if r:
        return r
    # 扫项目 worker 日志（key 关联）+ errors.log 尾部
    tail_buf: list = []
    for d in (project_dir(project), os.path.join(project_dir(project), "logs"), LOG_DIR):
        if not os.path.isdir(d):
            continue
        try:
            for fn in sorted(os.listdir(d)):
                if key.replace("/", "-") in fn or fn == "errors.log" or "errors" in fn:
                    fp = os.path.join(d, fn)
                    if os.path.getsize(fp) < 50 * 1024 * 1024:
                        tail_buf.append(open(fp, encoding="utf-8", errors="replace").read()[-8000:])
        except Exception:
            continue
    blob = " ".join(tail_buf).lower()
    if any(w in blob for w in ("429", "quota", "配额已耗尽", "rate limit", "insufficient_quota")):
        it_or_v["blocked_reason"] = "resource:minimax"
        return "resource:minimax"
    it_or_v["blocked_reason"] = "other"
    return "other"


def _resource_unblock(project: str, md: dict, vd: dict, alarms: list) -> None:
    """资源感知自动恢复（用户需求）：blocked 且原因=资源/网络（临时性）→ 检查资源 → 恢复后自动 unblock（zbot 通知）。
    其他原因（other）保持人工。

    注意：本函数直接改调用方传入的 md/vd 内存对象——不能调 _module_unblock / _version_unblock
    （它们会重读盘改盘，与调用方内存脱节，被紧随的 _schedule_module_iter 旧内存整写覆盖回
    blocked → 无限循环 2026-09-07）。"""
    for m in md.get("modules", []):
        for it in m.get("iterations", []):
            if it.get("status") != "blocked":
                continue
            reason = _mark_blocked_reason(project, m["name"], it)  # key=模块名（宽匹配 worker-__{role}-{模块}-it{N}）
            if reason not in ("resource:minimax", "network"):
                continue
            if reason == "network" or _minimax_quota_ok():
                for k in ("claimed", "claimed_pid", "fix_claimed", "fix_claimed_pid", "retest_claimed",
                          "retest_claimed_pid", "design_review_claimed", "design_review_claimed_pid",
                          "review_claimed", "review_claimed_pid", "review_feedback", "design_review_feedback",
                          "waiting_issues", "blocked_reason"):
                    it.pop(k, None)
                it["status"] = "design_pending"
                it["failures"] = 0
                it["retry_count"] = 0
                it["design_retry_count"] = 0
                it["case_retry_count"] = 0
                log(f"MODULE_UNBLOCK {project}/{m['name']} iter-{it['n']} -> design_pending（资源恢复·内联）")
                with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[RESOURCE_RECOVERED] 模块 {project}/{m['name']} iter-{it['n']} {reason} 恢复，已自动 unblock 重跑。\n")
                alarms.append(f"模块 {m['name']} 迭代 {it['n']} {reason} 恢复自动恢复")
    for v in vd.get("versions", []):
        if v.get("status") != "blocked":
            continue
        reason = _mark_blocked_reason(project, v["name"], v)
        if reason not in ("resource:minimax", "network"):
            continue
        if reason == "network" or _minimax_quota_ok():
            for k in ("arch_claimed", "arch_claimed_pid", "arch_review_claimed", "arch_review_claimed_pid",
                      "test_plan_claimed", "test_plan_claimed_pid", "testplan_review_claimed",
                      "testplan_review_claimed_pid", "st_claimed", "st_claimed_pid",
                      "qa_claimed", "qa_claimed_pid", "blocked_reason"):
                v.pop(k, None)
            back = v.pop("blocked_from", None) or "planning"
            v["status"] = back
            v["failures"] = 0
            log(f"VERSION_UNBLOCK {project}/{v['name']} -> {back}（资源恢复·内联，回被打断阶段）")
            with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                f.write(f"[RESOURCE_RECOVERED] 版本 {project}/{v['name']} {reason} 恢复，已自动 unblock 重跑。\n")
            alarms.append(f"版本 {v['name']} 资源恢复自动恢复")
    # 内存已是最新（调用方后续 _schedule_* 会整写落盘）；此处再显式写一次防无后续写盘场景
    # write_modules 由调用方写（resources.py 不依赖 modules.py）
    write_versions(project, vd)


def _minimax_quota_ok() -> bool:
    """MiniMax 配额检查（脚本固定规则，非 AI 读日志）：
    check_minimax_quota.py 退出码 0=健康（judge() 数值判定：5h≥30% 且周≥50%）→ 可自动恢复。
    1/2=紧张/受限、3=调用失败 → 不自动恢复（保守）。"""
    qs = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "scripts", "check_minimax_quota.py")
    try:
        r = subprocess.run(["python3", qs, "--quiet"], capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _log_matches(fn: str, key: str) -> bool:
    """日志名匹配（精确模式，防短名子串串扰）：
    模块 worker：worker-__{role}-{模块}-it{N}-r{n}-{role}.log → 模式 '-{模块}-it'
    版本 worker：worker-__arch{版本}/__archrev{版本}/__tp{版本}/__tprev{版本}/__sto{版本}/__qa{版本}... → 前缀 '__xxx{版本}'"""
    if key.startswith("v") and any(c.isdigit() for c in key):
        return any(f"__{p}{key}" in fn for p in ("arch", "archrev", "tp", "tprev", "sto", "qa", "st"))
    return f"-{key}-it" in fn


def _mark_blocked_reason(project: str, key: str, it_or_v: dict) -> str:
    """blocked 原因判定（脚本固定规则）：读该 key 关联 worker 日志尾部（精确路径 worker-{key}-r{N}-{role}.log
    或含 key 的 worker 日志）→ 关键词分类：
      resource:minimax（429/配额/rate limit/insufficient_quota）→ 配额恢复后自动 unblock
      network（timeout/APITimeoutError/ConnectionError）→ 临时性，自动重试
      other → 人工介入（永不自动）
    与 AI 无关——纯代码扫描固定规则；判定结果写入 blocked_reason 持久化。"""
    if it_or_v.get("blocked_reason"):
        return it_or_v["blocked_reason"]
    # 评审 FAIL×N 打回的 blocked 是内容问题（review_feedback/design_review_feedback 为 FAIL 打回痕迹）——
    # 直接判 other（人工介入，永不自动 unblock）；只有 stale/进程类 blocked（无 feedback）才按 network/resource 自动判。
    # 2026-09-07：曾误判 network 导致 soc-sim 内容性 blocked 被无限自动 unblock（评审日志里的 API timeout 字样误导关键词扫描）
    if it_or_v.get("review_feedback") or it_or_v.get("design_review_feedback"):
        it_or_v["blocked_reason"] = "other"
        return "other"
    key_norm = key.replace("/", "-")
    tail_buf: list = []
    # 只扫本项目日志（v2 每项目独立目录）+ 全局 errors.log 兜底；不扫全局 worker-*（v1 遗留跨项目，防串扰）
    for d in (os.path.join(project_dir(project), "logs"), LOG_DIR):
        if not os.path.isdir(d):
            continue
        try:
            for fn in sorted(os.listdir(d)):
                fp = os.path.join(d, fn)
                if fn == "errors.log":
                    pass  # 全局/项目 errors.log 都兜底
                elif fn.startswith("worker-") and d != LOG_DIR and _log_matches(fn, key_norm):
                    pass  # 本项目 worker 日志，精确模式匹配
                else:
                    continue
                try:
                    if os.path.getsize(fp) < 50 * 1024 * 1024:
                        tail_buf.append(open(fp, encoding="utf-8", errors="replace").read()[-8000:])
                except OSError:
                    continue
        except OSError:
            continue
    blob = " ".join(tail_buf).lower()
    if any(w in blob for w in ("429", "quota", "配额已耗尽", "rate limit", "insufficient_quota", "余额不足")):
        it_or_v["blocked_reason"] = "resource:minimax"
    elif any(w in blob for w in ("timeout", "apitimeouterror", "connectionerror", "连接超时", "超时")):
        it_or_v["blocked_reason"] = "network"
    else:
        it_or_v["blocked_reason"] = "other"
    return it_or_v["blocked_reason"]