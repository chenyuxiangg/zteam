#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""minimax 套餐余额查询（CLI）。

从 ~/.hermes/.env 的 MINIMAX_CN_API_KEY 读密钥，调用 https://www.minimaxi.com/v1/token_plan/remains，
按 zbot 实际判定需求输出三个等级：

  - general 模型 5h 窗口剩余 % （决定能否继续跑 code/test 阶段——核心指标）
  - general 模型周配额剩余 %
  - overall 状态码含义（1=受限，3=充足）

退出码：
  0 = 健康（5h 窗口 >= 30% 或 周配额 >= 50%）
  1 = 紧张（5h 窗口 < 30%）→ BLOCKED 排查时大概率是 API 限额
  2 = 严重受限（5h 窗口 < 10% 或 status=受限）→ 暂停流水线
  3 = 调用失败（凭据/网络/格式）

用 --quiet 只输出关键结论（脚本/CI 友好）。
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

ENV_FILE = Path.home() / ".hermes" / ".env"
URL = "https://www.minimaxi.com/v1/token_plan/remains"


def get_api_key() -> str | None:
    if not ENV_FILE.exists():
        return None
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("MINIMAX_CN_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def fetch_quota(api_key: str, timeout: float = 15) -> dict:
    req = urlrequest.Request(
        URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_general(data: dict) -> dict | None:
    for item in data.get("model_remains", []):
        if item.get("model_name") == "general":
            return item
    return None


def judge(general: dict) -> tuple[int, str]:
    """返回 (退出码, 状态文本)。

    status 字段语义在 minimaxi API 文档里没明说，实测：status=1 是活跃/正常计数中，
    不是"受限"标志。判定只看 remaining_percent 数值（更可靠）。"""
    interval_pct = general.get("current_interval_remaining_percent", 0)
    weekly_pct = general.get("current_weekly_remaining_percent", 0)
    if interval_pct < 10:
        return 2, f"严重受限（5h窗口剩{interval_pct}%）→ 暂停流水线"
    if interval_pct < 30:
        return 1, f"紧张（5h窗口剩{interval_pct}%）→ BLOCKED 大概率是 API 限额"
    if weekly_pct < 50:
        return 1, f"周配额紧张（剩{weekly_pct}%）→ 计划任务量大时易触发 429"
    return 0, f"健康（5h窗口剩{interval_pct}%，周配额剩{weekly_pct}%）"


def format_beijing(ts_ms: int) -> str:
    return (datetime.utcfromtimestamp(ts_ms / 1000) + timedelta(hours=8)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="minimax 套餐余额查询")
    parser.add_argument("--quiet", "-q", action="store_true", help="只输出关键结论")
    parser.add_argument("--json", action="store_true", help="原始 JSON 输出")
    args = parser.parse_args()

    api_key = get_api_key()
    if not api_key:
        print("ERROR: ~/.hermes/.env 缺少 MINIMAX_CN_API_KEY", file=sys.stderr)
        return 3

    try:
        data = fetch_quota(api_key)
    except (HTTPError, URLError) as e:
        print(f"ERROR: 调用失败 — {e}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"ERROR: 未知错误 — {e}", file=sys.stderr)
        return 3

    if data.get("base_resp", {}).get("status_code") != 0:
        print(f"ERROR: API 返回非成功 — {data}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    general = find_general(data)
    if not general:
        print("ERROR: 返回数据中找不到 model_name=general 的记录", file=sys.stderr)
        return 3

    code, verdict = judge(general)
    reset_beijing = format_beijing(general.get("end_time", 0))

    if args.quiet:
        print(f"{code} {verdict}")
        return code

    print(f"5h 窗口剩余: {general.get('current_interval_remaining_percent', 0)}% "
          f"(状态码 {general.get('current_interval_status')})")
    print(f"周配额剩余:   {general.get('current_weekly_remaining_percent', 0)}% "
          f"(状态码 {general.get('current_weekly_status')})")
    print(f"5h 窗口重置: {reset_beijing} (北京时间)")
    print(f"判定: {verdict}")
    return code


if __name__ == "__main__":
    sys.exit(main())
