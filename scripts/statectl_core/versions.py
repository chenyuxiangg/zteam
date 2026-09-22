"""版本管理（项目 → 版本 → 需求归属 + IT/STQ 调度 + 规格确认/驳回）。

- versions.json CRUD：ensure_versions / read_versions / write_versions
- 版本推进：advance_versions（惰性，所有需求 released → 版本 released）
- current 自动开新版本：advance_current（注册盲区修复）
- 需求文件 frontmatter 元数据解析：_parse_req_meta
- 调度：_advance_v2 / _schedule_it_st / _version_guard_watch
- 人工：cmd_confirm / cmd_reject（v2 规格评审）
- 评审回调：release_it / release_st（IT/PASS/FAIL 落定）
"""
from __future__ import annotations

import json
import os
import re
import sys

from . import paths as _paths
from .paths import WORKDIR, now_iso, project_dir, read_projects, rel_artifact, split_key, write_projects
from .pipeline import norm_product, product_path, spawn_worker
from .status import (
    acquire_lock,
    log,
    read_status,
    write_status,
)

__all__ = [
    "VERSIONS_FILE", "versions_path", "VERSION_FLOW",
    "_claims_sig", "_version_guard_watch",
    "ensure_versions", "read_versions", "advance_current", "write_versions",
    "_parse_req_meta", "advance_versions",
    "_it_inputs", "_schedule_it_st", "_advance_v2",
    "release_it", "release_st",
    "cmd_confirm", "cmd_reject", "_sync_project_version",
]

VERSIONS_FILE = "versions.json"


def versions_path(project: str) -> str:
    return os.path.join(project_dir(project), VERSIONS_FILE)


# ---- ③ 版本状态可达性表（v2 版本状态机——每个状态必须有接走通道；改状态机时同步维护此表 + diagnose D16 回归）
# channel: auto_sched=调度器分支（claim=False 自动 spawn/推进）| auto_done=worker 完成 release_* 回（claim 活态）
#          wait_user=等待用户/人工（notify/unblock 通道）| term=终态
# stuck=guard 兜底回退落点（该状态无接走通道时的安全回退）
VERSION_FLOW = {
    "planning":       {"channel": {"auto_sched"},                        "desc": "待 SE 架构（规格全锁定→spawn SE）"},
    "arch":           {"channel": {"auto_done"},   "stuck": "planning", "desc": "SE 架构中（release_arch DONE→arch_reviewing）；claim=False 滞留=死状态→guard 回 planning"},
    "arch_reviewing": {"channel": {"auto_sched", "auto_done"},           "desc": "PM 评审架构（release_arch PASS→testplan / FAIL→planning）"},
    "testplan":       {"channel": {"auto_sched", "auto_done"},           "desc": "TE 测试方案（release_testplan_v2 DONE→testplan_reviewing）"},
    "testplan_reviewing": {"channel": {"auto_sched", "auto_done"},       "desc": "SE 评审方案（PASS→in_dev / FAIL→testplan）"},
    "in_dev":         {"channel": {"auto_sched"},                        "desc": "模块迭代开发（_schedule_module_iter + 全 it_passed→st）"},
    "st":             {"channel": {"auto_done"},                        "desc": "STO 系统测试（release_st_v2 DONE→st_done）"},
    "st_done":        {"channel": {"auto_sched"},                        "desc": "ST 完成→qa（_schedule_st_qa spawn QA）"},
    "qa":             {"channel": {"auto_done"},                        "desc": "QA 发布评审（release_qa DONE→qa_reviewing）"},
    "qa_reviewing":   {"channel": {"wait_user"},                        "desc": "等用户确认用户指南（confirm_guide→released / reject_guide→qa）"},
    "released":       {"channel": {"term"},                             "desc": "终态"},
    "blocked":        {"channel": {"wait_user"},                        "desc": "人工 unblock"},
}
# v1 遗留状态（若 v2 数据出现 = 死状态，D16 报）：st_pending/st_passed/quality_pending/quality/security 等


