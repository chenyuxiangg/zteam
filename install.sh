#!/usr/bin/env bash
# zteam 流水线一键安装/修复（幂等：可重复执行，已存在的组件会跳过/保持）
# 用法: bash install.sh [--with-gateway]
#   --with-gateway: gateway 未运行时自动安装并启动用户级服务（干净机器一键到位）
#   REQREVIEW_DELIVER=telegram bash install.sh   # 创建 job 时直接带上投递目标（告警/结果推送到消息平台）
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$WORKSPACE/scripts"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_SCRIPTS="$HERMES_HOME/scripts"
HERMES_SKILLS="$HERMES_HOME/skills"

JOBS=(req-analyst-top req-reviewer-top req-worker-top req-weekly-audit req-result-notify)
SCHEDULES=("*/5 * * * *" "*/5 * * * *" "*/5 * * * *" "0 9 * * 1" "*/15 * * * *")
WRAPPERS=(watchdog-analyst.sh watchdog-reviewer.sh watchdog-worker.sh watchdog-weekly.sh watchdog-notify.sh)
WORKER_ENTRIES=(watchdog-analyst.py watchdog-reviewer.py watchdog-worker.py watchdog-weekly.py watchdog-notify.py)

say() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0. 前置检查 ----
command -v python3 >/dev/null || die "缺少 python3"
command -v hermes  >/dev/null || die "缺少 hermes CLI（请先安装 Hermes Agent: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash）"
[ -f "$SCRIPTS_DIR/statectl.py" ] || die "未找到 $SCRIPTS_DIR/statectl.py —— install.sh 必须放在流水线工作区根目录"

# ---- 1. 目录骨架（缺啥补啥，不覆盖已有文件） ----
# 资产层在根目录（roles/docs/scripts）；数据层在 workspace/（按项目分层：workspace/<项目>/ 下含全部子目录，
# 项目目录由 statectl register 在首次投放需求时自动创建；这里只建根与全局日志）
mkdir -p "$WORKSPACE"/{roles,docs,scripts,skills} "$WORKSPACE/workspace"/logs
[ -f "$WORKSPACE/workspace/status.lock" ] || touch "$WORKSPACE/workspace/status.lock"
touch "$WORKSPACE/workspace/logs/pipeline.log" "$WORKSPACE/workspace/logs/alarms.txt"
say "目录骨架就绪: $WORKSPACE（资产层 + workspace/ 数据层）"

# ---- 1.5 zbot 职责注入（roles/bot.md → gateway.json，幂等） ----
# gateway.json 内容变化才重启 gateway（幂等 install 零干扰；REQREVIEW_NO_RESTART=1 跳过重启）
GW_JSON_FILE="${HERMES_HOME:-$HOME/.hermes}/gateway.json"
GW_MD5_BEFORE="$(md5sum "$GW_JSON_FILE" 2>/dev/null | cut -d' ' -f1 || true)"
python3 "$SCRIPTS_DIR/bot_config.py" install
GW_MD5_AFTER="$(md5sum "$GW_JSON_FILE" 2>/dev/null | cut -d' ' -f1 || true)"
if [ "${REQREVIEW_NO_RESTART:-0}" != "1" ] && [ "$GW_MD5_BEFORE" != "$GW_MD5_AFTER" ]; then
  if systemctl --user is-active hermes-gateway >/dev/null 2>&1; then
    systemctl --user restart hermes-gateway
    say "zbot 职责已变更，gateway 已重启（Telegram 适配器重连中，正常现象）"
  else
    warn "gateway 未运行（跳过重启）；zbot 职责将在下次 gateway 启动时生效"
  fi
fi

# ---- 2. cron 薄壳（按当前工作区路径生成 → 工作区可迁移，迁移后重跑 install 即可） ----
mkdir -p "$HERMES_SCRIPTS"
for i in "${!WRAPPERS[@]}"; do
  cat > "$HERMES_SCRIPTS/${WRAPPERS[$i]}" <<EOF
#!/bin/bash
# zteam 上半部薄壳（由 install.sh 自动生成，请勿手改；工作区迁移后重跑 install.sh 重建）
exec python3 "$SCRIPTS_DIR/${WORKER_ENTRIES[$i]}"
EOF
  chmod +x "$HERMES_SCRIPTS/${WRAPPERS[$i]}"
done
say "cron 薄壳已就绪: $HERMES_SCRIPTS/{watchdog-*.sh}"

# ---- 2.5 skill 安装（req-review-pipeline 运维手册 → Hermes skills 目录；工作区为权威源，幂等覆盖） ----
if [ -d "$WORKSPACE/skills/req-review-pipeline" ]; then
  mkdir -p "$HERMES_SKILLS"
  cp -r "$WORKSPACE/skills/req-review-pipeline" "$HERMES_SKILLS/"
  say "skill 已安装: $HERMES_SKILLS/req-review-pipeline（工作区为权威源，重装即同步）"
else
  warn "工作区无 skills/req-review-pipeline，跳过 skill 安装"
fi

# ---- 3. cron jobs（幂等：按名查重；已存在但 deliver 不符则校正，保证重装/迁移后推送配置不丢） ----
LIST="$(hermes cron list 2>/dev/null || true)"
# 期望 deliver：默认 telegram（对齐 README：告警/结果自动推送到消息平台，tick 脚本无活静默不会刷屏）；
# 可用 REQREVIEW_DELIVER=local 覆盖为纯本地模式（输出只存 ~/.hermes/cron/output/）。
EXPECT_DELIVER="${REQREVIEW_DELIVER:-telegram}"
for i in "${!JOBS[@]}"; do
  name="${JOBS[$i]}"
  if echo "$LIST" | grep -q "Name:[[:space:]]*${name}\$"; then
    jid="$(echo "$LIST" | grep -B1 "Name:[[:space:]]*${name}\$" | head -1 | awk '{print $1}')"
    cur="$(echo "$LIST" | grep -A 6 "Name:[[:space:]]*${name}\$" | grep "Deliver:" | awk '{print $2}')"
    if [ "$cur" != "$EXPECT_DELIVER" ]; then
      hermes cron edit "$jid" --deliver "$EXPECT_DELIVER" >/dev/null
      say "job deliver 校正: $name $cur → $EXPECT_DELIVER"
    else
      say "job 已存在且 deliver 正确，跳过: $name"
    fi
  else
    hermes cron create "${SCHEDULES[$i]}" --name "$name" --script "${WRAPPERS[$i]}" --no-agent --repeat 0 --deliver "$EXPECT_DELIVER" >/dev/null
    say "已创建 job: $name (${SCHEDULES[$i]}) [deliver: $EXPECT_DELIVER]"
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
  say "安装完成，诊断全绿。投放需求: 新建/拷贝 需求.md 到 workspace/<项目名>/input/（项目目录不存在会自动创建）"
else
  warn "安装完成但诊断存在 FAIL（见上方报告，排查指南: docs/troubleshooting.md）"
fi
exit "$rc"
