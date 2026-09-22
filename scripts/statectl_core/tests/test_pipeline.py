"""Tests for statectl_core.pipeline: 状态机、阶段流转、claim/spawn/artifact。"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from statectl_core import paths, pipeline
from statectl_core.pipeline import (
    GATES,
    MID_STATES,
    RELEASE,
    STAGES,
    STATE_SET,
    _deps_satisfied,
    _find_block_stage,
    _iterations_prev_done,
    _stage_order,
    active_stage,
    build_worker_query,
    claim,
    drain_alarms,
    ensure_stages,
    find_claimable,
    new_stages,
    next_action,
    norm_product,
    parse_conclusion,
    prev_done_state,
    product_path,
    rollback_entry,
    set_stage_state,
    spawn_worker,
    stage_after as _stage_after,
    stage_cfg,
    stage_inputs,
    stale_recovery,
    write_artifact,
)

from ._helpers import StatectlTestCase


# ---- 状态机常量 ----

class StateMachineConstants(unittest.TestCase):
    def test_stages_count_and_structure(self) -> None:
        self.assertEqual(len(STAGES), 4)
        names = [s["name"] for s in STAGES]
        self.assertEqual(names, ["plan", "testplan", "code", "test"])
        for s in STAGES:
            self.assertIn("designer", s)
            self.assertIn("reviewer", s)
            self.assertIn("dir", s)
            self.assertIn("kind", s)

    def test_gates_count(self) -> None:
        self.assertEqual(len(GATES), 2)
        names = [g["name"] for g in GATES]
        self.assertEqual(names, ["quality", "security"])

    def test_release_shape(self) -> None:
        self.assertEqual(RELEASE["name"], "release")
        self.assertEqual(RELEASE["role"], "releaser")
        self.assertEqual(RELEASE["kind"], "dir")

    def test_mid_states_includes_design_review_release(self) -> None:
        # 中间态集合必须含分析/评审/阶段 designing+reviewing+gateing
        self.assertIn("analyzing", MID_STATES)
        self.assertIn("reviewing", MID_STATES)
        self.assertIn("releasing", MID_STATES)
        for s in STAGES:
            self.assertIn(f"{s['name']}_designing", MID_STATES)
            self.assertIn(f"{s['name']}_reviewing", MID_STATES)
        for g in GATES:
            self.assertIn(f"{g['name']}_gating", MID_STATES)

    def test_state_set_covers_legal_statuses(self) -> None:
        # STATE_SET 至少含：pending / approved / released / blocked / dispatched / removed
        for s in ("pending", "approved", "released", "blocked", "dispatched", "removed"):
            self.assertIn(s, STATE_SET)
        # 含各阶段 done
        for s in STAGES:
            self.assertIn(f"{s['name']}_done", STATE_SET)


# ---- 流转 ----

class StageCfg(unittest.TestCase):
    def test_returns_stage_dict(self) -> None:
        cfg = stage_cfg("plan")
        self.assertEqual(cfg["name"], "plan")

    def test_returns_gate_dict(self) -> None:
        cfg = stage_cfg("quality")
        self.assertEqual(cfg["name"], "quality")

    def test_returns_release(self) -> None:
        cfg = stage_cfg("release")
        self.assertEqual(cfg["name"], "release")

    def test_returns_none_for_unknown(self) -> None:
        self.assertIsNone(stage_cfg("nope"))


class StageAfter(unittest.TestCase):
    def test_plan_after_is_testplan(self) -> None:
        nxt = _stage_after("plan")
        self.assertEqual(nxt["name"], "testplan")

    def test_release_has_no_next(self) -> None:
        self.assertIsNone(_stage_after("release"))

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(_stage_after("nope"))


class NextAction(unittest.TestCase):
    def test_waiting_returns_none(self) -> None:
        self.assertIsNone(next_action({"status": "waiting"}))

    def test_awaiting_user_confirm_returns_none(self) -> None:
        self.assertIsNone(next_action({"status": "awaiting_user_confirm"}))

    def test_pending_returns_pm_design_req(self) -> None:
        self.assertEqual(next_action({"status": "pending"}), ("pm", "req", "design"))

    def test_needs_fix_returns_pm_design_req(self) -> None:
        self.assertEqual(next_action({"status": "needs_fix"}), ("pm", "req", "design"))

    def test_analyzing_returns_pm_design_req(self) -> None:
        # v2 PM 在 analyzing 时继续（同状态执行者 = 写产物）
        self.assertEqual(next_action({"status": "analyzing"}), ("pm", "req", "design"))

    def test_analyzed_returns_pm_design_req(self) -> None:
        # reject 后 PM 继续
        self.assertEqual(next_action({"status": "analyzed"}), ("pm", "req", "design"))

    def test_reviewing_returns_req_reviewer(self) -> None:
        self.assertEqual(next_action({"status": "reviewing"}), ("req-reviewer", "req", "review"))

    def test_approved_returns_none_v2(self) -> None:
        # v2：approved 等 SE 架构设计，不再直接进需求级方案
        self.assertIsNone(next_action({"status": "approved"}))

    def test_stage_designing_returns_designer(self) -> None:
        act = next_action({"status": "code_designing"})
        self.assertEqual(act, ("code-developer", "code", "design"))

    def test_stage_reviewing_returns_reviewer(self) -> None:
        act = next_action({"status": "code_reviewing"})
        self.assertEqual(act, ("code-reviewer", "code", "review"))

    def test_quality_gating_returns_quality_reviewer(self) -> None:
        act = next_action({"status": "quality_gating"})
        self.assertEqual(act, ("quality-reviewer", "quality", "gate"))

    def test_releasing_returns_releaser(self) -> None:
        self.assertEqual(next_action({"status": "releasing"}), ("releaser", "release", "release"))

    def test_unknown_returns_none(self) -> None:
        self.assertIsNone(next_action({"status": "foobar"}))


# ---- new_stages / ensure_stages ----

class NewStages(unittest.TestCase):
    def test_contains_every_known_stage(self) -> None:
        d = new_stages()
        for s in STAGES:
            self.assertIn(s["name"], d)
        for g in GATES:
            self.assertIn(g["name"], d)
        self.assertIn(RELEASE["name"], d)
        self.assertIn("req", d)

    def test_each_entry_has_required_fields(self) -> None:
        for k, v in new_stages().items():
            self.assertEqual(v["round"], 0)
            self.assertIsNone(v["product"])
            self.assertEqual(v["reviews"], [])
            self.assertIsNone(v["state"])
            self.assertIsNone(v["state_since"])
            self.assertEqual(v["timeline"], [])


class EnsureStages(unittest.TestCase):
    def test_initializes_when_missing(self) -> None:
        e: dict = {"status": "pending"}
        stages = ensure_stages(e)
        self.assertIn("plan", stages)
        self.assertIn("req", stages)

    def test_fills_missing_subfields(self) -> None:
        # 老数据：stages 已存在但子字段缺
        e = {"stages": {"req": {"round": 0}}}
        stages = ensure_stages(e)
        self.assertIsNone(stages["req"]["state"])

    def test_adds_missing_stage_keys(self) -> None:
        e = {"stages": {}}
        stages = ensure_stages(e)
        for s in STAGES + GATES + [RELEASE]:
            self.assertIn(s["name"], stages)


# ---- norm_product / product_path ----

class NormProduct(unittest.TestCase):
    def test_empty_passthrough(self) -> None:
        self.assertEqual(norm_product(""), "")
        self.assertEqual(norm_product(None), None)  # type: ignore[arg-type]

    def test_strips_workspace_prefix(self) -> None:
        self.assertEqual(norm_product("workspace/foo/bar.md"), "foo/bar.md")

    def test_strips_dot_slash_prefix(self) -> None:
        self.assertEqual(norm_product("./foo/bar.md"), "foo/bar.md")

    def test_strips_absolute_against_workspace(self) -> None:
        # WORKSPACE_DIR 在测试里被 StatectlTestCase 指向 tmp
        p = os.path.join(str(paths.WORKSPACE_DIR), "foo", "bar.md")
        self.assertEqual(norm_product(p), "foo/bar.md")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(norm_product("  foo/bar.md  "), "foo/bar.md")


class ProductPath(StatectlTestCase):
    def test_unregistered_project_falls_back_to_workspace(self) -> None:
        # 未登记 → 用 WORKSPACE_DIR/<p>
        got = product_path("foo/bar.md")
        self.assertEqual(got, os.path.join(paths.WORKSPACE_DIR, "foo/bar.md"))

    def test_registered_project_uses_work_path(self) -> None:
        wp = self.make_project("demo")
        # norm_product 去 WORKSPACE_DIR 前缀需要小心：用相对路径
        got = product_path("demo/input/REQ-1.md")
        self.assertEqual(got, os.path.join(wp, "input/REQ-1.md"))


# ---- set_stage_state 严格迁移校验 ----

class SetStageStateMigration(StatectlTestCase):
    """构造完整 entry（含 status）让 ensure_stages 正常工作。"""

    def _make_entry(self, plan_state: str | None = None,
                     plan_product: str | None = None,
                     release_state: str | None = None) -> dict:
        entry: dict = {"status": "pending"}
        ensure_stages(entry)
        if plan_state is not None:
            entry["stages"]["plan"]["state"] = plan_state
        if plan_product is not None:
            entry["stages"]["plan"]["product"] = plan_product
        if release_state is not None:
            entry["stages"]["release"]["state"] = release_state
        return entry

    def test_working_from_claimed(self) -> None:
        e = self._make_entry(plan_state="claimed")
        st = {"demo/REQ-1": e}
        ok, err = set_stage_state(st, "demo/REQ-1", "plan", "working")
        self.assertTrue(ok, err)
        self.assertEqual(e["stages"]["plan"]["state"], "working")

    def test_working_from_reviewing_fail_requeue(self) -> None:
        # reviewing → working：允许（FAIL 打回 / 评审修改轮）
        e = self._make_entry(plan_state="reviewing",
                              plan_product="demo/plans/REQ-1-r1.md")
        st = {"demo/REQ-1": e}
        ok, _ = set_stage_state(st, "demo/REQ-1", "plan", "working")
        self.assertTrue(ok)

    def test_working_from_done_rejected(self) -> None:
        e = self._make_entry(plan_state="done")
        st = {"demo/REQ-1": e}
        ok, err = set_stage_state(st, "demo/REQ-1", "plan", "working")
        self.assertFalse(ok)
        self.assertIn("不允许进入 working", err)

    def test_reviewing_requires_product(self) -> None:
        e = self._make_entry(plan_state="working")
        st = {"demo/REQ-1": e}
        ok, err = set_stage_state(st, "demo/REQ-1", "plan", "reviewing")
        self.assertFalse(ok)
        self.assertIn("reviewing 必须携带产物路径", err)

    def test_reviewing_with_product(self) -> None:
        e = self._make_entry(plan_state="working")
        st = {"demo/REQ-1": e}
        ok, err = set_stage_state(st, "demo/REQ-1", "plan", "reviewing",
                                    "demo/plans/REQ-1-r1.md")
        self.assertTrue(ok, err)
        self.assertEqual(e["stages"]["plan"]["product"], "demo/plans/REQ-1-r1.md")

    def test_reviewing_idempotent(self) -> None:
        e = self._make_entry(plan_state="reviewing",
                              plan_product="demo/plans/REQ-1-r1.md")
        st = {"demo/REQ-1": e}
        # reviewing → reviewing：幂等
        ok, _ = set_stage_state(st, "demo/REQ-1", "plan", "reviewing")
        self.assertTrue(ok)

    def test_done_only_from_reviewing(self) -> None:
        e = self._make_entry(plan_state="working")
        st = {"demo/REQ-1": e}
        ok, err = set_stage_state(st, "demo/REQ-1", "plan", "done")
        self.assertFalse(ok)
        self.assertIn("不允许进入 done", err)

    def test_unknown_state_rejected(self) -> None:
        e = self._make_entry()
        st = {"demo/REQ-1": e}
        ok, err = set_stage_state(st, "demo/REQ-1", "plan", "bogus")
        self.assertFalse(ok)
        self.assertIn("未知状态", err)

    def test_unknown_stage_rejected(self) -> None:
        e = self._make_entry()
        st = {"demo/REQ-1": e}
        ok, err = set_stage_state(st, "demo/REQ-1", "bogus", "working")
        self.assertFalse(ok)
        self.assertIn("未知阶段", err)

    def test_missing_entry_rejected(self) -> None:
        st: dict = {}
        ok, err = set_stage_state(st, "demo/REQ-1", "plan", "working")
        self.assertFalse(ok)
        self.assertIn("不存在", err)

    def test_top_status_derived_on_plan_done(self) -> None:
        e = self._make_entry(plan_state="reviewing")
        st = {"demo/REQ-1": e}
        set_stage_state(st, "demo/REQ-1", "plan", "done")
        self.assertEqual(e["status"], "plan_done")

    def test_top_status_derived_on_release_done(self) -> None:
        e = self._make_entry(release_state="reviewing")
        st = {"demo/REQ-1": e}
        set_stage_state(st, "demo/REQ-1", "release", "done")
        self.assertEqual(e["status"], "released")


# ---- prev_done_state ----

class PrevDoneState(unittest.TestCase):
    def test_analyzing_to_pending(self) -> None:
        self.assertEqual(prev_done_state({"status": "analyzing"}), "pending")

    def test_reviewing_to_analyzed(self) -> None:
        self.assertEqual(prev_done_state({"status": "reviewing"}), "analyzed")

    def test_releasing_to_last_stage_done(self) -> None:
        # 最后一阶段是 security → "security_done"
        self.assertEqual(prev_done_state({"status": "releasing"}), "security_done")

    def test_designing_to_prev_stage_done(self) -> None:
        # code_designing → testplan_done（前序 STAGES 阶段 = testplan）
        self.assertEqual(prev_done_state({"status": "code_designing"}), "testplan_done")

    def test_reviewing_to_redesign_self(self) -> None:
        # code_reviewing → code_designing（评审卡死 → 重新产出）
        self.assertEqual(prev_done_state({"status": "code_reviewing"}), "code_designing")

    def test_first_designing_to_approved(self) -> None:
        # plan_designing → approved（前一是 STAGES 之外，无对应完成态）
        self.assertEqual(prev_done_state({"status": "plan_designing"}), "approved")


# ---- rollback_entry ----

class RollbackEntry(StatectlTestCase):
    def test_mid_state_rollback(self) -> None:
        e = {"status": "code_designing", "failures": 0}
        st = {"demo/REQ-1": e}
        alarms: list = []
        rollback_entry(st, "demo/REQ-1", alarms, reason="test")
        self.assertEqual(e["status"], "testplan_done")  # code_designing → testplan_done
        self.assertEqual(e["failures"], 1)

    def test_non_mid_state_no_op(self) -> None:
        e = {"status": "pending", "failures": 0}
        st = {"demo/REQ-1": e}
        alarms: list = []
        rollback_entry(st, "demo/REQ-1", alarms, reason="test")
        self.assertEqual(e["status"], "pending")
        self.assertEqual(e["failures"], 0)

    def test_blocked_when_failures_reach_max(self) -> None:
        # MAX_FAILURES 默认 2；先累加到 1，再 +1 = 2 → blocked
        e = {"status": "code_designing", "failures": 1}
        st = {"demo/REQ-1": e}
        alarms: list = []
        rollback_entry(st, "demo/REQ-1", alarms, reason="test")
        self.assertEqual(e["status"], "blocked")
        self.assertEqual(e["failures"], 2)
        self.assertTrue(any("BLOCKED" in a for a in alarms))

    def test_clears_claim_fields(self) -> None:
        e = {"status": "code_designing", "failures": 0,
             "claimed_by": "fo", "claimed_at": "2026-01-01", "worker_pid": 12345}
        st = {"demo/REQ-1": e}
        alarms: list = []
        rollback_entry(st, "demo/REQ-1", alarms, reason="test")
        self.assertNotIn("claimed_by", e)
        self.assertNotIn("claimed_at", e)
        self.assertNotIn("worker_pid", e)


# ---- stale_recovery ----

class StaleRecovery(StatectlTestCase):
    def test_reclaims_only_mid_states_with_claim(self) -> None:
        # 无 claim 的中间态（waiting for claim）不回收
        st = {
            "demo/A": {"status": "code_designing"},  # 无 claim → 跳过
            "demo/B": {"status": "code_designing", "claimed_at": "2020-01-01T00:00:00Z"},  # 超时 + 无 pid → 回滚
        }
        alarms = stale_recovery(st)
        # A 不动；B 应回滚（status 从 designing 回到 testplan_done）
        self.assertEqual(st["demo/A"]["status"], "code_designing")
        self.assertEqual(st["demo/B"]["status"], "testplan_done")

    def test_skips_when_worker_alive(self) -> None:
        # claim 字段完整 + 存活 pid → 跳过（不回收）
        with mock.patch.object(pipeline, "pid_alive", return_value=True):
            st = {
                "demo/C": {"status": "code_designing",
                            "claimed_at": "2020-01-01T00:00:00Z",
                            "worker_pid": 999999},
            }
            alarms = stale_recovery(st)
            self.assertEqual(st["demo/C"]["status"], "code_designing")
            self.assertEqual(alarms, [])


# ---- claim / find_claimable ----

class FindClaimable(unittest.TestCase):
    def test_returns_oldest_unclaimed_with_matching_action(self) -> None:
        st = {
            "demo/A": {"status": "pending", "updated_at": "2026-01-02T00:00:00Z"},
            "demo/B": {"status": "pending", "updated_at": "2026-01-01T00:00:00Z"},
        }
        got = find_claimable(st, role="pm")
        self.assertIsNotNone(got)
        rid, _, _ = got
        self.assertEqual(rid, "demo/B")  # 最早 updated_at

    def test_skips_already_claimed(self) -> None:
        st = {
            "demo/A": {"status": "analyzing", "claimed_by": "pm"},  # 已认领
            "demo/B": {"status": "pending", "updated_at": "2026-01-01T00:00:00Z"},
        }
        got = find_claimable(st, role="pm")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], "demo/B")

    def test_returns_none_when_no_match(self) -> None:
        st = {"demo/A": {"status": "released"}}  # 无 next_action
        self.assertIsNone(find_claimable(st))

    def test_filters_by_role(self) -> None:
        st = {"demo/A": {"status": "pending"}}
        # 找 reviewer，但 next_action 给 pm → 不匹配
        self.assertIsNone(find_claimable(st, role="req-reviewer"))
        # 找 pm → 匹配
        self.assertIsNotNone(find_claimable(st, role="pm"))

    def test_supports_role_alias(self) -> None:
        st = {"demo/A": {"status": "analyzing"}}  # PM 阶段
        # alias analyst → req-analyst（不匹配 PM）
        self.assertIsNone(find_claimable(st, role="analyst"))
        # 直接 pm → 匹配
        self.assertIsNotNone(find_claimable(st, role="pm"))


class ClaimAtomicity(unittest.TestCase):
    def test_claim_succeeds_and_writes_fields(self) -> None:
        st = {"demo/REQ-1": {"status": "pending", "round": 0, "stages": {}}}
        ok = claim(st, "demo/REQ-1", "pm")
        self.assertTrue(ok)
        e = st["demo/REQ-1"]
        self.assertEqual(e["status"], "analyzing")
        self.assertEqual(e["claimed_by"], "pm")
        self.assertIn("claimed_at", e)
        self.assertEqual(e["worker_pid"], 0)

    def test_claim_fails_on_wrong_role(self) -> None:
        st = {"demo/REQ-1": {"status": "pending", "stages": {}}}
        self.assertFalse(claim(st, "demo/REQ-1", "req-reviewer"))

    def test_claim_fails_if_already_claimed(self) -> None:
        st = {"demo/REQ-1": {"status": "analyzing", "claimed_by": "pm",
                              "claimed_at": "2026-01-01T00:00:00Z"}}
        self.assertFalse(claim(st, "demo/REQ-1", "pm"))

    def test_claim_resets_done_to_claimed_for_redesign(self) -> None:
        # requeue 后旧 done 残留：phase=design + cur=done → 重置 claimed
        e = {"status": "code_designing", "stages": {"code": {"state": "done", "round": 1}}}
        st = {"demo/REQ-1": e}
        self.assertTrue(claim(st, "demo/REQ-1", "code-developer"))
        self.assertEqual(e["stages"]["code"]["state"], "claimed")


# ---- spawn_worker ----

class SpawnWorker(StatectlTestCase):
    def test_spawns_with_model_and_provider(self) -> None:
        # 用 mock 替换 subprocess.Popen，避免真的拉起 hermes
        fake_proc = mock.MagicMock(pid=12345)
        with mock.patch.object(pipeline.subprocess, "Popen", return_value=fake_proc) as m:
            pid = spawn_worker("code-developer", "demo/REQ-1", 1, "test query")
        self.assertEqual(pid, 12345)
        # 验证调用参数
        call = m.call_args
        cmd = call.args[0]
        self.assertEqual(cmd[0], "hermes")
        self.assertEqual(cmd[1], "chat")
        self.assertIn("-m", cmd)
        # model 取自 ROLE_MODELS["code-developer"] = (CODE_DEVELOPER_MODEL, CODE_PROVIDER)
        m_idx = cmd.index("-m")
        self.assertEqual(cmd[m_idx + 1], "deepseek-v4-flash")
        self.assertIn("--provider", cmd)

    def test_role_alias_resolved(self) -> None:
        # analyst alias → req-analyst 模型
        fake_proc = mock.MagicMock(pid=42)
        with mock.patch.object(pipeline.subprocess, "Popen", return_value=fake_proc) as m:
            spawn_worker("analyst", "demo/REQ-1", 1, "q")
        cmd = m.call_args.args[0]
        # req-analyst 模型 = ANALYST_MODEL = "deepseek-v4-flash"
        m_idx = cmd.index("-m")
        self.assertEqual(cmd[m_idx + 1], "deepseek-v4-flash")


# ---- build_worker_query ----

class BuildWorkerQuery(unittest.TestCase):
    def test_raises_on_role_mismatch(self) -> None:
        e = {"status": "pending", "round": 0}
        with self.assertRaises(RuntimeError):
            build_worker_query("req-reviewer", "demo/REQ-1", e)

    def test_req_design_returns_round_and_query(self) -> None:
        e = {"status": "pending", "round": 0}
        n, q = build_worker_query("pm", "demo/REQ-1", e)
        self.assertEqual(n, 1)
        self.assertIn("PM", q)
        self.assertIn("release_analyze", q)

    def test_req_review_returns_round_and_query(self) -> None:
        e = {"status": "reviewing", "round": 0, "analysis": "demo/analysis/REQ-1-r1.md",
             "reviews": [], "max_rounds": 3}
        n, q = build_worker_query("req-reviewer", "demo/REQ-1", e)
        self.assertEqual(n, 1)
        self.assertIn("release_review", q)
        self.assertIn("max_rounds=3", q)

    def test_stage_design_dir_kind_includes_task1(self) -> None:
        e = {"status": "code_designing", "round": 0,
             "stages": {"code": {"round": 0}}, "reviews": []}
        n, q = build_worker_query("code-developer", "demo/REQ-1", e)
        self.assertEqual(n, 1)
        self.assertIn("目录内创建全部源码", q)

    def test_stage_release_query_includes_tar_gz(self) -> None:
        e = {"status": "releasing", "round": 0,
             "stages": {"release": {"round": 0}}, "reviews": []}
        n, q = build_worker_query("releaser", "demo/REQ-1", e)
        self.assertEqual(n, 1)
        self.assertIn("tar.gz", q)


# ---- stage_inputs ----

class StageInputs(unittest.TestCase):
    def test_includes_analysis_label(self) -> None:
        e = {"status": "reviewing", "analysis": "demo/analysis/REQ-1-r1.md",
             "reviews": [], "stages": {}}
        outs = stage_inputs(e)
        labels = [o[0] for o in outs]
        # 必有"需求分析（approved 终版）"（需求原文路径推导要求 parts[0]=="analysis"，
        # 但生产环境下 analysis 字段是 "<project>/analysis/..."，所以"需求原文"未必出现）
        self.assertIn("需求分析（approved 终版）", labels)

    def test_includes_stage_terminal_products(self) -> None:
        e = {
            "status": "code_reviewing",
            "analysis": "demo/analysis/REQ-1-r1.md",
            "reviews": [],
            "stages": {"plan": {"product": "demo/plans/REQ-1-r1.md"}},
        }
        outs = stage_inputs(e)
        labels = [o[0] for o in outs]
        self.assertIn("plan 阶段终版", labels)

    def test_includes_gate_conclusions(self) -> None:
        e = {
            "status": "test_reviewing",
            "analysis": "demo/analysis/REQ-1-r1.md",
            "reviews": [],
            "stages": {"quality": {"product": "demo/quality/REQ-1-r1.md"}},
        }
        outs = stage_inputs(e)
        labels = [o[0] for o in outs]
        self.assertIn("quality 门禁结论", labels)


# ---- 调度前置 ----

class StageOrder(unittest.TestCase):
    def test_full_order(self) -> None:
        order = _stage_order()
        self.assertEqual(order, ["req", "plan", "testplan", "code", "test",
                                 "quality", "security", "release"])


class DepsSatisfied(unittest.TestCase):
    def test_no_deps_satisfied(self) -> None:
        self.assertTrue(_deps_satisfied({"depends_on": []}, {}))

    def test_all_deps_approved(self) -> None:
        e = {"_project": "demo", "depends_on": ["A", "B"]}
        st = {
            "demo/A": {"status": "approved"},
            "demo/B": {"status": "released"},
        }
        self.assertTrue(_deps_satisfied(e, st))

    def test_pending_dep_not_satisfied(self) -> None:
        e = {"_project": "demo", "depends_on": ["A"]}
        st = {"demo/A": {"status": "analyzing"}}
        self.assertFalse(_deps_satisfied(e, st))

    def test_missing_dep_treated_as_satisfied(self) -> None:
        # 依赖需求被删除 → 不阻塞
        e = {"_project": "demo", "depends_on": ["gone"]}
        self.assertTrue(_deps_satisfied(e, {}))


class IterationsPrevDone(unittest.TestCase):
    def test_iteration_one_no_constraint(self) -> None:
        e = {"_project": "demo", "version": "v1", "iteration": 1}
        self.assertTrue(_iterations_prev_done(e, {}))

    def test_prev_iter_must_be_released(self) -> None:
        e = {"_project": "demo", "version": "v1", "iteration": 2}
        st = {"demo/A": {"version": "v1", "iteration": 1, "status": "approved"}}
        # iteration 1 没 released → 不满足
        self.assertFalse(_iterations_prev_done(e, st))
        # released 后满足
        st["demo/A"]["status"] = "released"
        self.assertTrue(_iterations_prev_done(e, st))


class FindBlockStage(unittest.TestCase):
    def _entry_with(self, **stage_states: str | None) -> dict:
        """构造完整 entry（每阶段都有对应字段），便于测试 _find_block_stage 走全表。"""
        e: dict = {"status": "released"}
        ensure_stages(e)
        for n, s in stage_states.items():
            e["stages"][n]["state"] = s
        return e

    def test_returns_first_non_done_stage(self) -> None:
        e = self._entry_with(req="done", plan="done", testplan="done",
                              code="working")
        e["status"] = "code_designing"
        self.assertEqual(_find_block_stage(e), "code")

    def test_returns_none_when_all_done(self) -> None:
        e = self._entry_with(req="done", plan="done", testplan="done",
                              code="done", test="done",
                              quality="done", security="done",
                              release="done")
        self.assertIsNone(_find_block_stage(e))

    def test_top_status_proves_req_passed(self) -> None:
        # 顶层已 code_designing → req 视为通过（顶层状态证明）；返回首个未 done 的
        e = self._entry_with(req=None, plan="done", testplan="done",
                              code="working")
        e["status"] = "code_designing"
        self.assertEqual(_find_block_stage(e), "code")


# ---- active_stage ----

class ActiveStage(unittest.TestCase):
    def test_pending_returns_none(self) -> None:
        self.assertEqual(active_stage({"status": "pending"}), (None, None))

    def test_analyzing_returns_req(self) -> None:
        st, _ = active_stage({"status": "analyzing",
                               "stages": {"req": {"state": "working"}}})
        self.assertEqual(st, "req")

    def test_released_is_terminal_returns_none(self) -> None:
        # released 属于终态豁免：active_stage 返回 (None, None)
        self.assertEqual(active_stage({"status": "released"}), (None, None))

    def test_releasing_returns_release_working(self) -> None:
        st, _ = active_stage({"status": "releasing",
                                "stages": {"release": {"state": "working"}}})
        self.assertEqual(st, "release")


# ---- parse_conclusion ----

class ParseConclusion(unittest.TestCase):
    """parse_conclusion 是纯函数；用 TemporaryDirectory 不依赖 StatectlTestCase。"""

    def setUp(self) -> None:
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp_dir = self._td.name

    def tearDown(self) -> None:
        self._td.cleanup()

    def _write(self, body: str) -> str:
        p = os.path.join(self.tmp_dir, "review.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(body)
        return p


class ParseConclusionTests(ParseConclusion):
    def test_pass_with_conclusion_marker(self) -> None:
        p = self._write("... 结论：**PASS**\n其它内容")
        self.assertEqual(parse_conclusion(p), "PASS")

    def test_fail_with_conclusion_marker(self) -> None:
        p = self._write("... 结论：**FAIL**\n其它")
        self.assertEqual(parse_conclusion(p), "FAIL")

    def test_pass_via_pass_keyword_in_head(self) -> None:
        p = self._write("总体结论：PASS\n# review\n其它")
        self.assertEqual(parse_conclusion(p), "PASS")

    def test_fail_via_fail_keyword_in_head(self) -> None:
        p = self._write("FAIL\n# review")
        self.assertEqual(parse_conclusion(p), "FAIL")

    def test_unknown_when_no_marker(self) -> None:
        p = self._write("评审意见：\n- 第一条\n- 第二条\n无结论词")
        self.assertEqual(parse_conclusion(p), "UNKNOWN")

    def test_missing_file_returns_unknown(self) -> None:
        self.assertEqual(parse_conclusion("/nonexistent.md"), "UNKNOWN")


# ---- write_artifact ----

class WriteArtifact(StatectlTestCase):
    def test_writes_to_artifacts_dir(self) -> None:
        wp = self.make_project("demo")
        os.makedirs(os.path.join(wp, "input"), exist_ok=True)
        with open(os.path.join(wp, "input", "REQ-1.md"), "w") as f:
            f.write("# 原需求\n需求描述")
        e = {"status": "approved", "round": 1, "reviews": [], "forced": False,
             "stages": {}, "analysis": None}
        write_artifact("demo/REQ-1", e)
        out = os.path.join(wp, "artifacts", "REQ-1.md")
        self.assertTrue(os.path.exists(out))
        content = open(out, encoding="utf-8").read()
        self.assertIn("需求交付归档：REQ-1", content)
        self.assertIn("approved", content)

    def test_released_status_includes_release_section(self) -> None:
        wp = self.make_project("demo")
        os.makedirs(os.path.join(wp, "release"), exist_ok=True)
        os.makedirs(os.path.join(wp, "artifacts"), exist_ok=True)
        with open(os.path.join(wp, "release", "REQ-1-r1.md"), "w") as f:
            f.write("release notes")
        e = {"status": "released", "round": 1, "reviews": [],
             "stages": {"release": {"product": "demo/release/REQ-1-r1.md"}}}
        write_artifact("demo/REQ-1", e)
        out = os.path.join(wp, "artifacts", "REQ-1.md")
        content = open(out, encoding="utf-8").read()
        self.assertIn("完整交付", content)
        self.assertIn("发布说明", content)

    def test_forced_flag_adds_warning(self) -> None:
        wp = self.make_project("demo")
        os.makedirs(os.path.join(wp, "artifacts"), exist_ok=True)
        e = {"status": "approved", "round": 3, "reviews": [], "forced": True, "stages": {}}
        write_artifact("demo/REQ-1", e)
        content = open(os.path.join(wp, "artifacts", "REQ-1.md"), encoding="utf-8").read()
        self.assertIn("强制归档", content)


# ---- drain_alarms ----

class DrainAlarms(StatectlTestCase):
    def test_returns_empty_when_no_alarms(self) -> None:
        self.assertEqual(drain_alarms([]), "")

    def test_new_alerts_get_red_dot(self) -> None:
        out = drain_alarms(["[BLOCKED] 需求 X 卡死"])
        self.assertIn("🔴", out)

    def test_info_keywords_get_info_icon(self) -> None:
        out = drain_alarms(["worker 已重置"])
        self.assertIn("ℹ️", out)

    def test_unknown_gets_bullet(self) -> None:
        out = drain_alarms(["普通事件"])
        self.assertTrue(out.startswith("·"))

    def test_drains_existing_alarm_file(self) -> None:
        # 预写 ALARM_FILE
        os.makedirs(paths.LOG_DIR, exist_ok=True)
        with open(paths.ALARM_FILE, "w", encoding="utf-8") as f:
            f.write("[BLOCKED] 已卡死\n")
        out = drain_alarms([])
        self.assertIn("🔴", out)
        # 文件被清空
        self.assertEqual(open(paths.ALARM_FILE, encoding="utf-8").read(), "")


if __name__ == "__main__":
    unittest.main()