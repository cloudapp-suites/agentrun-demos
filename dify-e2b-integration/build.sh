#!/bin/bash
# 一键构建 Dify E2B 插件包
# 1. 拉取 E2B SDK（如果不存在）
# 2. 打包为 .difypkg
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/plugin"
OUTPUT_DIR="$SCRIPT_DIR/deploy"

# Step 1: 确保 E2B SDK 存在
if [ ! -d "$PLUGIN_DIR/e2b" ]; then
    echo "=== E2B SDK 不存在，运行 setup-sdk.sh ==="
    bash "$PLUGIN_DIR/setup-sdk.sh"
fi

# Step 2: 打包（临时移除 .gitignore，否则 dify CLI 会跳过 e2b/）
GITIGNORE="$PLUGIN_DIR/.gitignore"
if [ -f "$GITIGNORE" ]; then
    mv "$GITIGNORE" "$GITIGNORE.bak"
fi

echo "=== 打包插件 ==="
dify plugin package "$PLUGIN_DIR" -o "$OUTPUT_DIR/e2b-sandbox.difypkg"

# 恢复 .gitignore
if [ -f "$GITIGNORE.bak" ]; then
    mv "$GITIGNORE.bak" "$GITIGNORE"
fi

echo ""
echo "=== 构建完成 ==="
echo "插件包: $OUTPUT_DIR/e2b-sandbox.difypkg"
