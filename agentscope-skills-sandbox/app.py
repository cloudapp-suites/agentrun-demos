# -*- coding: utf-8 -*-
"""
AgentScope Skills Sandbox Demo — Web 服务入口
==============================================

基于 agentscope-runtime 的 AgentApp，展示 AgentScope ReActAgent 配合
Agent Skills 与 All-in-One 沙箱的集成能力。

每个 session 的首次请求：
  1. 通过 SandboxService.connect(session_id) 获取沙箱实例（多副本场景下复用同一沙箱）
  2. 通过沙箱 fs API 将 skills 上传到沙箱 /workspace/skills/
  3. 用 async_sandbox_tool_adapter 包装沙箱所有工具方法，注册到 Toolkit
  4. 注册 skills（dir 指向沙箱内路径）
  5. 缓存 sandbox + toolkit + memory 到 self.sessions

后续同 session 的请求：
  - 复用缓存的 sandbox + toolkit + memory
  - 通过 sandbox.fs.exists_async() 检查 /workspace/skills 是否存在，
    若不存在（如沙箱重启）则重新上传

请求结束：
  - 不关闭沙箱（per-session 复用）
  - 应用关闭时通过 SandboxService.stop() 统一释放

启动命令：
    python app.py
    python app.py --port 9090

环境变量（完整列表见 README.md）：
    SANDBOX_MANAGER_URL   沙箱管理器地址（必填）
    SANDBOX_MANAGER_TOKEN 访问凭证（必填）
    HOST / PORT           服务监听地址/端口
    MODEL_PROVIDER        openai | dashscope
    OPENAI_API_KEY / DASHSCOPE_API_KEY
    MAX_ITERS / PARALLEL_TOOL_CALLS / LOG_LEVEL
"""

import asyncio
import argparse
import base64
import contextvars
import hashlib
import hmac
import inspect
import json
import logging
import mimetypes
import os
import secrets
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import frontmatter

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse

from agentscope.agent import ReActAgent
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg, TextBlock
from agentscope.pipeline import stream_printing_messages
from agentscope.tool import Toolkit, ToolResponse
from agentscope.tool._types import AgentSkill

from agentscope_runtime.engine import AgentApp
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope_runtime.engine.services.sandbox.sandbox_service import SandboxService
from agentscope_runtime.sandbox.registry import SandboxRegistry

from all_in_one_sandbox_async import AllInOneSandboxAsync, register_template_name
from async_sandbox_adapter import async_sandbox_tool_adapter
from config import (
    SYS_PROMPT, SKILLS_DIR, SANDBOX_SKILLS_DIR, DISABLED_SKILLS,
    SANDBOX_TEMPLATE_NAME,
)


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 入站请求 base URL（scheme + host），由中间件在每次请求时写入 contextvar，
# 供 generate_download_url 生成下载链接时使用。
# ---------------------------------------------------------------------------
_inbound_host_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "inbound_host", default=None,
)


# ---------------------------------------------------------------------------
# 文件下载：generate_download_url 工具（per-session 闭包）
# ---------------------------------------------------------------------------

def _make_generate_download_url(session_id: str) -> Callable:
    """返回一个绑定了 session_id 的 generate_download_url 工具函数。

    Agent 调用此工具时只需传入沙箱内文件路径，函数内部自动签名并拼接 URL。
    endpoint 在每次调用时从 contextvar 动态解析，适配反向代理 / 多域名场景。
    """
    def generate_download_url(path: str) -> ToolResponse:
        """为沙箱内的文件生成签名下载链接，有效期 7 天。

        适用于沙箱中用户可能需要访问的文件。

        Args:
            path: 沙箱内文件的绝对路径，例如 /workspace/output/report.pdf

        Returns:
            可直接访问的签名下载 URL。
        """
        endpoint = _get_endpoint()
        token = _create_download_token(session_id)
        from urllib.parse import quote
        url = f"{endpoint}/download?token={token}&path={quote(path, safe='/')}"
        return ToolResponse(content=[TextBlock(type="text", text=url)])

    return generate_download_url


