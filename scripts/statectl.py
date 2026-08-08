#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
req-review 流水线状态控制与上下半部调度（方案 B 唯一实现）

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

WORKDIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))  # req-review/（realpath：兼容 ~/.hermes/scripts/ 下的符号链接调用）
INPUT_DIR = os.path.join(WORKDIR, "input")
ANALYSIS_DIR = os.path.join(WORKDIR, "analysis")
REVIEW_DIR = os.path.join(WORKDIR, "review")
ARTIFACT_DIR = os.path.join(WORKDIR, "artifacts")
LOG_DIR = os.path.join(WORKDIR, "logs")
SCRIPTS_DIR = os.path.join(WORKDIR, "scripts")
STATUS_FILE = os.path.join(WORKDIR, "status.json")
LOCK_FILE = os.path.join(WORKDIR, "status.lock")
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")
ALARM_FILE = os.path.join(LOG_DIR, "alarms.txt")

STALE_AFTER_MIN = int(os.environ.get("STALE_AFTER_MIN", "20"))   # 中间态超时（分钟）
MAX_FAILURES = int(os.environ.get("MAX_FAILURES", "2"))          # 连续失败上限
DEFAULT_MAX_ROUNDS = int(os.environ.get("DEFAULT_MAX_ROUNDS", "3"))

