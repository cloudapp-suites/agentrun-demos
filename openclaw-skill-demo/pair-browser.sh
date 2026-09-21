#!/usr/bin/env bash
# 打开 OpenClaw 独占会话，并生成 Control UI 一次性配对链接（Demo 便捷方式）
#
# 流程：
#   1. 交互输入/确认参数（命名空间、Agent 名、独占会话 ID、平台域名）
#   2. 脚本访问会话入口 http://<独占ID>.<agent>.<ns>.<域名>/ ——
#      触发平台为该会话创建/唤起独占 Pod（首次冷启动约 10s）；
#      若域名无法解析，会提示先做域名绑定（/etc/hosts 或 DNS 泛解析）
#   3. 按 label 等待会话 Pod 就绪（serving.knative.dev/contextID=<独占ID>）
#   4. 在 Pod 内执行 `openclaw dashboard --json` 获取一次性配对链接，
#      替换为会话域名后输出：浏览器打开即自动完成设备配对（owner 权限）
#
# ⚠️ 安全提示：链接内嵌一次性 owner 配对凭证（约 10 分钟有效），任何拿到链接的人
#    在有效期内都能以 owner 身份接入 Control UI，请勿外传。更安全的登录方式是
#    「Gateway 令牌 + 人工批准」：
#      kubectl exec -n <ns> <pod> -c <agent> -- openclaw devices approve --latest
#
# 依赖：kubectl、curl、python3（仅用于改写链接中的回环地址）
#
# 用法：
#   ./pair-browser.sh                       # 全交互
#   NS=default SESSION_ID=sess1 ./pair-browser.sh   # 环境变量作为默认值，回车确认即可
set -euo pipefail

die() { echo "✖ $*" >&2; exit 1; }

command -v kubectl >/dev/null || die "未找到 kubectl，请先安装并配置集群访问"
command -v curl >/dev/null || die "未找到 curl"
command -v python3 >/dev/null || die "未找到 python3（仅用于改写配对链接）"

# ── 1. 参数（交互输入/确认）─────────────────────────────────────────────
def_ns="${NS:-default}"
read -r -p "命名空间 [${def_ns}]: " ns; ns="${ns:-$def_ns}"

def_agent="${AGENT:-openclaw-skill-demo}"
read -r -p "Agent 名称 [${def_agent}]: " agent; agent="${agent:-$def_agent}"

