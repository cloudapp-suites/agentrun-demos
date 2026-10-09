# Hermes × 平台沙箱（技能方式集成）

将 [Hermes](https://github.com/NousResearch/hermes-agent)（v2026.9.24）以**独占模式**（每会话一个独享实例）部署为 Agent Runtime 平台的 Agent，通过平台**「技能」**机制调用托管沙箱：控制台从 ToolServer 生成技能包（`SKILL.md` + `scripts/invoke.py`），安装到 Hermes 技能目录后，Agent 用终端工具运行技能脚本，经网关（身份 JWT + RBAC）调用沙箱执行命令。

> 已在研发测试集群验证（2026-10-08）：镜像部署、Dashboard 对话（WebSocket 与 API Server）与技能安装使用均已实测；沙箱技能脚本链路（身份 JWT → 网关 RBAC）已验证至鉴权环节，按「四、授权」为 Agent 绑定 ToolServer 后即可调用沙箱执行命令。

## 链路

```
用户 → Hermes Dashboard（浏览器聊天，9119）/ API Server（OpenAI 兼容，8642）
  └─ Agent 加载技能（$HERMES_HOME/skills/<name>/SKILL.md，渐进式披露）
      └─ 终端工具运行:
           cd <技能目录> && python3 scripts/invoke.py --session-id <uuid> <method> '<json>'
          └─ MCP streamable-http → http://latest-<tool>.<ns>.svc.cluster.local
              └─ Higress 网关（agent-auth：身份 JWT 校验 + RBAC）
                  └─ ToolServer → 沙箱 Pod 执行（会话亲和：同 session-id 复用同一沙箱）
```

- 技能脚本读取平台挂载的身份凭证（`$AGENT_IDENTITY_TOKEN_PATH`）作为 `Authorization: Bearer`
- 沙箱命令不在 Agent 容器中运行；`hostname` 返回沙箱 Pod 名（如 `allinone-0920-ephemeral-1-xxx`）

## 前置条件

1. 集群已纳管到控制台，`default` 命名空间存在可用沙箱：`kubectl get toolserver -n default`

   > 命名空间以实际为准：本文示例统一用 `default`，命令与 CR 中的 `namespace` 请按你的环境替换（`install-skill.sh` 会提示输入）。
2. 镜像：`apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/hermes-skill:v2026.9.24`
   （公开可读、匿名可拉取，无需 `imagePullSecrets`；本目录 [Dockerfile](Dockerfile) 构建的官方镜像薄包装，已在研发测试集群验证）；如需自行构建：

   ```bash
   docker buildx build --platform linux/amd64 --provenance=false \
     -t <你的镜像仓库>/hermes-skill:v2026.9.24 --push .
   # 国内构建网络不便时，可先镜像官方镜像再覆盖 base：
   #   --build-arg HERMES_BASE=<你的镜像仓库>/hermes-agent:v2026.9.24
   ```

   薄包装做了三件事：① 追加技能脚本运行时（独立 venv：`python3` + `mcp==1.29.0`——技能脚本依赖 `streamablehttp_client` 兼容名，`mcp` 2.x 已移除，官方镜像的 Python 环境不保证该版本）；② 追加 entrypoint：从 `LLM_*` 环境变量生成 `config.yaml`（Provider / 默认模型）；③ 以 `gateway run` 启动 Dashboard + API Server（由容器内 s6-overlay 托管）。
3. **域名绑定**：独占模式的会话入口是独立子域 `<会话ID>.<agent名>.<ns>.<域名>`，需能解析到平台网关，否则浏览器/脚本访问不到：
   - 本地快速验证：在 `/etc/hosts` 增加一行（IP 与 `latest-<agent>.<ns>.<域名>` 的解析一致）：
     ```
     <网关IP>  sess1.hermes-skill-demo.default.agentrun.time
     ```
   - 长期使用：请管理员为 `*.<agent>.<ns>.<域名>`（或 `*.<域名>`）配置 DNS 泛解析
4. 强管控（enforcing）集群需给 Agent 授权，见「四、授权」

## 一、部署 Hermes Agent

### 方式 A：CR 方式（kubectl）

```bash
# 1. 编辑 hermes-agent-cr.yaml，替换 LLM_API_KEY、Dashboard 登录密码、API_SERVER_KEY 等占位符（镜像按需替换为自建仓库）
# 2. 部署
kubectl apply -f hermes-agent-cr.yaml
# 3. 等就绪（Agent READY=1；独占模式无常驻 Pod，访问时会话 Pod 才会拉起）
kubectl get agent hermes-skill-demo -n default
```

CR 关键配置（`hermes-agent-cr.yaml`）：

| 项 | 值 | 说明 |
|----|----|----|
| `image` | `.../agentrun/hermes-skill:v2026.9.24` | 官方 Hermes 镜像的薄包装镜像（公开可读；见「前置条件-2」） |
| `isolation` | `isolated` | 独占模式（推荐）：每会话一个独享实例，入口为 `<独占id>.<agent名>.<ns>.<域名>`，详见「独占模式说明」 |
| `ports` / 探针 | `9119`（Dashboard）；探针走容器内 `curl 127.0.0.1:8642/health` | API Server 的 `/health` 免登录，适合做探针；Dashboard 端口有登录认证，不适合直接 HTTP 探针 |
| `metadata.annotations` | `agentruntime.alibabacloud.com/access-mode: AllowAnonymous` | 平台不鉴权：网关放行匿名访问，可直接打开 Dashboard；Dashboard basic auth 仍生效 |
| `HERMES_DASHBOARD_BASIC_AUTH_*` | 自定义 | Dashboard 登录用户名/密码/会话密钥 |

环境变量：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `LLM_BASE_URL` | 是 | - | OpenAI 兼容地址（如 dashscope compatible-mode） |
| `LLM_API_KEY` | 是 | - | LLM API Key（模板中为占位符；生产建议 Secret + `valueFrom.secretKeyRef`） |
| `LLM_MODEL` | 否 | `qwen3.8-flash` | 模型名（写入 `config.yaml` 的 provider 目录与默认模型） |
| `HERMES_DASHBOARD` | 否 | - | 设为 `1` 启用 Dashboard（容器内 `0.0.0.0:9119`） |
| `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `_PASSWORD` | 是 | - | Dashboard 登录用户名/密码。非回环绑定必须配置认证，否则 Dashboard 拒绝启动（fail closed） |
| `HERMES_DASHBOARD_BASIC_AUTH_SECRET` | 否 | - | 会话签名密钥（`openssl rand -hex 32`），保证重启后登录态稳定 |
| `API_SERVER_ENABLED` | 是 | - | 启用 API Server（Dashboard 聊天依赖它，也提供 OpenAI 兼容 `/v1/chat/completions` 与 `/health`） |
| `API_SERVER_HOST` | 否 | `127.0.0.1` | 容器内需设为 `0.0.0.0` |
| `API_SERVER_KEY` | 是 | - | API Server 的 Bearer Key（≥8 字符，`openssl rand -hex 32`） |
| `HERMES_HOME` | 否 | `/opt/data` | 配置/技能/会话数据目录（官方镜像默认，通常无需修改） |

说明：
- 容器 entrypoint 启动时从 `LLM_*` 生成 `config.yaml`（自定义 Provider `agentrun-llm` + 默认模型），Dashboard 里无需再手工配置模型
- 平台会把镜像 tag 解析为 digest 固定到 revision：**升级镜像需重建 Agent（`delete` + `apply`）重新解析 tag**；仅 `kubectl apply` 相同 spec 不会更新 Pod
- 容器工作目录不持久（`/opt/data` 随 Pod 生命周期）：**会话 Pod 销毁后需重新安装技能包**（见「独占模式说明」）

### 方式 B：控制台（白屏）创建

1. 控制台 → **Agent** → 创建 Agent（高码/快速创建类型），填写：
   - 镜像：`apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/hermes-skill:v2026.9.24`
   - 端口：`9119`；健康检查：`/health`（API Server 端口 8642；如控制台不支持跨端口探针，建议改用 CR 方式部署）
   - 环境变量：逐个添加上表（`LLM_API_KEY`、`HERMES_DASHBOARD_BASIC_AUTH_*`、`API_SERVER_KEY` 必填）
   - 隔离策略：选**独占**
2. Agent 「身份」页签：设置**平台不鉴权**（否则经域名打开 Dashboard 会 401）
3. 创建后等待 Agent 就绪；访问方式见下方「独占模式说明」

### 独占模式说明（`isolation: isolated`，本 Demo 默认）

- **访问入口**：`http://<独占id>.<agent名>.<ns>.<域名>/`（如 `sess1.hermes-skill-demo.default.agentrun.time`）——每会话一个独享实例，首次访问冷启动约 10s；基础域名与 `latest-` 域名不可用（403）
- **独占 id 格式**：独占 id 会被用作域名的**最左一段**，需符合域名段（DNS label）规则——仅小写字母、数字、连字符 `-`，不能以 `-` 开头或结尾，长度 ≤ 63；不要用大写、下划线、点等字符（合法示例：`sess1`、`team-a-01`；非法示例：`Sess_1.2`）
- **状态随会话 Pod**：技能、会话记录、Dashboard 登录态等状态都是该会话 Pod 的本地状态（无共享存储）。同一会话 ID 复用同一 Pod；空闲缩零后保留 30 分钟，超时 Pod 销毁、状态丢失（重新访问同一会话 ID 相当于全新环境，需重装技能）

## 二、获取沙箱技能包（控制台）

1. 控制台 → **工具** → 打开目标沙箱（如 `allinone-0920`、`e2b-0920`）
2. 「**生成技能**」页签 → **创建技能**：
   - 勾选需要暴露的方法（**建议按需勾选**；全选会让 `SKILL.md` 很大，不利于模型使用）
   - **调用方式选「集群内访问」**（Hermes 部署在平台内，脚本走 `latest-<tool>.<ns>.svc.cluster.local`）
   - 填写技能名称/描述后发布
3. 在技能列表**下载技能包**（zip：`SKILL.md` + `scripts/invoke.py`）

> 技能包内容：`SKILL.md` 描述沙箱能力与方法用法；`scripts/invoke.py` 是生成的 MCP streamable-http 客户端（自动携带身份 JWT 与会话头）。
>
> 注意：**技能包从控制台下载获取，本仓库不内置**；名称与内容取决于你自己创建的工具沙箱（工具名不同则包不同）。

## 三、打开 Hermes Dashboard 并安装技能

### 1. 打开 Dashboard

浏览器访问 `http://<独占id>.<agent名>.<ns>.<域名>/`，输入 basic auth 用户名/密码（CR 中 `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `_PASSWORD` 的值）。

### 2. 安装技能（交互式脚本）

```bash
./install-skill.sh
```

脚本会依次：确认参数（命名空间、Agent 名、独占会话 ID、平台域名、技能包路径）→ 访问会话入口触发该会话的独占 Pod 创建（首次冷启动约 10s）→ 等待会话 Pod 就绪 → 复制技能包到 Pod 内 `/opt/data/skills/<技能名>/`（放入即被索引，无需联网安装）→ 执行 `hermes skills list` 验证。

手动方式（等效）：

```bash
POD=$(kubectl get pod -n default \
  -l "agentruntime.alibabacloud.com/agent=hermes-skill-demo,serving.knative.dev/contextID=<会话ID>" \
  -o jsonpath='{.items[0].metadata.name}')
kubectl cp -n default -c hermes-skill-demo ./<技能目录> "$POD:/opt/data/skills/<技能名>"
kubectl exec -n default "$POD" -c hermes-skill-demo -- hermes skills list
```

（`<技能目录>` 为技能包 zip 解压后的目录，含 `SKILL.md` 与 `scripts/`）

### 3. 验证

Dashboard 中**新建对话**（技能索引随会话创建，进行中的对话不会重载），发：

> 请使用 <技能名> 技能，在平台沙箱中执行 shell 命令 hostname 和 uname -a，然后把结果告诉我

期望结果：命令输出的主机名是**沙箱 Pod**（如 `allinone-0920-ephemeral-*`），不是 Agent 容器。

### 4. 可选：API Server（OpenAI 兼容）

平台入口是 Dashboard（9119）；API Server（8642）仅在容器内监听，调试脚本调用可先 port-forward：

```bash
kubectl port-forward -n default "$POD" 8642:8642
# 以 API_SERVER_KEY 作为 Bearer，请求 /v1/chat/completions（OpenAI Chat Completions 格式）
```

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
| 换会话 ID 后技能 / 会话记录消失 | 状态是会话 Pod 本地：保持同一会话 ID；Pod 销毁后需重装技能 |
| Dashboard 启动失败 / 打不开 | 非回环绑定必须配置认证：确认 `HERMES_DASHBOARD_BASIC_AUTH_USERNAME` / `_PASSWORD` 已设置 |
| Dashboard 打开但聊天无响应 | API Server 未启用或在启动中：确认 `API_SERVER_ENABLED=true` 且 `API_SERVER_KEY` 已设置（Dashboard 聊天依赖 gateway API） |
| 技能已放入但 Agent 不用它 | 需**新建对话**（进行中的会话不重载）；用 `hermes skills list`（kubectl exec）确认技能已列出；提示词点名技能名 |
| 模型反复调 Skill 而不执行脚本 | 模型工具调用能力不足：优先用工具调用能力较强的模型（`LLM_MODEL`）；技能按需勾选方法，减小 `SKILL.md` 体积 |
| 技能脚本 `ImportError: cannot import name 'streamablehttp_client'` | 容器内 `python3` 未指向技能脚本运行时：请使用本 Demo 镜像（内置 `mcp==1.29.0`）；自建镜像时勿省略 Dockerfile 中的 skill-runtime 步骤 |
| 沙箱命令返回主机名是 Agent Pod | 技能未生效：确认技能已安装、对话为新建，且提示词点名了正确技能 |
| 403 `no_matching_policy` | 未授权：检查 策略/角色/绑定（见「四」）；重建 Agent 后需重新绑定 |
| 模型 401 / 无可用 Provider | `LLM_API_KEY` 未配置或仍为占位符；配置后重建会话 Pod |
| `kubectl apply` 后镜像未更新 | revision 固定了镜像 digest；需 `delete` + `apply` 重建 Agent |
| 探针一直失败 | `/health` 由 API Server 提供（8642）：确认 `API_SERVER_ENABLED=true`；容器内可直接 `curl http://127.0.0.1:8642/health` 排查 |

## 文件说明

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 薄包装镜像：官方 Hermes 镜像 + 技能脚本运行时（`mcp==1.29.0`）+ entrypoint |
| `entrypoint.sh` | 从 `LLM_*` 环境变量生成 `config.yaml`（Provider / 默认模型），再以 `gateway run` 启动 |
| `hermes-agent-cr.yaml` | Agent CR 模板（独占模式；镜像为已推送的实测镜像，各类密钥为占位符，使用前替换） |
| `install-skill.sh` | 交互式把控制台下载的技能包安装到独占会话 Pod 的技能目录 |

镜像重新构建（需 Docker + buildx）：

```bash
docker buildx build --platform linux/amd64 --provenance=false \
  -t <你的镜像仓库>/hermes-skill:v2026.9.24 --push .
```

参考：Hermes 官方文档 [hermes-agent.nousresearch.com/docs](https://hermes-agent.nousresearch.com/docs/)（Docker 部署 / Web Dashboard / API Server / Skills）。
