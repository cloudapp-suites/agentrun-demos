# MCP JSON 配置

本文档演示如何在 MCP 客户端（IDE、Agent 框架等）中通过 JSON 配置接入平台托管的 ToolServer。

---

## 配置示例

```json
{
  "mcpServers": {
    "{{name}}": {
      "type": "streamable_http",
      "url": "https://{{endpoint}}/",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

---

## 字段说明

| 字段 | 说明                                                     |
|------|--------------------------------------------------------|
| `type` | 固定为 `streamable_http`，使用 Streamable HTTP 传输协议          |
| `url` | ToolServer 的访问地址。平台托管的 ToolServer 默认以 `/` 作为 MCP 端点    |
| `Authorization` | 访问凭证，格式为 `Bearer <token>`。请替换为工具设置中配置的凭证；若工具未绑定凭证则无需携带 |

---

## 无凭证场景

若工具未绑定访问凭证，省略 `headers` 即可：

```json
{
  "mcpServers": {
    "{{name}}": {
      "type": "streamable_http",
      "url": "https://{{endpoint}}/"
    }
  }
}
```

---

## 关于 `x-agentrun-session-id`

`x-agentrun-session-id` 是平台特有的请求头，用于会话亲和与流量路由，与 MCP 协议自身的 session id（由服务端在响应中返回）是两个独立的概念。

JSON 配置中的 `headers` 是静态值，无法在运行时动态替换。因此 `x-agentrun-session-id` 不适合写在 JSON 配置中，而应通过编程方式在每次建立连接时注入，将其关联到应用的会话 ID。

| 工具类型 | 是否必须 | 说明 |
|---------|---------|------|
| 沙箱工具（独占模式） | **必须** | 平台依据此值将请求路由到同一沙箱容器，保持进程状态（IPython 变量、文件系统、浏览器实例等）在多次调用间持续存在。同一会话期间应保持一致，建议使用应用会话 ID 或随机 UUID |
| 非沙箱工具（共享模式） | 非必须 | 不携带不影响功能，但携带后有利于会话亲和与日志追踪 |

编程方式注入示例见 Python 接入方式。

---

## 补充说明

- **`{{endpoint}}`**：替换为实际的 ToolServer 访问地址。
- **`{{name}}`**：替换为 ToolServer 名称，作为 MCP 客户端中的服务标识。
- 沙箱工具通过 MCP 配置即可直接使用沙箱暴露的所有工具（代码执行、文件操作、浏览器控制等），无需额外的沙箱 SDK。

---

## 完整 Demo

- [code-execution-mcp](https://github.com/cloudapp-suites/agentrun-demos/tree/main/code-execution-mcp) — 基于 MCP 协议的多语言代码执行 ToolServer
- [mcp-client-sample](https://github.com/cloudapp-suites/agentrun-demos/tree/main/mcp-client-sample) — MCP Python SDK 示例客户端
