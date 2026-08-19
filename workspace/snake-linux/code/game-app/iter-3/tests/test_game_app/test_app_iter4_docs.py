"""G4-4 用户指南 / G4-6 发布说明 / G4-1 SHA256SUMS UT（UT GUIDE-1~3 / REL-1~2 / SHA-1~2）。

被测文档位于仓库权威目录 snake-linux/release/（不在 workspace 下）：
- USER_GUIDE.md：五节齐全（下载运行/键位表/难度/皮肤/暂停/平台差异/已知限制）
- RELEASE_NOTES.md：v2.0.0 changelog + 功能列表
- SHA256SUMS：<64-hex>  <file> 格式
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import pytest

ROOT = Path(os.environ.get("SNAKE_LINUX_ROOT", "/home/zyzs/cyx/zteam/snake-linux"))
RELEASE_DIR = ROOT / "release"

# 五节标题（G4-4 设计要求）
REQUIRED_SECTIONS = ["下载与运行", "键位表", "难度", "皮肤", "暂停", "平台差异", "已知限制"]
# 键位表必含键（GUIDE-3）
REQUIRED_KEYS = ["W", "A", "S", "D", "P", "ESC", "Q", "R", "H"]


class TestUserGuide:
    """GUIDE-1/2/3：USER_GUIDE.md 字段完备性。"""

    @pytest.fixture(scope="class")
    def guide_text(self) -> str:
        path = RELEASE_DIR / "USER_GUIDE.md"
        assert path.exists(), f"用户指南不存在: {path}"
        return path.read_text(encoding="utf-8")

    def test_guide_exists(self):
        assert (RELEASE_DIR / "USER_GUIDE.md").exists()

    def test_all_sections_present(self, guide_text):
        """GUIDE-1：五节（七小节）齐全。"""
        for sec in REQUIRED_SECTIONS:
            assert sec in guide_text, f"USER_GUIDE.md 缺少小节: {sec}"

    def test_three_platforms_covered(self, guide_text):
        """GUIDE-2：Linux / Windows / macOS 三平台说明齐全。"""
        for plat in ["Linux", "Windows", "macOS"]:
            assert plat in guide_text, f"USER_GUIDE.md 缺少平台: {plat}"

    def test_keymap_table_complete(self, guide_text):
        """GUIDE-3：键位表包含 WASD/方向键/P/Q/R/H/ESC。"""
        for key in REQUIRED_KEYS:
            assert key in guide_text, f"USER_GUIDE.md 键位表缺少: {key}"

    def test_difficulty_table(self, guide_text):
        """难度表含三档。"""
        for diff in ["简单", "普通", "困难"]:
            assert diff in guide_text, f"USER_GUIDE.md 难度表缺少: {diff}"

    def test_skin_table(self, guide_text):
        """皮肤表含 3 套皮肤。"""
        for skin in ["经典", "深色", "色盲"]:
            assert skin in guide_text, f"USER_GUIDE.md 皮肤表缺少: {skin}"

    def test_known_limitations(self, guide_text):
        """已知限制小节包含未签名/公证提示。"""
        assert "未签名" in guide_text or "SmartScreen" in guide_text or "Gatekeeper" in guide_text


class TestReleaseNotes:
    """REL-1/2：RELEASE_NOTES.md 字段完备性。"""

    @pytest.fixture(scope="class")
    def notes_text(self) -> str:
        path = RELEASE_DIR / "RELEASE_NOTES.md"
        assert path.exists(), f"发布说明不存在: {path}"
        return path.read_text(encoding="utf-8")

    def test_notes_exists(self):
        assert (RELEASE_DIR / "RELEASE_NOTES.md").exists()

    def test_version_string(self, notes_text):
        """REL-1：包含 v2.0.0 版本号。"""
        assert "v2.0.0" in notes_text

    def test_features_listed(self, notes_text):
        """REL-2：列出新功能（难度/暂停/最高分/皮肤/打包）。"""
        for feat in ["难度", "暂停", "最高分", "皮肤", "三平台"]:
            assert feat in notes_text, f"RELEASE_NOTES.md 缺少功能: {feat}"

    def test_performance_section(self, notes_text):
        """性能指标小节（NFR-01/02 留档）。"""
        assert "FPS" in notes_text or "帧率" in notes_text
        assert "300" in notes_text or "内存" in notes_text

    def test_download_checksum_section(self, notes_text):
        """下载与校验小节。"""
        assert "SHA256" in notes_text or "校验" in notes_text


class TestSha256Sums:
    """SHA-1/2：SHA256SUMS 生成正确性。"""

    @pytest.fixture(scope="class")
    def sums_lines(self) -> list:
        path = RELEASE_DIR / "SHA256SUMS"
        assert path.exists(), f"SHA256SUMS 不存在: {path}"
        text = path.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert lines, "SHA256SUMS 为空"
        return lines

    def test_sums_exists(self):
        assert (RELEASE_DIR / "SHA256SUMS").exists()

    def test_each_line_64_hex_plus_filename(self, sums_lines):
        """SHA-1：每行格式 = <64-hex>  <file>。"""
        pattern = re.compile(r"^[0-9a-f]{64}\s{2}\S+$")
        for ln in sums_lines:
            assert pattern.match(ln), f"SHA256SUMS 行格式非法: {ln}"

    def test_hashes_match_actual_files(self, sums_lines):
        """SHA-2：重新计算 SHA256 与文件中记录匹配（对存在的文件校验）。"""
        for ln in sums_lines:
            digest, _, rel = ln.partition("  ")
            target = RELEASE_DIR / rel
            if not target.exists():
                continue  # 构建产物（dist/）尚未生成时跳过；存在则必须匹配
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            assert actual == digest, f"{rel} 校验和不匹配"
