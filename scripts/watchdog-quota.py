#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配额巡检 tick 入口（cron no_agent，每 30 分钟）。
调 scripts/check_minimax_quota.py 判定 5h 窗口剩余；紧张/严重时输出告警（经 cron deliver 推 Telegram），
健康时静默。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # realpath：兼容 ~/.hermes/scripts/ 下的符号链接调用
import statectl  # noqa: E402

sys.exit(statectl.main(["quota_tick"]))