def _version_guard_watch(project: str, vd: dict, alarms: list) -> None:
    """② 版本级巡检兜底（防静默卡死——仿 req 级 guard）：
    - arch + claim=False：死状态（无调度分支可接走）→ 立即补正回 planning（自动重调度 SE）
    - 其余中间态：连续 N tick 状态/claim 无变化（应推进未推进）→ VERSION_STUCK 告警（写审计 + alarms）
    脚本固定规则；补正仅限明确安全回退，其余告警为主（不自动改防误伤）。"""
    for v in vd.get("versions", []):
        status = v.get("status")
        if status in ("released", "blocked"):
            continue
        if status not in VERSION_FLOW:
            log(f"VERSION_GUARD {project}/{v['name']} 未知状态 {status}（不在可达性表）")
            alarms.append(f"版本 {v['name']} 状态 {status} 不在可达性表（VERSION_FLOW），需人工核查")
            continue
        # 死状态即时补正：arch + claim=False（无 worker 在跑也无调度分支能接走——只有 release_arch DONE 能离开但没人产出）
        if status == "arch" and not v.get("arch_claimed"):
            v["status"] = "planning"
            v["arch_failures"] = int(v.get("arch_failures", 0)) + 1
            log(f"VERSION_GUARD {project}/{v['name']} arch+无claim=死状态 → 回 planning（SE 重调度，累计 {v['arch_failures']} 次）")
            alarms.append(f"版本 {v['name']} 卡死 arch（无 claim）已自动回 planning 重调度 SE（第 {v['arch_failures']} 次）——若反复出现请人工核查架构评审 FAIL 原因")
            v["_guard_sig"] = f"{status}|{_claims_sig(v)}"
            v["_guard_ticks"] = 0
            continue
        # in_dev：开发期长驻状态，推进信号在模块迭代（claim/状态），版本 claim 恒空——
        # 版本级滞留检测对 in_dev 无意义（曾每 ~60 分钟误报 VERSION_STUCK），跳过
        if status == "in_dev":
            v.pop("_guard_sig", None)
            v.pop("_guard_ticks", None)
            continue
        # 滞留检测：状态/claim 组合连续 tick 无变化（调度器应推进却未推进）
        sig = f"{status}|{_claims_sig(v)}"
        if v.get("_guard_sig") == sig:
            v["_guard_ticks"] = int(v.get("_guard_ticks", 0)) + 1
        else:
            v["_guard_sig"] = sig
            v["_guard_ticks"] = 0
        ticks = int(v.get("_guard_ticks", 0))
        flow = VERSION_FLOW.get(status, {})
        no_worker = "True" not in _claims_sig(v)  # 所有 claim 均为 False（_claims_sig 全 False 也返回非空串——须查子串）
        if (ticks >= 12 and no_worker and "auto_done" not in flow.get("channel", set())
                and "wait_user" not in flow.get("channel", set())):
            # "wait_user" 状态（qa_reviewing 等 confirm_guide / blocked 等 unblock）本就不应有 worker
            # ——"等用户"非卡死，不计滞留（2026-09-11 修：曾对 qa_reviewing 每 ~60 分钟误报 VERSION_STUCK）
            # 12 tick（~60 分钟）无活 worker 且状态非"等 worker 回 release_*" → 应被调度/推进却停滞
            log(f"VERSION_STUCK {project}/{v['name']} 状态 {status} 滞留 {ticks} tick 无推进（claims 全空）")
            alarms.append(f"版本 {v['name']} 疑似卡死：状态 {status} 滞留 {ticks * 5} 分钟无活 worker 无推进——"
                          f"可能调度前置条件不满足（如规格未锁定/版本串行/依赖），请核查 versions.json + pipeline.log")
            v["_guard_ticks"] = 0  # 告警后重置（防每 tick 重复告警）


def _claims_sig(v: dict) -> str:
    """版本 claim 组合签名（判断有无活 worker/待评审）。"""
    return "|".join(str(bool(v.get(c))) for c in
                    ("arch_claimed", "arch_review_claimed", "test_plan_claimed",
                     "testplan_review_claimed", "st_claimed", "qa_claimed"))


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


