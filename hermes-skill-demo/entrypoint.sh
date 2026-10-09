#!/bin/sh
# Hermes 容器入口：从环境变量生成 $HERMES_HOME/config.yaml（LLM Provider / 默认模型），
# 然后交给官方入口（s6-overlay）以默认参数 `gateway run` 启动 Dashboard + API Server
set -e

CONFIG_PATH="${HERMES_HOME:-/opt/data}/config.yaml"

if [ ! -f "$CONFIG_PATH" ]; then
  /opt/skill-runtime/bin/python3 - <<'EOF'
import json
import os

base = os.environ.get("LLM_BASE_URL")
key = os.environ.get("LLM_API_KEY")
model = os.environ.get("LLM_MODEL", "qwen3.8-flash")
if not base or not key:
    raise SystemExit("LLM_BASE_URL / LLM_API_KEY are required")


def y(s):
    # JSON 字符串也是合法的 YAML 标量，避免引号/转义问题
    return json.dumps(s, ensure_ascii=False)


home = os.environ.get("HERMES_HOME", "/opt/data")
config = (
    "providers:\n"
    "  agentrun-llm:\n"
    f"    api: {y(base)}\n"
    f"    api_key: {y(key)}\n"
    "    discover_models: false\n"
    "    models:\n"
    f"      - {y(model)}\n"
    "model:\n"
    "  provider: agentrun-llm\n"
    f"  default: {y(model)}\n"
    "  api_mode: chat_completions\n"
)
os.makedirs(home, exist_ok=True)
path = os.path.join(home, "config.yaml")
with open(path, "w", encoding="utf-8") as f:
    f.write(config)
try:
    os.chown(path, 10000, 10000)  # hermes 用户（官方镜像 UID 10000）
except PermissionError:
    pass
print(f"✓ config.yaml generated: provider=agentrun-llm model={model}")
EOF
else
  echo "✓ config exists: $CONFIG_PATH"
fi

if [ "$#" -gt 0 ]; then
  exec /opt/hermes/docker/entrypoint-dispatch.sh "$@"
fi
exec /opt/hermes/docker/entrypoint-dispatch.sh gateway run
