# -*- coding: utf-8 -*-
"""parse_args 单元测试：对应测试方案 TC-U-11 / TC-U-12。

覆盖 FR-03 tick 可配置（50-1000ms 生效、越界报错退出码 2）与
FR-16 画布尺寸参数校验（非法/过小报错退出码 2）。
"""
import pytest

import snake


# ---------------------------------------------------------------------------
# TC-U-11（P1，FR-03）：tick 参数
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_tc_u11_tick_default():
    args = snake.parse_args([])
    assert args.tick == 200, '不传参数时默认 tick=200'


@pytest.mark.p1
def test_tc_u11_tick_boundaries_ok():
    assert snake.parse_args(['--tick', '50']).tick == 50
    assert snake.parse_args(['--tick', '1000']).tick == 1000


@pytest.mark.p1
@pytest.mark.parametrize('argv', [
    ['--tick', '49'],      # 低于下限
    ['--tick', '1001'],    # 高于上限
    ['--tick', 'abc'],     # 非数字
    ['--tick', '-100'],    # 负数
    ['--tick', '0'],       # 0
])
def test_tc_u11_tick_invalid_exit2(argv):
    with pytest.raises(SystemExit) as excinfo:
        snake.parse_args(argv)
    assert excinfo.value.code == 2, '非法 tick 应以退出码 2 结束'


# ---------------------------------------------------------------------------
# TC-U-12（P1，FR-16）：画布尺寸参数
# ---------------------------------------------------------------------------
@pytest.mark.p1
def test_tc_u12_dims_ok():
    args = snake.parse_args(['--width', '40', '--height', '20'])
    assert (args.width, args.height) == (40, 20)
    assert snake.parse_args(['--width', '10', '--height', '10']).width == 10


@pytest.mark.p1
@pytest.mark.parametrize('argv', [
    ['--width', '0'],          # 0
    ['--height', '-1'],        # 负数
    ['--width', '9'],          # 小于最小可玩值 10
    ['--height', '9'],         # 小于最小可玩值 10
    ['--width', 'abc'],        # 非整数
    ['--width', '4', '--height', '5'],  # 4x5 < 10x10
])
def test_tc_u12_dims_invalid_exit2(argv):
    with pytest.raises(SystemExit) as excinfo:
        snake.parse_args(argv)
    assert excinfo.value.code == 2, '非法尺寸应以退出码 2 结束'
