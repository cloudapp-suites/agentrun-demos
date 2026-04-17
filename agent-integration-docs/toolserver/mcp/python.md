# Python MCP 客户端访问 ToolServer

本文档演示如何通过 Python MCP SDK 以 Streamable HTTP 协议访问平台托管的 ToolServer。

**安装依赖：**
```bash
pip install mcp
```

**公共变量说明（以下所有示例均使用这些变量）：**

```python
import uuid

# ⚠️ 请替换为实际的 ToolServer 访问地址
ENDPOINT = "https://{{endpoint}}/"

# ⚠️ 如工具绑定了访问凭证，请替换为实际 Token；未绑定则设为 None
TOKEN = "YOUR_TOKEN_HERE"

# 平台会话 ID：同一会话期间保持一致，用于会话亲和与流量路由
# 注意：这是平台特有的请求头，与 MCP 协议自身的 session id（由服务端返回）无关
SESSION_ID = str(uuid.uuid4())
```

---

## 列出可用工具

```python
import asyncio
import json
import uuid
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ENDPOINT = "https://{{endpoint}}/"
TOKEN = "YOUR_TOKEN_HERE"
SESSION_ID = str(uuid.uuid4())


def build_headers() -> dict[str, str]:
    headers: dict[str, str] = {"x-agentrun-session-id": SESSION_ID}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


async def main():
    headers = build_headers()

    async with streamablehttp_client(ENDPOINT, headers=headers, timeout=60) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    tools = [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.inputSchema,
        }
        for t in result.tools
    ]
    print(json.dumps(tools, ensure_ascii=False, indent=2))


asyncio.run(main())
```

---

## 调用工具

```python
import asyncio
import uuid
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ENDPOINT = "https://{{endpoint}}/"
TOKEN = "YOUR_TOKEN_HERE"
SESSION_ID = str(uuid.uuid4())


def build_headers() -> dict[str, str]:
    headers: dict[str, str] = {"x-agentrun-session-id": SESSION_ID}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


async def main():
    headers = build_headers()

    async with streamablehttp_client(ENDPOINT, headers=headers, timeout=60) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 列出可用工具
            tools = await session.list_tools()
            print(f"可用工具: {[t.name for t in tools.tools]}")

            # 调用工具（以 execute_code 为例，请根据实际工具替换名称和参数）
            result = await session.call_tool(
                "execute_code",
                {"language": "python", "code": "print('Hello from sandbox!')"},
            )

            text = result.content[0].text if result.content else ""
            status = "ERROR" if result.isError else "OK"
            print(f"[{status}]\n{text}")


asyncio.run(main())
```

---

## 关于 `x-agentrun-session-id`

`x-agentrun-session-id` 是平台特有的请求头，用于会话亲和与流量路由，与 MCP 协议自身的 session id（由服务端在响应中返回）是两个独立的概念。

- **沙箱工具（独占模式）**：必须携带。平台依据此值将请求路由到同一沙箱容器，保持进程状态在多次调用间持续存在
- **非沙箱工具（共享模式）**：非必须，但携带后有利于会话亲和与日志追踪

建议在客户端生成随机 UUID 并在整个会话期间复用。

---

## 完整 Demo

- [react-with-sandbox-by-native-mcp](https://github.com/cloudapp-suites/agentrun-demos/tree/main/react-with-sandbox-by-native-mcp) — ReActAgent 通过原生 MCP 协议连接远程沙箱
- [mcp-client-sample](https://github.com/cloudapp-suites/agentrun-demos/tree/main/mcp-client-sample) — MCP Python SDK 示例客户端
- [code-execution-mcp](https://github.com/cloudapp-suites/agentrun-demos/tree/main/code-execution-mcp) — 基于 MCP 协议的多语言代码执行 ToolServer
