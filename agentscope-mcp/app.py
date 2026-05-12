# -*- coding: utf-8 -*-
"""
AgentScope MCP Demo — Web 服务入口
====================================

基于 agentscope-runtime 的 AgentApp，提供标准 AgentScope Runtime 协议的
HTTP 服务接口（SSE 流式响应），自动连接所有在 config.py 中配置的远程 MCP
服务并注册工具，支持多会话并发与内存会话隔离。

启动命令：
    python app.py                        # 默认读取 HOST/PORT 环境变量
    python app.py --port 9090            # 覆盖端口（优先于 PORT 环境变量）
    python app.py --host 127.0.0.1

环境变量（完整列表见 README.md）：
    # 服务地址
    HOST                服务监听地址，默认 0.0.0.0
    PORT                服务监听端口，默认 8080

    # 模型 provider（二选一）
    MODEL_PROVIDER      openai | dashscope，默认 openai

    # OpenAI 兼容接口（MODEL_PROVIDER=openai 时使用）
    OPENAI_API_KEY      必填
    OPENAI_API_BASE     模型访问地址，默认 https://dashscope.aliyuncs.com/compatible-mode/v1
    OPENAI_MODEL_NAME   模型名称，默认 qwen-plus

    # DashScope 原生 SDK（MODEL_PROVIDER=dashscope 时使用）
    DASHSCOPE_API_KEY   必填
    DASHSCOPE_API_BASE  模型访问地址（可选）
    DASHSCOPE_MODEL_NAME 模型名称，默认 qwen-plus

    # Agent 行为
    MAX_ITERS           最大推理-行动循环次数，默认 15
    PARALLEL_TOOL_CALLS 并行工具调用，true/false，默认 false
    LOG_LEVEL           日志级别，DEBUG/INFO/WARNING/ERROR，默认 INFO

接口说明：
    POST /process     主对话接口（SSE 流式返回）
    GET  /health      健康检查
    GET  /            服务信息
    协议详见 https://runtime.agentscope.io/en/protocol.html
"""

import argparse
import logging
import os
import uuid

from fastapi.responses import StreamingResponse

from agentscope.agent import ReActAgent
from agentscope.memory import InMemoryMemory
from agentscope.mcp import HttpStatefulClient
from agentscope.pipeline import stream_printing_messages
from agentscope.tool import Toolkit

from agentscope_runtime.engine import AgentApp
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest

