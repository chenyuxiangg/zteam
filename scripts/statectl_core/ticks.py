"""上半部 tick + 配额巡检。

- quota_tick：调 check_minimax_quota.py，根据退出码告警
  （健康/紧张/严重受限；调用失败静默避免与上游重复告警）。
- _format_beijing / _parse_zlog_message：quota_tick 辅助。

注：analyst_tick / reviewer_tick / worker_tick / weekly_tick / guard_recovery
    暂留 statectl.py（依赖 _apply_deps / register_new_inputs 等尚在拆出的内部辅助）；
    后续 commit 6+ 拆分。
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta

from .paths import QUOTA_SCRIPT

__all__ = ["quota_tick", "_format_beijing", "_parse_zlog_message"]


def _format_beijing(ts_ms: int) -> str:
    return (datetime.utcfromtimestamp(ts_ms / 1000) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def _parse_zlog_message(line: str) -> str:
    """Extract the message field from a pipe-delimited zlog line.

    Format: ``{ts}|{level_name:8}|{func}:{lineno}|{role:10}|{message}|{kv}``
    """
    parts = line.rstrip("\n").split("|", 5)
    if len(parts) != 6:
        raise ValueError(f"unexpected zlog line shape: {line!r}")
    return parts[4]


def quota_tick() -> int:
    """调用 check_minimax_quota.py，根据退出码生成告警；脚本不可用或调用失败时静默。

    退出码语义（脚本约定）：
      0 = 健康（5h 窗口 ≥ 30% 且 周配额 ≥ 50%）
      1 = 紧张（5h 窗口 < 30% 或 周配额 < 50%）
      2 = 严重受限（5h 窗口 < 10%）
      3 = 调用失败（凭据/网络/格式）
    """
    if not os.path.exists(QUOTA_SCRIPT):
        return 0
    try:
        r = subprocess.run([sys.executable, QUOTA_SCRIPT, "--json"], capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, Exception):
        return 0
    code = r.returncode
    if code == 0:
        return 0
    if code == 3:
        return 0
    try:
        import json as _json
        message = _parse_zlog_message(r.stdout)
        data = _json.loads(message)
        general = next((m for m in data.get("model_remains", []) if m.get("model_name") == "general"), None)
    except Exception:
        general = None
    if general is None:
        return 0
    interval_pct = general.get("current_interval_remaining_percent", 0)
    weekly_pct = general.get("current_weekly_remaining_percent", 0)
    reset_bj = _format_beijing(general.get("end_time", 0))
    if code == 2:
        level = "🔴 严重受限"
        hint = "建议暂停流水线（hermes cron pause <job_id>）避免无意义消耗 5h 窗口"
    else:
        level = "🟡 紧张"
        hint = "流水线跑 code/test 阶段密集调用时可能触发 429；持续 BLOCKED 模式 C 时优先排除配额"
    print(
        f"[QUOTA] minimax {level}\n"
        f"  5h 窗口剩余: {interval_pct}%\n"
        f"  周配额剩余:   {weekly_pct}%\n"
        f"  5h 窗口重置: {reset_bj}（北京时间）\n"
        f"  建议: {hint}"
    )
    return 0