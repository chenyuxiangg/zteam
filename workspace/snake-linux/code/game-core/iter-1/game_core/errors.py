"""errors 模块：异常定义。"""

class DirectionError(ValueError):
    """当前迭代不抛（反向移动静默忽略），保留为未来扩展。"""


class InvalidStateError(RuntimeError):
    """对 OVER/PAUSED 状态调用 set_direction/step/toggle_pause 时抛出。"""