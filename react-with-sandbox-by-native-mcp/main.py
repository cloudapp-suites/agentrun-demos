# -*- coding: utf-8 -*-
"""
ReActAgent + 远程 MCP Server（streamable-HTTP）Demo
====================================================

使用 AgentScope 的 ReActAgent 通过 streamable-HTTP 协议连接远程沙箱，
自动发现并注册沙箱暴露的所有 MCP 工具，然后执行单次任务或进入交互模式。

用法：
    # 交互模式（默认 openai provider + qwen3.5-flash，走 DashScope 兼容接口）
    python main.py \\
        --url http://<sandbox-host>/

    # 单次任务，显式指定 token 和模型
    python main.py \\
        --url http://<sandbox-host>/ \\
        --token <auth-token> \\
        --model qwen3.5-flash \\
        --task "列出 /workspace 目录"

    # 使用 DashScope 原生 SDK
    python main.py \\
        --url http://<sandbox-host>/ \\
        --provider dashscope \\
        --model qwen-max

环境变量：
    OPENAI_API_KEY      provider=openai 时必填
    OPENAI_API_BASE     OpenAI 兼容接口基础 URL
                        默认: https://dashscope.aliyuncs.com/compatible-mode/v1
    DASHSCOPE_API_KEY   provider=dashscope 时必填
"""

import argparse
import asyncio
import os
import signal
import sys
import uuid
from typing import Literal

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from agentscope.agent import ReActAgent
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg
from agentscope.mcp import HttpStatefulClient
from agentscope.tool import Toolkit

# ---------------------------------------------------------------------------
# 默认值（均可通过命令行参数覆盖）
# ---------------------------------------------------------------------------
DEFAULT_URL = ""
DEFAULT_TOKEN = ""
DEFAULT_MODEL = "qwen-plus"
DEFAULT_PROVIDER = "openai"

# 统一超时（秒）
REQUEST_TIMEOUT = 120
SSE_READ_TIMEOUT = 120

Provider = Literal["openai", "dashscope"]


def _build_headers(token: str) -> dict[str, str]:
    """生成请求头，每次调用产生新的 session-id 保证会话隔离。"""
    return {
        "x-agentrun-session-id": str(uuid.uuid4()),
        "Authorization": f"Bearer {token}",
    }


