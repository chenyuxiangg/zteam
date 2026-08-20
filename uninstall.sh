#!/usr/bin/env bash
# zteam 流水线卸载
# 默认: 移除 5 个 cron job + ~/.hermes/scripts 薄壳 + skill + zbot 职责配置，【保留全部数据】(项目产物/日志/需求)
# --full: 清空数据层 workspace/（全部项目：workspace/<项目>/{input,analysis,...,logs,status.json}），【保留项目资产】
#         （scripts/ roles/ docs/ skills/ 脚本/文档/git 历史）——交互确认输入 yes；或 REQREVIEW_FULL_YES=1 免交互
# 测试/部分卸载: REQREVIEW_NO_CRON=1 跳过 cron job 操作
# 用法: bash uninstall.sh [--full]
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_SCRIPTS="$HERMES_HOME/scripts"
HERMES_SKILLS="$HERMES_HOME/skills"

JOBS=(req-analyst-top req-reviewer-top req-worker-top req-weekly-audit req-result-notify)
WRAPPERS=(watchdog-analyst.sh watchdog-reviewer.sh watchdog-worker.sh watchdog-weekly.sh watchdog-notify.sh)

say()  { printf '\033[1;32m[uninstall]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[uninstall]\033[0m %s\n' "$*" >&2; }

FULL=0
[ "${1:-}" = "--full" ] && FULL=1

# ---- 0. --full 确认（不可恢复操作；REQREVIEW_FULL_YES=1 跳过交互，供 agent/自动化调用） ----
if [ "$FULL" -eq 1 ] && [ "${REQREVIEW_FULL_YES:-0}" != "1" ]; then
  echo "⚠️  --full 将清空数据层 workspace/（全部项目：workspace/<项目>/{input,analysis,...,logs,status.json}），项目资产与 git 历史保留；清空不可恢复"
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
  rm -f "$HERMES_SCRIPTS/$w" && say "已移除薄壳: $HERMES_SCRIPTS/$w"
done

# ---- 3.5 移除 skill（req-review-pipeline 运维手册） ----
rm -rf "$HERMES_SKILLS/req-review-pipeline" && say "已移除 skill: $HERMES_SKILLS/req-review-pipeline"

# ---- 4. 数据（--full：清空运行期数据，保留项目资产） ----
if [ "$FULL" -eq 1 ]; then
  # 安全校验：工作区必须是流水线目录（含 scripts/statectl.py）才允许清空
  if [ -f "$WORKSPACE/scripts/statectl.py" ] && [ "$WORKSPACE" != "$HOME" ] && [ "$WORKSPACE" != "/" ]; then
    # 清空范围（解耦后）：各项目 work_path 数据目录 + 项目映射表登记；保留 zteam/logs 审计与 status.lock
    # 保留范围：scripts/ roles/ docs/ skills/ projects.json 骨架/ README.md AGENTS.md install.sh uninstall.sh .gitignore .git/
    PJFILE="$WORKSPACE/projects.json"
    if [ -f "$PJFILE" ]; then
      python3 - "$PJFILE" <<'PYEOF'
import json, os, sys, shutil
pj = json.load(open(sys.argv[1], encoding="utf-8"))
for p in pj.get("projects", []):
    wp = p.get("work_path")
    if wp and os.path.isabs(wp) and wp != "/" and os.path.exists(wp):
        shutil.rmtree(wp, ignore_errors=True)
        print(f"  已清空项目数据: {p['name']} ({wp})")
json.dump({"projects": [], "updated_at": None}, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("  已清空项目映射表登记")
PYEOF
    fi
    mkdir -p "$WORKSPACE/logs"
    touch "$WORKSPACE/status.lock"
    touch "$WORKSPACE/logs/pipeline.log" "$WORKSPACE/logs/alarms.txt"
    say "已清空全部项目数据（work_path 目录 + projects.json 登记），项目资产与 git 历史保留"
    say "如需同步 git 备份: cd $WORKSPACE && git add -A && git commit -m 'uninstall --full 清空运行期数据' && git push"
  else
    warn "工作区校验未通过（$WORKSPACE），拒绝清空"
    exit 1
  fi
else
  warn "已保留数据: $WORKSPACE（如需清空运行期数据: bash $WORKSPACE/uninstall.sh --full）"
fi

say "卸载完成。gateway 保持运行（它同时服务 Hermes 其他功能；如不需要可 hermes gateway uninstall）"
