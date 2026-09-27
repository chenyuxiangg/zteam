"""Edge 数据类与 Driver 枚举。"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Driver(str, Enum):
    """边的驱动方式。"""

    TICK = "tick"
    MANUAL = "manual"


@dataclass(frozen=True)
class Edge:
    """图中的一条有向边（inode -> onode）。

    gate 引用 gates[].name；gate_value 是命中值（在对应 gate.enum_dir 里）；
    cmd 是函数名（registry.resolve_cmd 解析为可调用对象）。
    """

    name: str
    inode: str
    onode: str
    driver: Driver
    gate: str
    gate_value: Any
    cmd: str