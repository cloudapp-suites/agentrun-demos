# Dify + E2B 沙箱集成

将 [Dify](https://dify.ai) 与自建 E2B 兼容沙箱服务集成。通过 Dify 插件机制实现，零修改 Dify 和 sandbox-manager 源码。

> **预备知识**：本文档涉及 Agent Runtime 平台的 ToolServer、sandbox-manager 等概念，请先阅读 [预备知识](../agent-integration-docs/prerequisites.md)。

## 你将学到什么

- 如何开发 Dify Tool 插件并连接自建沙箱服务
- 如何在 Dify Workflow 中调用 E2B 沙箱执行代码
- 如何内嵌 fork 的 E2B Python SDK 以支持自定义 `api_url` / `sandbox_url`
- Dify 插件参数类型（`form: form` vs `form: llm`）在 Workflow 和 Agent 模式下的差异
- 中国网络环境下 Dify plugin-daemon 依赖安装的优化方案

## 代码阅读指引

建议按以下顺序阅读源码：

| 文件 | 关注点 |
|------|--------|
| `plugin/manifest.yaml` | 插件元数据、版本、入口定义 |
| `plugin/provider/e2b_sandbox.yaml` | 凭证字段定义（api_url / sandbox_url / api_key） |
| `plugin/tools/execute_code.yaml` | 工具参数定义，注意 `form: form` 的选择 |
| `plugin/tools/execute_code.py` | 核心实现：参数解析 → 创建沙箱 → 执行代码 → 返回结果 |
| `plugin/provider/e2b_sandbox.py` | 凭证验证逻辑 |
| `plugin/e2b/sandbox_sync/main.py` | 内嵌 E2B SDK 的 Sandbox.create() 入口 |

## 架构

```
Dify (Workflow / Agent)
  └─ E2B Sandbox Plugin (Dify Tool 插件)
       └─ E2B Python SDK (内嵌，支持自定义 api_url)
            ├─ 管控面 → sandbox-manager /e2b/sandboxes (创建/删除沙箱)
            └─ 数据面 → sandbox-manager → envd (执行命令/读写文件)
```

## 目录结构

```
dify-e2b-integration/
├── plugin/                        # Dify 插件源码
│   ├── manifest.yaml              #   插件清单
│   ├── main.py                    #   入口
│   ├── requirements.txt           #   Python 依赖
│   ├── _assets/icon.svg           #   图标
│   ├── provider/                  #   Provider 定义和凭证验证
│   │   ├── e2b_sandbox.yaml
│   │   └── e2b_sandbox.py
│   ├── tools/                     #   5 个工具实现
│   │   ├── execute_code.yaml/.py  #     执行代码（Python/JS/Shell）
│   │   ├── run_command.yaml/.py   #     运行 Shell 命令
│   │   ├── write_file.yaml/.py    #     写文件
│   │   ├── read_file.yaml/.py     #     读文件
│   │   └── list_files.yaml/.py    #     列出文件
│   ├── e2b/                       #   内嵌 E2B Python SDK（支持自定义 api_url）
│   └── e2b_connect/               #   Connect RPC 客户端
├── deploy/                        # 部署辅助
│   ├── e2b-sandbox.difypkg        #   预打包的插件文件
│   ├── install.sh                 #   Dify Helm 部署脚本
│   ├── uninstall.sh               #   Dify 卸载脚本
│   ├── patch-plugin-daemon.sh     #   plugin-daemon uv 镜像 patch
│   └── uv-wrapper.sh              #   uv 镜像替换脚本
├── .env.example                   # 环境变量模板
└── README.md
```

## 快速开始

### 1. 安装插件

**方式 A：使用预打包文件（推荐）**

```bash
# deploy/ 目录下已有预打包文件
ls deploy/e2b-sandbox.difypkg
```

打开 Dify → 插件页面 → 右上角「安装插件」→「上传本地文件」→ 选择 `e2b-sandbox.difypkg`。

**方式 B：从源码打包**

```bash
# 安装 Dify CLI
brew tap langgenius/dify && brew install dify

# 打包
dify plugin package plugin/
# 生成 plugin.difypkg，上传到 Dify 安装
```

### 2. 配置凭证

安装插件后，在 Dify「工具」页面找到 **E2B Sandbox**，点击「授权」，填写 `.env.example` 中的对应值。

### 3. 创建 Workflow 测试

```
[用户输入] → [LLM 生成代码] → [E2B 执行代码] → [输出结果]
```

1. 创建 Workflow，添加 LLM 节点生成 Python 代码
2. 添加「执行代码」工具节点：点击 `{x}` 映射 LLM 节点的 `text` 输出
3. 添加输出节点，映射执行代码节点的 `text` 输出
4. 运行测试

## 环境变量

以下变量在 Dify 插件凭证页面配置（非系统环境变量）：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `SANDBOX_MANAGER_API_URL` | 是 | - | sandbox-manager 的 E2B 兼容 API 地址 |
| `SANDBOX_DATA_PLANE_URL` | 是 | - | sandbox-manager 数据面地址（Connect RPC） |
| `API_KEY` | 是 | - | sandbox-manager 的 `bearer_token` |
| `DEFAULT_TEMPLATE_ID` | 否 | `e2b-sandbox` | 默认沙箱模板名称（即 ToolServer 名称） |

> **获取 API Key**：
> ```bash
> kubectl get configmap sandbox-manager-config -n <namespace> -o yaml | grep bearer_token
> ```

## 工具列表

| 工具 | 说明 | 关键参数 |
|------|------|----------|
| Execute Code | 执行代码，返回 stdout/stderr | `code`, `language` (python/javascript/shell) |
| Run Command | 执行 Shell 命令 | `command` |
| Write File | 向沙箱写入文件 | `path`, `content` |
| Read File | 从沙箱读取文件 | `path` |
| List Files | 列出目录文件 | `path` |

## 测试

安装插件并配置凭证后，在 Dify 中创建一个简单 Workflow 验证：

1. 添加「执行代码」工具节点，代码填 `print("hello from e2b")`，语言选 Python
2. 运行，预期输出 `hello from e2b`
3. 如果报错 `KeyError: 'code'`，检查 API Key 是否正确

## 注意事项

- 所有参数设置为 `form: form` 类型，同时兼容 Workflow 和 Agent 模式
- 每次工具调用创建新沙箱实例；如需共享状态，可组合 Write File → Execute Code
- 所有工具包含 try/except 保护，错误以文本消息返回

## 中国网络环境

Dify plugin-daemon 安装插件依赖时可能因 PyPI 访问慢而超时：

1. 在 plugin-daemon 环境变量中添加 `PIP_INDEX_URL` 和 `UV_INDEX_URL` 指向国内镜像
2. 对于 `uv sync` 类型的插件，使用 `deploy/patch-plugin-daemon.sh` 和 `deploy/uv-wrapper.sh`
