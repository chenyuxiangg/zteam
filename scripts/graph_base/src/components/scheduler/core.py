"""Scheduler 主循环：find_ready_next_node / claim / dispatch / trigger_edge / tick。"""

from __future__ import annotations

from pathlib import Path

from src.kernel import Edge, Graph, StateLock

from ..dispatcher import Dispatcher, DispatchResult
from ..monitor import Event, Monitor, get_monitor
from ..state_manager import State, StateManager, is_sop_done
from .cycle import detect_cycle_progress
from .evaluator import (
    EdgeCmdError,
    GateEvalError,
    evaluate_gates,
    run_edge_cmd,
    select_next_edge,
)


class Scheduler:
    """单实例调度器。"""

    def __init__(
        self,
        graph: Graph,
        root: Path,
        dispatcher: Dispatcher | None = None,
        monitor: Monitor | None = None,
    ) -> None:
        self._graph = graph
        self._root = Path(root)
        self._dispatcher = dispatcher
        self._monitor = monitor or Monitor(get_monitor())

    @property
    def graph(self) -> Graph:
        return self._graph

    @property
    def monitor(self) -> Monitor:
        return self._monitor

    def find_ready_next_node(
        self, state: State, base_dir: Path
    ) -> tuple[str, Edge] | None:
        """基于 state.current_node 选下一个候选节点（onode, edge）。

        仅判断"边的放行条件"——遍历以 current_node 为起点的所有出边：
        1. gate 求值（同一 gate 复用结果）
        2. gate_values[edge.gate] == edge.gate_value 才匹配
        3. should_run_cmd：driver=manual 需 state.triggered_edges 包含 edge.name
        命中第一条 → 返回 (edge.onode, edge)。

        返回 None：current_node 为空 / 无匹配边 / 全部 manual 未 trigger。
        gate.op 异常 → 抛 GateEvalError（让调用方决定是否记 alarm）。

        注意：本函数不判断"节点的进入条件"（iport）——iport 是下一节点的进入条件，
        由 tick 拿到 (next_node, edge) 后另行调 _iport_ready 检查。
        """
        if state.current_node is None:
            return None
        gate_values = evaluate_gates(self._graph, state.current_node, base_dir, state)
        edge = select_next_edge(self._graph, state.current_node, gate_values, state)
        if edge is None:
            return None
        return (edge.onode, edge)

    def claim(self, state_file: Path, owner: str) -> bool:
        """认领 state_file 的当前 tick 权（应用层 compare-and-swap）。

        语义：防止多个 worker / 监控器并发 tick 同一 instance：
        - 读 state.json 的 claim_pid / claim_ts
        - 持有者已死（pid_alive=False）或持有超时 → 写入新 claim，返回 True
        - 否则返回 False（其它 tick 在跑，调用方应放弃本次推进）

        拿到 True 才推进 state；拿到 False 直接 return alarms（不写盘）。
        """
        return StateManager.claim(state_file, owner)

    def dispatch(
        self,
        state: State,
        node_name: str,
        work_dir: Path,
        instance_id: str,
    ) -> DispatchResult | None:
        """调 dispatcher.dispatch(node)。"""
        if self._dispatcher is None:
            self._monitor.emit(Event.SCH_EV_ERROR, where="dispatch", reason="no dispatcher")
            return None
        node = self._graph.node_index.get(node_name)
        if node is None:
            return None
        return self._dispatcher.dispatch(self._graph, state, node, instance_id, work_dir)

    def trigger_edge(self, state_file: Path, edge_name: str, approver: str) -> State:
        """manual 边外部触发。"""
        new_state = StateManager.trigger_edge(state_file, edge_name, approver)
        self._monitor.emit(
            Event.SCH_EV_EDGE_ADMITTED, edge=edge_name, approver=approver
        )
        return new_state

    def tick(self, sop_name: str, instance_id: str) -> list[str]:
        """单实例 tick。

        顺序：
        1. read                       —— 读 state.json（持 StateLock）
        2. find_ready_next_node       —— 边放行条件：以 current_node 为起点的某条出边被 gate 放行？
           返回 None → SCH_EV_EDGE_REJECTED（出边都没被放行）
        3. _iport_ready(next_node)    —— 节点进入条件：next_node 的 iport 满足？
           返回 False → SCH_EV_AWAITING_IPORT（next_node 还没准备好接收）
        4. run_cmd                    —— 副作用动作（gate 通过后跑）
        5. advance                    —— transition + cycle 检测
        6. dispatch                   —— 拉 worker 跑 next_node 的 proc（输入已就绪才派）
        7. write                      —— 写盘

        节点进入条件（iport）与边放行条件（gate）是两件事——
        iport 不满足发 SCH_EV_AWAITING_IPORT；边未放行发 SCH_EV_EDGE_REJECTED。
        """
        alarms: list[str] = []
        state_file = self._state_path(sop_name, instance_id)
        base_dir = state_file.parent / instance_id
        if not state_file.exists():
            self._monitor.emit(
                Event.SCH_EV_ERROR, where="tick", reason="state not found",
                sop=sop_name, instance=instance_id,
            )
            return ["STATE_NOT_FOUND"]

        with StateLock(state_file):
            state = StateManager.read(state_file)
            self._monitor.emit(
                Event.SCH_EV_TICK, phase="enter", sop=sop_name, instance=instance_id,
                current_node=state.current_node,
            )

            if is_sop_done(self._graph, state):
                self._monitor.emit(Event.SCH_EV_SOP_DONE, sop=sop_name, instance=instance_id)
                return alarms

            # 边放行条件
            try:
                ready = self.find_ready_next_node(state, base_dir)
            except GateEvalError as exc:
                self._monitor.emit(Event.SCH_EV_ERROR, where="evaluate_gates", msg=str(exc))
                return ["GATE_EVAL_ERROR"]
            if ready is None:
                self._monitor.emit(
                    Event.SCH_EV_EDGE_REJECTED,
                    current_node=state.current_node,
                )
                return alarms
            next_node, edge = ready

            # 节点进入条件（next_node 的 iport）
            if not self._iport_ready(next_node, base_dir):
                self._monitor.emit(
                    Event.SCH_EV_AWAITING_IPORT, current_node=next_node,
                )
                return alarms

            try:
                self._run_edge_cmd(edge, state, base_dir)
            except EdgeCmdError as exc:
                self._monitor.emit(Event.SCH_EV_ERROR, where="run_edge_cmd", msg=str(exc))
                return ["EDGE_CMD_ERROR"]

            new_state, alarms = self._advance(state, edge, alarms)

            self._dispatch_if_any(new_state, next_node, instance_id, base_dir)

            StateManager.write(state_file, new_state)
            self._monitor.emit(
                Event.SCH_EV_TICK, phase="exit", sop=sop_name, instance=instance_id,
                current_node=new_state.current_node, selected_edge=edge.name,
            )
        return alarms

    def _run_edge_cmd(self, edge: Edge, state: State, base_dir: Path) -> None:
        """跑 edge.cmd；异常 → EdgeCmdError。"""
        run_edge_cmd(self._graph, edge, state, base_dir)

    def _iport_ready(self, node_name: str, base_dir: Path) -> bool:
        """判断 node_name 是否满足进入条件（iport = 节点开始工作所需的输入文件）。

        空 iport（节点无输入要求）直接视为满足；非空 iport 要求所有组至少一组
        文件全部存在（OR-of-AND）。

        本函数判断的是"节点的进入条件"——与 find_ready_next_node 中 gate 判断的
        "边的放行条件"是两件事：
          - iport 满足：节点可以开始干活
          - gate 通过：以 current_node 为起点的某条出边可以走
        两者都满足才会触发 cmd + transition。
        """
        from src.kernel import iport_satisfied

        node = self._graph.node_index.get(node_name)
        if node is None:
            return False
        if not node.iport:
            return True
        return bool(iport_satisfied(node, base_dir))

    def _advance(
        self, state: State, edge: Edge, alarms: list[str]
    ) -> tuple[State, list[str]]:
        """transition + cycle 检测；返回 (new_state, alarms)。"""
        new_state = StateManager.transition(
            state, from_node=state.current_node, to_node=edge.onode,
        )
        if self._graph.graph_mode.value == "directed_cycle":
            new_state = StateManager.record_cycle_step(new_state, edge.onode)
            prog = detect_cycle_progress(self._graph, new_state)
            if prog.over_threshold:
                self._monitor.emit(
                    Event.SCH_EV_TIMEOUT, what="cycle_threshold",
                    max_count=prog.max_count,
                )
                alarms.append("CYCLE_OVER_THRESHOLD")
        return new_state, alarms

    def _dispatch_if_any(
        self,
        new_state: State,
        next_node: str,
        instance_id: str,
        base_dir: Path,
    ) -> None:
        """拉 worker 跑 next_node 的 proc（无 dispatcher 时跳过）。"""
        if self._dispatcher is None:
            return
        dr = self._dispatcher.dispatch(
            self._graph, new_state,
            self._graph.node_index[next_node],
            instance_id, base_dir,
        )
        self._monitor.emit(
            Event.SCH_EV_NODE_START, node=next_node, pid=dr.pid if dr else 0,
        )

    def _state_path(self, sop_name: str, instance_id: str) -> Path:
        from src.kernel import state_path

        return state_path(root=self._root, sop_name=sop_name, instance_id=instance_id)