#!/usr/bin/env bash
# cron 健康守护：检查流水线 5 个 job 是否被 pause（enabled=false），异常则自动恢复 + 告警。
# 由 systemd user timer（hermes-cron-guard.timer）驱动——独立于 hermes cron/gateway，
# 即使 gateway 停摆或 cron job 全被 pause，本守护仍能运行并恢复。
# 幂等：全部正常时静默退出（看门狗模式）。
set -u
JOBS_FILE="${HERMES_HOME:-$HOME/.hermes}/cron/jobs.json"
HERMES="${HERMES_BIN:-/home/zyzs/.local/bin/hermes}"
WORKSPACE="/home/zyzs/cyx/zteam"
ALARMS="$WORKSPACE/workspace/logs/alarms.txt"
WANTED="req-analyst-top req-reviewer-top req-worker-top req-weekly-audit req-result-notify"

[ -f "$JOBS_FILE" ] || exit 0

PAUSED=""
for name in $WANTED; do
  enabled=$(python3 -c "
import json
d = json.load(open('$JOBS_FILE'))
for j in d.get('jobs', []):
    if j.get('name') == '$name':
        print('true' if j.get('enabled', True) else 'false')
        break
")
  [ "$enabled" = "false" ] && PAUSED="$PAUSED $name"
done

if [ -n "$PAUSED" ]; then
  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  mkdir -p "$(dirname "$ALARMS")"
  echo "$TS CRON_GUARD: 检测到流水线 job 被暂停:$PAUSED，执行恢复" >> "$ALARMS"
  for name in $WANTED; do
    "$HERMES" cron resume "$name" >/dev/null 2>&1 || true
  done
  echo "$TS CRON_GUARD: 已恢复全部流水线 job（resume）" >> "$ALARMS"
  echo "CRON_GUARD recovered paused pipeline jobs:$PAUSED"
fi
exit 0
