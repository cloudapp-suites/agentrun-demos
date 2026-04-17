# OpenClaw 沙箱集成文档

OpenClaw 是一个 AI Agent 框架。平台提供统一预构建镜像，内置 E2B 和 AgentScope 两种沙箱插件，通过环境变量切换后端，无需修改代码或重新构建镜像。

> 如需直接使用 E2B SDK，请参阅 e2b.md；如需直接使用 AgentScope SDK，请参阅 agentscope-runtime.md。

---

## 1. 两种后端对比

| | E2B 后端 | AgentScope 后端 |
|---|----------|----------------|
| 协议 | E2B SDK（REST + Connect RPC） | AgentScope Runtime HTTP API |
| 沙箱镜像 | `e2b-sandbox` | `runtime-sandbox-all-in-one`（AgentScope Runtime） |
| 切换方式 | `SANDBOX_BACKEND=e2b` | `SANDBOX_BACKEND=agentscope` |

> 两种后端功能等价，共用同一个 sandbox-manager 服务和同一个 OpenClaw 镜像。

---

## 2. 部署步骤

### 步骤一：创建沙箱模板

在控制台「工具管理」页面，根据所选后端创建对应的工具：

- E2B 后端：选择 `e2b-sandbox` 类型
- AgentScope 后端：选择 `allinone-sandbox`（AgentScope）类型

> 两种 ToolServer 可同时创建，按需在 Agent 环境变量中选择使用哪个。

### 步骤二：创建 Agent

在控制台「Agent」页面创建 Agent：

| 字段 | 值 |
|------|-----|
| 名称 | `openclaw-sandbox-demo` |
| 镜像 | `apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/openclaw-unified:latest` |
| 端口 | `18789` |

### 步骤三：配置环境变量

#### 通用变量（两种后端共用）

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `SANDBOX_BACKEND` | 是 | 沙箱后端，`e2b` 或 `agentscope` |
| `LLM_BASE_URL` | 是 | LLM API 地址（如 `https://coding.dashscope.aliyuncs.com/v1`） |
| `LLM_API_KEY` | 是 | LLM API Key |
| `GATEWAY_TOKEN` | 否 | Gateway 访问令牌（默认 `default-token`） |
| `LLM_PROVIDER` | 否 | 提供商标识（默认 `dashscope`） |
| `LLM_MODEL_ID` | 否 | 模型 ID（默认 `qwen3-coder-plus`） |

#### E2B 后端额外变量（`SANDBOX_BACKEND=e2b`）

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `E2B_API_KEY` | 是 | sandbox-manager Token（从集群详情页获取） |

> `E2B_API_URL` 和 `E2B_SANDBOX_URL` 镜像内已有集群内默认值，通常无需配置。

#### AgentScope 后端额外变量（`SANDBOX_BACKEND=agentscope`）

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `SANDBOX_MANAGER_TOKEN` | 是 | sandbox-manager Token（从集群详情页获取） |
| `SANDBOX_TYPE` | 否 | ToolServer 名称（默认 `allinone-sandbox`） |

> `SANDBOX_MANAGER_URL` 镜像内已有集群内默认值，通常无需配置。

---

## 3. 切换后端

只需修改 Agent 的环境变量，无需重新构建镜像：

1. 将 `SANDBOX_BACKEND` 改为 `e2b` 或 `agentscope`
2. 填写对应后端的连接参数
3. 重新部署 Agent（控制台操作或 `kubectl delete` + `kubectl apply`）

---

## 4. 调用方式

部署完成后，通过 Agent 访问地址调用：

```bash
# Chat Completions 格式
curl -sS http://<agent-host>/v1/chat/completions \
  -H 'Authorization: Bearer <GATEWAY_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"openclaw:main","messages":[{"role":"user","content":"用 Python 计算 fibonacci(10)"}]}'

# Responses 格式（OpenAI SDK v2.24+ 默认）
curl -sS http://<agent-host>/v1/responses \
  -H 'Authorization: Bearer <GATEWAY_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"openclaw:main","input":"用 Python 计算 fibonacci(10)"}'
```

多轮对话需传入 `x-openclaw-session-key` header 或 body 中的 `user` 字段保持会话。

---

## 5. 集成原理

OpenClaw 统一镜像内置了 E2B 和 AgentScope 两种沙箱插件。启动时 `entrypoint.sh` 根据 `SANDBOX_BACKEND` 环境变量选择加载哪个插件：

```
SANDBOX_BACKEND=e2b
  → 加载 E2B 沙箱插件
  → 插件通过 E2B SDK 调用 sandbox-manager 的 /e2b 兼容 API
  → sandbox-manager 创建 e2b-sandbox Pod（envd 进程）
  → 代码执行通过 E2B SDK 代理到沙箱 Pod

SANDBOX_BACKEND=agentscope
  → 加载 AgentScope 沙箱插件
  → 插件通过 HTTP 直接调用 sandbox-manager 的 /create_from_pool、/call_tool
  → sandbox-manager 创建 allinone-sandbox Pod（AgentScope Runtime）
  → 代码执行通过 /call_tool 端点路由到沙箱 Pod
```

两种插件对上层的 chat completions 处理逻辑完全透明。LLM 决定调用工具时，插件负责把工具调用路由到对应的沙箱 Pod 并返回结果。

---

## 6. 环境变量速查

### E2B 后端

| 变量 | 说明 |
|------|------|
| `E2B_API_URL` | 管控面地址|
| `E2B_SANDBOX_URL` | 数据面地址 |
| `E2B_API_KEY` | sandbox-manager Bearer Token |

### AgentScope 后端

| 变量 | 说明 |
|------|------|
| `SANDBOX_MANAGER_URL` | sandbox-manager 地址 |
| `SANDBOX_MANAGER_TOKEN` | sandbox-manager Bearer Token |

> 集群内部署时，URL 变量通常使用默认值即可，只需配置 Token。

---

## 完整 Demo

- [openclaw-unified-sandbox](https://github.com/cloudapp-suites/agentrun-demos/tree/main/openclaw-unified-sandbox) — OpenClaw + 统一沙箱后端（E2B / AgentScope 运行时切换）
- [openclaw-agentscope-integration](https://github.com/cloudapp-suites/agentrun-demos/tree/main/openclaw-agentscope-integration) — OpenClaw + AgentScope 沙箱集成
- [openclaw-e2b-integration](https://github.com/cloudapp-suites/agentrun-demos/tree/main/openclaw-e2b-integration) — OpenClaw + E2B 沙箱集成