# 下半部 worker 模型绑定（不同角色不同模型；可用环境变量覆盖）
# 当前 API（api.deepseek.com）可用模型：deepseek-v4-flash（快/便宜）、deepseek-v4-pro（强推理）
ANALYST_MODEL = os.environ.get("ANALYST_MODEL", "deepseek-v4-flash")
ANALYST_PROVIDER = os.environ.get("ANALYST_PROVIDER", "deepseek")
REVIEWER_MODEL = os.environ.get("REVIEWER_MODEL", "deepseek-v4-pro")
REVIEWER_PROVIDER = os.environ.get("REVIEWER_PROVIDER", "deepseek")

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
    """input/ 下未登记文件自动注册为 pending。返回新注册的 req_id 列表。"""
    registered = []
    if not os.path.isdir(INPUT_DIR):
        return registered
    for name in sorted(os.listdir(INPUT_DIR)):
        if not name.endswith(".md"):
            continue
        rid = name[:-3]
        if rid in st:
            continue
        st[rid] = {
            "status": "pending",
            "round": 0,
            "max_rounds": DEFAULT_MAX_ROUNDS,
            "forced": False,
            "analysis": None,
            "reviews": [],
            "failures": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        registered.append(rid)
        log(f"REGISTER {rid} status=pending round=0")
    return registered


def rollback_entry(st: dict, rid: str, alarms: list, reason: str) -> None:
    """中间态回滚：analyzing→pending / reviewing→analyzed；failures+1；达上限置 blocked。"""
    e = st[rid]
    was = e["status"]
    prev = "pending" if was == "analyzing" else "analyzed"
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
        if e.get("status") not in ("analyzing", "reviewing"):
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


def find_claimable(st: dict, role: str):
    """找最老（updated_at 最早）的可认领需求。返回 (req_id, entry) 或 None。"""
    cands = []
    for rid, e in st.items():
        if role == "analyst" and e.get("status") in ("pending", "needs_fix"):
            cands.append((e.get("updated_at", ""), rid, e))
        elif role == "reviewer" and e.get("status") == "analyzed":
            cands.append((e.get("updated_at", ""), rid, e))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    return cands[0][1], cands[0][2]


def claim(st: dict, rid: str, role: str) -> bool:
    """原子认领（compare-and-swap）：仅目标状态匹配时迁入中间态并写 claim 字段。"""
    e = st.get(rid)
    if not e:
        return False
    ok = (role == "analyst" and e["status"] in ("pending", "needs_fix")) or (
        role == "reviewer" and e["status"] == "analyzed"
    )
    if not ok:
        return False
    new_state = "analyzing" if role == "analyst" else "reviewing"
    log(f"CLAIM {rid} by={role} from={e['status']}")
    e["status"] = new_state
    e["claimed_by"] = role
    e["claimed_at"] = now_iso()
    e["worker_pid"] = 0  # spawn 后由 setpid 填充
    e["updated_at"] = now_iso()
    return True


def build_worker_query(role: str, rid: str, e: dict):
    """构造下半部 worker 的启动指令。返回 (round_n, query)。"""
    if role == "analyst":
        n = int(e["round"]) + 1
        out = f"analysis/{rid}-r{n}.md"
        q = [
            f"你是本流水线的【需求分析师】下半部 worker。严格遵循 roles/analyst.md 完成需求 {rid} 的第 {n} 轮分析/修改。",
            "输入文件：",
            f"- 需求原文：input/{rid}.md",
        ]
        if e.get("analysis"):
            q.append(f"- 上一版分析（修改轮必读）：{e['analysis']}")
        if e.get("reviews"):
            q.append(f"- 最新评审意见（修改轮必须逐条回应）：{e['reviews'][-1]}")
        q += [
            "任务：",
            f"1. 按 roles/analyst.md 的输出模板与工作原则产出本轮分析报告；",
            f"2. 写入 {out}；",
            f"3. 运行 python3 scripts/statectl.py release_analyze {rid} {out} 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报，过程留痕在 worker 日志即可。",
        ]
        return n, "\n".join(q)
    else:  # reviewer
        n = int(e["round"]) + 1
        out = f"review/{rid}-r{n}.md"
        analysis_file = e.get("analysis") or f"analysis/{rid}-r{n}.md"
        q = [
            f"你是本流水线的【需求评审师】下半部 worker。严格遵循 roles/reviewer.md 评审需求 {rid} 的第 {n} 轮分析。",
            "输入文件：",
            f"- 需求原文：input/{rid}.md",
            f"- 分析报告：{analysis_file}",
            f"注意：本需求 max_rounds={e.get('max_rounds', DEFAULT_MAX_ROUNDS)}，第 {n} 轮仍 FAIL 将由状态机自动强制归档，你无需关心。",
            "任务：",
            f"1. 按 roles/reviewer.md 的检查清单与输出模板评审；",
            f"2. 结论 PASS 或 FAIL，写入 {out}；",
            f"3. 运行 python3 scripts/statectl.py release_review {rid} {out} PASS|FAIL 完成状态更新（该命令会校验产物存在）；",
            "4. 完成后无需汇报。",
        ]
        return n, "\n".join(q)


def spawn_worker(role: str, rid: str, round_n: int, query: str) -> int:
    """setsid 拉起下半部 worker（独立会话，脱离 cron 进程组，不受 3 分钟限制）。"""
    model = ANALYST_MODEL if role == "analyst" else REVIEWER_MODEL
    provider = ANALYST_PROVIDER if role == "analyst" else REVIEWER_PROVIDER
    os.makedirs(LOG_DIR, exist_ok=True)
    logf = open(os.path.join(LOG_DIR, f"worker-{rid}-r{round_n}.log"), "ab")
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
    log(f"SPAWN {rid} worker={role} pid={p.pid} model={model} round={round_n}")
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


def write_artifact(rid: str, e: dict) -> None:
    """评审通过（含强制）后归档：结论摘要 + 原文 + 最终分析 + 全部评审历史。"""
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    reviews = e.get("reviews") or []
    forced = e.get("forced", False)
    parts = [f"# 需求评审归档：{rid}", ""]
    # 结论摘要区（快速全貌：接手开发 / 审计核对的第一屏）
    parts += ["## 结论摘要", "",
              f"- 状态：**{e.get('status', 'approved')}**（{'⚠️ 达到轮次上限强制归档，需人工复核' if forced else '正常评审通过'}）",
              f"- 最终轮次：r{e.get('round', 1)}（共 {len(reviews)} 轮评审）",
              f"- 最终分析：`{e.get('analysis', '')}`",
              f"- 评审历史：{' → '.join('`' + r + '`' for r in reviews) if reviews else '（无）'}（最后一轮为最终评审）",
              f"- 归档时间：{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
              "",
              "> 接手开发请以【需求原文 + 最终分析 + 最终评审（最后一轮）】为准；前面轮次的评审意见为过程记录（已解决或已驳回）。",
              ""]
    orig = os.path.join(INPUT_DIR, rid + ".md")
    if os.path.exists(orig):
        with open(orig, encoding="utf-8") as f:
            parts += ["## 需求原文", "", f.read().strip(), ""]
    if e.get("analysis"):
        ap = os.path.join(WORKDIR, e["analysis"])
        if os.path.exists(ap):
            with open(ap, encoding="utf-8") as f:
                parts += [f"## 最终分析（{e['analysis']}）", "", f.read().strip(), ""]
    if reviews:
        parts += [f"## 评审历史（{len(reviews)} 轮）", ""]
        for rp in reviews:
            full = os.path.join(WORKDIR, rp)
            if os.path.exists(full):
                with open(full, encoding="utf-8") as f:
                    parts += [f"### {rp}", "", f.read().strip(), ""]
    if forced:
        parts += ["## 备注", "本需求达到轮次上限被强制归档（forced=true），仍有未解决意见，请人工复核。"]
    with open(os.path.join(ARTIFACT_DIR, rid + ".md"), "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    log(f"ARCHIVE {rid} file=artifacts/{rid}.md forced={forced}")


# ---------------- 上半部 tick ----------------

def analyst_tick() -> int:
    with acquire_lock() as _:
        st = read_status()
        alarms = []
        register_new_inputs(st)
        alarms += stale_recovery(st)
        found = find_claimable(st, "analyst")
        if found:
            rid, e = found
            if claim(st, rid, "analyst"):
                n, query = build_worker_query("analyst", rid, e)
                pid = spawn_worker("analyst", rid, n, query)
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
            rid, e = found
            if claim(st, rid, "reviewer"):
                n, query = build_worker_query("reviewer", rid, e)
                pid = spawn_worker("reviewer", rid, n, query)
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
        for rid, e in sorted(st.items()):
            s = e.get("status")
            if s == "approved":
                if not os.path.exists(os.path.join(ARTIFACT_DIR, rid + ".md")):
                    issues.append(f"[AUDIT] 需求 {rid} 已 approved 但缺 artifacts/{rid}.md")
                if e.get("forced"):
                    issues.append(f"[AUDIT] 需求 {rid} 为强制归档（forced），请人工复核 artifacts/{rid}.md")
            elif s == "blocked":
                issues.append(f"[AUDIT] 需求 {rid} 处于 blocked，需人工介入（python3 scripts/statectl.py requeue {rid}）")
            elif s in ("analyzing", "reviewing"):
                issues.append(f"[AUDIT] 需求 {rid} 滞留 {s}（中间态不应跨周存在）")
        if os.path.isdir(INPUT_DIR):
            for name in sorted(os.listdir(INPUT_DIR)):
                if name.endswith(".md") and name[:-3] not in st:
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
        full = os.path.join(WORKDIR, product)
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
        full = os.path.join(WORKDIR, product)
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
                with open(ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(
                        f"[FORCED] 需求 {rid} 第 {e['round']} 轮仍 FAIL，已达 max_rounds，"
                        f"已强制归档（artifacts/{rid}.md），请人工复核未解决意见。\n"
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


def cmd_next(role: str) -> int:
    with acquire_lock() as _:
        st = read_status()
        found = find_claimable(st, role)
    if found:
        rid, e = found
        print(f"{rid}\t{e['status']}\tround={e['round']}\tmax_rounds={e.get('max_rounds')}")
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
        if rid not in st or st[rid]["status"] not in ("analyzing", "reviewing"):
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
    print(f"{'REQ-ID':<16} {'STATUS':<10} {'ROUND':<6} {'FORCED':<7} {'FAIL':<5} UPDATED_AT")
    for rid, e in sorted(st.items()):
        print(
            f"{rid:<16} {e['status']:<10} {e['round']:<6} {str(e.get('forced', False)):<7} "
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
        for rid, e in sorted(st.items()):
            if e.get("status") != "approved":
                continue
            upd = e.get("updated_at", "")
            if marker and upd <= marker:
                continue
            new_items.append((rid, e))
        if new_items:
            lines = [f"📋 需求评审结果（新增 {len(new_items)} 项归档）"]
            for rid, e in new_items:
                forced = " ⚠️强制归档（需人工复核）" if e.get("forced") else ""
                lines.append(f"✅ {rid} — 第 {e.get('round', '?')} 轮通过{forced}（artifacts/{rid}.md）")
            out = "\n".join(lines)
        else:
            out = ""
        with open(NOTIFY_MARKER, "w", encoding="utf-8") as f:
            f.write(now)
    if out:
        print(out)
    return 0


# ---------------- 诊断（DFx：一键健康检查） ----------------

STATE_SET = {"pending", "analyzing", "analyzed", "reviewing", "needs_fix", "approved", "blocked"}
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

    # D2 目录完整性
    missing = [d for d in ("input", "analysis", "review", "artifacts", "logs", "roles", "scripts", "docs")
               if not os.path.isdir(os.path.join(WORKDIR, d))]
    add("PASS" if not missing else "FAIL", "D2", "目录完整" if not missing else f"缺失目录: {missing}")

    # D3–D8 逐条目检查
    for rid, e in st.items():
        miss_f = [f for f in REQUIRED_FIELDS if f not in e]
        if miss_f:
            add("WARN", "D3", f"{rid} 缺字段 {miss_f}")
        s = e.get("status")
        if s not in STATE_SET:
            add("FAIL", "D4", f"{rid} 非法状态 {s!r}（合法: {sorted(STATE_SET)}）")
        if s in ("analyzing", "reviewing"):
            ca = e.get("claimed_at")
            if not ca:
                add("WARN", "D5", f"{rid} 处于 {s} 但无 claimed_at（下个 tick 的 stale 恢复会处理）")
            else:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(ca.replace("Z", "+00:00"))).total_seconds() / 60.0
                except ValueError:
                    age = STALE_AFTER_MIN + 1
                if age >= 24 * 60:
                    add("WARN", "D5", f"{rid} 滞留 {s} 已 {age:.0f} 分钟（>24h，异常，查 worker 日志）")
                elif age >= STALE_AFTER_MIN:
                    add("WARN", "D5", f"{rid} 滞留 {s} 已 {age:.0f} 分钟（>{STALE_AFTER_MIN}min，将自动 stale 恢复；或 rollback {rid}）")
        else:
            leftover = [k for k in ("claimed_by", "claimed_at", "worker_pid") if k in e]
            if leftover:
                add("WARN", "D6", f"{rid} 非中间态却残留 claim 字段 {leftover}（可手动清理）")
        for k in (e.get("analysis"),) + tuple(e.get("reviews", [])):
            if k and not os.path.exists(os.path.join(WORKDIR, k)):
                add("WARN", "D7", f"{rid} 引用文件缺失: {k}")
        if s == "approved":
            if not os.path.exists(os.path.join(ARTIFACT_DIR, rid + ".md")):
                add("WARN", "D8", f"{rid} 已 approved 但缺 artifacts/{rid}.md")
            if e.get("forced"):
                add("WARN", "D8", f"{rid} 为强制归档（forced），请人工复核未解决意见")

    # D9 input/ 未登记
    if os.path.isdir(INPUT_DIR):
        unreg = [n[:-3] for n in sorted(os.listdir(INPUT_DIR)) if n.endswith(".md") and n[:-3] not in st]
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
    for name in ("req-analyst-top", "req-reviewer-top", "req-weekly-audit", "req-result-notify"):
        if f"Name:      {name}" not in out and f"Name: {name}" not in out:
            add("WARN", "D12", f"cron job {name} 缺失（重建命令见 README 快速开始）")

    # D13 worker 进程
    out = _sh(["ps", "-eo", "args"])
    n = sum(1 for ln in out.splitlines() if "hermes chat" in ln and " -q " in ln)
    add("INFO", "D13", f"当前下半部 worker 进程数: {n}")

    # D14 日志可写
    add("PASS" if os.access(LOG_DIR, os.W_OK) else "FAIL", "D14", "logs/ 目录可写")

    print("== req-review 诊断报告 ==")
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
        if cmd == "register":
            return cmd_register()
        if cmd == "stale":
            return cmd_stale()
        if cmd == "next":
            return cmd_next(rest[0])
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
