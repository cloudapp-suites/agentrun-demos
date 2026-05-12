#!/usr/bin/env python3
"""
LangGraph + AgentScope 沙箱工具集成示例。

演示如何在 LangGraph ReAct Agent 中使用平台托管的沙箱工具（代码执行、文件操作）。
使用 register_custom_sandbox_type 注册自定义 ToolServer 名称映射。

Usage:
    export SANDBOX_MANAGER_URL=http://sandbox-manager.example.com
    export SANDBOX_MANAGER_TOKEN=your-token
    export SANDBOX_TYPE=my-base          # 平台上 ToolServer 的名称
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

# 过滤 LangGraph deprecation 警告，create_react_agent 仍是推荐用法
# langchain.agents.create_agent 尚未稳定
try:
    from langgraph.warnings import LangGraphDeprecatedSinceV10
    warnings.filterwarnings("ignore", category=LangGraphDeprecatedSinceV10)
except ImportError:
    pass

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
            version="v2",  # 使用 v2 版本，工具调用通过 Send API 并行分发
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
