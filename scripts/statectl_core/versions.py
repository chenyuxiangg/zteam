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

from .model_config import DEFAULT_MAX_ROUNDS
from .paths import (
    DEFAULT_PROJECT,
    WORKDIR,
    WORKSPACE_DIR,
    now_iso,
    project_dir,
    project_work_path,
    read_projects,
    split_key,
    write_projects,
)
from .pipeline import new_stages, norm_product, product_path, spawn_worker
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
    "_assign_iteration", "_register_one", "register_new_inputs",
    "release_it", "release_st", "release_arch", "release_testplan_v2",
    "cmd_confirm", "cmd_reject", "cmd_change_request",
    "cmd_project", "cmd_versions", "cmd_assign",
    "_valid_work_path", "_sync_project_version",
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


def _register_one(st: dict, proj: str, rid: str, full: str, registered: list) -> None:
    """单条需求注册为 pending（版本归属/冻结校验/落盘）——映射表与存量扫描共用。"""
    key = f"{proj}/{rid}"
    vd = ensure_versions(proj)
    meta = _parse_req_meta(full)
    ver = meta["version"]
    if not ver:
        ver = advance_current(proj)  # 未指定 → current；current released 时自动开新版本
        vd = read_versions(proj)  # advance 可能已落盘，重读
    else:
        # 显式指定 released 版本 → 拒绝（版本冻结，需开新版本承载）
        if ver in [x["name"] for x in vd["versions"]] and \
                next(x for x in vd["versions"] if x["name"] == ver).get("status") == "released":
            print(f"注册拒绝: {key} 指定版本 {ver} 已 released（冻结），请开新版本或 assign 到新版本", file=sys.stderr)
            log(f"REGISTER_REJECT {key} version={ver} released(冻结)")
            return
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


def register_new_inputs(st: dict) -> list:
    """扫描各项目 input/ 下未登记文件自动注册为 pending（项目目录自动创建）。
    结构：workspace/<project>/input/<req_id>.md（每个项目独立 input/）。
    兼容旧结构：workspace/input/<project>/<req_id>.md 与平铺 workspace/input/<req_id>.md（迁移前数据仍可注册）。
    返回新注册的 key（'<project>/<req_id>'）列表。"""
    registered = []
    # 新结构（项目工作路径解耦）：遍历映射表项目 → 扫 {work_path}/input/*.md（未登记项目不扫=强制先 project add）
    for p in read_projects().get("projects", []):
        idir = os.path.join(p["work_path"], "input")
        if not os.path.isdir(idir):
            continue
        for name in sorted(os.listdir(idir)):
            if not name.endswith(".md"):
                continue
            rid = name[:-3]
            key = f"{p['name']}/{rid}"
            if key in st:
                continue
            _register_one(st, p["name"], rid, os.path.join(idir, name), registered)
    # 存量兼容：workspace/<project>/input/*.md（迁移期旧数据仍可注册）
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
                _register_one(st, proj, rid, os.path.join(idir, name), registered)
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


def release_arch(project: str, version: str, product: str, conclusion: str) -> int:
    """架构阶段状态命令（v2）：
    SE 产出完成：release_arch {project} {version} {产物目录} DONE → arch_reviewing（等 PM 评审）
    PM 评审：    release_arch {project} {version} {评审意见} PASS|FAIL → PASS: testplan（TE 启动）/ FAIL: arch 重做"""
    conclusion = conclusion.strip().upper()
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        if conclusion == "DONE":
            if v.get("status") != "arch":
                print(f"版本状态非 arch（当前 {v.get('status')}）", file=sys.stderr)
                return 1
            full = product_path(product)
            if not os.path.exists(full):
                print(f"架构产物不存在: {full}", file=sys.stderr)
                return 1
            v["architecture"] = norm_product(product)
            v["status"] = "arch_reviewing"
            v["arch_claimed"] = False
            write_versions(project, vd)
            log(f"ARCH_DONE {project}/{version} product={v['architecture']}")
            return 0
        if conclusion not in ("PASS", "FAIL"):
            print("conclusion 必须为 DONE/PASS/FAIL", file=sys.stderr)
            return 1
        if v.get("status") != "arch_reviewing":
            print(f"评审仅对 arch_reviewing 有效（当前 {v.get('status')}）", file=sys.stderr)
            return 1
        v["arch_reviews"] = v.get("arch_reviews", []) + [norm_product(product)]
        v["arch_review_claimed"] = False  # 评审完成清 claim（防 stale 误判）
        v["arch_review_claimed_pid"] = 0
        if conclusion == "PASS":
            v["status"] = "testplan"  # TE 测试方案阶段
            v["test_plan_claimed"] = False
        else:
            v["status"] = "planning"  # FAIL → 回 planning（调度分支会自动重新 claim + spawn SE 重做；arch 无调度分支会卡死）
            v["arch_claimed"] = False
        v["arch_review_claimed"] = False
        v["arch_review_claimed_pid"] = 0
        write_versions(project, vd)
        log(f"ARCH_REVIEW {project}/{version} {conclusion} by=PM")
    return 0