# ---------------------------------------------------------------------------
# 模块级 session 注册表（/download 路由直接访问，无需经过 AgentApp runner）
# ---------------------------------------------------------------------------

_sessions: dict[str, "SessionState"] = {}

@dataclass
class SessionState:
    """单个会话的完整状态，跨请求持久保留。"""
    sandbox: AllInOneSandboxAsync
    toolkit: Toolkit
    memory: InMemoryMemory = field(default_factory=InMemoryMemory)


# ---------------------------------------------------------------------------
# 环境变量读取
# ---------------------------------------------------------------------------

def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


# ---------------------------------------------------------------------------
# 服务入口地址
# ---------------------------------------------------------------------------

def _get_endpoint() -> str:
    """返回本服务对外暴露的根 URL，按以下优先级解析：

    1. 入站请求的 base_url（由中间件写入 contextvar，适配反向代理）
    2. ENDPOINT 环境变量（显式配置）
    3. HOST / PORT 拼接（本地开发兜底）
    """
    # 优先：当前请求的入站 host（反向代理场景下最准确）
    inbound = _inbound_host_var.get()
    if inbound:
        return inbound.rstrip("/")

    # 其次：显式配置的 ENDPOINT 环境变量
    ep = _get_env("ENDPOINT")
    if ep:
        return ep.rstrip("/")

    # 兜底：从 HOST / PORT 拼接
    host = _get_env("HOST", "0.0.0.0")
    if host in ("0.0.0.0", ""):
        host = "localhost"
    port = _get_env("PORT", "8080")
    return f"http://{host}:{port}"


# ---------------------------------------------------------------------------
# 文件下载：签名 token 工具
# ---------------------------------------------------------------------------

_download_secret: str | None = None  # lazy init


def _get_download_secret() -> str:
    """返回 HMAC 签名密钥，优先从环境变量 DOWNLOAD_SECRET 读取。

    若未设置则随机生成（重启后失效），并打印告警。
    """
    global _download_secret
    if _download_secret is None:
        s = _get_env("DOWNLOAD_SECRET")
        if not s:
            s = secrets.token_hex(32)
            logger.warning(
                "DOWNLOAD_SECRET 未设置，已随机生成临时密钥（重启后失效）。"
                "建议通过环境变量 DOWNLOAD_SECRET 设置持久密钥。"
            )
        _download_secret = s
    return _download_secret


def _create_download_token(session_id: str, ttl_days: int = 7) -> str:
    """生成 HMAC-SHA256 签名的下载 token，格式：base64url(payload).signature。

    payload 包含 session_id 和过期时间戳（ttl_days 天后）。
    """
    payload = json.dumps(
        {"sid": session_id, "exp": int(time.time()) + ttl_days * 86400},
        separators=(",", ":"),
    )
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(
        _get_download_secret().encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_b64}.{sig}"


