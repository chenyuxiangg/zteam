"""validators 测试。"""

from src.kernel import Edge, Gate, Graph, GraphMode, Node, NodeAttr, validate
from src.kernel.validators import Issue


def _n(name: str, is_src: bool = False, is_sink: bool = False) -> Node:
    return Node(
        name=name,
        iport=(),
        oport=(),
        attr=NodeAttr(is_src=is_src, is_sink=is_sink, role=""),
    )


def _g(name: str, enum_dir=(True,)) -> Gate:
    return Gate(name=name, op="f", enum_dir=enum_dir)


def _e(name: str, inode: str, onode: str, gate: str = "ga", value=True, cmd="c") -> Edge:
    return Edge(name=name, inode=inode, onode=onode, driver="tick", gate=gate, gate_value=value, cmd=cmd)


def _build(nodes, gates, edges, mode="directed_cycle", name="x"):
    return Graph.build(
        name=name, graph_mode=mode,
        pre_handle="", post_handle="",
        nodes=nodes, gates=gates, edges=edges,
    )


def test_clean_graph_no_issues():
    """测试名：test_clean_graph_no_issues

    测试场景：自包含最小合法图（1 src+sink + 1 gate + 1 自环边）validate 返回空列表。
    前置条件：无。
    是否使用 mock：No。
    测试步骤：调 _build([a src+sink], [ga], [e a→a])；再 validate(g)。
    预期结果：issues == []。
    测试后清理：无。
    """
    g = _build([_n("a", is_src=True, is_sink=True)], [_g("ga")], [_e("e", "a", "a")])
    assert validate(g) == []


def test_multi_src_returns_issues():
    """测试名：test_multi_src_returns_issues

    测试场景：两个 src 节点时 validate 报 E_NO_SRC。
    前置条件：临时 Graph（直接 Graph(...) 绕过 build 验错场景）。
    是否使用 mock：No。
    测试步骤：1. 构造 nodes=[a src, b src]；2. validate(g)；3. 收集 code 列表。
    预期结果：codes 含 "E_NO_SRC"。
    测试后清理：无。
    """
    from src.kernel.graph import Graph as G
    g = G(
        name="x",
        graph_mode=GraphMode.DIRECTED_CYCLE,
        pre_handle="",
        post_handle="",
        nodes=(_n("a", is_src=True), _n("b", is_src=True)),
        gates=(_g("ga"),),
        edges=(_e("e", "a", "b"),),
    )
    issues = validate(g)
    codes = [i.code for i in issues]
    assert "E_NO_SRC" in codes


def test_multi_sink_returns_issues():
    """测试名：test_multi_sink_returns_issues

    测试场景：≥2 个 sink 节点时 validate 报 E_MULTI_SINK。
    前置条件：临时 Graph（b sink + c sink，绕过 build）。
    是否使用 mock：No。
    测试步骤：1. 构造 nodes=[a src, b sink, c sink]；2. validate(g)；3. 收集 code。
    预期结果：codes 含 "E_MULTI_SINK"。
    测试后清理：无。
    """
    from src.kernel.graph import Graph as G
    g = G(
        name="x",
        graph_mode=GraphMode.DIRECTED_CYCLE,
        pre_handle="",
        post_handle="",
        nodes=(
            _n("a", is_src=True),
            _n("b", is_sink=True),
            _n("c", is_sink=True),
        ),
        gates=(_g("ga"), _g("gb")),
        edges=(
            _e("e1", "a", "b", gate="ga"),
            _e("e2", "b", "c", gate="gb"),
        ),
    )
    issues = validate(g)
    codes = [i.code for i in issues]
    assert "E_MULTI_SINK" in codes


def test_no_sink_returns_issue():
    """测试名：test_no_sink_returns_issue

    测试场景：directed_cycle 下 0 sink 时 validate 报 E_MULTI_SINK。
    前置条件：临时 Graph（仅 src + 普通节点）。
    是否使用 mock：No。
    测试步骤：1. 构造 nodes=[a src, b]；2. validate(g)；3. 收集 code。
    预期结果：codes 含 "E_MULTI_SINK"。
    测试后清理：无。
    """
    from src.kernel.graph import Graph as G
    g = G(
        name="x",
        graph_mode=GraphMode.DIRECTED_CYCLE,
        pre_handle="",
        post_handle="",
        nodes=(_n("a", is_src=True), _n("b")),
        gates=(_g("ga"),),
        edges=(_e("e", "a", "b", gate="ga"),),
    )
    issues = validate(g)
    codes = [i.code for i in issues]
    assert "E_MULTI_SINK" in codes


def test_dup_gate_name_returns_issue():
    """测试名：test_dup_gate_name_returns_issue

    测试场景：两个 gate 同名时 validate 报 E_DUP_GATE_NAME。
    前置条件：临时 Graph（gates 含同名 ga 两次）。
    是否使用 mock：No。
    测试步骤：1. 构造 gates=[ga, ga]；2. validate(g)。
    预期结果：issues 至少一条 code == "E_DUP_GATE_NAME"。
    测试后清理：无。
    """
    from src.kernel.graph import Graph as G
    g = G(
        name="x", graph_mode=GraphMode.DIRECTED_CYCLE,
        pre_handle="", post_handle="",
        nodes=(_n("a", is_src=True, is_sink=True),),
        gates=(_g("ga"), _g("ga")),
        edges=(_e("e", "a", "a"),),
    )
    issues = validate(g)
    assert any(i.code == "E_DUP_GATE_NAME" for i in issues)


