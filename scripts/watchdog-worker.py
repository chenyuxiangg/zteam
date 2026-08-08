#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上半部·通用阶段 tick 入口（cron no_agent 调用）。
驱动阶段链（需求 → 方案 → 测试方案 → 代码 → 测试 → 质量/安全门禁 → 发布）：
注册新需求 / stale 恢复 / 按 next_action 认领并 spawn 对应角色 worker。
无活时静默（空 stdout），异常/告警时输出文本（经 cron deliver 投递）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # realpath：兼容 ~/.hermes/scripts/ 下的符号链接调用
import statectl  # noqa: E402

sys.exit(statectl.main(["worker_tick"]))
