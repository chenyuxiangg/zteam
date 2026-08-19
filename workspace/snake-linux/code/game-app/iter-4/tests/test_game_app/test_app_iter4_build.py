"""G4-1 构建脚本 / 打包资源 UT（UT BUILD-1~3 + SPEC 补充 + G4-5 字体资产）。

构建脚本冒烟（不真正执行 PyInstaller——本机无 pyinstaller 且无显示环境，
仅做静态冒烟：脚本存在 / bash 语法合法 / 关键命令存在）：

- BUILD-1（Linux）：scripts/build_linux.sh 存在 + bash -n 语法合法
- BUILD-2（Windows）：scripts/build_windows.bat 存在 + 关键命令（pyinstaller）存在
- BUILD-3（macOS）：scripts/build_macos.sh 存在 + bash -n 语法合法
- GEN-SHA：scripts/gen_sha256sums.sh 存在 + 调用 sha256sum
- 字体资产：game_app/fonts/SourceHanSansCN-Regular.otf 存在（G4-5）
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("SNAKE_LINUX_ROOT", "/home/zyzs/cyx/zteam/snake-linux"))
SCRIPTS_DIR = ROOT / "scripts"

# 打包源码根（iter-4 交付目录；真实代码在 workspace 数据层）
CODE_DIR = Path(os.environ.get(
    "SNAKE_LINUX_CODE_DIR",
    "/home/zyzs/cyx/zteam/workspace/snake-linux/code/game-app/iter-4",
))


class TestBuildLinux:
    """BUILD-1：Linux ELF 构建脚本静态冒烟。"""

    def test_script_exists(self):
        assert (SCRIPTS_DIR / "build_linux.sh").exists()

    def test_bash_syntax_valid(self):
        """bash -n 语法检查通过。"""
        r = subprocess.run(
            ["bash", "-n", str(SCRIPTS_DIR / "build_linux.sh")],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"build_linux.sh 语法错误: {r.stderr}"

    def test_invokes_pyinstaller(self):
        src = (SCRIPTS_DIR / "build_linux.sh").read_text(encoding="utf-8")
        assert "pyinstaller" in src
        assert "snake-gui.spec" in src

    def test_spec_entry_point_exists(self):
        """检视 F-1 回归：spec 候选目录中至少一个存在 __main__.py（入口可达）。

        本机无 pyinstaller 无法真实构建，但至少必须验证 spec 引用的
        代码目录真实存在入口文件——否则三平台打包矩阵在 Analysis 阶段必败。
        """
        import re
        import os as os_mod
        spec_src = (ROOT / "spec" / "snake-gui.spec").read_text(encoding="utf-8")
        specpath = str(ROOT / "spec")
        m = None
        for var in ("GAME_APP_CANDIDATES", "GAME_APP_DIR"):
            m = re.search(rf"{var}\s*=\s*(\[.*?\])", spec_src, re.DOTALL)
            if m:
                break
        assert m, "spec 未定义 GAME_APP_CANDIDATES/GAME_APP_DIR 列表"
        candidates = eval(m.group(1), {"os": os_mod, "SPECPATH": specpath})
        assert any(
            os_mod.path.isfile(os_mod.path.join(c, "__main__.py")) for c in candidates
        ), f"spec 所有候选入口均不存在: {candidates}"


class TestBuildWindows:
    """BUILD-2：Windows .exe 构建脚本静态冒烟。"""

    def test_script_exists(self):
        assert (SCRIPTS_DIR / "build_windows.bat").exists()

    def test_invokes_pyinstaller(self):
        src = (SCRIPTS_DIR / "build_windows.bat").read_text(encoding="utf-8")
        assert "pyinstaller" in src.lower()
        assert "snake-gui.spec" in src

    def test_output_name(self):
        src = (SCRIPTS_DIR / "build_windows.bat").read_text(encoding="utf-8")
        assert ".exe" in src


class TestBuildMacos:
    """BUILD-3：macOS .app 构建脚本静态冒烟。"""

    def test_script_exists(self):
        assert (SCRIPTS_DIR / "build_macos.sh").exists()

    def test_bash_syntax_valid(self):
        r = subprocess.run(
            ["bash", "-n", str(SCRIPTS_DIR / "build_macos.sh")],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"build_macos.sh 语法错误: {r.stderr}"

    def test_dual_arch(self):
        src = (SCRIPTS_DIR / "build_macos.sh").read_text(encoding="utf-8")
        assert "x86_64" in src or "intel" in src.lower()
        assert "arm64" in src or "universal" in src.lower()


class TestGenSha256Sums:
    """GEN-SHA：SHA256SUMS 生成脚本冒烟。"""

    def test_script_exists(self):
        assert (SCRIPTS_DIR / "gen_sha256sums.sh").exists()

    def test_bash_syntax_valid(self):
        r = subprocess.run(
            ["bash", "-n", str(SCRIPTS_DIR / "gen_sha256sums.sh")],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"gen_sha256sums.sh 语法错误: {r.stderr}"

    def test_uses_sha256sum(self):
        src = (SCRIPTS_DIR / "gen_sha256sums.sh").read_text(encoding="utf-8")
        assert "sha256sum" in src


class TestPackagedFontAsset:
    """G4-5：打包内置字体资产存在性。"""

    def test_font_file_exists_in_iter4(self):
        """iter-4 交付目录 game_app/fonts/ 含 SourceHanSansCN-Regular.otf。"""
        font = CODE_DIR / "game_app" / "fonts" / "SourceHanSansCN-Regular.otf"
        assert font.exists(), f"字体不存在: {font}"
        assert font.stat().st_size > 100000, "字体文件过小（疑似占位）"

    def test_font_license_note(self):
        """字体目录含 license/README 说明（OFL 协议）。"""
        fonts_dir = CODE_DIR / "game_app" / "fonts"
        notes = [p for p in fonts_dir.iterdir() if p.suffix in (".md", ".txt", ".license")]
        assert notes, "fonts/ 目录缺少 license/README 说明文件"

    def test_font_used_in_spec_datas(self):
        """spec datas 包含字体文件（与 get_bundled_font_path 一致）。"""
        spec_src = (ROOT / "spec" / "snake-gui.spec").read_text(encoding="utf-8")
        assert "SourceHanSansCN-Regular.otf" in spec_src


class TestReleaseAssets:
    """NFR-07：发布物清单（release/ 目录）。"""

    def test_release_dir_has_docs(self):
        for name in ["USER_GUIDE.md", "RELEASE_NOTES.md", "SHA256SUMS"]:
            assert (ROOT / "release" / name).exists(), f"release/ 缺少 {name}"
