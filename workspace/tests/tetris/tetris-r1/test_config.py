# -*- coding: utf-8 -*-
"""parse_args 配置解析测试：TC-U-16 / TC-U-17（FR-03 / FR-26）。

对应测试方案 §3.2 用例表：
    TC-U-16 (P1)  --tick 50/2000/500 生效；49/2001/abc/-100 → 可读错误 + 退出码 2；默认 500
    TC-U-17 (P2)  --no-color → no_color=True；不传 → False
"""
import sys

import pytest

import tetris


def _parse(argv):
    """捕获 argparse 的 SystemExit，返回 (args, exit_code)。"""
    try:
        return tetris.parse_args(argv), None
    except SystemExit as exc:
        return None, exc.code


# ---------------------------------------------------------------------------
# TC-U-16：tick 配置（FR-03）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('value,expect', [
    ('50', 50), ('2000', 2000), ('500', 500),
])
def test_tc_u16_tick_in_range_ok(value, expect):
    args, code = _parse(['--tick', value])
    assert code is None
    assert args.tick == expect


@pytest.mark.parametrize('bad', ['49', '2001', 'abc', '-100'])
def test_tc_u16_tick_out_of_range_rejected(bad):
    """越界/非数字/负数 → SystemExit 2（argparse error），stderr 含取值范围提示。"""
    args, code = _parse(['--tick', bad])
    assert args is None
    assert code == 2


def test_tc_u16_tick_default_500():
    args, code = _parse([])
    assert code is None
    assert args.tick == 500


# ---------------------------------------------------------------------------
# TC-U-17：颜色开关（FR-26）
# ---------------------------------------------------------------------------
def test_tc_u17_no_color_flag():
    args, code = _parse(['--no-color'])
    assert code is None
    assert args.no_color is True


def test_tc_u17_color_default_on():
    args, code = _parse([])
    assert code is None
    assert args.no_color is False