def _verify_download_token(token: str) -> str | None:
    """验证下载 token，成功返回 session_id，否则返回 None。"""
    try:
        payload_b64, sig = token.rsplit(".", 1)
        expected = hmac.new(
            _get_download_secret().encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("下载 token 签名不匹配  expected=%s  actual=%s", expected, sig)
            return None
        # 补齐 base64 padding
        pad = 4 - len(payload_b64) % 4
        if pad != 4:
            payload_b64 += "=" * pad
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        if payload["exp"] < time.time():
            logger.warning("下载 token 已过期  exp=%s  now=%s", payload["exp"], time.time())
            return None
        return payload["sid"]
    except Exception as exc:
        logger.warning("下载 token 解析失败  token=%s  error=%s", token[:50], exc)
        return None


def _build_model():
    """根据 MODEL_PROVIDER 环境变量构建模型与 Formatter。"""
    provider = _get_env("MODEL_PROVIDER", "openai").lower()

    if provider == "openai":
        from agentscope.model import OpenAIChatModel
        from agentscope.formatter import OpenAIChatFormatter

        api_key = _get_env("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("MODEL_PROVIDER=openai 时必须设置 OPENAI_API_KEY")
        model_name = _get_env("OPENAI_MODEL_NAME", "qwen3.5-plus")
        api_base = _get_env(
            "OPENAI_API_BASE",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        stream = _get_env("MODEL_STREAM", "true").lower() != "false"
        kwargs: dict = dict(api_key=api_key, model_name=model_name, stream=stream)
        if api_base:
            kwargs["client_args"] = {"base_url": api_base}
        logger.debug("模型配置 provider=openai model=%s api_base=%s", model_name, api_base)
        return OpenAIChatModel(**kwargs), OpenAIChatFormatter()

    elif provider == "dashscope":
        from agentscope.model import DashScopeChatModel
        from agentscope.formatter import DashScopeChatFormatter

        api_key = _get_env("DASHSCOPE_API_KEY")
        if not api_key:
            raise EnvironmentError("MODEL_PROVIDER=dashscope 时必须设置 DASHSCOPE_API_KEY")
        model_name = _get_env("DASHSCOPE_MODEL_NAME", "qwen3.5-plus")
        api_base = _get_env("DASHSCOPE_API_BASE")
        stream = _get_env("MODEL_STREAM", "true").lower() != "false"
        kwargs = dict(api_key=api_key, model_name=model_name, stream=stream)
        if api_base:
            kwargs["base_http_api_url"] = api_base
        logger.debug("模型配置 provider=dashscope model=%s", model_name)
        return DashScopeChatModel(**kwargs), DashScopeChatFormatter()

    else:
        raise ValueError(f"不支持的 MODEL_PROVIDER={provider!r}，可选值: openai / dashscope")


def _get_max_iters() -> int:
    try:
        return int(_get_env("MAX_ITERS", "1000"))
    except ValueError:
        return 1000


def _get_parallel_tool_calls() -> bool:
    return _get_env("PARALLEL_TOOL_CALLS", "false").lower() == "true"


# ---------------------------------------------------------------------------
# 模型代理：捕获每次 API 调用的 token 用量
# ---------------------------------------------------------------------------

class _UsageCapturingModel:
    """对 ChatModelBase 的透明代理，捕获每次调用返回的 ChatResponse.usage。

    通过 __getattr__ 将所有属性/方法访问透明转发给被代理的模型，仅拦截
    __call__ 以在非流式/流式两种场景下均能读到 ChatUsage。

    Attributes:
        last_usage:          最近一次调用的 ChatUsage（含 input/output tokens）
        total_input_tokens:  本 session 累计输入 token 数
        total_output_tokens: 本 session 累计输出 token 数
    """

    def __init__(self, model) -> None:
        self._model = model
        self.last_usage = None
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def __getattr__(self, name: str):
        return getattr(self._model, name)

    def _capture(self, usage) -> None:
        if usage is None:
            return
        self.last_usage = usage
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens

    async def __call__(self, *args, **kwargs):
        result = await self._model(*args, **kwargs)

        if self._model.stream:
            # 流式：把 AsyncGenerator 包一层，从最后一个 chunk 读 usage
            proxy = self

            async def _capturing_stream():
                last_chunk = None
                async for chunk in result:
                    last_chunk = chunk
                    yield chunk
                proxy._capture(getattr(last_chunk, "usage", None))

            return _capturing_stream()
        else:
            # 非流式：ChatResponse 直接带 usage
            self._capture(getattr(result, "usage", None))
            return result


# ---------------------------------------------------------------------------
# ReActAgent Hook：记录 Reasoning 与 Tool 执行日志
# ---------------------------------------------------------------------------

def _post_reasoning_hook(agent, kwargs: dict, output) -> None:
    """post_reasoning hook：记录模型的推理文本与计划调用的工具，附打 token 用量。

    Args:
        agent:  ReActAgent 实例
        kwargs: _reasoning 的入参 {"tool_choice": ...}
        output: _reasoning 返回的 Msg，含 text / tool_use 内容块
    """
    if output is None:
        return None

    # ── token 用量（由 _UsageCapturingModel 代理注入）──
    usage = getattr(agent.model, "last_usage", None)
    if usage:
        total_in  = getattr(agent.model, "total_input_tokens",  0)
        total_out = getattr(agent.model, "total_output_tokens", 0)
        logger.info(
            "[Reason] tokens  本次=%din/%dout  累计=%din/%dout",
            usage.input_tokens, usage.output_tokens, total_in, total_out,
        )

    # ── 推理文本（thought）──
    text_blocks = output.get_content_blocks("text")
    if text_blocks:
        text = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in text_blocks
        ).strip()
        if text:
            logger.info("[Reason] %s", text[:600])

    # ── 计划调用的工具（tool_use）──
    for block in output.get_content_blocks("tool_use"):
        name = block.get("name", "?")
        inp = block.get("input", {}) if isinstance(block, dict) else getattr(block, "input", {})
        inp_str = str(inp)[:50]
        logger.info("[Tool Call] %s  args=%s", name, inp_str)

    return None


def _post_acting_hook(agent, kwargs: dict, output) -> None:
    """post_acting hook：记录工具执行完成，附打累计 token 用量。"""
    tool_call = kwargs.get("tool_call", {})
    name = (
        tool_call.get("name", "?")
        if isinstance(tool_call, dict)
        else getattr(tool_call, "name", "?")
    )
    total_in  = getattr(agent.model, "total_input_tokens",  0)
    total_out = getattr(agent.model, "total_output_tokens", 0)
    token_str = f"  累计tokens={total_in}in/{total_out}out" if total_in else ""
    if output is not None:
        logger.info("[Tool Done] %s  output=%s%s", name, str(output)[:200], token_str)
    else:
        logger.info("[Tool Done] %s%s", name, token_str)
    return None


# 注册为类级别 hook，对所有 ReActAgent 实例生效
ReActAgent.register_class_hook("post_reasoning", "log_reasoning", _post_reasoning_hook)
ReActAgent.register_class_hook("post_acting",   "log_acting",    _post_acting_hook)

# ---------------------------------------------------------------------------
# 沙箱工具注册
# ---------------------------------------------------------------------------

# AllInOneSandboxAsync 中需要注册到 Toolkit 的异步方法名列表
_SANDBOX_TOOL_METHODS = [
    # 代码执行
    "run_ipython_cell",
    "run_shell_command",
    # 文件系统
    "read_file",
    "read_multiple_files",
    "write_file",
    "edit_file",
    "create_directory",
    "list_directory",
    "directory_tree",
    "move_file",
    "search_files",
    "get_file_info",
    "list_allowed_directories",
    # GUI
    "computer_use",
    # 浏览器
    "browser_close",
    "browser_resize",
    "browser_console_messages",
    "browser_handle_dialog",
    "browser_file_upload",
    "browser_press_key",
    "browser_navigate",
    "browser_navigate_back",
    "browser_navigate_forward",
    "browser_network_requests",
    "browser_pdf_save",
    "browser_take_screenshot",
    "browser_snapshot",
    "browser_click",
    "browser_drag",
    "browser_hover",
    "browser_type",
    "browser_select_option",
    "browser_tab_list",
    "browser_tab_new",
    "browser_tab_select",
    "browser_tab_close",
    "browser_wait_for",
]


def _register_sandbox_tools(toolkit: Toolkit, sandbox: AllInOneSandboxAsync) -> int:
    """将沙箱的所有工具方法包装后注册到 Toolkit。

    通过 async_sandbox_tool_adapter 将沙箱绑定方法转换为返回 ToolResponse
    的 async 函数，再通过 toolkit.register_tool_function() 注册。
    functools.wraps 保留原方法签名与 docstring，Toolkit 据此生成 JSON Schema。

    Args:
        toolkit: 目标 Toolkit 实例
        sandbox: 已启动的 AllInOneSandboxAsync 实例

    Returns:
        实际注册的工具数量
    """
    count = 0
    for method_name in _SANDBOX_TOOL_METHODS:
        method = getattr(sandbox, method_name, None)
        if method is None or not inspect.iscoroutinefunction(method):
            logger.warning("沙箱方法 [%s] 不存在或非 async，跳过", method_name)
            continue
        wrapped = async_sandbox_tool_adapter(method)
        toolkit.register_tool_function(wrapped)
        logger.debug("沙箱工具 [%s] 注册完成", method_name)
        count += 1

    logger.info("沙箱工具注册完成，共 %d 个", count)
    return count


# ---------------------------------------------------------------------------
# Skills 工具函数
# ---------------------------------------------------------------------------

def _pack_skills_tar(skills_dir: str, sandbox_skills_dir: str) -> str:
    """将本地 skills 目录打包为临时 tar.gz，返回临时文件路径。"""
    arcname = Path(sandbox_skills_dir).name  # 解压后的目录名，如 "skills"
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    with tarfile.open(tmp.name, "w:gz") as tar:
        tar.add(skills_dir, arcname=arcname)
    return tmp.name


def _register_skills(toolkit: Toolkit, skills_dir: str, sandbox_skills_dir: str) -> int:
    """从本地 SKILL.md 提取元数据，将 skills 注册到 toolkit（dir 指向沙箱路径）。

    绕过 register_agent_skill() 的本地路径校验，直接写入 toolkit.skills，
    dir 指向沙箱内路径，使 LLM 通过沙箱 read_file 工具读取 SKILL.md。
    """
    disabled = set(DISABLED_SKILLS)
    count = 0
    base = Path(skills_dir)

    for skill_dir in sorted(base.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_dir.is_dir() or not skill_md.exists():
            continue
        try:
            post = frontmatter.load(str(skill_md))
            name: str = post.metadata.get("name", skill_dir.name)
            description: str = post.metadata.get("description", "")
        except Exception as exc:
            logger.warning("解析 %s 失败，跳过：%s", skill_md, exc)
            continue

        if name in disabled:
            logger.debug("skill [%s] 在 DISABLED_SKILLS 中，跳过", name)
            continue

        sandbox_path = f"{sandbox_skills_dir}/{skill_dir.name}"
        toolkit.skills[name] = AgentSkill(
            name=name,
            description=description,
            dir=sandbox_path,
        )
        logger.debug("skill 已注册: [%s]  sandbox_dir=%s", name, sandbox_path)
        count += 1

    logger.info("skills 注册完成，共 %d 个（disabled=%d）", count, len(disabled))
    return count


async def _ensure_skills_uploaded(
    sandbox: AllInOneSandboxAsync,
    skills_dir: str,
    sandbox_skills_dir: str,
) -> None:
    """将 skills 打包压缩后上传到沙箱，再在沙箱内解压。"""
    skills_path = Path(skills_dir)
    if not skills_path.exists():
        logger.warning("SKILLS_DIR 不存在，跳过 skills 上传: %s", skills_dir)
        return

    exists = await sandbox.fs.exists_async(sandbox_skills_dir)
    if exists:
        logger.debug("沙箱内 skills 目录已存在，跳过上传: %s", sandbox_skills_dir)
        return

    logger.info("上传 skills 到沙箱 %s ...", sandbox_skills_dir)

    # 1. 本地打包成 tar.gz
    tmp_path = _pack_skills_tar(skills_dir, sandbox_skills_dir)
    try:
        size_kb = Path(tmp_path).stat().st_size / 1024
        logger.info("  [1/3] 打包完成  %.1f KB", size_kb)

        # 2. 上传单个压缩包到沙箱
        parent_dir = str(Path(sandbox_skills_dir).parent)
        sandbox_archive = f"{parent_dir}/skills.tar.gz"
        await sandbox.fs.write_from_path_async(
            sandbox_archive,
            tmp_path,
            content_type="application/gzip",
        )
        logger.info("  [2/3] 上传完成  %s", sandbox_archive)

        # 3. 在沙箱内解压，完成后删除压缩包
        cmd = f"tar -xzf {sandbox_archive} -C {parent_dir} && rm {sandbox_archive}"
        result = await sandbox.run_shell_command(cmd)
        logger.info("  [3/3] 解压完成  %s", result)

    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# AgentApp 实例
# ---------------------------------------------------------------------------
agent_app = AgentApp(
    app_name="AgentScope Skills Sandbox",
    app_description=(
        "集成 Agent Skills 与 All-in-One 沙箱的 AI 助手，"
        "具备代码执行、文件处理、浏览器操作等全套能力，"
        "基于 AgentScope ReActAgent + agentscope-runtime。"
    ),
)

# ---------------------------------------------------------------------------
# 应用启动时注册沙箱模板名 → AllInOneSandboxAsync
# ---------------------------------------------------------------------------
# 通过 register_template_name 将平台沙箱模板名（如 "all-in-one"）写入
# SandboxRegistry，后续可用 SandboxRegistry.get_classes_by_type() 查找。
_SandboxClass = register_template_name(SANDBOX_TEMPLATE_NAME)
logger.info(
    "沙箱模板 [%s] 已注册 → %s",
    SANDBOX_TEMPLATE_NAME,
    _SandboxClass.__name__,
)


# ---------------------------------------------------------------------------
# 中间件：将入站请求的 base URL（scheme + host）写入 contextvar
# ---------------------------------------------------------------------------
# 参考 zero_code 的 _capture_inbound_host 模式。
# 反向代理 / SLB 场景下，request.base_url 会携带客户端实际访问的域名，
# 用于 generate_download_url 生成正确的下载链接。

@agent_app.middleware("http")
async def capture_inbound_host(request: Request, call_next):
    base = str(request.base_url).rstrip("/")
    token = _inbound_host_var.set(base)
    try:
        return await call_next(request)
    finally:
        _inbound_host_var.reset(token)


# ---------------------------------------------------------------------------
# AgentApp 生命周期钩子
# ---------------------------------------------------------------------------

@agent_app.init
async def init_func(self):
    """应用启动：创建 SandboxService，初始化 session 缓存，打印配置摘要。"""
    # 与模块级 _sessions 共享同一个 dict 对象，/download 路由可直接访问
    self.sessions: dict[str, SessionState] = _sessions

    # 创建并启动 SandboxService（通过 manager session mapping 实现多副本沙箱复用）
    sandbox_manager_url = _get_env("SANDBOX_MANAGER_URL") or None
    sandbox_token = _get_env("SANDBOX_MANAGER_TOKEN") or None
    self.sandbox_service = SandboxService(
        base_url=sandbox_manager_url,
        bearer_token=sandbox_token,
        drain_on_stop=False,
    )
    await self.sandbox_service.start()

    skills_path = Path(SKILLS_DIR)
    skill_count = 0
    if skills_path.exists():
        skill_count = sum(
            1 for d in skills_path.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
            and d.name not in set(DISABLED_SKILLS)
        )

    logger.info(
        "AgentScope Skills Sandbox 启动完成  "
        "provider=%s  max_iters=%d  parallel_tool_calls=%s  skills=%d",
        _get_env("MODEL_PROVIDER", "openai"),
        _get_max_iters(),
        _get_parallel_tool_calls(),
        skill_count,
    )

    if not sandbox_manager_url:
        logger.warning(
            "SANDBOX_MANAGER_URL 未设置，将以 embedded 模式启动本地沙箱（仅供本地测试）。"
        )


@agent_app.shutdown
async def shutdown_func(self):
    """应用关闭：通过 SandboxService.stop() 释放所有沙箱。"""
    self.sessions.clear()
    _sessions.clear()

    if hasattr(self, "sandbox_service") and self.sandbox_service:
        logger.info("正在通过 SandboxService 释放所有沙箱...")
        await self.sandbox_service.stop()
        logger.info("SandboxService 已停止。")

    logger.info("AgentScope Skills Sandbox 已关闭。")


# ---------------------------------------------------------------------------
# Session 初始化：首次创建沙箱 + 注册工具
# ---------------------------------------------------------------------------

async def _init_session(session_id: str, sandbox_service: SandboxService) -> SessionState:
    """为新 session 通过 SandboxService 获取沙箱、注册工具与 skills，返回 SessionState。"""
    logger.info(">>> 初始化 session  session_id=%s", session_id)

    logger.info("  [1/4] 通过 SandboxService 获取沙箱  template=%s", SANDBOX_TEMPLATE_NAME)
    sandboxes = sandbox_service.connect(
        session_id=session_id,
        sandbox_types=[SANDBOX_TEMPLATE_NAME],
    )
    if not sandboxes:
        raise RuntimeError(
            f"SandboxService.connect 未返回沙箱实例  "
            f"session_id={session_id}  template={SANDBOX_TEMPLATE_NAME}"
        )
    sandbox = sandboxes[0]
    await sandbox.start_async()
    logger.info("  [1/4] 沙箱已就绪  sandbox_id=%s", sandbox.sandbox_id)

    logger.info("  [2/4] 上传 skills 到沙箱  dest=%s", SANDBOX_SKILLS_DIR)
    await _ensure_skills_uploaded(sandbox, SKILLS_DIR, SANDBOX_SKILLS_DIR)

    logger.info("  [3/4] 注册沙箱工具到 Toolkit")
    toolkit = Toolkit()
    _register_sandbox_tools(toolkit, sandbox)

    logger.info("  [4/4] 注册 skills 到 Toolkit  src=%s", SKILLS_DIR)
    skills_path = Path(SKILLS_DIR)
    if skills_path.exists():
        _register_skills(toolkit, SKILLS_DIR, SANDBOX_SKILLS_DIR)
    else:
        logger.warning("  [4/4] SKILLS_DIR 不存在，跳过: %s", SKILLS_DIR)

    # 注册文件下载工具（闭包绑定 session_id，endpoint 在调用时从 contextvar 动态解析）
    toolkit.register_tool_function(_make_generate_download_url(session_id))
    logger.info("  下载工具 generate_download_url 注册完成")

    logger.info("<<< session 初始化完成  session_id=%s  sandbox_id=%s",
                session_id, sandbox.sandbox_id)
    return SessionState(sandbox=sandbox, toolkit=toolkit)


# ---------------------------------------------------------------------------
# 核心查询处理函数
# ---------------------------------------------------------------------------

@agent_app.query(framework="agentscope")
async def query_func(
    self,
    msgs,
    request: AgentRequest = None,
    **kwargs,
):
    """处理每次用户请求，复用 per-session 沙箱与 Toolkit。

    Args:
        self:    Runner 实例，通过 self.sessions 访问 session 缓存。
        msgs:    已转换为 AgentScope Msg 格式的输入消息列表。
        request: AgentScope Runtime 标准请求对象。
        **kwargs: 框架传入的额外参数。

    Yields:
        (Msg, bool)：消息对象及是否为最后一个流式分片的标志。
    """
    session_id = request.session_id if request else str(uuid.uuid4())

    # 取首条消息的前 80 字符用于日志预览
    _preview = ""
    if msgs:
        _first = msgs[0]
        _text = getattr(_first, "content", "") or ""
        if isinstance(_text, list):
            _text = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in _text)
        _preview = str(_text)[:80].replace("\n", " ")

    logger.info("=> 请求开始  session_id=%s  input=%.80s", session_id, _preview)

    # -------------------------------------------------------------------
    # 1. 获取或初始化 session 状态
    # -------------------------------------------------------------------
    if session_id not in self.sessions:
        logger.info("新 session，初始化沙箱  session_id=%s", session_id)
        state = await _init_session(session_id, self.sandbox_service)
        self.sessions[session_id] = state
    else:
        state = self.sessions[session_id]
        logger.debug("复用已有 session  session_id=%s  sandbox_id=%s",
                     session_id, state.sandbox.sandbox_id)
        # 检查 skills 目录是否仍存在（沙箱可能因 idle timeout 重启）
        await _ensure_skills_uploaded(state.sandbox, SKILLS_DIR, SANDBOX_SKILLS_DIR)

    # -------------------------------------------------------------------
    # 2. 构建模型与 ReActAgent
    # -------------------------------------------------------------------
    model, formatter = _build_model()

    agent = ReActAgent(
        name="SkillsSandboxAssistant",
        sys_prompt=SYS_PROMPT,
        model=model,
        formatter=formatter,
        memory=state.memory,
        toolkit=state.toolkit,
        max_iters=_get_max_iters(),
        parallel_tool_calls=_get_parallel_tool_calls(),
    )
    agent.set_console_output_enabled(False)

    # 用代理模型替换，以捕获每次推理的 token 用量供 hook 日志使用
    agent.model = _UsageCapturingModel(agent.model)

    # -------------------------------------------------------------------
    # 3. 流式执行
    # -------------------------------------------------------------------
    logger.info("=> 请求执行  session_id=%s", session_id)

    async for msg, last in stream_printing_messages(
        agents=[agent],
        coroutine_task=agent(msgs),
    ):
        yield msg, last

    logger.info("<= 请求完成  session_id=%s", session_id)


# ---------------------------------------------------------------------------
# 文件下载路由：GET /download?token=<token>&path=<path>
# ---------------------------------------------------------------------------

@agent_app.get("/download", tags=["agent-api"])
async def download_file(
    token: str = Query(..., description="由 generate_download_url 工具生成的签名凭证"),
    path: str = Query(..., description="沙箱内文件绝对路径，如 /workspace/output/report.pdf"),
):
    """从沙箱内流式下载文件。

    token 由 Agent 调用 generate_download_url 工具生成，内含 session_id 与过期时间，
    经 HMAC-SHA256 签名防篡改，有效期 7 天，无需额外 Authorization 头。
    """
    session_id = _verify_download_token(token)
    if session_id is None:
        raise HTTPException(status_code=403, detail="无效或已过期的下载凭证")

    state = _sessions.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会话不存在或沙箱已释放")

    try:
        # 以流式模式读取，适合大文件
        file_stream = await state.sandbox.fs.read_async(path, fmt="stream")
    except Exception as exc:
        logger.warning("读取沙箱文件失败  path=%s  error=%s", path, exc)
        raise HTTPException(status_code=404, detail=f"文件不存在或读取失败: {exc}") from exc

    mime, _ = mimetypes.guess_type(path)
    filename = Path(path).name
    logger.info("下载沙箱文件  session_id=%s  path=%s  mime=%s", session_id, path, mime)

    # RFC 5987: 中文文件名需用 filename*=UTF-8''... 编码，否则 latin-1 报错
    from urllib.parse import quote
    encoded_filename = quote(filename, safe='')
    # 纯 ASCII 文件名直接用 filename=，含非 ASCII 字符则只用 filename*=
    try:
        filename.encode("ascii")
    except UnicodeEncodeError:
        content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"
    else:
        content_disposition = f'attachment; filename="{filename}"'

    return StreamingResponse(
        file_stream,
        media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": content_disposition},
    )


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
        description="AgentScope Skills Sandbox Demo Web 服务",
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
