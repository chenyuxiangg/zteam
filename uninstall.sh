#!/usr/bin/env bash
# req-review 流水线卸载
# 默认: 移除 4 个 cron job + ~/.hermes/scripts 薄壳 + zbot 职责配置，【保留全部数据】(status.json/产物/日志/需求)
# --full: 清空数据层 workspace/（input/ analysis/ review/ artifacts/ logs/ status.json），【保留项目资产】
#         （scripts/ roles/ docs/ 脚本/文档/git 历史）——交互确认输入 yes；或 REQREVIEW_FULL_YES=1 免交互
# 测试/部分卸载: REQREVIEW_NO_CRON=1 跳过 cron job 操作
# 用法: bash uninstall.sh [--full]
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_SCRIPTS="$HOME/.hermes/scripts"

JOBS=(req-analyst-top req-reviewer-top req-weekly-audit req-result-notify)
WRAPPERS=(watchdog-analyst.sh watchdog-reviewer.sh watchdog-weekly.sh watchdog-notify.sh)

say()  { printf '\033[1;32m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[uninstall]\033[0m %s\n' "$*" >&2; }

FULL=0
[ "${1:-}" = "--full" ] && FULL=1

# ---- 0. --full 确认（不可恢复操作；REQREVIEW_FULL_YES=1 跳过交互，供 agent/自动化调用） ----
if [ "$FULL" -eq 1 ] && [ "${REQREVIEW_FULL_YES:-0}" != "1" ]; then
  echo "⚠️  --full 将清空数据层 workspace/（input/ analysis/ review/ artifacts/ logs/ status.json），项目资产与 git 历史保留；清空不可恢复"
  read -r -p "输入 yes 确认: " ans
  [ "$ans" = "yes" ] || { echo "已取消"; exit 1; }
fi

# ---- 1. 移除 zbot 职责配置（数据删除前执行——bot_config.py 在工作区内，删数据后无法再调用） ----
if [ -f "$WORKSPACE/scripts/bot_config.py" ]; then
  python3 "$WORKSPACE/scripts/bot_config.py" uninstall || warn "zbot 职责配置移除失败（可手动: python3 scripts/bot_config.py uninstall）"
  say "zbot 职责配置已移除；gateway 内存中旧配置无害（job 已移除），如需立即生效: systemctl --user restart hermes-gateway"
else
  warn "未找到 bot_config.py，跳过 zbot 配置移除"
fi

# ---- 2. 移除 cron jobs（按名反查 id，缺哪个删哪个；失败只告警不中断） ----
if [ "${REQREVIEW_NO_CRON:-0}" = "1" ]; then
  say "跳过 cron 操作（REQREVIEW_NO_CRON=1，测试/部分卸载模式）"
else
  LIST="$(hermes cron list 2>/dev/null || true)"
  for name in "${JOBS[@]}"; do
    id="$(echo "$LIST" | grep -B1 "Name:.*$name" | grep -oE '[0-9a-f]{12}' | head -1 || true)"
    if [ -n "$id" ]; then
      if hermes cron remove "$id" >/dev/null 2>&1; then
        say "已移除 job: $name ($id)"
      else
        warn "移除 job 失败（继续）: $name ($id)"
      fi
    else
      say "job 不存在，跳过: $name"
    fi
  done
fi

# ---- 3. 移除薄壳 ----
for w in "${WRAPPERS[@]}"; do
  rm -f "$HERMES_SCRIPTS/$w" && say "已移除薄壳: ~/.hermes/scripts/$w"
done

# ---- 4. 数据（--full：清空运行期数据，保留项目资产） ----
if [ "$FULL" -eq 1 ]; then
  # 安全校验：工作区必须是流水线目录（含 scripts/statectl.py）才允许清空
  if [ -f "$WORKSPACE/scripts/statectl.py" ] && [ "$WORKSPACE" != "$HOME" ] && [ "$WORKSPACE" != "/" ]; then
    # 清空范围：workspace/ 整个数据层（input/ analysis/ review/ artifacts/ logs/ status.json）
    # 保留范围：scripts/ roles/ docs/ README.md AGENTS.md install.sh uninstall.sh .gitignore .git/
    rm -rf "$WORKSPACE/workspace"
    # 重建空骨架（与 install.sh 目录结构一致，保证 uninstall 后工作区仍可用）
    mkdir -p "$WORKSPACE/workspace"/{input,analysis,review,artifacts,logs}
    echo '{}' > "$WORKSPACE/workspace/status.json"
    touch "$WORKSPACE/workspace/logs/pipeline.log" "$WORKSPACE/workspace/logs/alarms.txt" "$WORKSPACE/workspace/status.lock"
    say "已清空数据层 workspace/（input/ analysis/ review/ artifacts/ logs/ status.json），项目资产与 git 历史保留"
    say "如需同步 git 备份: cd $WORKSPACE && git add -A && git commit -m 'uninstall --full 清空运行期数据' && git push"
  else
    warn "工作区校验未通过（$WORKSPACE），拒绝清空"
    exit 1
  fi
else
  warn "已保留数据: $WORKSPACE（如需清空运行期数据: bash $WORKSPACE/uninstall.sh --full）"
fi

say "卸载完成。gateway 保持运行（它同时服务 Hermes 其他功能；如不需要可 hermes gateway uninstall）"
