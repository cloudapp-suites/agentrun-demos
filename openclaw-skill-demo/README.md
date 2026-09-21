# OpenClaw × 平台沙箱（技能方式集成）

将 [OpenClaw](https://github.com/openclaw/openclaw)（v2026.9.5）以**独占模式**（每会话一个独享实例）部署为 Agent Runtime 平台的 Agent，通过平台**「技能」**机制调用托管沙箱：控制台从 ToolServer 生成技能包（`SKILL.md` + `scripts/invoke.py`），在 Control UI 中导入技能后，Agent 运行技能脚本经网关（身份 JWT + RBAC）调用沙箱执行命令。

> 已在研发测试集群验证：`allinone-0920` / `e2b-0920` 两个沙箱均可在 OpenClaw 中通过技能执行命令（模型 `qwen3.8-flash`），命令返回的是沙箱 Pod 主机名（非 Agent 容器）。独占模式下已验证：会话子域访问冷启动、Host 头 Origin 校验（合法 Origin 放行 / 跨站 Origin 拒绝）、一次性配对链接生成。

## 链路

```
用户 → OpenClaw（Control UI / `openclaw agent` / 渠道消息）
  └─ Agent 加载技能（<workspace>/skills/<name>/SKILL.md）
      └─ exec 工具运行:
           cd <skill 目录> && python3 scripts/invoke.py --session-id <uuid> <method> '<json>'
          └─ MCP streamable-http → http://latest-<tool>.<ns>.svc.cluster.local
              └─ Higress 网关（agent-auth：身份 JWT 校验 + RBAC）
                  └─ ToolServer → 沙箱 Pod 执行（会话亲和：同 session-id 复用同一沙箱）
```

- 技能脚本读取平台挂载的身份凭证（`$AGENT_IDENTITY_TOKEN_PATH`）作为 `Authorization: Bearer`
- 沙箱命令不在 Agent 容器中运行；`hostname` 返回沙箱 Pod 名（如 `allinone-0920-ephemeral-1-xxx`）

## 前置条件

1. 集群已纳管到控制台，`default` 命名空间存在可用沙箱：`kubectl get toolserver -n default`

   > 命名空间以实际为准：本文示例统一用 `default`，命令与 CR 中的 `namespace` 请按你的环境替换（`pair-browser.sh` 会提示输入）。
2. 镜像：`apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/openclaw-skill:2026.9.5`
   （公开可读、匿名可拉取，无需 `imagePullSecrets`；基于 OpenClaw 官方镜像 v2026.9.5 的薄包装，见 [Dockerfile](Dockerfile)：追加 entrypoint 生成配置 + 预装 `python3` 与 `mcp==1.29.0`，技能脚本依赖）
3. **域名绑定**：独占模式的会话入口是独立子域 `<会话ID>.<agent名>.<ns>.<域名>`，需能解析到平台网关，否则浏览器/脚本访问不到：
   - 本地快速验证：在 `/etc/hosts` 增加一行（IP 与 `latest-<agent>.<ns>.<域名>` 的解析一致）：
     ```
     <网关IP>  sess1.openclaw-skill-demo.default.agentrun.time
     ```
   - 长期使用：请管理员为 `*.<agent>.<ns>.<域名>`（或 `*.<域名>`）配置 DNS 泛解析
4. 强管控（enforcing）集群需给 Agent 授权，见「四、授权」

## 一、部署 OpenClaw Agent

### 方式 A：CR 方式（kubectl）

```bash
# 1. 编辑 openclaw-agent-cr.yaml，替换 LLM_API_KEY（必填）
# 2. 部署
kubectl apply -f openclaw-agent-cr.yaml
# 3. 等就绪（Agent READY=1；独占模式无常驻 Pod，访问时会话 Pod 才会拉起）
kubectl get agent openclaw-skill-demo -n default
```

CR 关键配置（`openclaw-agent-cr.yaml`）：

| 项 | 值 | 说明 |
|----|----|----|
| `image` | `.../agentrun/openclaw-skill:2026.9.5` | OpenClaw 薄包装镜像（公开可读） |
| `isolation` | `isolated` | 独占模式（推荐）：每会话一个独享实例，入口为 `<独占id>.<agent名>.<ns>.<域名>`，详见「独占模式说明」 |
| `ports` / 探针 | `18789` / `/healthz`（liveness）、`/startupz`（readiness） | 网关 HTTP 端口与探针（免鉴权） |
| `metadata.annotations` | `agentruntime.alibabacloud.com/access-mode: AllowAnonymous` | 平台不鉴权：网关放行匿名访问，可直接打开 Control UI |
| `OPENCLAW_GATEWAY_TOKEN` | 自定义 token | Control UI 连接时的 Gateway secret |

环境变量：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_BASE_URL` | 是 | - | OpenAI 兼容地址（如 dashscope compatible-mode） |
| `LLM_API_KEY` | 是 | - | LLM API Key（模板中为占位符；生产建议 Secret + `valueFrom.secretKeyRef`） |
| `LLM_MODEL` | 否 | `qwen3.8-flash` | 模型名（写入 `openclaw.json` 的 provider 目录与默认模型） |
| `OPENCLAW_GATEWAY_TOKEN` | 否 | - | Gateway token（Control UI / CLI 连接用；建议必填） |
| `OPENCLAW_TRUSTED_PROXIES` | 否 | - | 可信代理来源（逗号分隔）。平台在同一个 Pod 内以 loopback 转发并携带 `X-Forwarded-*`，声明 `127.0.0.1` 即可；否则 UI 访问被拒（`proxy_attribution_required`） |
| `OPENCLAW_UI_ORIGIN` | 否 | - | 浏览器 Origin 白名单。**独占模式下不需要**（域名随会话 ID 变化，entrypoint 自动启用 Host 头校验：Origin 必须与访问 Host 一致）；仅固定域名部署（共享模式）时使用 |
| `OPENCLAW_STATE_DIR` / `OPENCLAW_CONFIG_PATH` / `OPENCLAW_WORKSPACE_DIR` | 否 | `/home/node/.openclaw*` | 状态/配置/工作区路径 |

说明：
- 容器 entrypoint 启动时从 `LLM_*` 生成 `openclaw.json`（Gateway `bind: lan`、token 鉴权、自定义 provider `agentrun-llm`、默认模型、Control UI Origin 策略），然后启动 `openclaw gateway`
- 平台会把镜像 tag 解析为 digest 固定到 revision：**升级镜像需重建 Agent（`delete` + `apply`）重新解析 tag**；仅 `kubectl apply` 相同 spec 不会更新 Pod
- 容器工作目录不持久：**会话 Pod 销毁后需重新安装技能包、重新配对**（见「独占模式说明」）

### 方式 B：控制台（白屏）创建

1. 控制台 → **Agent** → 创建 Agent（高码/快速创建类型），填写：
   - 镜像：`apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/openclaw-skill:2026.9.5`
   - 端口：`18789`；健康检查：`/healthz`（就绪建议 `/startupz`）
   - 环境变量：逐个添加上表（`LLM_API_KEY`、`OPENCLAW_GATEWAY_TOKEN` 必填）
   - 隔离策略：选**独占**
2. Agent 「身份」页签：设置**平台不鉴权**（否则经域名打开 Control UI 会 401）
3. 创建后等待 Agent 就绪；访问方式见下方「独占模式说明」

### 独占模式说明（`isolation: isolated`，本 Demo 默认）

- **访问入口**：`http://<独占id>.<agent名>.<ns>.<域名>/`（如 `sess1.openclaw-skill-demo.default.agentrun.time`）——每会话一个独享实例，首次访问冷启动约 10s；基础域名与 `latest-` 域名不可用（403）
- **独占 id 格式**：独占 id 会被用作域名的**最左一段**，需符合域名段（DNS label）规则——仅小写字母、数字、连字符 `-`，不能以 `-` 开头或结尾，长度 ≤ 63；不要用大写、下划线、点等字符（合法示例：`sess1`、`team-a-01`；非法示例：`Sess_1.2`）
- **状态随会话 Pod**：技能、设备配对等状态都是该会话 Pod 的本地状态（无共享存储）。同一会话 ID 复用同一 Pod；空闲缩零后保留 30 分钟，超时 Pod 销毁、状态丢失（重新访问同一会话 ID 相当于全新环境）

## 二、获取沙箱技能包（控制台）

1. 控制台 → **工具** → 打开目标沙箱（如 `allinone-0920`、`e2b-0920`）
2. 「**生成技能**」页签 → **创建技能**：
   - 勾选需要暴露的方法（建议按需勾选；全选会让 `SKILL.md` 很大，不利于模型使用）
   - **调用方式选「集群内访问」**（OpenClaw 部署在平台内，脚本走 `latest-<tool>.<ns>.svc.cluster.local`）
   - 填写技能名称/描述后发布
3. 在技能列表**下载技能包**（zip：`SKILL.md` + `scripts/invoke.py`）

> 注意：**技能包从控制台下载获取，本仓库不内置**；名称与内容取决于你自己创建的工具沙箱（工具名不同则包不同）。

## 三、打开 Control UI 并安装技能

技能安装到 OpenClaw 工作区，**全程在 Control UI 完成，无需 kubectl**。

### 1. 打开会话并完成配对（交互式脚本）

```bash
./pair-browser.sh
```

脚本会依次：

1. 提示输入/确认：命名空间、Agent 名、**独占会话 ID**、平台域名（回车即用默认值；也可用 `NS=... SESSION_ID=...` 等环境变量作默认）
2. **访问会话入口**（触发该会话的独占 Pod 创建，首次冷启动约 10s）——若域名无法解析，会提示先做域名绑定（`/etc/hosts` 或 DNS 泛解析）
3. 按 label 等待会话 Pod 就绪（`serving.knative.dev/contextID=<会话ID>`）
4. 在 Pod 内生成**一次性配对链接**并输出

把输出的链接**在新标签页打开**即自动以 owner 身份完成设备配对（无需再输 Gateway 令牌）；链接约 10 分钟内有效，请勿外传。保持同一会话 ID，后续再次进入只需重新执行脚本。

> 更安全的登录方式（生产建议）：浏览器打开会话入口 → 输入 Gateway 令牌（`OPENCLAW_GATEWAY_TOKEN` 的值）→ 在 Pod 内批准设备：
> ```bash
> POD=$(kubectl get pod -n default \
>   -l "agentruntime.alibabacloud.com/agent=openclaw-skill-demo,serving.knative.dev/contextID=<会话ID>" \
>   -o jsonpath='{.items[0].metadata.name}')
> kubectl exec -n default $POD -c openclaw-skill-demo -- openclaw devices approve --latest
> ```

### 2. 鉴权与配对（简化说明）

- **网关强制认证**：OpenClaw 拒绝无认证监听非 loopback，本 Demo 用 token 模式（`OPENCLAW_GATEWAY_TOKEN`）
- **浏览器设备配对**：首次接入 Control UI 的新浏览器需要在网关侧配对；Minimal 路径 = `pair-browser.sh` 的一次性链接（自动配对、owner 权限、约 10 分钟有效）
- **平台侧**（`access-mode: AllowAnonymous`）只控制"能否访问到网关"；网关自身的 token 与设备配对仍然生效
- 生产级认证（OIDC/Cloudflare Access/Tailscale 等）见 OpenClaw 官方文档：[gateway/auth](https://docs.openclaw.ai/gateway/config-gateway)

### 3. 导入技能

1. 进入 **设置 → Skills**，点「**导入技能**」
2. 填写技能名称，然后**选择整个技能文件夹**（技能包解压后的目录，含 `SKILL.md` 与 `scripts/`），或分别选择其中的文件
3. 导入后确认技能出现在「**工作区 Skills**」分组，且状态为「**就绪**」

### 4. 验证

在 Control UI 聊天里发：

> 请使用 <技能名> 技能，在平台沙箱中执行 shell 命令 hostname

期望结果：回复中的主机名是**沙箱 Pod**（如 `allinone-0920-ephemeral-*`），不是 Agent 容器。

## 四、授权（强管控集群）

enforcing 模式下 Agent 默认无权调用 ToolServer，在控制台「**安全与权限 → 访问控制**」配置：

1. **策略管理** → 创建策略，策略文档（`<clusterId>` 为 Agent 所在集群 ID）：

   ```json
   [{"Effect":"Allow","Action":["Invoke"],
     "Resource":["<clusterId>/default/ToolServer/allinone-0920",
                 "<clusterId>/default/ToolServer/e2b-0920"]}]
   ```

2. **角色管理** → 创建角色并挂载该策略
3. 将角色**绑定到该 Agent 的身份**（Agent 创建时平台自动生成同名身份）

> ⚠️ **重建 Agent（delete + apply）后绑定会随旧身份清理而丢失**——需要重新执行第 3 步绑定（策略与角色保留）。revision 滚动（改 spec）不受影响。

宽松（permissive）模式无需此步骤。

## 五、常见问题

| 现象 | 原因 / 处理 |
|------|------|
| 会话子域无法解析（浏览器打不开、脚本提示域名绑定） | 未做域名绑定：`/etc/hosts` 加一行或让管理员配 DNS 泛解析（见「前置条件-3」） |
| 基础 / `latest-` 域名访问 403 | 独占模式必须走会话子域 `<独占id>.<agent名>.<ns>.<域名>` |
| 换会话 ID 后技能/配对消失 | 状态是会话 Pod 本地：保持同一会话 ID；Pod 销毁后需重装技能、重配对 |
| UI 打开后一直等待批准 | 新浏览器需设备配对：用 `./pair-browser.sh` 的一次性链接；或在 Pod 内 `openclaw devices approve --latest` |
| UI 连不上（Origin 校验失败） | 独占模式 entrypoint 已启用 Host 头校验（Origin 必须与访问 Host 一致）；固定域名部署需设 `OPENCLAW_UI_ORIGIN` 为实际访问域名（含协议、端口） |
| 日志告警 `dangerouslyAllowHostHeaderOriginFallback=true is enabled` | 独占模式下的预期行为：访问域名随会话变化，网关按 Host 校验 Origin（仅 Origin=访问 Host 时放行，跨站 Origin 仍被拒绝）；固定域名部署设 `OPENCLAW_UI_ORIGIN` 后不再出现 |
| 技能脚本 `ImportError: cannot import name 'streamablehttp_client'` | 容器的 `mcp` 版本过新（2.x 移除了兼容名）；固定 `mcp==1.29.0`（本 Demo 镜像已内置） |
| 网关启动被拒：`existing config is missing gateway.mode` | 配置缺少 `gateway.mode`；entrypoint 已生成 `mode: "local"` |
| 平台内访问不到网关 | 容器内默认 `bind: loopback`；配置需 `gateway.bind: "lan"` |
| UI 403 `proxy_attribution_required` | 请求经平台转发（loopback + `X-Forwarded-*`）但未声明可信代理；设置 `OPENCLAW_TRUSTED_PROXIES=127.0.0.1` |
| 想把网关设为无认证（`auth.mode=none`） | 不可行：非 loopback 监听必须带认证，网关启动时直接拒绝（`refusing to bind gateway to 0.0.0.0:18789 without auth`） |
| 403 `no_matching_policy` | 未授权：检查 策略/角色/绑定（见「四」）；重建 Agent 后需重新绑定 |
| 模型 401 / `No API key found for provider "agentrun-llm"` | `LLM_API_KEY` 未配置或仍为占位符 |
| 沙箱命令返回主机名是 Agent Pod | 技能未生效：确认技能在「工作区 Skills」中为「就绪」，且提示词点名了正确技能 |
| `kubectl apply` 后镜像未更新 | revision 固定了镜像 digest；需 `delete` + `apply` 重建 Agent |

## 文件说明

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 薄包装镜像：OpenClaw 官方镜像 + entrypoint + `python3`/`mcp==1.29.0` |
| `entrypoint.sh` | 从环境变量生成 `openclaw.json`（Gateway/Provider/默认模型/Origin 策略）并启动网关 |
| `openclaw-agent-cr.yaml` | Agent CR 模板（独占模式；`LLM_API_KEY` 为占位符，使用前替换） |
| `pair-browser.sh` | 交互式打开独占会话并生成 Control UI 一次性配对链接（见「三-1」） |

镜像重新构建（需 Docker + buildx）：

```bash
docker buildx build --platform linux/amd64 \
  -t <你的镜像仓库>/openclaw-skill:2026.9.5 --push .
# 国内网络不便时，可先用 --build-arg OPENCLAW_BASE=<你的镜像仓库>/openclaw:2026.9.5 镜像官方镜像
```
