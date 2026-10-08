# Hermes × 平台沙箱（技能方式集成）镜像
#
# 基于 Hermes 官方镜像（v2026.9.24，nousresearch/hermes-agent）的薄包装：
#   1) 追加「技能脚本运行时」（独立 venv：python3 + mcp==1.29.0）——平台生成的
#      技能包内 scripts/invoke.py 依赖 MCP Python SDK 的 streamablehttp_client
#      兼容名（mcp 2.x 已移除）；独立运行时保证技能脚本的依赖版本，且不与
#      Agent 自身运行环境相互影响
#   2) 追加 entrypoint：从环境变量生成 $HERMES_HOME/config.yaml（LLM Provider /
#      默认模型），再交给官方入口（s6-overlay）以 `gateway run` 启动
#      （Dashboard 9119 + API Server 8642 由 s6 托管）
#
# 国内构建网络不便时，可先镜像官方镜像再覆盖 base：
#   --build-arg HERMES_BASE=<你的镜像仓库>/hermes-agent:v2026.9.24

ARG HERMES_BASE=nousresearch/hermes-agent:v2026.9.24
FROM ${HERMES_BASE}

# 技能脚本运行时：独立 venv，不改动 Hermes 自身运行环境
ARG PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/
USER root
RUN /usr/bin/python3 -m venv /opt/skill-runtime \
  && /opt/skill-runtime/bin/pip install --no-cache-dir -i ${PIP_INDEX} "mcp==1.29.0"

# Agent 终端内 python3 的解析顺序：
#   /opt/hermes/bin（hermes 命令）→ /opt/skill-runtime/bin（技能脚本运行时）→ /opt/hermes/.venv/bin
ENV PATH="/opt/hermes/bin:/opt/skill-runtime/bin:${PATH}"

COPY --chmod=755 entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