sid="${SESSION_ID:-}"
while :; do
  if [ -z "$sid" ]; then
    read -r -p "独占会话 ID（小写字母/数字/连字符，≤63，如 sess1）: " sid
  fi
  if [[ "$sid" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] && [ "${#sid}" -le 63 ]; then
    break
  fi
  echo "✖ 非法会话 ID：${sid}（仅小写字母/数字/连字符，不能以连字符开头/结尾；示例 sess1、team-a-01）"
  sid=""
done

# 域名：从 Agent 状态 URL（http://latest-<agent>.<ns>.<域名>）自动推导，失败则用默认值
domain="${DOMAIN:-}"
if [ -z "$domain" ]; then
  url="$(kubectl get agent "$agent" -n "$ns" -o jsonpath='{.status.url}' 2>/dev/null || true)"
  host_part="${url#*://}"; host_part="${host_part%%/*}"
  prefix="latest-${agent}.${ns}."
  if [[ "$host_part" == "$prefix"* ]]; then
    domain="${host_part#"$prefix"}"
  fi
fi
def_domain="${domain:-agentrun.time}"
read -r -p "平台域名 [${def_domain}]: " domain; domain="${domain:-$def_domain}"

session_host="${sid}.${agent}.${ns}.${domain}"
echo
echo "  命名空间    : ${ns}"
echo "  Agent       : ${agent}"
echo "  独占会话 ID : ${sid}"
echo "  访问入口    : http://${session_host}/"
read -r -p "确认无误？[Y/n] " ok
[[ "${ok:-Y}" =~ ^[Yy]?$ ]] || die "已取消"

container="${CONTAINER:-$agent}"

# ── 2. 访问会话入口（触发独占 Pod 创建/唤起）────────────────────────────
echo "→ 访问会话入口（触发该会话的独占 Pod，首次冷启动约 10s）…"
set +e
curl_out="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 60 "http://${session_host}/" 2>&1)"
curl_rc=$?
set -e
if [ "$curl_rc" -eq 0 ]; then
  # 能收到任意 HTTP 状态码即代表链路可达（401/403 也说明已到网关）
  echo "✓ 会话入口可达（HTTP ${curl_out}）"
elif echo "$curl_out" | grep -qiE 'resolve|nodename|name or service'; then
  cat >&2 <<EOF
✖ 域名无法解析：${session_host}
  独占模式的会话入口是独立子域，需先完成域名绑定：
  - 本地快速验证：在 /etc/hosts 增加一行（IP 与 latest-${agent}.${ns}.${domain} 的解析一致）：
      <网关IP>  ${session_host}
  - 长期使用：让管理员为 *.${domain}（或 *.${agent}.${ns}.${domain}）配置 DNS 泛解析
  - 同时检查：域名拼写、命名空间是否正确
EOF
  exit 1
else
  echo "⚠️  暂时访问不通（curl 退出码 ${curl_rc}：${curl_out}）" >&2
  echo "    继续等待 Pod（冷启动期间访问超时属正常，稍后可用输出的链接再访问）…" >&2
fi

# ── 3. 等待会话 Pod 就绪 ────────────────────────────────────────────────
selector="agentruntime.alibabacloud.com/agent=${agent},serving.knative.dev/contextID=${sid}"
echo "→ 等待会话 Pod 就绪（label: ${selector}）…"
pod=""; ready=""
deadline=$((SECONDS + 240))
while [ "$SECONDS" -lt "$deadline" ]; do
  pod="$(kubectl get pod -n "$ns" -l "$selector" --sort-by=.metadata.creationTimestamp \
    -o jsonpath='{.items[-1:].metadata.name}' 2>/dev/null || true)"
  if [ -n "$pod" ]; then
    ready="$(kubectl get pod "$pod" -n "$ns" \
      -o jsonpath='{range .status.conditions[?(@.type=="Ready")]}{.status}{end}' 2>/dev/null || true)"
    [ "$ready" = "True" ] && break
  fi
  printf '.'; sleep 3
done
printf '\n'
if [ -z "$pod" ] || [ "${ready:-}" != "True" ]; then
  echo "✖ 等待超时：未找到就绪的会话 Pod（selector: ${selector}）" >&2
  echo "  排查: kubectl get pods -n ${ns} -l ${selector}" >&2
  echo "        kubectl describe pod -n ${ns} <pod>" >&2
  exit 1
fi
echo "✓ 会话 Pod 就绪: ${pod}"

# ── 4. 生成一次性配对链接 ──────────────────────────────────────────────
echo "→ 生成 Control UI 一次性配对链接…"
json="$(kubectl exec -n "$ns" "$pod" -c "$container" -- openclaw dashboard --json)"
link="$(python3 - "$json" "$session_host" <<'PY'
import json
import sys
import urllib.parse

raw, host = sys.argv[1], sys.argv[2]
try:
    browser_url = json.loads(raw)["browserUrl"]
except Exception:
    sys.exit("解析 dashboard 输出失败：\n" + raw)
browser_url = browser_url.replace("http://127.0.0.1:18789", f"http://{host}", 1)
browser_url = browser_url.replace(
    urllib.parse.quote("ws://127.0.0.1:18789", safe=""),
    urllib.parse.quote(f"ws://{host}", safe=""),
)
print(browser_url)
PY
)"

cat <<EOF

══════════════════════════════════════════════════════════════════
在浏览器打开（建议新标签页，约 10 分钟内有效）：

  ${link}

打开后自动以 owner 身份完成设备配对，无需再输入 Gateway 令牌。
使用要点：
  - 保持会话 ID「${sid}」不变：技能、设备配对等都是该会话 Pod 的本地状态
  - 会话空闲回收（缩零保留 30 分钟）后，Pod 销毁状态即丢失，需重新配对/重装技能
  - 链接含一次性配对凭证，请勿外传；更安全方式见脚本头部注释
══════════════════════════════════════════════════════════════════
EOF
