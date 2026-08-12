"""CLI 合同测试：E-02（非 TTY）/ E-04（地图不存在）。

通过 subprocess 在隔离环境运行主程序，验证退出码与错误信息。
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

from tests._path import code_dir  # noqa: F401


CODE = code_dir()


class TestNonTtyExit(unittest.TestCase):
    """E-02：stdin 非 TTY 时 main_cli 报错退出 exit 1。"""

    def test_t_e02_non_tty_exits_1(self):
        env = {**os.environ, "PYTHONPATH": str(CODE)}
        result = subprocess.run(
            [sys.executable, "-m", "pacman"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        self.assertEqual(result.returncode, 1)
        err = result.stderr.decode("utf-8", errors="replace")
        self.assertIn("需要真实终端", err)


class TestMissingMap(unittest.TestCase):
    """E-04：--map 不存在路径应报错（exit 1）。"""

    def test_e04_load_map_raises_maperror(self):
        """直接调用 load_map() 验证 MapError（main_cli 路径已被 TTY 检查先拦截）。"""
        from pacman.map import MapError, load_map
        with self.assertRaises(MapError) as cm:
            load_map("/nonexistent/path/pacman_map.txt")
        # 错误信息应包含"不存在"
        self.assertIn("不存在", str(cm.exception))

    def test_e04_main_cli_path(self):
        """_parse_args 解析合法 argv 路径；main_cli 在地图不存在时返回 1（端到端需 TTY，跳过）。"""
        # 端到端路径需要 TTY，进程会先报"非 TTY"。MapError 由 load_map 内部抛出：
        # 已通过 test_e04_load_map_raises_maperror 覆盖 MapError 自身。
        from pacman.main import _parse_args
        cfg = _parse_args(["--map", "/tmp/nonexistent_pacman.txt"])
        self.assertEqual(cfg.map_path, "/tmp/nonexistent_pacman.txt")


if __name__ == "__main__":
    unittest.main(verbosity=2)