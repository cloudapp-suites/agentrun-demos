# AgentScope MCP Demo

基于 [AgentScope](https://github.com/modelscope/agentscope) ReActAgent +
[agentscope-runtime](https://github.com/modelscope/agentscope-runtime) 的多远程 MCP 工具 AI 助手。

通过 streamable-HTTP 协议连接一个或多个远程 MCP 服务，自动发现并注册所有工具，
提供符合 [AgentScope Runtime 协议](https://runtime.agentscope.io/en/protocol.html) 的标准 HTTP 接口（SSE 流式响应），支持多会话并发。

## 你将学到什么

通过阅读和运行本 Demo，你可以了解：

- 如何用 AgentScope 的 `ReActAgent` 构建一个具备工具调用能力的 AI 助手
- 如何通过 `HttpStatefulClient` 连接远程 MCP 服务并自动注册工具
- 如何用 `agentscope-runtime` 的 `AgentApp` 将 Agent 包装为标准 HTTP 服务
- 如何实现基于 `session_id` 的多会话内存隔离
- 如何将 AgentScope 的 session_id 作为 `x-agentrun-session-id` 透传到 MCP 工具请求头，实现 agentrun 平台的会话亲和与独占会话沙箱选择
- 如何通过 `config.py` 实现配置与代码分离，无需修改主程序即可调整行为

## 代码阅读指引

建议按以下顺序阅读源码：

1. **`config.py`** — 从配置入手，了解 SYS_PROMPT 和 MCP_SERVERS 的数据结构
2. **`app.py`** — 核心逻辑，重点关注：
   - `_build_model()` — 如何根据环境变量构建不同 provider 的模型实例
   - `query_func()` — 每次请求的完整生命周期：连接 MCP → 创建 Agent → 流式响应 → 断开连接
   - `_build_headers()` — 如何将 session_id 透传到 MCP 服务实现会话关联
   - `init_func()` / `shutdown_func()` — AgentApp 的生命周期钩子

---

## 文件结构

```
agentscope-mcp/
├── config.py          # 用户配置文件（SYS_PROMPT、MCP 服务列表）← 主要调试入口
├── app.py             # Web 服务入口（基于 AgentApp）
├── requirements.txt   # Python 依赖
├── Dockerfile         # 容器镜像定义
├── build_image.sh     # 构建 Docker 镜像脚本
└── README.md          # 本文档
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 MCP 服务与系统提示词

编辑 `config.py`（详见[配置说明 → config.py](#configpy--用户代码配置)）。

### 3. 设置环境变量

```bash
export OPENAI_API_KEY=sk-xxxx
export OPENAI_MODEL_NAME=qwen-plus
export OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 4. 启动服务

```bash
python app.py
```

服务启动后：

| 接口 | 说明 |
|------|------|
| `POST http://localhost:8080/process` | 主对话接口（SSE 流式） |
| `GET  http://localhost:8080/health`  | 健康检查 |
| `GET  http://localhost:8080/`        | 服务信息 |

---

## 请求示例

请求示例参见 [curl 调用 Agent](../agent-integration-docs/agent/code/curl.md)。

---

## 配置说明

本 Demo 有两类配置入口，分工明确：

| 配置方式 | 适用内容 | 生效方式 |
|---------|---------|---------|
| `config.py`（代码） | SYS_PROMPT、MCP 服务列表 | 重启进程 |
| 环境变量 | 模型 provider、API Key、模型名称、服务端口等 | 重启进程或重启容器 |

---

### config.py — 用户代码配置

#### SYS_PROMPT（最简单的调试入口）

```python
SYS_PROMPT: str = (
    "你是一个智能 AI 助手，具备通过 MCP 工具调用远程服务的能力。\n"
    "请根据用户需求，合理选择并调用工具完成任务，并给出清晰的结果说明。\n"
    "如果没有合适的工具可用，请直接用已有知识回答用户问题。"
)
```

修改示例：

| 目标 | 做法 |
|------|------|
| 限制回答语言 | 末尾加 `"所有回答必须使用中文。"` |
| 限制话题范围 | 加 `"只回答与代码相关的问题，拒绝其他话题。"` |
| 调整输出格式 | 加 `"所有回答请使用 Markdown 格式。"` |
| 设定角色 | 首行改为 `"你是一名资深 DevOps 工程师，..."` |

#### MCP_SERVERS（MCP 服务列表）

```python
MCP_SERVERS: list[MCPServerConfig] = [
    MCPServerConfig(
        name="sandbox",
        url="https://sandbox.example.com/mcp",
        token="your-token",
    ),
]
```

`MCPServerConfig` 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 服务唯一标识名称，用于日志区分 |
| `url` | str | MCP 端点 URL |
| `token` | str | 访问凭证，以 `Authorization: Bearer <token>` 发送；留空则不添加 |
| `transport` | str | `streamable_http`（URL 默认路径为 `/`）或 `sse`（以 `/sse` 结尾） |
| `timeout` | float | 单次请求超时（秒），默认 120 |
| `sse_read_timeout` | float | SSE 读取超时（秒），默认 120 |
| `extra_headers` | dict | 额外自定义请求头 |

**x-agentrun-session-id 说明**

每次请求将 `AgentRequest.session_id`（即本次对话的会话 ID）作为 `x-agentrun-session-id` 附加到 MCP 服务的请求头中。
MCP 服务端可用此字段将工具调用与客户端会话绑定，实现上下文隔离与日志追踪。

在线调试时如需将多个请求路由到同一个固定 session（例如复现某次异常），可在 `extra_headers` 中覆盖：

```python
extra_headers={"x-agentrun-session-id": "debug-session-fixed-id-001"}
```

---

### 环境变量参考

#### 服务地址

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `HOST` | 服务监听地址 | `0.0.0.0` |
| `PORT` | 服务监听端口 | `8080` |

#### 模型 Provider（二选一）

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `MODEL_PROVIDER` | 使用哪套 provider：`openai` 或 `dashscope` | `openai` |

#### OpenAI 兼容接口（`MODEL_PROVIDER=openai` 时使用）

| 变量名 | 是否必填 | 说明 | 默认值 |
|--------|---------|------|--------|
| `OPENAI_API_KEY` | 必填 | API 访问密钥 | — |
| `OPENAI_API_BASE` | 可选 | 模型访问地址（支持 DashScope、DeepSeek、Moonshot 等兼容接口） | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `OPENAI_MODEL_NAME` | 可选 | 模型名称 | `qwen-plus` |

#### DashScope 原生 SDK（`MODEL_PROVIDER=dashscope` 时使用）

| 变量名 | 是否必填 | 说明 | 默认值 |
|--------|---------|------|--------|
| `DASHSCOPE_API_KEY` | 必填 | DashScope API 密钥 | — |
| `DASHSCOPE_API_BASE` | 可选 | 自定义 DashScope 访问地址 | — |
| `DASHSCOPE_MODEL_NAME` | 可选 | 模型名称 | `qwen-plus` |

#### Agent 行为

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `MAX_ITERS` | ReActAgent 最大推理-行动循环次数 | `15` |
| `PARALLEL_TOOL_CALLS` | 是否并行执行多工具调用，`true`/`false` | `false` |
| `MODEL_STREAM` | 是否启用模型流式输出，`true`/`false` | `true` |

#### 日志

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `LOG_LEVEL` | 日志级别：`DEBUG`/`INFO`/`WARNING`/`ERROR` | `INFO` |

---

## Docker 部署

### 构建镜像

```bash
./build_image.sh                     # 默认：agentscope-mcp:latest
./build_image.sh my-demo v1.0        # 自定义镜像名和标签
```

### 启动 Web 服务

```bash
docker run -d --name mcp-assistant \
  -p 8080:8080 \
  -e OPENAI_API_KEY=sk-xxxx \
  -e OPENAI_MODEL_NAME=qwen-plus \
  -e OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 \
  agentscope-mcp:latest
```

### 使用 DashScope 原生 SDK

```bash
docker run -d --name mcp-assistant \
  -p 8080:8080 \
  -e MODEL_PROVIDER=dashscope \
  -e DASHSCOPE_API_KEY=sk-xxxx \
  -e DASHSCOPE_MODEL_NAME=qwen-max \
  agentscope-mcp:latest
```

### 挂载自定义 config.py（在线调试首选，无需重建镜像）

修改本地 `config.py`（SYS_PROMPT 或 MCP_SERVERS）后，挂载重启即可：

```bash
docker run -d --name mcp-assistant \
  -p 8080:8080 \
  -e OPENAI_API_KEY=sk-xxxx \
  -v $(pwd)/config.py:/app/config.py:ro \
  agentscope-mcp:latest
```

### 完整参数示例

```bash
docker run -d --name mcp-assistant \
  -p 8080:8080 \
  -e HOST=0.0.0.0 \
  -e PORT=8080 \
  -e MODEL_PROVIDER=openai \
  -e OPENAI_API_KEY=sk-xxxx \
  -e OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 \
  -e OPENAI_MODEL_NAME=qwen-plus \
  -e MAX_ITERS=15 \
  -e PARALLEL_TOOL_CALLS=false \
  -e MODEL_STREAM=true \
  -e LOG_LEVEL=INFO \
  -v $(pwd)/config.py:/app/config.py:ro \
  agentscope-mcp:latest
```

---


## 常见问题

**Q: 如何同时连接多个 MCP 服务？**

在 `config.py` 的 `MCP_SERVERS` 列表中添加多个 `MCPServerConfig` 即可，每次请求会按顺序连接并将所有工具合并注册。

**Q: 如何实现多轮对话？**

客户端每次请求传入同一个 `session_id`，服务端会自动复用对应的 `InMemoryMemory`，保留历史上下文。

**Q: 如何调试 MCP 连接问题？**

1. 确认 URL 格式正确（`streamable_http` → `/mcp`，`sse` → `/sse`）
2. 确认 `token` 填写正确
3. 查看日志（`LOG_LEVEL=DEBUG`），每次请求会打印 `session-id`，可在 MCP 服务端按此 ID 查找对应日志

**Q: 如何在线调试时固定 MCP session-id？**

正常情况下 `x-agentrun-session-id` 与请求的 `session_id` 保持一致，无需手动设置。
如需将多个不同会话的请求路由到 MCP 服务端同一个固定 session（例如复现某次异常），在 `extra_headers` 中覆盖即可：

```python
extra_headers={"x-agentrun-session-id": "my-debug-session-001"}
```

---

## 平台部署

### 打包模式

1. 运行打包工具，运行时选择 **Python 3.12**：
   ```bash
   ../pack-tools/pack-python.sh -s .
   ```
2. 在管控台创建 Agent，选择「上传压缩包」，上传生成的 `.tar.gz`
3. 启动命令：`sh start.sh`
4. HTTP 端口：`8080`
5. 健康检查：`/health`

### 必填环境变量

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | 模型 API Key |

完整环境变量列表见上方[环境变量参考](#环境变量参考)。
