"""Public API 一致性 + 重复定义 + 死 import 安全网（commit 8）。

死代码清理的 3 个安全网，确保删/合不会破坏外部契约：

1. test_public_api_each_name_importable
   每个 .py 模块的 __all__ 中每个名字都能 `from <module> import <name>`。
   防止：__all__ 残留旧名（commit 6 删过但漏了某个 __all__ 入口）。

2. test_no_duplicate_definitions
   列举已知的重复定义位置（release_arch/release_testplan_v2/_version_unblock/
   _stage_order/_find_block_stage/VERSIONS_FILE），断言只有 live 位置还
   持有 def（其它位置必须已删）。
   防止：合并重复定义时漏删一个。

3. test_no_dead_imports_after_cleanup
   列出本次清理要删的 import 别名（_paths, _status, DEFAULT_MAX_ROUNDS 等），
   断言这些别名在删除位置不再被引用（防 lint-only 删后破坏运行）。

执行批次 1/2/3 时，这些测试必须保持通过；任何一个失败 = 漏删或误删。
"""
from __future__ import annotations

import importlib
import unittest


# 每个模块的 (module_name, __all__) — 用 importlib 动态拿，避开硬编码漂移
_PUBLIC_MODULES = (
    "statectl_core.commands",
    "statectl_core.diagnose",
    "statectl_core.issues",
    "statectl_core.model_config",
    "statectl_core.modules",
    "statectl_core.paths",
    "statectl_core.pipeline",
    "statectl_core.qa",
    "statectl_core.release",
    "statectl_core.resources",
    "statectl_core.status",
    "statectl_core.ticks",
    "statectl_core.versions",
)


class TestPublicApiImportable(unittest.TestCase):
    """每个模块的 __all__ 中每个名字都能 import。"""

    def test_each_all_name_importable(self) -> None:
        for mod_name in _PUBLIC_MODULES:
            with self.subTest(module=mod_name):
                mod = importlib.import_module(mod_name)
                all_names = getattr(mod, "__all__", None)
                self.assertIsNotNone(all_names, f"{mod_name} 无 __all__")
                for name in all_names:
                    with self.subTest(module=mod_name, name=name):
                        self.assertTrue(
                            hasattr(mod, name),
                            f"{mod_name}.{name} 在 __all__ 声明但模块无此属性",
                        )


# 已知的重复定义位置（活版本 + 应删除位置）
# (name, live_module, live_attr, dead_module, dead_attr, dead_line)
_KNOWN_DUPLICATES = [
    # release_arch: live=versions, dead=issues
    ("release_arch", "versions", "release_arch", "issues", "release_arch"),
    # release_testplan_v2: live=versions, dead=issues
    ("release_testplan_v2", "versions", "release_testplan_v2",
     "issues", "release_testplan_v2"),
    # _version_unblock: live=resources, dead=versions
    ("_version_unblock", "resources", "_version_unblock",
     "versions", "_version_unblock"),
    # _stage_order: live=pipeline, dead=commands
    ("_stage_order", "pipeline", "_stage_order", "commands", "_stage_order"),
    # _find_block_stage: live=pipeline, dead=commands
    ("_find_block_stage", "pipeline", "_find_block_stage",
     "commands", "_find_block_stage"),
]


def _def_defined_in(mod, attr: str) -> bool:
    """检查 attr 是否在 mod 中以 def 形式定义（而非仅通过 import 暴露）。"""
    import inspect
    obj = getattr(mod, attr, None)
    if obj is None:
        return False
    # 如果是从其它模块 import 来的，__module__ != 当前模块
    return getattr(obj, "__module__", None) == mod.__name__


