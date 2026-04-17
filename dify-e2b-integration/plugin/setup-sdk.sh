#!/bin/bash
# 拉取 E2B Python SDK 并拷贝到插件目录
# 打包插件前需要先运行此脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
E2B_REPO="https://github.com/e2b-dev/E2B.git"
E2B_BRANCH="main"
TMP_DIR=$(mktemp -d)

echo "=== 拉取 E2B Python SDK ==="
git clone --depth 1 --branch "$E2B_BRANCH" "$E2B_REPO" "$TMP_DIR/E2B"

SDK_SRC="$TMP_DIR/E2B/packages/python-sdk"

if [ ! -d "$SDK_SRC/e2b" ]; then
    echo "Error: E2B Python SDK not found at $SDK_SRC/e2b"
    rm -rf "$TMP_DIR"
    exit 1
fi

# 拷贝 SDK 核心包
echo "=== 拷贝 e2b/ ==="
rm -rf "$SCRIPT_DIR/e2b" "$SCRIPT_DIR/e2b_connect"
cp -r "$SDK_SRC/e2b" "$SCRIPT_DIR/e2b"

# 拷贝 Connect RPC 客户端
if [ -d "$SDK_SRC/e2b_connect" ]; then
    echo "=== 拷贝 e2b_connect/ ==="
    cp -r "$SDK_SRC/e2b_connect" "$SCRIPT_DIR/e2b_connect"
fi

# Patch metadata.py — 内嵌 SDK 无法通过 importlib.metadata 获取版本号
METADATA_FILE="$SCRIPT_DIR/e2b/api/metadata.py"
if [ -f "$METADATA_FILE" ]; then
    cat > "$METADATA_FILE" << 'PYEOF'
"""Patched metadata for embedded E2B SDK."""

def get_version() -> str:
    try:
        from importlib.metadata import version
        return version("e2b")
    except Exception:
        return "1.0.0"
PYEOF
    echo "=== Patched e2b/api/metadata.py ==="
fi

# 清理
rm -rf "$TMP_DIR"

echo ""
echo "=== 完成 ==="
echo "e2b/ 和 e2b_connect/ 已就绪，可以打包插件："
echo "  dify plugin package $(dirname "$SCRIPT_DIR")/plugin/"
