"""状态文件读写、flock、日志、claim 字段清理。

所有路径常量动态引用 paths 模块（不要在模块顶部把路径值拷贝成本模块变量
——否则测试 setUp 把 paths.WORKDIR 重定向到 tmp_path 后，本模块仍指向原始
路径，导致写入真实工作区）。
"""
from __future__ import annotations

import fcntl
import json
import os
import time

from . import paths as _paths
from .paths import ensure_project, project_lock_file, project_status_file, read_projects, split_key

__all__ = [
    "log",
    "read_status", "write_status",
    "acquire_lock", "clear_claim", "pid_alive",
]


def log(line: str) -> None:
    """追加一行到 logs/pipeline.log（ISO 时间前缀 + 消息；append 模式，进程安全由 O_APPEND 保证）。"""
    os.makedirs(_paths.LOG_DIR, exist_ok=True)
    with open(_paths.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{_paths.now_iso()} {line}\n")


def read_status(project: str = None) -> dict:
    """读状态。project 指定 → 只读该项目 status.json；None → 聚合全部项目（key 仍 '<project>/<req_id>'）。
    兼容旧单文件：workspace/status.json 存在（迁移前）时优先读它。"""
    if project is not None:
        try:
            with open(project_status_file(project), encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    # 聚合全部项目（解耦后主源 = 映射表 work_path/status.json；存量 workspace 兼容）
    merged: dict = {}
    if os.path.isfile(_paths.STATUS_FILE):  # 迁移前的单文件
        try:
            with open(_paths.STATUS_FILE, encoding="utf-8") as f:
                merged.update(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    for p in read_projects().get("projects", []):  # 映射表项目
        sf = project_status_file(p["name"])
        if os.path.isfile(sf):
            try:
                with open(sf, encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in data.items():
                    merged.setdefault(k, v)  # 单文件优先
            except (FileNotFoundError, json.JSONDecodeError):
                continue
    if os.path.isdir(_paths.WORKSPACE_DIR):  # 存量兼容（未登记/迁移前数据）
        for proj in sorted(os.listdir(_paths.WORKSPACE_DIR)):
            sf = project_status_file(proj)
            if os.path.isfile(sf):
                try:
                    with open(sf, encoding="utf-8") as f:
                        data = json.load(f)
                    for k, v in data.items():
                        merged.setdefault(k, v)  # 单文件优先
                except (FileNotFoundError, json.JSONDecodeError):
                    continue
    return merged


def write_status(st: dict, project: str = None) -> None:
    """写状态。project 指定 → 写该项目文件；None → 按 key 分发到各项目文件。
    迁移兼容：workspace/status.json 仍存在时同步写它（旧读路径可见），迁移完成后由 migrate 删除。"""
    if project is not None:
        ensure_project(project)
        tmp = project_status_file(project) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, project_status_file(project))
        return
    by_proj: dict = {}
    for key, e in st.items():
        p, _ = split_key(key)
        by_proj.setdefault(p, {})[key] = e
    for p, sub in by_proj.items():
        ensure_project(p)
        tmp = project_status_file(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sub, f, ensure_ascii=False, indent=2)
        os.replace(tmp, project_status_file(p))
    if os.path.isfile(_paths.STATUS_FILE):  # 迁移兼容
        with open(_paths.STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)


def acquire_lock(timeout: float = 10.0, project: str = None):
    """flock 写锁。project 指定 → 项目锁（项目间并发的基础）；None → 全局锁（register/聚合扫描）。
    返回文件句柄（调用方负责 with 释放；超时会抛 RuntimeError）。"""
    lockf = open(project_lock_file(project) if project else _paths.LOCK_FILE, "w")
    deadline = time.time() + timeout
    while True:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lockf
        except BlockingIOError:
            if time.time() > deadline:
                lockf.close()
                raise RuntimeError("状态锁获取超时（另一进程持有锁）")
            time.sleep(0.2)


def clear_claim(e: dict) -> None:
    """清掉认领相关字段（claimed_by/claimed_at/worker_pid），常用于回滚/stale 恢复。"""
    e.pop("claimed_by", None)
    e.pop("claimed_at", None)
    e.pop("worker_pid", None)


def pid_alive(pid) -> bool:
    """判定 PID 是否存活（None/0/负/非法 → False；PermissionError → True 表示存在但无权限）。"""
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