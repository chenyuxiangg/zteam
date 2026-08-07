#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""巡检 tick 入口（cron no_agent，每周一次）。
只检查一致性（approved/artifacts、blocked、滞留中间态、未登记输入），只告警不改状态。
一切正常时静默（空 stdout）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # realpath：兼容 ~/.hermes/scripts/ 下的符号链接调用
import statectl  # noqa: E402

sys.exit(statectl.main(["weekly_tick"]))
