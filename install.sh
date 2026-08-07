#!/usr/bin/env bash
# req-review 流水线一键安装/修复（幂等：可重复执行，已存在的组件会跳过/保持）
# 用法: bash install.sh [--with-gateway]
#   --with-gateway: gateway 未运行时自动安装并启动用户级服务（干净机器一键到位）
#   REQREVIEW_DELIVER=telegram bash install.sh   # 创建 job 时直接带上投递目标（告警/结果推送到消息平台）
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$WORKSPACE/scripts"
HERMES_SCRIPTS="$HOME/.hermes/scripts"

JOBS=(req-analyst-top req-reviewer-top req-weekly-audit req-result-notify)
SCHEDULES=("*/5 * * * *" "*/5 * * * *" "0 9 * * 1" "*/15 * * * *")
WRAPPERS=(watchdog-analyst.sh watchdog-reviewer.sh watchdog-weekly.sh watchdog-notify.sh)
WORKER_ENTRIES=(watchdog-analyst.py watchdog-reviewer.py watchdog-weekly.py watchdog-notify.py)

say() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0. 前置检查 ----
command -v python3 >/dev/null || die "缺少 python3"
command -v hermes  >/dev/null || die "缺少 hermes CLI（请先安装 Hermes Agent: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash）"
[ -f "$SCRIPTS_DIR/statectl.py" ] || die "未找到 $SCRIPTS_DIR/statectl.py —— install.sh 必须放在流水线工作区根目录"

# ---- 1. 目录骨架（缺啥补啥，不覆盖已有文件） ----
mkdir -p "$WORKSPACE"/{input,analysis,review,artifacts,logs,roles,docs,scripts}
[ -f "$WORKSPACE/status.json" ] || echo '{}' > "$WORKSPACE/status.json"
touch "$WORKSPACE/logs/pipeline.log" "$WORKSPACE/logs/alarms.txt" "$WORKSPACE/status.lock"
say "目录骨架就绪: $WORKSPACE"

# ---- 1.5 zbot 职责注入（roles/bot.md → gateway.json，幂等；重启 gateway 生效） ----
python3 "$SCRIPTS_DIR/bot_config.py" install

# ---- 2. cron 薄壳（按当前工作区路径生成 → 工作区可迁移，迁移后重跑 install 即可） ----
mkdir -p "$HERMES_SCRIPTS"
for i in "${!WRAPPERS[@]}"; do
  cat > "$HERMES_SCRIPTS/${WRAPPERS[$i]}" <<EOF
#!/bin/bash
# req-review 上半部薄壳（由 install.sh 自动生成，请勿手改；工作区迁移后重跑 install.sh 重建）
exec python3 "$SCRIPTS_DIR/${WORKER_ENTRIES[$i]}"
EOF
  chmod +x "$HERMES_SCRIPTS/${WRAPPERS[$i]}"
done
say "cron 薄壳已就绪: $HERMES_SCRIPTS/{watchdog-*.sh}"

# ---- 3. cron jobs（幂等：按名查重，存在则跳过） ----
LIST="$(hermes cron list 2>/dev/null || true)"
DELIVER_ARGS=()
[ -n "${REQREVIEW_DELIVER:-}" ] && DELIVER_ARGS=(--deliver "$REQREVIEW_DELIVER")
for i in "${!JOBS[@]}"; do
  name="${JOBS[$i]}"
  if echo "$LIST" | grep -q "Name:.*$name"; then
    say "job 已存在，跳过: $name"
  else
    hermes cron create "${SCHEDULES[$i]}" --name "$name" --script "${WRAPPERS[$i]}" --no-agent --repeat 0 "${DELIVER_ARGS[@]}" >/dev/null
    say "已创建 job: $name (${SCHEDULES[$i]})${DELIVER_ARGS:+ [deliver: $REQREVIEW_DELIVER]}"
  fi
done

# ---- 4. gateway 检查与可选自启 ----
WITH_GATEWAY=0
[ "${1:-}" = "--with-gateway" ] && WITH_GATEWAY=1
if hermes cron status 2>/dev/null | grep -q "Gateway is running"; then
  say "gateway 运行中，cron 会自动触发"
elif [ "$WITH_GATEWAY" -eq 1 ]; then
  say "gateway 未运行，--with-gateway 已指定，正在安装并启动用户级服务…"
  if hermes gateway install >/dev/null 2>&1 && hermes cron status 2>/dev/null | grep -q "Gateway is running"; then
    say "gateway 已启动（hermes-gateway.service，enabled + linger，开机自启）"
  else
    warn "自动启动失败（可能无 systemd，如 WSL/Docker）。手动方案: hermes gateway run（前台）或 sudo hermes gateway install --system"
  fi
else
  warn "gateway 未运行 —— job 不会自动触发。启动: hermes gateway start（首次安装: hermes gateway install）；或重跑: bash install.sh --with-gateway"
fi

# ---- 5. 自检 ----
set +e
python3 "$SCRIPTS_DIR/statectl.py" diagnose
rc=$?
set -e
if [ "$rc" -eq 0 ]; then
  say "安装完成，诊断全绿。投放需求: cp 需求.md $WORKSPACE/input/"
else
  warn "安装完成但诊断存在 FAIL（见上方报告，排查指南: docs/troubleshooting.md）"
fi
exit "$rc"
