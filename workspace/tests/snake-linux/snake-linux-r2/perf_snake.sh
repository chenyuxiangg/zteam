#!/usr/bin/env bash
# 性能测试入口：TC-P-01（输入延迟）+ TC-P-02（CPU/RSS 占用）。
# 对应测试方案 §5 的 `bash tests/perf_snake.sh`（r2 补上该缺口，回应评审意见 3）。
#
# 实现说明：
# - 延迟测量与 CPU/RSS 采样由 perf_snake.py 完成（pexpect PTY + 屏幕轮询；
#   CPU/RSS 优先 pidstat，缺失时 ps 兜底）；
# - 本脚本负责统一入口、参数透传与退出码汇总。
#
# 用法：bash perf_snake.sh [--duration 30] [--samples 20]
# 退出码：0 = 指标达标；1 = 指标超标（记录缺陷单，不阻塞 P0/P1 功能门禁）。
set -u
cd "$(dirname "$0")" || exit 1

echo "==> 性能测试入口（TC-P-01/02，测试方案 §5）"
if command -v pidstat >/dev/null 2>&1; then
    echo "==> pidstat 可用：TC-P-02 优先使用 pidstat 采样"
else
    echo "==> pidstat 不可用：TC-P-02 使用 ps 轮询兜底（结果等价，注明于报告）"
fi

python3 perf_snake.py "$@"
rc=$?
echo "==> perf_snake.py 退出码: ${rc}（0=达标；1=超标记录缺陷单，不阻塞功能门禁）"
exit ${rc}
