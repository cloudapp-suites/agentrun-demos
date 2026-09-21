# QwenPaw × 平台沙箱（技能方式集成）

将 [QwenPaw](https://github.com/agentscope-ai/QwenPaw) 部署为 Agent Runtime 平台的 Agent，通过平台**「技能」**机制调用托管沙箱：控制台从 ToolServer 生成技能包（`SKILL.md` + `scripts/invoke.py`），上传到 QwenPaw 后，Agent 用 `execute_shell_command` 运行技能脚本，经网关（身份 JWT + RBAC）调用沙箱执行命令。

> 已在研发测试集群验证（2026-09-20）：`allinone-0920` / `e2b-0920` 两个沙箱均可在 QwenPaw 中通过技能执行命令，命令返回的是沙箱 Pod 主机名（非 Agent 容器）。

## 链路

```
用户 → QwenPaw 界面（对话）
  └─ Agent 加载技能（读 SKILL.md）
      └─ execute_shell_command:
           cd <skill 目录> && python scripts/invoke.py --session-id <uuid> <method> '<json>'
          └─ MCP streamable-http → http://latest-<tool>.<ns>.svc.cluster.local
              └─ Higress 网关（agent-auth：身份 JWT 校验 + RBAC）
                  └─ ToolServer → 沙箱 Pod 执行（会话亲和：同 session-id 复用同一沙箱）
```

- 技能脚本读取平台挂载的身份凭证（`$AGENT_IDENTITY_TOKEN_PATH`，即 `/var/run/agentruntime/credentials/identity/token`），以 `Authorization: Bearer <JWT>` 调用网关，不携带 ToolServer 凭证
- 沙箱内执行的命令不在 Agent 容器中运行；`hostname` 返回沙箱 Pod 名（如 `allinone-0920-ephemeral-1-xxx`）
- 会话亲和：技能脚本按 session-id 复用沙箱，会话内多次命令共享沙箱状态

## 前置条件

1. 集群已纳管到控制台，`default` 命名空间存在可用的沙箱（ToolServer）：

   > 命名空间以实际为准：本文示例统一用 `default`，命令与 CR 中的 `namespace` 请按你的环境替换。

   ```bash
   kubectl get toolserver -n default
   ```

2. QwenPaw 镜像：`apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun-test/qwenpaw-agentscope:latest`（内置 QwenPaw + Console 前端；技能方式不依赖任何代码补丁）
3. 强管控（enforcing）集群需先给 Agent 授权，见「四、授权」

## 一、创建 QwenPaw Agent

### 方式 A：CR 方式（kubectl）

```bash
# 1. 编辑 qwenpaw-agent-cr.yaml，替换 LLM_API_KEY（必填）
# 2. 部署
kubectl apply -f qwenpaw-agent-cr.yaml
# 3. 等就绪（Pod 2/2 Running、Agent READY=1）
kubectl get agent qwenpaw-skill-demo -n default
```

CR 关键配置（`qwenpaw-agent-cr.yaml`）：

| 项 | 值 | 说明 |
|----|----|----|
| `image` | `.../agentrun-test/qwenpaw-agentscope:latest` | QwenPaw 镜像 |
| `isolation` | `isolated` | 独占模式（推荐）：每会话一个独享实例，入口为 `<独占id>.<agent名>.<ns>.<域名>`；详见下方「独占模式说明」 |
| `ports` / 探针 | `8088` / 容器内 `exec` 探针（`curl http://127.0.0.1:8088/api/healthz`） | QwenPaw HTTP 服务；开启登录认证后 `/api/healthz` 需认证，探针须走容器内 loopback（在认证豁免名单中） |
| `metadata.annotations` | `agentruntime.alibabacloud.com/access-mode: AllowAnonymous` | 平台不鉴权：网关放行匿名访问，可直接从域名打开 QwenPaw 界面（等价于控制台「身份」页签设置「平台不鉴权」） |
| `imagePullSecrets` | `imagepull-...` | 按集群实际的镜像拉取凭证填写 |

环境变量：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `QWENPAW_WORKING_DIR` | 否 | `/app/working` | QwenPaw 工作目录（config.json、workspaces） |
| `QWENPAW_SECRET_DIR` | 否 | `/app/working.secret` | 密钥目录（LLM Provider 配置） |
| `QWENPAW_RUNNING_IN_CONTAINER` | 否 | `1` | 容器模式 |
| `QWENPAW_PORT` | 否 | `8088` | HTTP 端口 |
| `QWENPAW_AUTH_ENABLED` | 否 | - | 设为 `true` 开启 Console 界面登录认证（单用户） |
| `QWENPAW_AUTH_USERNAME` | 否 | - | 登录用户名（开启认证时必填，启动时自动注册） |
| `QWENPAW_AUTH_PASSWORD` | 否 | - | 登录密码（开启认证时必填；模板中为占位符，使用前替换） |
| `LLM_BASE_URL` | 否 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI 兼容地址 |
| `LLM_API_KEY` | **是** | - | LLM API Key（模板中为占位符，使用前替换；生产建议用 Secret + `valueFrom.secretKeyRef`） |
| `LLM_MODEL` | 否 | `qwen3.8-flash` | 模型名。建议使用工具调用能力较强的模型（实测 `qwen3-coder-plus` 可用） |

说明：
- entrypoint 启动时把 `LLM_*` 写入 QwenPaw 的 Provider 配置（Console 界面无需手动配置模型）
- 开启登录认证后：打开界面需输入用户名/密码；凭据以加盐哈希存于 `SECRET_DIR/auth.json`（忘记密码可删除该文件后重启重新注册）
- 环境变量变更后 `kubectl apply` 会滚动出新 revision（新 Pod）；容器工作目录不持久，**Pod 重建后需重新上传技能包**

### 方式 B：控制台（白屏）创建

1. 控制台 → **Agent** → 创建 Agent（高码/快速创建类型），填写：
   - 镜像：`apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun-test/qwenpaw-agentscope:latest`
   - 端口：`8088`；健康检查：`/api/healthz`（如开启登录认证，HTTP 探针会因未带凭证而失败，建议改用 CR 方式部署或暂不开启认证）
   - 环境变量：逐个添加上表（`LLM_API_KEY` 必填）
2. Agent 「身份」页签：设置**平台不鉴权**（否则经域名打开 QwenPaw 界面会 401）
3. 创建后等待 Pod 就绪；共享模式 Agent URL 形如 `http://latest-<agent-name>.default.<集群域名>`，独占模式见下方说明

### 独占模式（`isolation: isolated`，本 Demo 默认）

- **访问入口**：`http://<独占id>.<agent名>.<ns>.<域名>/`（如 `sess1.qwenpaw-skill-demo.default.agentrun.time`）——每会话一个独享实例，首次访问冷启动约 10s；基础域名与 `latest-` 域名不可用（403）
- **独占 id 格式**：独占 id 会被用作域名的**最左一段**，需符合域名段（DNS label）规则——仅小写字母、数字、连字符 `-`，不能以 `-` 开头或结尾，长度 ≤ 63；不要用大写、下划线、点等字符（合法示例：`sess1`、`team-a-01`；非法示例：`Sess_1.2`）
- **技能包**：在会话界面上传即可（技能是会话实例本地状态，换会话需重新上传）
- **登录账号**：`QWENPAW_AUTH_*` 由环境变量自动注册，无需额外操作
- 浏览器访问时 `/etc/hosts` 需映射所用会话子域（不支持通配）

## 二、获取沙箱技能包（控制台）

1. 控制台 → **工具** → 打开目标沙箱（如 `allinone-0920`、`e2b-0920`）
2. 进入「**生成技能**」页签 → **创建技能**：
   - 勾选需要暴露的方法（**建议按需勾选**；全选会让 `SKILL.md` 很大，不利于模型使用）
   - **调用方式选「集群内访问」**（QwenPaw 部署在平台内，脚本走 `latest-<tool>.<ns>.svc.cluster.local`）
   - 填写技能名称/描述后发布
3. 在技能列表**下载技能包**（zip：`SKILL.md` + `scripts/invoke.py`）

> 技能包内容：`SKILL.md` 描述沙箱能力与方法用法；`scripts/invoke.py` 是生成的 MCP streamable-http 客户端（自动携带身份 JWT 与会话头）。
>
> 注意：**技能包从控制台下载获取，本仓库不内置**；名称与内容取决于你自己创建的工具沙箱（工具名不同则包不同）。

## 三、在 QwenPaw 中使用

1. 打开 QwenPaw 界面：独占模式用 `http://<独占id>.<agent名>.default.<域名>/`（本 Demo 默认，必须带会话子域）；共享模式用 `latest-<agent名>` 域名；本地调试也可 `kubectl port-forward` 到 Pod 的 8088
2. **Workspace → Skills → Add Skill → Upload via Zip**，上传两个技能包，技能出现在「Enabled Skills」即生效
3. 在 Chat 中让 Agent 使用技能，例如：

   > 请使用 allinone-0920 技能，在沙箱中执行 shell 命令 hostname 和 uname -a，然后把结果告诉我

4. 验证成功：命令输出的主机名是**沙箱 Pod**（`allinone-0920-ephemeral-*` / `e2b-0920-ephemeral-*`），不是 Agent 容器

## 四、授权（强管控集群）

enforcing 模式下 Agent 默认无权调用 ToolServer，在控制台「**安全与权限 → 访问控制**」配置：

1. **策略管理** → 创建策略，策略文档（`<clusterId>` 为 Agent 所在集群 ID）：

   ```json
   [{"Effect":"Allow","Action":["Invoke"],
     "Resource":["<clusterId>/default/ToolServer/allinone-0920",
                 "<clusterId>/default/ToolServer/e2b-0920"]}]
   ```

2. **角色管理** → 创建角色并挂载该策略
3. 将角色**绑定到该 Agent 的身份**（Agent 创建时平台自动生成身份，名与 Agent 同名）

宽松（permissive）模式无需此步骤。

## 五、常见问题

| 现象 | 原因 / 处理 |
|------|------|
| 403 `no_matching_policy` | 未授权：检查 策略/角色/绑定 是否已下发（见「四、授权」） |
| 403 `x-agentrun-session-id header is required` | 两种场景：① 手工 curl 沙箱未带会话头（技能脚本会自动携带）；② 独占模式下用了基础/`latest-` 域名——必须走会话子域 `<独占id>.<agent名>.<ns>.<域名>` |
| 模型反复调 Skill 而不执行脚本 | 模型工具调用能力不足：换更强模型（`LLM_MODEL`，实测 `qwen3-coder-plus` 可完成单步调用）；技能按需选方法，减小 SKILL.md 体积 |
| 脚本报 `Unknown method` | 方法名与 SKILL.md 不一致，核对生成的技能包 |
| `ToolNotFoundError: unknown` | 模型把 MCP 方法名当本地工具名调用，属模型行为，重试或换模型 |
| 命令执行超时 | allinone 沙箱单次转发上限 600s |

## 文件说明

| 文件 | 说明 |
|------|------|
| `qwenpaw-agent-cr.yaml` | Agent CR 模板（`LLM_API_KEY` 为占位符，使用前替换） |
