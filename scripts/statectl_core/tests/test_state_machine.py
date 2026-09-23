"""状态机迁移图谱测试（commit 7 强化）。

完整枚举 set_stage_state 的合法/非法迁移：
- 6 种起始状态（None / claimed / working / reviewing / done）×
  3 种目标状态（working / reviewing / done）
- 对每个 stage（req / plan / testplan / code / test / quality / security / gateX / release）
- 断言：合法迁移返回 (True, '')，非法返回 (False, 非空 err)
- 断言：非法迁移不修改状态

目的：捕捉状态机迁移规则的任何回归（拼错/漏分支/过松校验）。
"""
from __future__ import annotations

import unittest

from statectl_core.pipeline import (
    GATES,
    RELEASE,
    STAGES,
    ensure_stages,
    set_stage_state,
)


def _seed(stage: str, state):
    """构造最小 status 字典：含 demo/R1 + 目标阶段 + 指定初始 state。"""
    st = {
        "demo/R1": {
            "status": "pending",
            "round": 0,
            "max_rounds": 3,
            "forced": False,
            "analysis": None,
            "reviews": [],
            "failures": 0,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        }
    }
    s = ensure_stages(st["demo/R1"])
    s[stage]["state"] = state
    return st


def _all_stages():
    return ["req"] + [s["name"] for s in STAGES] + [g["name"] for g in GATES] + [RELEASE["name"]]


# 合法迁移表：(from_state, to_state) → 是否需 product 参数
_LEGAL = {
    (None, "working"):           {"need_product": False},
    ("claimed", "working"):      {"need_product": False},
    ("reviewing", "working"):    {"need_product": False},   # 返工
    ("working", "reviewing"):    {"need_product": True},
    ("reviewing", "reviewing"):  {"need_product": False},   # 幂等
    ("reviewing", "done"):       {"need_product": False},
}


class LegalTransitions(unittest.TestCase):
    """合法迁移全跑通：每个 stage × 合法 from/to 组合都成功。"""

    def test_all_legal_transitions(self) -> None:
        for stage in _all_stages():
            for (from_s, to_s), rule in _LEGAL.items():
                with self.subTest(stage=stage, from_s=from_s, to_s=to_s):
                    st = _seed(stage, from_s)
                    product = "demo/plans/R1-r1.md" if rule["need_product"] and stage != "req" else None
                    ok, err = set_stage_state(st, "demo/R1", stage, to_s, product)
                    self.assertTrue(ok, f"{stage}: {from_s}→{to_s} 应该合法，实际 err={err!r}")
                    self.assertEqual(err, "")
                    self.assertEqual(st["demo/R1"]["stages"][stage]["state"], to_s)


class IllegalTransitions(unittest.TestCase):
    """非法迁移全拒绝 + 不修改状态。"""

    def _assert_rejected(self, stage: str, from_s, to_s: str, product=None) -> None:
        st = _seed(stage, from_s)
        before_state = st["demo/R1"]["stages"][stage]["state"]
        before_top = st["demo/R1"]["status"]
        ok, err = set_stage_state(st, "demo/R1", stage, to_s, product)
        self.assertFalse(ok, f"{stage}: {from_s}→{to_s} 应该被拒绝，实际 ok")
        self.assertTrue(err, f"{stage}: {from_s}→{to_s} err 应非空")
        # 状态未被修改（顶层 + 阶段层都未变）
        self.assertEqual(st["demo/R1"]["stages"][stage]["state"], before_state,
                         f"{stage}: {from_s}→{to_s} 阶段状态被改了")
        self.assertEqual(st["demo/R1"]["status"], before_top,
                         f"{stage}: {from_s}→{to_s} 顶层 status 被改了")

    def test_skip_working_to_done(self) -> None:
        """working → done 是跳级，必须拒绝。"""
        for stage in _all_stages():
            self._assert_rejected(stage, "working", "done", "demo/plans/x.md")

    def test_done_terminal_no_reentry(self) -> None:
        """done 是终态：done → 任何状态都被拒绝。"""
        for stage in _all_stages():
            self._assert_rejected(stage, "done", "working")
            self._assert_rejected(stage, "done", "reviewing", "demo/plans/x.md")
            self._assert_rejected(stage, "done", "done")

    def test_none_to_reviewing_requires_working(self) -> None:
        """None → reviewing（不经过 working）必须拒绝。"""
        for stage in _all_stages():
            self._assert_rejected(stage, None, "reviewing", "demo/plans/x.md")

    def test_none_to_done_rejected(self) -> None:
        """None → done 直接跳到完成，必须拒绝。"""
        for stage in _all_stages():
            self._assert_rejected(stage, None, "done")

    def test_claimed_to_reviewing_requires_working(self) -> None:
        """claimed → reviewing 必须先 working（claimed 是 tick 刚认领，worker 未启动）。"""
        for stage in _all_stages():
            self._assert_rejected(stage, "claimed", "reviewing", "demo/plans/x.md")

    def test_reviewing_requires_product_for_non_req(self) -> None:
        """reviewing 必须带 product（req 阶段除外）。"""
        for stage in [s["name"] for s in STAGES] + [g["name"] for g in GATES] + [RELEASE["name"]]:
            # working → reviewing 但 product=None → 拒绝
            self._assert_rejected(stage, "working", "reviewing", product=None)

    def test_unknown_target_state(self) -> None:
        """未知 state 值直接拒绝。"""
        for bad in ("claimed", "approved", "", "foo", "Done"):
            with self.subTest(bad_state=bad):
                self._assert_rejected("plan", "working", bad, "demo/plans/x.md")

    def test_unknown_stage(self) -> None:
        """未知 stage 拒绝。"""
        st = _seed("plan", "working")
        ok, err = set_stage_state(st, "demo/R1", "no_such_stage", "done")
        self.assertFalse(ok)
        self.assertIn("未知阶段", err)

    def test_unknown_rid(self) -> None:
        """未知 rid 拒绝（不抛异常）。"""
        st = _seed("plan", "working")
        ok, err = set_stage_state(st, "no/such/rid", "plan", "done")
        self.assertFalse(ok)
        self.assertIn("不存在", err)


class TopLevelStatusDerivation(unittest.TestCase):
    """迁移后顶层 status 必须正确派生（commit 5 引入）。"""

    def test_req_done_awaits_user(self) -> None:
        st = _seed("req", "reviewing")
        set_stage_state(st, "demo/R1", "req", "done")
        self.assertEqual(st["demo/R1"]["status"], "awaiting_user_confirm")

    def test_release_done_marks_released(self) -> None:
        st = _seed(RELEASE["name"], "reviewing")
        set_stage_state(st, "demo/R1", RELEASE["name"], "done")
        self.assertEqual(st["demo/R1"]["status"], "released")

    def test_gate_done_marks_gate_done(self) -> None:
        for gate in GATES:
            stage = gate["name"]
            st = _seed(stage, "reviewing")
            set_stage_state(st, "demo/R1", stage, "done")
            self.assertEqual(st["demo/R1"]["status"], f"{stage}_done",
                             f"gate {stage} done 后顶层应是 {stage}_done")

    def test_stage_designing_marks_designing(self) -> None:
        for stage_def in STAGES:
            stage = stage_def["name"]
            st = _seed(stage, None)
            set_stage_state(st, "demo/R1", stage, "working")
            self.assertEqual(st["demo/R1"]["status"], f"{stage}_designing")


if __name__ == "__main__":
    unittest.main()
