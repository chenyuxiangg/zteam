"""问题单 + 架构/测试方案阶段命令。

- 问题单（v2：提单人复测闭环）：MTO/STO 提单，FO 修复，提单人复测关闭。
  状态：open（FO 处理中）→ fixed（FO 修复完成）→ closed（提单人复测通过）
       pending（挂起，下版本处理）→ open（activate 唤回）
  动作：open / fix（带修复证据校验）/ close / reopen / list / assign（SE 分单）
       reject（FO 拒修）/ pend / activate / split（跨模块拆分）
- 架构/方案阶段命令：release_arch / release_testplan_v2（DONE/PASS/FAIL）
- 调度：_schedule_arch_te（planning→arch→arch_reviewing→testplan→testplan_reviewing→in_dev）

本模块自带 _read_modules_for_issue 简化版（仅查模块名是否存在），
不依赖 modules.py——保证 cmd_issue.assign / cmd_issue.split 在 modules.py
未拆时也能独立工作。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from . import paths as _paths
from .paths import (
    WORKDIR,
    MODULES_FILE,
    now_iso,
    project_dir,
)
from .pipeline import norm_product, product_path, spawn_worker
from .status import (
    acquire_lock,
    log,
    read_status,
    write_status,
)
from .versions import read_versions, write_versions

__all__ = [
    "issues_dir", "_issue_path", "_issue_status", "_issue_owner",
    "_issue_reporter", "_issue_path_reporter", "_issue_owner_locked",
    "_issue_brief_for_fix", "_issue_path_owner",
    "cmd_issue", "open_issues",
    "_arch_inputs", "_schedule_arch_te",
]


# ---- 模块名查询（cmd_issue.assign / split 用）----

def _read_modules_for_issue(project: str) -> list:
    """读 modules.json，返回 modules 列表（不存在/损坏 → []）。
    为避免循环依赖（issues.py 早于 modules.py 拆出），本模块自带最小实现；
    真正的完整 CRUD 见 modules.py（后续拆出时统一引用）。"""
    p = os.path.join(project_dir(project), MODULES_FILE)
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f).get("modules", [])
    except (json.JSONDecodeError, OSError):
        return []


# ---- 问题单目录/路径 ----

def issues_dir(project: str) -> str:
    d = os.path.join(project_dir(project), "issues")
    os.makedirs(d, exist_ok=True)
    return d


def _issue_path(project: str, iid: str) -> str:
    return os.path.join(issues_dir(project), f"{iid}.md")


def _issue_status(content: str) -> str:
    """问题单状态（读状态行首个'状态：'行，非全文匹配）。
    2026-09-08：UARTIO-01 261KB 正文历史含 69 处'状态：fixed/open'字样，全文匹配曾把
    line3=closed 的单误判 fixed → soc-sim it2 复测死循环 + fix/close 误伤正文记录。"""
    for ln in content.splitlines():
        if ln.startswith("状态："):
            v = ln.split("：", 1)[1].strip()
            return v if v in ("open", "fixed", "closed", "pending") else "closed"
    return "closed"


def _issue_owner(content: str) -> str:
    """问题单归属模块（读'归属模块：'行）。返回 '' 表示未裁决（待 SE 分单）或历史单无字段。
    2026-09-11 新增：根治'项目级 open 单全量挂 waiting_issues'导致的错挂（UARTIO-01/SOCSIM-05/06、
    DEBUGCORE-01/03、WEBAPI-02/03 五连犯）。"""
    for ln in content.splitlines():
        if ln.startswith("归属模块："):
            v = ln.split("：", 1)[1].strip()
            return "" if v in ("待定", "") else v
    return ""


def _issue_reporter(content: str) -> str:
    """问题单提单人角色（MTO/STO）。历史单无规范化值时返回 ''（复测方按缺省 MTO 处理）。"""
    for ln in content.splitlines():
        if ln.startswith("提单人："):
            v = ln.split("：", 1)[1].strip().upper()
            if "STO" in v:
                return "STO"
            if "MTO" in v:
                return "MTO"
            return ""
    return ""


def _issue_path_reporter(project: str, iid: str) -> str:
    p = _issue_path(project, iid)
    if not os.path.exists(p):
        return ""
    return _issue_reporter(open(p, encoding="utf-8").read())


def _issue_owner_locked(content: str) -> bool:
    """归属是否已被 SE 复核锁定（FO 不可再拒修——防推诿循环）。"""
    return any(l.startswith("归属复核：") and "locked" in l for l in content.splitlines()[:20])


def _issue_brief_for_fix(project: str, iid: str) -> str:
    """FO 修复上下文：描述（头部）+ **复测方最新意见/修复建议**（尾部关键段）+ 归属。
    2026-09-11 教训：原实现只取单前 2000 字符 → 描述在前、复测方三次重申的精确修复建议在后
    （SOCSIM-05 单 64KB）→ FO 看不到建议 → 标 fixed 但未改正确路径 → 复测反复打回。"""
    p = _issue_path(project, iid)
    try:
        c = open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return f"- {iid}: (不可读)"
    head = c[:1500]
    tail = c[-2500:] if len(c) > 4000 else ""
    owner = _issue_owner(c) or "待定"
    rep = _issue_reporter(c) or "?"
    s = f"- {iid}（归属 {owner}，提单人 {rep}）：\n{head}"
    if tail:
        s += f"\n  ...【单末尾·含复测方最新意见/修复建议（**必须逐条落实**）】...\n{tail}"
    return s


def _issue_path_owner(project: str, iid: str) -> str:
    p = _issue_path(project, iid)
    if not os.path.exists(p):
        return ""
    return _issue_owner(open(p, encoding="utf-8").read())


def cmd_issue(project: str, action: str, rest: list) -> int:
    """问题单（MTO/STO 提单，FO 修复，提单人复测关闭）：
    issue {project} open <iid> <严重级> <描述...> / fix <iid> / close <iid> / list [open]"""
    action = action.lower()
    if action == "list":
        filt = rest[0].lower() if rest else ""
        for f in sorted(os.listdir(issues_dir(project))):
            if not f.endswith(".md"):
                continue
            content = open(os.path.join(issues_dir(project), f), encoding="utf-8").read()
            status = _issue_status(content)
            if filt and status != filt:
                continue
            first = content.splitlines()[1] if len(content.splitlines()) > 1 else ""
            print(f"  {f[:-3]:20s} [{status}] {first.strip()}")
        return 0
    if not rest:
        print(f"issue {action} 参数不足", file=sys.stderr)
        return 1
    iid = rest[0]
    p = _issue_path(project, iid)
    if action == "open":
        if len(rest) < 2:
            print("issue open <iid> <严重级> <描述>", file=sys.stderr)
            return 1
        if os.path.exists(p):
            print(f"问题单 {iid} 已存在", file=sys.stderr)
            return 1
        content = (f"# 问题单 {iid}\n\n状态：open\n归属模块：待定\n严重级：{rest[1]}\n"
                   f"提单人：{os.environ.get('ISSUE_REPORTER', '?')}\n时间：{now_iso()}\n\n描述：{' '.join(rest[2:]) or ''}\n\n"
                   f"## 修复记录\n\n## 复测记录\n")
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"ISSUE_OPEN {project}/{iid} sev={rest[1]}")
        return 0
    if not os.path.exists(p):
        print(f"问题单 {iid} 不存在", file=sys.stderr)
        return 1
    content = open(p, encoding="utf-8").read()
    if action == "assign":
        # SE 分单（归属裁决）：issue {project} assign <iid> <模块> [备注]
        # 使问题单带上归属模块 → 调度只派给该模块 FO（根治错挂）
        if len(rest) < 2:
            print("issue assign <iid> <模块> [备注]", file=sys.stderr)
            return 1
        module = rest[1].strip()
        names = [x["name"] for x in _read_modules_for_issue(project)]
        if module not in names:
            print(f"模块 {module} 不存在（可用：{', '.join(names)}）", file=sys.stderr)
            return 1
        lines = content.splitlines()
        done = False
        for i, ln in enumerate(lines):
            if ln.startswith("归属模块："):
                lines[i] = f"归属模块：{module}"
                done = True
                break
        if not done:
            for i, ln in enumerate(lines):
                if ln.startswith("状态："):
                    lines.insert(i + 1, f"归属模块：{module}")
                    done = True
                    break
            if not done:
                lines.insert(1, f"归属模块：{module}")
        _was_rejected = "FO 拒修" in content
        if _was_rejected and not any(l.startswith("归属复核：") for l in lines):
            for i, ln in enumerate(lines):
                if ln.startswith("归属模块："):
                    lines.insert(i + 1, "归属复核：locked（SE 复核后锁定，FO 不得再拒）")
                    break
        content = "\n".join(lines) + "\n"
        note = (" ".join(rest[2:])).strip()
        content += f"- {now_iso()} SE 归属裁决 → {module}" + (f"（{note}）" if note else "") + "\n"
        if _was_rejected:
            content += "- %s SE 复核 FO 拒修：维持/改派归属 %s，归属已锁定（FO 不得再拒）\n" % (now_iso(), module)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"ISSUE_ASSIGN {project}/{iid} -> {module}")
        return 0
    if action == "reject":
        # FO 拒修（P1-2，2026-09-11）：根因不在本模块/单不合理 → 退回并重新裁决
        # 触发点=命令入口；兜底=tick 检测待归属单自动 spawn SE 重新裁决
        cur = _issue_status(content)
        if cur != "open":
            print(f"问题单 {iid} 非 open（当前 {cur}），不可拒修", file=sys.stderr)
            return 1
        if _issue_owner_locked(content):
            print(f"❌ 问题单 {iid} 归属已由 SE 复核锁定，FO 不得再拒修——"
                  f"如仍有异议请升级人工处理（勿沉默不标）", file=sys.stderr)
            return 1
        owner = _issue_owner(content)
        if not owner:
            print(f"问题单 {iid} 尚未裁决归属（无需拒修——调度会交 SE 分单）", file=sys.stderr)
            return 1
        reason = " ".join(rest[1:]).strip() or "未注明理由"
        lines = content.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("归属模块："):
                lines[i] = "归属模块：待定"
                break
        content = "\n".join(lines) + "\n"
        content += f"- {now_iso()} FO 拒修（原归属 {owner}）：{reason}（退回重新裁决）\n"
        n_rej = content.count("FO 拒修")
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"ISSUE_REJECT {project}/{iid}（原归属 {owner}）：{reason}")
        if n_rej >= 2:
            try:
                with open(_paths.ALARM_FILE, "a", encoding="utf-8") as _af:
                    _af.write(f"问题单 {iid} 已被 FO 拒修 {n_rej} 次——请人工核查归属裁决是否反复不准\n")
            except OSError:
                pass
        return 0
    if action == "pend":
        # 挂起（待下版本处理）：issue {project} pend <iid> <目标版本> [理由]
        # 语义：closed=已验证闭环；pending=挂起待处理（不阻塞收口，可被 activate 唤回队列）
        if len(rest) < 2:
            print("issue pend <iid> <目标版本> [理由]", file=sys.stderr)
            return 1
        target_ver = rest[1].strip()
        cur = _issue_status(content)
        if cur not in ("open", "fixed"):
            print(f"问题单 {iid} 非 open/fixed（当前 {cur}），不可挂起", file=sys.stderr)
            return 1
        lines = content.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("状态："):
                lines[i] = "状态：pending"
                lines.insert(i + 1, f"目标版本：{target_ver}")
                break
        content = "\n".join(lines) + "\n"
        content += f"- {now_iso()} 挂起 → pending（目标版本 {target_ver}）：{' '.join(rest[2:]) or '未注明理由'}\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"ISSUE_PEND {project}/{iid} -> pending(target={target_ver})")
        return 0
    if action == "activate":
        # 激活挂起单：pending → open（回到流水线并经 SE 分单）
        cur = _issue_status(content)
        if cur != "pending":
            print(f"问题单 {iid} 非 pending（当前 {cur}），不可激活", file=sys.stderr)
            return 1
        lines = content.splitlines()
        for i, ln in enumerate(lines):
            if ln.startswith("状态："):
                lines[i] = "状态：open"
                break
        content = "\n".join(lines) + "\n"
        content += f"- {now_iso()} 激活 pending→open（进 SE 归属裁决队列）\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"ISSUE_ACTIVATE {project}/{iid} -> open")
        return 0
    if action == "split":
        # 拆分（跨模块缺陷按项拆单，SE 用）：issue {project} split <原单> <新单号> <模块> <项描述>
        if len(rest) < 4:
            print("issue split <原单> <新单号> <模块> <项描述>", file=sys.stderr)
            return 1
        new_id, module, desc = rest[1].strip(), rest[2].strip(), " ".join(rest[3:]).strip()
        names = [x["name"] for x in _read_modules_for_issue(project)]
        if module not in names:
            print(f"模块 {module} 不存在（可用：{', '.join(names)}）", file=sys.stderr)
            return 1
        np_ = _issue_path(project, new_id)
        if os.path.exists(np_):
            print(f"问题单 {new_id} 已存在", file=sys.stderr)
            return 1
        sev = next((l.split("：", 1)[1].strip() for l in content.splitlines()[:12] if l.startswith("严重级：")), "P2")
        rep = _issue_reporter(content) or "?"
        with open(np_, "w", encoding="utf-8") as f:
            f.write(f"# 问题单 {new_id}\n\n状态：open\n归属模块：{module}\n严重级：{sev}\n"
                    f"提单人：{rep}\n时间：{now_iso()}\n\n"
                    f"描述：{desc}（**由 {iid} 拆分而来**——跨模块缺陷按项拆分，2026-09-11）\n\n"
                    f"## 修复记录\n\n## 复测记录\n")
        content = content.rstrip("\n") + f"\n- {now_iso()} 拆分 → 新建 {new_id}（归属 {module}）：{desc}\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        log(f"ISSUE_SPLIT {project}/{iid} -> {new_id}({module})")
        return 0
    if action == "fix":
        if _issue_status(content) != "open":
            print(f"问题单 {iid} 非 open 状态", file=sys.stderr)
            return 1
        # 修复证据校验（2026-09-11 P1-1，触发点=命令入口·不可绕过）：
        # 归属模块代码目录须存在 mtime 晚于提单时间的文件；否则拒绝（兜底：单停留 open → tick 续派）。
        # 依据：SOCSIM-05/06 复测方代码核证「调用点仍 1 处」「常量仍 4096」，但单已被标 fixed（假修复）。
        # 确属无需改码的修复（纯文档判定/环境类）：issue fix <iid> --force <理由>（留审计 + 告警人工复核）。
        force = bool(len(rest) > 1 and rest[1] == "--force")
        owner = _issue_owner(content)
        if not owner:
            print(f"❌ 问题单 {iid} 未裁决归属，禁止标 fixed——请先由 SE 分单："
                  f"issue {project} assign {iid} <模块>", file=sys.stderr)
            return 1
        if force:
            _reason = " ".join(rest[2:]) or "未注明理由"
            log(f"ISSUE_FIX_FORCE {project}/{iid}（跳过修复证据校验：{_reason}）")
            try:
                with open(_paths.ALARM_FILE, "a", encoding="utf-8") as _af:
                    _af.write(f"问题单 {iid} 以 --force 跳过修复证据校验（{_reason}）——请人工复核\n")
            except OSError:
                pass
        else:
            _tline = next((l.split("：", 1)[1].strip() for l in content.splitlines()[:15]
                           if l.startswith("时间：")), "")
            _its_ts = 0.0
            if _tline:
                try:
                    _its_ts = datetime.strptime(_tline, "%Y-%m-%dT%H:%M:%SZ").replace(
                        tzinfo=timezone.utc).timestamp()
                except ValueError:
                    _its_ts = 0.0
            _cdir = os.path.join(project_dir(project), "code", owner)
            _newest, _newest_mt = None, 0.0
            _SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", "node_modules", ".mypy_cache", ".ruff_cache", "dist", "build"}
            _SKIP_EXT = {".pyc", ".pyo", ".log", ".tmp", ".lock"}
            for _root, _dirs, _files in os.walk(_cdir):
                _dirs[:] = [d for d in _dirs if d not in _SKIP_DIRS]
                for _fn in _files:
                    if os.path.splitext(_fn)[1] in _SKIP_EXT:
                        continue  # 缓存/日志不算代码改动（防 pytest 缓存刷新被当修复证据）
                    _fp = os.path.join(_root, _fn)
                    try:
                        _mt = os.path.getmtime(_fp)
                    except OSError:
                        continue
                    if _mt > _newest_mt:
                        _newest_mt, _newest = _mt, os.path.relpath(_fp, _cdir)
            if _newest_mt <= _its_ts:
                print(f"❌ 修复证据校验未通过：模块 {owner} 代码目录（{_cdir}）无 mtime 晚于提单时间"
                      f"（{_tline or '未知'}）的文件（最新改动：{_newest or '无'}）。\n"
                      f"   请先真正修复代码；确属无需改码（纯文档判定/环境类）用："
                      f"issue {project} fix {iid} --force <理由>", file=sys.stderr)
                return 1
            log(f"ISSUE_FIX_VERIFY {project}/{iid} ok（{owner} 最新改动：{_newest}）")
        content = content.replace("状态：open", "状态：fixed", 1)
        content += f"- {now_iso()} FO 修复完成\n"
    elif action == "close":
        if _issue_status(content) != "fixed":
            print(f"问题单 {iid} 非 fixed 状态（需 FO 先修复）", file=sys.stderr)
            return 1
        content = content.replace("状态：fixed", "状态：closed", 1)
        content += f"- {now_iso()} 提单人复测通过，关闭\n"
    elif action == "reopen":
        # 复测不通过 → 回 open（FO 再修；waiting_issues 分支自动重试）
        if _issue_status(content) != "fixed":
            print(f"问题单 {iid} 非 fixed 状态（仅复测不通过可 reopen）", file=sys.stderr)
            return 1
        content = content.replace("状态：fixed", "状态：open", 1)
        content += f"- {now_iso()} 复测不通过，重新 open：{' '.join(rest[1:]) or '未注明原因'}\n"
    else:
        print(f"未知 issue 动作: {action}（open/fix/close/reopen/list）", file=sys.stderr)
        return 1
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    log(f"ISSUE_{action.upper()} {project}/{iid}")
    return 0


def open_issues(project: str) -> list:
    """项目当前 open/fixed 问题单（门禁条件：>0 时模块/版本不进下一阶段）。"""
    out = []
    for f in sorted(os.listdir(issues_dir(project))):
        if not f.endswith(".md"):
            continue
        content = open(os.path.join(issues_dir(project), f), encoding="utf-8").read()
        if _issue_status(content) in ("open", "fixed"):
            out.append(f[:-3])
    return out


def _arch_inputs(project: str, reqs: list, st: dict) -> str:
    """SE 架构输入清单：版本下全部需求规格。"""
    lines = []
    for r in reqs:
        e = st.get(f"{project}/{r}") or {}
        lines.append(f"- {r}：规格={product_path(e.get('analysis') or '') or '?'}（状态={e.get('status', '?')}）")
    return "\n".join(lines)


def _schedule_arch_te(project: str, vd: dict, st: dict, alarms: list) -> None:
    """版本级前置阶段调度（v2 M3）：
    planning + 规格全 approved → SE 架构（arch）；arch_reviewing 等 PM；testplan 等 TE；testplan_reviewing 等 SE → in_dev"""
    for v in vd.get("versions", []):
        status = v.get("status")
        if status == "released":
            continue
        reqs = v.get("reqs") or []
        if not reqs:
            continue
        if status == "planning":
            # 规格锁定判定：approved=已评审通过；dispatched=已派发模块（approved 后继，规格仍锁定）——
            # 与 VERSION_FLOW.planning 接走语义（规格全锁定→spawn SE）一致，架构 FAIL 回 planning 重做时不受需求已派发阻塞
            if not all(st.get(f"{project}/{r}", {}).get("status") in ("approved", "dispatched") for r in reqs):
                continue
            # 版本串行：其他版本活跃（arch~qa_reviewing）时不启动架构
            ACTIVE = ("arch", "arch_reviewing", "testplan", "testplan_reviewing",
                      "in_dev", "st", "st_done", "qa", "qa_reviewing")
            if any(x.get("status") in ACTIVE for x in vd.get("versions", [])):
                continue
            if not v.get("arch_claimed"):
                v["arch_claimed"] = True
                v["arch_claimed_pid"] = 0
                v["status"] = "arch"
                out = f"{project}/arch/{v['name']}/"
                query = (
                    f"你是本流水线的【SE（架构设计）】。严格遵循 {WORKDIR}/roles/se.md 为项目 {project} 版本 {v['name']} "
                    f"执行架构设计（全量需求规格一次性）。\n"
                    f"版本需求规格（全部已获用户评审通过）：\n{_arch_inputs(project, reqs, st)}\n"
                    f"任务：1. 阅读全部规格，输出架构设计到 {product_path(out)}（架构/技术选型/模块间依赖/接口/构建/发布/配置）；\n"
                    f"2. 设计功能模块组织并落盘（按需执行，幂等）：\n"
                    f"   python3 {WORKDIR}/scripts/statectl.py module {project} add <模块名> <类型:默认 基础平台/中间件/上层应用，可自定义> [desc]\n"
                    f"   python3 {WORKDIR}/scripts/statectl.py module {project} dep <模块名> <依赖模块,逗号分隔>\n"
                    f"   python3 {WORKDIR}/scripts/statectl.py module {project} dispatch <模块名> <req_id,逗号分隔>\n"
                    f"   python3 {WORKDIR}/scripts/statectl.py module {project} iter <模块名> <迭代号,逗号分隔>（SE 排迭代计划）\n"
                    f"3. 输出功能模块分工表到 {product_path(out)}功能模块分工表.md（模块/职责/需求/依赖/迭代计划）；\n"
                    f"4. 运行 python3 {WORKDIR}/scripts/statectl.py release_arch {project} {v['name']} {out} DONE 完成状态更新；\n"
                    f"6. 完成后无需汇报。"
                )
                pid = spawn_worker("se", f"{project}/__arch{v['name']}", 1, query)
                v["arch_claimed_pid"] = pid
                log(f"SPAWN-SE {project}/{v['name']} worker=se pid={pid}")
                alarms.append(f"版本 {v['name']} 进入架构设计（SE pid={pid}）")
        elif status == "arch_reviewing":
            # PM 评审架构（评审缺失修复：自动 spawn 评审者，不依赖人工）
            if not v.get("arch_review_claimed"):
                v["arch_review_claimed"] = True
                out = f"{project}/review/arch/{v['name']}/"
                query = (
                    f"你是本流水线的【PM】。严格遵循 {WORKDIR}/roles/pm.md 为项目 {project} 版本 {v['name']} 评审架构设计。\n"
                    f"架构设计：{product_path(v.get('architecture') or '')}；模块分工：同目录功能模块分工表.md；需求规格见分工表。\n"
                    f"任务：1. 评审架构是否覆盖全部需求规格/模块组织合理/迭代计划可行；\n"
                    f"2. 评审意见写到 {product_path(out)}（明确 PASS 或 FAIL + 具体问题）；\n"
                    f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_arch {project} {v['name']} {out} PASS|FAIL；\n"
                    f"4. 完成后无需汇报。"
                )
                pid = spawn_worker("pm", f"{project}/__archrev{v['name']}", 1, query)
                v["arch_review_claimed_pid"] = pid
                log(f"SPAWN-ARCHREV {project}/{v['name']} worker=pm pid={pid}")
                alarms.append(f"版本 {v['name']} 架构待 PM 评审（pid={pid}）")
        elif status == "testplan_reviewing":
            # SE 评审整体测试方案（评审缺失修复）
            if not v.get("testplan_review_claimed"):
                v["testplan_review_claimed"] = True
                out = f"{project}/review/testplan/{v['name']}/"
                query = (
                    f"你是本流水线的【SE】。严格遵循 {WORKDIR}/roles/se.md 为项目 {project} 版本 {v['name']} 评审整体测试方案。\n"
                    f"测试方案：{v.get('test_plan')}；架构设计：{product_path(v.get('architecture') or '')}。\n"
                    f"任务：1. 评审 IT/ST 方案覆盖性与测试套件框架可用性（对照架构/模块分工）；\n"
                    f"2. 评审意见写到 {product_path(out)}（明确 PASS 或 FAIL + 具体问题）；\n"
                    f"3. 运行 python3 {WORKDIR}/scripts/statectl.py release_testplan_v2 {project} {v['name']} {out} PASS|FAIL；\n"
                    f"4. 完成后无需汇报。"
                )
                pid = spawn_worker("se", f"{project}/__tprev{v['name']}", 1, query)
                v["testplan_review_claimed_pid"] = pid
                log(f"SPAWN-TPREV {project}/{v['name']} worker=se pid={pid}")
                alarms.append(f"版本 {v['name']} 测试方案待 SE 评审（pid={pid}）")
        elif status == "testplan":
            if not v.get("test_plan_claimed"):
                v["test_plan_claimed"] = True
                v["test_plan_claimed_pid"] = 0
                v["status"] = "testplan"
                out = f"{project}/testplans/{v['name']}/"
                query = (
                    f"你是本流水线的【TE（整体测试方案）】。严格遵循 {WORKDIR}/roles/te.md 为项目 {project} 版本 {v['name']} "
                    f"制定整体测试方案。\n"
                    f"输入：架构设计 {v.get('architecture')}；需求规格见分工表模块需求。\n"
                    f"任务：1. 输出整体测试方案到 {product_path(out)}（IT 方案/ST 方案/测试套件框架设计，模板可参考主流测试套 pytest）；\n"
                    f"2. 运行 python3 {WORKDIR}/scripts/statectl.py release_testplan_v2 {project} {v['name']} {out} DONE 完成状态更新；\n"
                    f"3. 完成后无需汇报。"
                )
                pid = spawn_worker("te", f"{project}/__tp{v['name']}", 1, query)
                v["test_plan_claimed_pid"] = pid  # spawn 后写回真实 pid（原为 1314 占位 0；漏写 → 巡检把占位 0 当死进程→误杀重开→3 连 blocked）
                log(f"SPAWN-TE {project}/{v['name']} worker=te pid={pid}")
                alarms.append(f"版本 {v['name']} 进入测试方案设计（TE pid={pid}）")
    write_versions(project, vd)