"""errors 模块：渲染层异常层级。

迭代 3 增量（设计 §2.4 + §3.3 修订 P3-1）：SkinNotFoundError 实装结构化构造签名
`(name, available)`，并暴露 `self.name` / `self.available` 供 FO set_skin / UT 断言使用。
"""


class RenderError(RuntimeError):
    """渲染模块异常基类。

    覆盖场景：
    - pygame 初始化失败（无图形环境）
    - 颜色 RGB 非法（由 Skin 注入时校验）
    - 窗口尺寸过小（小于最小可玩尺寸）
    - render() 收到非法 snapshot（如 snake_body 为空）
    - 迭代 3 增量：enable_high_dpi / set_skin / handle_resize / render 未 init 抛此异常
    """


class SkinNotFoundError(RenderError):
    """皮肤名不在注册表中（迭代 3 触发；迭代 1 仅 DEFAULT_SKIN 不会触发）。

    修订 P3-1 实装构造签名 `(name, available)`，结构化字段供调用方断言：
        e.name       # 缺失的皮肤名
        e.available  # 当前注册表 key 列表（tuple）
    """

    def __init__(self, name: str, available):
        # available 既可传 tuple 也可传 dict_keys，统一转 tuple 存
        super().__init__(f"皮肤 {name!r} 不在注册表 {list(available)}")
        self.name = name
        self.available = tuple(available)


__all__ = ["RenderError", "SkinNotFoundError"]
