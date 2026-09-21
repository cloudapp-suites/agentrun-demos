# Agent Integration Docs

Agent Runtime 平台的集成文档，涵盖 Agent 和 ToolServer 的接入方式。

> 建议先阅读 [预备知识](prerequisites.md) 了解平台核心概念，以及 [访问凭证与鉴权](common/caller-credentials.md) 了解如何获取和携带凭证。
>
> 完整 Demo 与源码：[github.com/cloudapp-suites/agentrun-demos](https://github.com/cloudapp-suites/agentrun-demos)

## Agent 接入

通过代码方式创建和调用 Agent：

| 文档 | 说明 |
|------|------|
| [curl](agent/code/curl.md) | 使用 curl 调用 Agent（OpenAI 兼容接口） |
| [python](agent/code/python.md) | 使用 Python（OpenAI SDK）调用 Agent |
| [零代码 Agent](agent/code/zeroCodeAgent.md) | 通过管控台零代码创建 Agent |

## ToolServer 接入

### 代码方式

| 文档 | 说明 |
|------|------|
| [agentscope-runtime](toolserver/code/agentscope-runtime.md) | 基于 agentscope-runtime SDK 开发 ToolServer |
| [e2b](toolserver/code/e2b.md) | E2B 兼容沙箱 ToolServer |
| [langgraph](toolserver/code/langgraph.md) | LangGraph 集成 ToolServer |
| [claw-skill-integration](toolserver/code/claw-skill-integration.md) | Claw 类 Agent（OpenClaw / QwenPaw）技能方式集成沙箱 |

### MCP 方式

| 文档 | 说明 |
|------|------|
| [json](toolserver/mcp/json.md) | MCP ToolServer JSON 配置 |
| [python](toolserver/mcp/python.md) | MCP ToolServer Python 接入 |

## 打包与发布

| 工具 | 说明 |
|------|------|
| [pack-tools](https://github.com/cloudapp-suites/agentrun-demos/tree/main/pack-tools) | Python / Node.js 应用离线打包，生成压缩包通过管控台上传部署 |
