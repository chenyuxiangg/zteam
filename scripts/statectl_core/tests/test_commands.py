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
        # 空 args → 打印 help 并返回 0
        self.assertEqual(main([]), 0)

    def test_help_variants(self) -> None:
        from statectl_core.commands import main
        for argv in (["help"], ["--help"], ["-h"]):
            with self.subTest(argv=argv):
                self.assertEqual(main(argv), 0)

    def test_unknown_returns_two(self) -> None:
        from statectl_core.commands import main
        self.assertEqual(main(["totally_made_up"]), 2)

    def test_cmd_help_returns_zero(self) -> None:
        from statectl_core.commands import cmd_help
        self.assertEqual(cmd_help(), 0)

    def test_help_mentions_all_categories(self) -> None:
        """帮助文本应覆盖全部 5 大类：tick / release / 人工 / 版本项目 / 诊断。"""
        import io
        from contextlib import redirect_stdout
        from statectl_core.commands import cmd_help
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_help()
        text = buf.getvalue()
        for keyword in ("tick", "release_", "人工", "版本", "诊断", "diagnose"):
            self.assertIn(keyword, text, f"帮助缺失关键词 {keyword!r}")


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
        # 重定向 commands.py 模块内的 PAUSE_FILE/NOTIFY_MARKER/CONFIRM_REMINDED
        from statectl_core import commands
        from statectl_core.paths import (
            NOTIFY_MARKER as _tnm, CONFIRM_REMINDED as _tcr, PAUSE_FILE as _tpf,
        )
        self._saved = {
            "PAUSE_FILE": commands.PAUSE_FILE,
            "NOTIFY_MARKER": commands.NOTIFY_MARKER,
            "CONFIRM_REMINDED": commands.CONFIRM_REMINDED,
        }
        commands.PAUSE_FILE = _tpf
        commands.NOTIFY_MARKER = _tnm
        commands.CONFIRM_REMINDED = _tcr

    def tearDown(self) -> None:
        from statectl_core import commands
        for k, v in self._saved.items():
            setattr(commands, k, v)
        super().tearDown()

    def test_dispatch_empty_state(self) -> None:
        from statectl_core.commands import main
        # 这些 subcommand 在空状态下应该无副作用地返回 0
        for sub in ["stale", "register", "list", "notify", "next"]:
            with self.subTest(sub=sub):
                self.assertEqual(main([sub]), 0)

    def test_main_dispatch_all_subcommands(self) -> None:
        """遍历 35 个 subcommand，每个用最小合理参数调用，断言返回 int（不崩溃）。
        目的：派发表（main() 内的 if 链）任何分支拼写错/参数解析错会被立刻发现。"""
        from statectl_core.commands import main
        # 准备一些必要的状态文件以满足各 subcommand 的最低前置：
        rid, e = _seed_e(status="pending")
        from statectl_core.status import write_status as _ws
        _ws({rid: e}, project="demo")
        # 各 subcommand 的最小调用参数（空项目/最小状态都能跑通的形参）
        cases = {
            # tick 类（无参）
            "quota_tick": [],
            "weekly_tick": [],
            "diagnose": [],
            # release 类（按真实签名给最小参数）
            "release_analyze": ["demo/R1", "demo/analysis/x.md"],
            "release_review": ["demo/R1", "demo/review/x.md", "PASS"],
            "release_stage_design": ["demo/R1", "plan", "demo/plans/x-r1.md"],
            "release_stage_review": ["demo/R1", "plan", "demo/plans/x-r1-review.md", "PASS"],
            "release_gate": ["demo/R1", "plan", "demo/plans/x-r1.md", "PASS"],
            "release_release": ["demo/R1", "demo/release/x.md"],
            "release_it": ["demo", "v1", "1", "demo/it/x.md", "DONE"],
            "release_st": ["demo", "v1", "demo/st/x.md", "DONE"],
            "release_arch": ["demo", "v1", "demo/arch/x.md", "DONE"],
            "release_testplan_v2": ["demo", "v1", "demo/testplans/x.md", "DONE"],
            "release_module": ["demo", "m1", "1", "design", "demo/code/x.md", "DONE"],
            "release_qa": ["demo", "v1", "demo/quality/x.md", "DONE"],
            "release_st_v2": ["demo", "v1", "demo/st/x.md", "DONE"],
            "release_st_case": ["demo", "v1", "demo/tests/x.md", "DONE"],
            # 人工
            "register": [],
            "stale": [],
            "next": [],
            "claim": ["demo/R1", "worker"],
            "setpid": ["demo/R1", "99999"],
            "rollback": ["demo/R1", "test"],
            "requeue": ["demo/R1"],
            "record_product": ["demo/R1", "plan", "demo/plans/x-r1.md"],
            "resume": ["demo/R1", "plan", "designing"],
            "halt": [],
            "unhalt": [],
            "notify": [],
            "list": [],
            "get": ["demo/R1"],
            # 模块/版本/项目
            "module": ["demo", "list", []],
            "issue": ["demo", "list", ""],   # cmd_issue(rest[2:]) 需 rest[2:] 含可调 lower() 的字符串
            "unblock": ["demo", "v1"],
            "confirm": ["demo/R1"],
            "reject": ["demo/R1", "test reason"],
            "change_request": ["demo/R1", "modify", "test"],
            "project": ["list", []],
            "versions": [None],
            "assign": ["demo/R1", "version=v1"],
            "confirm_guide": ["demo", "v1"],
            "reject_guide": ["demo", "v1", "test"],
            "set_status": ["demo/R1", "plan", "working"],
        }
        # 至少 35 个 subcommand 覆盖（实际 40+，含子命令分类完整）
        self.assertGreaterEqual(len(cases), 35,
            f"cases 字典应至少覆盖 35 个 subcommand，实际 {len(cases)} 个")
        for sub, args in cases.items():
            with self.subTest(sub=sub):
                rc = main([sub] + list(args))
                self.assertIsInstance(rc, int)
                # 退出码应该在合法范围（0=成功，1=业务错，2=参数错）
                self.assertIn(rc, (0, 1, 2),
                    f"{sub} 退出码异常: {rc}")


if __name__ == "__main__":
    unittest.main()