# 导入用户配置（仅 SYS_PROMPT 和 MCP_SERVERS）
from config import SYS_PROMPT, MCP_SERVERS, MCPServerConfig


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 从环境变量读取模型与 Agent 配置
# ---------------------------------------------------------------------------
def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _build_model():
    """根据环境变量构建 ChatModelBase 与 Formatter。

    优先读取 MODEL_PROVIDER 决定使用哪套 provider：
      - openai：读取 OPENAI_API_KEY / OPENAI_API_BASE / OPENAI_MODEL_NAME
      - dashscope：读取 DASHSCOPE_API_KEY / DASHSCOPE_API_BASE / DASHSCOPE_MODEL_NAME

    Returns:
        (model, formatter) 元组。

    Raises:
        EnvironmentError: 必填的 API Key 未设置时抛出。
    """
    provider = _get_env("MODEL_PROVIDER", "openai").lower()

    if provider == "openai":
        from agentscope.model import OpenAIChatModel
        from agentscope.formatter import OpenAIChatFormatter

        api_key = _get_env("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "MODEL_PROVIDER=openai 时必须设置环境变量 OPENAI_API_KEY"
            )
        model_name = _get_env("OPENAI_MODEL_NAME", "qwen-plus")
        api_base = _get_env(
            "OPENAI_API_BASE",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        stream = _get_env("MODEL_STREAM", "true").lower() != "false"

        kwargs: dict = dict(api_key=api_key, model_name=model_name, stream=stream)
        if api_base:
            kwargs["client_args"] = {"base_url": api_base}

        logger.info(
            "模型配置 provider=openai model=%s api_base=%s", model_name, api_base
        )
        return OpenAIChatModel(**kwargs), OpenAIChatFormatter()

    elif provider == "dashscope":
        from agentscope.model import DashScopeChatModel
        from agentscope.formatter import DashScopeChatFormatter

        api_key = _get_env("DASHSCOPE_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "MODEL_PROVIDER=dashscope 时必须设置环境变量 DASHSCOPE_API_KEY"
            )
        model_name = _get_env("DASHSCOPE_MODEL_NAME", "qwen-plus")
        api_base = _get_env("DASHSCOPE_API_BASE")
        stream = _get_env("MODEL_STREAM", "true").lower() != "false"

        kwargs = dict(api_key=api_key, model_name=model_name, stream=stream)
        if api_base:
            kwargs["base_http_api_url"] = api_base

        logger.info(
            "模型配置 provider=dashscope model=%s", model_name
        )
        return DashScopeChatModel(**kwargs), DashScopeChatFormatter()

    else:
        raise ValueError(
            f"不支持的 MODEL_PROVIDER={provider!r}，可选值: openai / dashscope"
        )


def _get_max_iters() -> int:
    try:
        return int(_get_env("MAX_ITERS", "15"))
    except ValueError:
        logger.warning("MAX_ITERS 不是有效整数，使用默认值 15")
        return 15


def _get_parallel_tool_calls() -> bool:
    return _get_env("PARALLEL_TOOL_CALLS", "false").lower() == "true"


# ---------------------------------------------------------------------------
# AgentApp 实例
# ---------------------------------------------------------------------------
agent_app = AgentApp(
    app_name="AgentScope MCP Assistant",
    app_description=(
        "支持多远程 MCP 工具调用的 AI 助手，"
        "基于 AgentScope ReActAgent + agentscope-runtime。"
    ),
)


# ---------------------------------------------------------------------------
# 工具函数：生成 MCP 请求头
# ---------------------------------------------------------------------------

def _build_headers(server_cfg: MCPServerConfig, session_id: str) -> dict[str, str]:
    """为指定 MCP 服务生成请求头。

    使用请求关联的 session_id 作为 x-agentrun-session-id，使 MCP 服务端
    能够将工具调用与发起请求的会话绑定，便于按会话隔离上下文与追踪日志。
    若 extra_headers 中已显式指定 x-agentrun-session-id，则以用户指定值为准。

    Args:
        server_cfg: MCP 服务配置对象。
        session_id: 当前请求的会话 ID（来自 AgentRequest.session_id）。
    """
    headers: dict[str, str] = {"x-agentrun-session-id": session_id}
    if server_cfg.token:
        headers["Authorization"] = f"Bearer {server_cfg.token}"
    headers.update(server_cfg.extra_headers)
    return headers


# ---------------------------------------------------------------------------
# AgentApp 生命周期钩子
# ---------------------------------------------------------------------------

@agent_app.init
async def init_func(self):
    """应用启动：初始化内存会话存储，打印配置摘要。"""
    self.sessions: dict[str, InMemoryMemory] = {}
    logger.info(
        "AgentScope MCP Assistant 启动完成  "
        "provider=%s  max_iters=%d  parallel_tool_calls=%s  mcp_servers=%d",
        _get_env("MODEL_PROVIDER", "openai"),
        _get_max_iters(),
        _get_parallel_tool_calls(),
        len(MCP_SERVERS),
    )
    if not MCP_SERVERS:
        logger.warning(
            "config.py 中 MCP_SERVERS 为空，助手将不具备工具调用能力，仅支持纯对话。"
        )


@agent_app.shutdown
async def shutdown_func(self):
    """应用关闭：清理内存会话存储。"""
    self.sessions.clear()
    logger.info("AgentScope MCP Assistant 已关闭。")


# ---------------------------------------------------------------------------
# 核心查询处理函数
# ---------------------------------------------------------------------------

@agent_app.query(framework="agentscope")
async def query_func(    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """处理每次用户请求：连接 MCP 服务 → 构建 Agent → 流式响应 → 断开连接。

    Args:
        self:    Runner 实例，通过 self.sessions 访问会话存储。
        msgs:    已转换为 AgentScope Msg 格式的输入消息列表。
        request: AgentScope Runtime 标准请求对象（含 session_id、user_id 等）。
        **kwargs: 框架传入的额外参数。

    Yields:
        (Msg, bool)：消息对象及是否为最后一个流式分片的标志。
    """
    session_id = request.session_id if request else str(uuid.uuid4())

    # -----------------------------------------------------------------------
    # 1. 逐个连接 MCP 服务（串行，避免 anyio 上下文并发嵌套问题）
    # -----------------------------------------------------------------------
    mcp_clients: list[HttpStatefulClient] = []
    toolkit = Toolkit()

    try:
        for server_cfg in MCP_SERVERS:
            headers = _build_headers(server_cfg, session_id)
            logger.info(
                "连接 MCP 服务 [%s]  url=%s  session-id=%s",
                server_cfg.name,
                server_cfg.url,
                headers.get("x-agentrun-session-id", "-"),
            )
            client = HttpStatefulClient(
                name=server_cfg.name,
                transport=server_cfg.transport,
                url=server_cfg.url,
                headers=headers,
                timeout=server_cfg.timeout,
                sse_read_timeout=server_cfg.sse_read_timeout,
            )
            await client.connect()
            await toolkit.register_mcp_client(client)
            mcp_clients.append(client)
            logger.info("MCP 服务 [%s] 连接成功，工具已注册", server_cfg.name)

        # -------------------------------------------------------------------
        # 2. 获取或创建本会话的内存（同一 session_id 共享多轮对话历史）
        # -------------------------------------------------------------------
        if session_id not in self.sessions:
            self.sessions[session_id] = InMemoryMemory()
            logger.debug("新建会话内存 session_id=%s", session_id)
        memory = self.sessions[session_id]

        # -------------------------------------------------------------------
        # 3. 从环境变量构建模型，创建 ReActAgent
        # -------------------------------------------------------------------
        model, formatter = _build_model()

        agent = ReActAgent(
            name="MCPAssistant",
            sys_prompt=SYS_PROMPT,
            model=model,
            formatter=formatter,
            memory=memory,
            toolkit=toolkit,
            max_iters=_get_max_iters(),
            parallel_tool_calls=_get_parallel_tool_calls(),
        )
        agent.set_console_output_enabled(False)

        # -------------------------------------------------------------------
        # 4. 流式执行，yield (msg, last)
        # -------------------------------------------------------------------
        async for msg, last in stream_printing_messages(
            agents=[agent],
            coroutine_task=agent(msgs),
        ):
            yield msg, last

    finally:
        # 按 LIFO 顺序关闭，避免 anyio 上下文嵌套异常
        for client in reversed(mcp_clients):
            if client.is_connected:
                try:
                    await client.close()
                    logger.info("MCP 服务 [%s] 连接已关闭", client.name)
                except Exception as exc:
                    logger.warning("关闭 MCP 服务 [%s] 时出错：%s", client.name, exc)


# ---------------------------------------------------------------------------
# 兼容路由：平台调用 POST / 时转发到与 /process 相同的处理逻辑
# ---------------------------------------------------------------------------

@agent_app.post("/", tags=["agent-api"], include_in_schema=False)
async def root_query_handler(request: dict):
    """将 POST / 请求转发到与 POST /process 相同的流式处理逻辑。"""
    return StreamingResponse(
        agent_app._stream_generator(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="AgentScope MCP Demo Web 服务",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--host",
        default=os.getenv("HOST", "0.0.0.0"),
        help="服务监听地址（也可通过 HOST 环境变量设置）",
    )
    p.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8080")),
        help="服务监听端口（也可通过 PORT 环境变量设置）",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    agent_app.run(host=args.host, port=args.port)
