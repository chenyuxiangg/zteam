"""Renderer 生命周期测试：init/shutdown/__enter__/__exit__ 幂等。"""
import pytest

from gui_renderer import Renderer
from gui_renderer.errors import RenderError


def test_init_is_idempotent():
    """init() 多次调用不报错（设计 §5.6 韧性）。"""
    r = Renderer((512, 472))
    r.init()
    r.init()  # 不抛
    r.shutdown()


def test_shutdown_is_idempotent():
    """shutdown() 多次调用不报错（FR-11 退出无残留）。"""
    r = Renderer((512, 472))
    r.init()
    r.shutdown()
    r.shutdown()  # 不抛


def test_context_manager_returns_self():
    """__enter__ 返回 self。"""
    r = Renderer((512, 472))
    with r as entered:
        assert entered is r


def test_context_manager_calls_init_and_shutdown():
    """__enter__ 触发 init，__exit__ 触发 shutdown（无异常路径）。"""
    r = Renderer((512, 472))
    with r:
        # 在上下文内已经 init；shutdown 由 __exit__ 调用
        assert r._initialized is True
    assert r._initialized is False


def test_context_manager_shutdown_on_exception():
    """__exit__ 即使 render 抛异常也调用 shutdown（异常安全）。"""
    r = Renderer((512, 472))
    with pytest.raises(RuntimeError, match="simulated"):
        with r:
            assert r._initialized is True
            raise RuntimeError("simulated")
    # 即便异常，shutdown 仍被调用
    assert r._initialized is False


def test_shutdown_without_init_does_not_raise():
    """未 init() 直接 shutdown() 不抛（幂等设计）。"""
    r = Renderer((512, 472))
    r.shutdown()  # 不抛