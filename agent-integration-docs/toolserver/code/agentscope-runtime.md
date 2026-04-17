# agentscope-runtime 集成沙箱工具

本文档演示如何在 agentscope-runtime Agent 中通过代码集成平台托管的沙箱工具。

---

## 概述

平台托管的沙箱工具（如 All-in-One 沙箱）提供代码执行、文件操作、浏览器控制、GUI 操作等能力。在 agentscope-runtime 中集成沙箱工具需要以下步骤：

1. **创建沙箱实例** — 通过沙箱管理器创建并启动沙箱
2. **适配工具方法** — 将沙箱方法的返回值转换为 AgentScope Toolkit 要求的 `ToolResponse`
3. **注册到 Toolkit** — 将适配后的方法注册到 Toolkit，供 ReActAgent 调用

---

## 1. 创建沙箱实例

### 基本用法

> **前提条件**：以下示例假设你已在平台上创建了名称为 `base` 的 ToolServer（即 ToolServer 名称与 agentscope-runtime 内置的沙箱类型名称一致）。如果你的 ToolServer 使用了自定义名称（如 `my-base`），请跳过本节，直接参考后面的 [名称不一致 — 需要注册映射](#名称不一致--需要注册映射) 章节。

agentscope-runtime 内置了 `BaseSandboxAsync`、`BrowserSandboxAsync` 等沙箱类，通过 `base_url` 和 `bearer_token` 连接集群的沙箱管理器（可从集群详情页获取）：

```python
from agentscope_runtime.sandbox.box.base import BaseSandboxAsync

# base_url:     集群沙箱管理器地址（可从集群详情页获取）
# bearer_token: 集群沙箱管理器访问凭证（可从集群详情页获取）
sandbox = BaseSandboxAsync(
    base_url="http://sandbox-manager.example.com",
    bearer_token="your-sandbox-manager-token",
)
await sandbox.start_async()

# 调用沙箱工具
result = await sandbox.run_ipython_cell("print('Hello from sandbox!')")
print(result)

# 使用完毕后释放
await sandbox.close_async()
```

### ToolServer 名称与沙箱类型的映射

ToolServer 名称是用户在平台上自定义的标识（如 `my-base`），用于在集群内查找 ToolServer。ToolServer 关联的沙箱类型由 YAML 中 `sandBoxTemplate.name` 字段确定（如 `base`、`browser`）。创建沙箱时需要将 ToolServer 名称作为 `sandbox_type` 传入。

根据 ToolServer 名称与 agentscope-runtime 内置沙箱类型名称是否一致，分两种情况：

#### 名称一致 — 无需注册

如果 ToolServer 名称恰好与 agentscope-runtime 内置的沙箱类型名称一致（如 `base`、`browser` 等），可以直接使用，无需额外注册：

```python
from agentscope_runtime.sandbox.box.base import BaseSandboxAsync

# ToolServer 名称为 "base"，与内置 SandboxType.BASE 一致
sandbox = BaseSandboxAsync(
    base_url="http://sandbox-manager.example.com",
    bearer_token="your-sandbox-manager-token",
    sandbox_type="base",
)
await sandbox.start_async()
```

> **注意**：此方式要求平台集群中存在名称为 `base` 的 ToolServer。如果用户创建的 ToolServer 使用了自定义名称（如 `my-base`），请参见下方的注册映射。

#### 名称不一致 — 需要注册映射

如果 ToolServer 名称是自定义的（如 `my-base`），与 agentscope-runtime 内置类型名称不一致，需要先通过 `register_custom_sandbox_type` 将自定义名称映射到对应的沙箱类：

```python
from agentscope_runtime.sandbox.enums import SandboxType
from agentscope_runtime.sandbox.registry import SandboxRegistry


def register_custom_sandbox_type(custom_name: str, sandbox_class: type):
    """将自定义 ToolServer 名称注册到 SandboxRegistry，映射到指定的沙箱类。

    Args:
        custom_name:   平台上 ToolServer 的名称（sandBoxTemplate.name）。
        sandbox_class: 对应的 agentscope-runtime 沙箱类。
    """
    existing_types = [t.value for t in SandboxType]
    if custom_name in existing_types:
        return

    SandboxType.add_member(custom_name.upper().replace("-", "_"), custom_name)
    custom_type = SandboxType(custom_name)
    SandboxRegistry._type_registry[custom_type] = sandbox_class
```

使用示例：

```python
from agentscope_runtime.sandbox.box.base import BaseSandboxAsync

# ToolServer 名称为 "my-base"，其 sandBoxTemplate.name 为 "base"
# 需要将 "my-base" 映射到 BaseSandboxAsync
register_custom_sandbox_type("my-base", BaseSandboxAsync)

sandbox = BaseSandboxAsync(
    base_url="http://sandbox-manager.example.com",
    bearer_token="your-sandbox-manager-token",
    sandbox_type="my-base",
)
await sandbox.start_async()
```

### 使用 All-in-One 沙箱

All-in-One 沙箱组合了代码执行、文件系统、浏览器、GUI 等全套能力。agentscope-runtime 目前尚未内置 `AllInOneSandboxAsync`，需要自定义定义。

通过多重继承复用已有的沙箱 Mixin，无需重复声明方法：

```python
from typing import Optional
from agentscope_runtime.sandbox.box.gui.gui_sandbox import GuiSandboxAsync
from agentscope_runtime.sandbox.box.filesystem.filesystem_sandbox import FilesystemSandboxAsync
from agentscope_runtime.sandbox.box.browser.browser_sandbox import BrowserSandboxAsync
from agentscope_runtime.sandbox.enums import SandboxType
from agentscope_runtime.sandbox.registry import SandboxRegistry
from agentscope_runtime.sandbox.utils import build_image_uri
from agentscope_runtime.sandbox.constant import TIMEOUT


@SandboxRegistry.register(
    build_image_uri("runtime-sandbox-all-in-one"),
    sandbox_type="all_in_one_async",
    security_level="high",
    timeout=TIMEOUT,
    description="All-in-One Sandbox (Async)",
)
class AllInOneSandboxAsync(GuiSandboxAsync, FilesystemSandboxAsync, BrowserSandboxAsync):
    """All-in-One 异步沙箱，集成代码执行、文件系统、浏览器、GUI 等全套工具。

    方法来源（通过 MRO 自动继承，无需重复声明）：
      - run_ipython_cell / run_shell_command  ← BaseSandboxAsync
      - computer_use / get_desktop_url_async  ← GuiSandboxAsync
      - read_file / write_file / ...          ← FilesystemSandboxAsync
      - browser_* 系列                        ← BrowserSandboxAsync
    """

    def __init__(
        self,
        sandbox_id: Optional[str] = None,
        base_url: Optional[str] = None,
        bearer_token: Optional[str] = None,
        sandbox_type: str = "all_in_one_async",
        workspace_dir: Optional[str] = None,
    ):
        super().__init__(
            sandbox_id,
            base_url,
            bearer_token,
            SandboxType(sandbox_type),
            workspace_dir,
        )
```

同样，如果 ToolServer 名称（如 `all-in-one`）与默认的 `all_in_one_async` 不一致，需要注册映射：

```python
# ToolServer 名称为 "all-in-one"，映射到 AllInOneSandboxAsync
register_custom_sandbox_type("all-in-one", AllInOneSandboxAsync)

sandbox = AllInOneSandboxAsync(
    base_url="http://sandbox-manager.example.com",
    bearer_token="your-sandbox-manager-token",
    sandbox_type="all-in-one",
)
await sandbox.start_async()
```


---

## 2. 沙箱工具适配器

AgentScope 的 Toolkit 要求工具函数返回 `ToolResponse` 对象，而沙箱方法返回的是 `dict`、`str` 或 MCP `CallToolResult` 等原始类型。需要一个适配器进行转换。

agentscope-runtime 目前尚未内置此适配器，以下提供完整实现：

```python
import logging
import functools
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from mcp.types import CallToolResult
from agentscope.mcp import MCPClientBase

logger = logging.getLogger(__name__)


def async_sandbox_tool_adapter(func):
    """将沙箱异步方法包装为返回 ToolResponse 的工具函数。

    通过 functools.wraps 保留原方法签名与 docstring，
    使 Toolkit 能正确生成 JSON Schema 暴露给 LLM。

    Args:
        func: 沙箱异步方法（如 sandbox.run_ipython_cell）。

    Returns:
        返回 ToolResponse 的 async 函数。
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            res = await func(*args, **kwargs)
        except Exception as e:
            logger.warning("沙箱工具调用失败  tool=%s  error=%s", func.__name__, e)
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: {e}")],
            )

        # 已经是 ToolResponse，直接返回
        if isinstance(res, ToolResponse):
            return res

        # 尝试解析为 MCP CallToolResult
        try:
            mcp_res = CallToolResult.model_validate(res)
            return ToolResponse(
                content=MCPClientBase._convert_mcp_content_to_as_blocks(mcp_res.content),
                metadata=mcp_res.meta,
            )
        except Exception:
            pass

        # 兜底：将原始返回值转为文本
        if isinstance(res, str):
            text = res
        elif isinstance(res, dict):
            text = str(res.get("content", res.get("stdout", res)))
        else:
            text = str(res)

        return ToolResponse(
            content=[TextBlock(type="text", text=text)],
        )

    return wrapper
```

---

## 3. 注册沙箱工具到 Toolkit

将沙箱方法通过适配器包装后注册到 Toolkit，供 ReActAgent 使用。

```python
import inspect
from agentscope.tool import Toolkit


# 需要注册的沙箱方法名列表（按能力分类）
SANDBOX_TOOL_METHODS = [
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


def register_sandbox_tools(toolkit: Toolkit, sandbox) -> int:
    """将沙箱的工具方法包装后注册到 Toolkit。

    Args:
        toolkit: 目标 Toolkit 实例。
        sandbox: 已启动的沙箱实例（如 AllInOneSandboxAsync）。

    Returns:
        实际注册的工具数量。
    """
    count = 0
    for method_name in SANDBOX_TOOL_METHODS:
        method = getattr(sandbox, method_name, None)
        if method is None or not inspect.iscoroutinefunction(method):
            continue
        wrapped = async_sandbox_tool_adapter(method)
        toolkit.register_tool_function(wrapped)
        count += 1
    return count
```

使用示例：

```python
toolkit = Toolkit()
count = register_sandbox_tools(toolkit, sandbox)
print(f"已注册 {count} 个沙箱工具")

# 将 toolkit 传给 ReActAgent
agent = ReActAgent(
    name="SandboxAgent",
    sys_prompt="你是一个智能助手，可以使用沙箱工具完成任务。",
    model=model,
    formatter=formatter,
    toolkit=toolkit,
)
```

---

## 环境变量参考

| 变量 | 必填 | 说明 |
|------|------|------|
| `SANDBOX_MANAGER_URL` | 是 | 集群沙箱管理器地址（可从集群详情页获取） |
| `SANDBOX_MANAGER_TOKEN` | 否 | 集群沙箱管理器访问凭证（可从集群详情页获取） |

---

## 完整 Demo

- [agentscope-mcp](https://github.com/cloudapp-suites/agentrun-demos/tree/main/agentscope-mcp) — AgentScope ReActAgent + 多远程 MCP 工具 AI 助手
- [agentscope-skills-sandbox](https://github.com/cloudapp-suites/agentrun-demos/tree/main/agentscope-skills-sandbox) — AgentScope + Agent Skills + All-in-One 沙箱集成

## 打包部署

如需将应用打包为离线压缩包通过管控台上传部署，请参考 [pack-tools](https://github.com/cloudapp-suites/agentrun-demos/tree/main/pack-tools)。
