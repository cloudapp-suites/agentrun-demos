# Claw 类 Agent 技能方式集成

OpenClaw、QwenPaw 等 Claw 类 Agent 框架部署到平台后，可通过平台**「技能」**机制调用托管沙箱（All-in-One / E2B）：技能包由平台生成，装入 Agent 即可使用，无需在 Agent 侧集成沙箱 SDK 或修改框架代码。

> 如需直接使用 E2B SDK 或 AgentScope SDK 接入沙箱，请分别参阅 e2b.md、agentscope-runtime.md。

---

## 集成机制

- **技能包由平台生成**——在控制台从目标 ToolServer（沙箱）生成技能包，内含技能说明与调用脚本
- **装入即用**——技能装入 Agent 后由其按需调用；沙箱的鉴权、创建、复用与回收均由平台处理，Agent 无需管理凭证
- **与框架无关**——机制对所有 Claw 类框架一致，差异仅在技能的安装方式与 Agent 的访问入口

---

## 完整 Demo

| Demo | 说明 |
|------|------|
| [openclaw-skill-demo](https://github.com/cloudapp-suites/agentrun-demos/tree/main/openclaw-skill-demo) | OpenClaw（独占模式）技能方式调用 All-in-One / E2B 沙箱 |
| [qwenpaw-skill-demo](https://github.com/cloudapp-suites/agentrun-demos/tree/main/qwenpaw-skill-demo) | QwenPaw（独占模式）技能方式调用 All-in-One / E2B 沙箱 |

> 部署 Agent、生成/下载技能包、安装技能等具体操作见各 Demo 的 README。
