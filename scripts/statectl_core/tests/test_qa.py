"""Tests for statectl_core.qa: QA 发布 + 用户指南确认/驳回 + ST 调度 + ST 用例 TE 评审。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from statectl_core import qa, versions
from statectl_core.qa import (
    release_qa,
    confirm_guide,
    reject_guide,
    _schedule_st_qa,
    release_st_case,
)
from statectl_core.modules import write_modules
from statectl_core.versions import _sync_project_version

from ._helpers import StatectlTestCase


class _SeedMixin(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")


# ---------------- release_qa ----------------

class ReleaseQa(_SeedMixin):
    def _seed_qa(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa"}]})
        rel = os.path.join(self.wp, "release", "v1.0.0")
        os.makedirs(rel, exist_ok=True)
        # 包内一键脚本
        with open(os.path.join(rel, "install.sh"), "w") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(rel, "uninstall.sh"), "w") as f:
            f.write("#!/bin/sh\n")
        with open(os.path.join(rel, "start.sh"), "w") as f:
            f.write("#!/bin/sh\n")
        # 打包 + sha + 冷启动证据
        import tarfile
        with tarfile.open(os.path.join(rel, "v1.0.0.tar.gz"), "w") as tf:
            for f in ("install.sh", "uninstall.sh", "start.sh"):
                tf.add(os.path.join(rel, f), arcname=f)
        with open(os.path.join(rel, "SHA256SUMS"), "w") as f:
            f.write("deadbeef  v1.0.0.tar.gz\n")
        with open(os.path.join(rel, "可用性自检.md"), "w") as f:
            f.write("全新环境 mktemp -d 冷启动 /api/state 200\n")
        # 模块全 it_passed
        write_modules("demo", {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "it_passed"}]}]})

    def test_done_passes(self) -> None:
        self._seed_qa()
        with mock.patch("statectl_core.qa.product_path", return_value=os.path.join(self.wp, "release", "v1.0.0")):
            with mock.patch("os.path.exists", return_value=True):
                rc = release_qa("demo", "v1.0.0", "demo/release/v1.0.0/", "DONE")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "qa_reviewing")

    def test_selftest_fail(self) -> None:
        # 缺 tar.gz → 自检失败
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa"}]})
        write_modules("demo", {"modules": [{"name": "m1", "iterations": [
            {"n": 1, "status": "it_passed"}]}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_qa("demo", "v1.0.0", "demo/release/v1.0.0/", "DONE")
        self.assertEqual(rc, 1)

    def test_wrong_conclusion(self) -> None:
        rc = release_qa("demo", "v1.0.0", "demo/release/", "PASS")
        self.assertEqual(rc, 1)

    def test_wrong_status(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "in_dev"}]})
        rc = release_qa("demo", "v1.0.0", "demo/release/", "DONE")
        self.assertEqual(rc, 1)

    def test_missing_version(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": []})
        rc = release_qa("demo", "v9.9.9", "demo/release/", "DONE")
        self.assertEqual(rc, 1)

    def test_missing_product(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa"}]})
        with mock.patch("os.path.exists", return_value=False):
            rc = release_qa("demo", "v1.0.0", "demo/release/", "DONE")
        self.assertEqual(rc, 1)


# ---------------- confirm_guide ----------------

class ConfirmGuide(_SeedMixin):
    def test_released_with_dispatch_archive(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa_reviewing", "reqs": ["R1"]}]})
        with mock.patch("statectl_core.qa.read_status", return_value={
            "demo/R1": {"status": "dispatched"}}):
            with mock.patch("statectl_core.qa.write_status"):
                with mock.patch("statectl_core.qa._sync_project_version") as m_sync:
                    rc = confirm_guide("demo", "v1.0.0")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "released")
        self.assertIsNotNone(v.get("released_at"))
        m_sync.assert_called_once_with("demo", "v1.0.0")
        # 归档应已写入
        ap = os.path.join(self.wp, "artifacts", "R1.md")
        self.assertTrue(os.path.exists(ap))

    def test_no_dispatch_no_change(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa_reviewing", "reqs": []}]})
        rc = confirm_guide("demo", "v1.0.0")
        self.assertEqual(rc, 0)

    def test_wrong_status(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa"}]})
        rc = confirm_guide("demo", "v1.0.0")
        self.assertEqual(rc, 1)

    def test_missing_version(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": []})
        rc = confirm_guide("demo", "v9.9.9")
        self.assertEqual(rc, 1)


# ---------------- reject_guide ----------------

class RejectGuide(_SeedMixin):
    def test_reject(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa_reviewing", "qa_claimed": True}]})
        rc = reject_guide("demo", "v1.0.0", "用户指南遗漏章节")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "qa")
        self.assertFalse(v["qa_claimed"])
        self.assertEqual(v["guide_reject_reason"], "用户指南遗漏章节")

    def test_wrong_status(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "qa"}]})
        rc = reject_guide("demo", "v1.0.0", "x")
        self.assertEqual(rc, 1)


# ---------------- _schedule_st_qa ----------------

class ScheduleStQa(_SeedMixin):
    def test_in_dev_full_iter_spawns_sto(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "in_dev"}]}
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "it_passed", "it_report": "demo/it/report.md"}]}]}
        st: dict = {}
        alarms: list = []
        with mock.patch("statectl_core.qa.spawn_worker", return_value=11) as m_sw:
            _schedule_st_qa("demo", vd, md, st, alarms)
        m_sw.assert_called_once()
        self.assertEqual(vd["versions"][0]["status"], "st")
        self.assertTrue(vd["versions"][0]["st_claimed"])

    def test_already_claimed_skips(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "st", "st_claimed": True,
                             "st_claimed_pid": 99999}]}
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "it_passed"}]}]}
        with mock.patch("statectl_core.qa.spawn_worker") as m_sw:
            with mock.patch("statectl_core.modules.pid_alive", return_value=True):
                _schedule_st_qa("demo", vd, md, {}, [])
        m_sw.assert_not_called()

    def test_st_done_spawns_qa(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "st_done"}]}
        md: dict = {"modules": []}
        alarms: list = []
        with mock.patch("statectl_core.qa.spawn_worker", return_value=22) as m_sw:
            _schedule_st_qa("demo", vd, md, {}, alarms)
        m_sw.assert_called_once()
        self.assertEqual(vd["versions"][0]["status"], "qa")

    def test_qa_reviewing_skipped(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "qa_reviewing"}]}
        md: dict = {"modules": []}
        with mock.patch("statectl_core.qa.spawn_worker") as m_sw:
            _schedule_st_qa("demo", vd, md, {}, [])
        m_sw.assert_not_called()

    def test_released_skipped(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "released"}]}
        md: dict = {"modules": []}
        with mock.patch("statectl_core.qa.spawn_worker") as m_sw:
            _schedule_st_qa("demo", vd, md, {}, [])
        m_sw.assert_not_called()

    def test_st_pending_full_iter_spawns_sto(self) -> None:
        vd = {"versions": [{"name": "v1.0.0", "status": "st_pending"}]}
        md = {"modules": [{"name": "m1", "alive": True, "iterations": [
            {"n": 1, "status": "it_passed"}]}]}
        alarms: list = []
        with mock.patch("statectl_core.qa.spawn_worker", return_value=33) as m_sw:
            _schedule_st_qa("demo", vd, md, {}, alarms)
        m_sw.assert_called_once()


# ---------------- release_st_case ----------------

class ReleaseStCase(_SeedMixin):
    def _lock(self):
        cm = mock.MagicMock()
        cm.__enter__ = lambda s: s
        cm.__exit__ = lambda s, *a: None
        return cm

    def test_pass_no_basis_fails(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "st"}]})
        case_p = os.path.join(self.wp, "st-case-no-basis.md")
        with open(case_p, "w") as f:
            f.write("用例：无任何依据字段的文档")
        with mock.patch("statectl_core.qa.acquire_lock", return_value=self._lock()):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("statectl_core.qa.product_path", return_value=case_p):
                    rc = release_st_case("demo", "v1.0.0", "demo/st/case.md", "PASS")
        self.assertEqual(rc, 1)

    def test_pass_with_basis(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "st"}]})
        case_p = os.path.join(self.wp, "st-case.md")
        with open(case_p, "w") as f:
            f.write("标题\n实现依据：xxx\n")
        with mock.patch("statectl_core.qa.acquire_lock", return_value=self._lock()):
            with mock.patch("os.path.exists", return_value=True):
                with mock.patch("statectl_core.qa.product_path", return_value=case_p):
                    rc = release_st_case("demo", "v1.0.0", "demo/st/case.md", "PASS")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertTrue(v["st_case_passed"])

    def test_fail_no_basis_check(self) -> None:
        # FAIL 不需要门禁
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "st"}]})
        with mock.patch("os.path.exists", return_value=True):
            rc = release_st_case("demo", "v1.0.0", "demo/st/case.md", "FAIL")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertFalse(v["st_case_passed"])

    def test_bad_conclusion(self) -> None:
        rc = release_st_case("demo", "v1.0.0", "demo/st/case.md", "DONE")
        self.assertEqual(rc, 1)

    def test_missing_version(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": []})
        rc = release_st_case("demo", "v9.9.9", "demo/st/case.md", "PASS")
        self.assertEqual(rc, 1)

    def test_missing_product(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": [
            {"name": "v1.0.0", "status": "st"}]})
        with mock.patch("os.path.exists", return_value=False):
            rc = release_st_case("demo", "v1.0.0", "demo/st/case.md", "PASS")
        self.assertEqual(rc, 1)


# ---------------- _sync_project_version ----------------

class SyncProjectVersion(unittest.TestCase):
    def test_updates_latest_version(self) -> None:
        from statectl_core import paths
        # 临时改 PROJECTS_FILE 写表
        original = paths.PROJECTS_FILE
        import tempfile, json
        with tempfile.TemporaryDirectory() as td:
            paths.PROJECTS_FILE = os.path.join(td, "projects.json")
            json.dump({"projects": [{"name": "demo"}]}, open(paths.PROJECTS_FILE, "w"))
            _sync_project_version("demo", "v1.0.0")
            data = json.load(open(paths.PROJECTS_FILE))
            self.assertEqual(data["projects"][0]["latest_version"], "v1.0.0")
            paths.PROJECTS_FILE = original


if __name__ == "__main__":
    unittest.main()