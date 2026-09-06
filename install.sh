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

JOBS=(req-analyst-top req-reviewer-top req-worker-top req-weekly-audit req-quota-tick req-result-notify)
SCHEDULES=("*/5 * * * *" "*/5 * * * *" "*/5 * * * *" "0 9 * * 1" "*/30 * * * *" "*/15 * * * *")
WRAPPERS=(watchdog-analyst.sh watchdog-reviewer.sh watchdog-worker.sh watchdog-weekly.sh watchdog-quota.sh watchdog-notify.sh)
WORKER_ENTRIES=(watchdog-analyst.py watchdog-reviewer.py watchdog-worker.py watchdog-weekly.py watchdog-quota.py watchdog-notify.py)

say() { printf '\033[1;32m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[install]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0. 前置检查 ----
command -v python3 >/dev/null || die "缺少 python3"
command -v hermes  >/dev/null || die "缺少 hermes CLI（请先安装 Hermes Agent: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash）"
[ -f "$SCRIPTS_DIR/statectl.py" ] || die "未找到 $SCRIPTS_DIR/statectl.py —— install.sh 必须放在流水线工作区根目录"

# ---- 0.5 环境残留检查（其他 zteam 副本/接管检测）----
# 规则（脚本固定）：薄壳存在且 exec 指向 != 当前工作区 = cron 被其他 zteam 接管（CONFLICT）
#               gateway system_prompt 含其他 zteam 路径 = 注入被接管（CONFLICT）
#               存在其他工作区副本（statectl.py）= WARN（静默副本不阻断，但提示）
# CONFLICT → die 引导先 uninstall；REQREVIEW_FORCE=1 跳过检查（高级覆盖场景）
CONFLICTS=""
OTHER_COPIES=""
[ "${REQREVIEW_FORCE:-0}" != "1" ] && {
  # 1a. cron 薄壳指向（~/.hermes/scripts/watchdog-worker.sh 的 exec 目标）
  WRAPPER="$HERMES_SCRIPTS/watchdog-worker.sh"
  if [ -f "$WRAPPER" ]; then
    TARGET="$(grep -oE 'exec python3 "[^"]+"' "$WRAPPER" | sed 's/exec python3 "//; s/"$//' || true)"
    if [ -n "$TARGET" ] && [ "$(dirname "$TARGET" 2>/dev/null)" != "$SCRIPTS_DIR" ]; then
      CONFLICTS="${CONFLICTS}  ⚠️ cron 薄壳指向其他工作区: $TARGET（当前: $WORKSPACE）\n"
    fi
  fi
  # 1b. gateway.json system_prompt 注入指向
  GW_JSON="${HERMES_HOME:-$HOME/.hermes}/gateway.json"
  if [ -f "$GW_JSON" ]; then
    for other in $(grep -oE '/home/[^"]*zteam' "$GW_JSON" 2>/dev/null | sort -u || true); do
      case "$other" in "$WORKSPACE"*) ;; *) CONFLICTS="${CONFLICTS}  ⚠️ gateway zbot 注入指向其他工作区: $other\n";; esac
    done
  fi
  # 1c. 其他 zteam 副本扫描（轻量：home 下 maxdepth 5 找 statectl.py，排除自身与 Hermes 内部）
  if command -v find >/dev/null; then
    for c in $(find "$HOME" -maxdepth 5 -name statectl.py -not -path "$WORKSPACE/*" -not -path "$HERMES_HOME/*" -not -path "*/.*/*" 2>/dev/null | head -3 || true); do
      OTHER_COPIES="${OTHER_COPIES}  ℹ️ 发现其他 zteam 工作区副本: $(dirname "$c")\n"
    done
  fi
  # 1d. 运行中的其他副本 worker（命令行含其他 zteam 路径的 hermes chat）
  if command -v ps >/dev/null; then
    for pid in $(ps aux 2>/dev/null | grep "hermes chat" | grep -v grep | grep -oE "$HOME/[^ ]*zteam[^ ]*" | grep -v "^$WORKSPACE" | head -1 >/dev/null 2>&1; echo ""); do :; done
    OTHER_WORKERS="$(ps aux 2>/dev/null | grep "hermes chat" | grep -v grep | grep -c "$HOME/" | head -1 || true)"
  fi
}
if [ -n "$CONFLICTS" ]; then
  warn "环境残留检查发现冲突："
  printf "$CONFLICTS"
  die "存在其他 zteam 接管 cron/gateway——请先运行对应工作区的 uninstall.sh 卸载已有服务（bash <残留工作区>/uninstall.sh 或 bash $WORKSPACE/uninstall.sh 均会按名清理 cron job/薄壳/注入/worker），清理后再重新 install；确认覆盖请: REQREVIEW_FORCE=1 bash install.sh"
fi
if [ -n "$OTHER_COPIES" ]; then
  warn "环境检查提示（不阻断）："
  printf "$OTHER_COPIES"
  warn "如为残留副本，建议确认后删除（rm -rf <副本目录>）或先 uninstall 其服务"
fi

# ---- 1. 目录骨架（缺啥补啥，不覆盖已有文件） ----
# 资产层在根目录（roles/docs/scripts）；数据层在 workspace/（按项目分层：workspace/<项目>/ 下含全部子目录，
# 项目目录由 statectl register 在首次投放需求时自动创建；这里只建根与全局日志）
mkdir -p "$WORKSPACE"/{roles,docs,scripts,skills} "$WORKSPACE/logs"
[ -f "$WORKSPACE/status.lock" ] || touch "$WORKSPACE/status.lock"
touch "$WORKSPACE/logs/pipeline.log" "$WORKSPACE/logs/alarms.txt"
say "目录骨架就绪: $WORKSPACE（资产层 + logs/ 审计；项目数据在映射表 work_path）"

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
  say "安装完成，诊断全绿。投放需求: 先 project add <项目名> [路径] 登记，再放 需求.md 到 {work_path}/input/（默认 ~/project/<项目名>/input/）"
else
  warn "安装完成但诊断存在 FAIL（见上方报告，排查指南: docs/troubleshooting.md）"
fi
exit "$rc"
