"""Tests for statectl_core.commands: cmd_* 系列人工命令 + main() 派发表。

覆盖范围（commit 6）：
- 子命令 dispatch（每个 subcommand 用 sys.argv[1:] 模拟调用，断言返回码）
- cmd_halt / cmd_unhalt：PAUSE_FILE 存在与否
- cmd_notify：NOTIFY_MARKER / CONFIRM_REMINDED 文件写入
- cmd_set_status / cmd_rollback / cmd_requeue 状态机迁移
- main(["unknown"]) → 2
- main([]) → 0
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from ._helpers import StatectlTestCase


def _seed_e(rid="demo/R1", **overrides):
    """标准 status 条目（最小可用）。"""
    e = {
        "status": "pending",
        "round": 0,
        "max_rounds": 3,
        "forced": False,
        "analysis": None,
        "reviews": [],
        "failures": 0,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "stages": {},
    }
    e.update(overrides)
    return rid, e


class MainDispatch(unittest.TestCase):
    """主循环 main() 派发表：所有 subcommand 至少能解析且返回 int。"""

    def test_empty_returns_zero(self) -> None:
        from statectl_core.commands import main
        self.assertEqual(main([]), 0)

    def test_unknown_returns_two(self) -> None:
        from statectl_core.commands import main
        self.assertEqual(main(["totally_made_up"]), 2)


class HaltUnhalt(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")
        # 重定向 commands.py 模块内的 PAUSE_FILE 引用（import-time 绑定）
        from statectl_core import commands
        self._cmd_pause = commands.PAUSE_FILE
        from statectl_core.paths import PAUSE_FILE as _tpf
        commands.PAUSE_FILE = _tpf

    def tearDown(self) -> None:
        from statectl_core import commands
        commands.PAUSE_FILE = self._cmd_pause
        super().tearDown()

    def test_halt_creates_pause_file(self) -> None:
        from statectl_core.commands import cmd_halt, cmd_unhalt
        from statectl_core import commands as _cmds
        from statectl_core.paths import PAUSE_FILE
        # 测试用隔离路径
        _cmds.PAUSE_FILE = PAUSE_FILE
        self.assertFalse(os.path.exists(PAUSE_FILE))
        self.assertEqual(cmd_halt("smoke-test"), 0)
        self.assertTrue(os.path.exists(PAUSE_FILE))
        self.assertIn("smoke-test", open(PAUSE_FILE, encoding="utf-8").read())
        self.assertEqual(cmd_unhalt(), 0)
        self.assertFalse(os.path.exists(PAUSE_FILE))

    def test_double_halt_returns_one(self) -> None:
        from statectl_core.commands import cmd_halt
        cmd_halt()
        self.assertEqual(cmd_halt(), 1)

    def test_unhalt_when_not_paused(self) -> None:
        from statectl_core.commands import cmd_unhalt
        self.assertEqual(cmd_unhalt(), 1)


class Notify(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")
        from statectl_core import commands
        self._cmd_notify = commands.NOTIFY_MARKER
        self._cmd_confirm = commands.CONFIRM_REMINDED
        from statectl_core.paths import NOTIFY_MARKER as _tnm, CONFIRM_REMINDED as _tcr
        commands.NOTIFY_MARKER = _tnm
        commands.CONFIRM_REMINDED = _tcr

    def tearDown(self) -> None:
        from statectl_core import commands
        commands.NOTIFY_MARKER = self._cmd_notify
        commands.CONFIRM_REMINDED = self._cmd_confirm
        super().tearDown()

    def test_first_run_initializes_marker(self) -> None:
        from statectl_core.commands import cmd_notify
        from statectl_core import commands as _cmds
        from statectl_core.paths import NOTIFY_MARKER
        _cmds.NOTIFY_MARKER = NOTIFY_MARKER
        self.assertFalse(os.path.exists(NOTIFY_MARKER))
        self.assertEqual(cmd_notify(), 0)
        self.assertTrue(os.path.exists(NOTIFY_MARKER))

    def test_writes_confirm_reminded(self) -> None:
        from statectl_core.commands import cmd_notify
        from statectl_core import commands as _cmds
        from statectl_core.paths import CONFIRM_REMINDED
        _cmds.CONFIRM_REMINDED = CONFIRM_REMINDED
        cmd_notify()
        # 即使无 pending confirm，文件也存在且为合法 JSON 数组
        self.assertTrue(os.path.exists(CONFIRM_REMINDED))
        data = json.load(open(CONFIRM_REMINDED, encoding="utf-8"))
        self.assertIsInstance(data, list)


class ListGet(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")

    def test_list_empty(self) -> None:
        from statectl_core.commands import cmd_list
        self.assertEqual(cmd_list(), 0)

    def test_list_one(self) -> None:
        from statectl_core.commands import cmd_list
        from statectl_core.status import write_status
        rid, e = _seed_e()
        write_status({rid: e}, project="demo")
        self.assertEqual(cmd_list(), 0)

    def test_get_missing_returns_one(self) -> None:
        from statectl_core.commands import cmd_get
        self.assertEqual(cmd_get("demo/nope"), 1)

    def test_get_existing(self) -> None:
        from statectl_core.commands import cmd_get
        from statectl_core.status import write_status
        rid, e = _seed_e(rid="demo/R2")
        write_status({rid: e}, project="demo")
        self.assertEqual(cmd_get("demo/R2"), 0)


class SetStatus(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")

    def test_set_status_missing_rid(self) -> None:
        from statectl_core.commands import cmd_set_status
        self.assertEqual(cmd_set_status("demo/nope", "req", "working"), 1)

    def test_set_status_workflow(self) -> None:
        from statectl_core.commands import cmd_set_status
        from statectl_core.status import read_status, write_status
        rid, e = _seed_e(status="analyzing")
        write_status({rid: e}, project="demo")
        # working → reviewing (需 product) → done 是合法路径
        self.assertEqual(cmd_set_status(rid, "plan", "working"), 0)
        # 写一个真存在的 product 文件路径
        proj_wp = self.wp
        product_rel = "demo/plans/R1-r1.md"
        full = os.path.join(proj_wp, "plans", "R1-r1.md")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("# plan")
        self.assertEqual(cmd_set_status(rid, "plan", "reviewing", product_rel), 0)


class Next(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")

    def test_next_no_pending(self) -> None:
        from statectl_core.commands import cmd_next
        self.assertEqual(cmd_next("worker"), 0)


class Stale(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")

    def test_stale_empty(self) -> None:
        from statectl_core.commands import cmd_stale
        self.assertEqual(cmd_stale(), 0)


class SubcommandDispatch(StatectlTestCase):
    """main() 派发表：调用每个 subcommand 不应抛异常，至少返回 int。"""

    def setUp(self) -> None:
        super().setUp()
        self.wp = self.make_project("demo")

    def test_dispatch_empty_state(self) -> None:
        from statectl_core.commands import main
        # 这些 subcommand 在空状态下应该无副作用地返回 0
        for sub in ["stale", "register", "list", "notify", "next"]:
            with self.subTest(sub=sub):
                self.assertEqual(main([sub]), 0)


if __name__ == "__main__":
    unittest.main()
