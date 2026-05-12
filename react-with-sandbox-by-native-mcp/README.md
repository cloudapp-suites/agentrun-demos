# ReActAgent + 远程沙箱 MCP Server Demo

使用 [AgentScope](https://github.com/modelscope/agentscope) 的 `ReActAgent`，
通过 **streamable-HTTP** 协议直接以**原生 MCP 方式**连接远程沙箱，自动发现并注册
沙箱暴露的所有 MCP 工具（文件系统、IPython、Shell、浏览器控制等），然后执行单次
任务或进入交互模式。

## 核心概念：原生 MCP 模式 vs 传统 SDK 模式

### 传统 SDK 模式

```
用户代码
  │
  ├─ SandboxClient.create()          # 通过沙箱 SDK 创建沙箱实例，获取实例 ID
  │
  ├─ sandbox.run_ipython_cell(...)   # 通过 SDK 提供的方法调用沙箱能力
  ├─ sandbox.run_shell_command(...)
  └─ sandbox.destroy()              # 显式销毁沙箱实例
```

沙箱实例的生命周期由 SDK 管理，调用方感知不到底层通信协议，灵活性受限于 SDK
所封装的接口。

### 原生 MCP 模式（本 Demo 演示的方式）

```
用户代码
  │
  ├─ HttpStatefulClient.connect()    # 直接建立 streamable-HTTP 长连接
  │     请求头携带：
  │       x-agentrun-session-id: <UUID>   ← 标识一个独占沙箱会话
  │       Authorization: Bearer <token>
  │
  ├─ list_tools() / call_tool()      # 标准 MCP 协议调用，无需沙箱专属 SDK
  └─ HttpStatefulClient.close()
```

**关键区别**：

| | 传统 SDK 模式 | 原生 MCP 模式 |
|---|---|---|
| 沙箱创建方式 | SDK 显式 `create()` | 首次请求时携带 `x-agentrun-session-id` 自动创建 |
| 会话绑定 | SDK 内部维护实例 ID | 每个请求头中的 `x-agentrun-session-id` 标识同一会话 |
| 工具发现 | SDK 硬编码接口 | 标准 MCP `list_tools()`，动态发现 |
| 协议依赖 | 沙箱专属 SDK | 标准 MCP 协议，任意 MCP 兼容客户端均可接入 |
| 沙箱独占性 | 实例隔离 | 相同 session-id 的请求路由到同一沙箱容器 |

**`x-agentrun-session-id` 的作用**：服务端以该请求头的值作为会话标识，将同一
session-id 的所有请求路由到同一个沙箱容器，从而保持进程状态（如 IPython kernel
中的变量、Shell 中的工作目录、浏览器实例等）在多次 MCP 调用之间持续存在。每次
运行 `main.py` 都会生成一个新 UUID，即创建一个全新的独占沙箱会话。

## 目录结构

```
react-with-sandbox-by-native-mcp/
├── main.py           # 主程序
├── requirements.txt  # Python 依赖
└── README.md
```

## 安装依赖

```bash
pip install -r requirements.txt
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | `--provider openai` 时必填 |
| `OPENAI_API_BASE` | OpenAI 兼容接口基础 URL，默认 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `DASHSCOPE_API_KEY` | `--provider dashscope` 时必填 |
| `DASHSCOPE_API_BASE` | DashScope 原生接口基础 URL，不设置则使用 SDK 默认值 |

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--url` | 远程 MCP Server 地址（streamable-HTTP 端点），**必填** | 无 |
| `--token` | 鉴权 token，写入 `Authorization: Bearer <token>` | 空字符串 |
| `--provider` | 模型 provider：`openai` 或 `dashscope` | `openai` |
| `--model` | 模型名称，与 `--provider` 搭配使用 | `qwen-plus` |
| `--task` | 单次任务描述，不填则进入交互模式 | 无 |

每次运行自动生成新的 `x-agentrun-session-id`（随机 UUID），对应一个独占沙箱会话。

超时：请求超时与 SSE 读取超时均为 **120 秒**。

## 使用示例

### DashScope 原生 SDK

```bash
export DASHSCOPE_API_KEY=<your-dashscope-key>

# 交互模式
python main.py \
    --provider dashscope \
    --model qwen-plus \
    --url http://<sandbox-host>/ \
    --token <auth-token>

# 单次任务
python main.py \
    --provider dashscope \
    --model qwen-plus \
    --url http://<sandbox-host>/ \
    --token <auth-token> \
    --task "列出 /workspace 目录，再用 Python 计算前 10 个质数"
```

### OpenAI 兼容接口（DashScope / DeepSeek / Moonshot 等）

```bash
export OPENAI_API_KEY=<your-dashscope-key>
export OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1

python main.py \
    --provider openai \
    --model qwen-plus \
    --url http://<sandbox-host>/ \
    --token <auth-token> \
    --task "截一张当前桌面截图"
```

### 标准 OpenAI

```bash
export OPENAI_API_KEY=<your-openai-key>

python main.py \
    --provider openai \
    --model gpt-4o \
    --url http://<sandbox-host>/ \
    --token <auth-token>
```

## 工作流程

```
main.py
  │
  ├─ 生成 x-agentrun-session-id（UUID）      # 标识本次独占沙箱会话
  │
  ├─ HttpStatefulClient.connect()            # 建立 streamable-HTTP 长连接
  │     所有请求均携带：
  │       x-agentrun-session-id: <UUID>
  │       Authorization: Bearer <token>
  │
  ├─ list_tools()                            # 动态发现沙箱暴露的 MCP 工具
  ├─ Toolkit.register_mcp_client()           # 注册到 AgentScope Toolkit
  │
  ├─ ReActAgent(toolkit=toolkit)             # 创建 ReAct Agent
  │     ├─ Reasoning: 分析任务，选择工具
  │     ├─ Acting:    通过 MCP call_tool() 调用沙箱工具
  │     └─ Observing: 观察工具返回结果，继续推理
  │
  └─ HttpStatefulClient.close()             # 关闭连接（沙箱会话随之结束）
```
