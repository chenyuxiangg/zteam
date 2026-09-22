"""Tests for statectl_core.issues: 问题单 + 架构/方案阶段命令。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from statectl_core import issues, paths, versions
from statectl_core.issues import (
    _arch_inputs,
    _issue_brief_for_fix,
    _issue_owner,
    _issue_owner_locked,
    _issue_path,
    _issue_path_owner,
    _issue_path_reporter,
    _issue_reporter,
    _issue_status,
    _read_modules_for_issue,
    _schedule_arch_te,
    cmd_issue,
    issues_dir,
    open_issues,
    release_arch,
    release_testplan_v2,
)

from ._helpers import StatectlTestCase


def _seed(self: StatectlTestCase) -> str:
    """登记 demo 项目并返回 work_path；issues.py 测试用。"""
    return self.make_project("demo")


class _SeedMixin(StatectlTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wp = _seed(self)


# ---------------- issues_dir / _issue_path ----------------

class IssueDirs(_SeedMixin):
    def test_creates_issues_dir(self) -> None:
        d = issues_dir("demo")
        self.assertTrue(os.path.isdir(d))
        self.assertEqual(os.path.basename(d), "issues")

    def test_issue_path_format(self) -> None:
        p = _issue_path("demo", "FOO-01")
        self.assertTrue(p.endswith(os.path.join("issues", "FOO-01.md")))


# ---------------- _issue_status ----------------

class IssueStatus(unittest.TestCase):
    def test_reads_status_line(self) -> None:
        c = "# 问题单\n\n状态：open\n归属模块：m\n"
        self.assertEqual(_issue_status(c), "open")

    def test_unknown_status_returns_closed(self) -> None:
        c = "# 问题单\n\n状态：weird\n归属模块：m\n"
        self.assertEqual(_issue_status(c), "closed")

    def test_no_status_line_returns_closed(self) -> None:
        self.assertEqual(_issue_status("# no status line\n"), "closed")

    def test_only_first_status_line_matters(self) -> None:
        # 全文多处状态字样不影响（防误判）
        c = "\n".join([
            "# 问题单",
            "",
            "状态：open",
            "归属模块：m",
            "## 修复记录",
            "状态：fixed",  # 第 6 行也有，但只 first 匹配
        ])
        self.assertEqual(_issue_status(c), "open")


# ---------------- _issue_owner ----------------

class IssueOwner(unittest.TestCase):
    def test_returns_module(self) -> None:
        c = "状态：open\n归属模块：m\n"
        self.assertEqual(_issue_owner(c), "m")

    def test_pending_returns_empty(self) -> None:
        # "待定" 表示未裁决
        self.assertEqual(_issue_owner("归属模块：待定\n"), "")

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(_issue_owner("归属模块：\n"), "")

    def test_no_owner_line_returns_empty(self) -> None:
        self.assertEqual(_issue_owner("# no owner\n"), "")


# ---------------- _issue_reporter ----------------

class IssueReporter(unittest.TestCase):
    def test_sto(self) -> None:
        self.assertEqual(_issue_reporter("提单人：STO\n"), "STO")

    def test_mto(self) -> None:
        self.assertEqual(_issue_reporter("提单人：MTO\n"), "MTO")

    def test_unknown_role_returns_empty(self) -> None:
        self.assertEqual(_issue_reporter("提单人：QA\n"), "")

    def test_no_reporter_line_returns_empty(self) -> None:
        self.assertEqual(_issue_reporter("# no reporter\n"), "")


# ---------------- _issue_owner_locked ----------------

class IssueOwnerLocked(unittest.TestCase):
    def test_locked_in_first_20_lines(self) -> None:
        c = "归属模块：m\n归属复核：locked\n"
        self.assertTrue(_issue_owner_locked(c))

    def test_not_locked(self) -> None:
        c = "归属模块：m\n"
        self.assertFalse(_issue_owner_locked(c))

    def test_locked_after_20_ignored(self) -> None:
        c = "\n".join(["x"] * 20) + "\n归属复核：locked\n"
        self.assertFalse(_issue_owner_locked(c))


# ---------------- _issue_brief_for_fix ----------------

class IssueBriefForFix(_SeedMixin):
    def test_short_content_only_head(self) -> None:
        p = os.path.join(self.wp, "issues", "FOO-01.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# FOO-01\n状态：open\n归属模块：m\n提单人：MTO\n\n描述：abc\n")
        s = _issue_brief_for_fix("demo", "FOO-01")
        self.assertIn("FOO-01", s)
        self.assertIn("归属 m", s)
        self.assertIn("提单人 MTO", s)
        self.assertIn("描述：abc", s)

    def test_long_content_includes_tail(self) -> None:
        p = os.path.join(self.wp, "issues", "BAR-01.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        long_content = "# BAR-01\n状态：open\n归属模块：m\n提单人：STO\n\n描述：" + "x" * 5000 + "\n\n**复测方最新意见**：务必修 X\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(long_content)
        s = _issue_brief_for_fix("demo", "BAR-01")
        self.assertIn("复测方最新意见", s)
        self.assertIn("**必须逐条落实**", s)

    def test_missing_file_returns_unreadable(self) -> None:
        s = _issue_brief_for_fix("demo", "NONEXIST")
        self.assertIn("不可读", s)


# ---------------- _issue_path_owner / _issue_path_reporter ----------------

class IssuePathHelpers(_SeedMixin):
    def test_path_owner_returns_owner(self) -> None:
        p = os.path.join(self.wp, "issues", "X-01.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("归属模块：myMod\n")
        self.assertEqual(_issue_path_owner("demo", "X-01"), "myMod")

    def test_path_owner_missing_returns_empty(self) -> None:
        self.assertEqual(_issue_path_owner("demo", "NONE"), "")

    def test_path_reporter_returns_role(self) -> None:
        p = os.path.join(self.wp, "issues", "Y-01.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("提单人：STO\n")
        self.assertEqual(_issue_path_reporter("demo", "Y-01"), "STO")


# ---------------- _read_modules_for_issue ----------------

class ReadModulesForIssue(_SeedMixin):
    def test_returns_empty_when_no_file(self) -> None:
        self.assertEqual(_read_modules_for_issue("demo"), [])

    def test_returns_modules_list(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "a"}, {"name": "b"}]}, f)
        names = [m["name"] for m in _read_modules_for_issue("demo")]
        self.assertEqual(names, ["a", "b"])

    def test_corrupt_returns_empty(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            f.write("not-json{")
        self.assertEqual(_read_modules_for_issue("demo"), [])


# ---------------- cmd_issue.open ----------------

class CmdIssueOpen(_SeedMixin):
    def test_open_creates_file(self) -> None:
        rc = cmd_issue("demo", "open", ["FOO-01", "P1", "测试描述"])
        self.assertEqual(rc, 0)
        p = os.path.join(self.wp, "issues", "FOO-01.md")
        self.assertTrue(os.path.exists(p))
        content = open(p, encoding="utf-8").read()
        self.assertIn("状态：open", content)
        self.assertIn("归属模块：待定", content)
        self.assertIn("严重级：P1", content)
        self.assertIn("测试描述", content)

    def test_open_existing_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "first"])
        rc = cmd_issue("demo", "open", ["FOO-01", "P1", "second"])
        self.assertEqual(rc, 1)

    def test_open_no_severity_returns_1(self) -> None:
        self.assertEqual(cmd_issue("demo", "open", ["FOO-01"]), 1)


# ---------------- cmd_issue.assign ----------------

class CmdIssueAssign(_SeedMixin):
    def test_assign_known_module_succeeds(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}, {"name": "m2"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        rc = cmd_issue("demo", "assign", ["FOO-01", "m1", "因为 X"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("归属模块：m1", content)
        self.assertIn("SE 归属裁决 → m1", content)

    def test_assign_unknown_module_returns_1(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        self.assertEqual(cmd_issue("demo", "assign", ["FOO-01", "unknown"]), 1)

    def test_assign_after_reject_locks(self) -> None:
        # FO 拒修后 SE 重新分单 → 自动加 归属复核：locked 行
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        # 模拟 FO 拒修（直接在单里写）
        p = os.path.join(self.wp, "issues", "FOO-01.md")
        c = open(p, encoding="utf-8").read()
        c = c.replace("归属模块：待定", "归属模块：m1").rstrip("\n") + "\n- foo FO 拒修（原归属 m1）：理由\n"
        with open(p, "w", encoding="utf-8") as f:
            f.write(c)
        rc = cmd_issue("demo", "assign", ["FOO-01", "m1"])
        self.assertEqual(rc, 0)
        content = open(p, encoding="utf-8").read()
        self.assertIn("归属复核：locked", content)


# ---------------- cmd_issue.reject ----------------

class CmdIssueReject(_SeedMixin):
    def test_reject_open_resets_owner_and_logs(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "assign", ["FOO-01", "m1"])
        rc = cmd_issue("demo", "reject", ["FOO-01", "不在本模块"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("归属模块：待定", content)
        self.assertIn("FO 拒修（原归属 m1）：不在本模块", content)

    def test_reject_non_open_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        # 先 fixed 才能 reopen
        with open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8") as f:
            c = f.read()
        c = c.replace("状态：open", "状态：fixed", 1)
        with open(os.path.join(self.wp, "issues", "FOO-01.md"), "w", encoding="utf-8") as f:
            f.write(c)
        self.assertEqual(cmd_issue("demo", "reject", ["FOO-01", "理由"]), 1)

    def test_reject_locked_owner_returns_1(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        # 模拟归属已 locked
        p = os.path.join(self.wp, "issues", "FOO-01.md")
        c = open(p, encoding="utf-8").read()
        c = c.replace("归属模块：待定", "归属模块：m1\n归属复核：locked")
        with open(p, "w", encoding="utf-8") as f:
            f.write(c)
        self.assertEqual(cmd_issue("demo", "reject", ["FOO-01", "理由"]), 1)

    def test_reject_no_owner_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        # owner 为"待定" → _issue_owner 返回 "" → 无需拒修
        self.assertEqual(cmd_issue("demo", "reject", ["FOO-01", "理由"]), 1)


# ---------------- cmd_issue.pend / activate ----------------

class CmdIssuePendActivate(_SeedMixin):
    def test_pend_to_pending(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        rc = cmd_issue("demo", "pend", ["FOO-01", "v2.0.0", "下版本处理"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("状态：pending", content)
        self.assertIn("目标版本：v2.0.0", content)

    def test_activate_pending_to_open(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "pend", ["FOO-01", "v2.0.0", "理由"])
        rc = cmd_issue("demo", "activate", ["FOO-01"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("状态：open", content)

    def test_activate_non_pending_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        self.assertEqual(cmd_issue("demo", "activate", ["FOO-01"]), 1)


# ---------------- cmd_issue.split ----------------

class CmdIssueSplit(_SeedMixin):
    def test_split_creates_new_and_appends_history(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}, {"name": "m2"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        rc = cmd_issue("demo", "split", ["FOO-01", "FOO-01-a", "m2", "子项 a"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(os.path.join(self.wp, "issues", "FOO-01-a.md")))
        self.assertTrue(os.path.exists(os.path.join(self.wp, "issues", "FOO-01.md")))
        new_content = open(os.path.join(self.wp, "issues", "FOO-01-a.md"), encoding="utf-8").read()
        self.assertIn("归属模块：m2", new_content)
        self.assertIn("由 FOO-01 拆分而来", new_content)
        old_content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("拆分 → 新建 FOO-01-a", old_content)

    def test_split_unknown_module_returns_1(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        self.assertEqual(cmd_issue("demo", "split", ["FOO-01", "NEW", "unknown", "desc"]), 1)

    def test_split_existing_new_id_returns_1(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "open", ["FOO-01-a", "P1", "existing"])
        self.assertEqual(cmd_issue("demo", "split", ["FOO-01", "FOO-01-a", "m1", "desc"]), 1)


# ---------------- cmd_issue.fix（修复证据校验） ----------------

class CmdIssueFix(_SeedMixin):
    def _setup_open_with_owner(self) -> str:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "assign", ["FOO-01", "m1"])
        # 建 code/m1 目录 + 一个新文件（mtime 晚于提单）
        cdir = os.path.join(self.wp, "code", "m1")
        os.makedirs(cdir, exist_ok=True)
        # 写一个时间戳晚于 now_iso 的文件（直接用将来时间戳）
        import time as _t
        p = os.path.join(cdir, "new.py")
        with open(p, "w") as f:
            f.write("# new code")
        future = _t.time() + 3600
        os.utime(p, (future, future))
        return p

    def test_fix_passes_with_recent_code(self) -> None:
        self._setup_open_with_owner()
        rc = cmd_issue("demo", "fix", ["FOO-01"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("状态：fixed", content)
        self.assertIn("FO 修复完成", content)

    def test_fix_no_owner_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        # owner 仍为"待定"
        self.assertEqual(cmd_issue("demo", "fix", ["FOO-01"]), 1)

    def test_fix_no_recent_code_returns_1(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "assign", ["FOO-01", "m1"])
        # 建 code/m1 但无新文件
        os.makedirs(os.path.join(self.wp, "code", "m1"), exist_ok=True)
        self.assertEqual(cmd_issue("demo", "fix", ["FOO-01"]), 1)

    def test_fix_force_skips_check(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "assign", ["FOO-01", "m1"])
        # 无新文件 + force
        os.makedirs(os.path.join(self.wp, "code", "m1"), exist_ok=True)
        rc = cmd_issue("demo", "fix", ["FOO-01", "--force", "纯文档判定"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("状态：fixed", content)


# ---------------- cmd_issue.close / reopen ----------------

class CmdIssueCloseReopen(_SeedMixin):
    def _to_fixed(self) -> None:
        with open(os.path.join(self.wp, "modules.json"), "w") as f:
            json.dump({"modules": [{"name": "m1"}]}, f)
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "assign", ["FOO-01", "m1"])
        cdir = os.path.join(self.wp, "code", "m1")
        os.makedirs(cdir, exist_ok=True)
        p = os.path.join(cdir, "new.py")
        with open(p, "w") as f:
            f.write("# new")
        import time as _t
        future = _t.time() + 3600
        os.utime(p, (future, future))
        cmd_issue("demo", "fix", ["FOO-01"])

    def test_close_fixed_succeeds(self) -> None:
        self._to_fixed()
        rc = cmd_issue("demo", "close", ["FOO-01"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("状态：closed", content)

    def test_close_open_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        self.assertEqual(cmd_issue("demo", "close", ["FOO-01"]), 1)

    def test_reopen_fixed_succeeds(self) -> None:
        self._to_fixed()
        rc = cmd_issue("demo", "reopen", ["FOO-01", "复测不通过"])
        self.assertEqual(rc, 0)
        content = open(os.path.join(self.wp, "issues", "FOO-01.md"), encoding="utf-8").read()
        self.assertIn("状态：open", content)
        self.assertIn("复测不通过", content)

    def test_reopen_open_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        self.assertEqual(cmd_issue("demo", "reopen", ["FOO-01", "理由"]), 1)


# ---------------- cmd_issue.list ----------------

class CmdIssueList(_SeedMixin):
    def test_list_all(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "open", ["FOO-02", "P2", "desc"])
        # 不抛异常 + 内部 print；只断言不报错
        self.assertEqual(cmd_issue("demo", "list", []), 0)

    def test_list_filter(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        # filter=open → 应通过；filter=fixed → 也通过（无内容输出，但不报错）
        self.assertEqual(cmd_issue("demo", "list", ["open"]), 0)


# ---------------- cmd_issue 兜底 ----------------

class CmdIssueFallback(_SeedMixin):
    def test_unknown_action_returns_1(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        self.assertEqual(cmd_issue("demo", "weird", ["FOO-01"]), 1)

    def test_no_args_returns_1(self) -> None:
        self.assertEqual(cmd_issue("demo", "fix", []), 1)

    def test_operate_on_missing_returns_1(self) -> None:
        self.assertEqual(cmd_issue("demo", "fix", ["NONE-01"]), 1)


# ---------------- open_issues ----------------

class OpenIssuesList(_SeedMixin):
    def test_returns_open_and_fixed(self) -> None:
        cmd_issue("demo", "open", ["FOO-01", "P1", "desc"])
        cmd_issue("demo", "open", ["FOO-02", "P1", "desc"])
        # 第二个手工改 closed（不应进 list）
        p2 = os.path.join(self.wp, "issues", "FOO-02.md")
        c = open(p2, encoding="utf-8").read().replace("状态：open", "状态：closed", 1)
        with open(p2, "w", encoding="utf-8") as f:
            f.write(c)
        # 第三个手工改 fixed（应进 list）
        cmd_issue("demo", "open", ["FOO-03", "P1", "desc"])
        p3 = os.path.join(self.wp, "issues", "FOO-03.md")
        c = open(p3, encoding="utf-8").read().replace("状态：open", "状态：fixed", 1)
        with open(p3, "w", encoding="utf-8") as f:
            f.write(c)
        out = open_issues("demo")
        self.assertIn("FOO-01", out)
        self.assertIn("FOO-03", out)
        self.assertNotIn("FOO-02", out)

    def test_empty_dir(self) -> None:
        self.assertEqual(open_issues("demo"), [])


# ---------------- release_arch ----------------

class ReleaseArch(_SeedMixin):
    def _make_v(self, status: str = "arch") -> None:
        versions.write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{
                "name": "v1.0.0", "status": status,
                "iterations": [], "reqs": [],
            }],
        })

    def test_done_transitions_to_arch_reviewing(self) -> None:
        self._make_v("arch")
        prod = os.path.join(self.wp, "arch", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "doc.md"), "w") as f:
            f.write("arch")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_arch("demo", "v1.0.0", "demo/arch/v1.0.0/", "DONE")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "arch_reviewing")
        self.assertFalse(v["arch_claimed"])

    def test_done_wrong_state_returns_1(self) -> None:
        self._make_v("planning")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(release_arch("demo", "v1.0.0", "any", "DONE"), 1)

    def test_done_missing_product_returns_1(self) -> None:
        self._make_v("arch")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(release_arch("demo", "v1.0.0", "demo/arch/none/", "DONE"), 1)

    def test_pass_transitions_to_testplan(self) -> None:
        self._make_v("arch_reviewing")
        prod = os.path.join(self.wp, "review", "arch", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "review.md"), "w") as f:
            f.write("OK")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_arch("demo", "v1.0.0", "demo/review/arch/v1.0.0/review.md", "PASS")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "testplan")

    def test_fail_transitions_to_planning(self) -> None:
        self._make_v("arch_reviewing")
        prod = os.path.join(self.wp, "review", "arch", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "review.md"), "w") as f:
            f.write("NG")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_arch("demo", "v1.0.0", "demo/review/arch/v1.0.0/review.md", "FAIL")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "planning")

    def test_invalid_conclusion_returns_1(self) -> None:
        self._make_v("arch")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(release_arch("demo", "v1.0.0", "any", "MAYBE"), 1)

    def test_unknown_version_returns_1(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": []})
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(release_arch("demo", "v9.9.9", "any", "DONE"), 1)


# ---------------- release_testplan_v2 ----------------

class ReleaseTestplanV2(_SeedMixin):
    def _make_v(self, status: str) -> None:
        versions.write_versions("demo", {
            "current": "v1.0.0",
            "versions": [{
                "name": "v1.0.0", "status": status,
                "iterations": [], "reqs": [],
            }],
        })

    def test_done_transitions_to_testplan_reviewing(self) -> None:
        self._make_v("testplan")
        prod = os.path.join(self.wp, "testplans", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "plan.md"), "w") as f:
            f.write("plan")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_testplan_v2("demo", "v1.0.0", "demo/testplans/v1.0.0/", "DONE")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "testplan_reviewing")

    def test_pass_transitions_to_in_dev(self) -> None:
        self._make_v("testplan_reviewing")
        prod = os.path.join(self.wp, "review", "testplan", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "review.md"), "w") as f:
            f.write("OK")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_testplan_v2("demo", "v1.0.0", "demo/review/testplan/v1.0.0/review.md", "PASS")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "in_dev")

    def test_fail_transitions_to_testplan(self) -> None:
        self._make_v("testplan_reviewing")
        prod = os.path.join(self.wp, "review", "testplan", "v1.0.0")
        os.makedirs(prod, exist_ok=True)
        with open(os.path.join(prod, "review.md"), "w") as f:
            f.write("NG")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            rc = release_testplan_v2("demo", "v1.0.0", "demo/review/testplan/v1.0.0/review.md", "FAIL")
        self.assertEqual(rc, 0)
        v = versions.read_versions("demo")["versions"][0]
        self.assertEqual(v["status"], "testplan")

    def test_done_wrong_state_returns_1(self) -> None:
        self._make_v("planning")
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(release_testplan_v2("demo", "v1.0.0", "any", "DONE"), 1)

    def test_unknown_version_returns_1(self) -> None:
        versions.write_versions("demo", {"current": "v1.0.0", "versions": []})
        with mock.patch("statectl_core.issues.acquire_lock") as m_lock:
            m_lock.return_value.__enter__ = mock.Mock()
            m_lock.return_value.__exit__ = mock.Mock()
            self.assertEqual(release_testplan_v2("demo", "v9.9.9", "any", "DONE"), 1)


# ---------------- _arch_inputs ----------------

class ArchInputs(unittest.TestCase):
    def test_routes_each_req(self) -> None:
        st = {"demo/REQ-1": {"status": "approved", "analysis": "demo/analysis/REQ-1-r1.md"},
              "demo/REQ-2": {"status": "approved", "analysis": None}}
        s = _arch_inputs("demo", ["REQ-1", "REQ-2"], st)
        self.assertIn("REQ-1", s)
        self.assertIn("approved", s)
        self.assertIn("REQ-2", s)


# ---------------- _schedule_arch_te ----------------

class ScheduleArchTe(_SeedMixin):
    def _v(self, status: str, **extra) -> dict:
        base = {"name": "v1.0.0", "status": status, "iterations": [],
                "reqs": ["REQ-1", "REQ-2"]}
        base.update(extra)
        return base

    def test_planning_with_all_approved_spawns_se(self) -> None:
        v = self._v("planning")
        st = {"demo/REQ-1": {"status": "approved"},
              "demo/REQ-2": {"status": "approved"}}
        with mock.patch("statectl_core.issues.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.issues.write_versions"):
            m_spawn.return_value = 111
            alarms: list = []
            _schedule_arch_te("demo", {"versions": [v]}, st, alarms)
        self.assertTrue(v["arch_claimed"])
        self.assertEqual(v["status"], "arch")
        self.assertEqual(m_spawn.call_args.args[0], "se")

    def test_planning_with_partial_approved_no_spawn(self) -> None:
        v = self._v("planning")
        st = {"demo/REQ-1": {"status": "approved"},
              "demo/REQ-2": {"status": "analyzing"}}
        with mock.patch("statectl_core.issues.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.issues.write_versions"):
            _schedule_arch_te("demo", {"versions": [v]}, st, [])
        m_spawn.assert_not_called()

    def test_planning_with_active_version_no_spawn(self) -> None:
        # 版本串行：另一版本已 arch → 不再 spawn
        v1 = self._v("planning")
        v2 = self._v("arch")
        st = {"demo/REQ-1": {"status": "approved"}, "demo/REQ-2": {"status": "approved"}}
        with mock.patch("statectl_core.issues.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.issues.write_versions"):
            _schedule_arch_te("demo", {"versions": [v1, v2]}, st, [])
        m_spawn.assert_not_called()

    def test_arch_reviewing_spawns_pm(self) -> None:
        v = self._v("arch_reviewing")
        st = {}
        with mock.patch("statectl_core.issues.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.issues.write_versions"):
            m_spawn.return_value = 222
            _schedule_arch_te("demo", {"versions": [v]}, st, [])
        self.assertTrue(v["arch_review_claimed"])
        self.assertEqual(m_spawn.call_args.args[0], "pm")

    def test_testplan_spawns_te(self) -> None:
        v = self._v("testplan")
        st = {}
        with mock.patch("statectl_core.issues.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.issues.write_versions"):
            m_spawn.return_value = 333
            _schedule_arch_te("demo", {"versions": [v]}, st, [])
        self.assertTrue(v["test_plan_claimed"])
        self.assertEqual(m_spawn.call_args.args[0], "te")

    def test_testplan_reviewing_spawns_se(self) -> None:
        v = self._v("testplan_reviewing")
        st = {}
        with mock.patch("statectl_core.issues.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.issues.write_versions"):
            m_spawn.return_value = 444
            _schedule_arch_te("demo", {"versions": [v]}, st, [])
        self.assertTrue(v["testplan_review_claimed"])
        self.assertEqual(m_spawn.call_args.args[0], "se")

    def test_released_skipped(self) -> None:
        v = self._v("released")
        with mock.patch("statectl_core.issues.spawn_worker") as m_spawn, \
             mock.patch("statectl_core.issues.write_versions"):
            _schedule_arch_te("demo", {"versions": [v]}, {}, [])
        m_spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()