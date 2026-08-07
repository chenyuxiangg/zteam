#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上半部·评审师 tick 入口（cron no_agent 调用）。
只做秒级操作：stale 恢复 / 原子认领 / spawn 评审 worker。
无活时静默（空 stdout），异常/告警时输出文本（经 cron deliver 投递）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # realpath：兼容 ~/.hermes/scripts/ 下的符号链接调用
import statectl  # noqa: E402

sys.exit(statectl.main(["reviewer_tick"]))
