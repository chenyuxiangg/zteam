"""State dataclass：SOP 实例运行时快照。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping


def _empty_str_map() -> Mapping[str, str]:
    return {}


def _empty_int_map() -> Mapping[str, int]:
    return {}


def _empty_files_map() -> Mapping[str, tuple[str, ...]]:
    return {}


@dataclass(frozen=True)
class State:
    """不可变 SOP 实例状态。"""

    sop_name: str
    instance_id: str
    graph_name: str
    current_node: str | None = None
    history: tuple[tuple[str, str], ...] = ()
    triggered_edges: Mapping[str, str] = field(default_factory=_empty_str_map)
    cycle_counts: Mapping[str, int] = field(default_factory=_empty_int_map)
    last_output: Mapping[str, tuple[str, ...]] = field(default_factory=_empty_files_map)

    def evolve(self, **changes) -> "State":
        """生成新 State；不影响当前对象。"""
        return replace(self, **changes)