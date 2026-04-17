# LangGraph 集成 AgentScope 沙箱工具

本文档演示如何在 LangGraph ReAct Agent 中通过代码集成平台托管的沙箱工具（代码执行等）。

---

## 概述

平台托管的沙箱工具提供代码执行能力。在 LangGraph 中集成沙箱工具需要以下步骤：

1. **创建沙箱实例** — 通过 agentscope-runtime SDK 创建并启动沙箱
2. **将沙箱方法转换为 LangChain Tool** — 使用 `StructuredTool` 包装沙箱异步方法
3. **构建 ReAct Agent** — 使用 `create_react_agent` 将工具注入 LangGraph Agent

---

## 1. 安装依赖

```bash
pip install langgraph>=0.2.0 langchain>=0.3.0 langchain-openai>=0.2.0 agentscope-runtime
```

---

## 2. 创建沙箱实例

通常平台上创建的 ToolServer 使用自定义名称（如 `my-base`），与 agentscope-runtime 内置类型名称不一致，需要先注册映射：

```python
from agentscope_runtime.sandbox.box.base import BaseSandboxAsync
from agentscope_runtime.sandbox.enums import SandboxType
from agentscope_runtime.sandbox.registry import SandboxRegistry


def register_custom_sandbox_type(custom_name: str, sandbox_class: type):
    """将自定义 ToolServer 名称注册到 SandboxRegistry，映射到指定的沙箱类。"""
    existing_types = [t.value for t in SandboxType]
    if custom_name in existing_types:
        return
    SandboxType.add_member(custom_name.upper().replace("-", "_"), custom_name)
    custom_type = SandboxType(custom_name)
    SandboxRegistry._type_registry[custom_type] = sandbox_class


# 假设平台上 ToolServer 名称为 "my-base"
register_custom_sandbox_type("my-base", BaseSandboxAsync)

sandbox = BaseSandboxAsync(
    base_url="http://sandbox-manager.example.com",
    bearer_token="your-sandbox-manager-token",
    sandbox_type="my-base",
)
```

---

## 3. 将沙箱方法包装为 LangChain Tool

LangGraph 使用 LangChain 的 `BaseTool` 体系。需要将沙箱的异步方法包装为 `StructuredTool`，保留参数签名供 LLM 生成正确的 tool_call。

```python
import asyncio
import functools
from langchain_core.tools import StructuredTool


def wrap_sandbox_method(sandbox, method_name: str) -> StructuredTool:
    """将沙箱异步方法包装为 LangChain StructuredTool。"""
    method = getattr(sandbox, method_name)

    @functools.wraps(method)
    async def _arun(*args, **kwargs):
        result = await method(*args, **kwargs)
        if isinstance(result, dict):
            return str(result.get("content", result.get("stdout", result)))
        return str(result)

    @functools.wraps(method)
    def _run(*args, **kwargs):
        return asyncio.run(_arun(*args, **kwargs))

    return StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=method_name,
        description=method.__doc__ or f"sandbox tool: {method_name}",
    )


# BaseSandboxAsync 提供的工具方法
SANDBOX_TOOL_METHODS = [
    "run_ipython_cell",
    "run_shell_command",
]

tools = [
    wrap_sandbox_method(sandbox, name)
    for name in SANDBOX_TOOL_METHODS
    if hasattr(sandbox, name)
]
```

---

## 4. 构建 LangGraph ReAct Agent

使用 `create_react_agent` 快速构建一个带沙箱工具的 ReAct Agent。

> **注意**：`langgraph.prebuilt.create_react_agent` 在 LangGraph v1.0 中标记为 deprecated，建议使用 `version="v2"` 参数获得新的工具调用分发机制。可通过 `warnings.filterwarnings` 过滤警告。

```python
import warnings
from langgraph.warnings import LangGraphDeprecatedSinceV10
warnings.filterwarnings("ignore", category=LangGraphDeprecatedSinceV10)

from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="qwen3.5-plus",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    temperature=0,
)

graph = create_react_agent(
    model=llm,
    tools=tools,
    prompt=(
        "You are a helpful assistant with sandbox tools for code execution and file operations. "
        "Use run_ipython_cell for Python code, run_shell_command for shell commands "
    ),
    version="v2",  # 使用 v2 版本，工具调用通过 Send API 并行分发
)
```

### 运行对话

```python
import asyncio

async def chat(user_input: str):
    result = await graph.ainvoke(
        {"messages": [{"role": "user", "content": user_input}]}
    )
    # 取最后一条 AI 消息
    for msg in reversed(result["messages"]):
        if msg.type == "ai" and msg.content:
            print(msg.content)
            break

asyncio.run(chat("Use Python to generate two large random numbers and compute their sum."))
```

---

## 5. 完整示例

以下是一个完整的可运行示例：

