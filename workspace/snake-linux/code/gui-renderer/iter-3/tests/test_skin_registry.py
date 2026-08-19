"""SKIN_REGISTRY 完整性 + Renderer 切皮肤相关测试（设计 §7.6）。"""
import pytest

from gui_renderer import DEFAULT_SKIN, COLORBLIND_FRIENDLY_SKIN, DARK_SKIN, SKIN_REGISTRY
from gui_renderer.errors import SkinNotFoundError


# ========================================================================
# 注册表完整性
# ========================================================================


def test_skin_registry_classic_is_default_skin():
    """SKIN_REGISTRY['classic'] is DEFAULT_SKIN（同一对象）。"""
    assert SKIN_REGISTRY["classic"] is DEFAULT_SKIN


def test_skin_registry_dark_is_dark_skin():
    """SKIN_REGISTRY['dark'] is DARK_SKIN。"""
    assert SKIN_REGISTRY["dark"] is DARK_SKIN


def test_skin_registry_colorblind_is_cb_skin():
    """SKIN_REGISTRY['colorblind_friendly'] is COLORBLIND_FRIENDLY_SKIN。"""
    assert SKIN_REGISTRY["colorblind_friendly"] is COLORBLIND_FRIENDLY_SKIN


def test_skin_registry_all_skins_pass_validate_skin(renderer):
    """注册表内所有 skin 通过 _validate_skin（构造 Renderer 时隐式校验）。"""
    # 三个皮肤都通过 Renderer(skin=...) 走一遍校验，不抛即为通过
    from gui_renderer import Renderer

    for name, skin in SKIN_REGISTRY.items():
        r = Renderer((640, 480), skin=skin, enable_high_dpi=False)
        assert r.skin is skin


def test_skin_names_returns_three_names(renderer):
    """skin_names() 返回 3 元素 tuple（含 classic / dark / colorblind_friendly）。"""
    names = renderer.skin_names()
    assert isinstance(names, tuple)
    assert len(names) == 3
    assert "classic" in names
    assert "dark" in names
    assert "colorblind_friendly" in names


# ========================================================================
# SkinNotFoundError 构造（设计 §3.3 修订 P3-1）
# ========================================================================


def test_skinnotfounderror_structured_construction():
    """SkinNotFoundError 构造参数 (name, available)（修订 P3-1）。"""
    e = SkinNotFoundError(name="nope", available=("classic", "dark", "colorblind_friendly"))
    assert e.name == "nope"
    assert "classic" in e.available
    assert "dark" in e.available
    assert "colorblind_friendly" in e.available


def test_skinnotfounderror_is_render_error():
    """SkinNotFoundError 继承自 RenderError（异常层级一致）。"""
    from gui_renderer import RenderError

    e = SkinNotFoundError(name="x", available=())
    assert isinstance(e, RenderError)
