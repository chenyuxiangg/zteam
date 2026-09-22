"""发布评审（QA）+ ST 用例 TE 评审。

- release_qa: QA 产出完成（包内一键脚本 + 全冷启动验证）→ qa_reviewing（等用户评审）
- confirm_guide: 用户指南用户确认 → released（写归档 + 同步 latest_version）
- reject_guide: 用户驳回用户指南 → 回 qa
- _schedule_st_qa: 调度 STO → QA
- release_st_case: ST 用例 TE 评审（带"实现依据"门禁）

机制回归门禁（release_qa DONE 触机）调用 modules._mechanism_selftest：
P0-8 发布前机检（结构不变式 + 版本/模块/问题单合法 + 发布包完整性 + 一键脚本三件套）。
"""
from __future__ import annotations

import os
import sys

from .paths import now_iso
from .pipeline import norm_product, product_path, spawn_worker
from .status import acquire_lock, log, read_status, write_status
from .paths import abs_artifact
from .versions import _sync_project_version, read_versions, write_versions
from .modules import _mechanism_selftest
from .issues import open_issues

__all__ = [
    "release_qa", "confirm_guide", "reject_guide",
    "_schedule_st_qa", "release_st_case",
]


def release_qa(project: str, version: str, product: str, conclusion: str) -> int:
    """QA 发布状态命令（v2 M5）：QA 产出 → release_qa {p} {v} {发布目录} DONE
    → qa_reviewing（等用户指南用户评审）；用户确认 → confirm_guide → released。"""
    conclusion = conclusion.strip().upper()
    if conclusion != "DONE":
        print("release_qa 仅支持 DONE（QA 完成标记）", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        if v.get("status") != "qa":
            print(f"版本状态非 qa（当前 {v.get('status')}）", file=sys.stderr)
            return 1
        full = product_path(product)
        if not os.path.exists(full):
            print(f"发布包不存在: {full}", file=sys.stderr)
            return 1
        v["release_pkg"] = norm_product(product)
        v["qa_claimed"] = False
        # 机制回归门禁（P0-8）：发布前机检结构不变式，未通过则拒绝（不落 qa_reviewing）
        _msf = _mechanism_selftest(project)
        if _msf:
            print("❌ 机制回归自检未通过，禁止 QA_DONE：\n  - " + "\n  - ".join(_msf), file=sys.stderr)
            log(f"QA_SELFTEST_FAIL {project}/{version}: {_msf[:3]}")
            return 1
        log(f"QA_SELFTEST_OK {project}/{version}（机制回归通过）")
        v["status"] = "qa_reviewing"  # 用户指南等用户评审
        write_versions(project, vd)
        log(f"QA_DONE {project}/{version} pkg={v['release_pkg']}")
    return 0


def confirm_guide(project: str, version: str) -> int:
    """用户确认用户指南（发布前最后一关）→ released（版本串行解除）。"""
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        if v.get("status") != "qa_reviewing":
            print(f"confirm_guide 仅对 qa_reviewing 有效（当前 {v.get('status')}）", file=sys.stderr)
            return 1
        v["status"] = "released"
        v["released_at"] = now_iso()
        write_versions(project, vd)
        # 需求收口：版本下 dispatched 需求 → released
        st = read_status()
        changed = False
        for r in v.get("reqs", []):
            e = st.get(f"{project}/{r}")
            if e and e.get("status") == "dispatched":
                e["status"] = "released"
                e["updated_at"] = now_iso()
                changed = True
                # v2 归档：artifacts/{project}/{rid}.md 指向版本发布包（保持 D8 诊断语义）
                ap = abs_artifact(project, r)
                if not os.path.exists(ap):
                    os.makedirs(os.path.dirname(ap), exist_ok=True)
                    with open(ap, "w", encoding="utf-8") as f:
                        f.write(f"# 归档 {project}/{r}\n\n版本：{version}\n发布包：{v.get('release_pkg')}\n状态：released（v2 模块中心，随版本发布）\n")
        if changed:
            write_status(st)
        # 版本 released → 同步项目映射表 latest_version（脚本守护）
        _sync_project_version(project, version)
        log(f"VERSION_RELEASED {project}/{version}（用户确认用户指南）")
    return 0


def reject_guide(project: str, version: str, reason: str) -> int:
    """用户驳回用户指南 → 版本回 qa（QA 修订）。"""
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        if v.get("status") != "qa_reviewing":
            print(f"reject_guide 仅对 qa_reviewing 有效（当前 {v.get('status')}）", file=sys.stderr)
            return 1
        v["status"] = "qa"
        v["qa_claimed"] = False
        v["guide_reject_reason"] = reason.strip()
        write_versions(project, vd)
        log(f"GUIDE_REJECT {project}/{version} reason={reason.strip()[:80]}")
    return 0


def _schedule_st_qa(project: str, vd: dict, md: dict, st: dict, alarms: list) -> None:
    """版本 ST / QA 调度（v2 M5）：in_dev + 全部模块迭代 it_passed → st（STO）→ st_done → qa（QA）→ qa_reviewing（等用户）。"""
    for v in vd.get("versions", []):
        status = v.get("status")
        if status in ("released", "qa", "qa_reviewing"):
            continue
        if status in ("in_dev", "st", "st_pending"):
            # 注意含 "st"/"st_pending"：STO 为长任务（分轮次协议），worker 死亡后 st_claimed 被 VERSION_STALE 重置，
            # 需本分支重新 spawn 续跑（否则版本永久卡在 st——2026-09-10 发现的缺口）；
            # "st_pending"：_advance_v2 在 in_dev+全 it_passed 时会抢注该状态，须一并纳入（2026-09-11）
            mods = [m for m in md.get("modules", []) if m.get("alive", True) and m.get("iterations")]
            if mods and all(
                    all(it.get("status") == "it_passed" for it in m.get("iterations", []))
                    for m in mods):
                if not v.get("st_claimed"):
                    v["st_claimed"] = True
                    v["status"] = "st"
                    out = f"{project}/st/{v['name']}/"
                    its = "\n".join(
                        f"- {m['name']} iter-{it['n']}：{it.get('it_report') or '?'}"
                        for m in mods for it in m.get("iterations", []))
                    query = (
                        f"你是本流水线的【STO（系统测试者，ST）】。严格遵循 {os.environ.get('WORKDIR', '.')}/roles/sto.md 为项目 {project} 版本 {v['name']} "
                        f"执行版本系统测试（ST）。\n"
                        f"整体测试方案：{product_path(v.get('test_plan') or '')}\n模块 IT 产物：\n{its}\n"
                        f"任务（**分轮次执行协议**：ST 为长任务（含 2h 级长稳），单轮跑不完，必须多轮累积）：\n"
                        f"0. **开工先读进度**：若 {product_path(out)}ST进度.md 存在，读取已完成/未完成测试组，**绝不重跑已完成部分**；"
                        f"若不存在则本轮为第 1 轮；\n"
                        f"1. 第 1 轮（**若 {product_path(out)}测试用例.md 已存在且 TE 已评 PASS（版本 st_case_passed）则跳过本步，勿重复提交**）："
                        f"写测试用例文档到 {product_path(out)}测试用例.md，提交 TE 评审"
                        f"（python3 {os.environ.get('WORKDIR', '.')}/scripts/statectl.py release_st_case {project} {v['name']} {product_path(out)}测试用例.md PASS）；\n"
                        f"2. 用例评审通过后**按测试组分轮执行**（建议顺序：debug → journey → limits → regression → stability → 长稳/UI 等重负载组），"
                        f"每轮尽力多跑，但**容量受限（上下文/工具上限）时安全结束**——结束前务必更新 {product_path(out)}ST进度.md"
                        f"（记录：本轮完成组及证据日志路径、未完成组、下轮起点）；\n"
                        f"3. **仅当全部测试组执行完毕**才运行 python3 {os.environ.get('WORKDIR', '.')}/scripts/statectl.py release_st_v2 {project} {v['name']} {out} DONE；"
                        f"未跑完不要调用（下一轮自动续跑）；\n"
                        f"4. 缺陷提问题单（issue open）；完成后无需汇报。\n"
                        f"⚠️ 禁止多引擎并行（4 vCPU 节点资源受限，多实例并发会致 504 假失败）——单实例串行 + 充足 cmd_timeout。"
                    )
                    pid = spawn_worker("sto", f"{project}/__sto{v['name']}", 1, query)
                    v["st_claimed_pid"] = pid
                    log(f"SPAWN-STO {project}/{v['name']} pid={pid}")
                    alarms.append(f"版本 {v['name']} 进入系统测试（STO pid={pid}）")
        elif status == "st_done":
            if not v.get("qa_claimed"):
                v["qa_claimed"] = True
                v["status"] = "qa"
                out = f"{project}/release/{v['name']}/"
                query = (
                    f"你是本流水线的【QA（质量专员）】。严格遵循 {os.environ.get('WORKDIR', '.')}/roles/qa.md 为项目 {project} 版本 {v['name']} 执行发布评审。\n"
                    f"输入：架构设计 {v.get('architecture')}；ST 报告 {v.get('st_product')}；模块设计见模块目录。\n"
                    f"任务：1. 评审测试报告（功能实现率/功能测试通过率/覆盖率）+ 检查安全红线；\n"
                    f"2. 编写用户指南到 {product_path(out)}用户指南.md（安装/卸载章节须指向包内一键脚本）；\n"
                    f"2.5 打包含前端时：`install.sh` 的前端构建必须实际跑通（npm run build 含类型检查）；**包内不得混入 tests/ 或 *.test.ts**（会致 vue-tsc 失败、用户装不上）；\n"
                    f"3. 按构建规则制作 release 发布包到 {product_path(out)}（含发布说明/SHA256SUMS/可用性自检），**包内必须含一键脚本三件套：install.sh（一键安装）/ uninstall.sh（一键卸载）/ start.sh（一键启动）**；\n"
                    f"4. ★【全新环境回归（强制）】：`mktemp -d` 建隔离目录 → 解包 tar.gz → 按 requirements.txt 在干净环境装依赖"
                    f"（不得以开发/测试环境跑通为准）→ 严格按用户指南步骤启动 → 健康检查（/api/state 须 200）"
                    f"→ 命令与输出写入 release 目录「可用性自检.md」，须含「全新环境」与「冷启动」证据；未通过必须修复后重跑；\n"
                    f"5. 运行 python3 {os.environ.get('WORKDIR', '.')}/scripts/statectl.py release_qa {project} {v['name']} {out} DONE（进入用户指南用户评审）；\n"
                    f"6. 完成后无需汇报。"
                )
                pid = spawn_worker("qa", f"{project}/__qa{v['name']}", 1, query)
                v["qa_claimed_pid"] = pid
                log(f"SPAWN-QA {project}/{v['name']} pid={pid}")
                alarms.append(f"版本 {v['name']} 进入发布评审（QA pid={pid}）")
    write_versions(project, vd)


def release_st_case(project: str, version: str, product: str, conclusion: str) -> int:
    """ST 用例 TE 评审（v2 M5）：release_st_case {p} {v} {用例} PASS|FAIL
    （用例评审通过后才可写 ST 测试代码——铁律）。"""
    conclusion = conclusion.strip().upper()
    if conclusion not in ("PASS", "FAIL"):
        print("conclusion 必须为 PASS/FAIL", file=sys.stderr)
        return 1
    with acquire_lock() as _:
        vd = read_versions(project)
        v = next((x for x in vd["versions"] if x["name"] == version), None)
        if not v:
            print(f"版本 {version} 不存在", file=sys.stderr)
            return 1
        full = product_path(product)
        if not os.path.exists(full):
            print(f"用例不存在: {full}", file=sys.stderr)
            return 1
        if conclusion == "PASS":
            # 判据可达性门禁（P1-9，2026-09-11）：用例文档须含「实现依据」字段——
            # 判据必须数学可达并引用实现（字段/常量/语义）。依据：STB-03「RSS 首末增幅 ≤20%」对有界
            # 环形缓冲（环未满必然增长）数学不可达，白判 FAIL 一轮。
            try:
                _doc = open(full, encoding="utf-8", errors="replace").read()
            except OSError as e:
                print(f"用例读取失败：{e}", file=sys.stderr)
                return 1
            if "实现依据" not in _doc:
                print("❌ 判据可达性门禁未通过：用例文档缺少「实现依据」字段——"
                      "每条判据须引用实现依据（具体字段/常量/语义），确保判据在实现语义下可达。"
                      "（STB-03 教训：判据与实现语义脱节会误判 FAIL）", file=sys.stderr)
                log(f"ST_CASE_GATE_FAIL {project}/{version}（缺实现依据）")
                return 1
        v.setdefault("st_case_reviews", []).append(norm_product(product))
        v["st_case_passed"] = conclusion == "PASS"
        write_versions(project, vd)
        log(f"ST_CASE {project}/{version} {conclusion} by=TE")
    return 0