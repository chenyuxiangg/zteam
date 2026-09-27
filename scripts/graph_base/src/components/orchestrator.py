"""Orchestrator：顶层组装（create_instance / tick / run）。"""

from __future__ import annotations

import time
from pathlib import Path

from src.kernel import Graph

from .dispatcher import Dispatcher, ProcessDispatcher
from .monitor import Monitor, get_monitor
from .scheduler import Scheduler
from .state_manager import State, StateManager, is_sop_done, run_post_handle


class Orchestrator:
    """封装 Graph + Scheduler + StateManager + Monitor + Dispatcher。"""

    def __init__(
        self,
        graph: Graph,
        root: Path,
        dispatcher: Dispatcher | None = None,
        monitor: Monitor | None = None,
    ) -> None:
        self._graph = graph
        self._root = Path(root)
        self._dispatcher = dispatcher if dispatcher is not None else ProcessDispatcher()
        self._monitor = monitor if monitor is not None else Monitor(get_monitor())
        self._scheduler = Scheduler(
            graph=self._graph,
            root=self._root,
            dispatcher=self._dispatcher,
            monitor=self._monitor,
        )

    @property
    def graph(self) -> Graph:
        return self._graph

    @property
    def scheduler(self) -> Scheduler:
        return self._scheduler

    def create_instance(self, base_dir: Path | None = None) -> str:
        """新建实例：返回 instance_id。"""
        from src.kernel import new_instance_id, state_path

        iid = new_instance_id()
        sop_dir = self._root / self._graph.name
        sop_dir.mkdir(parents=True, exist_ok=True)
        sf = state_path(root=self._root, sop_name=self._graph.name, instance_id=iid)
        StateManager.create(sf, sop_name=self._graph.name, graph=self._graph, instance_id=iid)
        return iid

    def tick(self, sop_name: str, instance_id: str) -> list[str]:
        """单实例 tick。"""
        return self._scheduler.tick(sop_name, instance_id)

    def run(self, sop_name: str, instance_id: str, max_ticks: int = 1000) -> list[str]:
        """阻塞跑：tick 直到 is_sop_done（包含 sink worker 完成检查），或 max_ticks。

        is_sop_done 已包含"sink oport 非空 → last_output 有产物"的检查，
        所以这里只需一个简单循环 + 必要时短暂 sleep 让 sink worker 落盘。
        """
        all_alarms: list[str] = []
        sf = self._state_file(sop_name, instance_id)
        for _ in range(max_ticks):
            alarms = self.tick(sop_name, instance_id)
            all_alarms.extend(alarms)
            state = StateManager.read(sf)
            if is_sop_done(self._graph, state):
                run_post_handle(self._graph, state, sf.parent / instance_id)
                break
            # is_sop_done=False 但 current_node 已是 sink → 等 sink worker 写盘
            time.sleep(0.05)
        return all_alarms

    def trigger_edge(self, sop_name: str, instance_id: str, edge_name: str, approver: str) -> State:
        """manual 边外部触发。"""
        sf = self._state_file(sop_name, instance_id)
        return self._scheduler.trigger_edge(sf, edge_name, approver)

    def _state_file(self, sop_name: str, instance_id: str) -> Path:
        from src.kernel import state_path

        return state_path(root=self._root, sop_name=sop_name, instance_id=instance_id)