def release_testplan_v2(project: str, version: str, product: str, conclusion: str) -> int:
    """整体测试方案状态命令（v2）：
    TE 产出完成：release_testplan_v2 {project} {version} {产物} DONE → testplan_reviewing（等 SE 评审）
    SE 评审：    release_testplan_v2 {project} {version} {评审意见} PASS|FAIL → PASS: in_dev（模块迭代）/ FAIL: testplan 重做"""
    conclusion = conclusion.strip().upper()
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        if conclusion == "DONE":
            if v.get("status") != "testplan":
                print(f"版本状态非 testplan（当前 {v.get('status')}）", file=sys.stderr)
                return 1
            full = product_path(product)
            if not os.path.exists(full):
                print(f"测试方案产物不存在: {full}", file=sys.stderr)
                return 1
            v["test_plan"] = norm_product(product)
            v["status"] = "testplan_reviewing"
            v["test_plan_claimed"] = False
            write_versions(project, vd)
            log(f"TESTPLAN_DONE {project}/{version} product={v['test_plan']}")
            return 0
        if conclusion not in ("PASS", "FAIL"):
            print("conclusion 必须为 DONE/PASS/FAIL", file=sys.stderr)
            return 1
        if v.get("status") != "testplan_reviewing":
            print(f"评审仅对 testplan_reviewing 有效（当前 {v.get('status')}）", file=sys.stderr)
            return 1
        v["test_plan_reviews"] = v.get("test_plan_reviews", []) + [norm_product(product)]
        v["testplan_review_claimed"] = False  # 评审完成清 claim
        v["testplan_review_claimed_pid"] = 0
        if conclusion == "PASS":
            v["status"] = "in_dev"  # 模块迭代开发
        else:
            v["status"] = "testplan"
            v["test_plan_claimed"] = False
        v["testplan_review_claimed"] = False
        v["testplan_review_claimed_pid"] = 0
        write_versions(project, vd)
        log(f"TESTPLAN_REVIEW {project}/{version} {conclusion} by=SE")
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


# ---- 变更三分场景 / 项目映射 / 版本视图 / 人工归属 ----

