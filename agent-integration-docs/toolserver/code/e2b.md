# E2B 沙箱集成文档

平台提供 E2B 兼容的沙箱服务，每个沙箱是独立的 K8s Pod，支持代码执行、文件操作和进程管理。

> 如需了解 Claw 类 Agent 框架（OpenClaw、QwenPaw 等）如何通过技能调用沙箱，请参阅 claw-skill-integration.md。

---

## 1. 使用平台 E2B 沙箱

E2B SDK 默认连接官方云服务，通过环境变量即可切换到平台自建服务：

```bash
export E2B_API_URL=http://<sandbox-manager-address>/e2b      # 管控面（沙箱 CRUD）
export E2B_SANDBOX_URL=http://<sandbox-manager-address>       # 数据面（代码执行、文件操作）
export E2B_API_KEY=<调用方自身凭证：外部身份 API Key（art_ak_...）>
```

> - 域名从控制台「集群详情」页面获取，管控面和数据面必须同时配置。
> - `E2B_API_KEY` 为**调用方自身**的身份凭证：在「访问控制 → 身份管理 → 外部身份」注册身份（API Key 模式）获得，且该身份需已被授予沙箱服务的访问权限，详见「访问凭证」文档。

### Python

```bash
# 建议固定使用 2.46.0 及以上版本
pip install "e2b==2.46.0"
```

> **版本说明**：`> 2.13.0 && <= 2.45.0` 的版本会在客户端强制校验 API Key 格式，
> 导致 `art_ak_...` 格式的凭证报格式错误；2.46.0 起该校验已移除，请勿使用上述区间版本。

```python
from e2b import Sandbox

# 推荐使用 Sandbox.create 创建沙箱（自动清理请配合 with 语句）
sandbox = Sandbox.create(template="e2b-sandbox")

result = sandbox.commands.run("echo 'Hello from sandbox!'")
print(result.stdout)

sandbox.files.write("/home/user/test.txt", "hello world")
print(sandbox.files.read("/home/user/test.txt"))

sandbox.kill()
```

> **协议建议**：请使用 `http://` 访问（见上文环境变量示例），不要使用 `https://`。
> 平台沙箱服务使用自签证书，SDK 校验会失败，错误日志关键字：
>
> - e2b 2.13.0（httpx/httpcore 实现）：`[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate`
> - e2b 2.46.0（pyqwest 实现）：`invalid peer certificate: ... 证书不受信任`
>
> 各版本的 TLS 校验实现差异很大（httpx 时代可 patch `ssl.create_default_context`，
> pyqwest 时代需导出证书注入 `tls_ca_cert`，且 SDK 未暴露相关参数），
> 绕过的实现过于复杂且随版本漂移，因此建议直接使用 http。

### JavaScript

```bash
# 建议固定使用 2.46.0 及以上版本
npm install "e2b@2.46.0"
```

> **版本说明**：与 Python 版一致，`> 2.13.0 && <= 2.45.0` 的版本会在客户端强制校验 API Key 格式，
> 导致 `art_ak_...` 格式的凭证报格式错误；2.46.0 起该校验已移除，请勿使用上述区间版本。

```javascript
import { Sandbox } from 'e2b';

const sandbox = await Sandbox.create({ template: 'e2b-sandbox' });

const result = await sandbox.commands.run('echo "Hello from sandbox!"');
console.log(result.stdout);

await sandbox.files.write('/home/user/test.txt', 'hello world');
console.log(await sandbox.files.read('/home/user/test.txt'));

await sandbox.kill();
```

> SDK 会自动读取上述环境变量，代码中无需重复指定地址。

---

## 2. 环境变量速查

| 变量 | 说明                                                                       |
|------|--------------------------------------------------------------------------|
| `E2B_API_URL` | 管控面地址（集群详情页获取）                                                    |
| `E2B_SANDBOX_URL` | 数据面地址（集群详情页获取） |
| `E2B_API_KEY` | 调用方自身凭证：外部身份 API Key（art_ak_），「访问控制 → 身份管理」注册获得 |