class TestNoDuplicateDefinitions(unittest.TestCase):
    """重复定义合并安全网：每个名字只有 live 位置还持有 def，dead 位置必须已删。"""

    def test_live_locations_exist(self) -> None:
        for name, live_mod, live_attr, _, _ in _KNOWN_DUPLICATES:
            with self.subTest(name=name, location="live"):
                mod = importlib.import_module(f"statectl_core.{live_mod}")
                self.assertTrue(
                    _def_defined_in(mod, live_attr),
                    f"live 实现 statectl_core.{live_mod}.{live_attr} 未以 def 形式定义",
                )

    def test_dead_locations_removed(self) -> None:
        for name, _, _, dead_mod, dead_attr in _KNOWN_DUPLICATES:
            with self.subTest(name=name, location="dead"):
                mod = importlib.import_module(f"statectl_core.{dead_mod}")
                self.assertFalse(
                    _def_defined_in(mod, dead_attr),
                    f"dead 副本 statectl_core.{dead_mod}.{dead_attr} 仍以 def 形式定义",
                )

    def test_duplicate_constants_removed(self) -> None:
        """VERSIONS_FILE 只在 versions.py 定义（paths.py 版本应删除）。"""
        paths_mod = importlib.import_module("statectl_core.paths")
        versions_mod = importlib.import_module("statectl_core.versions")
        # paths.py 应不再有 VERSIONS_FILE（live 在 versions.py）
        self.assertFalse(
            hasattr(paths_mod, "VERSIONS_FILE"),
            "paths.VERSIONS_FILE 是重复定义，应删除",
        )
        # versions.py 必须保留 VERSIONS_FILE（live）
        self.assertTrue(
            hasattr(versions_mod, "VERSIONS_FILE"),
            "versions.VERSIONS_FILE 是 live，必须保留",
        )


# 本次清理要删的 import 别名 / 函数（用于"防回滚"检查）
# (module, attr_name) — 这些名字应不再出现在对应模块里
_DEAD_NAMES_TO_REMOVE = [
    # 批次 1：未使用 import / 保活
    ("pipeline", "_status"),                       # 5.1
    ("versions", "_paths"),                        # 5.4
    ("commands", "MODULE_TYPES"),                  # 5.2
    ("commands", "abs_artifact"),                  # 5.2
    ("modules", "abs_artifact"),                   # 5.3
    # 批次 1：空 stub
    ("pipeline", "_stage_state"),                  # 1.6 / 4.1
    # 批次 2：仅测试用
    ("resources", "_resource_blocked_reason"),     # 1.4
]


class TestDeadNamesRemoved(unittest.TestCase):
    """批次清理安全网：每个 dead 名字在对应模块必须已删除。"""

    def test_dead_names_not_present(self) -> None:
        for mod_name, attr in _DEAD_NAMES_TO_REMOVE:
            with self.subTest(module=mod_name, attr=attr):
                mod = importlib.import_module(f"statectl_core.{mod_name}")
                self.assertFalse(
                    hasattr(mod, attr),
                    f"statectl_core.{mod_name}.{attr} 应已删除（仍存在 = 漏删）",
                )


class TestUnchangedApis(unittest.TestCase):
    """批次清理不能误伤：高频引用 API 仍必须可访问。"""

    def test_main_still_entry(self) -> None:
        from statectl_core import main
        self.assertTrue(callable(main))

    def test_quota_tick_still_entry(self) -> None:
        from statectl_core import quota_tick
        self.assertTrue(callable(quota_tick))

    def test_diagnose_still_entry(self) -> None:
        from statectl_core import diagnose
        self.assertTrue(callable(diagnose))

    def test_status_api(self) -> None:
        from statectl_core.status import read_status, write_status, acquire_lock, log
        for fn in (read_status, write_status, acquire_lock, log):
            self.assertTrue(callable(fn))

    def test_pipeline_core(self) -> None:
        from statectl_core.pipeline import (
            STAGES, GATES, RELEASE, MID_STATES, ensure_stages,
            set_stage_state, claim, find_claimable, stale_recovery,
        )
        for x in (STAGES, GATES, RELEASE, MID_STATES):
            self.assertIsNotNone(x)
        for fn in (ensure_stages, set_stage_state, claim, find_claimable, stale_recovery):
            self.assertTrue(callable(fn))

    def test_versions_core(self) -> None:
        from statectl_core.versions import (
            ensure_versions, read_versions, write_versions,
            release_it, release_st, release_arch, release_testplan_v2,
            cmd_confirm, cmd_reject, cmd_assign,
        )
        for fn in (ensure_versions, read_versions, write_versions,
                   release_it, release_st, release_arch, release_testplan_v2,
                   cmd_confirm, cmd_reject, cmd_assign):
            self.assertTrue(callable(fn))


if __name__ == "__main__":
    unittest.main()
