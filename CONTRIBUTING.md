# Demo 编写指引

本文档为 agentrun-demos 仓库的 demo 编写规范，确保风格统一、可直接运行、无敏感信息。

---

## 1. 目录命名

使用小写字母 + 横线（kebab-case），如 `agentscope-mcp`、`react-with-sandbox-by-native-mcp`。

---

## 2. README.md 结构

每个 demo 必须包含 `README.md`，推荐章节顺序：

| 章节 | 必选 | 说明 |
|------|------|------|
| 标题 + 一句话描述 | ✅ | 说明这个 demo 做什么 |
| 你将学到什么 | 推荐 | 列出 3-5 个学习点 |
| 代码阅读指引 | 推荐 | 按推荐顺序列出源文件及重点关注内容 |
| 目录结构 | ✅ | 代码块展示文件树 |
| 快速开始 | ✅ | 安装依赖 → 配置 → 启动，可复制粘贴直接运行 |
| 环境变量 | ✅ | 表格：变量名、必填、默认值、说明 |
| Docker 部署 | 按需 | 构建镜像 + 运行命令 |
| 打包上传部署 | 按需 | 引用 pack-tools |
| 测试 | 推荐 | 如何验证 demo 正常工作 |

---

## 3. 环境变量

- 代码中只通过 `os.environ.get()` 或命令行参数读取配置，**禁止硬编码密钥**
- 提供 `.env.example` 模板，密钥类使用占位符（`sk-your-api-key`、`your-token`），非敏感默认值直接写实际值
- `.env` 已在 `.gitignore` 中排除

---

## 4. 依赖版本

- **Python（requirements.txt）**：所有依赖使用 `==` 固定版本，如 `agentscope==1.0.13`
- **Node.js（package.json）**：使用 `^` 范围版本，并将 `package-lock.json` 一并入库

---

## 5. 敏感信息

### 禁止出现

- 真实的 API Key、Token、密码
- 个人信息（用户名、工号、邮箱）
- 内部测试实例名、内部命名空间

### 自查命令

```bash
grep -rnE '(sk-[a-zA-Z0-9]{20,}|password\s*=\s*\S+|secret\s*=)' .
```

---

## 6. 镜像地址

- **Dockerfile FROM 基础镜像**：使用 `apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/` 下的镜像
- **构建脚本 DEFAULT_REGISTRY**：使用占位符 `registry.example.com/your-namespace`，支持 `-r` 参数覆盖
- **DashScope API / 阿里云 pip 镜像**：公开服务，可直接使用

---

## 7. 集成文档联动

新 demo 如对应 `agent-integration-docs/` 下的某篇文档，在该文档末尾添加：

```markdown
## 完整 Demo

- [demo-name](https://github.com/cloudapp-suites/agentrun-demos/tree/main/demo-name) — 一句话说明
```

Python / Node.js 代码类 demo 追加打包部署引用（框架集成类默认走镜像模式，不添加）：

```markdown
## 打包部署

如需将应用打包为离线压缩包通过管控台上传部署，请参考 [pack-tools](https://github.com/cloudapp-suites/agentrun-demos/tree/main/pack-tools)。
```

---

## 8. 提交前检查清单

- [ ] 目录名为 kebab-case
- [ ] README.md 包含：标题、目录结构、快速开始、环境变量表格
- [ ] 提供 `.env.example`（如需环境变量）
- [ ] 无硬编码密钥、Token、密码、个人信息
- [ ] 镜像地址符合规范
- [ ] 根 `README.md` 的 Demo 索引已更新
