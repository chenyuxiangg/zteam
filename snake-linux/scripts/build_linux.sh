#!/usr/bin/env bash
# scripts/build_linux.sh — Linux ELF 构建脚本（iter-4 G4-1）
# 用途：在 Linux 构建机上产出 dist/snake-gui（单文件可执行）
# 前置：Python 3.8+ / pip install pyinstaller==5.13+
#
# 使用：
#   cd snake-linux/
#   bash scripts/build_linux.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 清理
rm -rf build dist

# 构建
pyinstaller --clean --noconfirm spec/snake-gui.spec

# 重命名产物
if [ -f dist/snake-gui ]; then
    mv dist/snake-gui dist/snake-gui-linux-x86_64
    chmod +x dist/snake-gui-linux-x86_64
    echo "[build_linux] 完成: dist/snake-gui-linux-x86_64"
else
    echo "[build_linux] 失败: dist/snake-gui 未生成" >&2
    exit 1
fi

# r2 P2-2：构建脚本只产包，不生成 SHA256SUMS（由 gen_sha256sums.sh 统一生成）