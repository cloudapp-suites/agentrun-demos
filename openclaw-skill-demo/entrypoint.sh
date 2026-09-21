#!/bin/sh
# OpenClaw 容器入口：从环境变量生成 openclaw.json → 启动 Gateway
set -e

CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-/home/node/.openclaw/openclaw.json}"

if [ ! -f "$CONFIG_PATH" ]; then
  node - <<'EOF'
const fs = require("fs");
const cfgPath = process.env.OPENCLAW_CONFIG_PATH || "/home/node/.openclaw/openclaw.json";
const baseUrl = process.env.LLM_BASE_URL;
const apiKey = process.env.LLM_API_KEY;
const model = process.env.LLM_MODEL || "qwen3.8-flash";
if (!baseUrl || !apiKey) {
  console.error("LLM_BASE_URL / LLM_API_KEY are required");
  process.exit(1);
}
const cfg = {
  gateway: {
    mode: "local", // 网关运行模式（缺失会被判定为异常配置拒绝启动）
    bind: "lan", // 容器内默认 loopback 不可达，平台流量从 pod IP 进入
    auth: { mode: "token" }, // token 由 OPENCLAW_GATEWAY_TOKEN 环境变量提供
  },
  models: {
    mode: "merge",
    providers: {
      "agentrun-llm": {
        baseUrl,
        apiKey,
        api: "openai-completions",
        models: [
          {
            id: model,
            name: model,
            reasoning: false,
            input: ["text"],
            contextWindow: 131072,
            maxTokens: 16384,
          },
        ],
      },
    },
  },
  agents: { defaults: { model: { primary: `agentrun-llm/${model}` } } },
};
// Control UI 浏览器 Origin 校验：
// - 独占模式（isolation: isolated）：访问域名随会话 ID 变化，无法预先固定；
//   启用 Host 头校验（Origin 必须与访问的 Host 一致，即平台按 Host 路由的域名）
// - 固定域名部署：用 OPENCLAW_UI_ORIGIN 显式指定 Origin 白名单
if (process.env.OPENCLAW_UI_ORIGIN) {
  cfg.gateway.controlUi = { allowedOrigins: [process.env.OPENCLAW_UI_ORIGIN] };
} else {
  cfg.gateway.controlUi = { dangerouslyAllowHostHeaderOriginFallback: true };
}
// 平台在 Pod 内以 loopback 转发并携带 X-Forwarded-* 头，需声明可信代理来源
const proxies = (process.env.OPENCLAW_TRUSTED_PROXIES || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
if (proxies.length) {
  cfg.gateway.trustedProxies = proxies;
}
fs.mkdirSync(cfgPath.slice(0, cfgPath.lastIndexOf("/")), { recursive: true });
fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2));
console.log(`✓ openclaw.json generated: provider=agentrun-llm model=${model} bind=lan`);
EOF
else
  echo "✓ config exists: $CONFIG_PATH"
fi

exec node openclaw.mjs gateway
