"""Shared test helpers for statectl_core tests.

statectl_core 的多数函数读写 WORKDIR 下的全局路径（status.json / projects.json
/ logs/pipeline.log 等）。直接跑测试会污染真实工作区。每个 test 必须把
statectl_core.paths 里的路径常量临时指向 tmp_path；tearDown 还原。

用法::

    from ._helpers import StatectlTestCase, with_tmp_workdir

    class FooTest(StatectlTestCase):
        def test_x(self) -> None:
            self.write_projects({"projects": [{"name": "demo", "work_path": str(self.tmp / "demo")}]})
            ...
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterable

# Ensure `scripts/` is on sys.path so both `import statectl` (CLI shim) and
# `import statectl_core` resolve when tests are launched via
# `python3 -m unittest` from any cwd.
#   helpers.py → tests/ → statectl_core/ → scripts/  (三层 dirname)
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


# ---- Path constants that get redirected to tmp_path during a test ---------

# statectl_core.paths 暴露的所有可被重定向的路径名（实际值不重要，只是
# 标识位；具体重定向逻辑在 StatectlTestCase.setUp 里实现）。
_REDIRECTABLE_PATH_NAMES: tuple[str, ...] = (
    "WORKDIR",
    "WORKSPACE_DIR",
    "LOG_DIR",
    "SCRIPTS_DIR",
    "STATUS_FILE",
    "LOCK_FILE",
    "LOG_FILE",
    "ALARM_FILE",
    "PROJECTS_FILE",
    "NOTIFY_MARKER",
    "CONFIRM_REMINDED",
    "PAUSE_FILE",
)


class StatectlTestCase(unittest.TestCase):
    """Base class that points every WORKDIR-rooted path at a temp dir.

    子目录 (packages 包一层 __init__.py 时，import 子模块用 `statectl_core.paths`)，
    默认不预先 import——子模块测试按需 import 即可。setUp 不主动 import，
    只在第一次访问 self.paths 时懒加载（这样不需要 statectl_core 在测试里被
    强制引入就能运行纯 statectl.py 测试）。
    """

    _paths_mod = None  # class-level cache; per-test patching in setUp

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.workdir = self.tmp  # 别名：模拟 zteam 根目录

        # 懒加载 paths 子模块
        from statectl_core import paths as _paths  # noqa: WPS433
        self._paths_mod = _paths

        # 保存原值并在 tmp 下建立镜像目录
        self._saved: dict[str, Any] = {}
        for name in _REDIRECTABLE_PATH_NAMES:
            if hasattr(_paths, name):
                self._saved[name] = getattr(_paths, name)
        # WORKDIR 系列常量统一重定向到 tmp 根
        _paths.WORKDIR = str(self.tmp)
        _paths.SCRIPTS_DIR = str(self.tmp / "scripts")
        _paths.WORKSPACE_DIR = str(self.tmp / "workspace")
        _paths.LOG_DIR = str(self.tmp / "logs")
        _paths.STATUS_FILE = os.path.join(_paths.WORKSPACE_DIR, "status.json")
        _paths.LOCK_FILE = str(self.tmp / "status.lock")
        _paths.LOG_FILE = os.path.join(_paths.LOG_DIR, "pipeline.log")
        _paths.ALARM_FILE = os.path.join(_paths.LOG_DIR, "alarms.txt")
        _paths.PROJECTS_FILE = str(self.tmp / "projects.json")
        _paths.NOTIFY_MARKER = os.path.join(_paths.LOG_DIR, ".notify_marker")
        _paths.CONFIRM_REMINDED = os.path.join(_paths.LOG_DIR, ".confirm_reminded")
        _paths.PAUSE_FILE = str(self.tmp / ".pause")

        # 预创建必备目录
        for d in (_paths.WORKSPACE_DIR, _paths.LOG_DIR, _paths.SCRIPTS_DIR):
            os.makedirs(d, exist_ok=True)

    def tearDown(self) -> None:
        # 还原所有被改写的常量
        if self._paths_mod is not None:
            for name, value in self._saved.items():
                setattr(self._paths_mod, name, value)
        self._tmp.cleanup()
        super().tearDown()

    # ---- 项目 helpers ----

    def write_projects(self, payload: dict[str, Any]) -> None:
        """覆盖 projects.json（自动加 updated_at）。"""
        if self._paths_mod is None:
            raise RuntimeError("write_projects: StatectlTestCase.setUp 没跑")
        self._paths_mod.write_projects(payload)

    def read_projects(self) -> dict[str, Any]:
        if self._paths_mod is None:
            raise RuntimeError("read_projects: StatectlTestCase.setUp 没跑")
        return self._paths_mod.read_projects()

    def make_project(
        self,
        name: str,
        work_path: str | None = None,
        *,
        default: bool = False,
        latest_version: str | None = None,
    ) -> str:
        """登记一个项目到 projects.json 并建好 work_path 目录骨架。

        返回 work_path 字符串（方便测试断言）。"""
        if self._paths_mod is None:
            raise RuntimeError("make_project: StatectlTestCase.setUp 没跑")
        wp = work_path or str(self.tmp / "projects" / name)
        os.makedirs(wp, exist_ok=True)
        payload = self.read_projects()
        payload.setdefault("projects", [])
        # 替换同名项或追加
        payload["projects"] = [
            p for p in payload["projects"] if p.get("name") != name
        ]
        payload["projects"].append({
            "name": name,
            "work_path": wp,
            "default": default,
            **({"latest_version": latest_version} if latest_version else {}),
        })
        self.write_projects(payload)
        return wp


def assert_lines_equal(
    test: unittest.TestCase,
    actual: Iterable[str],
    expected: Iterable[str],
) -> None:
    """逐行比较，忽略末尾空行。"""
    actual_lines = [ln.rstrip() for ln in actual]
    expected_lines = [ln.rstrip() for ln in expected]
    test.assertEqual(actual_lines, expected_lines)


def read_json(path: str | os.PathLike[str]) -> Any:
    """读取 JSON 文件并返回解析结果；文件不存在抛 FileNotFoundError。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)