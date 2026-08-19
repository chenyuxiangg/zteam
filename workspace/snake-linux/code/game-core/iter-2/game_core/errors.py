"""errors 模块：异常定义（迭代 2 删除 DirectionError 占位）。

迭代 2 起反向输入统一静默忽略或放行（长度 1 允许、长度 ≥2 忽略），不再抛
DirectionError，故从 errors.py 与 __init__.py 同步删除定义与 re-export。
"""
class InvalidStateError(RuntimeError):
    """对 OVER 状态调用 set_direction/step/toggle_pause；
    对 PAUSED 状态调用 step；
    OVER 状态下调用 toggle_pause；
    抛出。"""