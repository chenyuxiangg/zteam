"""Tests for statectl_core.resources: 资源感知恢复 + 版本 unblock + blocked 原因判定。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from statectl_core import resources, versions
from statectl_core.resources import (
    _log_matches,
    _mark_blocked_reason,
    _minimax_quota_ok,
    _resource_unblock,
    _version_unblock,
)

from ._helpers import StatectlTestCase


class _SeedMixin(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")


# ---------------- _version_unblock ----------------

class VersionUnblock(_SeedMixin):
    def _make_v(self, status: str = "blocked", **extra) -> None:
        base = {"name": "v1.0.0", "status": status, "iterations": [], "reqs": []}
        base.update(extra)
        versions.write_versions("demo", {"current": "v1.0.0",
                                          "versions": [base]})

    def test_unblock_returns_to_blocked_from(self) -> None:
        self._make_v(blocked_from="arch")
        rc = _version_unblock("demo", "v1.0.0")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "arch")
        self.assertNotIn("blocked_from", v)
        self.assertEqual(v["failures"], 0)

    def test_unblock_defaults_to_planning(self) -> None:
        # 缺省 blocked_from → planning（兼容旧数据）
        self._make_v()
        rc = _version_unblock("demo", "v1.0.0")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "planning")

    def test_unblock_clears_all_claims(self) -> None:
        self._make_v(
            blocked_from="arch",
            arch_claimed=True, arch_claimed_pid=100,
            arch_review_claimed=True, arch_review_claimed_pid=101,
            test_plan_claimed=True, test_plan_claimed_pid=102,
            testplan_review_claimed=True, testplan_review_claimed_pid=103,
            st_claimed=True, st_claimed_pid=104,
            qa_claimed=True, qa_claimed_pid=105,
            blocked_reason="resource:minimax",
        )
        rc = _version_unblock("demo", "v1.0.0")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        for k in ("arch_claimed", "arch_review_claimed", "test_plan_claimed",
                  "testplan_review_claimed", "st_claimed", "qa_claimed",
                  "blocked_reason"):
            self.assertNotIn(k, v)

    def test_unknown_version_returns_1(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": []})
        self.assertEqual(_version_unblock("demo", "v9.9.9"), 1)

    def test_non_blocked_returns_1(self) -> None:
        self._make_v(status="planning")
        self.assertEqual(_version_unblock("demo", "v1.0.0"), 1)


# ---------------- _resource_unblock ----------------

class ResourceUnblock(_SeedMixin):
    def _setup_blocked(self, *, kind: str, it_status: str = "blocked",
                        it_reason: str = None) -> tuple:
        """建一个 blocked 迭代或版本。kind='module' or 'version'。"""
        if kind == "module":
            md = {"modules": [{
                "name": "m1", "iterations": [{
                    "n": 1, "status": it_status, "claimed": True, "claimed_pid": 1,
                }],
            }]}
            if it_reason:
                md["modules"][0]["iterations"][0]["blocked_reason"] = it_reason
            return md, {"versions": []}
        else:
            vd = {"versions": [{"name": "v1.0.0", "status": it_status,
                                  "iterations": [], "reqs": []}]}
            if it_reason:
                vd["versions"][0]["blocked_reason"] = it_reason
            return {"modules": []}, vd

    def test_module_minimax_recovers_when_quota_ok(self) -> None:
        md, vd = self._setup_blocked(kind="module", it_reason="resource:minimax")
        with mock.patch("statectl_core.resources._minimax_quota_ok", return_value=True):
            alarms: list = []
            _resource_unblock("demo", md, vd, alarms)
        it = md["modules"][0]["iterations"][0]
        self.assertEqual(it["status"], "design_pending")
        self.assertEqual(it["failures"], 0)
        # claimed 等系列被 pop（实际不再调用 _module_unblock——内联修改）
        self.assertNotIn("claimed", it)
        self.assertNotIn("blocked_reason", it)
        self.assertTrue(any("m1" in a for a in alarms))

    def test_module_network_recovers_immediately(self) -> None:
        md, vd = self._setup_blocked(kind="module", it_reason="network")
        with mock.patch("statectl_core.resources._minimax_quota_ok") as m_quota:
            alarms: list = []
            _resource_unblock("demo", md, vd, alarms)
            # network 不调配额检查
            m_quota.assert_not_called()
        self.assertEqual(md["modules"][0]["iterations"][0]["status"], "design_pending")

    def test_module_other_no_autorecover(self) -> None:
        md, vd = self._setup_blocked(kind="module", it_reason="other")
        with mock.patch("statectl_core.resources._minimax_quota_ok") as m_quota:
            alarms: list = []
            _resource_unblock("demo", md, vd, alarms)
            m_quota.assert_not_called()
        self.assertEqual(md["modules"][0]["iterations"][0]["status"], "blocked")

    def test_module_minimax_quota_not_ok_no_recover(self) -> None:
        md, vd = self._setup_blocked(kind="module", it_reason="resource:minimax")
        with mock.patch("statectl_core.resources._minimax_quota_ok", return_value=False):
            alarms: list = []
            _resource_unblock("demo", md, vd, alarms)
        self.assertEqual(md["modules"][0]["iterations"][0]["status"], "blocked")

    def test_version_minimax_recovers(self) -> None:
        md, vd = self._setup_blocked(kind="version", it_reason="resource:minimax",
                                       it_status="blocked")
        vd["versions"][0]["blocked_from"] = "arch"
        with mock.patch("statectl_core.resources._minimax_quota_ok", return_value=True):
            alarms: list = []
            _resource_unblock("demo", md, vd, alarms)
        self.assertEqual(vd["versions"][0]["status"], "arch")
        self.assertTrue(any("v1.0.0" in a for a in alarms))

    def test_version_other_skipped(self) -> None:
        md, vd = self._setup_blocked(kind="version", it_reason="other")
        with mock.patch("statectl_core.resources._minimax_quota_ok") as m_quota:
            _resource_unblock("demo", md, vd, [])
            m_quota.assert_not_called()
        self.assertEqual(vd["versions"][0]["status"], "blocked")

    def test_non_blocked_module_skipped(self) -> None:
        md, vd = self._setup_blocked(kind="module", it_status="dev_working")
        with mock.patch("statectl_core.resources._minimax_quota_ok") as m_quota:
            _resource_unblock("demo", md, vd, [])
            m_quota.assert_not_called()
        self.assertEqual(md["modules"][0]["iterations"][0]["status"], "dev_working")

    def test_alarm_file_written_on_recover(self) -> None:
        md, vd = self._setup_blocked(kind="module", it_reason="network")
        from statectl_core import paths
        alarm = paths.ALARM_FILE
        before = os.path.getsize(alarm) if os.path.exists(alarm) else 0
        with mock.patch("statectl_core.resources._minimax_quota_ok", return_value=True):
            _resource_unblock("demo", md, vd, [])
        after = os.path.getsize(alarm) if os.path.exists(alarm) else 0
        self.assertGreater(after, before)
        with open(alarm, "r", encoding="utf-8") as f:
            self.assertIn("RESOURCE_RECOVERED", f.read())


# ---------------- _minimax_quota_ok ----------------

class MinimaxQuotaOk(unittest.TestCase):
    def test_returns_true_on_rc_0(self) -> None:
        fake = mock.Mock(returncode=0)
        with mock.patch("statectl_core.resources.subprocess.run", return_value=fake):
            self.assertTrue(_minimax_quota_ok())

    def test_returns_false_on_nonzero(self) -> None:
        fake = mock.Mock(returncode=1)
        with mock.patch("statectl_core.resources.subprocess.run", return_value=fake):
            self.assertFalse(_minimax_quota_ok())

    def test_returns_false_on_exception(self) -> None:
        with mock.patch("statectl_core.resources.subprocess.run",
                         side_effect=OSError("boom")):
            self.assertFalse(_minimax_quota_ok())


# ---------------- _log_matches ----------------

class LogMatches(unittest.TestCase):
    def test_version_arch_prefix(self) -> None:
        self.assertTrue(_log_matches("worker-__archv1.0.0.log", "v1.0.0"))

    def test_version_qa_prefix(self) -> None:
        self.assertTrue(_log_matches("worker-__qav1.0.0.log", "v1.0.0"))

    def test_module_pattern(self) -> None:
        self.assertTrue(_log_matches("worker-__fo-m1-it1.log", "m1"))

    def test_module_short_name_no_substring_collision(self) -> None:
        # "m" 不会误匹配 m1（精确模式：'-{key}-it'）
        self.assertFalse(_log_matches("worker-__fo-m1-it1.log", "m"))
        # 但 "m1" 能匹配
        self.assertTrue(_log_matches("worker-__fo-m1-it1.log", "m1"))

    def test_version_digit_detection(self) -> None:
        # 版本必须含数字才视为版本 key
        self.assertFalse(_log_matches("worker-__arch.log", "arch"))

    def test_module_no_digit_falls_through(self) -> None:
        self.assertFalse(_log_matches("worker-__fo-mod.log", "mod"))
        # 但若 key 含 '-it' 子串 → 误匹配（原文如此：保留）
        self.assertTrue(_log_matches("worker-__fo-mod-it5.log", "mod"))


# ---------------- _mark_blocked_reason ----------------

class MarkBlockedReason(_SeedMixin):
    def test_existing_reason_returned(self) -> None:
        it = {"blocked_reason": "resource:minimax"}
        self.assertEqual(_mark_blocked_reason("demo", "m1", it), "resource:minimax")

    def test_review_feedback_marks_other(self) -> None:
        # 评审 FAIL×N 打回的 blocked → 直接 other（永不自动 unblock）
        logs = os.path.join(self.wp, "logs")
        os.makedirs(logs, exist_ok=True)
        # 即使日志里满是 timeout 字样也不能误判
        with open(os.path.join(logs, "errors.log"), "w") as f:
            f.write("timeout timeout timeout connectionerror")
        it = {"review_feedback": "demo/review/foo.md"}
        self.assertEqual(_mark_blocked_reason("demo", "m1", it), "other")
        self.assertEqual(it["blocked_reason"], "other")

    def test_design_review_feedback_marks_other(self) -> None:
        it = {"design_review_feedback": "demo/review/d.md"}
        self.assertEqual(_mark_blocked_reason("demo", "m1", it), "other")

    def test_quota_keywords(self) -> None:
        logs = os.path.join(self.wp, "logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "errors.log"), "w") as f:
            f.write("HTTP 429 配额已耗尽")
        it: dict = {}
        self.assertEqual(_mark_blocked_reason("demo", "m1", it), "resource:minimax")

    def test_network_keywords(self) -> None:
        logs = os.path.join(self.wp, "logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "errors.log"), "w") as f:
            f.write("APITimeoutError: ConnectionError")
        it: dict = {}
        self.assertEqual(_mark_blocked_reason("demo", "m1", it), "network")

    def test_no_keywords_marks_other(self) -> None:
        logs = os.path.join(self.wp, "logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "errors.log"), "w") as f:
            f.write("regular content")
        it: dict = {}
        self.assertEqual(_mark_blocked_reason("demo", "m1", it), "other")

    def test_no_logs_dir_handles_gracefully(self) -> None:
        it: dict = {}
        # 没建 logs 目录 → 静默处理 → other
        self.assertEqual(_mark_blocked_reason("demo", "m1", it), "other")


if __name__ == "__main__":
    unittest.main()