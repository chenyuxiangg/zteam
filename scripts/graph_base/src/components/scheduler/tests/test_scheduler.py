"""Scheduler 主循环测试。"""

from __future__ import annotations

from pathlib import Path

from src.components import Scheduler
from src.components.scheduler.evaluator import EdgeCmdError
from src.kernel import (
    Edge,
    Gate,
    Graph,
    GraphMode,
    Node,
    NodeAttr,
    register_op,
)


def _build_graph() -> Graph:
    n_a = Node(name="a", iport=(), oport=(("f/a.md",),),
               attr=NodeAttr(is_src=True, role="r"))
    n_b = Node(name="b", iport=(("f/a.md",),), oport=(),
               attr=NodeAttr(is_sink=True, role="r"))
    g_g = Gate(name="g_g", op="sch_always_true", enum_dir=(True,))
    e_ab = Edge(name="ab", inode="a", onode="b",
                driver="tick", gate="g_g", gate_value=True, cmd="")
    return Graph.build(
        name="sch", graph_mode=GraphMode.DIRECTED_NOCYCLE,
        pre_handle="", post_handle="",
        nodes=[n_a, n_b], gates=[g_g], edges=[e_ab],
    )


def _register_gate() -> None:
    """注册 _build_graph 使用的 gate op（test 间复用同一 registry）。"""
    register_op(
        "sch_always_true",
        lambda base_dir, state, graph, gate: True,
    )


def test_tick_returns_state_not_found_when_missing(tmp_path: Path) -> None:
    """测试名：test_tick_returns_state_not_found_when_missing

    测试场景：tick 调用时不存在的 instance 路径 → 返回 STATE_NOT_FOUND alarm。
    前置条件：tmp_path；_build_graph；scheduler root=tmp_path。
    是否使用 mock：No。
    测试步骤：1. sch = Scheduler(graph=g, root=tmp_path)；2. sch.tick("sch", "no_instance")。
    预期结果：alarms 含 "STATE_NOT_FOUND"。
    测试后清理：pytest tmp_path 自动清理。
    """
    g = _build_graph()
    sch = Scheduler(graph=g, root=tmp_path)
    alarms = sch.tick("sch", "no_instance")
    assert "STATE_NOT_FOUND" in alarms


def test_tick_no_dispatcher_when_next_node_iport_missing(tmp_path: Path) -> None:
    """测试名：test_tick_no_dispatcher_when_next_node_iport_missing

    测试场景：next_node 的 iport 缺失时 tick 不应推进 state。

    新语义：iport 是 next_node 的进入条件。next_node=b 有非空 iport 且未写产物
    → _iport_ready(b) False → AWAITING_IPORT 返回，state 不动。
    前置条件：tmp_path；_build_graph（b 的 iport=(("f/a.md",),)）；手工写入 current_node="a" state。
    是否使用 mock：No。
    测试步骤：1. 写初始 state；2. sch.tick("sch", "abc")；3. 读 state 校验 current_node。
    预期结果：alarms == []；new_state.current_node == "a"（未推进）。
    测试后清理：pytest tmp_path 自动清理。
    """
    _register_gate()
    g = _build_graph()
    state_file = tmp_path / "sch" / "abc.json"
    state_file.parent.mkdir(parents=True)
    from src.components.state_manager import State, StateManager
    state = State(sop_name="sch", instance_id="abc", graph_name="sch",
                  current_node="a")
    StateManager.write(state_file, state)

    sch = Scheduler(graph=g, root=tmp_path, dispatcher=None)
    alarms = sch.tick("sch", "abc")
    assert alarms == []
    new_state = StateManager.read(state_file)
    assert new_state.current_node == "a"  # 未推进


def test_trigger_edge_writes_to_state(tmp_path: Path) -> None:
    """测试名：test_trigger_edge_writes_to_state

    测试场景：Scheduler.trigger_edge 把 edge_name + approver 写进 state.triggered_edges 并落盘。
    前置条件：tmp_path；_build_graph；写初始 state。
    是否使用 mock：No。
    测试步骤：1. sch.trigger_edge(state_file, "ab", "alice")；2. 读 state。
    预期结果：new_state.triggered_edges["ab"] == "alice"。
    测试后清理：pytest tmp_path 自动清理。
    """
    g = _build_graph()
    state_file = tmp_path / "sch" / "abc.json"
    state_file.parent.mkdir(parents=True)
    from src.components.state_manager import State, StateManager
    StateManager.write(
        state_file,
        State(sop_name="sch", instance_id="abc", graph_name="sch",
              current_node="a"),
    )
    sch = Scheduler(graph=g, root=tmp_path, dispatcher=None)
    sch.trigger_edge(state_file, "ab", "alice")
    new_state = StateManager.read(state_file)
    assert new_state.triggered_edges["ab"] == "alice"
