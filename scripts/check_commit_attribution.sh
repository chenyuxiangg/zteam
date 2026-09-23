#!/usr/bin/env bash
# 检查 commit message 是否包含 attribution 行（Co-Authored-By）。
#
# 用法：
#   scripts/check_commit_attribution.sh           # 检查 HEAD
#   scripts/check_commit_attribution.sh <commit>  # 检查指定 commit
#   scripts/check_commit_attribution.sh HEAD~3..  # 检查范围内的所有 commit
#
# 退出码：0=全合规；1=有 commit 缺 attribution。

set -euo pipefail

# 期望的 attribution 标记
EXPECTED="Co-Authored-By: Claude Code <noreply@anthropic.com>"

if [[ $# -eq 0 ]]; then
    range="HEAD"
else
    range="$*"
fi

bad=0
total=0
while read -r sha; do
    [[ -z "$sha" ]] && continue
    total=$((total + 1))
    msg=$(git log -1 --format="%B" "$sha")
    if grep -qF "$EXPECTED" <<< "$msg"; then
        printf "✓ %s\n" "$(git log -1 --format='%h %s' "$sha")"
    else
        printf "✗ %s（缺少 Co-Authored-By）\n" "$(git log -1 --format='%h %s' "$sha")"
        bad=$((bad + 1))
    fi
done < <(git rev-list "$range" 2>/dev/null)

if [[ $total -eq 0 ]]; then
    echo "未找到任何 commit（range='$range'）" >&2
    exit 2
fi

echo "—— 共 $total 个 commit，$bad 个缺 attribution ——"
exit $((bad > 0 ? 1 : 0))
