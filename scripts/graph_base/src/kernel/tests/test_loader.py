"""loader 测试。"""

import json
from pathlib import Path

import pytest

from src.kernel import load_graph
from src.kernel.loader import GraphLoadError


def test_load_software_team(tmp_path: Path):
    """测试名：test_load_software_team

    测试场景：加载内置 software_team_graph.json 得到 2 节点 / 1 gate / 2 边的 Graph。
    前置条件：config/software_team_graph.json 存在。
    是否使用 mock：No。
    测试步骤：调 load_graph(REPO/config/software_team_graph.json)。
    预期结果：name == "software_team"，nodes/gates/edges 数量正确。
    测试后清理：pytest tmp_path 自动清理。
    """
    src = Path(__file__).resolve().parents[3] / "config" / "software_team_graph.json"
    g = load_graph(src)
    assert g.name == "software_team"
    assert len(g.nodes) == 2
    assert len(g.gates) == 1
    assert len(g.edges) == 2


def test_load_missing_file(tmp_path: Path):
    """测试名：test_load_missing_file

    测试场景：load_graph 路径不存在时抛 GraphLoadError。
    前置条件：tmp_path 下无 nope.json。
    是否使用 mock：No。
    测试步骤：调 load_graph(tmp_path/"nope.json")。
    预期结果：抛 GraphLoadError 且 message 含 "不存在"。
    测试后清理：pytest tmp_path 自动清理。
    """
    with pytest.raises(GraphLoadError, match="不存在"):
        load_graph(tmp_path / "nope.json")


def test_load_invalid_json(tmp_path: Path):
    """测试名：test_load_invalid_json

    测试场景：JSON 解析失败时抛 GraphLoadError。
    前置条件：tmp_path/bad.json 写入 "{not json"。
    是否使用 mock：No。
    测试步骤：调 load_graph(bad.json)。
    预期结果：抛 GraphLoadError 且 message 含 "JSON"。
    测试后清理：pytest tmp_path 自动清理。
    """
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(GraphLoadError, match="JSON"):
        load_graph(p)


def test_load_missing_required_field(tmp_path: Path):
    """测试名：test_load_missing_required_field

    测试场景：JSON 缺 name 字段时抛 GraphLoadError。
    前置条件：tmp_path/missing.json 写入 {"nodes":[], "gates":[], "edges":[]}。
    是否使用 mock：No。
    测试步骤：调 load_graph(missing.json)。
    预期结果：抛 GraphLoadError 且 message 含 "name"。
    测试后清理：pytest tmp_path 自动清理。
    """
    p = tmp_path / "missing.json"
    p.write_text(json.dumps({"nodes": [], "gates": [], "edges": []}), encoding="utf-8")
    with pytest.raises(GraphLoadError, match="name"):
        load_graph(p)


def test_load_bad_graph_mode(tmp_path: Path):
    """测试名：test_load_bad_graph_mode

    测试场景：graph_mode 不在枚举值内时抛 GraphLoadError。
    前置条件：tmp_path/bad.json 写入 graph_mode="bogus"。
    是否使用 mock：No。
    测试步骤：调 load_graph(bad.json)。
    预期结果：抛 GraphLoadError 且 message 含 "graph_mode"。
    测试后清理：pytest tmp_path 自动清理。
    """
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps(
            {
                "name": "x",
                "graph_mode": "bogus",
                "nodes": [],
                "gates": [],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GraphLoadError, match="graph_mode"):
        load_graph(p)


def test_load_node_attr_is_src_must_be_bool(tmp_path: Path):
    """测试名：test_load_node_attr_is_src_must_be_bool

    测试场景：attr.is_src 非 bool 时抛 GraphLoadError。
    前置条件：tmp_path/bad.json 节点 attr.is_src="yes"（字符串）。
    是否使用 mock：No。
    测试步骤：调 load_graph(bad.json)。
    预期结果：抛 GraphLoadError 且 message 含 "is_src"。
    测试后清理：pytest tmp_path 自动清理。
    """
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps(
            {
                "name": "x",
                "graph_mode": "directed_cycle",
                "nodes": [
                    {
                        "name": "a",
                        "iport": [],
                        "oport": [],
                        "attr": {"is_src": "yes", "role": "r"},
                    }
                ],
                "gates": [{"name": "g", "op": "f", "enum_dir": [True]}],
                "edges": [
                    {
                        "name": "e",
                        "inode": "a",
                        "onode": "a",
                        "driver": "tick",
                        "gate": "g",
                        "gate_value": True,
                        "cmd": "c",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GraphLoadError, match="is_src"):
        load_graph(p)