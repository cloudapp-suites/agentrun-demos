# CoPaw 沙箱集成文档

CoPaw 是一个 Python Agent 框架。平台提供统一预构建镜像，内置 E2B 和 AgentScope 两种沙箱支持，通过环境变量切换后端，无需修改代码或重新构建镜像。

> 如需直接使用 E2B SDK，请参阅 e2b.md；如需直接使用 AgentScope SDK，请参阅 agentscope-runtime.md。

---

## 1. 两种后端对比

| | E2B 后端 | AgentScope 后端 |
|---|----------|----------------|
| 协议 | E2B SDK（REST + Connect RPC） | HTTP API（/call_tool） |
| 沙箱镜像 | `e2b-sandbox-copaw` | `runtime-sandbox-all-in-one`（AgentScope Runtime） |
| 切换方式 | `COPAW_CONFIG_JSON` 中不填 type | `COPAW_CONFIG_JSON` 中 `type: "agentscope"` |

> 两种后端功能等价，共用同一个 sandbox-manager 服务和同一个 CoPaw 镜像。

---

## 2. 部署步骤

### 步骤一：创建沙箱模板

在控制台「工具管理」页面，根据所选后端创建对应的工具：

- E2B 后端：选择 `e2b-sandbox` 类型
- AgentScope 后端：选择 `allinone-sandbox`（AgentScope）类型

### 步骤二：创建 Agent

在控制台「Agent」页面创建 Agent：

| 字段 | 值 |
|------|-----|
| 名称 | `copaw-sandbox-demo` |
| 镜像 | `apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/copaw-unified:latest` |
| 端口 | `8088` |

### 步骤三：配置环境变量

#### 通用变量（两种后端共用）

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `COPAW_API_KEYS` | 是 | CoPaw 认证密钥（格式 `用户名:密钥`，如 `user1:<your-api-key>`） |
| `COPAW_PROVIDERS_JSON` | 是 | LLM 配置（见下方） |

`COPAW_PROVIDERS_JSON` 示例：

```json
{
  "providers": {
    "aliyun": {
      "base_url": "https://coding.dashscope.aliyuncs.com/v1",
      "api_key": "<your-llm-api-key>"
    }
  },
  "active_llm": {
    "provider_id": "aliyun",
    "model": "qwen3-coder-plus"
  }
}
```

#### E2B 后端（默认）

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `COPAW_CONFIG_JSON` | 否 | 沙箱配置（见下方，镜像有默认值） |
| `E2B_API_KEY` | 是 | sandbox-manager Token（从集群详情页获取） |

`COPAW_CONFIG_JSON` 示例：

```json
{"sandbox": {"enabled": true, "template_id": "e2b-sandbox-copaw"}}
```

> `E2B_API_URL` 和 `E2B_SANDBOX_URL` 镜像内已有集群内默认值，通常无需配置。

#### AgentScope 后端

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `COPAW_CONFIG_JSON` | 是 | 沙箱配置（见下方） |
| `SANDBOX_MANAGER_URL` | 是 | sandbox-manager 地址（从集群详情页获取） |
| `SANDBOX_MANAGER_TOKEN` | 是 | sandbox-manager Token（从集群详情页获取） |

`COPAW_CONFIG_JSON` 示例：

```json
{"sandbox": {"enabled": true, "type": "agentscope", "template_id": "allinone-sandbox"}}
```

---

## 3. 切换后端

只需修改 Agent 的环境变量，无需重新构建镜像：

1. 修改 `COPAW_CONFIG_JSON` 中的 `sandbox.type` 字段（不填或 `"e2b"` → E2B，`"agentscope"` → AgentScope）
2. 填写对应后端的连接参数（E2B 需要 `E2B_API_KEY`，AgentScope 需要 `SANDBOX_MANAGER_URL` + `SANDBOX_MANAGER_TOKEN`）
3. 重新部署 Agent（控制台操作或 `kubectl delete` + `kubectl apply`）

---

## 4. 使用方式

部署完成后，浏览器访问 Agent 地址即可打开 CoPaw Console 界面，在对话中即可使用沙箱执行代码。

API 调用：

```bash
curl -sS -N http://<agent-host>/api/agent/process \
  -H 'Authorization: Bearer <COPAW_API_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "test-session",
    "input": [{"role": "user", "content": [{"type": "text", "text": "用 Python 计算 fibonacci(10)"}]}]
  }'
```

> 响应为 SSE 流式格式。`COPAW_API_KEY` 是 `COPAW_API_KEYS` 中冒号后面的部分（如配置 `user1:my-key`，则用 `my-key`）。多轮对话使用相同 `session_id` 保持上下文。

---

## 5. 集成原理

CoPaw 统一镜像通过 `fs_backend` 抽象层实现双后端支持。启动时根据 `COPAW_CONFIG_JSON` 中的 `sandbox.type` 选择后端：

```
sandbox.type 不填 / "e2b"
  → E2BSandboxProvider 通过 E2B SDK 创建沙箱
  → set_backend(E2BBackend(sandbox))
  → 工具调用通过 E2B SDK 代理到 e2b-sandbox-copaw Pod

sandbox.type = "agentscope"
  → AgentscopeSandboxProvider 通过 HTTP 调用 sandbox-manager
  → set_backend(AgentscopeBackend(handle))
  → 工具调用通过 /call_tool 端点路由到 allinone-sandbox Pod
```

### 架构分层

```
┌─────────────────────────────────────────────────┐
│  统一工具层 (tools.py)                            │
│  execute_shell_command / execute_python_code      │
│  sandbox_read_file / sandbox_write_file / ...     │
│  ↓ 调用 get_backend()                            │
├─────────────────────────────────────────────────┤
│  fs_backend 抽象层 (adapter.py)                   │
│  ┌──────────────┬──────────────┬──────────────┐  │
│  │ E2BBackend   │ Agentscope   │ LocalBackend │  │
│  │ E2B SDK      │ Backend      │ 本地执行     │  │
│  │ commands.run  │ /call_tool   │ subprocess   │  │
│  └──────────────┴──────────────┴──────────────┘  │
├─────────────────────────────────────────────────┤
│  SandboxProvider 层（生命周期管理）                │
│  E2BSandboxProvider / AgentscopeSandboxProvider   │
└─────────────────────────────────────────────────┘
         ↓                    ↓
    sandbox-manager      sandbox-manager
    /e2b API             /create_from_pool
         ↓                    ↓
    agent-runtime-controller (K8s)
         ↓                    ↓
    e2b-sandbox Pod      allinone-sandbox Pod
```

所有工具函数通过 `get_backend()` 获取当前后端实例，完全不感知具体是 E2B 还是 AgentScope，实现了后端透明切换。

### 沙箱工具列表

| 工具 | 说明 |
|------|------|
| `execute_shell_command` | Shell 命令在沙箱中执行（同名覆盖本地工具） |
| `execute_python_code` | Python 代码在沙箱中执行（同名覆盖本地工具） |
| `sandbox_read_file` | 读取沙箱内文件 |
| `sandbox_write_file` | 写入沙箱内文件（自动创建父目录） |
| `sandbox_list_files` | 列出沙箱内目录（支持 depth） |
| `sandbox_download_file` | 下载沙箱文件到本地 |

---

## 6. 环境变量速查

### E2B 后端

| 变量 | 说明 |
|------|------|
| `E2B_API_URL` | 管控面地址 |
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

- [copaw-unified-sandbox](https://github.com/cloudapp-suites/agentrun-demos/tree/main/copaw-unified-sandbox) — CoPaw + 统一沙箱后端（E2B / AgentScope 运行时切换）
