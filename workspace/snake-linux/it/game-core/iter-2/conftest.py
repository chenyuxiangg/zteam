"""pytest 全局配置：注册 p0/p1/p2 marker（消除警告）。"""
import sys
from pathlib import Path


def pytest_configure(config):
    config.addinivalue_line("markers", "p0: P0 用例（核心功能/发布阻塞）")
    config.addinivalue_line("markers", "p1: P1 用例（重要功能边界）")
    config.addinivalue_line("markers", "p2: P2 用例（体验细节）")
