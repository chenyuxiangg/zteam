"""Tests for statectl_core.paths: 路径常量、项目映射、相对路径工具。"""
from __future__ import annotations

import json
import os
import unittest

from statectl_core import paths
from statectl_core.paths import (
    DEFAULT_PROJECT,
    PROJECTS_FILE,
    WORKDIR,
    WORKSPACE_DIR,
    ensure_project,
    now_iso,
    project_default,
    project_dir,
    project_lock_file,
    project_log_dir,
    project_status_file,
    project_work_path,
    read_projects,
    rel_analysis,
    rel_artifact,
    rel_input,
    rel_review,
    rel_stage_product,
    rel_stage_review,
    split_key,
    worker_log_name,
    write_projects,
)

from ._helpers import StatectlTestCase


class PathConstants(StatectlTestCase):
    def test_workdir_is_parent_of_scripts(self) -> None:
        # WORKDIR 应是 scripts/ 的父目录
        self.assertEqual(os.path.basename(self._paths_mod.SCRIPTS_DIR), "scripts")
        self.assertEqual(
            os.path.dirname(self._paths_mod.SCRIPTS_DIR),
            self._paths_mod.WORKDIR,
        )

    def test_workspace_and_log_dir_under_workdir(self) -> None:
        self.assertTrue(self._paths_mod.WORKSPACE_DIR.startswith(self._paths_mod.WORKDIR))
        self.assertTrue(self._paths_mod.LOG_DIR.startswith(self._paths_mod.WORKDIR))

    def test_default_project_is_default(self) -> None:
        self.assertEqual(self._paths_mod.DEFAULT_PROJECT, "default")


class NowIso(StatectlTestCase):
    def test_returns_utc_z_suffix(self) -> None:
        s = now_iso()
        # 形如 2026-09-22T12:34:56Z（精确长度 20）
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class SplitKey(unittest.TestCase):
    """split_key 是纯字符串处理，不依赖 WORKDIR——不需要 StatectlTestCase。"""

    def test_project_prefix(self) -> None:
        self.assertEqual(split_key("foo/bar"), ("foo", "bar"))

    def test_default_project_on_no_slash(self) -> None:
        self.assertEqual(split_key("bar"), ("default", "bar"))

    def test_empty_project_falls_back_to_default(self) -> None:
        # key 起始是 '/bar'（极少见；rsplit 后项目为空）
        self.assertEqual(split_key("/bar"), ("default", "bar"))

    def test_multiple_slashes_keep_rightmost_as_rid(self) -> None:
        # '/'-rsplit, maxsplit=1, 取最右一段作 rid
        self.assertEqual(split_key("a/b/c"), ("a/b", "c"))


class RelativePathTools(unittest.TestCase):
    """相对路径工具也是纯字符串函数，不读文件系统。"""

    def test_rel_input(self) -> None:
        self.assertEqual(rel_input("foo", "REQ-1"), "foo/input/REQ-1.md")

    def test_rel_analysis_includes_round(self) -> None:
        self.assertEqual(rel_analysis("foo", "REQ-1", 2), "foo/analysis/REQ-1-r2.md")

    def test_rel_review_includes_round(self) -> None:
        self.assertEqual(rel_review("foo", "REQ-1", 1), "foo/review/REQ-1-r1.md")

    def test_rel_artifact_no_round(self) -> None:
        self.assertEqual(rel_artifact("foo", "REQ-1"), "foo/artifacts/REQ-1.md")

    def test_rel_stage_product_file_kind(self) -> None:
        cfg = {"dir": "plans", "kind": "file"}
        self.assertEqual(rel_stage_product(cfg, "foo", "REQ-1", 1), "foo/plans/REQ-1-r1.md")

    def test_rel_stage_product_dir_kind(self) -> None:
        cfg = {"dir": "code", "kind": "dir"}
        self.assertEqual(rel_stage_product(cfg, "foo", "REQ-1", 2), "foo/code/REQ-1-r2/")

    def test_rel_stage_review(self) -> None:
        cfg = {"dir": "plans"}
        self.assertEqual(rel_stage_review(cfg, "foo", "REQ-1", 1), "foo/plans/REQ-1-r1-review.md")

    def test_worker_log_name_without_role(self) -> None:
        self.assertEqual(worker_log_name("foo", "REQ-1", 1), "worker-REQ-1-r1.log")

    def test_worker_log_name_with_role(self) -> None:
        self.assertEqual(worker_log_name("foo", "REQ-1", 2, "fo"), "worker-REQ-1-r2-fo.log")


