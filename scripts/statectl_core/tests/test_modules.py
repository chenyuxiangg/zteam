"""Tests for statectl_core.modules: 模块 CRUD + 调度 + 迭代链 + 工具。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from statectl_core import modules, versions
from statectl_core.modules import (
    MODULE_TYPES,
    cmd_module,
    ensure_modules,
    read_modules,
    write_modules,
    _get_mod_iter,
    _module_unblock,
    release_module,
    _module_passed,
    _module_stale_recovery,
    _version_stale_recovery,
    _module_inputs,
    _issue_stale_watch,
    _dep_cycle,
    _se_triage_and_attach,
    _schedule_module_iter,
    release_st_v2,
    _module_checks,
    _mechanism_selftest,
)
from statectl_core.issues import open_issues

from ._helpers import StatectlTestCase


# ---------------- helpers ----------------

class _SeedMixin(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")


# ---------------- constants ----------------

class Constants(unittest.TestCase):
    def test_module_types_default(self) -> None:
        self.assertEqual(MODULE_TYPES, ("基础平台", "中间件", "上层应用"))


# ---------------- ensure / read / write ----------------

class ModuleCRUD(_SeedMixin):
    def test_ensure_creates_file(self) -> None:
        md = ensure_modules("demo")
        self.assertEqual(md, {"modules": []})
        self.assertTrue(os.path.exists(os.path.join(self.wp, "modules.json")))

    def test_read_returns_existing(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1"}]})
        md = read_modules("demo")
        self.assertEqual(len(md["modules"]), 1)

    def test_write_atomic(self) -> None:
        # 验证临时文件被替换
        write_modules("demo", {"modules": [{"name": "m2"}]})
        self.assertFalse(os.path.exists(os.path.join(self.wp, "modules.json.tmp")))
        md = json.load(open(os.path.join(self.wp, "modules.json"), encoding="utf-8"))
        self.assertEqual(md["modules"][0]["name"], "m2")


# ---------------- cmd_module ----------------

class CmdModule(_SeedMixin):
    def test_list(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "type": "基础平台", "alive": True, "depends_on": [], "reqs": []}]})
        with mock.patch("statectl_core.modules.acquire_lock") as mlock:
            rc = cmd_module("demo", "list", [])
            self.assertEqual(rc, 0)
        mlock.assert_called_once()

    def test_add(self) -> None:
        with mock.patch("statectl_core.modules.acquire_lock") as mlock:
            rc = cmd_module("demo", "add", ["m1", "基础平台", "模块描述"])
            self.assertEqual(rc, 0)
        md = read_modules("demo")
        self.assertEqual(md["modules"][0]["name"], "m1")
        self.assertEqual(md["modules"][0]["type"], "基础平台")
        self.assertEqual(md["modules"][0]["desc"], "模块描述")

    def test_add_missing_args(self) -> None:
        rc = cmd_module("demo", "add", ["m1"])
        self.assertEqual(rc, 1)

    def test_add_empty_type(self) -> None:
        rc = cmd_module("demo", "add", ["m1", "  "])
        self.assertEqual(rc, 1)

    def test_add_duplicate(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True}]})
        rc = cmd_module("demo", "add", ["m1", "x"])
        self.assertEqual(rc, 1)

    def test_rm_marks_alive_false(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True}]})
        rc = cmd_module("demo", "rm", ["m1"])
        self.assertEqual(rc, 0)
        self.assertFalse(read_modules("demo")["modules"][0]["alive"])

    def test_rm_nonexistent(self) -> None:
        rc = cmd_module("demo", "rm", ["ghost"])
        self.assertEqual(rc, 1)

    def test_dep(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True}]})
        rc = cmd_module("demo", "dep", ["m1", "m2,m3"])
        self.assertEqual(rc, 0)
        self.assertEqual(read_modules("demo")["modules"][0]["depends_on"], ["m2", "m3"])

    def test_dep_missing(self) -> None:
        rc = cmd_module("demo", "dep", ["m1"])
        self.assertEqual(rc, 1)

    def test_dep_module_not_found(self) -> None:
        rc = cmd_module("demo", "dep", ["ghost", "m1"])
        self.assertEqual(rc, 1)

    def test_iter_creates(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True, "iterations": []}]})
        rc = cmd_module("demo", "iter", ["m1", "1,2,3"])
        self.assertEqual(rc, 0)
        its = read_modules("demo")["modules"][0]["iterations"]
        self.assertEqual([x["n"] for x in its], [1, 2, 3])

    def test_iter_dedup(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True,
                                            "iterations": [{"n": 1, "status": "design_pending"}]}]})
        rc = cmd_module("demo", "iter", ["m1", "1,2"])
        self.assertEqual(rc, 0)
        its = read_modules("demo")["modules"][0]["iterations"]
        self.assertEqual([x["n"] for x in its], [1, 2])

    def test_iter_invalid(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True}]})
        rc = cmd_module("demo", "iter", ["m1", "x"])
        self.assertEqual(rc, 1)

    def test_iter_missing(self) -> None:
        rc = cmd_module("demo", "iter", ["ghost", "1"])
        self.assertEqual(rc, 1)

    def test_dispatch(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True, "reqs": []}]})
        with mock.patch("statectl_core.modules.read_status", return_value={
            "demo/R1": {"status": "approved"},
            "demo/R2": {"status": "analyzing"},
        }):
            with mock.patch("statectl_core.modules.write_status"):
                rc = cmd_module("demo", "dispatch", ["m1", "R1,R2"])
                self.assertEqual(rc, 0)
        md = read_modules("demo")
        self.assertIn("R1", md["modules"][0]["reqs"])
        self.assertNotIn("R2", md["modules"][0]["reqs"])  # R2 状态非 approved

    def test_dispatch_nonexistent(self) -> None:
        rc = cmd_module("demo", "dispatch", ["ghost", "R1"])
        self.assertEqual(rc, 1)

    def test_unknown(self) -> None:
        rc = cmd_module("demo", "weird", [])
        self.assertEqual(rc, 1)

    def test_unblock_dispatch(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "alive": True,
                                              "iterations": [{"n": 1, "status": "blocked",
                                                              "claimed": True, "claimed_pid": 1}]}]})
        with mock.patch("statectl_core.modules._module_unblock", return_value=0) as m_unblock:
            rc = cmd_module("demo", "unblock", ["m1", "1"])
            self.assertEqual(rc, 0)
        m_unblock.assert_called_once()


# ---------------- _get_mod_iter ----------------

class GetModIter(_SeedMixin):
    def test_returns_module_and_iter(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1",
                                          "iterations": [{"n": 1, "status": "x"}]}]})
        m, it = _get_mod_iter("demo", "m1", "1")
        self.assertEqual(m["name"], "m1")
        self.assertEqual(it["n"], 1)

    def test_module_missing(self) -> None:
        m, it = _get_mod_iter("demo", "ghost", "1")
        self.assertIsNone(m)
        self.assertIsNone(it)

    def test_iter_missing(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "iterations": []}]})
        m, it = _get_mod_iter("demo", "m1", "9")
        self.assertIsNone(m)
        self.assertIsNone(it)


# ---------------- _module_unblock ----------------

class ModuleUnblock(_SeedMixin):
    def test_unblock_resets(self) -> None:
        write_modules("demo", {"modules": [{
            "name": "m1", "design": {},
            "iterations": [{"n": 1, "status": "blocked", "claimed": True, "claimed_pid": 1,
                            "fix_claimed": True, "failures": 3, "retry_count": 2,
                            "design_retry_count": 1, "case_retry_count": 1,
                            "review_feedback": "f", "design_review_feedback": "df"}]
        }]})
        rc = _module_unblock("demo", "m1", "1")
        self.assertEqual(rc, 0)
        it = read_modules("demo")["modules"][0]["iterations"][0]
        self.assertEqual(it["status"], "design_pending")
        self.assertNotIn("claimed", it)
        self.assertEqual(it["failures"], 0)  # failures 重置
        self.assertEqual(it["retry_count"], 0)
        self.assertNotIn("review_feedback", it)

    def test_non_blocked_returns_1(self) -> None:
        write_modules("demo", {"modules": [{
            "name": "m1", "design": {},
            "iterations": [{"n": 1, "status": "design_working"}]
        }]})
        rc = _module_unblock("demo", "m1", "1")
        self.assertEqual(rc, 1)

    def test_module_missing(self) -> None:
        rc = _module_unblock("demo", "ghost", "1")
        self.assertEqual(rc, 1)


# ---------------- release_module ----------------

class ReleaseModule(_SeedMixin):
    def _seed(self, status="dev_working", **extra) -> dict:
        it = {"n": 1, "status": status, "design_review_feedback": None, "review_feedback": None,
              "case_passed": False}
        it.update(extra)
        return it

    def test_design_done(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="design_working")]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "design", "demo/design/m1/", "DONE")
        self.assertEqual(rc, 0)
        m = read_modules("demo")["modules"][0]
        self.assertIsNotNone(m["design"]["product"])
        self.assertEqual(m["iterations"][0]["status"], "design_reviewing")

    def test_design_pass(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {"reviews": []}, "iterations": [
            self._seed(status="design_reviewing", design_review_claimed_pid=999)]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "design", "demo/r.md", "PASS")
        self.assertEqual(rc, 0)
        it = read_modules("demo")["modules"][0]["iterations"][0]
        self.assertEqual(it["status"], "dev_working")

    def test_design_fail_back_to_retry(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {"reviews": []}, "iterations": [
            self._seed(status="design_reviewing", design_retry_count=0)]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "design", "demo/r.md", "FAIL")
        self.assertEqual(rc, 0)
        it = read_modules("demo")["modules"][0]["iterations"][0]
        self.assertEqual(it["status"], "design_working")
        self.assertEqual(it["design_retry_count"], 1)

    def test_design_fail_3_times_blocks(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {"reviews": []}, "iterations": [
            self._seed(status="design_reviewing", design_retry_count=2)]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "design", "demo/r.md", "FAIL")
        self.assertEqual(rc, 0)
        self.assertEqual(read_modules("demo")["modules"][0]["iterations"][0]["status"], "blocked")

    def test_code_done(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="dev_working")]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "code", "demo/code/", "DONE")
        self.assertEqual(rc, 0)
        self.assertEqual(read_modules("demo")["modules"][0]["iterations"][0]["status"], "dev_reviewing")

    def test_review_pass(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="dev_reviewing", retry_count=0)]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "review", "demo/r.md", "PASS")
        self.assertEqual(rc, 0)
        self.assertEqual(read_modules("demo")["modules"][0]["iterations"][0]["status"], "it_working")

    def test_review_fail_blocks_at_3(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="dev_reviewing", retry_count=2)]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "review", "demo/r.md", "FAIL")
        self.assertEqual(rc, 0)
        self.assertEqual(read_modules("demo")["modules"][0]["iterations"][0]["status"], "blocked")

    def test_case_pass_no_basis_fails(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="it_working")]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "case", "demo/case.md", "PASS")
        self.assertEqual(rc, 1)  # 缺"实现依据"

    def test_case_pass_with_basis(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="it_working")]}]})
        # 写真实的 case 文件（实现依据）
        case_p = os.path.join(self.wp, "case.md")
        with open(case_p, "w") as f:
            f.write("标题\n实现依据：xxx\n其他")
        cm = mock.MagicMock()
        cm.__enter__ = lambda s: s
        cm.__exit__ = lambda s, *a: None
        with mock.patch("statectl_core.modules.acquire_lock", return_value=cm):
            with mock.patch("statectl_core.modules._module_checks", return_value=[]):
                # release_module 用 product_path 解析，源码在 root 解析 demo/case.md
                with mock.patch("statectl_core.pipeline.product_path", return_value=case_p):
                    rc = release_module("demo", "m1", "1", "case", "demo/case.md", "PASS")
        self.assertEqual(rc, 0)
        self.assertTrue(read_modules("demo")["modules"][0]["iterations"][0]["case_passed"])

    def test_case_fail_blocks_at_3(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="it_working", case_retry_count=2)]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_module("demo", "m1", "1", "case", "demo/case.md", "FAIL")
        self.assertEqual(rc, 0)
        self.assertEqual(read_modules("demo")["modules"][0]["iterations"][0]["status"], "blocked")

    def test_it_done_no_opens_passes(self) -> None:
        write_modules("demo", {"modules": [{"name": "m1", "design": {}, "iterations": [
            self._seed(status="it_working")]}]})
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("statectl_core.modules.open_issues", return_value=[]):
                with mock.patch("statectl_core.modules._module_checks", return_value=[]):
                    rc = release_module("demo", "m1", "1", "it", "demo/it/", "DONE")
        self.assertEqual(rc, 0)
        self.assertEqual(read_modules("demo")["modules"][0]["iterations"][0]["status"], "it_passed")

    def test_unknown_action(self) -> None:
        rc = release_module("demo", "m1", "1", "weird", "demo/x", "DONE")
        self.assertEqual(rc, 1)

    def test_missing_product(self) -> None:
        with mock.patch("os.path.exists", return_value=False):
            rc = release_module("demo", "m1", "1", "design", "demo/x", "DONE")
        self.assertEqual(rc, 1)


# ---------------- _module_passed ----------------

class ModulePassed(unittest.TestCase):
    def test_returns_true_if_any_iter_passed(self) -> None:
        md = {"modules": [{"name": "m", "iterations": [{"n": 1, "status": "it_passed"}]}]}
        self.assertTrue(_module_passed(md, "m"))

    def test_returns_false_if_none_passed(self) -> None:
        md = {"modules": [{"name": "m", "iterations": [{"n": 1, "status": "it_working"}]}]}
        self.assertFalse(_module_passed(md, "m"))

    def test_missing_module_returns_true(self) -> None:
        # 已下线模块不阻塞
        self.assertTrue(_module_passed({"modules": []}, "ghost"))


# ---------------- _module_stale_recovery ----------------

class ModuleStaleRecovery(_SeedMixin):
    def test_died_worker_releases_claim(self) -> None:
        md = {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "dev_working", "claimed": True, "claimed_pid": 99999,
             "failures": 0}
        ]}]}
        alarms: list = []
        with mock.patch("statectl_core.modules.pid_alive", return_value=False):
            _module_stale_recovery("demo", md, alarms)
        it = md["modules"][0]["iterations"][0]
        self.assertFalse(it["claimed"])
        self.assertEqual(it["failures"], 1)
        self.assertTrue(any("m1" in a for a in alarms))

    def test_3_failures_blocks(self) -> None:
        md = {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "dev_working", "claimed": True, "claimed_pid": 99999,
             "failures": 2}
        ]}]}
        alarms: list = []
        with mock.patch("statectl_core.modules.pid_alive", return_value=False):
            _module_stale_recovery("demo", md, alarms)
        self.assertEqual(md["modules"][0]["iterations"][0]["status"], "blocked")

    def test_alive_worker_not_touched(self) -> None:
        md = {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "dev_working", "claimed": True, "claimed_pid": 1}
        ]}]}
        with mock.patch("statectl_core.modules.pid_alive", return_value=True):
            _module_stale_recovery("demo", md, [])
        self.assertTrue(md["modules"][0]["iterations"][0]["claimed"])

    def test_review_worker_death_releases_claim(self) -> None:
        md = {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "dev_reviewing", "review_claimed": True, "review_claimed_pid": 99999}
        ]}]}
        alarms: list = []
        with mock.patch("statectl_core.modules.pid_alive", return_value=False):
            _module_stale_recovery("demo", md, alarms)
        self.assertFalse(md["modules"][0]["iterations"][0]["review_claimed"])


# ---------------- _version_stale_recovery ----------------

class VersionStaleRecovery(_SeedMixin):
    def test_arch_worker_died(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev",
                             "arch_claimed": True, "arch_claimed_pid": 99999,
                             "failures": 0}]}
        alarms: list = []
        with mock.patch("statectl_core.modules.pid_alive", return_value=False):
            _version_stale_recovery("demo", vd, alarms)
        self.assertFalse(vd["versions"][0]["arch_claimed"])
        self.assertEqual(vd["versions"][0]["failures"], 1)

    def test_released_skipped(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "released",
                             "arch_claimed": True, "arch_claimed_pid": 99999}]}
        with mock.patch("statectl_core.modules.pid_alive", return_value=False):
            _version_stale_recovery("demo", vd, [])
        self.assertTrue(vd["versions"][0]["arch_claimed"])

    def test_3_failures_blocks(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev",
                             "arch_claimed": True, "arch_claimed_pid": 99999,
                             "failures": 2}]}
        with mock.patch("statectl_core.modules.pid_alive", return_value=False):
            _version_stale_recovery("demo", vd, [])
        self.assertEqual(vd["versions"][0]["status"], "blocked")
        self.assertEqual(vd["versions"][0]["blocked_from"], "in_dev")


# ---------------- _module_inputs ----------------

class ModuleInputs(_SeedMixin):
    def test_lists_req_specs(self) -> None:
        st = {"demo/R1": {"analysis": "需求规格 A"}, "demo/R2": {"analysis": "需求规格 B"}}
        m = {"name": "m1", "reqs": ["R1", "R2"]}
        out = _module_inputs("demo", m, st)
        self.assertIn("R1", out)
        self.assertIn("需求规格 A", out)


# ---------------- _issue_stale_watch ----------------

class IssueStaleWatch(_SeedMixin):
    def test_no_dir_no_op(self) -> None:
        alarms: list = []
        _issue_stale_watch("demo", alarms)
        self.assertEqual(alarms, [])

    def test_open_issue_emits_alarm(self) -> None:
        idir = os.path.join(self.wp, "issues")
        os.makedirs(idir, exist_ok=True)
        # 写一个超老 mtime 的 open 单
        p = os.path.join(idir, "TEST-01.md")
        with open(p, "w") as f:
            f.write("状态：open\n")
        import time
        old = time.time() - 25 * 3600
        os.utime(p, (old, old))
        alarms: list = []
        _issue_stale_watch("demo", alarms)
        self.assertTrue(any("TEST-01" in a for a in alarms))

    def test_closed_issue_skipped(self) -> None:
        idir = os.path.join(self.wp, "issues")
        os.makedirs(idir, exist_ok=True)
        p = os.path.join(idir, "TEST-02.md")
        with open(p, "w") as f:
            f.write("状态：closed\n")
        import time
        old = time.time() - 25 * 3600
        os.utime(p, (old, old))
        alarms: list = []
        _issue_stale_watch("demo", alarms)
        self.assertFalse(any("TEST-02" in a for a in alarms))


# ---------------- _dep_cycle ----------------

class DepCycle(unittest.TestCase):
    def test_no_cycle(self) -> None:
        md = {"modules": [
            {"name": "a", "depends_on": []},
            {"name": "b", "depends_on": ["a"]},
        ]}
        self.assertEqual(_dep_cycle(md, "b"), [])

    def test_direct_cycle(self) -> None:
        md = {"modules": [
            {"name": "a", "depends_on": ["b"]},
            {"name": "b", "depends_on": ["a"]},
        ]}
        cyc = _dep_cycle(md, "a")
        self.assertIn("a", cyc)
        self.assertIn("b", cyc)

    def test_self_dependency(self) -> None:
        # 自依赖，方向规则
        md = {"modules": [{"name": "a", "depends_on": []}]}
        self.assertEqual(_dep_cycle(md, "a"), [])


# ---------------- _se_triage_and_attach ----------------

class SeTriage(_SeedMixin):
    def test_no_opens_no_op(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md = {"modules": []}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker") as m_sw:
            _se_triage_and_attach("demo", vd, md, alarms)
        m_sw.assert_not_called()

    def test_unassigned_issues_spawn_se(self) -> None:
        idir = os.path.join(self.wp, "issues")
        os.makedirs(idir, exist_ok=True)
        with open(os.path.join(idir, "TEST-01.md"), "w") as f:
            f.write("状态：open\n归属模块：待定\n")
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md: dict = {"modules": []}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker", return_value=12345) as m_sw:
            _se_triage_and_attach("demo", vd, md, alarms)
        m_sw.assert_called_once()
        self.assertTrue(vd["versions"][0]["triage_claimed"])
        self.assertEqual(vd["versions"][0]["triage_claimed_pid"], 12345)

    def test_triage_claimed_already_skips_spawn(self) -> None:
        idir = os.path.join(self.wp, "issues")
        os.makedirs(idir, exist_ok=True)
        with open(os.path.join(idir, "TEST-01.md"), "w") as f:
            f.write("状态：open\n归属模块：待定\n")
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev", "triage_claimed": True, "triage_claimed_pid": 99999}]}
        md: dict = {"modules": []}
        with mock.patch("statectl_core.modules.spawn_worker") as m_sw:
            with mock.patch("statectl_core.modules.pid_alive", return_value=True):
                _se_triage_and_attach("demo", vd, md, [])
        m_sw.assert_not_called()

    def test_owned_issues_attached_to_it_working(self) -> None:
        idir = os.path.join(self.wp, "issues")
        os.makedirs(idir, exist_ok=True)
        with open(os.path.join(idir, "TEST-01.md"), "w") as f:
            f.write("状态：open\n归属模块：m1\n")
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "it_working"}
        ]}]}
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker"):
            _se_triage_and_attach("demo", vd, md, alarms)
        it = md["modules"][0]["iterations"][0]
        self.assertIn("TEST-01", it.get("waiting_issues", []))

    def test_owned_issues_reactivate_it_passed(self) -> None:
        idir = os.path.join(self.wp, "issues")
        os.makedirs(idir, exist_ok=True)
        with open(os.path.join(idir, "TEST-02.md"), "w") as f:
            f.write("状态：open\n归属模块：m1\n")
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "it_passed"}
        ]}]}
        vd = {"versions": [{"name": "v1.0.0", "status": "st"}]}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker"):
            _se_triage_and_attach("demo", vd, md, alarms)
        it = md["modules"][0]["iterations"][0]
        self.assertEqual(it["status"], "it_working")
        self.assertIn("TEST-02", it["waiting_issues"])
        # 版本应回到 in_dev
        self.assertEqual(vd["versions"][0]["status"], "in_dev")

    def test_invariant_heal_business_iter(self) -> None:
        # 进行中迭代但版本在 st_done → 应自愈到 in_dev
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "it_working"}
        ]}]}
        vd = {"versions": [{"name": "v1.0.0", "status": "st_done"}]}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker"):
            _se_triage_and_attach("demo", vd, md, alarms)
        self.assertEqual(vd["versions"][0]["status"], "in_dev")


# ---------------- _schedule_module_iter ----------------

class ScheduleModuleIter(_SeedMixin):
    def test_skips_non_in_dev(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "planning"}]}
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "design_pending"}
        ]}]}
        st = {}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker") as m_sw:
            _schedule_module_iter("demo", vd, md, st, alarms)
        m_sw.assert_not_called()

    def test_design_pending_spawns_mde(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "design_pending", "design": {}}
        ]}]}
        st: dict = {}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker", return_value=111) as m_sw:
            _schedule_module_iter("demo", vd, md, st, alarms)
        m_sw.assert_called_once()
        it = md["modules"][0]["iterations"][0]
        self.assertEqual(it["status"], "design_working")
        self.assertTrue(it["claimed"])

    def test_it_working_spawns_mto(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md = {"modules": [{"name": "m1", "alive": True, "design": {},
                            "iterations": [
            {"n": 1, "status": "it_working", "case_passed": False}
        ]}]}
        st: dict = {}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker", return_value=222) as m_sw:
            _schedule_module_iter("demo", vd, md, st, alarms)
        m_sw.assert_called_once()

    def test_it_working_with_issues_spawns_fo_fix(self) -> None:
        idir = os.path.join(self.wp, "issues")
        os.makedirs(idir, exist_ok=True)
        with open(os.path.join(idir, "TEST-01.md"), "w") as f:
            f.write("状态：open\n归属模块：m1\n")
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md = {"modules": [{"name": "m1", "alive": True, "design": {},
                            "iterations": [
            {"n": 1, "status": "it_working", "case_passed": True,
             "it_product": "demo/it/", "waiting_issues": ["TEST-01"]}
        ]}]}
        st: dict = {}
        alarms: list = []
        with mock.patch("statectl_core.modules.spawn_worker", return_value=333) as m_sw:
            _schedule_module_iter("demo", vd, md, st, alarms)
        m_sw.assert_called_once()
        self.assertTrue(md["modules"][0]["iterations"][0].get("fix_claimed"))

    def test_blocked_iter_skipped(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "blocked"}
        ]}]}
        with mock.patch("statectl_core.modules.spawn_worker") as m_sw:
            _schedule_module_iter("demo", vd, md, {}, [])
        m_sw.assert_not_called()

    def test_already_claimed_skipped(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "design_pending", "claimed": True, "design": {}}
        ]}]}
        with mock.patch("statectl_core.modules.spawn_worker") as m_sw:
            _schedule_module_iter("demo", vd, md, {}, [])
        m_sw.assert_not_called()


# ---------------- release_st_v2 ----------------

class ReleaseStV2(_SeedMixin):
    def _lock(self):
        cm = mock.MagicMock()
        cm.__enter__ = lambda s: s
        cm.__exit__ = lambda s, *a: None
        return cm

    def test_done_no_opens(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "st"}]})
        with mock.patch("statectl_core.modules.acquire_lock", return_value=self._lock()):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("statectl_core.qa.open_issues", return_value=[]):
                    rc = release_st_v2("demo", "v1.0.0", "demo/st/", "DONE")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "st_done")

    def test_done_with_opens(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "st"}]})
        with mock.patch("statectl_core.modules.acquire_lock", return_value=self._lock()):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("statectl_core.modules.open_issues", return_value=["T-1"]):
                    rc = release_st_v2("demo", "v1.0.0", "demo/st/", "DONE")
        self.assertEqual(rc, 0)
        self.assertEqual(versions.read_versions("demo")["versions"][0]["status"], "st")

    def test_wrong_status(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "in_dev"}]})
        rc = release_st_v2("demo", "v1.0.0", "demo/st/", "DONE")
        self.assertEqual(rc, 1)


# ---------------- _module_checks ----------------

class ModuleChecks(_SeedMixin):
    def test_no_config_returns_empty(self) -> None:
        self.assertEqual(_module_checks("demo", "m1"), [])

    def test_min_count_violation(self) -> None:
        os.makedirs(os.path.join(self.wp, "code", "m1"), exist_ok=True)
        with open(os.path.join(self.wp, "code", "m1", "main.py"), "w") as f:
            f.write("def f(): pass\n")
        with open(os.path.join(self.wp, "module_checks.json"), "w") as f:
            json.dump({"m1": [{"file": "main.py", "pattern": "watch_dog",
                                "min_count": 2, "why": "TEST"}]}, f)
        fails = _module_checks("demo", "m1")
        self.assertTrue(any("min_count" in str(f) or "匹配" in str(f) for f in fails))

    def test_max_value_violation(self) -> None:
        os.makedirs(os.path.join(self.wp, "code", "m1"), exist_ok=True)
        with open(os.path.join(self.wp, "code", "m1", "cfg.py"), "w") as f:
            f.write("CHUNK = 4096\n")
        with open(os.path.join(self.wp, "module_checks.json"), "w") as f:
            json.dump({"m1": [{"file": "cfg.py", "pattern": r"CHUNK\s*=\s*(\d+)",
                                "max_value": 2048, "why": "TEST"}]}, f)
        fails = _module_checks("demo", "m1")
        self.assertTrue(any("4096" in str(f) for f in fails))

    def test_missing_file(self) -> None:
        with open(os.path.join(self.wp, "module_checks.json"), "w") as f:
            json.dump({"m1": [{"file": "ghost.py", "pattern": "x", "min_count": 1}]}, f)
        fails = _module_checks("demo", "m1")
        self.assertTrue(any("找不到" in str(f) for f in fails))


# ---------------- _mechanism_selftest ----------------

class MechanismSelftest(_SeedMixin):
    def test_empty_state(self) -> None:
        fails = _mechanism_selftest("demo")
        self.assertEqual(fails, [])

    def test_unknown_version_status(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0",
                                           "versions": [{"name": "v1.0.0", "status": "junk"}]})
        fails = _mechanism_selftest("demo")
        self.assertTrue(any("不在可达性表" in f for f in fails))

    def test_invariant_violation(self) -> None:
        # 进行中迭代 + 版本 st_done → 应被检出不变量违反
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "st_done"}]})
        write_modules("demo", {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "it_working"}]}]})
        fails = _mechanism_selftest("demo")
        self.assertTrue(any("不变式违反" in f for f in fails))

    def test_release_pkg_incomplete(self) -> None:
        rel = os.path.join(self.wp, "release", "v1.0.0")
        os.makedirs(rel, exist_ok=True)
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa"}]})
        write_modules("demo", {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "it_passed"}]}]})
        fails = _mechanism_selftest("demo")
        self.assertTrue(any("发布物不完整" in f for f in fails))


if __name__ == "__main__":
    unittest.main()