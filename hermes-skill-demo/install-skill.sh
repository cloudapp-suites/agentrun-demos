#!/usr/bin/env bash
# 将控制台生成的沙箱技能包安装到 Hermes 独占会话（Demo 便捷方式）
#
# 流程：
#   1. 交互输入/确认参数（命名空间、Agent 名、独占会话 ID、平台域名、技能包路径）
#   2. 访问会话入口 http://<独占ID>.<agent>.<ns>.<域名>/ —— 触发该会话的独占 Pod
#      创建/唤起（首次冷启动约 10s）；若域名无法解析，会提示先做域名绑定
#   3. 按 label 等待会话 Pod 就绪（serving.knative.dev/contextID=<独占ID>）
#   4. 把技能包（zip 或解压后的目录）复制到 Pod 内技能目录
#      （$HERMES_HOME/skills = /opt/data/skills/<技能名>/，放入即被索引），
#      修正属主后执行 `hermes skills list` 验证
#
# 说明：
#   - 技能包（zip：SKILL.md + scripts/invoke.py）从控制台「工具 → 生成技能」下载，
#     本仓库不内置；技能名优先取 SKILL.md frontmatter 的 name 字段
#   - 技能是会话 Pod 的本地状态：空闲缩零回收（30 分钟）后 Pod 销毁，需重新安装
#
# 依赖：kubectl、curl、python3（解压 zip / 解析技能名）
#
# 用法：
#   ./install-skill.sh                                            # 全交互
#   SKILL_PKG=./my-sandbox-skill.zip SESSION_ID=sess1 ./install-skill.sh
set -euo pipefail

die() { echo "✖ $*" >&2; exit 1; }

command -v kubectl >/dev/null || die "未找到 kubectl，请先安装并配置集群访问"
command -v curl >/dev/null || die "未找到 curl"
command -v python3 >/dev/null || die "未找到 python3（用于解压技能包并解析技能名）"

# ── 1. 参数（交互输入/确认）─────────────────────────────────────────────
def_ns="${NS:-default}"
read -r -p "命名空间 [${def_ns}]: " ns; ns="${ns:-$def_ns}"

def_agent="${AGENT:-hermes-skill-demo}"
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

pkg="${SKILL_PKG:-}"
while :; do
  pkg="${pkg/#\~/$HOME}"
  if [ -z "$pkg" ]; then
    read -r -p "技能包路径（控制台下载的 zip 或解压后的技能目录）: " pkg
    continue
  fi
  [ -e "$pkg" ] && break
  echo "✖ 路径不存在：$pkg"
  pkg=""
done

session_host="${sid}.${agent}.${ns}.${domain}"
echo
echo "  命名空间    : ${ns}"
echo "  Agent       : ${agent}"
echo "  独占会话 ID : ${sid}"
echo "  访问入口    : http://${session_host}/"
echo "  技能包      : ${pkg}"
read -r -p "确认无误？[Y/n] " ok
[[ "${ok:-Y}" =~ ^[Yy]?$ ]] || die "已取消"

container="${CONTAINER:-$agent}"

# ── 2. 解压技能包并解析技能目录/技能名 ─────────────────────────────────
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

if ! IFS=$'\t' read -r skill_src skill_name < <(python3 - "$pkg" "$tmpdir" <<'PY'
import os
import re
import sys
import zipfile

pkg, tmpdir = sys.argv[1], sys.argv[2]

if os.path.isdir(pkg):
    root = pkg
else:
    dest = os.path.join(tmpdir, "pkg")
    with zipfile.ZipFile(pkg) as z:
        z.extractall(dest)
    # 技能根目录：SKILL.md 在 zip 根，或在唯一一层子目录中
    root = None
    if os.path.isfile(os.path.join(dest, "SKILL.md")):
        root = dest
    else:
        for entry in sorted(os.listdir(dest)):
            sub = os.path.join(dest, entry)
            if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "SKILL.md")):
                root = sub
                break
    if root is None:
        sys.exit("技能包内未找到 SKILL.md，请确认是控制台「生成技能」下载的 zip")

if not os.path.isfile(os.path.join(root, "SKILL.md")):
    sys.exit("目录内未找到 SKILL.md：" + root)

name = ""
with open(os.path.join(root, "SKILL.md"), encoding="utf-8") as f:
    head = f.read(4096)
m = re.search(r"^---\s*\n(.*?)\n---", head, re.S)
if m:
    nm = re.search(r"^name:\s*[\"']?([A-Za-z0-9][A-Za-z0-9._-]*)", m.group(1), re.M)
    if nm:
        name = nm.group(1)


def safe(s):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-._")
    return s or "skill"


print(f"{os.path.abspath(root)}\t{safe(name or os.path.basename(os.path.abspath(root.rstrip('/'))))}")
PY
); then
  die "解析技能包失败（请查看上方错误信息）"
fi
[ -n "${skill_src:-}" ] && [ -n "${skill_name:-}" ] || die "解析技能包失败：无法确定技能目录或技能名"
echo "✓ 技能：${skill_name}（本地目录 ${skill_src}）"

# ── 3. 访问会话入口（触发独占 Pod 创建/唤起）并等待就绪 ─────────────────
echo "→ 访问会话入口（触发该会话的独占 Pod，首次冷启动约 10s）…"
set +e
curl_out="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 60 "http://${session_host}/" 2>&1)"
curl_rc=$?
set -e
if [ "$curl_rc" -eq 0 ]; then
  # 能收到任意 HTTP 状态码即代表链路可达（401 也说明已到 Dashboard 登录页）
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
  echo "    继续等待 Pod（冷启动期间访问超时属正常）…" >&2
fi

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

# ── 4. 复制技能包到 Pod 并验证 ──────────────────────────────────────────
echo "→ 复制技能包到 ${pod}:/opt/data/skills/${skill_name}/ …"
kubectl exec -n "$ns" "$pod" -c "$container" -- sh -c \
  "mkdir -p /opt/data/skills && rm -rf '/opt/data/skills/${skill_name}'"
kubectl cp -n "$ns" -c "$container" "$skill_src" "$pod:/opt/data/skills/${skill_name}"
kubectl exec -n "$ns" "$pod" -c "$container" -- sh -c \
  "chown -R hermes:hermes '/opt/data/skills/${skill_name}' 2>/dev/null || true"

echo "→ 验证（hermes skills list）…"
set +e
list_out="$(kubectl exec -n "$ns" "$pod" -c "$container" -- hermes skills list 2>&1)"
list_rc=$?
set -e
if [ "$list_rc" -eq 0 ] && echo "$list_out" | grep -Fq "$skill_name"; then
  echo "✓ 技能已安装: ${skill_name}"
else
  echo "⚠️  未在技能列表中匹配到 ${skill_name}，完整输出如下（请人工确认）："
  echo "$list_out"
fi

cat <<EOF

══════════════════════════════════════════════════════════════════
技能已放入会话 Pod。使用要点：
  - 打开 Dashboard 发消息：http://${session_host}/
  - 新建对话后生效（技能索引随会话创建；进行中的会话不会重载）
  - 提示词示例：请使用 ${skill_name} 技能完成 <你的任务>
  - 若为平台沙箱技能（含 scripts/invoke.py）：让它「在平台沙箱中执行 shell 命令 hostname」，
    期望输出的是沙箱 Pod 名（如 allinone-0920-ephemeral-*），不是 Agent 容器
  - 技能是会话 Pod 的本地状态：保持会话 ID「${sid}」不变可复用；
    空闲缩零回收（30 分钟）后 Pod 销毁，需重新执行本脚本安装
══════════════════════════════════════════════════════════════════
EOF