class ProjectsMap(StatectlTestCase):
    def test_read_empty_when_missing(self) -> None:
        self.assertEqual(self.read_projects(), {"projects": []})

    def test_write_then_read_roundtrip(self) -> None:
        payload = {"projects": [{"name": "demo", "work_path": str(self.tmp / "demo")}]}
        self.write_projects(payload)
        got = self.read_projects()
        self.assertEqual(got["projects"][0]["name"], "demo")
        # updated_at 自动写入
        self.assertIn("updated_at", got)

    def test_write_is_atomic_via_tmp_replace(self) -> None:
        # 写入不应留 .tmp 残骸
        self.write_projects({"projects": [{"name": "x", "work_path": "/x"}]})
        self.assertFalse(os.path.exists(self._paths_mod.PROJECTS_FILE + ".tmp"))

    def test_project_work_path_returns_none_when_unknown(self) -> None:
        self.assertIsNone(project_work_path("nope"))

    def test_project_default_returns_none_when_no_default(self) -> None:
        self.write_projects({"projects": [{"name": "a", "work_path": "/a"}]})
        self.assertIsNone(project_default())

    def test_project_default_finds_default_flag(self) -> None:
        self.write_projects({"projects": [
            {"name": "a", "work_path": "/a"},
            {"name": "b", "work_path": "/b", "default": True},
        ]})
        self.assertEqual(project_default(), "b")


class ProjectDirs(StatectlTestCase):
    def test_project_dir_uses_work_path_when_registered(self) -> None:
        wp = self.make_project("demo")  # 自动登记到映射表
        self.assertEqual(project_dir("demo"), wp)

    def test_project_dir_falls_back_to_workspace_when_unregistered(self) -> None:
        fb = os.path.join(self._paths_mod.WORKSPACE_DIR, "ghost")
        self.assertEqual(project_dir("ghost"), fb)

    def test_project_status_file_under_project_dir(self) -> None:
        wp = self.make_project("demo")
        self.assertEqual(project_status_file("demo"), os.path.join(wp, "status.json"))

    def test_project_lock_file_under_project_dir(self) -> None:
        wp = self.make_project("demo")
        self.assertEqual(project_lock_file("demo"), os.path.join(wp, "status.lock"))

    def test_project_log_dir_under_project_dir(self) -> None:
        wp = self.make_project("demo")
        self.assertEqual(project_log_dir("demo"), os.path.join(wp, "logs"))


class EnsureProject(StatectlTestCase):
    def test_creates_all_subdirs_and_status_json(self) -> None:
        wp = self.make_project("demo")
        # 先把 status.json 删掉，确保 ensure_project 会重建
        if os.path.exists(os.path.join(wp, "status.json")):
            os.remove(os.path.join(wp, "status.json"))
        ensure_project("demo")
        for sub in ("input", "analysis", "review", "plans", "testplans", "code", "tests",
                    "quality", "security", "release", "artifacts", "archive", "logs"):
            self.assertTrue(os.path.isdir(os.path.join(wp, sub)), f"missing dir: {sub}")
        self.assertTrue(os.path.exists(os.path.join(wp, "status.json")))

    def test_idempotent(self) -> None:
        self.make_project("demo")
        # 跑两次不抛错也不破坏已有文件
        ensure_project("demo")
        ensure_project("demo")
        wp = self._paths_mod.project_dir("demo")
        self.assertTrue(os.path.isdir(os.path.join(wp, "input")))


if __name__ == "__main__":
    unittest.main()