def _build_model(provider: Provider, model_name: str):
    """根据 provider 参数构建对应的 ChatModelBase 实现。

    openai    使用 OpenAIChatModel，同时支持设置 OPENAI_API_BASE
              指向任何 OpenAI 兼容接口（如 DashScope、Moonshot、DeepSeek 等）。
    dashscope 使用 DashScopeChatModel（原生 SDK）。
    """
    if provider == "openai":
        from agentscope.model import OpenAIChatModel
        from agentscope.formatter import OpenAIChatFormatter

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise EnvironmentError("请先设置环境变量 OPENAI_API_KEY")

        kwargs = dict(api_key=api_key, model_name=model_name, stream=True)
        api_base = os.environ.get(
            "OPENAI_API_BASE",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        if api_base:
            kwargs["client_args"] = {"base_url": api_base}
        return OpenAIChatModel(**kwargs), OpenAIChatFormatter()

    elif provider == "dashscope":
        from agentscope.model import DashScopeChatModel
        from agentscope.formatter import DashScopeChatFormatter

        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            raise EnvironmentError("请先设置环境变量 DASHSCOPE_API_KEY")

        base_url = os.environ.get("DASHSCOPE_API_BASE")
        kwargs = dict(
            api_key=api_key,
            model_name=model_name,
            stream=True,
        )
        if base_url:
            kwargs["base_http_api_url"] = base_url
        return (
            DashScopeChatModel(**kwargs),
            DashScopeChatFormatter(),
        )

    else:
        raise ValueError(f"未知 provider: {provider!r}，可选值: openai / dashscope")


async def run(
    url: str,
    token: str,
    provider: Provider,
    model_name: str,
    task: str | None,
) -> None:
    """主流程：连接 MCP Server → 注册工具 → 启动 ReActAgent → 交互。"""

    # -----------------------------------------------------------------------
    # 1. 连接远程 MCP Server
    # -----------------------------------------------------------------------
    headers = _build_headers(token)
    print(f"[session-id]  {headers['x-agentrun-session-id']}")
    print(f"[MCP server]  {url}")
    print(f"[provider]    {provider}")
    print(f"[model]       {model_name}\n")

    mcp_client = HttpStatefulClient(
        name="remote-sandbox",
        transport="streamable_http",
        url=url,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
        sse_read_timeout=SSE_READ_TIMEOUT,
    )

    toolkit = Toolkit()

    try:
        await mcp_client.connect()
        print("[MCP] 连接成功")

        # -------------------------------------------------------------------
        # 2. 列出并注册全部工具
        # -------------------------------------------------------------------
        tools = await mcp_client.list_tools()
        print(f"[MCP] 可用工具 ({len(tools)} 个):")
        for t in tools:
            desc = (t.description or "").splitlines()[0][:72]
            print(f"  • {t.name:<30} {desc}")
        print()

        await toolkit.register_mcp_client(mcp_client)

        # -------------------------------------------------------------------
        # 3. 构建模型与 ReActAgent
        # -------------------------------------------------------------------
        model, formatter = _build_model(provider, model_name)

        agent = ReActAgent(
            name="SandboxAgent",
            sys_prompt=(
                "你是一个智能助手，可以通过工具访问远程沙箱环境。\n"
                "沙箱提供文件系统操作、Python 代码执行（IPython）、"
                "Shell 命令执行、浏览器控制等能力。\n"
                "请根据用户需求，合理选择工具完成任务，并给出清晰的结果说明。"
            ),
            model=model,
            formatter=formatter,
            memory=InMemoryMemory(),
            toolkit=toolkit,
            max_iters=15,
            parallel_tool_calls=False,
        )

        # -------------------------------------------------------------------
        # 4. 单次任务 or 交互循环
        # -------------------------------------------------------------------
        # ANSI 颜色
        USER_COLOR  = "\033[32m"   # 绿色：用户输入提示
        AGENT_COLOR = "\033[36m"   # 青色：Agent 回复
        RESET       = "\033[0m"

        if task:
            print(f"{USER_COLOR}用户> {RESET}{task}\n")
            reply = await agent(Msg(name="user", role="user", content=task))
            print(f"{AGENT_COLOR}Agent> {RESET}{reply.get_text_content()}")
        else:
            # prompt_toolkit：正确处理中文 IME 输入和宽字符光标定位
            style = Style.from_dict({"prompt": "#00AA00"})
            prompt_session = PromptSession(style=style)

            def _on_sigint(signum, frame):
                print(f"\n{RESET}退出。")
                sys.exit(0)

            signal.signal(signal.SIGINT, _on_sigint)

            print("进入交互模式（输入 exit / quit 退出）\n")
            while True:
                try:
                    with patch_stdout():
                        user_input = (
                            await prompt_session.prompt_async(
                                message=[("class:prompt", "用户> ")]
                            )
                        ).strip()
                except (EOFError, KeyboardInterrupt):
                    print(f"\n{RESET}退出。")
                    break
                if not user_input or user_input.lower() in ("exit", "quit"):
                    print(f"{RESET}退出。")
                    break
                print(f"{AGENT_COLOR}Agent> {RESET}", end="", flush=True)
                reply = await agent(
                    Msg(name="user", role="user", content=user_input)
                )
                print(f"\n{AGENT_COLOR}{reply.get_text_content()}{RESET}\n")

    finally:
        if mcp_client.is_connected:
            await mcp_client.close()
            print("\n[MCP] 连接已关闭")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ReActAgent + 远程沙箱 MCP Server（streamable-HTTP）Demo",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--url",
        required=True,
        help="远程 MCP Server 地址（streamable-HTTP 端点），必填",
    )
    p.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help="鉴权 token（写入 Authorization: Bearer <token>）",
    )
    p.add_argument(
        "--provider",
        default=DEFAULT_PROVIDER,
        choices=["openai", "dashscope"],
        help=(
            "模型 provider。"
            "openai: 使用 OpenAIChatModel，支持 OPENAI_API_BASE 指向兼容接口；"
            "dashscope: 使用 DashScopeChatModel 原生 SDK"
        ),
    )
    p.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        dest="model_name",
        help="模型名称，与 --provider 搭配使用",
    )
    p.add_argument(
        "--task",
        default=None,
        help="指定单次任务（不填则进入交互模式）",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(
        run(
            url=args.url,
            token=args.token,
            provider=args.provider,
            model_name=args.model_name,
            task=args.task,
        )
    )
