"""模块管理 + 调度 + 模块迭代链（v2 模块中心：SE 抉择组织形态）。

- modules.json CRUD：ensure_modules / read_modules / write_modules
- 人工：cmd_module（list / add / rm / dep / dispatch / iter / unblock）
- 调度：_se_triage_and_attach（SE 分单）/ _schedule_module_iter（迭代链）
- 状态命令：release_module（design/code/review/case/it 5 种 action）
- 巡检：_module_stale_recovery / _version_stale_recovery
       _issue_stale_watch / _dep_cycle / _module_checks
- 发布门禁：_mechanism_selftest（P0-8：机制回归自检）
- 工具：_get_mod_iter / _module_unblock / _module_inputs / _module_passed
- ST 登记：release_st_v2
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from . import paths as _paths
from .paths import (
    MODULES_FILE,
    WORKDIR,
    now_iso,
    project_dir,
    project_log_dir,
    worker_log_name,
)
from .pipeline import norm_product, product_path, spawn_worker
from .status import (
    acquire_lock,
    log,
    pid_alive,
    read_status,
    write_status,
)
from .versions import VERSION_FLOW, read_versions, write_versions
from .issues import (
    _issue_brief_for_fix,
    _issue_owner,
    _issue_path,
    _issue_path_owner,
    _issue_path_reporter,
    _issue_status,
    issues_dir,
    open_issues,
)

__all__ = [
    "MODULE_TYPES",
    "modules_path", "ensure_modules", "read_modules", "write_modules",
    "cmd_module",
    "_get_mod_iter", "_module_unblock",
    "release_module",
    "_module_passed",
    "_module_stale_recovery", "_version_stale_recovery",
    "_module_inputs", "_issue_stale_watch", "_dep_cycle",
    "_se_triage_and_attach", "_schedule_module_iter",
    "release_st_v2",
    "_module_checks", "_mechanism_selftest",
]


MODULE_TYPES = ("基础平台", "中间件", "上层应用")  # 默认分类（引导用）；项目组可自定义（SE 与用户对齐）


def modules_path(project: str) -> str:
    return os.path.join(project_dir(project), MODULES_FILE)


def ensure_modules(project: str) -> dict:
    p = modules_path(project)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    md = {"modules": []}
    write_modules(project, md)
    return md


def read_modules(project: str) -> dict:
    return ensure_modules(project)


def write_modules(project: str, md: dict) -> None:
    p = modules_path(project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(md, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def cmd_module(project: str, action: str, rest: list) -> int:
    """模块管理（SE 使用）：module {project} add <name> <类型> [desc] / rm <name> /
    dep <name> <dep1,dep2> / dispatch <name> <req_id1,req_id2> / list"""
    action = action.lower()
    with acquire_lock() as _:
        md = read_modules(project)
        mods = md.setdefault("modules", [])
        if action == "list":
            for m in mods:
                print(f"  {m['name']} [{m.get('type','?')}] alive={m.get('alive', True)} "
                      f"deps={m.get('depends_on', [])} reqs={len(m.get('reqs', []))}")
            return 0
        if action == "add":
            if len(rest) < 2:
                print("module add <name> <类型(默认:基础平台/中间件/上层应用，项目组可自定义)> [desc]", file=sys.stderr)
                return 1
            name, mtype = rest[0], rest[1]
            # 类型不强制三类（项目组可自定义分类，如"数据服务"）；仅要求非空
            if not mtype.strip():
                print("类型不能为空", file=sys.stderr)
                return 1
            if any(m["name"] == name for m in mods):
                print(f"模块 {name} 已存在", file=sys.stderr)
                return 1
            mods.append({"name": name, "type": mtype, "desc": " ".join(rest[2:]) or "",
                         "depends_on": [], "reqs": [], "design": {"product": None, "reviews": []},
                         "iterations": [], "alive": True})
            write_modules(project, md)
            log(f"MODULE_ADD {project}/{name} type={mtype}")
            return 0
        if action == "rm":
            if not rest:
                print("module rm <name>", file=sys.stderr)
                return 1
            m = next((x for x in mods if x["name"] == rest[0]), None)
            if not m:
                print(f"模块 {rest[0]} 不存在", file=sys.stderr)
                return 1
            m["alive"] = False  # 下线（保留历史，需求需重新分发）
            write_modules(project, md)
            log(f"MODULE_RM {project}/{rest[0]} (下线)")
            return 0
        if action == "dep":
            if len(rest) < 2:
                print("module dep <name> <dep1,dep2>", file=sys.stderr)
                return 1
            m = next((x for x in mods if x["name"] == rest[0]), None)
            if not m:
                print(f"模块 {rest[0]} 不存在", file=sys.stderr)
                return 1
            m["depends_on"] = [x.strip() for x in rest[1].split(",") if x.strip()]
            write_modules(project, md)
            log(f"MODULE_DEP {project}/{rest[0]} -> {m['depends_on']}")
            return 0
        if action == "dispatch":
            if len(rest) < 2:
                print("module dispatch <name> <req_id1,req_id2>", file=sys.stderr)
                return 1
            m = next((x for x in mods if x["name"] == rest[0]), None)
            if not m:
                print(f"模块 {rest[0]} 不存在", file=sys.stderr)
                return 1
            st = read_status()
            for rid in [x.strip() for x in rest[1].split(",") if x.strip()]:
                key = f"{project}/{rid}"
                if key not in st:
                    print(f"需求 {key} 不存在", file=sys.stderr)
                    continue
                if st[key].get("status") != "approved":
                    print(f"需求 {key} 非 approved（{st[key].get('status')}），跳过", file=sys.stderr)
                    continue
                if rid not in m.setdefault("reqs", []):
                    m["reqs"].append(rid)
                st[key]["status"] = "dispatched"
                st[key]["module"] = rest[0]
                st[key]["updated_at"] = now_iso()
            write_modules(project, md)
            write_status(st)
            log(f"MODULE_DISPATCH {project}/{rest[0]} <- {rest[1]}")
            return 0
        if action == "iter":
            if len(rest) < 2:
                print("module iter <name> <迭代号列表:1,2,3>", file=sys.stderr)
                return 1
            m = next((x for x in mods if x["name"] == rest[0]), None)
            if not m:
                print(f"模块 {rest[0]} 不存在", file=sys.stderr)
                return 1
            nums = []
            for x in rest[1].split(","):
                try:
                    nums.append(int(x.strip()))
                except ValueError:
                    pass
            nums = sorted(set(nums))
            if not nums:
                print("迭代号无效", file=sys.stderr)
                return 1
            existing = {it["n"] for it in m.get("iterations", [])}
            for n in nums:
                if n not in existing:
                    m.setdefault("iterations", []).append(
                        {"n": n, "status": "design_pending", "dev_product": None,
                         "ut_product": None, "it_product": None, "it_report": None, "it_reviews": []})
            m["iterations"].sort(key=lambda x: x["n"])
            write_modules(project, md)
            log(f"MODULE_ITER {project}/{rest[0]} -> {nums}")
            return 0
        if action == "unblock":
            if len(rest) < 2:
                print("module unblock <name> <迭代号>", file=sys.stderr)
                return 1
            return _module_unblock(project, rest[0], rest[1])
        print(f"未知 module 动作: {action}（add/rm/dep/dispatch/list）", file=sys.stderr)
        return 1


def _get_mod_iter(project: str, module: str, iter_n: str):
    """取模块迭代对象（含模块）。"""
    md = read_modules(project)
    m = next((x for x in md.get("modules", []) if x["name"] == module), None)
    if not m:
        print(f"模块 {module} 不存在", file=sys.stderr)
        return None, None
    it = next((x for x in m.get("iterations", []) if str(x.get("n")) == str(iter_n)), None)
    if not it:
        print(f"迭代 {iter_n} 不存在（模块 {module}）", file=sys.stderr)
        return None, None
    return m, it


def _module_unblock(project: str, module: str, iter_n: str) -> int:
    """模块 unblock（工具缺口 #10）：blocked 迭代 → 回 design_pending（重跑），清 failures/retry/claim。
    无锁纯逻辑——调用方（cmd_module/tick）负责持锁（防嵌套 flock 死锁）。"""
    m, it = _get_mod_iter(project, module, iter_n)
    if not m:
        return 1
    if it.get("status") != "blocked":
        print(f"模块 {module} 迭代 {iter_n} 非 blocked（当前 {it.get('status')}），无需 unblock", file=sys.stderr)
        return 1
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
    md = read_modules(project)
    mm = next(x for x in md["modules"] if x["name"] == module)
    ii = next(x for x in mm["iterations"] if str(x.get("n")) == str(iter_n))
    mm["design"] = m["design"]
    for k, val in it.items():
        ii[k] = val
    # 清掉 ii 中残留但 it 已 pop 的键（re-read 后的副本可能比 it 多）
    for k in ("claimed", "claimed_pid", "fix_claimed", "fix_claimed_pid", "retest_claimed",
              "retest_claimed_pid", "design_review_claimed", "design_review_claimed_pid",
              "review_claimed", "review_claimed_pid", "review_feedback", "design_review_feedback",
              "waiting_issues", "blocked_reason"):
        ii.pop(k, None)
    write_modules(project, md)
    log(f"MODULE_UNBLOCK {project}/{module} iter-{iter_n} -> design_pending（人工/资源恢复）")
    return 0


def release_module(project: str, module: str, iter_n: str, action: str, product: str, conclusion: str = "") -> int:
    """模块迭代状态命令（v2 M4）：release_module {project} {module} {iter} {action} {产物} [结论]
    action/结论 语义：
      design DONE(MDE 产出→design_reviewing) ｜ design PASS|FAIL(SE 评审→dev_working/design_working)
      code   DONE(FO 产出→dev_reviewing 检视门禁)
      review PASS|FAIL(MDE/SE 检视→it_working / dev_working+唤醒 FO)
      case   PASS|FAIL(TE 评 MTO 用例，不迁移)
      it     DONE(MTO 报告，open_issues 空→it_passed，有 open 等闭环)"""
    conclusion = conclusion.strip().upper()
    with acquire_lock() as _:
        m, it = _get_mod_iter(project, module, iter_n)
        if not m:
            return 1
        full = product_path(product) if product else None
        if product and not os.path.exists(full):
            print(f"产物不存在: {full}", file=sys.stderr)
            return 1
        status = it.get("status")
        if action == "design":
            if conclusion == "DONE":
                if status != "design_working":
                    print(f"design DONE 需 design_working（当前 {status}）", file=sys.stderr)
                    return 1
                m["design"]["product"] = norm_product(product)
                m["design"]["reviews"] = m["design"].get("reviews", [])
                it["status"] = "design_reviewing"
                it["claimed"] = False
            elif conclusion in ("PASS", "FAIL"):
                if status != "design_reviewing":
                    print(f"design 评审需 design_reviewing（当前 {status}）", file=sys.stderr)
                    return 1
                m["design"]["reviews"].append(norm_product(product))
                it["design_review_claimed"] = False  # 评审完成清 claim
                it["design_review_claimed_pid"] = 0
                if conclusion == "PASS":
                    it["status"] = "dev_working"
                    it["failures"] = int(it.get("failures", 0)) + int(it.get("design_retry_count", 0))
                    it["design_retry_count"] = 0
                else:
                    it["status"] = "design_working"  # 打回修订
                    it["design_retry_count"] = int(it.get("design_retry_count", 0)) + 1
                    it["design_review_feedback"] = norm_product(product)
                    if int(it.get("design_retry_count", 0)) >= 3:
                        it["status"] = "blocked"
                        with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[BLOCKED] 模块 {project}/{module} 迭代 {iter_n} 设计第 {it['design_retry_count']} 次评审仍 FAIL，已停止，请人工介入。\n")
                it["claimed"] = False
                it["design_review_claimed"] = False
                it["design_review_claimed_pid"] = 0
            else:
                print("design 结论必须为 DONE/PASS/FAIL", file=sys.stderr)
                return 1
        elif action == "code":
            if conclusion != "DONE" or status != "dev_working":
                print(f"code DONE 需 dev_working（当前 {status}）", file=sys.stderr)
                return 1
            it["dev_product"] = norm_product(product)
            it["status"] = "dev_reviewing"
            it["claimed"] = False
        elif action == "review":
            if conclusion not in ("PASS", "FAIL") or status != "dev_reviewing":
                print(f"review 需 dev_reviewing + PASS/FAIL（当前 {status}）", file=sys.stderr)
                return 1
            it.setdefault("reviews", []).append(norm_product(product))
            it["review_claimed"] = False  # 检视完成清 claim
            it["review_claimed_pid"] = 0
            if conclusion == "PASS":
                it["status"] = "it_working"
                it["claimed"] = False
                it["failures"] = int(it.get("failures", 0)) + int(it.get("retry_count", 0))
                it["retry_count"] = 0
            else:
                it["status"] = "dev_working"  # 打回修复
                it["claimed"] = False
                it["retry_count"] = int(it.get("retry_count", 0)) + 1
                it["review_feedback"] = norm_product(product)
                if int(it.get("retry_count", 0)) >= 3:
                    it["status"] = "blocked"
                    with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[BLOCKED] 模块 {project}/{module} 迭代 {iter_n} 检视第 {it['retry_count']} 次仍 FAIL，已停止，请人工介入。\n")
            it["review_claimed"] = False
            it["review_claimed_pid"] = 0
        elif action == "case":
            if conclusion not in ("PASS", "FAIL"):
                print("case 结论必须为 PASS/FAIL", file=sys.stderr)
                return 1
            if conclusion == "PASS":
                # 判据可达性门禁（P1-9，2026-09-11，同 release_st_case）
                try:
                    _casedoc = open(product_path(product), encoding="utf-8", errors="replace").read()
                except OSError as e:
                    print(f"用例读取失败：{e}", file=sys.stderr)
                    return 1
                if "实现依据" not in _casedoc:
                    print("❌ 判据可达性门禁未通过：用例文档缺少「实现依据」字段（判据须引用实现依据）",
                          file=sys.stderr)
                    log(f"MODULE_CASE_GATE_FAIL {project}/{module}/it{iter_n}（缺实现依据）")
                    return 1
            it.setdefault("case_reviews", []).append(norm_product(product))
            if conclusion == "PASS":
                it["case_passed"] = True
                it["case_retry_count"] = 0
            else:
                it["case_passed"] = False
                it["case_retry_count"] = int(it.get("case_retry_count", 0)) + 1
                if int(it.get("case_retry_count", 0)) >= 3:
                    it["status"] = "blocked"
                    with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[BLOCKED] 模块 {project}/{module} 迭代 {iter_n} 测试用例 TE 评审第 {it['case_retry_count']} 次仍 FAIL，已停止，请人工介入。\n")
        elif action == "it":
            if conclusion != "DONE" or status != "it_working":
                print(f"it DONE 需 it_working（当前 {status}）", file=sys.stderr)
                return 1
            # 静态锚定门禁（P1-3）：必须存在的调用点/常量上限（配置 {work_path}/module_checks.json）
            _mc = _module_checks(project, module)
            if _mc:
                print("❌ 静态锚定检查未通过，禁止 IT 登记：\n  - " + "\n  - ".join(_mc), file=sys.stderr)
                log(f"MODULE_CHECK_FAIL {project}/{module}: {_mc[:2]}")
                return 1
            it["it_report"] = norm_product(product)
            it["it_product"] = norm_product(product)
            it["claimed"] = False
            # 门禁：open 问题单须清空
            # 2026-09-11 SE 分单机制：只挂【归属本模块】的 open 单——根治"项目级全量挂载"错挂
            # （UARTIO-01/SOCSIM-05/06、DEBUGCORE-01/03、WEBAPI-02/03 五连犯）
            # 未裁决归属（待定/历史无字段）的单不挂：由 SE 分单环节裁决后经"补挂/再激活"进入本模块
            has_other_opens = bool(open_issues(project))
            opens = [iid for iid in open_issues(project) if _issue_path_owner(project, iid) == module]
            if opens:
                it["status"] = "it_working"  # 等问题单闭环
                it["waiting_issues"] = opens
                print(f"模块 IT 完成但存在未闭环问题单 {opens}，等待修复后自动收口", file=sys.stderr)
            else:
                it["status"] = "it_passed"
                if has_other_opens:
                    print("（项目内其他模块 open 单不阻塞本模块收口，待 SE 分单至归属模块处理）", file=sys.stderr)
        else:
            print(f"未知 action: {action}（design/code/review/case/it）", file=sys.stderr)
            return 1
        # 写回（_get_mod_iter 读了独立 dict，需重新读+改+写）
        md = read_modules(project)
        mm = next(x for x in md["modules"] if x["name"] == module)
        ii = next(x for x in mm["iterations"] if str(x.get("n")) == str(iter_n))
        mm["design"] = m["design"]
        for k, val in it.items():
            ii[k] = val
        write_modules(project, md)
        log(f"MODULE_{action.upper()} {project}/{module} iter-{iter_n} {conclusion} -> {it.get('status')}")
    return 0


def _module_passed(md: dict, module: str) -> bool:
    """模块是否已通过（任一迭代 it_passed，供依赖判定）。"""
    m = next((x for x in md.get("modules", []) if x["name"] == module), None)
    if not m:
        return True  # 依赖模块不存在（已下线）→ 不阻塞
    return any(it.get("status") == "it_passed" for it in m.get("iterations", []))


def _module_stale_recovery(project: str, md: dict, alarms: list) -> None:
    """模块级 stale 兜底：迭代 claimed（含评审 claim）但 worker 进程死亡 → 清 claim 重调度。"""
    for m in md.get("modules", []):
        for it in m.get("iterations", []):
            # 主 claim（design/dev/it worker）
            if it.get("claimed") and not pid_alive(it.get("claimed_pid")):
                it["claimed"] = False
                it["failures"] = int(it.get("failures", 0)) + 1
                log(f"MODULE_STALE {project}/{m['name']} iter-{it['n']} worker 死亡，重置调度 (failures={it['failures']})")
                alarms.append(f"模块 {m['name']} 迭代 {it['n']} worker 死亡已重置")
                if int(it.get("failures", 0)) >= 3:
                    it["status"] = "blocked"
                    with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[BLOCKED] 模块 {project}/{m['name']} 迭代 {it['n']} 连续失败 3 次，已停止。\n")
            # 活但无输出超时（P2-6，2026-09-11）：进程存活但 worker 日志 >N 分钟无写入 → 判卡死，kill + 重置。
            # 阈值默认 60 分钟（长任务如 ST 长稳天然长时间无输出，须宽松；可用 WORKER_IDLE_MAX_MIN 覆盖）
            _idle_max = int(os.environ.get("WORKER_IDLE_MAX_MIN", "60")) * 60
            for _cf, _pf, _rid, _role in (
                    ("fix_claimed", "fix_claimed_pid", f"__fix-{m['name']}-it{it['n']}", "fo"),
                    ("retest_claimed", "retest_claimed_pid", f"__retest-{m['name']}-it{it['n']}", None)):
                if not it.get(_cf):
                    continue
                _pid = it.get(_pf)
                if not (_pid and pid_alive(_pid)):
                    continue
                _ldir = project_log_dir(project)
                _cands = []
                if os.path.isdir(_ldir):
                    if _role:
                        _one = os.path.join(_ldir, worker_log_name(project, _rid, 1, _role))
                        _cands = [_one] if os.path.exists(_one) else []
                    else:
                        _cands = [os.path.join(_ldir, f) for f in os.listdir(_ldir)
                                  if f.startswith(f"worker-{_rid}-r1-")]
                try:
                    _mt = max(os.path.getmtime(c) for c in _cands)
                except ValueError:
                    continue  # 无日志可判 → 跳过（不误杀）
                if (time.time() - _mt) > _idle_max:
                    try:
                        os.kill(int(_pid), 9)
                    except OSError:
                        pass
                    it[_cf] = False
                    it.pop(_pf, None)
                    it["failures"] = int(it.get("failures", 0)) + 1
                    log(f"MODULE_IDLE_KILL {project}/{m['name']} iter-{it['n']} {_cf} 存活但 {_idle_max // 60} 分钟无输出 → 终止重置")
                    alarms.append(f"模块 {m['name']} 迭代 {it['n']} worker 疑似卡死（{_idle_max // 60} 分钟无输出）已终止重置")
            # 评审 claim（design_reviewing SE 评审 / dev_reviewing MDE 检视）
            for rclaim, rpid in (("design_review_claimed", "design_review_claimed_pid"),
                                 ("review_claimed", "review_claimed_pid")):
                if it.get(rclaim) and not pid_alive(it.get(rpid)):
                    it[rclaim] = False
                    log(f"MODULE_REV_STALE {project}/{m['name']} iter-{it['n']} {rclaim} 评审 worker 死亡，重置")
                    alarms.append(f"模块 {m['name']} 迭代 {it['n']} 评审 worker 死亡已重置（{rclaim}）")


def _version_stale_recovery(project: str, vd: dict, alarms: list) -> None:
    """版本级 stale 兜底：版本 claim（SE/TE/STO/QA/评审 worker）进程死亡 → 清 claim 重调度。"""
    for v in vd.get("versions", []):
        if v.get("status") == "released":
            continue
        claims = (("arch_claimed", "arch_claimed_pid", "SE 架构"),
                  ("arch_review_claimed", "arch_review_claimed_pid", "PM 架构评审"),
                  ("test_plan_claimed", "test_plan_claimed_pid", "TE 测试方案"),
                  ("testplan_review_claimed", "testplan_review_claimed_pid", "SE 方案评审"),
                  ("st_claimed", "st_claimed_pid", "STO 系统测试"),
                  ("qa_claimed", "qa_claimed_pid", "QA 发布"))
        for cfield, pfield, label in claims:
            if v.get(cfield) and not pid_alive(v.get(pfield)):
                v[cfield] = False
                v["failures"] = int(v.get("failures", 0)) + 1
                log(f"VERSION_STALE {project}/{v['name']} {label} worker 死亡，重置 (failures={v.get('failures')})")
                alarms.append(f"版本 {v['name']} {label} worker 死亡已重置")
                if int(v.get("failures", 0)) >= 3:
                    v["blocked_from"] = v.get("status")   # 记录被打断阶段（unblock 回现场，而非架构起点——2026-09-11 ST 阶段误回退教训）
                    v["status"] = "blocked"
                    with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[BLOCKED] 版本 {project}/{v['name']} 连续失败 3 次，已停止。\n")


def _module_inputs(project: str, m: dict, st: dict) -> str:
    """模块需求规格清单（MDE 输入）。"""
    lines = []
    for r in m.get("reqs", []):
        e = st.get(f"{project}/{r}") or {}
        lines.append(f"- {r}：规格={e.get('analysis') or '?'}")
    return "\n".join(lines)


def _issue_stale_watch(project: str, alarms: list) -> None:
    """问题单长期 open 告警：open 超 24h（按文件 mtime）→ alarms.txt 留痕（每 24h 一次）。"""
    idir = os.path.join(project_dir(project), "issues")
    if not os.path.isdir(idir):
        return
    now = time.time()
    for fname in sorted(os.listdir(idir)):
        if not fname.endswith(".md"):
            continue
        fp = os.path.join(idir, fname)
        try:
            content = open(fp, encoding="utf-8").read()
        except Exception:
            continue
        if _issue_status(content) != "open":
            continue
        age = now - os.path.getmtime(fp)
        if age > 24 * 3600:
            with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                f.write(f"[ISSUE_STALE] {project}/{fname[:-3]} open 超过 24h（{int(age // 3600)}h），请确认修复进度。\n")
            log(f"ISSUE_STALE {project}/{fname[:-3]} age={int(age // 3600)}h")
            alarms.append(f"问题单 {fname[:-3]} open 超 24h 未闭环")


def _dep_cycle(md: dict, module: str) -> list:
    """检测模块依赖环：从 module 出发 DFS，返回环路径（空 = 无环）。
    注意：初始 stack 为空（不含起点）——否则所有模块都误报'自己→自己'成环。"""
    def dfs(cur, stack):
        if cur in stack:
            i = stack.index(cur)
            return stack[i:] + [cur]
        for d in (next((x for x in md.get("modules", []) if x["name"] == cur), {}) or {}).get("depends_on", []):
            r = dfs(d, stack + [cur])
            if r:
                return r
        return []
    return dfs(module, [])


def _se_triage_and_attach(project: str, vd: dict, md: dict, alarms: list) -> None:
    """SE 分单（问题单归属裁决）+ 归属单补挂 / 已收口迭代再激活（2026-09-11 用户拍板机制）。

    背景：问题单此前无归属字段 → release_module it 把项目级全部 open 单挂进迭代 waiting_issues
    → 错挂五连犯（UARTIO-01→elf-loader/state-capture、SOCSIM-05/06→web-api、DEBUGCORE-01/03→web-api）
    → FO 被派无关单，拒绝或"假修复"（只标状态不改码），反复 spawn 空转。

    机制：MTO/STO 提单（归属=待定）→ SE 读单裁决根因归属 → `issue assign <iid> <模块>`
    → 本函数把归属单补挂到该模块迭代；若该模块迭代已 it_passed 则**再激活**（it_working）
    走「FO 修复 → MTO 复测 → 闭环」再收口。
    """
    # 0) 结构不变式自愈（D17 的自动补正，幂等·每 tick）：存在"进行中迭代"（非 it_passed/blocked）时
    #    版本必须在 in_dev —— 否则 FO/检视/MTO 派单被 _schedule_module_iter 的 in_dev 门禁挡住，
    #    且"全 it_passed"前提破坏使 STO 不再重生、st 通道又不报滞留 → 静默完全停滞。
    #    （2026-09-11 STO 第 10 轮发现；补作为幂等自愈，覆盖"再激活时版本回退被漏"的历史情形）
    for _v in vd.get("versions", []):
        _s = _v.get("status")
        if _s in ("st", "st_pending", "st_done", "qa", "qa_reviewing"):
            _busy = [f"{_m['name']}/it{_it['n']}" for _m in md.get("modules", [])
                     for _it in _m.get("iterations", [])
                     if _it.get("status") not in ("it_passed", "blocked")]
            if _busy:
                _v["status"] = "in_dev"
                _v["failures"] = 0
                _v.pop("st_claimed", None)
                _v.pop("st_claimed_pid", None)
                log(f"VERSION_REOPEN {project}/{_v['name']} {_s}→in_dev（不变式自愈：存在进行中迭代 {_busy[:3]}）")
                alarms.append(f"版本 {_v['name']} 由 {_s} 回到开发链（不变式自愈：进行中迭代 {_busy[:3]}）")
                break

    opens = open_issues(project)
    if not opens:
        # 无 open 单：仅清理分单 claim 残留（worker 干完退出后 reset）
        for v in vd.get("versions", []):
            if v.get("triage_claimed") and not pid_alive(v.get("triage_claimed_pid")):
                v["triage_claimed"] = False
                v.pop("triage_claimed_pid", None)
        return

    # 1) 归属单补挂 / 迭代再激活（归属模块 = 该模块最后一个迭代）
    for m in md.get("modules", []):
        if not m.get("alive", True):
            continue
        owned = [iid for iid in opens if _issue_path_owner(project, iid) == m["name"]]
        if not owned:
            continue
        its = sorted(m.get("iterations", []), key=lambda x: x.get("n", 0))
        if not its:
            continue
        last = its[-1]
        wi = list(last.get("waiting_issues") or [])
        missing = [i for i in owned if i not in wi]
        if not missing:
            continue
        st_ = last.get("status")
        if st_ == "it_working":
            last["waiting_issues"] = wi + missing
            log(f"MODULE_ISSUE_ATTACH {project}/{m['name']} iter-{last['n']} 补挂归属单 {missing}")
            alarms.append(f"模块 {m['name']} 迭代 {last['n']} 补挂问题单 {missing}")
        elif st_ == "it_passed":
            last["status"] = "it_working"
            last["waiting_issues"] = wi + missing
            last["claimed"] = False
            last["failures"] = 0
            last["retry_count"] = 0
            log(f"MODULE_ITER_REACTIVATE {project}/{m['name']} iter-{last['n']} it_passed→it_working（归属单 {missing} 回归修复）")
            alarms.append(f"模块 {m['name']} 迭代 {last['n']} 再激活（归属单 {missing} 回归修复）")
            # A2（2026-09-11 STO 第 10 轮发现）：版本同步回开发链。
            # 原因：再激活后的 FO/检视/MTO 派单逻辑在 _schedule_module_iter 的 `status != "in_dev"` 门禁内；
            # 且"全迭代 it_passed"被破坏会使 STO 不再重生、而 st 的告警通道（auto_done）不报滞留
            # → 否则版本退化为「无 FO / 无 STO / 无告警」的静默完全停滞。修复闭环后全 it_passed 自动回 st。
            for _v in vd.get("versions", []):
                _old = _v.get("status")
                if _old in ("st", "st_pending", "st_done", "qa", "qa_reviewing"):
                    _v["status"] = "in_dev"
                    _v["failures"] = 0
                    _v.pop("st_claimed", None)
                    _v.pop("st_claimed_pid", None)
                    log(f"VERSION_REOPEN {project}/{_v['name']} {_old}→in_dev（归属单 {missing} 回归修复；闭环后自动回 st）")
                    alarms.append(f"版本 {_v['name']} 由 {_old} 回到开发链（ST 阶段缺陷回归修复 {missing}）")

    # 2) 待归属单 → spawn SE 分单 worker（每版本至多一个 in-flight）
    unassigned = [iid for iid in opens if not _issue_path_owner(project, iid)]
    if not unassigned:
        for v in vd.get("versions", []):
            if v.get("triage_claimed") and not pid_alive(v.get("triage_claimed_pid")):
                v["triage_claimed"] = False
                v.pop("triage_claimed_pid", None)
        return
    target = next((v for v in vd.get("versions", [])
                   if v.get("status") not in ("released", "blocked")), None)
    if target is None:
        return
    if target.get("triage_claimed") and not pid_alive(target.get("triage_claimed_pid")):
        target["triage_claimed"] = False
        log(f"TRIAGE_STALE {project}/{target['name']} 分单 worker 死亡，重置")
    if target.get("triage_claimed"):
        return
    target["triage_claimed"] = True
    target["triage_claimed_pid"] = 0
    idir = issues_dir(project)
    brief = []
    for iid in unassigned:
        p = os.path.join(idir, f"{iid}.md")
        try:
            head = " ".join(open(p, encoding="utf-8", errors="replace").read()[:900].split())
        except OSError:
            head = "(不可读)"
        brief.append(f"- {iid}: {head}")
    mods_brief = "\n".join(
        f"- {m['name']}（依赖 {m.get('depends_on') or ['无']}）：{(m.get('desc') or '')[:100]}"
        for m in md.get("modules", []))
    query = (
        f"你是本流水线的【SE（系统工程师）】。严格遵循 {WORKDIR}/roles/se.md 执行**问题单归属裁决（分单）**。\n"
        f"待裁决问题单（{len(unassigned)} 条）：\n" + "\n".join(brief) + "\n\n"
        f"模块清单（归属候选）：\n{mods_brief}\n\n"
        f"任务：逐单判断根因归属模块（依据问题单描述的根因指向/代码路径/证据，可查 "
        f"{project_dir(project)}/code/ 下各模块源码与 design/ 设计文档），"
        f"然后对每单执行：python3 {WORKDIR}/scripts/statectl.py issue {project} assign <iid> <模块> <裁决理由一句话>；\n"
        f"裁决原则：根因代码位置在哪模块就归哪模块（跨模块缺陷归**根因所在模块**，而非发现它的模块）；\n"
        f"**跨模块拆分（重要）**：若单内复测意见明确指出该缺陷含**多个分属不同模块的项**（单模块修复不足以闭环），"
        f"执行拆分：`issue {project} split <原单> <新单号> <模块> <该项描述>` 逐项拆出（新单号沿用原前缀+序号，如 WEBUI-08），"
        f"每项归其根因模块；拆完在原单记录拆分说明并 `issue {project} close <原单>`（若其项已全部转出）或保持 open 说明剩余项；\n"
        f"全部裁决完毕后结束（无需汇报）。\n"
        f"⚠️ 只做归属裁决（issue assign），不要修改问题单其它内容、不要执行 fix/close/其它状态命令。"
    )
    pid = spawn_worker("se", f"{project}/__triage", 1, query)
    target["triage_claimed_pid"] = pid
    log(f"SPAWN-TRIAGE {project}/{target['name']} pid={pid}（{len(unassigned)} 单待归属裁决）")
    alarms.append(f"问题单归属裁决启动（{len(unassigned)} 单，SE pid={pid}）")


def _schedule_module_iter(project: str, vd: dict, md: dict, st: dict, alarms: list) -> None:
    """模块迭代链调度（v2 M4）：版本 in_dev → 按迭代计划推进模块（依赖串行/无依赖并行，模块跨迭代）。
    design_pending→MDE；design_reviewing→等 SE；dev_working→FO；dev_reviewing→等检视；
    it_working→MTO（用例 TE 评审→测试代码→IT）；检视 FAIL 打回时直接唤醒 FO。"""
    _se_triage_and_attach(project, vd, md, alarms)  # SE 分单 + 归属单补挂/迭代再激活（无条件执行，ST 阶段亦需）
    for v in vd.get("versions", []):
        if v.get("status") != "in_dev":
            continue
        for m in md.get("modules", []):
            if not m.get("alive", True):
                continue
            if not _module_passed(md, m["name"]) and m.get("iterations"):
                # 自身 previous 迭代未完成时不调度（跨迭代串行）——在迭代循环内判
                pass
            # 依赖环检测（死锁防御）
            cyc = _dep_cycle(md, m["name"])
            if cyc:
                with open(_paths.ALARM_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[DEP_CYCLE] 项目 {project} 模块依赖成环: {' → '.join(cyc)}，请人工修正 module dep。\n")
                alarms.append(f"模块依赖成环: {' → '.join(cyc)}")
                continue
            for it in sorted(m.get("iterations", []), key=lambda x: x["n"]):
                status = it.get("status")
                # 同模块前序迭代串行
                prev = [x for x in m["iterations"] if x["n"] < it["n"]]
                if prev and any(x.get("status") != "it_passed" for x in prev):
                    continue
                if status == "blocked":
                    continue
                if it.get("claimed"):
                    continue
                # 模块依赖（迭代级）：依赖模块已通过
                if not all(_module_passed(md, d) for d in m.get("depends_on", [])):
                    continue
                if status == "design_pending":
                    it["claimed"] = True
                    it["claimed_pid"] = 0
                    it["status"] = "design_working"
                    out = f"{project}/design/{m['name']}/"
                    # 增量迭代上下文（条件注入，2026-09-08 UARTIO-01 34 轮错派教训）：
                    # - 非首次设计（既有 design 产物）→ 提示基于既有设计增量设计，勿全量重做
                    # - 项目 open 问题单 → 列出供 MDE 判断归属（issue 无模块字段，需自行判断相关性）
                    ctx = ""
                    prev_design = (m.get("design") or {}).get("product")
                    if prev_design:
                        ctx += (f"既有设计（前序迭代产物；若本次为缺陷修复/增量迭代，请基于它增量设计，"
                                f"勿全量重做）：{product_path(prev_design)}\n")
                    _opens = [i for i in open_issues(project) if _issue_path_owner(project, i) == m["name"]]
                    if _opens:
                        _idir = issues_dir(project)
                        ctx += "归属于本模块的 open 问题单（SE 已裁决归属，设计必须覆盖其根因）：\n"
                        for _iid in _opens:
                            try:
                                _head = open(os.path.join(_idir, f"{_iid}.md"), encoding="utf-8").read()[:400].replace("\n", " ")
                            except OSError:
                                _head = "(不可读)"
                            ctx += f"  - {_iid}: {_head}\n"
                    query = (
                        f"你是本流水线的【MDE（模块设计）】。严格遵循 {WORKDIR}/roles/mde.md 为模块 {m['name']} "
                        f"（版本 {v['name']} 迭代 {it['n']}）设计功能模块。\n"
                        f"架构设计：{product_path(v.get('architecture') or '')}\n模块需求规格：\n{_module_inputs(project, m, st)}\n"
                        f"{ctx}"
                        f"任务：1. 输出功能模块设计文档到 {product_path(out)}（数据结构/接口/实现细节/DFx/可测试性/UT 框架）；\n"
                        f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} design {out} DONE；\n"
                        f"3. 完成后无需汇报。"
                    )
                    pid = spawn_worker("mde", f"{project}/__mde-{m['name']}-it{it['n']}", 1, query)
                    it["claimed_pid"] = pid
                    log(f"SPAWN-MDE {project}/{m['name']} iter-{it['n']} pid={pid}")
                    alarms.append(f"模块 {m['name']} 迭代 {it['n']} 进入设计（MDE pid={pid}）")
                elif status == "design_working":
                    # 设计打回修订（SE 评审 FAIL → MDE 带意见修订；首次设计由 design_pending 进入）
                    fb = f"\n设计评审反馈（请先阅读并修订）：{it.get('design_review_feedback')}\n" if it.get("design_review_feedback") else ""
                    out = f"{project}/design/{m['name']}/"
                    query = (
                        f"你是本流水线的【MDE（模块设计）】。严格遵循 {WORKDIR}/roles/mde.md 修订模块 {m['name']} "
                        f"（版本 {v['name']} 迭代 {it['n']}）功能模块设计。\n"
                        f"架构设计：{product_path(v.get('architecture') or '')}\n既有设计：{m['design'].get('product')}\n{fb}"
                        f"任务：1. 按评审意见修订设计（或重写），更新到 {product_path(out)}；\n"
                        f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} design {out} DONE；\n"
                        f"3. 完成后无需汇报。"
                    )
                    it["claimed"] = True
                    it["claimed_pid"] = 0
                    pid = spawn_worker("mde", f"{project}/__mderev-{m['name']}-it{it['n']}", 1, query)
                    it["claimed_pid"] = pid
                    log(f"SPAWN-MDE-REV {project}/{m['name']} iter-{it['n']} pid={pid}")
                    alarms.append(f"模块 {m['name']} 迭代 {it['n']} 设计修订（MDE pid={pid}）")
                elif status == "design_reviewing":
                    # SE 评审模块设计（评审缺失修复）
                    if not it.get("design_review_claimed"):
                        it["design_review_claimed"] = True
                        out = f"{project}/review/design/{m['name']}/iter-{it['n']}/"
                        query = (
                            f"你是本流水线的【SE】。严格遵循 {WORKDIR}/roles/se.md 评审模块 {m['name']} "
                            f"（版本 {v['name']} 迭代 {it['n']}）功能模块设计。\n"
                            f"模块设计：{m['design'].get('product')}；架构设计：{product_path(v.get('architecture') or '')}\n"
                            f"任务：1. 评审设计是否遵循架构（接口/数据流/模块间契约）+ 可落地（FO 可据其 TDD）；\n"
                            f"2. 评审意见写到 {product_path(out)}（明确 PASS 或 FAIL + 具体问题）；\n"
                            f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} design {out} PASS|FAIL；\n"
                            f"4. 完成后无需汇报。"
                        )
                        pid = spawn_worker("se", f"{project}/__drev-{m['name']}-it{it['n']}", 1, query)
                        it["design_review_claimed_pid"] = pid
                        log(f"SPAWN-DREV {project}/{m['name']} iter-{it['n']} worker=se pid={pid}")
                        alarms.append(f"模块 {m['name']} 迭代 {it['n']} 设计待 SE 评审（pid={pid}）")
                elif status == "design_working":
                    # MDE 修订设计（SE 评审 FAIL 打回；首轮由 design_pending 分支置位并 spawn，此分支只处理打回轮）
                    rev = (m["design"].get("reviews") or [])
                    fb = f"\nSE 评审意见（请先阅读并逐条修订）：{rev[-1]}\n" if rev else ""
                    out = f"{project}/design/{m['name']}/"
                    query = (
                        f"你是本流水线的【MDE（模块设计）】。严格遵循 {WORKDIR}/roles/mde.md 为模块 {m['name']} "
                        f"（版本 {v['name']} 迭代 {it['n']}）修订功能模块设计（按 SE 评审意见）。\n"
                        f"架构设计：{product_path(v.get('architecture') or '')}\n模块需求规格：\n{_module_inputs(project, m, st)}\n"
                        f"{fb}"
                        f"任务：1. 阅读 SE 评审意见并逐条修订，输出更新后的功能模块设计文档到 {product_path(out)}；\n"
                        f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} design {out} DONE；\n"
                        f"3. 完成后无需汇报。"
                    )
                    it["claimed"] = True
                    it["claimed_pid"] = 0
                    pid = spawn_worker("mde", f"{project}/__mde-{m['name']}-it{it['n']}", 1, query)
                    it["claimed_pid"] = pid
                    log(f"SPAWN-MDE-REV {project}/{m['name']} iter-{it['n']} pid={pid}（SE 意见修订设计）")
                    alarms.append(f"模块 {m['name']} 迭代 {it['n']} MDE 按评审意见修订设计（pid={pid}）")
                elif status == "dev_working":
                    out = f"{project}/code/{m['name']}/iter-{it['n']}/"
                    fb = f"\n检视反馈（请先阅读并修复）：{it.get('review_feedback')}\n" if it.get("review_feedback") else ""
                    query = (
                        f"你是本流水线的【FO（开发者，TDD）】。严格遵循 {WORKDIR}/roles/fo.md 为模块 {m['name']} "
                        f"（版本 {v['name']} 迭代 {it['n']}）TDD 开发。\n"
                        f"模块设计：{m['design'].get('product')}\n{fb}"
                        f"任务：1. 先写测试再实现（TDD），输出代码与 UT 用例到 {product_path(out)}；\n"
                        f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} code {out} DONE；\n"
                        f"3. 完成后无需汇报。"
                    )
                    it["claimed"] = True
                    it["claimed_pid"] = 0
                    pid = spawn_worker("fo", f"{project}/__fo-{m['name']}-it{it['n']}", 1, query)
                    it["claimed_pid"] = pid
                    log(f"SPAWN-FO {project}/{m['name']} iter-{it['n']} pid={pid}")
                    alarms.append(f"模块 {m['name']} 迭代 {it['n']} 进入开发（FO pid={pid}）")
                elif status == "dev_reviewing":
                    # MDE 代码检视（检视门禁，评审缺失修复）
                    if not it.get("review_claimed"):
                        it["review_claimed"] = True
                        out = f"{project}/review/code/{m['name']}/iter-{it['n']}/"
                        query = (
                            f"你是本流水线的【MDE】。严格遵循 {WORKDIR}/roles/mde.md 对模块 {m['name']} "
                            f"（版本 {v['name']} 迭代 {it['n']}）执行代码检视（模块内实现视角）。\n"
                            f"模块设计：{m['design'].get('product')}；代码：{it.get('dev_product')}\n"
                            f"任务：1. 按检视清单核对（实现与设计一致/边界异常/可测试性/风格）；\n"
                            f"2. 检视意见写到 {product_path(out)}（明确 PASS 或 FAIL + 具体问题，FAIL 需指向代码位置）；\n"
                            f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} review {out} PASS|FAIL；\n"
                            f"4. 完成后无需汇报。"
                        )
                        pid = spawn_worker("mde", f"{project}/__crev-{m['name']}-it{it['n']}", 1, query)
                        it["review_claimed_pid"] = pid
                        log(f"SPAWN-CREV {project}/{m['name']} iter-{it['n']} worker=mde pid={pid}")
                        alarms.append(f"模块 {m['name']} 迭代 {it['n']} 代码待检视（MDE pid={pid}）")
                elif status == "it_working":
                    if not it.get("case_passed"):
                        # MTO 用例阶段（TE 评审通过才能写测试代码——脚本侧由 case 命令门禁）
                        out = f"{project}/it/{m['name']}/iter-{it['n']}/"
                        query = (
                            f"你是本流水线的【MTO（模块测试者，IT）】。严格遵循 {WORKDIR}/roles/mto.md 为模块 {m['name']} "
                            f"（版本 {v['name']} 迭代 {it['n']}）执行模块集成测试（IT）。\n"
                            f"整体测试方案：{product_path(v.get('test_plan') or '')}\n模块设计：{m['design'].get('product')}\n"
                            f"任务：1. 先写测试用例文档到 {product_path(out)}测试用例.md；\n"
                            f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} case {out}测试用例.md PASS（用例经 TE 评审通过；若 TE 未通过会打回，需按意见修改后重新提交）；\n"
                            f"3. 用例评审通过后写测试代码并执行模块 IT，输出模块测试报告到 {product_path(out)}；发现缺陷提问题单（issue open）；\n"
                            f"4. 运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} it {out} DONE 完成登记"
                            f"（该命令=**IT 执行完毕登记**：发现问题时也必须执行——系统据 open 问题单挂载 waiting 并启动修复链，非宣告通过；无 open 单则自动 it_passed。切勿因存在 open 问题单而跳过登记）；\n"
                            f"6. 完成后无需汇报。"
                        )
                        it["claimed"] = True
                        it["claimed_pid"] = 0
                        pid = spawn_worker("mto", f"{project}/__mto-{m['name']}-it{it['n']}", 1, query)
                        it["claimed_pid"] = pid
                        log(f"SPAWN-MTO {project}/{m['name']} iter-{it['n']} pid={pid}")
                        alarms.append(f"模块 {m['name']} 迭代 {it['n']} 进入 IT（MTO pid={pid}）")
                    elif not it.get("it_product"):
                        # case_passed 已 True（用例已过）但 IT 未登记（MTO 中途退出/漏登记 release it DONE）→ 续跑收尾登记
                        # 2026-09-10 web-ui it2 卡死教训：MTO 误把收尾登记当"越权"停手 → it_product 空 + waiting 未挂 → 调度无分支卡死
                        if not it.get("claimed"):
                            it["claimed"] = True
                            it["claimed_pid"] = 0
                            out = f"{project}/it/{m['name']}/iter-{it['n']}/"
                            query = (
                                f"你是本流水线的【MTO（模块测试者，IT）】。严格遵循 {WORKDIR}/roles/mto.md 为模块 {m['name']} "
                                f"（版本 {v['name']} 迭代 {it['n']}）**续跑收尾登记**（上一轮已完成用例评审与测试执行，但未登记）。\n"
                                f"产物目录：{product_path(out)}（测试用例.md/模块测试报告/执行日志/问题单应已存在，请先核对）；\n"
                                f"任务：运行 python3 {WORKDIR}/scripts/statectl.py release_module {project} {m['name']} {it['n']} it {out} DONE "
                                f"完成登记。\n"
                                f"说明：该命令=**IT 执行完毕登记**（发现问题时也必须执行——系统会据 open 问题单挂载 waiting 并启动修复链），"
                                f"**不是宣告通过**；无 open 单则自动 it_passed。不要因存在 open 问题单而跳过登记。"
                            )
                            pid = spawn_worker("mto", f"{project}/__mto-{m['name']}-it{it['n']}", 1, query)
                            it["claimed_pid"] = pid
                            log(f"SPAWN-MTO-RESUME {project}/{m['name']} iter-{it['n']} pid={pid}（IT 收尾登记续跑）")
                            alarms.append(f"模块 {m['name']} 迭代 {it['n']} IT 收尾登记续跑（MTO pid={pid}）")
                    elif it.get("it_product"):
                        # 问题单闭环（v2 §7.2）：open → FO 修复（issue fix）；全 fixed → MTO 复测（issue close）；全 closed → it_passed
                        # 条件用 it_product（release it DONE 才设）而非 waiting_issues：MTO 执行中 it_product 空仍走上方用例分支；
                        # IT 已产出后 waiting 被数据卫生清空（如 UARTIO-01 错派移除）也进入本分支 → opens/fixeds 空 → 自动收口 it_passed
                        # （原 elif waiting_issues 在 waiting=[] 时不执行，it_working+空 waiting 会卡死——2026-09-08 elf-loader it1）
                        isdir = issues_dir(project)
                        def _istate(iid: str) -> str:
                            p = os.path.join(isdir, f"{iid}.md")
                            if not os.path.exists(p):
                                return "closed"
                            return _issue_status(open(p, encoding="utf-8").read())
                        opens = [iid for iid in it["waiting_issues"] if _istate(iid) == "open"]
                        fixeds = [iid for iid in it["waiting_issues"] if _istate(iid) == "fixed"]
                        # stale 兜底：修复/复测 worker 死亡 → 清 claim 重试（防 claim 残留卡死）
                        if it.get("fix_claimed") and not pid_alive(it.get("fix_claimed_pid")):
                            it["fix_claimed"] = False
                            log(f"MODULE_FIX_STALE {project}/{m['name']} iter-{it['n']} 修复 worker 死亡，重置")
                            alarms.append(f"模块 {m['name']} 迭代 {it['n']} 修复 worker 死亡已重置")
                        if it.get("retest_claimed") and not pid_alive(it.get("retest_claimed_pid")):
                            it["retest_claimed"] = False
                            log(f"MODULE_RETEST_STALE {project}/{m['name']} iter-{it['n']} 复测 worker 死亡，重置")
                            alarms.append(f"模块 {m['name']} 迭代 {it['n']} 复测 worker 死亡已重置")
                        # 全部 closed → 自动收口 it_passed
                        if not opens and not fixeds:
                            it["status"] = "it_passed"
                            it["waiting_issues"] = []
                            it["fix_claimed"] = False
                            it["retest_claimed"] = False
                            log(f"MODULE_IT {project}/{m['name']} iter-{it['n']} 问题单全部闭环 -> it_passed")
                            alarms.append(f"模块 {m['name']} 迭代 {it['n']} 问题单闭环，IT 通过")
                        if opens and not it.get("fix_claimed"):
                            # FO 修复 open 问题单
                            it["fix_claimed"] = True
                            out = f"{project}/code/{m['name']}/iter-{it['n']}/"
                            iss_list = "\n".join(_issue_brief_for_fix(project, iid) for iid in opens)
                            fix_cmds = "\n".join(f"python3 {WORKDIR}/scripts/statectl.py issue {project} fix {iid}" for iid in opens)
                            query = (
                                f"你是本流水线的【FO（开发者）】。严格遵循 {WORKDIR}/roles/fo.md 为模块 {m['name']} "
                                f"（版本 {v['name']} 迭代 {it['n']}）修复问题单。\n"
                                f"模块设计：{m['design'].get('product')}；代码：{it.get('dev_product')}\n"
                                f"open 问题单（必须全部修复）：\n{iss_list}\n"
                                f"任务：1. 逐一修复问题单描述缺陷，修改代码到 {product_path(out)}；\n"
                                f"⚠️ 硬性要求：①问题单末尾的【复测方最新意见/修复建议】必须**逐条落实**（不得只按描述笼统修，修完哪些条、每条改了哪个文件哪一行，写进单内「修复记录」）；\n"
                                f"②修复必须在**真链运行路径**生效（UT 全绿 ≠ 闭环——UT 常只覆盖单路径而漏真链调用链）；③自证方式：核证复测方指出的调用点/常量/路径（如 L1366 调用点、WRITE_CHUNK_BYTES）确实已改；\n"
                                f"④上一轮已被复测打回的，先读单末尾「复测记录」里的重申建议——**未落实即视为未修复**。\n"
                                f"2. 每个修复完成执行：\n{fix_cmds}\n"
                                f"⚠️ 若某单根因**不在本模块**（或单不合理），**必须**执行 issue {project} reject <iid> <理由：根因模块+证据>（禁止沉默不标=空转、禁止硬改凑数=假修复）；修复须真正改码（issue fix 有证据校验；纯文档判定类用 --force <理由>）；\n"
                                f"3. **续跑提示**：单内若已有「修复记录/复测记录」（前轮处理痕迹），先读它避免重复劳动；"
                                f"本轮只处理仍为 open 的单（已 fixed 的已不在清单，调度天然续跑）；被截断时调度会重新派发，无需从头分析。\n"
                                f"4. 全部修复后无需汇报。"
                            )
                            pid = spawn_worker("fo", f"{project}/__fix-{m['name']}-it{it['n']}", 1, query)
                            it["fix_claimed_pid"] = pid
                            log(f"SPAWN-FIX {project}/{m['name']} iter-{it['n']} pid={pid}（问题单修复）")
                            alarms.append(f"模块 {m['name']} 迭代 {it['n']} FO 修复问题单（pid={pid}）")
                        elif fixeds and not it.get("retest_claimed"):
                            # 提单人（MTO）复测 fixed 问题单
                            it["retest_claimed"] = True
                            out = f"{project}/it/{m['name']}/iter-{it['n']}/"
                            iss_list = "\n".join(f"- {iid}: {open(os.path.join(isdir, f'{iid}.md'), encoding='utf-8').read()[:2000]}"
                                                 for iid in fixeds)
                            close_cmds = "\n".join(f"python3 {WORKDIR}/scripts/statectl.py issue {project} close {iid}" for iid in fixeds)
                            query = (
                                f"你是本流水线的【MTO（提单人，复测）】。严格遵循 {WORKDIR}/roles/mto.md 复测模块 {m['name']} "
                                f"（版本 {v['name']} 迭代 {it['n']}）已修复问题单。\n"
                                f"模块设计：{m['design'].get('product')}；代码：{it.get('dev_product')}\n"
                                f"fixed 问题单（逐一复测）：\n{iss_list}\n"
                                f"任务：1. 逐一复测修复是否解决（可跑测试代码），复测记录写入问题单文件；\n"
                                f"2. 复测通过执行：\n{close_cmds}\n"
                                f"3. 复测不通过将问题单改回 open（编辑文件 状态：fixed→状态：open）并说明原因；\n"
                                f"4. 全部处理后无需汇报。"
                            )
                            # E2（2026-09-11）：复测方=提单人——ST 阶段提单（STO）由 STO 验收；IT 阶段提单（MTO）原流程不变
                            _st_issues = [x for x in fixeds if _issue_path_reporter(project, x) == "STO"]
                            _rrole = "mto"
                            if _st_issues:
                                _rrole = "sto"
                                query = (
                                    f"你是本流水线的【STO（提单人，ST 阶段验收）】。严格遵循 {WORKDIR}/roles/sto.md 复测模块 {m['name']} "
                                    f"（版本 {v['name']} 迭代 {it['n']}）已修复的 **ST 阶段问题单**。\n"
                                    f"模块设计：{m['design'].get('product')}；代码：{it.get('dev_product')}\n"
                                    f"fixed 问题单（逐一复测）：\n{iss_list}\n"
                                    f"任务：1. 按各问题单内「复测判据」逐一起真服务/真链复测，复测记录写入问题单文件；\n"
                                    f"2. 复测通过执行：\n{close_cmds}\n"
                                    f"3. 复测不通过将问题单改回 open（编辑文件 状态：fixed→状态：open）并说明原因；\n"
                                    f"4. 全部处理后无需汇报。"
                                )
                            pid = spawn_worker(_rrole, f"{project}/__retest-{m['name']}-it{it['n']}", 1, query)
                            it["retest_claimed_pid"] = pid
                            log(f"SPAWN-RETEST {project}/{m['name']} iter-{it['n']} pid={pid}（问题单复测）")
                            alarms.append(f"模块 {m['name']} 迭代 {it['n']} MTO 复测问题单（pid={pid}）")
    write_modules(project, md)


def release_st_v2(project: str, version: str, product: str, conclusion: str) -> int:
    """版本 ST 状态命令（v2 M5）：STO 产出完成 → release_st_v2 {p} {v} {报告目录} DONE
    → 校验 open_issues 空 → st_done（有 open 等问题单闭环）。"""
    conclusion = conclusion.strip().upper()
    if conclusion != "DONE":
        print("release_st_v2 仅支持 DONE（STO 完成标记）", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        if v.get("status") != "st":
            print(f"版本状态非 st（当前 {v.get('status')}）", file=sys.stderr)
            return 1
        full = product_path(product)
        if not os.path.exists(full):
            print(f"ST 报告不存在: {full}", file=sys.stderr)
            return 1
        v["st_product"] = norm_product(product)
        v["st_claimed"] = False
        opens = open_issues(project)
        if opens:
            v["status"] = "st"  # 等问题单闭环
            v["waiting_issues"] = opens
            print(f"ST 完成但存在未闭环问题单 {opens}，等待闭环后自动收口", file=sys.stderr)
        else:
            v["status"] = "st_done"
        write_versions(project, vd)
        log(f"ST_DONE {project}/{version} product={v['st_product']}")
    return 0


def _module_checks(project: str, module: str) -> list:
    """模块静态锚定检查（P1-3，2026-09-11）：把复测方发现的"必须存在的调用点/常量上限"配置化为门禁。
    触机=release_module it DONE（命令入口）；触发者=命令入口；兜底=拒绝登记（迭代不收口）。
    配置：{work_path}/module_checks.json  形如
      {"soc-sim": [{"file":"engine_worker.py","pattern":"poll_mem_watches|_diff_watch_callbacks",
                    "min_count":2,"why":"SOCSIM-05"}, {...}]}
    依据：SOCSIM-06 UT 用假监视器全绿但真链 503（WRITE_CHUNK_BYTES 仍 4096）；SOCSIM-05 UT 只覆盖单路径。"""
    cfg_p = os.path.join(project_dir(project), "module_checks.json")
    if not os.path.exists(cfg_p):
        return []
    try:
        cfg = json.load(open(cfg_p, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"module_checks.json 解析失败：{e}"]
    rules = cfg.get(module) or []
    fails = []
    base = os.path.join(project_dir(project), "code", module)
    for r in rules:
        rel = r.get("file", "")
        target = None
        for root, _dirs, files in os.walk(base):
            if rel in files:
                target = os.path.join(root, rel)
        if target is None:
            fails.append(f"找不到文件 {rel}（规则：{r.get('why', '')}）")
            continue
        txt = open(target, encoding="utf-8", errors="replace").read()
        pat = r.get("pattern", "")
        n = len(re.findall(pat, txt))
        if r.get("min_count") is not None and n < int(r["min_count"]):
            fails.append(f"{rel} 匹配 {pat!r} 次数 {n} < {r['min_count']}（{r.get('why', '')}）")
        if r.get("max_value") is not None:
            m = re.search(pat, txt)
            if not m:
                fails.append(f"{rel} 未匹配 {pat!r}")
            else:
                try:
                    val = int(m.group(1))
                    if val > int(r["max_value"]):
                        fails.append(f"{rel} {pat} 当前值 {val} > 上限 {r['max_value']}（{r.get('why', '')}）")
                except (IndexError, ValueError):
                    fails.append(f"{rel} 规则 pattern 需含一个数字捕获组")
    return fails


def _mechanism_selftest(project: str) -> list:
    """机制回归自检（P0-8，2026-09-11）：发布前机检结构不变式，返回失败项（空=通过）。
    触机=release_qa DONE（命令入口）；触发者=命令入口；兜底=拒绝发布（QA_DONE 不落状态）。
    依据：v1.0.0 期间 3 次"机制半通"（再激活未回 in_dev→静默停滞、st 无续跑、FO 上下文截断），
    上线缺少强制回归环节。此自检把"触机三要素"里可机器判定的部分固化为发布门禁。"""
    fails = []
    try:
        vd = read_versions(project)
        md = read_modules(project)
    except Exception as e:  # noqa: BLE001
        return [f"状态文件读取失败：{e}"]
    # ① 版本状态必须在可达性表内
    for v in vd.get("versions", []):
        s = v.get("status")
        if s and s not in VERSION_FLOW:
            fails.append(f"版本 {v['name']} 状态 {s} 不在可达性表（VERSION_FLOW）")
    # ② 结构不变式：存在进行中迭代（非 it_passed/blocked）时版本必须 in_dev
    busy = [f"{m['name']}/it{it['n']}={it.get('status')}" for m in md.get("modules", [])
            for it in m.get("iterations", []) if it.get("status") not in ("it_passed", "blocked")]
    for v in vd.get("versions", []):
        if busy and v.get("status") in ("st", "st_pending", "st_done", "qa", "qa_reviewing"):
            fails.append(f"不变式违反：版本 {v['name']}={v.get('status')} 但存在进行中迭代 {busy[:3]}")
    # ③ 发布前提：ST 之后阶段的版本，全部模块迭代必须 it_passed
    for v in vd.get("versions", []):
        if v.get("status") not in ("st", "st_pending", "st_done", "qa", "qa_reviewing", "released"):
            continue
        notpass = [f"{m['name']}/it{it['n']}={it.get('status')}" for m in md.get("modules", [])
                   for it in m.get("iterations", []) if it.get("status") != "it_passed"]
        if notpass:
            fails.append(f"版本 {v['name']} 存在未通过迭代：{notpass[:3]}")
    # ⑤ 发布物冷启动验证（P0-8 补充，2026-09-11）：防"发布包未冷启动验证"复发
    #    依据：v1.0.0 首次发布包 requirements.txt 漏列 inprocess 依赖，用户照指南启动即 EngineBootError。
    for v in vd.get("versions", []):
        if v.get("status") not in ("qa", "qa_reviewing", "released"):
            continue
        rel_dir = os.path.join(project_dir(project), "release", v["name"])
        files = os.listdir(rel_dir) if os.path.isdir(rel_dir) else []
        has_pkg = any(f.endswith(".tar.gz") for f in files)
        has_sha = "SHA256SUMS" in files
        has_cold = False
        for fn in files:
            if fn.endswith(".md"):
                try:
                    _txt = open(os.path.join(rel_dir, fn), encoding="utf-8", errors="replace").read()
                    # 用户铁律：QA 回归必须基于全新（隔离）环境——记录须同时含两个锚点
                    if "全新环境" in _txt and "冷启动" in _txt:
                        has_cold = True
                        break
                except OSError:
                    pass
        # 一键脚本三件套（用户要求：发包必须含一键安装/卸载）
        _pkg = next((os.path.join(rel_dir, f) for f in files if f.endswith(".tar.gz")), None)
        if _pkg:
            try:
                import tarfile
                with tarfile.open(_pkg) as _tf:
                    _names = {os.path.basename(n) for n in _tf.getnames()}
                _need = {"install.sh", "uninstall.sh", "start.sh"}
                _miss = sorted(_need - _names)
                if _miss:
                    fails.append(f"版本 {v['name']} 发布包缺少一键脚本：{_miss}"
                                 f"（发包硬性要求：一键安装 install.sh / 一键卸载 uninstall.sh / 一键启动 start.sh）")
            except Exception as _e:  # noqa: BLE001
                fails.append(f"版本 {v['name']} 发布包读取失败：{_e}")
        if not (has_pkg and has_sha):
            fails.append(f"版本 {v['name']} 发布物不完整（需 .tar.gz + SHA256SUMS——请用 packaging/make_release.sh 打包）")
        elif not has_cold:
            fails.append(f"版本 {v['name']} 缺全新环境冷启动记录（release/{v['name']}/ 需含「全新环境」+「冷启动」证据——"
                         f"用 packaging/make_release.sh 的冷启动门禁生成）")
    # ④ 问题单状态合法：open/fixed 单必须已有归属（未裁决=绕过分单流程）
    for iid in open_issues(project):
        try:
            c = open(_issue_path(project, iid), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if not _issue_owner(c):
            fails.append(f"问题单 {iid} 归属未裁决（未走 SE 分单流程）")
    return fails