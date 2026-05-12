#!/bin/bash
# Patch plugin-daemon deployment to fix uv.lock PyPI URLs for China
# Strategy: wrap uv binary to auto-replace PyPI URLs with Aliyun mirror before uv sync

KUBECONFIG=${KUBECONFIG:-kubeconfig.txt}

# The wrapper script that replaces uv:
# 1. Before "uv sync", replace files.pythonhosted.org in uv.lock with Aliyun mirror
# 2. Then call the real uv binary
# This ensures uv sync downloads from Aliyun mirror instead of PyPI

kubectl --kubeconfig=$KUBECONFIG patch deployment dify-plugin-daemon -n dify --type='json' -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/containers/0/command",
    "value": ["/bin/bash", "-c"]
  },
  {
    "op": "add",
    "path": "/spec/template/spec/containers/0/args",
    "value": [
      "cp /usr/local/bin/uv /usr/local/bin/uv.real && cat > /usr/local/bin/uv << '\''WRAPPER'\''\n#!/bin/bash\n# Auto-patch uv.lock before uv sync\nif [[ \"$1\" == \"sync\" ]]; then\n  if [ -f uv.lock ]; then\n    sed -i \"s|https://files.pythonhosted.org/packages/|https://mirrors.aliyun.com/pypi/packages/|g\" uv.lock\n    echo \"[uv-wrapper] Patched uv.lock to use Aliyun mirror\"\n  fi\nfi\nexec /usr/local/bin/uv.real \"$@\"\nWRAPPER\nchmod +x /usr/local/bin/uv && mkdir -p /root/.config/uv && echo '\''index-url = \"https://mirrors.aliyun.com/pypi/simple/\"'\\'' > /root/.config/uv/uv.toml && exec /app/main"
    ]
  }
]'

echo "Patched. Plugin-daemon pod will restart automatically."
