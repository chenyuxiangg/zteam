#!/usr/bin/env bash
# scripts/gen_sha256sums.sh — 生成三平台包 SHA256SUMS（iter-4 G4-1）
# 用途：发布前统一生成校验和，输出到 dist/SHA256SUMS
# 前置：dist/ 下已生成构建产物
#
# 使用：
#   bash scripts/gen_sha256sums.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ ! -d dist ]; then
    echo "[gen_sha256sums] 警告: dist/ 不存在，无产物可校验" >&2
    exit 0
fi

{
    if [ -f dist/snake-gui-linux-x86_64 ]; then
        sha256sum dist/snake-gui-linux-x86_64
    fi
    if [ -f dist/snake-gui-windows-x86_64.exe ]; then
        sha256sum dist/snake-gui-windows-x86_64.exe
    fi
    if [ -d dist/snake-gui.app ]; then
        find dist/snake-gui.app -type f -exec sha256sum {} \;
    fi
} > dist/SHA256SUMS

echo "[gen_sha256sums] SHA256SUMS 已生成"
cat dist/SHA256SUMS
