"""Tests for statectl_core.release: 下半部 release_* 系列。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from statectl_core import paths, release
from statectl_core.model_config import DEFAULT_MAX_ROUNDS
from statectl_core.release import (
    release_analyze,
    release_gate,
    release_release,
    release_review,
    release_stage_design,
    release_stage_review,
)

from ._helpers import StatectlTestCase


def _seed_project(self) -> str:
    """StatectlTestCase 派生：登记 demo 项目并返回 work_path。"""
    return self.make_project("demo")


class ReleaseAnalyze(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = _seed_project(self)
        os.makedirs(os.path.join(self.wp, "analysis"), exist_ok=True)

    def test_analyze_requires_analyzing_state(self) -> None:
        e = {"status": "pending", "stages": {}, "round": 0}
        with mock.patch("statectl_core.release.read_status", return_value={"demo/REQ-1": e}), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_analyze("demo/REQ-1", "demo/analysis/REQ-1-r1.md")
        self.assertEqual(rc, 1)

    def test_analyze_transitions_to_awaiting_user_confirm(self) -> None:
        # 写产物
        prod = os.path.join(self.wp, "analysis", "REQ-1-r1.md")
        with open(prod, "w") as f:
            f.write("分析报告")
        e = {"status": "analyzing", "stages": {}, "round": 0, "claimed_by": "pm"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status") as m_write, \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_analyze("demo/REQ-1", "demo/analysis/REQ-1-r1.md")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "awaiting_user_confirm")
        self.assertEqual(e["analysis"], "demo/analysis/REQ-1-r1.md")
        self.assertNotIn("claimed_by", e)
        m_write.assert_called()

    def test_missing_product_triggers_rollback(self) -> None:
        # 不创建产物 → rollback_entry 应被调用
        e = {"status": "analyzing", "stages": {}, "round": 0, "claimed_by": "pm"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status") as m_write, \
             mock.patch("statectl_core.release.rollback_entry") as m_roll, \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_analyze("demo/REQ-1", "demo/analysis/REQ-1-r1.md")
        self.assertEqual(rc, 1)
        m_roll.assert_called()


class ReleaseReview(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = _seed_project(self)
        os.makedirs(os.path.join(self.wp, "review"), exist_ok=True)

    def _write_product(self) -> str:
        p = os.path.join(self.wp, "review", "REQ-1-r1.md")
        with open(p, "w") as f:
            f.write("评审意见")
        return "demo/review/REQ-1-r1.md"

    def test_invalid_conclusion_returns_1(self) -> None:
        self.assertEqual(release_review("demo/REQ-1", "any.md", "MAYBE"), 1)

    def test_pass_approves_entry(self) -> None:
        prod = self._write_product()
        e = {"status": "reviewing", "stages": {}, "round": 0, "claimed_by": "req-reviewer",
             "max_rounds": DEFAULT_MAX_ROUNDS}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.write_artifact"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_review("demo/REQ-1", prod, "PASS")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "approved")
        self.assertEqual(e["round"], 1)
        self.assertEqual(e["reviews"], [prod])

    def test_fail_below_max_rounds_returns_needs_fix(self) -> None:
        prod = self._write_product()
        e = {"status": "reviewing", "stages": {}, "round": 0, "claimed_by": "req-reviewer",
             "max_rounds": 3}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_review("demo/REQ-1", prod, "FAIL")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "needs_fix")
        self.assertEqual(e["round"], 1)

    def test_fail_at_max_rounds_forces_approved(self) -> None:
        prod = self._write_product()
        e = {"status": "reviewing", "stages": {}, "round": 2, "claimed_by": "req-reviewer",
             "max_rounds": 3}  # round==3 后 FAIL → 强制归档
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.write_artifact"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_review("demo/REQ-1", prod, "FAIL")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "approved")
        self.assertTrue(e["forced"])

    def test_non_reviewing_state_returns_1(self) -> None:
        e = {"status": "pending", "stages": {}, "round": 0}
        with mock.patch("statectl_core.release.read_status", return_value={"demo/REQ-1": e}), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_review("demo/REQ-1", "demo/review/x.md", "PASS")
        self.assertEqual(rc, 1)

    def test_missing_product_rolls_back(self) -> None:
        e = {"status": "reviewing", "stages": {}, "round": 0, "claimed_by": "req-reviewer"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.rollback_entry") as m_roll, \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_review("demo/REQ-1", "demo/review/none.md", "PASS")
        self.assertEqual(rc, 1)
        m_roll.assert_called()


class ReleaseStageDesign(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = _seed_project(self)
        os.makedirs(os.path.join(self.wp, "plans"), exist_ok=True)

    def test_design_requires_product(self) -> None:
        e = {"status": "plan_designing", "stages": {}, "claimed_by": "dev-plan-designer"}
        st = {"demo/REQ-1": e}
        # 不创建产物
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.rollback_entry"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_stage_design("demo/REQ-1", "plan", "demo/plans/REQ-1-r1.md")
        self.assertEqual(rc, 1)

    def test_design_transitions_to_reviewing(self) -> None:
        prod = os.path.join(self.wp, "plans", "REQ-1-r1.md")
        with open(prod, "w") as f:
            f.write("开发方案")
        e = {"status": "plan_designing", "stages": {}, "claimed_by": "dev-plan-designer",
             "version": "v1", "iteration": 1}
        # release_stage_design 内部走 set_stage_state(_, _, "plan", "reviewing", product)
        # set_stage_state 要求 cur ∈ ("working", "reviewing")，故需先让 cur=working
        e["stages"]["plan"] = {"round": 0, "state": "working"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_stage_design("demo/REQ-1", "plan", "demo/plans/REQ-1-r1.md")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "plan_reviewing")
        self.assertEqual(e["stages"]["plan"]["product"], "demo/plans/REQ-1-r1.md")


class ReleaseStageReview(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = _seed_project(self)
        os.makedirs(os.path.join(self.wp, "plans"), exist_ok=True)

    def test_pass_sets_done(self) -> None:
        prod = os.path.join(self.wp, "plans", "REQ-1-r1-review.md")
        with open(prod, "w") as f:
            f.write("评审意见")
        e = {"status": "plan_reviewing", "stages": {}, "claimed_by": "dev-plan-reviewer",
             "version": "v1", "iteration": 1, "max_rounds": 3}
        e["stages"]["plan"] = {"round": 0, "state": "reviewing", "product": "demo/plans/REQ-1-r1.md"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_stage_review("demo/REQ-1", "plan", "demo/plans/REQ-1-r1-review.md", "PASS")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "plan_done")
        self.assertEqual(e["stages"]["plan"]["state"], "done")
        self.assertEqual(e["stages"]["plan"]["round"], 1)

    def test_fail_at_max_rounds_blocks(self) -> None:
        prod = os.path.join(self.wp, "plans", "REQ-1-r3-review.md")
        with open(prod, "w") as f:
            f.write("评审意见")
        e = {"status": "plan_reviewing", "stages": {}, "claimed_by": "dev-plan-reviewer",
             "version": "v1", "iteration": 1, "max_rounds": 3}
        e["stages"]["plan"] = {"round": 3, "state": "reviewing", "product": "demo/plans/REQ-1-r3.md"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_stage_review("demo/REQ-1", "plan", "demo/plans/REQ-1-r3-review.md", "FAIL")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "blocked")

    def test_invalid_conclusion_returns_1(self) -> None:
        rc = release_stage_review("demo/REQ-1", "plan", "any.md", "MAYBE")
        self.assertEqual(rc, 1)


class ReleaseGate(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = _seed_project(self)
        os.makedirs(os.path.join(self.wp, "quality"), exist_ok=True)

    def test_pass_sets_quality_done(self) -> None:
        prod = os.path.join(self.wp, "quality", "REQ-1-r1.md")
        with open(prod, "w") as f:
            f.write("质量结论")
        e = {"status": "quality_gating", "stages": {}, "claimed_by": "quality-reviewer",
             "version": "v1", "iteration": 1, "max_rounds": 3}
        # release_gate 内部走 set_stage_state(_, _, "quality", "done")，要求 cur=reviewing
        e["stages"]["quality"] = {"round": 0, "state": "reviewing", "product": "demo/quality/REQ-1-r1.md"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_gate("demo/REQ-1", "quality", "demo/quality/REQ-1-r1.md", "PASS")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "quality_done")
        self.assertEqual(e["stages"]["quality"]["state"], "done")

    def test_invalid_conclusion_returns_1(self) -> None:
        rc = release_gate("demo/REQ-1", "quality", "any.md", "MAYBE")
        self.assertEqual(rc, 1)


class ReleaseRelease(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = _seed_project(self)
        os.makedirs(os.path.join(self.wp, "release"), exist_ok=True)

    def test_release_sets_released_and_writes_artifact(self) -> None:
        prod_dir = os.path.join(self.wp, "release", "REQ-1-r1")
        os.makedirs(prod_dir, exist_ok=True)
        with open(os.path.join(prod_dir, "release-notes.md"), "w") as f:
            f.write("release notes")
        e = {"status": "releasing", "stages": {}, "claimed_by": "releaser",
             "version": "v1", "iteration": 1, "max_rounds": 3}
        e["stages"]["release"] = {"round": 0, "state": "reviewing"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.write_artifact") as m_arch, \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_release("demo/REQ-1", "demo/release/REQ-1-r1/")
        self.assertEqual(rc, 0)
        self.assertEqual(e["status"], "released")
        # norm_product 不去尾 '/'：保留 dir 类产物的尾斜杠（与原代码行为一致）
        self.assertEqual(e["stages"]["release"]["product"], "demo/release/REQ-1-r1/")
        m_arch.assert_called()

    def test_missing_release_dir_rolls_back(self) -> None:
        e = {"status": "releasing", "stages": {}, "claimed_by": "releaser"}
        e["stages"]["release"] = {"round": 0, "state": "reviewing"}
        st = {"demo/REQ-1": e}
        with mock.patch("statectl_core.release.read_status", return_value=st), \
             mock.patch("statectl_core.release.write_status"), \
             mock.patch("statectl_core.release.rollback_entry") as m_roll, \
             mock.patch("statectl_core.release.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_release("demo/REQ-1", "demo/release/REQ-1-r1/")
        self.assertEqual(rc, 1)
        m_roll.assert_called()


if __name__ == "__main__":
    unittest.main()