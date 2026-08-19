"""G4-5 字体路径定位 + G4-2 字体优先级 UT（UT FONT-1~5）。

迭代 4 增量（设计 §4.8 + INV-20）：
- 优先级 1：打包内置字体文件（PyInstaller --onefile sys._MEIPASS）
- 优先级 2：源码目录 / --onedir 模式（__file__ 邻近）
- 优先级 3：pygame.font.match_font 回退链（"notosanscjksc", "notosanscjk", ...）
- 优先级 4：pygame.font.Font(None, size) SDL 默认字体兜底

不变量（INV-19/20）：
- 全失败后 _cjk_font_fallback == True（菜单/HUD 仍可读英文）
- 优先级链：内置文件 > match_font > Font(None)
- CJKFontFallbackWarning 在全失败时触发
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


class TestBundledFontPath:
    """FONT-1：get_bundled_font_path 优先级：sys._MEIPASS > __file__ 邻近 > 空串。"""

    def test_returns_meipass_path_when_present(self, monkeypatch, tmp_path) -> None:
        """优先级 1：PyInstaller --onefile 临时目录下的字体文件。"""
        from game_app import _constants as const_mod
        fake_font = tmp_path / "SourceHanSansCN-Regular.otf"
        fake_font.write_bytes(b"fake otf")
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        result = const_mod.get_bundled_font_path()
        assert result == str(fake_font)

    def test_returns_source_path_when_no_meipass(self, monkeypatch) -> None:
        """优先级 2：无 sys._MEIPASS 时，源码 __file__ 邻近目录字体文件。"""
        from game_app import _constants as const_mod
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

        # 在 _constants 所在目录创建占位字体文件
        const_dir = Path(const_mod.__file__).parent
        fake_font = const_dir / const_mod.BUNDLED_FONT_FILENAME
        created_here = not fake_font.exists()
        if created_here:
            fake_font.write_bytes(b"fake otf")
        try:
            result = const_mod.get_bundled_font_path()
            if created_here:
                assert result == str(fake_font)
            else:
                # 字体本来就在（开发环境）— 结果就是该路径
                assert result == str(fake_font)
        finally:
            if created_here:
                fake_font.unlink()

    def test_returns_empty_when_no_font_anywhere(self, monkeypatch, tmp_path) -> None:
        """优先级失败：sys._MEIPASS 无 + __file__ 邻近无 → 返回空串（兜底链触发）。"""
        from game_app import _constants as const_mod
        # 把 sys._MEIPASS 指向无字体的目录
        empty = tmp_path / "empty_meipass"
        empty.mkdir()
        monkeypatch.setattr(sys, "_MEIPASS", str(empty), raising=False)

        # 也确保 __file__ 邻近无字体
        const_dir = Path(const_mod.__file__).parent
        fake_font = const_dir / const_mod.BUNDLED_FONT_FILENAME
        if fake_font.exists():
            original = fake_font.read_bytes()
            fake_font.unlink()
            try:
                result = const_mod.get_bundled_font_path()
                assert result == ""
            finally:
                fake_font.write_bytes(original)
        else:
            result = const_mod.get_bundled_font_path()
            assert result == ""

    def test_bundled_font_filename_is_sourcehan(self) -> None:
        """INV-20：内置字体文件名 = SourceHanSansCN-Regular.otf。"""
        from game_app import _constants as const_mod
        assert const_mod.BUNDLED_FONT_FILENAME == "SourceHanSansCN-Regular.otf"

    def test_meipass_priority_over_source(self, monkeypatch, tmp_path) -> None:
        """INV-20：sys._MEIPASS 优先级 > __file__ 邻近。"""
        from game_app import _constants as const_mod
        meipass_font = tmp_path / "SourceHanSansCN-Regular.otf"
        meipass_font.write_bytes(b"meipass otf")
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

        # 也确保源码目录有字体（如果没就创建临时）—— 测试 MEIPASS 优先
        const_dir = Path(const_mod.__file__).parent
        source_font = const_dir / const_mod.BUNDLED_FONT_FILENAME
        source_existed = source_font.exists()
        if not source_existed:
            source_font.write_bytes(b"source otf")
        try:
            result = const_mod.get_bundled_font_path()
            # MEIPASS 路径应胜出
            assert result == str(meipass_font)
        finally:
            if not source_existed:
                source_font.unlink()


class TestLoadCjkFontPriorities:
    """FONT-2/3/4：_load_cjk_font 优先级 + 警告触发。"""

    def test_bundled_font_first(self, monkeypatch, fake_pygame) -> None:
        """FONT-1/2：内置字体路径有效 → 优先用内置字体。"""
        from game_app.fonts import _load_cjk_font
        from game_app import _constants as const_mod

        captured_calls = []

        def capture_font(*args, **kwargs):
            captured_calls.append({"args": args, "kwargs": kwargs})
            return MagicMock()

        monkeypatch.setattr(fake_pygame.font, "Font", capture_font)
        monkeypatch.setattr("game_app.fonts.get_bundled_font_path", lambda: "/fake/bundled.otf")

        _load_cjk_font(20)
        assert len(captured_calls) == 1
        # 第一个位置参数应为路径
        assert captured_calls[0]["args"][0] == "/fake/bundled.otf"
        assert captured_calls[0]["args"][1] == 20

    def test_match_font_fallback_when_bundled_fails(self, monkeypatch, fake_pygame) -> None:
        """FONT-2：内置字体加载失败 → match_font 回退链生效。"""
        from game_app.fonts import _load_cjk_font
        from game_app import _constants as const_mod

        # 内置字体失败
        def font_raises(*args, **kwargs):
            if args and args[0] == "/fake/bundled.otf":
                raise fake_pygame.error("bundled broken")
            return MagicMock()
        fake_pygame.font.Font.side_effect = font_raises
        monkeypatch.setattr("game_app.fonts.get_bundled_font_path", lambda: "/fake/bundled.otf")

        # match_font 返回第一个候选
        fake_pygame.font.match_font.side_effect = lambda name, bold=False: (
            f"/usr/share/fonts/{name}.ttf" if name == "notosanscjksc" else None
        )

        _load_cjk_font(20)
        # 第二次调用应是 match_font 返的第一个候选
        calls = fake_pygame.font.Font.call_args_list
        # 第一次失败，第二次走 match_font
        assert any("/usr/share/fonts/notosanscjksc.ttf" in str(c) for c in calls)

    def test_default_font_last_resort(self, monkeypatch, fake_pygame) -> None:
        """FONT-3：内置 + match_font 全失败 → Font(None, size) 兜底。"""
        from game_app.fonts import _load_cjk_font
        from game_app import _constants as const_mod

        monkeypatch.setattr("game_app.fonts.get_bundled_font_path", lambda: "")
        fake_pygame.font.match_font.return_value = None  # 全部失败

        _load_cjk_font(20)
        calls = fake_pygame.font.Font.call_args_list
        # 最后一次调用应传 None（默认字体）
        assert calls[-1].args[0] is None

    def test_cjk_font_fallback_warning_emitted(self, monkeypatch, fake_pygame, capsys) -> None:
        """FONT-4：CJKFontFallbackWarning 在全失败时触发（INV-19）。"""
        from game_app.fonts import _load_cjk_font
        from game_app import _constants as const_mod
        from game_app.errors import CJKFontFallbackWarning

        monkeypatch.setattr("game_app.fonts.get_bundled_font_path", lambda: "")
        fake_pygame.font.match_font.return_value = None

        with pytest.warns(CJKFontFallbackWarning):
            _load_cjk_font(20)

    def test_bundled_path_empty_string_returns_empty(self) -> None:
        """FONT-1：内置字体不存在时 get_bundled_font_path 返回空串（不是 None）。"""
        from game_app import _constants as const_mod
        # 不创建字体文件 → 应返空串
        result = const_mod.get_bundled_font_path()
        assert isinstance(result, str)
        # 当前测试环境下 fonts 目录无字体 → 空串
        assert result == ""


class TestFallbackFlag:
    """FONT-5：_cjk_font_fallback 标志在全失败后置 True（INV-19）。"""

    def test_fallback_flag_initialized_false(self, app_uninitialized) -> None:
        """App 构造后 _cjk_font_fallback == False（初始状态）。"""
        assert hasattr(app_uninitialized, "_cjk_font_fallback")
        assert app_uninitialized._cjk_font_fallback is False

    def test_fallback_flag_set_after_init_failure(self, monkeypatch, fake_pygame, fake_storage, fake_renderer_iter3) -> None:
        """全失败后 _cjk_font_fallback == True（INV-19）。"""
        from game_app import App
        from game_app import storage as storage_mod
        from game_app import app as app_mod
        from game_app import _constants as const_mod

        monkeypatch.setattr(storage_mod, "create_storage", lambda path=None: fake_storage)
        monkeypatch.setattr(app_mod, "Renderer", lambda *a, **kw: fake_renderer_iter3)
        monkeypatch.setattr("game_app.fonts.get_bundled_font_path", lambda: "")
        fake_pygame.font.match_font.return_value = None

        a = App()
        a._init_pygame()
        assert a._cjk_font_fallback is True


# 补一个 import 让 MagicMock 可用
from unittest.mock import MagicMock