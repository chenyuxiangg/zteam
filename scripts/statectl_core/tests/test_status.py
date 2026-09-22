"""Tests for statectl_core.status: 状态读写、锁、日志、claim/pid 工具。"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess as _sp
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone

from statectl_core import status
from statectl_core.status import (
    acquire_lock,
    clear_claim,
    log,
    pid_alive,
    read_status,
    write_status,
)

from ._helpers import StatectlTestCase


class Log(StatectlTestCase):
    def test_appends_line_with_iso_prefix(self) -> None:
        log("hello world")
        with open(self._paths_mod.LOG_FILE, encoding="utf-8") as f:
            content = f.read()
        # ISO 时间前缀 + 空格 + 消息
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) hello world\n$", content)
        self.assertIsNotNone(m, f"log line format unexpected: {content!r}")

    def test_appends_multiple_lines_in_order(self) -> None:
        log("first")
        log("second")
        log("third")
        with open(self._paths_mod.LOG_FILE, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln]
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].endswith(" first"))
        self.assertTrue(lines[1].endswith(" second"))
        self.assertTrue(lines[2].endswith(" third"))


class WriteReadStatus(StatectlTestCase):
    def test_write_and_read_single_project(self) -> None:
        wp = self.make_project("alpha")
        st = {"alpha/REQ-1": {"status": "pending"}}
        write_status(st, project="alpha")
        got = read_status(project="alpha")
        self.assertEqual(got, st)

    def test_write_to_missing_project_creates_dirs(self) -> None:
        wp = str(self.tmp / "fresh")
        # 先登记映射表
        self.write_projects({"projects": [{"name": "fresh", "work_path": wp}]})
        write_status({"fresh/REQ-1": {"status": "pending"}}, project="fresh")
        self.assertTrue(os.path.isdir(wp))
        self.assertTrue(os.path.exists(os.path.join(wp, "status.json")))

    def test_read_missing_project_returns_empty(self) -> None:
        self.assertEqual(read_status(project="nope"), {})

    def test_read_corrupt_project_json_returns_empty(self) -> None:
        wp = self.make_project("alpha")
        with open(os.path.join(wp, "status.json"), "w") as f:
            f.write("{not valid json")
        self.assertEqual(read_status(project="alpha"), {})

    def test_write_dispatches_by_key_prefix(self) -> None:
        # 写聚合时按 '<project>/<rid>' 分发到各项目文件
        wp_a = self.make_project("alpha")
        wp_b = self.make_project("beta")
        st = {
            "alpha/REQ-1": {"status": "pending"},
            "beta/REQ-2": {"status": "analyzing"},
        }
        write_status(st)
        a = read_status(project="alpha")
        b = read_status(project="beta")
        self.assertEqual(a, {"alpha/REQ-1": {"status": "pending"}})
        self.assertEqual(b, {"beta/REQ-2": {"status": "analyzing"}})

    def test_write_no_residue_tmp_file(self) -> None:
        wp = self.make_project("alpha")
        write_status({"alpha/REQ-1": {"status": "pending"}}, project="alpha")
        self.assertFalse(os.path.exists(os.path.join(wp, "status.json.tmp")))

    def test_write_status_is_atomic(self) -> None:
        # 写之前把旧文件给覆盖，新内容应完整可见
        wp = self.make_project("alpha")
        write_status({"alpha/REQ-1": {"status": "analyzing"}}, project="alpha")
        st = json.load(open(os.path.join(wp, "status.json")))
        self.assertEqual(st["alpha/REQ-1"]["status"], "analyzing")


class ReadStatusAggregation(StatectlTestCase):
    """聚合模式：兼容旧单文件 + 映射表项目 + workspace 存量。"""

    def test_aggregates_registered_projects(self) -> None:
        self.make_project("alpha")
        self.make_project("beta")
        write_status({"alpha/REQ-1": {"status": "pending"}}, project="alpha")
        write_status({"beta/REQ-2": {"status": "pending"}}, project="beta")
        merged = read_status()
        self.assertIn("alpha/REQ-1", merged)
        self.assertIn("beta/REQ-2", merged)

    def test_legacy_single_file_takes_precedence(self) -> None:
        # 当 workspace/status.json（旧单文件）存在时，它的 keys 不能被项目文件覆盖
        wp_a = self.make_project("alpha")
        # 写项目文件
        write_status({"alpha/REQ-1": {"status": "pending"}}, project="alpha")
        # 写旧单文件（同 key 覆盖值不同）
        legacy = {"alpha/REQ-1": {"status": "approved"}}
        os.makedirs(os.path.dirname(self._paths_mod.STATUS_FILE), exist_ok=True)
        json.dump(legacy, open(self._paths_mod.STATUS_FILE, "w"))
        merged = read_status()
        self.assertEqual(merged["alpha/REQ-1"]["status"], "approved")


class AcquireLock(StatectlTestCase):
    def test_acquire_and_release(self) -> None:
        f = acquire_lock(project=None)
        self.assertIsNotNone(f)
        # close 后能再拿
        f.close()
        f2 = acquire_lock(project=None)
        f2.close()

    def test_project_lock_independent_from_global(self) -> None:
        # 项目锁和全局锁是两个不同文件，并发互不阻塞
        wp = self.make_project("alpha")
        fp = acquire_lock(project="alpha")
        fg = acquire_lock(project=None)
        fp.close()
        fg.close()

    def test_lock_times_out_when_held(self) -> None:
        holder = acquire_lock(timeout=10.0, project=None)
        try:
            with self.assertRaises(RuntimeError) as cm:
                acquire_lock(timeout=0.3, project=None)
            self.assertIn("状态锁获取超时", str(cm.exception))
        finally:
            holder.close()


class ClearClaim(unittest.TestCase):
    def test_removes_three_fields(self) -> None:
        e = {
            "status": "pending",
            "claimed_by": "fo",
            "claimed_at": "2026-01-01T00:00:00Z",
            "worker_pid": 12345,
            "other": "kept",
        }
        clear_claim(e)
        self.assertNotIn("claimed_by", e)
        self.assertNotIn("claimed_at", e)
        self.assertNotIn("worker_pid", e)
        self.assertEqual(e["other"], "kept")

    def test_safe_when_already_absent(self) -> None:
        e = {"status": "pending"}
        clear_claim(e)  # 不抛错
        self.assertEqual(e, {"status": "pending"})


class PidAlive(unittest.TestCase):
    def test_none_returns_false(self) -> None:
        self.assertFalse(pid_alive(None))

    def test_zero_returns_false(self) -> None:
        # pid=0 视为未 spawn（防 kill(0,0) 误判进程组存活）
        self.assertFalse(pid_alive(0))

    def test_negative_returns_false(self) -> None:
        self.assertFalse(pid_alive(-1))

    def test_invalid_string_returns_false(self) -> None:
        self.assertFalse(pid_alive("not-a-pid"))

    def test_current_process_pid_returns_true(self) -> None:
        self.assertTrue(pid_alive(os.getpid()))

    def test_nonexistent_pid_returns_false(self) -> None:
        # 取一个很大的 PID，几乎不可能存活
        self.assertFalse(pid_alive(2**30))


if __name__ == "__main__":
    unittest.main()