#!/bin/bash
# 一键构建 Dify E2B 插件包
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/plugin"

# 解压 E2B SDK
if [ ! -d "$PLUGIN_DIR/e2b" ]; then
    echo "=== 解压 E2B SDK ==="
    tar xzf "$PLUGIN_DIR/e2b-sdk.tar.gz" -C "$PLUGIN_DIR"
fi

# 打包（临时移除 .gitignore，dify CLI 会读它跳过文件）
echo "=== 打包插件 ==="
GITIGNORE="$PLUGIN_DIR/.gitignore"
mv "$GITIGNORE" "$GITIGNORE.bak" 2>/dev/null || true
dify plugin package "$PLUGIN_DIR" -o "$SCRIPT_DIR/deploy/e2b-sandbox.difypkg"
mv "$GITIGNORE.bak" "$GITIGNORE" 2>/dev/null || true

echo "=== 完成: deploy/e2b-sandbox.difypkg ==="