def advance_current(project: str) -> str:
    """版本推进（注册盲区修复）：current 版本已 released 时自动开新版本（语义化 minor+1）为 current；
    否则返回当前 current。调用方在注册新需求未指定版本时使用。"""
    vd = read_versions(project)
    cur = vd.get("current", "v1.0.0")
    v = next((x for x in vd["versions"] if x["name"] == cur), None)
    if v and v.get("status") != "released":
        return cur
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", cur)
    base_minor = int(m.group(2)) if m else 0
    i = 1
    while True:
        new_name = f"v1.{base_minor + i}.0"
        if not next((x for x in vd["versions"] if x["name"] == new_name), None):
            break
        i += 1
    nv = {"name": new_name, "status": "planning", "iterations": [],
          "reqs": [], "released_at": None,
          "architecture": None, "module_plan": None, "test_plan": None,
          "qa_report": None, "release_pkg": None, "st_product": None,
          "st_claimed": False, "qa_claimed": False}
    vd["versions"].append(nv)
    vd["current"] = new_name
    write_versions(project, vd)
    log(f"VERSION_ADVANCE {project}: current {cur}(released) → 新版本 {new_name}（自动）")
    return new_name


def write_versions(project: str, vd: dict) -> None:
    p = versions_path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(vd, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


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
                    f"你是本流水线的【集成测试设计执行者】。严格遵循 {WORKDIR}/roles/it-designer.md "
                    f"为项目 {project} 版本 {v['name']} 的迭代 {it['n']} 执行集成测试（IT）。\n"
                    f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {project}/__it{it['n']} test working（幂等，标记集成测试执行中）；\n"
                    f"迭代内需求（UT 均已通过）：\n{_it_inputs(project, reqs, st)}\n"
                    f"任务：1. 按 {WORKDIR}/roles/it-designer.md 在 {product_path(out)} 目录内产出集成测试（用例+报告+结论 PASS/FAIL）；\n"
                    f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_it {project} {v['name']} {it['n']} {out} 完成状态更新；\n"
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
                f"你是本流水线的【系统测试执行者】。严格遵循 {WORKDIR}/roles/st-tester.md "
                f"为项目 {project} 版本 {v['name']} 执行系统测试（ST，全部迭代 IT 已通过）。\n"
                f"启动时（第 0 步）：运行 python3 {WORKDIR}/scripts/statectl.py set_status {project}/__st{''.join(v['name'].split('.'))} test working（幂等）；\n"
                f"迭代集成测试产物：\n" + "\n".join(
                    f"- iter-{it['n']}：{it.get('it_product') or '?'}" for it in iters)
                + f"\n任务：1. 按 {WORKDIR}/roles/st-tester.md 在 {product_path(out)} 目录内产出系统测试（用例+报告+结论 PASS/FAIL）；\n"
                f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_st {project} {v['name']} {out} 完成状态更新；\n3. 完成后无需汇报。"
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
        full = product_path(product)
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
        full = product_path(product)
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
        if not e.get("analysis") or not os.path.exists(product_path(e["analysis"])):
            print(f"规格产物不存在或未登记: {e.get('analysis')}", file=sys.stderr)
            return 1
        e["status"] = "approved"
        e["approved_at"] = now_iso()
        e["updated_at"] = now_iso()
        write_status(st)
        log(f"USER_CONFIRM {rid} -> approved (规格锁定)")
    return 0


def _sync_project_version(project: str, version: str) -> None:
    """版本 released → 更新项目映射表 latest_version（脚本守护，AI 不自保证）。"""
    pj = read_projects()
    p = next((x for x in pj.get("projects", []) if x["name"] == project), None)
    if p:
        p["latest_version"] = version
        write_projects(pj)
        log(f"PROJECT_VERSION {project} -> {version}")


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


# 内部引用提示（保活 statectl.py 桥接兼容——发布期校验）。
_ = (WORKDIR, now_iso, project_dir, rel_artifact, split_key, norm_product,
     product_path, spawn_worker, acquire_lock, log, read_status, write_status)