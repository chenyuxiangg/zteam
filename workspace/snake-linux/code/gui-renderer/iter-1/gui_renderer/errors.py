"""errors 模块：渲染层异常层级。"""


class RenderError(RuntimeError):
    """渲染模块异常基类。

    覆盖场景：
    - pygame 初始化失败（无图形环境）
    - 颜色 RGB 非法（由 Skin 注入时校验）
    - 窗口尺寸过小（小于最小可玩尺寸）
    - render() 收到非法 snapshot（如 snake_body 为空）
    """


class SkinNotFoundError(RenderError):
    """皮肤名不在注册表中（迭代 3 触发；迭代 1 仅 DEFAULT_SKIN 不会触发）。

    占位异常，确保迭代 3 接入 set_skin() 时异常层级已就位。
    """


__all__ = ["RenderError", "SkinNotFoundError"]