# OpenClaw × 平台沙箱（技能方式集成）镜像
#
# 基于 OpenClaw 官方镜像（v2026.9.5）的薄包装：仅追加 entrypoint，启动时从
# 环境变量生成 openclaw.json（LLM Provider / 默认模型 / Gateway bind+token），
# 然后启动 Gateway。沙箱能力由「技能」提供，不修改 OpenClaw 本体。
#
# 国内构建网络不便时，可先镜像官方镜像再覆盖 base：
#   --build-arg OPENCLAW_BASE=<你的镜像仓库>/openclaw:2026.9.5

ARG OPENCLAW_BASE=ghcr.io/openclaw/openclaw:2026.9.5
FROM ${OPENCLAW_BASE}

# 平台生成的技能包依赖 python3 + MCP SDK（官方 OpenClaw 镜像未内置）
# 固定 mcp==1.29.0：与 QwenPaw 镜像一致，保留技能脚本使用的
# `streamablehttp_client` 兼容名（mcp 2.x 已移除）
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
USER root
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-pip \
  && pip3 install --no-cache-dir --break-system-packages -i ${PIP_INDEX} "mcp==1.29.0" \
  && rm -rf /var/lib/apt/lists/*
USER node

COPY --chmod=755 entrypoint.sh /entrypoint.sh

ENTRYPOINT ["tini", "-s", "--", "/entrypoint.sh"]
