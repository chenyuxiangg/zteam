"""Tests for statectl_core.model_config: 模型常量、ROLE_* 映射完整性。"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from statectl_core import model_config
from statectl_core.model_config import (
    ANALYST_MODEL,
    ANALYST_PROVIDER,
    CODE_PROVIDER,
    DEFAULT_MAX_ROUNDS,
    FO_MODEL,
    FO_PROVIDER,
    MAX_FAILURES,
    PM_MODEL,
    ROLE_CN,
    ROLE_FILES,
    ROLE_MODELS,
    STALE_AFTER_MIN,
)

from ._helpers import StatectlTestCase


class DefaultConstants(unittest.TestCase):
    def test_stale_after_min_default(self) -> None:
        # 20 分钟（中间态超时）
        self.assertEqual(model_config.STALE_AFTER_MIN, 20)

    def test_max_failures_default(self) -> None:
        self.assertEqual(model_config.MAX_FAILURES, 2)

    def test_default_max_rounds(self) -> None:
        self.assertEqual(model_config.DEFAULT_MAX_ROUNDS, 3)

    def test_analyst_default_model(self) -> None:
        self.assertEqual(ANALYST_MODEL, "deepseek-v4-flash")

    def test_analyst_default_provider(self) -> None:
        self.assertEqual(ANALYST_PROVIDER, "deepseek")

    def test_pm_uses_pro(self) -> None:
        # PM/SE/TE 用 pro 强推理（v2 八角色）
        self.assertIn("pro", PM_MODEL)

    def test_fo_uses_minimax(self) -> None:
        self.assertEqual(FO_MODEL, "MiniMax-M3")
        self.assertEqual(FO_PROVIDER, "minimax-cn")

    def test_code_provider_default(self) -> None:
        # 2026-08-15 临时切 DeepSeek
        self.assertEqual(CODE_PROVIDER, "deepseek")


class EnvOverrides(unittest.TestCase):
    """环境变量覆盖必须生效；模块在 import 时快照环境变量。"""

    def _reload(self, env: dict[str, str]) -> dict:
        """在 mock 环境下重 import 模块，返回新模块对象。"""
        with mock.patch.dict(os.environ, env, clear=False):
            import importlib
            return importlib.reload(model_config)

    def test_analyst_model_override(self) -> None:
        new = self._reload({"ANALYST_MODEL": "test-model-X"})
        self.assertEqual(new.ANALYST_MODEL, "test-model-X")
        # 也得进入 ROLE_MODELS 映射
        self.assertEqual(new.ROLE_MODELS["req-analyst"][0], "test-model-X")

    def test_stale_after_min_override(self) -> None:
        new = self._reload({"STALE_AFTER_MIN": "99"})
        self.assertEqual(new.STALE_AFTER_MIN, 99)

    def test_max_failures_override(self) -> None:
        new = self._reload({"MAX_FAILURES": "5"})
        self.assertEqual(new.MAX_FAILURES, 5)

    def test_default_max_rounds_override(self) -> None:
        new = self._reload({"DEFAULT_MAX_ROUNDS": "10"})
        self.assertEqual(new.DEFAULT_MAX_ROUNDS, 10)


class RoleModelsMapping(unittest.TestCase):
    """ROLE_MODELS 必须覆盖所有 worker 角色；每个值都是 (model, provider) 二元组。"""

    EXPECTED_ROLES = {
        "req-analyst", "req-reviewer",
        "pm", "se", "te", "mde", "fo", "mto", "sto", "qa",
        "dev-plan-designer", "dev-plan-reviewer",
        "test-plan-designer", "test-plan-reviewer",
        "code-developer", "code-reviewer",
        "test-developer", "test-reviewer",
        "quality-reviewer", "security-reviewer",
        "releaser",
        "it-designer", "it-reviewer",
        "st-tester", "st-reviewer",
    }

    def test_covers_all_expected_roles(self) -> None:
        self.assertEqual(set(ROLE_MODELS.keys()), self.EXPECTED_ROLES)

    def test_values_are_model_provider_pairs(self) -> None:
        for role, (model, provider) in ROLE_MODELS.items():
            self.assertIsInstance(model, str, f"{role} model 非字符串")
            self.assertIsInstance(provider, str, f"{role} provider 非字符串")
            self.assertTrue(model, f"{role} model 为空")
            self.assertTrue(provider, f"{role} provider 为空")


class RoleFilesMapping(StatectlTestCase):
    """ROLE_FILES 路径：v1/v2 八角色用绝对路径（worker cwd 是项目工作路径），it-* 用相对路径。"""

    EXPECTED_ROLES = {
        "req-analyst", "req-reviewer",
        "pm", "se", "te", "mde", "fo", "mto", "sto", "qa",
        "dev-plan-designer", "dev-plan-reviewer",
        "test-plan-designer", "test-plan-reviewer",
        "code-developer", "code-reviewer",
        "test-developer", "test-reviewer",
        "quality-reviewer", "security-reviewer",
        "releaser",
        "it-designer", "it-reviewer",
        "st-tester", "st-reviewer",
    }

    def test_covers_all_expected_roles(self) -> None:
        self.assertEqual(set(ROLE_FILES.keys()), self.EXPECTED_ROLES)

    def test_v1_v2_eight_roles_use_absolute_paths(self) -> None:
        # req-* / dev-plan-* / test-plan-* / code-* / test-* / quality-* /
        # security-* + pm/se/te/mde/fo/mto/sto/qa 走绝对路径（WORKDIR/roles/）
        # releaser 走相对路径（与 it-*/st-* 同——worker cwd 已是项目工作路径）
        abs_roles = [
            r for r in self.EXPECTED_ROLES
            if not r.startswith(("it-", "st-")) and r != "releaser"
        ]
        for r in abs_roles:
            self.assertTrue(
                ROLE_FILES[r].startswith("/"),
                f"{r} 应是绝对路径: {ROLE_FILES[r]!r}",
            )
            self.assertIn(
                f"/roles/{r}.md", ROLE_FILES[r],
                f"{r} 应含 /roles/<role>.md: {ROLE_FILES[r]!r}",
            )

    def test_relative_path_roles(self) -> None:
        # it-* / st-* / releaser 走相对路径（worker cwd 是项目工作路径）
        for r in ("releaser", "it-designer", "it-reviewer", "st-tester", "st-reviewer"):
            self.assertFalse(
                ROLE_FILES[r].startswith("/"),
                f"{r} 应是相对路径: {ROLE_FILES[r]!r}",
            )
            self.assertTrue(
                ROLE_FILES[r].startswith("roles/"),
                f"{r} 应以 roles/ 开头: {ROLE_FILES[r]!r}",
            )


class RoleCnMapping(unittest.TestCase):
    EXPECTED_ROLES = {
        "req-analyst", "req-reviewer",
        "pm", "se", "te", "mde", "fo", "mto", "sto", "qa",
        "dev-plan-designer", "dev-plan-reviewer",
        "test-plan-designer", "test-plan-reviewer",
        "code-developer", "code-reviewer",
        "test-developer", "test-reviewer",
        "quality-reviewer", "security-reviewer",
        "releaser",
        "it-designer", "it-reviewer",
        "st-tester", "st-reviewer",
    }

    def test_covers_all_expected_roles(self) -> None:
        self.assertEqual(set(ROLE_CN.keys()), self.EXPECTED_ROLES)

    def test_values_are_non_empty_strings(self) -> None:
        for role, cn in ROLE_CN.items():
            self.assertIsInstance(cn, str)
            self.assertTrue(cn.strip(), f"{role} 中文名为空")


if __name__ == "__main__":
    unittest.main()