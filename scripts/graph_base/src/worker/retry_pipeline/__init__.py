"""retry_pipeline SOP worker 注册中心。

注册 gate op / proc / cmd 到全局 registry。
"""

from __future__ import annotations

from pathlib import Path

from src.kernel import register_op


def harvester_threshold_gate(base_dir, state, graph, gate) -> bool:
    """harvester 自环阈值门：cycle_counts["harvester"] >= 3 → 切出边。

    关键：每次 evaluate_gates 都会重读 state（不缓存），所以 harvester
    自环 3 次后这个 gate 才会返回 True。
    """
    return state.cycle_counts.get("harvester", 0) >= 3


def manual_publish_gate(base_dir, state, graph, gate) -> bool:
    """manual_publish_gate：无条件 True（manual 边是否走取决于 triggered_edges）。"""
    return True


def harvester_proc(base_dir, state, graph, node_name):
    """harvester 跑一次：写 3 个批次 JSON 文件 + 1 个固定 marker 文件。

    修复 Bug 1：批次文件名按 (cycle, batch_idx) 唯一化避免并发覆盖。
    同时写一个固定路径的 `harvester_done.json` 作为下游 qa_reviewer 的
    iport 满足信号（与 cycle 编号解耦）。
    """
    out_dir = base_dir / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    cycle = state.cycle_counts.get(node_name, 0)
    for i in range(1, 4):
        p = out_dir / f"raw_batch_{i}_cycle{cycle}.json"
        p.write_text(
            f'{{"batch": {i}, "node": "{node_name}", "cycle": {cycle}}}\n',
            encoding="utf-8",
        )
        files.append(str(p))
    # 固定路径 marker：每次都重写，qa_reviewer iport 信号
    marker = out_dir / "harvester_done.json"
    marker.write_text(
        f'{{"harvester": "done", "cycle": {cycle}}}\n',
        encoding="utf-8",
    )
    files.append(str(marker))
    return tuple(files)


def qa_reviewer_proc(base_dir, state, graph, node_name):
    """qa 跑一次：写 qa_pass_1.json（要求 raw_batch_1.json 已存在）。"""
    p = base_dir / "data" / "qa_pass_1.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"qa": "passed", "reviewer": "auto"}\n', encoding="utf-8")
    return (str(p),)


def publisher_proc(base_dir, state, graph, node_name):
    """publisher 写 release/notes.md + changelog.md。"""
    out_dir = base_dir / "release"
    out_dir.mkdir(parents=True, exist_ok=True)
    p1 = out_dir / "notes.md"
    p2 = out_dir / "changelog.md"
    p1.write_text("# Release Notes\n\n_auto-generated_\n", encoding="utf-8")
    p2.write_text("# Changelog\n\n- v1.0\n", encoding="utf-8")
    return (str(p1), str(p2))


def harvester_loop_cmd(base_dir, state, graph, edge):
    """harvester 自环 cmd：写一个 debug 标记文件（验证 cmd 跑过）。"""
    cycle = state.cycle_counts.get("harvester", 0)
    dbg = base_dir / "data" / f"loop_iter_{cycle}.json"
    dbg.parent.mkdir(parents=True, exist_ok=True)
    dbg.write_text(f'{{"edge": "harvester_loop", "cycle": {cycle}}}\n', encoding="utf-8")


def harvester_pass_cmd(base_dir, state, graph, edge):
    """harvester → qa cmd：写通过标记。"""
    p = base_dir / "data" / "harvester_passed.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"harvester": "passed_to_qa"}\n', encoding="utf-8")


def qa_approve_cmd(base_dir, state, graph, edge):
    """qa → publisher manual 边 trigger 后跑：写审批审计文件。"""
    audit = base_dir / "data" / "qa_approved.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(
        f'{{"approved_by": "manual_trigger", "edge": "{edge.name}"}}\n',
        encoding="utf-8",
    )


register_op("harvester_threshold_gate", harvester_threshold_gate)
register_op("manual_publish_gate", manual_publish_gate)
register_op("harvester_proc", harvester_proc)
register_op("qa_reviewer_proc", qa_reviewer_proc)
register_op("publisher_proc", publisher_proc)
register_op("harvester_loop_cmd", harvester_loop_cmd)
register_op("harvester_pass_cmd", harvester_pass_cmd)
register_op("qa_approve_cmd", qa_approve_cmd)
