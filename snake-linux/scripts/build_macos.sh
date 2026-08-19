#!/usr/bin/env bash
# scripts/build_macos.sh — macOS .app 构建脚本（iter-4 G4-1）
# 用途：在 macOS 构建机上产出 dist/snake-gui.app（双架构：Intel + Apple Silicon）
# 前置：macOS 12+ / Python 3.8+ / pip install pyinstaller==5.13+
#
# 使用：
#   cd snake-linux/
#   bash scripts/build_macos.sh
#
# 产物：
#   dist/snake-gui-intel.app  （x86_64）
#   dist/snake-gui-arm64.app  （Apple Silicon）
#   若本机有 lipo：合并为 dist/snake-gui.app（universal2）

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 清理
rm -rf build dist

# 构建 Intel 版本
pyinstaller --clean --noconfirm --target-arch x86_64 spec/snake-gui.spec
if [ -d dist/snake-gui.app ]; then
    mv dist/snake-gui.app dist/snake-gui-intel.app
    echo "[build_macos] Intel 版本完成: dist/snake-gui-intel.app"
else
    echo "[build_macos] 失败: dist/snake-gui.app 未生成（Intel）" >&2
    exit 1
fi

# 构建 Apple Silicon 版本
pyinstaller --clean --noconfirm --target-arch arm64 spec/snake-gui.spec
if [ -d dist/snake-gui.app ]; then
    mv dist/snake-gui.app dist/snake-gui-arm64.app
    echo "[build_macos] Apple Silicon 版本完成: dist/snake-gui-arm64.app"
else
    echo "[build_macos] 失败: dist/snake-gui.app 未生成（arm64）" >&2
    exit 1
fi

# 合并双架构为 universal2（可选，需安装 lipo）
# r2 P1-3：以 arm64 完整 .app 为基础，仅替换 Contents/MacOS/snake-gui 二进制，
# 不重建 bundle 结构（避免丢失 Info.plist / Resources / 框架）
if command -v lipo &> /dev/null; then
    echo "[build_macos] 合并 universal2..."
    cp -R dist/snake-gui-arm64.app dist/snake-gui.app
    lipo -create \
        -output dist/snake-gui.app/Contents/MacOS/snake-gui \
        dist/snake-gui-intel.app/Contents/MacOS/snake-gui \
        dist/snake-gui-arm64.app/Contents/MacOS/snake-gui
    rm -rf dist/snake-gui-intel.app dist/snake-gui-arm64.app
    echo "[build_macos] universal2 合并完成: dist/snake-gui.app"
fi

# r2 P2-2：构建脚本只产包，不生成 SHA256SUMS（由 gen_sha256sums.sh 统一生成）
echo "[build_macos] 完成"