```python
#!/usr/bin/env python3
"""
LangGraph + AgentScope 沙箱工具集成示例。

Usage:
    export SANDBOX_MANAGER_URL=http://sandbox-manager.example.com
    export SANDBOX_MANAGER_TOKEN=your-token
    export SANDBOX_TYPE=my-base
    export OPENAI_API_KEY=your-key
    export OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

    python langgraph_sandbox_agent.py
"""

import asyncio
import functools
import os
import warnings

from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

# 过滤 LangGraph deprecation 警告
from langgraph.warnings import LangGraphDeprecatedSinceV10
warnings.filterwarnings("ignore", category=LangGraphDeprecatedSinceV10)

from langgraph.prebuilt import create_react_agent

from agentscope_runtime.sandbox.box.base import BaseSandboxAsync
from agentscope_runtime.sandbox.enums import SandboxType
from agentscope_runtime.sandbox.registry import SandboxRegistry


# ---------------------------------------------------------------------------
# 自定义 ToolServer 名称注册
# ---------------------------------------------------------------------------

def register_custom_sandbox_type(custom_name: str, sandbox_class: type):
    """将自定义 ToolServer 名称注册到 SandboxRegistry，映射到指定的沙箱类。"""
    existing_types = [t.value for t in SandboxType]
    if custom_name in existing_types:
        return
    SandboxType.add_member(custom_name.upper().replace("-", "_"), custom_name)
    custom_type = SandboxType(custom_name)
    SandboxRegistry._type_registry[custom_type] = sandbox_class


# ---------------------------------------------------------------------------
# 沙箱工具包装
# ---------------------------------------------------------------------------

def wrap_sandbox_method(sandbox, method_name: str) -> StructuredTool:
    """将沙箱异步方法包装为 LangChain StructuredTool。"""
    method = getattr(sandbox, method_name)

    @functools.wraps(method)
    async def _arun(*args, **kwargs):
        result = await method(*args, **kwargs)
        if isinstance(result, dict):
            return str(result.get("content", result.get("stdout", result)))
        return str(result)

    @functools.wraps(method)
    def _run(*args, **kwargs):
        return asyncio.run(_arun(*args, **kwargs))

    return StructuredTool.from_function(
        func=_run,
        coroutine=_arun,
        name=method_name,
        description=method.__doc__ or f"sandbox tool: {method_name}",
    )


# BaseSandboxAsync 提供的工具方法
SANDBOX_TOOL_METHODS = [
    "run_ipython_cell",
    "run_shell_command",
]

PROMPT = (
    "Use Python to generate two large random numbers and compute their sum. "
    "Print the two numbers and the result."
)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def main():
    sandbox_type = os.environ.get("SANDBOX_TYPE", "my-base")
    register_custom_sandbox_type(sandbox_type, BaseSandboxAsync)

    sandbox = BaseSandboxAsync(
        base_url=os.environ.get("SANDBOX_MANAGER_URL", "http://localhost:8080"),
        bearer_token=os.environ.get("SANDBOX_MANAGER_TOKEN", ""),
        sandbox_type=sandbox_type,
    )
    await sandbox.start_async()
    print(f"沙箱已启动: {sandbox.sandbox_id}")

    try:
        tools = [
            wrap_sandbox_method(sandbox, name)
            for name in SANDBOX_TOOL_METHODS
            if hasattr(sandbox, name)
        ]
        print(f"已注册 {len(tools)} 个沙箱工具: {[t.name for t in tools]}")

        llm = ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL", "qwen3.5-plus"),
            base_url=os.environ.get("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            temperature=0,
        )
        graph = create_react_agent(
            model=llm,
            tools=tools,
            prompt=(
                "You are a helpful assistant with sandbox tools for code execution and file operations. "
                "Use run_ipython_cell for Python code, run_shell_command for shell commands "
            ),
            version="v2",
        )

        print(f"\n正在调用 Agent 执行: {PROMPT}\n")

        result = await graph.ainvoke(
            {"messages": [{"role": "user", "content": PROMPT}]}
        )
        for msg in reversed(result["messages"]):
            if msg.type == "ai" and msg.content:
                print(f"Agent 结果:\n{msg.content}")
                break

    finally:
        await sandbox.close_async()
        print("\n沙箱已释放")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 环境变量参考

| 变量 | 必填 | 说明 |
|------|------|------|
| `SANDBOX_MANAGER_URL` | 是 | 集群沙箱管理器地址（可从集群详情页获取） |
| `SANDBOX_MANAGER_TOKEN` | 否 | 集群沙箱管理器访问凭证（可从集群详情页获取） |
| `SANDBOX_TYPE` | 否 | ToolServer 名称，默认 `my-base` |
| `OPENAI_API_KEY` | 是 | OpenAI API Key（或 DashScope API Key） |
| `OPENAI_BASE_URL` | 否 | OpenAI 兼容 API 地址，如 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `OPENAI_MODEL` | 否 | 模型名称，默认 `qwen3.5-plus` |

---

## 完整 Demo

- [langgraph-sandbox-example](https://github.com/cloudapp-suites/agentrun-demos/tree/main/langgraph-sandbox-example) — LangGraph + 沙箱集成完整示例

## 打包部署

如需将应用打包为离线压缩包通过管控台上传部署，请参考 [pack-tools](https://github.com/cloudapp-suites/agentrun-demos/tree/main/pack-tools)。