def cmd_change_request(rid: str, action: str, desc: str) -> int:
    """变更三分场景（P1-02）：change_request {req_id} modify|remove <描述>
    - modify：需求回 analyzing（重细化规格）→ 用户评审 → 重新分发/重跑（原草稿与旧规格留档）
    - remove：忽略该需求（removed 状态；从版本/模块 reqs 移除；依赖它的需求自动解锁）
    版本冻结：released 版本下的需求变更被拒绝（需开新版本承载）。"""
    action = action.strip().lower()
    if action not in ("modify", "remove"):
        print("change_request 动作必须为 modify/remove", file=sys.stderr)
        return 1
    if action == "modify" and not desc.strip():
        print("modify 需要变更描述: change_request {req_id} modify <描述>", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        st = read_status()
        e = st.get(rid)
        if not e:
            print(f"{rid} 不存在", file=sys.stderr)
            return 1
        project, rid_short = split_key(rid)
        vd = read_versions(project)
        ver = e.get("version")
        v = next((x for x in vd["versions"] if x["name"] == ver), None)
        if v and v.get("status") == "released":
            print(f"版本 {ver} 已 released（冻结），变更需开新版本承载（assign {rid} version=新版本 后处理）", file=sys.stderr)
            return 1
        if action == "modify":
            if e.get("status") not in ("approved", "dispatched", "released"):
                print(f"modify 仅对 approved/dispatched/released 需求有效（当前 {e.get('status')}）", file=sys.stderr)
                return 1
            e["status"] = "analyzing"  # 重细化（规格重做）
            e["change_log"] = e.get("change_log", []) + [{"t": now_iso(), "action": "modify", "desc": desc.strip()}]
            e["updated_at"] = now_iso()
            write_status(st)
            log(f"CHANGE_MODIFY {rid} -> analyzing（{desc.strip()[:60]}）")
        else:  # remove
            if e.get("status") == "removed":
                print(f"{rid} 已是 removed", file=sys.stderr)
                return 1
            e["status"] = "removed"
            e["change_log"] = e.get("change_log", []) + [{"t": now_iso(), "action": "remove", "desc": desc.strip() or "删除需求"}]
            e["updated_at"] = now_iso()
            # 从版本/模块 reqs 移除
            if v and rid_short in v.get("reqs", []):
                v["reqs"] = [r for r in v["reqs"] if r != rid_short]
            # 延迟导入避免循环依赖（versions ↔ modules）
            from .modules import read_modules, write_modules
            md = read_modules(project)
            changed = False
            for m in md.get("modules", []):
                if rid_short in m.get("reqs", []):
                    m["reqs"] = [r for r in m["reqs"] if r != rid_short]
                    changed = True
            if changed:
                write_modules(project, md)
            write_versions(project, vd)
            write_status(st)
            log(f"CHANGE_REMOVE {rid} -> removed（从版本/模块移除，依赖自动解锁）")
    return 0


def _valid_work_path(path: str) -> bool:
    """工作路径校验：绝对路径 + 禁止 zteam 内部（防污染 git 仓）。"""
    if not os.path.isabs(path):
        print("工作路径必须是绝对路径", file=sys.stderr)
        return False
    real_wd = os.path.realpath(path)
    if real_wd == os.path.realpath(WORKDIR) or real_wd.startswith(os.path.realpath(WORKDIR) + os.sep):
        print(f"工作路径不能在 zteam 内部（{WORKDIR}）——会污染 git 仓", file=sys.stderr)
        return False
    return True


def cmd_project(project: str, rest: list) -> int:
    """项目映射表命令（唯一真理源，用户明确修改才可写）：
    project list / info {name} / add {name} {path?} / setpath {name} {path} / default {name} / rm {name}"""
    if project == "list":
        pj = read_projects()
        ps = pj.get("projects", [])
        if not ps:
            print("（尚无项目——用 `project add {name} {path?}` 登记，或让 zbot 帮你创建）")
            return 0
        for p in sorted(ps, key=lambda x: x["name"]):
            mark = " [默认]" if p.get("default") else ""
            print(f"{p['name']} | 最新 {p.get('latest_version') or '—'} | {p.get('work_path')}{mark}")
        return 0
    if not rest:
        print("project list / info <name> / add <name> <path?> / setpath <name> <path> / default <name> / rm <name>", file=sys.stderr)
        return 1
    name = rest[0]
    if project == "info":
        wp = project_work_path(name)
        if not wp:
            print(f"项目 {name} 未登记", file=sys.stderr)
            return 1
        pj = read_projects()
        p = next(x for x in pj["projects"] if x["name"] == name)
        print(f"项目 {name}")
        print(f"  成立时间: {p.get('created_at')}")
        print(f"  最新版本: {p.get('latest_version') or '—'}")
        print(f"  工作路径: {p.get('work_path')}")
        print(f"  默认标记: {'是' if p.get('default') else '否'}")
        return 0
    if not re.match(r"^[A-Za-z0-9_-]+$", name):
        print("项目名仅允许 [A-Za-z0-9_-]", file=sys.stderr)
        return 1
    if project in ("add", "setpath", "default", "rm"):
        with acquire_lock() as _:  # 映射表为全局资产，用全局锁
            pj = read_projects()
            ps = pj.setdefault("projects", [])
            if project == "add":
                if any(p["name"] == name for p in ps):
                    print(f"项目 {name} 已登记", file=sys.stderr)
                    return 1
                path = rest[1] if len(rest) > 1 else os.path.join(os.path.expanduser("~"), "project", name)
                if not _valid_work_path(path):
                    return 1
                ps.append({"name": name, "created_at": now_iso(), "latest_version": None,
                           "work_path": path, "default": False})
                write_projects(pj)
                log(f"PROJECT_ADD {name} path={path}")
                print(f"已登记项目 {name} → {path}")
                return 0
            p = next((x for x in ps if x["name"] == name), None)
            if not p:
                print(f"项目 {name} 未登记", file=sys.stderr)
                return 1
            if project == "setpath":
                if len(rest) < 2:
                    print("project setpath <name> <path>", file=sys.stderr)
                    return 1
                if not _valid_work_path(rest[1]):
                    return 1
                old = p["work_path"]
                p["work_path"] = rest[1]
                write_projects(pj)
                log(f"PROJECT_SETPATH {name} {old} -> {rest[1]}")
                print(f"已迁移项目 {name}：{old} → {rest[1]}")
                return 0
            if project == "default":
                for q in ps:
                    q["default"] = (q["name"] == name)
                write_projects(pj)
                log(f"PROJECT_DEFAULT {name}")
                print(f"默认项目已设为 {name}")
                return 0
            if project == "rm":
                ps.remove(p)
                write_projects(pj)
                log(f"PROJECT_RM {name}（仅解除登记，数据未删）")
                print(f"已解除登记 {name}（工作路径数据未删除）")
                return 0
    print(f"未知 project 动作 {project}", file=sys.stderr)
    return 1


def cmd_versions(project: str = None) -> int:
    """版本聚合视图：statectl versions [project]（无参 = 全部项目）。"""
    projects = [project] if project else [p["name"] for p in read_projects().get("projects", [])]
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
