"""Tests for statectl_core.diagnose: 一键健康检查。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

# 注：statectl_core.__init__ 通过 `from .diagnose import diagnose` 把同名属性
# rebind 成函数，导致 `statectl_core.diagnose` 指向函数而非模块。
# 因此必须用 sys.modules 拿到真正的模块才能 patch 其上的 _sh。
_DIAGNOSE_MOD = sys.modules["statectl_core.diagnose"]
assert isinstance(_DIAGNOSE_MOD, type(json)), "statectl_core.diagnose 应为模块，被 __init__ rebind 后仍可从 sys.modules 取"

from statectl_core.diagnose import REQUIRED_FIELDS, _sh, diagnose

from ._helpers import StatectlTestCase


class _SeedMixin(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")


class Constants(unittest.TestCase):
    def test_required_fields(self) -> None:
        self.assertIn("status", REQUIRED_FIELDS)
        self.assertIn("analysis", REQUIRED_FIELDS)


class Sh(unittest.TestCase):
    def test_returns_stdout(self) -> None:
        with mock.patch("subprocess.run") as mrun:
            mrun.return_value = mock.Mock(stdout="hello", returncode=0)
            self.assertEqual(_sh(["echo", "hi"]), "hello")

    def test_empty_on_exception(self) -> None:
        with mock.patch("subprocess.run", side_effect=OSError("boom")):
            self.assertEqual(_sh(["x"]), "")


class Diagnose(_SeedMixin):
    def test_empty_state_returns_zero(self) -> None:
        # No projects registered → diagnose should not fail with 1
        with mock.patch.object(_DIAGNOSE_MOD, "_sh", return_value="Gateway is running\n"):
            rc = diagnose()
        self.assertEqual(rc, 0)

    def test_required_fields_present(self) -> None:
        self.assertIn("status", REQUIRED_FIELDS)

    def test_with_project_and_status(self) -> None:
        from statectl_core.status import write_status as _ws
        st = {"demo/R1": {"status": "approved", "round": 0, "max_rounds": 3,
                          "forced": False, "analysis": None, "reviews": [],
                          "failures": 0, "created_at": "2026-09-01T00:00:00Z",
                          "updated_at": "2026-09-01T00:00:00Z"}}
        _ws(st, project="demo")
        with mock.patch.object(_DIAGNOSE_MOD, "_sh", return_value="Gateway is running\n"):
            rc = diagnose()
        self.assertEqual(rc, 0)

    def test_sh_is_actually_mocked(self) -> None:
        # 显式断言 _sh 已被 mock：避免真实 hermes 进程让用例假阳性通过。
        sentinel = "MOCKED_GATEWAY_OUTPUT_FOR_TEST"
        with mock.patch.object(_DIAGNOSE_MOD, "_sh", return_value=sentinel) as msh:
            calls = []
            def _spy(args, timeout=15):
                calls.append(args)
                return sentinel
            msh.side_effect = _spy
            diagnose()
        self.assertTrue(calls, "diagnose() 未调用 _sh，patch 路径错位")
        self.assertIn(["hermes", "cron", "status"], calls)


if __name__ == "__main__":
    unittest.main()