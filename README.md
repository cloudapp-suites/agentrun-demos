# AgentRun Demos

[Agent Runtime](https://runtime.agentscope.io) 平台的示例项目集合，展示如何构建、部署和集成 AI Agent 与 ToolServer。

## Demo 索引

### Agent

| 目录 | 说明 |
|------|------|
| [agentscope-mcp](agentscope-mcp/) | AgentScope ReActAgent + 多远程 MCP 工具 AI 助手 |
| [agentscope-skills-sandbox](agentscope-skills-sandbox/) | AgentScope + Agent Skills + All-in-One 沙箱集成 |
| [react-with-sandbox-by-native-mcp](react-with-sandbox-by-native-mcp/) | ReActAgent 通过原生 MCP 协议连接远程沙箱 |
| [langgraph-sandbox-example](langgraph-sandbox-example/) | LangGraph + 沙箱集成示例 |

### ToolServer

| 目录 | 说明 |
|------|------|
| [code-execution-mcp](code-execution-mcp/) | 基于 MCP 协议的多语言代码执行服务 |

### 框架集成

| 目录 | 说明 |
|------|------|
| [openclaw-unified-sandbox](openclaw-unified-sandbox/) | OpenClaw + 统一沙箱后端（E2B / AgentScope 运行时切换） |
| [openclaw-agentscope-integration](openclaw-agentscope-integration/) | OpenClaw + AgentScope 沙箱集成 |
| [openclaw-e2b-integration](openclaw-e2b-integration/) | OpenClaw + E2B 沙箱集成 |
| [copaw-unified-sandbox](copaw-unified-sandbox/) | CoPaw + 统一沙箱后端（E2B / AgentScope 运行时切换） |
| [dify-e2b-integration](dify-e2b-integration/) | Dify + E2B 沙箱集成（Dify 插件方式） |

### 工具与文档

| 目录 | 说明 |
|------|------|
| [mcp-client-sample](mcp-client-sample/) | MCP Python SDK 示例客户端 |
| [pack-tools](pack-tools/) | Python / Node.js 应用离线打包工具 |
| [agent-integration-docs](agent-integration-docs/) | Agent 与 ToolServer 接入文档 |

### 进阶（TODO）

| 目录 | 说明 | 状态 |
|------|------|------|
| - | A2A（Agent-to-Agent）多 Agent 协作 | 🚧 TODO |
| - | 自定义沙箱模板开发 | 🚧 TODO |
| - | Agent + RAG + 沙箱联动（数据分析场景） | 🚧 TODO |
| - | 多 MCP Server 编排 | 🚧 TODO |
| - | 会话持久化与恢复 | 🚧 TODO |
| - | Agent 可观测性 | 🚧 TODO |

## 学习地图

| 阶段 | 内容 | 文档 / Demo |
|------|------|-------------|
| 1. 了解概念 | 平台核心概念：Agent、ToolServer、沙箱、Agent CR | [预备知识](agent-integration-docs/prerequisites.md) |
| 2. 创建 Agent | 零代码创建 / AgentScope 代码 / LangGraph 代码 | [零代码 Agent](agent-integration-docs/agent/code/zeroCodeAgent.md) |
| 3. 调用 Agent | curl / Python SDK（OpenAI 兼容接口） | [curl](agent-integration-docs/agent/code/curl.md)、[Python](agent-integration-docs/agent/code/python.md) |
| 4. 开发 ToolServer | MCP 协议（JSON / Python）/ agentscope-runtime SDK / 框架集成 | [ToolServer 接入文档](agent-integration-docs/toolserver/) |
| 5. 运行 Demo | 根据使用的框架选择对应 demo 实际运行 | 见上方 Demo 索引 |

## 快速开始

每个 demo 目录下都有独立的 `README.md`，包含环境要求、安装步骤和使用说明。

## License

[Apache 2.0](LICENSE)
