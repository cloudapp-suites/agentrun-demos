#!/bin/bash
# Auto-patch uv.lock before uv sync to use Aliyun mirror
if [[ "$1" == "sync" ]]; then
  if [ -f uv.lock ]; then
    sed -i 's|https://files.pythonhosted.org/packages/|https://mirrors.aliyun.com/pypi/packages/|g' uv.lock
    echo "[uv-wrapper] Patched uv.lock to use Aliyun mirror"
  fi
fi
exec /usr/local/bin/uv.real "$@"
