"""CJK 字体回退链单测（UT 39）。

需求：
- pygame.font.match_font 候选 → pygame.font.Font(path, size)
- 全失败 → pygame.font.Font(None, size) 兜底
"""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from game_app.fonts import _load_cjk_font, _CJK_FONT_CANDIDATES


class TestLoadCjkFontFallbackChain:
    def test_first_candidate_match(self, fake_pygame) -> None:
        """第一个候选就匹配 → 调 pygame.font.Font(path, size)。"""
        fake_pygame.font.match_font.return_value = "/usr/share/fonts/cjk.ttf"
        fake_pygame.font.Font.return_value = MagicMock(name="loaded_font")

        result = _load_cjk_font(22)
        # 只调 1 次 match_font（第一个就成功）
        assert fake_pygame.font.match_font.call_count == 1
        # Font 被调，路径 = match_font 返回值
        fake_pygame.font.Font.assert_called_once_with("/usr/share/fonts/cjk.ttf", 22)
        assert result == fake_pygame.font.Font.return_value

    def test_third_candidate_match(self, fake_pygame) -> None:
        """第三个候选才匹配 → 前 2 次返 None，第 3 次返 path。"""
        # 用 side_effect 控制每次调用返回
        fake_pygame.font.match_font.side_effect = [None, None, "/usr/share/fonts/wqy.ttf"]
        fake_pygame.font.Font.return_value = MagicMock(name="loaded_font")

        result = _load_cjk_font(22, bold=True)
        # 调 3 次
        assert fake_pygame.font.match_font.call_count == 3
        # Font 被调一次，路径 = 第 3 次返回值
        fake_pygame.font.Font.assert_called_once_with("/usr/share/fonts/wqy.ttf", 22)
        # 验证 bold 参数传递给 match_font
        third_call_kwargs = fake_pygame.font.match_font.call_args_list[2]
        assert third_call_kwargs.kwargs.get("bold") is True

    def test_all_candidates_fail_uses_default(self, fake_pygame) -> None:
        """全部候选返 None → pygame.font.Font(None, size) 兜底。"""
        fake_pygame.font.match_font.return_value = None
        fake_pygame.font.Font.return_value = MagicMock(name="default_font")

        result = _load_cjk_font(22)
        # match_font 被调 5 次（所有候选）
        assert fake_pygame.font.match_font.call_count == len(_CJK_FONT_CANDIDATES)
        # Font 被调一次，路径 = None（SDL 默认字体）
        fake_pygame.font.Font.assert_called_once_with(None, 22)
        assert result == fake_pygame.font.Font.return_value

    def test_candidates_count_is_five(self) -> None:
        """候选链固定 5 项（规格要求）。"""
        assert len(_CJK_FONT_CANDIDATES) == 5
        # 候选顺序与设计文档一致
        assert "notosanscjksc" in _CJK_FONT_CANDIDATES[0]
        assert "arialunicodems" in _CJK_FONT_CANDIDATES[-1]


class TestFontsDefaultSafe:
    def test_font_loader_does_not_raise(self, fake_pygame) -> None:
        """_load_cjk_font 不应抛异常（match_font 全 None 时 SDL 默认字体兜底）。"""
        fake_pygame.font.match_font.return_value = None
        fake_pygame.font.Font.return_value = MagicMock(name="default_font")
        # 不抛
        _load_cjk_font(48)
        _load_cjk_font(22)
        _load_cjk_font(22, bold=True)