# Code Execution MCP Server

基于 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 的多语言代码执行服务，支持 **streamable HTTP** 协议。

> ⚠️ 这是一个教学 Demo，非生产级代码执行服务。如需生产使用，请在沙箱环境中运行并加访问控制。

## Quick Start

```bash
# 安装依赖
npm install

# 启动服务（开发模式，tsx 直接运行无需构建）
npm run dev
```

### 测试客户端

`example_client.py` 是一个基于 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 的示例客户端，依次调用 `execute_code` 工具执行 Python / JavaScript / TypeScript / Shell / Java 代码。

```bash
# 安装 MCP Python SDK
pip install mcp

# 连接本地服务（默认 http://localhost:80/mcp）
python example_client.py

# 指定 endpoint
python example_client.py --endpoint http://localhost:80/mcp

# 指定 endpoint + token
python example_client.py --endpoint https://mcp.example.com/mcp --token <bearer-token>

# 指定 session-id（默认自动生成 UUID）
python example_client.py --endpoint https://mcp.example.com/mcp --token <bearer-token> --session-id <uuid>
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--endpoint` | MCP 服务地址 | `$MCP_URL` 或 `http://localhost:80/mcp` |
| `--token` | Bearer Token，附加到 `Authorization` 请求头 | 无 |
| `--session-id` | `x-agentrun-session-id` 请求头的值 | 自动生成 UUID |

## 你将学到什么

通过阅读和运行本 Demo，你可以了解：

- 如何用 TypeScript 实现一个符合 MCP 协议的 Tool Server（streamable HTTP 传输）
- 如何设计多语言代码执行引擎（Python / JavaScript / TypeScript / Java / Shell）
- 如何通过 `hooks.js` 实现 pre/post hook 模式，在不修改核心代码的情况下扩展行为
- 如何处理子进程的超时控制、stdout/stderr 捕获与退出码

## 代码阅读指引

建议按以下顺序阅读源码：

1. **`src/index.ts`** — MCP 服务入口，重点关注：
   - MCP Server 的初始化与 tool 注册
   - streamable HTTP 传输层的配置
   - `execute_code` tool handler 的实现：参数校验 → pre_hook → 执行 → post_hook → 返回
2. **`src/executor.ts`** — 多语言执行引擎，重点关注：
   - 不同语言的临时文件创建与命令构造策略
   - 子进程超时控制与资源清理
3. **`hooks.js`** — 用户自定义钩子，了解 pre/post hook 的调用时机与参数结构

---

提供 `execute_code` 工具，支持以下编程语言：

| 语言 | 运行时 |
|------|--------|
| Python | `python3` |
| JavaScript | `node` |
| TypeScript | `tsx` |
| Java | `javac` + `java` |
| Shell | `bash` |

---

## 目录结构

```
code-execution-mcp/
├── src/
│   ├── index.ts        # MCP 服务主入口（streamable HTTP）
│   └── executor.ts     # 多语言代码执行引擎
├── hooks.js            # 用户自定义 Hook（调试入口，直接编辑无需重建）
├── example_client.py   # Python 示例客户端（MCP SDK）
├── package.json
├── tsconfig.json
├── Dockerfile
└── build_image.sh      # 多架构镜像构建脚本
```

---

## 调试与定制：hooks.js

`hooks.js` 是为调试和演示预留的入口，无需重新构建即可修改生效。

```js
// hooks.js

// pre_hook：代码执行前调用，可修改/拦截执行上下文
export async function pre_hook(ctx) {
  // ctx: { language, code, timeout }
  console.error(`[pre_hook] language=${ctx.language}`);
  return ctx;
}

// post_hook：代码执行后调用，可修改/记录结果
export async function post_hook(ctx, result) {
  // result: { stdout, stderr, exitCode, executionTimeMs }
  console.error(`[post_hook] exitCode=${result.exitCode}`);
  return result;
}
```

**使用场景示例：**

```js
// 禁止 Shell 执行
export async function pre_hook(ctx) {
  if (ctx.language === 'shell') {
    throw new Error('Shell execution is disabled.');
  }
  return ctx;
}

// 记录慢执行
export async function post_hook(ctx, result) {
  if (result.executionTimeMs > 5000) {
    console.error(`[warn] Slow execution: ${result.executionTimeMs}ms`);
  }
  return result;
}
```

修改 `hooks.js` 后重启服务即可生效。如通过平台部署，点击保存触发重启。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址 |
| `PORT` | `80` | 监听端口 |
| `EXECUTION_TIMEOUT` | `30` | 单次执行默认超时（秒） |
| `MAX_EXECUTION_TIMEOUT` | `120` | 允许的最大超时（秒） |

---

## Docker 部署

### 构建与运行

```bash
# 构建 TypeScript
npm run build

# 直接运行构建产物
npm start
```

### 构建镜像

```bash
# 构建并推送多架构镜像（amd64 + arm64）
chmod +x build_image.sh
./build_image.sh

# 指定 tag
./build_image.sh -t v1.0.0

# 指定仓库
./build_image.sh -r registry.example.com/myns -n code-exec-mcp -t v1.0.0
```

### 运行

```bash
docker run -d --name code-exec-mcp \
  -p 80:80 \
  registry.example.com/myns/code-exec-mcp:latest
```

### 挂载自定义 hooks.js

```bash
docker run -d --name code-exec-mcp \
  -p 80:80 \
  -v $(pwd)/hooks.js:/app/hooks.js:ro \
  registry.example.com/myns/code-exec-mcp:latest
```

---

## MCP 工具说明

### `execute_code`

执行代码并返回输出。

**输入参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `language` | enum | 是 | `python` / `javascript` / `typescript` / `java` / `shell` |
| `code` | string | 是 | 待执行的代码 |
| `timeout` | number | 否 | 超时秒数（默认 30，最大 120） |

**Java 说明：** 需定义 `public class Main`，包含 `public static void main(String[] args)` 方法。

**返回：**

```
=== stdout ===
Hello, World!

=== stderr ===
（空）

=== summary ===
exit_code: 0
execution_time: 123ms
```

## MCP 客户端配置

服务启动后，MCP 接入地址为：

```
http://<host>:<port>/mcp
```

在 MCP 客户端（如 AgentScope）中配置：

```python
MCPServerConfig(
    name="code-execution",
    url="http://localhost:80/mcp",
    transport="streamable_http",
)
```

---

## 注意事项

- Java 执行需在运行环境中安装 JDK（Docker 镜像已包含 `default-jdk-headless`）。
- TypeScript 执行通过项目内置的 `tsx` 完成，无需额外安装。

---

## 平台部署

### 打包模式

1. 运行打包工具，运行时选择 **Node.js 20**：
   ```bash
   ../pack-tools/pack-nodejs.sh -s .
   ```
2. 在管控台创建 ToolServer，选择「上传压缩包」，上传生成的 `.tar.gz`
3. 启动命令：`sh start.sh`
4. HTTP 端口：`80`
5. 健康检查：`/health`
