#!/usr/bin/env bash
# 一键运行全部自动化测试（r2）：
#   1) 单元层：pytest（test_game_state / test_config / test_input）
#   2) 集成层：e2e_snake.py（PTY 端到端，TC-I-01~11）
#   3) 性能层：perf_snake.sh（TC-P-01/02，基线记录）
# 系统层（TC-S-01~06）与 TC-P-03 为人工验收，见 checklist-system.md。
#
# 用法：bash run_all.sh
# 退出码：0 = 单元+集成全过（P2 SKIP 不算失败）；非 0 = 存在失败（明细见输出）。
set -u
cd "$(dirname "$0")" || exit 1
rc_all=0

echo "########## [1/3] 单元层 pytest ##########"
python3 -m pytest -q test_game_state.py test_config.py test_input.py
rc1=$?
[ ${rc1} -ne 0 ] && rc_all=1
echo "单元层退出码: ${rc1}"

echo
echo "########## [2/3] 集成层 PTY 端到端 ##########"
python3 e2e_snake.py
rc2=$?
[ ${rc2} -ne 0 ] && rc_all=1
echo "集成层退出码: ${rc2}"

echo
echo "########## [3/3] 性能层（基线记录，不阻塞） ##########"
bash perf_snake.sh
rc3=$?
echo "性能层退出码: ${rc3}（1=超标仅记录缺陷单，不阻塞功能门禁）"

echo
echo "########## 汇总 ##########"
echo "单元层=${rc1} 集成层=${rc2} 性能层=${rc3}"
if [ ${rc_all} -eq 0 ]; then
    echo "结论: 单元+集成全过（P2 SKIP 不计失败）；系统层人工验收见 checklist-system.md"
else
    echo "结论: 存在失败（见上方明细；P0/P1 失败阻塞发布，P2 不阻塞）"
fi
exit ${rc_all}
