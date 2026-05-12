# -*- coding: utf-8 -*-
"""
AgentScope MCP Demo 配置文件
============================

本文件是用户最主要的在线调试入口，支持以下修改：
  - SYS_PROMPT：调整助手的系统人设与行为风格（最简单的调试项）
  - MCP_SERVERS：增删远程 MCP 工具服务，每个服务包括 URL 与访问凭证

模型相关配置（API Key、模型名称、访问地址等）通过环境变量注入，
无需修改代码，详见 README.md 中的"环境变量参考"。
"""

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# 【在线调试演示】系统提示词 (SYS_PROMPT)
#
# 这是最简单的调试入口：修改此字符串即可改变助手的行为风格、回答范围、
# 语气等，保存后重启服务即可生效。例如：
#   - 改为中文专属助手：将第一行改为 "你是一个中文 AI 助手，..."
#   - 限制话题范围：添加 "只回答与代码相关的问题，拒绝其他话题。"
#   - 调整输出格式：添加 "所有回答请使用 Markdown 格式。"
# ---------------------------------------------------------------------------
SYS_PROMPT: str = (
    "你是一个智能 AI 助手，具备通过 MCP 工具调用远程服务的能力。\n"
    "请根据用户需求，合理选择并调用工具完成任务，并给出清晰的结果说明。\n"
    "如果没有合适的工具可用，请直接用已有知识回答用户问题。"
)


# ---------------------------------------------------------------------------
# MCP 服务配置
# ---------------------------------------------------------------------------

@dataclass
class MCPServerConfig:
    """单个远程 MCP 服务的配置。

    Attributes:
        name:        服务的唯一标识名称，用于日志和区分。
        url:         MCP 服务端点 URL，streamable-HTTP 协议端点默认路径为
                     ``/``，SSE 协议端点通常以 ``/sse`` 结尾。
        token:       访问凭证，以 ``Authorization: Bearer <token>`` 形式
                     附加到每次请求头中。留空则不添加鉴权头。
        transport:   传输协议，可选 ``streamable_http`` 或 ``sse``。
                     默认 ``streamable_http``。
        timeout:     单次请求超时（秒），默认 120。
        sse_read_timeout: SSE 读取超时（秒），默认 120。
        extra_headers: 额外的自定义请求头，字典形式。

    Note:
        每次请求会将 AgentRequest.session_id（即本次对话的会话 ID）作为
        ``x-agentrun-session-id`` 附加到请求头中，使 MCP 服务端能够将工具
        调用与发起请求的客户端会话绑定，便于按会话隔离上下文与追踪日志。
        如需覆盖此值（例如在线调试时将多个请求路由到同一个固定 session），
        可在 ``extra_headers`` 中显式指定 ``x-agentrun-session-id``。
    """

    name: str
    url: str
    token: str = ""
    transport: Literal["streamable_http", "sse"] = "streamable_http"
    timeout: float = 120.0
    sse_read_timeout: float = 120.0
    extra_headers: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 【用户配置区】在此列表中添加/删除/修改 MCP 服务
#
# 示例：
#   MCPServerConfig(
#       name="my-service",
#       url="https://my-service.example.com/",
#       token="sk-xxxxxx",
#   ),
#
# x-agentrun-session-id 说明：
#   每次请求时，程序将 AgentRequest.session_id（即本次对话的会话 ID）作为
#   x-agentrun-session-id 附加到对应 MCP 服务请求头中。
#   MCP 服务端可用此值将工具调用与客户端会话绑定，实现上下文隔离与日志追踪。
#   如需在调试时将多个请求路由到同一个固定 session（例如复现某次异常），
#   可在 extra_headers 中显式覆盖该值：
#     extra_headers={"x-agentrun-session-id": "your-fixed-session-id"}
# ---------------------------------------------------------------------------
MCP_SERVERS: list[MCPServerConfig] = [
    # MCPServerConfig(
    #     name="file",
    #     url="http://latest-file.default.${GATEWAY_DOMAIN}/",
    # ),
    # ---- 示例 1：基础配置 ----
    # MCPServerConfig(
    #     name="my-service",
    #     url="https://my-service.example.com/",
    #     token="your-token",
    # ),

    # ---- 示例 2：带额外自定义请求头 ----
    # MCPServerConfig(
    #     name="custom-service",
    #     url="https://custom.example.com/",
    #     token="your-token",
    #     extra_headers={
    #         "x-tenant-id": "team-001",
    #         # 固定 session-id（调试用）：
    #         # "x-agentrun-session-id": "debug-session-fixed-id",
    #     },
    # ),
]