def test_dup_edge_name_returns_issue():
    """测试名：test_dup_edge_name_returns_issue

    测试场景：两个 edge 同名时 validate 报 E_DUP_EDGE_NAME。
    前置条件：临时 Graph（edges 含同名 e 两次，gate_value True/False 区分）。
    是否使用 mock：No。
    测试步骤：1. 构造 edges=[e True, e False]；2. validate(g)。
    预期结果：issues 至少一条 code == "E_DUP_EDGE_NAME"。
    测试后清理：无。
    """
    from src.kernel.graph import Graph as G
    g = G(
        name="x", graph_mode=GraphMode.DIRECTED_CYCLE,
        pre_handle="", post_handle="",
        nodes=(_n("a", is_src=True, is_sink=True),),
        gates=(_g("ga", enum_dir=(True, False)),),
        edges=(
            _e("e", "a", "a", value=True),
            _e("e", "a", "a", value=False),
        ),
    )
    issues = validate(g)
    assert any(i.code == "E_DUP_EDGE_NAME" for i in issues)


def test_gate_value_not_in_enum():
    """测试名：test_gate_value_not_in_enum

    测试场景：edge.gate_value 不在 gate.enum_dir 内时报 E_GATE_VALUE_NOT_IN_ENUM。
    前置条件：临时 Graph（enum_dir=(True,)，edge value="missing"）。
    是否使用 mock：No。
    测试步骤：1. 构造 edge value="missing"；2. validate(g)。
    预期结果：issues 至少一条 code == "E_GATE_VALUE_NOT_IN_ENUM"。
    测试后清理：无。
    """
    from src.kernel.graph import Graph as G
    g = G(
        name="x", graph_mode=GraphMode.DIRECTED_CYCLE,
        pre_handle="", post_handle="",
        nodes=(_n("a", is_src=True, is_sink=True),),
        gates=(_g("ga", enum_dir=(True,)),),
        edges=(_e("e", "a", "a", value="missing"),),
    )
    issues = validate(g)
    assert any(i.code == "E_GATE_VALUE_NOT_IN_ENUM" for i in issues)


def test_cycle_on_nocycle_warns():
    """测试名：test_cycle_on_nocycle_warns

    测试场景：directed_nocycle 模式下存在环时报 W_CYCLE_ON_NOCYCLE 警告。
    前置条件：临时 Graph（a↔b 互成环，nocycle 模式）。
    是否使用 mock：No。
    测试步骤：1. 构造 a→b / b→a 双向边（mode=nocycle）；2. validate(g)。
    预期结果：issues 至少一条 code == "W_CYCLE_ON_NOCYCLE"。
    测试后清理：无。
    """
    from src.kernel.graph import Graph as G
    g = G(
        name="x", graph_mode=GraphMode.DIRECTED_NOCYCLE,
        pre_handle="", post_handle="",
        nodes=(_n("a", is_src=True), _n("b", is_sink=True)),
        gates=(_g("ga", enum_dir=(True,)), _g("gb", enum_dir=(True,))),
        edges=(
            _e("e1", "a", "b", gate="ga", value=True),
            _e("e2", "b", "a", gate="gb", value=True),
        ),
    )
    issues = validate(g)
    assert any(i.code == "W_CYCLE_ON_NOCYCLE" for i in issues)


def test_cycle_on_cycle_no_warn_in_issues():
    """测试名：test_cycle_on_cycle_no_warn_in_issues

    测试场景：directed_cycle 模式下的环不产生 W_CYCLE_ON_NOCYCLE 警告。
    前置条件：_build 构造 a→b / b→a 互成环（cycle 模式）。
    是否使用 mock：No。
    测试步骤：调 validate(_build(...))。
    预期结果：issues 中无 code 含 "CYCLE" 字样。
    测试后清理：无。
    """
    g = _build(
        [_n("a", is_src=True), _n("b", is_sink=True)],
        [_g("ga"), _g("gb")],
        [
            _e("e1", "a", "b", gate="ga"),
            _e("e2", "b", "a", gate="gb"),
        ],
        mode="directed_cycle",
    )
    issues = validate(g)
    assert not any("CYCLE" in i.code for i in issues)


def test_issue_path_is_string():
    """测试名：test_issue_path_is_string

    测试场景：Issue.path 接受 tuple 或 str 输入，统一序列化为单字符串表示。
    前置条件：无。
    是否使用 mock：No。
    测试步骤：1. Issue(path=(nodes,2,name))；2. Issue(path="nodes[2].name")。
    预期结果：两个 i.path 都 == "nodes[2].name"。
    测试后清理：无。
    """
    i = Issue(code="X", level="error", message="m", path=("nodes", 2, "name"))
    assert i.path == "nodes[2].name"
    i2 = Issue(code="X", level="error", message="m", path="nodes[2].name")
    assert i2.path == "nodes[2].name"
