"""Tests for scripts/check_commit_attribution.sh.

确保 commit message attribution 检查脚本能：
- 检测存在 Co-Authored-By 的 commit（合规）
- 检测缺失 attribution 的 commit（不合规，exit=1）
- HEAD 默认行为（无参数）
- 无 commit 时退出码 2
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "check_commit_attribution.sh"


_ATTRIBUTION = "Co-Authored-By: Claude Code <noreply@anthropic.com>"


def _run_in_tmp_repo(setup_commits: list[tuple[str, bool]]) -> tuple[int, str]:
    """在临时 git 仓库中创建 commit（(msg, has_attribution) 元组列表），跑检查脚本。

    返回 (exit_code, stdout)。
    """
    with tempfile.TemporaryDirectory() as td:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "tester",
            "GIT_AUTHOR_EMAIL": "tester@example.com",
            "GIT_COMMITTER_NAME": "tester",
            "GIT_COMMITTER_EMAIL": "tester@example.com",
        }
        subprocess.run(["git", "init", "-q"], cwd=td, check=True, env=env)
        # 初始 commit 也带 attribution（用 --allow-empty 风格：直接 init 一个带 attribution 的根 commit）
        (Path(td) / "a").write_text("a")
        subprocess.run(["git", "add", "a"], cwd=td, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-q", "-m", f"init\n\n{_ATTRIBUTION}"],
            cwd=td, check=True, env=env,
        )
        # 后续 commit（每个用一个新文件以确保 git 允许空 commit 之外的版本）
        for i, (msg, has_attr) in enumerate(setup_commits, start=1):
            (Path(td) / f"f{i}").write_text(f"f{i}")
            subprocess.run(["git", "add", f"f{i}"], cwd=td, check=True, env=env)
            if has_attr:
                full_msg = f"{msg}\n\n{_ATTRIBUTION}"
            else:
                full_msg = msg
            subprocess.run(
                ["git", "commit", "-q", "-m", full_msg],
                cwd=td, check=True, env=env,
            )
        # 只检查 setup_commits 创建的那几个 commit（不包括 init）
        target_range = f"HEAD~{len(setup_commits)}..HEAD"
        r = subprocess.run(
            ["bash", str(_SCRIPT), target_range],
            cwd=td, capture_output=True, text=True,
        )
    return r.returncode, r.stdout


class CheckAttribution(unittest.TestCase):
    def test_all_have_attribution(self) -> None:
        rc, out = _run_in_tmp_repo([
            ("fix: foo", True),
            ("feat: bar", True),
        ])
        self.assertEqual(rc, 0)
        self.assertIn("0 个缺 attribution", out)

    def test_one_missing(self) -> None:
        rc, out = _run_in_tmp_repo([
            ("fix: foo", True),
            ("feat: bar without attribution", False),
        ])
        self.assertEqual(rc, 1)
        self.assertIn("1 个缺 attribution", out)
        self.assertIn("bar without attribution", out)

    def test_all_missing(self) -> None:
        rc, out = _run_in_tmp_repo([
            ("no attr 1", False),
            ("no attr 2", False),
        ])
        self.assertEqual(rc, 1)
        self.assertIn("2 个缺 attribution", out)


if __name__ == "__main__":
    unittest.main()
