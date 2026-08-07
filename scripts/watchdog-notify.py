#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结果推送 tick 入口（cron no_agent，deliver=telegram 时推送到消息平台）。
有新归档才输出（推送），无新增静默。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # realpath：兼容 ~/.hermes/scripts/ 下的符号链接调用
import statectl  # noqa: E402

sys.exit(statectl.main(["notify"]))
