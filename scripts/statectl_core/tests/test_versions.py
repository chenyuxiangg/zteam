"""Tests for statectl_core.versions: 版本状态机 + IT/ST 调度 + 规格确认/驳回。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from statectl_core import paths, versions
from statectl_core.versions import (
    VERSIONS_FILE,
    VERSION_FLOW,
    _advance_v2,
    _claims_sig,
    _it_inputs,
    _parse_req_meta,
    _schedule_it_st,
    _version_guard_watch,
    advance_current,
    advance_versions,
    cmd_confirm,
    cmd_reject,
    ensure_versions,
    read_versions,
    release_it,
    release_st,
    versions_path,
    write_versions,
)

from ._helpers import StatectlTestCase


class _SeedProject(StatectlTestCase):
    """登记 demo 项目并返回 work_path。"""

    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")


# ---------------- 文件级辅助 ----------------

class VersionsPath(unittest.TestCase):
    def test_joins_project_dir(self) -> None:
        # project_dir 走映射表，未登记回退 workspace/<proj>
        self.assertTrue(versions_path("foo").endswith(os.path.join("workspace", "foo", VERSIONS_FILE)))


class VersionFlowTable(unittest.TestCase):
    def test_terminal_states(self) -> None:
        self.assertEqual(VERSION_FLOW["released"]["channel"], {"term"})
        self.assertEqual(VERSION_FLOW["blocked"]["channel"], {"wait_user"})

    def test_arch_has_stuck_fallback(self) -> None:
        # arch 死状态有 stuck=planning（兜底回退落点）
        self.assertEqual(VERSION_FLOW["arch"].get("stuck"), "planning")

    def test_qa_reviewing_is_wait_user(self) -> None:
        # 防止 v2 卡死误报（_version_guard_watch 跳过 wait_user）
        self.assertEqual(VERSION_FLOW["qa_reviewing"]["channel"], {"wait_user"})


# ---------------- _claims_sig ----------------

class ClaimsSig(unittest.TestCase):
    def test_all_false_returns_empty_pipe(self) -> None:
        v = {"arch_claimed": False, "arch_review_claimed": False, "test_plan_claimed": False,
             "testplan_review_claimed": False, "st_claimed": False, "qa_claimed": False}
        self.assertEqual(_claims_sig(v), "False|False|False|False|False|False")

    def test_mixed_returns_truthy(self) -> None:
        v = {"arch_claimed": True}
        sig = _claims_sig(v)
        self.assertIn("True", sig)
        # 第一段 True（arch_claimed=1），其余 False
        self.assertEqual(sig.split("|")[0], "True")


# ---------------- ensure_versions / read_versions / write_versions ----------------

class EnsureVersions(_SeedProject):
    def test_first_call_creates_default_v1(self) -> None:
        vd = ensure_versions("demo")
        self.assertEqual(vd["current"], "v1.0.0")
        self.assertEqual(len(vd["versions"]), 1)
        v = vd["versions"][0]
        self.assertEqual(v["name"], "v1.0.0")
        self.assertEqual(v["status"], "planning")
        self.assertEqual(v["iterations"][0]["n"], 1)
        # 字段补齐（首次创建仅含基础字段；v2 扩展字段在二次读时补齐）
        self.assertIn("st_product", v)
        self.assertIn("released_at", v)

    def test_creates_versions_json_file(self) -> None:
        ensure_versions("demo")
        self.assertTrue(os.path.exists(versions_path("demo")))

    def test_read_returns_same_dict(self) -> None:
        vd = ensure_versions("demo")
        # 写入后再读 → 内容一致
        write_versions("demo", {"current": "v2.0.0", "versions": []})
        self.assertEqual(read_versions("demo"), {"current": "v2.0.0", "versions": []})

    def test_old_iteration_int_migrates_to_objects(self) -> None:
        # 写入 v1 旧格式（iterations=[1,2]）
        write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{
                "name": "v1.0.0", "status": "in_dev", "reqs": ["REQ-1"], "released_at": None,
                "iterations": [1, 2],
            }],
        })
        vd = ensure_versions("demo")
        iters = vd["versions"][0]["iterations"]
        self.assertEqual(len(iters), 2)
        self.assertEqual(iters[0], {"n": 1, "status": "pending", "reqs": [],
                                    "it_product": None, "it_reviews": []})
        self.assertEqual(iters[1]["n"], 2)

    def test_migration_persists_immediately(self) -> None:
        # 迁移后立即落盘（防只内存迁移）
        write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{
                "name": "v1.0.0", "status": "in_dev", "reqs": [],
                "iterations": [1],
            }],
        })
        ensure_versions("demo")
        with open(versions_path("demo"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data["versions"][0]["iterations"][0], dict)

    def test_corrupt_json_falls_back_to_init(self) -> None:
        with open(versions_path("demo"), "w") as f:
            f.write("not-json{")
        vd = ensure_versions("demo")
        # 不抛异常，返回默认
        self.assertEqual(vd["current"], "v1.0.0")


# ---------------- advance_current ----------------

class AdvanceCurrent(_SeedProject):
    def test_returns_current_when_not_released(self) -> None:
        self.assertEqual(advance_current("demo"), "v1.0.0")

    def test_creates_new_version_when_current_released(self) -> None:
        write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "released",
                          "iterations": [], "reqs": [], "released_at": "now"}],
        })
        new = advance_current("demo")
        self.assertEqual(new, "v1.1.0")
        vd = read_versions("demo")
        self.assertEqual(vd["current"], "v1.1.0")
        self.assertEqual(len(vd["versions"]), 2)
        self.assertEqual(vd["versions"][1]["status"], "planning")

    def test_avoids_name_collision(self) -> None:
        write_versions("demo", {
            "current": "v1.5.0",
            "versions": [
                {"name": "v1.5.0", "status": "released", "iterations": [], "reqs": [], "released_at": "x"},
                {"name": "v1.6.0", "status": "released", "iterations": [], "reqs": [], "released_at": "x"},
            ],
        })
        new = advance_current("demo")
        self.assertEqual(new, "v1.7.0")


# ---------------- _parse_req_meta ----------------

class ParseReqMeta(unittest.TestCase):
    def _write(self, content: str) -> str:
        import tempfile
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return f.name

    def test_frontmatter_kv(self) -> None:
        p = self._write("---\nversion: v2.0.0\niteration: 3\ndepends_on: REQ-1, REQ-2\n---\n# body\n")
        meta = _parse_req_meta(p)
        self.assertEqual(meta["version"], "v2.0.0")
        self.assertEqual(meta["iteration"], 3)
        self.assertEqual(meta["depends_on"], ["REQ-1", "REQ-2"])

    def test_hash_comment_kv(self) -> None:
        p = self._write("# version: v1.0.0\n# iteration: 2\n# depends_on: REQ-1\n")
        meta = _parse_req_meta(p)
        self.assertEqual(meta["version"], "v1.0.0")
        self.assertEqual(meta["iteration"], 2)
        self.assertEqual(meta["depends_on"], ["REQ-1"])

    def test_missing_keys_return_defaults(self) -> None:
        p = self._write("# just a title\n\nbody\n")
        meta = _parse_req_meta(p)
        self.assertEqual(meta, {"version": None, "iteration": None, "depends_on": []})

    def test_invalid_iteration_ignored(self) -> None:
        p = self._write("# iteration: abc\n")
        self.assertIsNone(_parse_req_meta(p)["iteration"])

    def test_missing_file_returns_defaults(self) -> None:
        meta = _parse_req_meta("/nonexistent/path.md")
        self.assertEqual(meta, {"version": None, "iteration": None, "depends_on": []})


# ---------------- advance_versions ----------------

class AdvanceVersions(_SeedProject):
    def test_all_released_promotes_version(self) -> None:
        # v1 含两个需求，都 released → 版本 released
        write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "in_dev", "reqs": ["REQ-1", "REQ-2"],
                          "iterations": [], "released_at": None}],
        })
        st = {
            "demo/REQ-1": {"status": "released"},
            "demo/REQ-2": {"status": "released"},
        }
        advance_versions("demo", st)
        vd = read_versions("demo")
        self.assertEqual(vd["versions"][0]["status"], "released")
        self.assertIsNotNone(vd["versions"][0]["released_at"])

    def test_partial_released_no_promote(self) -> None:
        write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "in_dev", "reqs": ["REQ-1", "REQ-2"],
                          "iterations": [], "released_at": None}],
        })
        st = {"demo/REQ-1": {"status": "released"}, "demo/REQ-2": {"status": "approved"}}
        advance_versions("demo", st)
        vd = read_versions("demo")
        self.assertEqual(vd["versions"][0]["status"], "in_dev")

    def test_already_released_skipped(self) -> None:
        write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "released", "reqs": ["REQ-1"],
                          "iterations": [], "released_at": "earlier"}],
        })
        st = {"demo/REQ-1": {"status": "released"}}
        advance_versions("demo", st)
        # released_at 不被覆盖
        vd = read_versions("demo")
        self.assertEqual(vd["versions"][0]["released_at"], "earlier")


# ---------------- _it_inputs ----------------

class ItInputs(unittest.TestCase):
    def test_routes_each_req(self) -> None:
        st = {"demo/REQ-1": {"status": "test_done",
                              "stages": {"code": {"product": "demo/code/REQ-1-r1/"},
                                          "test": {"product": "demo/tests/REQ-1-r1/"}}},
              "demo/REQ-2": {"status": "approved", "stages": {}}}
        s = _it_inputs("demo", ["REQ-1", "REQ-2"], st)
        self.assertIn("REQ-1", s)
        self.assertIn("demo/code/REQ-1-r1/", s)
        self.assertIn("demo/tests/REQ-1-r1/", s)
        self.assertIn("REQ-2", s)
        self.assertIn("?", s)  # REQ-2 缺产物 → "?"


# ---------------- _schedule_it_st ----------------

class ScheduleItSt(_SeedProject):
    def _seed_v(self, **over) -> dict:
        base = {"name": "v1.0.0", "status": "in_dev", "iterations": [
            {"n": 1, "status": "pending", "reqs": ["REQ-1"], "it_claimed": False}],
                "reqs": ["REQ-1"], "st_claimed": False}
        base.update(over)
        return base

    def test_spawns_it_when_all_reqs_done(self) -> None:
        v = self._seed_v()
        st = {"demo/REQ-1": {"status": "test_done"}}
        with mock.patch("statectl_core.versions.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.versions.write_versions"):
            m_spawn.return_value = 12345
            alarms: list = []
            _schedule_it_st("demo", {"versions": [v]}, st, alarms)
        self.assertTrue(v["iterations"][0]["it_claimed"])
        self.assertEqual(v["iterations"][0]["status"], "it_pending")
        m_spawn.assert_called_once()
        # 角色 = it-designer
        args = m_spawn.call_args
        self.assertEqual(args[0][0], "it-designer")
        self.assertTrue(any("it-designer" in str(a) for a in args.args))
        self.assertTrue(len(alarms) >= 1)

    def test_no_spawn_when_reqs_not_done(self) -> None:
        v = self._seed_v()
        st = {"demo/REQ-1": {"status": "plan_reviewing"}}
        with mock.patch("statectl_core.versions.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.versions.write_versions"):
            _schedule_it_st("demo", {"versions": [v]}, st, [])
        m_spawn.assert_not_called()
        self.assertFalse(v["iterations"][0]["it_claimed"])

    def test_no_spawn_when_already_claimed(self) -> None:
        v = self._seed_v()
        v["iterations"][0]["it_claimed"] = True
        st = {"demo/REQ-1": {"status": "test_done"}}
        with mock.patch("statectl_core.versions.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.versions.write_versions"):
            _schedule_it_st("demo", {"versions": [v]}, st, [])
        m_spawn.assert_not_called()

    def test_spawns_st_when_pending(self) -> None:
        v = self._seed_v(status="st_pending", st_claimed=False,
                         iterations=[{"n": 1, "status": "it_passed", "reqs": ["REQ-1"],
                                       "it_product": "demo/it/iter-1/"}])
        with mock.patch("statectl_core.versions.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.versions.write_versions"):
            m_spawn.return_value = 99
            alarms: list = []
            _schedule_it_st("demo", {"versions": [v]}, {}, alarms)
        self.assertTrue(v["st_claimed"])
        m_spawn.assert_called_once()
        # 角色 = st-tester
        self.assertEqual(m_spawn.call_args.args[0], "st-tester")

    def test_no_st_when_already_claimed(self) -> None:
        v = self._seed_v(status="st_pending", st_claimed=True)
        with mock.patch("statectl_core.versions.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.versions.write_versions"):
            _schedule_it_st("demo", {"versions": [v]}, {}, [])
        m_spawn.assert_not_called()


# ---------------- _advance_v2 ----------------

class AdvanceV2(_SeedProject):
    def test_all_it_passed_promotes_to_st_pending(self) -> None:
        v = {"name": "v1.0.0", "status": "in_dev",
             "iterations": [{"n": 1, "status": "it_passed", "reqs": ["REQ-1"]}]}
        with mock.patch("statectl_core.versions.write_versions"):
            _advance_v2("demo", {"versions": [v]}, {}, [])
        self.assertEqual(v["status"], "st_pending")
        self.assertFalse(v.get("st_claimed", True))

    def test_partial_it_passed_no_promote(self) -> None:
        v = {"name": "v1.0.0", "status": "in_dev",
             "iterations": [{"n": 1, "status": "it_passed", "reqs": ["REQ-1"]},
                             {"n": 2, "status": "pending", "reqs": ["REQ-2"]}]}
        _advance_v2("demo", {"versions": [v]}, {}, [])
        self.assertEqual(v["status"], "in_dev")

    def test_released_skipped(self) -> None:
        v = {"name": "v1.0.0", "status": "released",
             "iterations": [{"n": 1, "status": "it_passed", "reqs": ["REQ-1"]}]}
        _advance_v2("demo", {"versions": [v]}, {}, [])
        self.assertEqual(v["status"], "released")

    def test_no_iters_skipped(self) -> None:
        v = {"name": "v1.0.0", "status": "in_dev", "iterations": []}
        _advance_v2("demo", {"versions": [v]}, {}, [])
        self.assertEqual(v["status"], "in_dev")


# ---------------- _version_guard_watch ----------------

class VersionGuardWatch(_SeedProject):
    def test_arch_dead_state_self_corrects(self) -> None:
        v = {"name": "v1.0.0", "status": "arch", "arch_claimed": False}
        alarms: list = []
        _version_guard_watch("demo", {"versions": [v]}, alarms)
        self.assertEqual(v["status"], "planning")
        self.assertEqual(v["arch_failures"], 1)
        self.assertTrue(any("arch" in a for a in alarms))

    def test_unknown_state_alarms_but_no_crash(self) -> None:
        v = {"name": "v1.0.0", "status": "st_passed"}  # 离开可达性表
        alarms: list = []
        _version_guard_watch("demo", {"versions": [v]}, alarms)
        self.assertTrue(any("不在可达性表" in a for a in alarms))

    def test_in_dev_skipped_no_stuck(self) -> None:
        # in_dev 是开发期长驻状态，不算滞留（防误报）
        v = {"name": "v1.0.0", "status": "in_dev"}
        alarms: list = []
        # 跑 20 次：sig 不变但因 status=in_dev 直接跳过
        for _ in range(20):
            _version_guard_watch("demo", {"versions": [v]}, alarms)
        self.assertEqual(v["status"], "in_dev")
        self.assertEqual(alarms, [])

    def test_wait_user_not_counted_as_stuck(self) -> None:
        # qa_reviewing/blocked 是 wait_user，连续 12 tick 不报
        v = {"name": "v1.0.0", "status": "qa_reviewing"}
        alarms: list = []
        for _ in range(15):
            _version_guard_watch("demo", {"versions": [v]}, alarms)
        self.assertEqual(alarms, [])

    def test_stuck_after_12_ticks_no_worker(self) -> None:
        # planning：claims 全空，无 worker，channel 含 auto_sched
        # ——但 12 tick 后若仍未推进，会告警（auto_sched 仍判滞留）
        v = {"name": "v1.0.0", "status": "planning",
             "arch_claimed": False, "arch_review_claimed": False,
             "test_plan_claimed": False, "testplan_review_claimed": False,
             "st_claimed": False, "qa_claimed": False}
        alarms: list = []
        # 跑 13 次：第 13 次时 ticks 累积到 12，触发告警
        for _ in range(13):
            _version_guard_watch("demo", {"versions": [v]}, alarms)
        self.assertTrue(any("疑似卡死" in a for a in alarms))


# ---------------- release_it ----------------

class ReleaseIt(_SeedProject):
    def test_pass_marks_it_passed(self) -> None:
        write_versions("demo", {"current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "st_pending",
                          "iterations": [{"n": 1, "status": "it_pending", "reqs": ["REQ-1"],
                                          "it_claimed": True, "it_product": None, "it_reviews": []}],
                          "reqs": ["REQ-1"]}]})
        prod = os.path.join(self.wp, "it", "iter-1")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "report.md"), "w") as f:
            f.write("IT PASS")
        rc = release_it("demo", "v1.0.0", "1", "demo/it/iter-1/", "PASS")
        self.assertEqual(rc, 0)
        it = read_versions("demo")["versions"][0]["iterations"][0]
        self.assertEqual(it["status"], "it_passed")
        self.assertEqual(it["it_product"], "demo/it/iter-1/")

    def test_fail_resets_to_pending_and_unclaims(self) -> None:
        write_versions("demo", {"current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "st_pending",
                          "iterations": [{"n": 1, "status": "it_pending", "reqs": ["REQ-1"],
                                          "it_claimed": True, "it_product": None, "it_reviews": []}],
                          "reqs": ["REQ-1"]}]})
        prod = os.path.join(self.wp, "it", "iter-1")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "report.md"), "w") as f:
            f.write("IT FAIL")
        rc = release_it("demo", "v1.0.0", "1", "demo/it/iter-1/", "FAIL")
        self.assertEqual(rc, 0)
        it = read_versions("demo")["versions"][0]["iterations"][0]
        self.assertEqual(it["status"], "it_pending")
        self.assertFalse(it["it_claimed"])

    def test_invalid_conclusion_returns_1(self) -> None:
        self.assertEqual(release_it("demo", "v1.0.0", "1", "any", "MAYBE"), 1)

    def test_missing_product_returns_1(self) -> None:
        write_versions("demo", {"current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "st_pending",
                          "iterations": [{"n": 1, "status": "it_pending", "reqs": []}]}]})
        self.assertEqual(release_it("demo", "v1.0.0", "1", "demo/it/none/", "PASS"), 1)

    def test_unknown_version_returns_1(self) -> None:
        write_versions("demo", {"current": "v1.0.0", "versions": []})
        self.assertEqual(release_it("demo", "v9.9.9", "1", "any", "PASS"), 1)

    def test_unknown_iter_returns_1(self) -> None:
        write_versions("demo", {"current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "iterations": [{"n": 1, "reqs": []}]}]})
        self.assertEqual(release_it("demo", "v1.0.0", "9", "any", "PASS"), 1)


# ---------------- release_st ----------------

class ReleaseSt(_SeedProject):
    def test_pass_marks_st_passed(self) -> None:
        write_versions("demo", {"current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "st_pending", "st_claimed": True,
                          "iterations": [], "reqs": []}]})
        prod = os.path.join(self.wp, "st", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "report.md"), "w") as f:
            f.write("ST PASS")
        rc = release_st("demo", "v1.0.0", "demo/st/v1.0.0/", "PASS")
        self.assertEqual(rc, 0)
        v = read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "st_passed")

    def test_fail_resets_to_st_pending_and_unclaims(self) -> None:
        write_versions("demo", {"current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "st_pending", "st_claimed": True,
                          "iterations": [], "reqs": []}]})
        prod = os.path.join(self.wp, "st", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "report.md"), "w") as f:
            f.write("ST FAIL")
        rc = release_st("demo", "v1.0.0", "demo/st/v1.0.0/", "FAIL")
        self.assertEqual(rc, 0)
        v = read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "st_pending")
        self.assertFalse(v["st_claimed"])

    def test_invalid_conclusion_returns_1(self) -> None:
        self.assertEqual(release_st("demo", "v1.0.0", "any", "MAYBE"), 1)

    def test_missing_product_returns_1(self) -> None:
        write_versions("demo", {"current": "v1.0.0",
            "versions": [{"name": "v1.0.0", "status": "st_pending", "iterations": []}]})
        self.assertEqual(release_st("demo", "v1.0.0", "demo/st/none/", "PASS"), 1)

    def test_unknown_version_returns_1(self) -> None:
        write_versions("demo", {"current": "v1.0.0", "versions": []})
        self.assertEqual(release_st("demo", "v9.9.9", "any", "PASS"), 1)


# ---------------- cmd_confirm ----------------

class CmdConfirm(_SeedProject):
    def test_legal_state_transitions_to_approved(self) -> None:
        # 创建规格产物
        prod = os.path.join(self.wp, "analysis", "REQ-1-r1.md")
        os.makedirs(os.path.dirname(prod), exist_ok=True)
        with open(prod, "w") as f:
            f.write("规格")
        st = {"demo/REQ-1": {"status": "awaiting_user_confirm",
                                "analysis": "demo/analysis/REQ-1-r1.md"}}
        with mock.patch("statectl_core.versions.read_status", return_value=st), \
             mock.patch("statectl_core.versions.write_status"), \
             mock.patch("statectl_core.versions.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = cmd_confirm("demo/REQ-1")
        self.assertEqual(rc, 0)
        self.assertEqual(st["demo/REQ-1"]["status"], "approved")
        self.assertIn("approved_at", st["demo/REQ-1"])

    def test_wrong_state_returns_1(self) -> None:
        st = {"demo/REQ-1": {"status": "analyzing"}}
        with mock.patch("statectl_core.versions.read_status", return_value=st), \
             mock.patch("statectl_core.versions.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = cmd_confirm("demo/REQ-1")
        self.assertEqual(rc, 1)

    def test_missing_req_returns_1(self) -> None:
        with mock.patch("statectl_core.versions.read_status", return_value={}), \
             mock.patch("statectl_core.versions.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(cmd_confirm("demo/REQ-1"), 1)

    def test_missing_product_returns_1(self) -> None:
        st = {"demo/REQ-1": {"status": "awaiting_user_confirm",
                              "analysis": "demo/analysis/none.md"}}
        with mock.patch("statectl_core.versions.read_status", return_value=st), \
             mock.patch("statectl_core.versions.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(cmd_confirm("demo/REQ-1"), 1)


# ---------------- cmd_reject ----------------

class CmdReject(_SeedProject):
    def test_legal_state_transitions_to_analyzing(self) -> None:
        st = {"demo/REQ-1": {"status": "awaiting_user_confirm"}}
        with mock.patch("statectl_core.versions.read_status", return_value=st), \
             mock.patch("statectl_core.versions.write_status"), \
             mock.patch("statectl_core.versions.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = cmd_reject("demo/REQ-1", "需求不清晰")
        self.assertEqual(rc, 0)
        self.assertEqual(st["demo/REQ-1"]["status"], "analyzing")
        self.assertEqual(st["demo/REQ-1"]["reject_reason"], "需求不清晰")

    def test_empty_reason_returns_1(self) -> None:
        self.assertEqual(cmd_reject("demo/REQ-1", "   "), 1)

    def test_wrong_state_returns_1(self) -> None:
        st = {"demo/REQ-1": {"status": "analyzing"}}
        with mock.patch("statectl_core.versions.read_status", return_value=st), \
             mock.patch("statectl_core.versions.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(cmd_reject("demo/REQ-1", "理由"), 1)

    def test_missing_req_returns_1(self) -> None:
        with mock.patch("statectl_core.versions.read_status", return_value={}), \
             mock.patch("statectl_core.versions.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(cmd_reject("demo/REQ-1", "理由"), 1)


if __name__ == "__main__":
    unittest.main()