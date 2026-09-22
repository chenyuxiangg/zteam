"""Tests for statectl_core.ticks: quota_tick + 辅助。"""
from __future__ import annotations

import unittest
from unittest import mock

from statectl_core.ticks import (
    _format_beijing,
    _parse_zlog_message,
    quota_tick,
)


class FormatBeijing(unittest.TestCase):
    def test_returns_strftime(self) -> None:
        out = _format_beijing(0)
        self.assertEqual(out, "1970-01-01 08:00:00")

    def test_nonzero_ts(self) -> None:
        out = _format_beijing(1700000000000)
        self.assertIn("2023", out)


class ParseZlogMessage(unittest.TestCase):
    def test_valid(self) -> None:
        line = "ts|INFO|func:10|role_name |message body|kv=value"
        self.assertEqual(_parse_zlog_message(line), "message body")

    def test_invalid_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_zlog_message("not enough parts")


class QuotaTick(unittest.TestCase):
    def test_returns_0_when_no_script(self) -> None:
        # 默认无脚本：返回 0（静默）
        with mock.patch("os.path.exists", return_value=False):
            self.assertEqual(quota_tick(), 0)

    def test_returns_0_on_healthy(self) -> None:
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("statectl_core.ticks.subprocess.run") as mrun:
                mrun.return_value = mock.Mock(returncode=0, stdout="")
                self.assertEqual(quota_tick(), 0)

    def test_returns_0_on_failure_silent(self) -> None:
        # code=3 调用失败 → 静默
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("statectl_core.ticks.subprocess.run") as mrun:
                mrun.return_value = mock.Mock(returncode=3, stdout="")
                self.assertEqual(quota_tick(), 0)

    def test_returns_0_on_timeout(self) -> None:
        with mock.patch("os.path.exists", return_value=True):
            with mock.patch("statectl_core.ticks.subprocess.run",
                             side_effect=TimeoutError("slow")):
                self.assertEqual(quota_tick(), 0)


if __name__ == "__main__":
    unittest.main()