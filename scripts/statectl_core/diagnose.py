"""一键健康检查（DFx 落地）。

诊断项：
  D1   status.json（项目级）合法 + JSON 完整
  D2   目录完整性（roles/scripts/docs + 各项目 work_path 子目录）
  D3   需求条目字段完整（REQUIRED_FIELDS）
  D4   状态机合法（STATE_SET）
  D5   中间态滞留检测（claimed/working/reviewing 超过 STALE_AFTER_MIN）
  D6   非中间态却残留 claim 字段（数据卫生）
  D7   引用产物路径存在性
  D8   终态归档完整性（abs_artifact）
  D9   input/ 未登记文件
  D10  状态锁可获取性（无进程持锁）
  D11  gateway 运行状态
  D12  cron job 存在性
  D13  当前下半部 worker 进程数
  D14  logs/ 目录可写
  D15  版本状态机可达性表（VERSION_FLOW）
  D16  实际版本状态在 VERSION_FLOW 内
  D17  结构不变式（进行中迭代 → 版本 in_dev）
  D18  renode 多引擎实例检测

任一 FAIL → 退出码 1（cron 告警）。详细排查见 docs/troubleshooting.md。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from .paths import (
    DEFAULT_PROJECT,
    LOG_DIR,
    WORKDIR,
    WORKSPACE_DIR,
    abs_artifact,
    read_projects,
    rel_artifact,
    split_key,
)
from .pipeline import product_path
from .status import acquire_lock, read_status
from .versions import VERSION_FLOW, read_versions
from .modules import read_modules

__all__ = ["diagnose", "_sh", "REQUIRED_FIELDS"]


REQUIRED_FIELDS = ["status", "round", "max_rounds", "forced", "analysis",
                   "reviews", "failures", "created_at", "updated_at"]


def _sh(args, timeout=15) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except Exception:
        return ""


def diagnose() -> int:
    """一键健康检查（DFx 落地）。任一 FAIL → 退出码 1。"""
    from .pipeline import STALE_AFTER_MIN, STATE_SET, MID_STATES
    rows = []

    def add(level, code, msg):
        rows.append((level, code, msg))

    # D1 status.json
    try:
        st = read_status()
        add("PASS", "D1", "status.json 存在且 JSON 合法")
    except json.JSONDecodeError as e:
        st = {}
        add("FAIL", "D1", f"status.json JSON 损坏: {e}")
    except FileNotFoundError:
        st = {}
        ps = read_projects().get("projects", [])
        if ps and any(os.path.exists(os.path.join(p["work_path"], "status.json")) for p in ps):
            add("FAIL", "D1", "存在已投放项目但 status.json 缺失")
        else:
            add("INFO", "D1", "尚无已投放项目")

    # D2 目录完整性
    missing = [d for d in ("roles", "scripts", "docs") if not os.path.isdir(os.path.join(WORKDIR, d))]
    proj_srcs = []
    for p in read_projects().get("projects", []):
        proj_srcs.append((p["name"], p.get("work_path")))
    for p in sorted(os.listdir(WORKSPACE_DIR)) if os.path.isdir(WORKSPACE_DIR) else []:
        if os.path.isdir(os.path.join(WORKSPACE_DIR, p)) and p not in ("logs",) and not p.startswith("."):
            if p not in [x[0] for x in proj_srcs]:
                proj_srcs.append((p, os.path.join(WORKSPACE_DIR, p)))
    for proj, base in proj_srcs:
        if not base or not os.path.isdir(base):
            add("WARN", "D2", f"{proj} 工作路径未创建（{base}）")
            continue
        miss_p = [d for d in ("input", "analysis", "review", "artifacts", "plans", "testplans",
                              "code", "tests", "quality", "security", "release", "archive", "logs")
                  if not os.path.isdir(os.path.join(base, d))]
        if miss_p:
            if "input" in miss_p:
                add("WARN", "D2", f"{proj} 工作路径未初始化")
            else:
                missing.append(f"{proj}/{{{','.join(miss_p)}}}")
    if not os.path.isdir(LOG_DIR):
        missing.append("logs")
    add("PASS" if not missing else "FAIL", "D2", "目录完整" if not missing else f"缺失目录: {missing}")

    # D3-D8
    for key, e in st.items():
        miss_f = [f for f in REQUIRED_FIELDS if f not in e]
        if miss_f:
            add("WASS", "D3", f"{key} 缺字段 {miss_f}") if False else add("WARN", "D3", f"{key} 缺字段 {miss_f}")
        s = e.get("status")
        if s not in STATE_SET:
            add("FAIL", "D4", f"{key} 非法状态 {s!r}")
        if s in MID_STATES:
            ca = e.get("claimed_at")
            if not ca:
                add("WARN", "D5", f"{key} 处于 {s} 但无 claimed_at")
            else:
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(ca.replace("Z", "+00:00"))).total_seconds() / 60.0
                except ValueError:
                    age = STALE_AFTER_MIN + 1
                if age >= 24 * 60:
                    add("WARN", "D5", f"{key} 滞留 {s} 已 {age:.0f} 分钟")
                elif age >= STALE_AFTER_MIN:
                    add("WARN", "D5", f"{key} 滞留 {s} 已 {age:.0f} 分钟")
        else:
            leftover = [k for k in ("claimed_by", "claimed_at", "worker_pid") if k in e]
            if leftover:
                add("WARN", "D6", f"{key} 非中间态却残留 claim 字段 {leftover}")
        for k in (e.get("analysis"),) + tuple(e.get("reviews", [])):
            if k and not os.path.exists(product_path(k)):
                add("WARN", "D7", f"{key} 引用文件缺失: {k}")
        if s in ("approved", "released"):
            project, rid = split_key(key)
            if not os.path.exists(abs_artifact(project, rid)):
                add("WARN", "D8", f"{key} 已 {s} 但缺 {rel_artifact(project, rid)}")
            if e.get("forced"):
                add("WARN", "D8", f"{key} 为强制归档（forced），请人工复核")

    # D9 input/ 未登记
    unreg = []
    for p in read_projects().get("projects", []):
        idir = os.path.join(p["work_path"], "input")
        if os.path.isdir(idir):
            for name in sorted(os.listdir(idir)):
                if name.endswith(".md") and f"{p['name']}/{name[:-3]}" not in st:
                    unreg.append(f"{p['name']}/{name}")
    for proj in sorted(os.listdir(WORKSPACE_DIR)) if os.path.isdir(WORKSPACE_DIR) else []:
        if proj in ("logs",) or proj.startswith(".") or not os.path.isdir(os.path.join(WORKSPACE_DIR, proj)):
            continue
        idir = os.path.join(WORKSPACE_DIR, proj, "input")
        if os.path.isdir(idir):
            for name in sorted(os.listdir(idir)):
                if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                    unreg.append(f"{proj}/{name}")
    legacy_input = os.path.join(WORKSPACE_DIR, "input")
    if os.path.isdir(legacy_input):
        for proj in sorted(os.listdir(legacy_input)):
            pdir = os.path.join(legacy_input, proj)
            if os.path.isdir(pdir):
                for name in sorted(os.listdir(pdir)):
                    if name.endswith(".md") and f"{proj}/{name[:-3]}" not in st:
                        unreg.append(f"{proj}/{name}")
            elif pdir.endswith(".md") and f"{DEFAULT_PROJECT}/{proj[:-3]}" not in st:
                unreg.append(proj)
    if unreg:
        add("INFO", "D9", f"input/ 未登记文件 {unreg}")

    # D10 锁
    try:
        acquire_lock(timeout=2).close()
        add("PASS", "D10", "状态锁可获取")
    except RuntimeError:
        add("INFO", "D10", "状态锁被占用")

    # D11 gateway
    out = _sh(["hermes", "cron", "status"])
    if "Gateway is running" in out:
        add("PASS", "D11", "gateway 运行中")
    else:
        add("FAIL", "D11", "gateway 未运行")

    # D12 cron job
    out = _sh(["hermes", "cron", "list"])
    for name in ("req-analyst-top", "req-reviewer-top", "req-worker-top", "req-weekly-audit", "req-result-notify"):
        if f"Name:      {name}" not in out and f"Name: {name}" not in out:
            add("WARN", "D12", f"cron job {name} 缺失")

    # D13 worker 进程
    out = _sh(["ps", "-eo", "args"])
    n = sum(1 for ln in out.splitlines() if "hermes chat" in ln and " -q " in ln)
    add("INFO", "D13", f"当前下半部 worker 进程数: {n}")

    # D14 日志可写
    add("PASS" if os.access(LOG_DIR, os.W_OK) else "FAIL", "D14", "logs/ 目录可写")

    # D15 版本可达性
    dead = []
    for st, flow in VERSION_FLOW.items():
        if not flow.get("channel"):
            dead.append(f"{st}(无通道)")
    if dead:
        add("FAIL", "D15", f"版本状态机可达性表存在死状态: {', '.join(dead)}")
    else:
        add("PASS", "D15", f"版本状态机可达性表完整（{len(VERSION_FLOW)} 状态）")

    # D16 实际状态合法
    bad_v = []
    for p in [x["name"] for x in read_projects().get("projects", [])]:
        try:
            vd = read_versions(p)
        except Exception:
            continue
        for v in vd.get("versions", []):
            s = v.get("status")
            if s and s not in VERSION_FLOW:
                bad_v.append(f"{p}/{v['name']}={s}")
    if bad_v:
        add("WARN", "D16", f"存在不在可达性表的版本状态: {', '.join(bad_v[:5])}")
    else:
        add("PASS", "D16", "全部版本状态在可达性表内")

    # D17 结构不变式
    d17_bad = []
    for p in [x["name"] for x in read_projects().get("projects", [])]:
        try:
            _vd = read_versions(p)
            _md = read_modules(p)
        except Exception:
            continue
        _busy = []
        for _m in _md.get("modules", []):
            for _it in _m.get("iterations", []):
                if _it.get("status") not in ("it_passed", "blocked"):
                    _busy.append(f"{_m['name']}/it{_it['n']}={_it.get('status')}")
        if not _busy:
            continue
        for _v in _vd.get("versions", []):
            if _v.get("status") in ("st", "st_done", "st_pending", "qa", "qa_reviewing"):
                d17_bad.append(f"{p}/{_v['name']}={_v.get('status')} 但存在进行中迭代（{', '.join(_busy[:3])}）")
    if d17_bad:
        add("FAIL", "D17", "迭代/版本状态不自洽: " + "; ".join(d17_bad[:3]))
    else:
        add("PASS", "D17", "迭代/版本状态自洽")

    # D18 多引擎
    try:
        _psr = subprocess.run(["pgrep", "-fc", "renode.*--disable-xwt"], capture_output=True, text=True)
        _neng = int((_psr.stdout or "0").strip() or 0)
    except Exception:
        _neng = 0
    if _neng > 1:
        add("WARN", "D18", f"检测到 {_neng} 个 renode 引擎实例并存")
    else:
        add("PASS", "D18", f"renode 引擎实例数正常（{_neng}）")

    print("== zteam 诊断报告 ==")
    for level, code, msg in rows:
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "INFO": "ℹ️"}[level]
        print(f"  {icon} [{code}] {msg}")
    nfail = sum(1 for r in rows if r[0] == "FAIL")
    nwarn = sum(1 for r in rows if r[0] == "WARN")
    print(f"== 结论: {nfail} 个严重问题 / {nwarn} 个警告 ==")
    return 1 if nfail else 0