"""Smoke tests: statectl_core 包可以被 import，子模块均能加载。"""
from __future__ import annotations

import importlib
import unittest

from ._helpers import _SCRIPTS


class PackageImportable(unittest.TestCase):
    def test_import_statectl_core(self) -> None:
        mod = importlib.import_module("statectl_core")
        self.assertTrue(mod.__doc__)

    def test_scripts_on_sys_path(self) -> None:
        # _helpers 已经把 scripts 加到 sys.path；这里再断言一遍确保 helper 没退化
        self.assertIn(_SCRIPTS, __import__("sys").path)

    def test_submodule_paths_loads(self) -> None:
        mod = importlib.import_module("statectl_core.paths")
        self.assertTrue(hasattr(mod, "WORKDIR"))

    def test_submodule_status_loads(self) -> None:
        mod = importlib.import_module("statectl_core.status")
        self.assertTrue(hasattr(mod, "read_status"))

    def test_submodule_model_config_loads(self) -> None:
        mod = importlib.import_module("statectl_core.model_config")
        self.assertTrue(hasattr(mod, "ROLE_MODELS"))


if __name__ == "__main__":
    unittest.main()