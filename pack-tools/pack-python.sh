#!/bin/sh
# 以 sh 调用时自动切换到完整 bash 执行（脚本使用了 bash 特有语法）
# 情况1: 真正的 sh/dash（无 BASH_VERSION），直接 exec bash
[ -z "${BASH_VERSION:-}" ] && exec bash "$0" "$@"
# 情况2: macOS /bin/sh = bash POSIX 模式（BASH_VERSION 有值但禁止了进程替换），也需重新 exec
# shellcheck disable=SC3010
[[ -o posix ]] && exec bash "$0" "$@"
# =============================================================================
# pack-python.sh — 通用 Python 应用离线打包脚本（Docker 构建 Linux 依赖）
#
# 原理：
#   用 Docker 在目标 Linux 平台的容器内执行 pip install，确保所有 C 扩展
#   二进制文件（numpy、grpcio 等）与目标系统原生兼容，再将源代码 + lib/
#   一起打包为 tar.gz，解压后可直接离线运行。
#
# 支持的依赖管理方式（自动检测）：
#   requirements.txt        → pip install -r requirements.txt
#   pyproject.toml (通用)   → pip install .
#   pyproject.toml (Poetry) → pip install .（pip 读取 PEP 517 元数据）
#   pyproject.toml (uv)     → pip install .（pip 读取 PEP 517 元数据）
#   setup.py / setup.cfg    → pip install .
#
# 环境要求：
#   - Docker Desktop（必须）
#   - macOS / Linux：直接运行
#   - Windows：请在 Git Bash 或 WSL2 终端中执行，不支持 CMD / PowerShell
#
# 用法：
#   ./pack-python.sh [选项]
#
# 选项：
#   -s DIR   源代码目录（必填）
#   -o DIR   输出目录（默认：<src>/../）
#   -e CMD   Python 启动方式，支持两种格式（默认：app.py）：
#              主文件:   app.py            → python app.py
#              模块启动: -m uvicorn app:main → python -m uvicorn app:main
#   -a ARCH  目标架构 amd64|arm64（默认：amd64；可用 TARGET_ARCH 环境变量）
#   -h       显示帮助信息
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 打包说明（运行时展示）
# ---------------------------------------------------------------------------
cat << 'INTRO'
╔══════════════════════════════════════════════════════════════════════════════╗
║                    pack-python.sh  打包说明                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  目标：打出一个可在云上 Linux 环境直接运行的离线包，包含全部依赖，           ║
║        部署时无需联网下载任何内容。                                          ║
║                                                                              ║
║  为什么需要 Docker：                                                         ║
║    Python 的 C 扩展（numpy、grpcio 等）是平台相关的二进制文件。             ║
║    在 macOS 上 pip install 得到的是 macOS 格式，无法在 Linux 上运行。        ║
║    通过 Docker 在目标 Linux 平台容器内执行 pip install，                     ║
║    可确保下载到与云上环境兼容的 Linux 原生二进制。                           ║
║                                                                              ║
║  包内容：源码 + lib/（全部依赖）                                             ║
║  启动方式：./start.sh，自动将 lib/ 加入 PYTHONPATH，无需任何额外安装。       ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
INTRO

# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR=""
OUTPUT_DIR=""
ENTRY_CMD="app.py"
TARGET_ARCH="${TARGET_ARCH:-amd64}"

# ---------------------------------------------------------------------------
# 解析选项
# ---------------------------------------------------------------------------
usage() {
    sed -n '/^# 用法/,/^# ====/p' "$0" | grep -v '^# ====' | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -s) SRC_DIR="$(cd "$2" && pwd)"; shift 2 ;;
        -o) OUTPUT_DIR="$2";             shift 2 ;;
        -e) ENTRY_CMD="$2";              shift 2 ;;
        -a) TARGET_ARCH="$2";            shift 2 ;;
        -h|--help) usage ;;
        *) echo "未知选项: $1（-h 查看帮助）"; exit 1 ;;
    esac
done

if [[ -z "${SRC_DIR}" ]]; then
    echo "错误: 请用 -s DIR 指定 Python 项目目录（-h 查看帮助）"
    exit 1
fi

# ---------------------------------------------------------------------------
# 推导固定变量
# ---------------------------------------------------------------------------
APP_NAME="$(basename "${SRC_DIR}")"
OUTPUT_DIR="${OUTPUT_DIR:-"${SRC_DIR}/.."}"
OUTPUT_DIR="$(cd "${OUTPUT_DIR}" && pwd)"

case "${TARGET_ARCH}" in
    amd64|x86_64)  DOCKER_PLATFORM="linux/amd64" ;;
    arm64|aarch64) DOCKER_PLATFORM="linux/arm64" ;;
    *)
        echo "错误: 不支持的目标架构 '${TARGET_ARCH}'，请使用 amd64 或 arm64"
        exit 1
        ;;
esac

TIMESTAMP="$(date +%Y%m%d%H%M%S)"
PACKAGE_NAME="${APP_NAME}-${TIMESTAMP}"
TMP_DIR="/tmp/${PACKAGE_NAME}"
APP_DIR="${TMP_DIR}/${APP_NAME}"
OUTPUT_FILE="${OUTPUT_DIR}/${PACKAGE_NAME}.tar.gz"

# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    echo "错误: 未检测到 docker 命令，请先安装并启动 Docker Desktop。"; exit 1
fi

# ---------------------------------------------------------------------------
# 自动检测依赖管理方式
# ---------------------------------------------------------------------------
_detect_dep_type() {
    local src="$1"
    local has_req=false
    local has_pyproject=false
    local has_setup=false
    local pyproject_tool=""

    [[ -f "${src}/requirements.txt" ]] && has_req=true
    [[ -f "${src}/setup.py" || -f "${src}/setup.cfg" ]] && has_setup=true

    if [[ -f "${src}/pyproject.toml" ]]; then
        has_pyproject=true
        if grep -q '\[tool\.poetry\]' "${src}/pyproject.toml" 2>/dev/null; then
            pyproject_tool="Poetry"
        elif [[ -f "${src}/uv.lock" ]] || grep -q '\[tool\.uv\]' "${src}/pyproject.toml" 2>/dev/null; then
            pyproject_tool="uv"
        else
            pyproject_tool="通用"
        fi
    fi

    # 输出检测结果：类型描述 | 建议安装命令
    if ${has_req} && ${has_pyproject}; then
        echo "requirements.txt + pyproject.toml (${pyproject_tool})|AMBIGUOUS"
    elif ${has_req}; then
        echo "requirements.txt|pip install --target /target --no-cache-dir -r /src/requirements.txt"
    elif ${has_pyproject}; then
        echo "pyproject.toml (${pyproject_tool})|pip install --target /target --no-cache-dir /src"
    elif ${has_setup}; then
        echo "setup.py / setup.cfg|pip install --target /target --no-cache-dir /src"
    else
        echo "未检测到依赖配置文件|NONE"
    fi
}

DETECT_RESULT="$(_detect_dep_type "${SRC_DIR}")"
DETECT_TYPE="${DETECT_RESULT%%|*}"
DETECT_CMD="${DETECT_RESULT##*|}"

echo "=================================================="
echo "  通用 Python 应用打包"
echo "  包名:     ${APP_NAME}"
echo "  源目录:   ${SRC_DIR}"
echo "  启动方式: python ${ENTRY_CMD}"
echo "  目标平台: ${DOCKER_PLATFORM}"
echo "  输出文件: ${OUTPUT_FILE}"
echo "=================================================="

# ---------------------------------------------------------------------------
# 交互 1：确认 / 修改依赖安装方式
# ---------------------------------------------------------------------------
echo ""
echo "── 依赖安装方式 ────────────────────────────────────"
echo "  检测到: ${DETECT_TYPE}"
echo ""
echo "  容器内路径说明："
echo "    /src    → 源代码目录（只读挂载）"
echo "    /target → 依赖安装目标目录（即包内 lib/）"
echo ""

if [[ "${DETECT_CMD}" == "AMBIGUOUS" ]]; then
    # requirements.txt 和 pyproject.toml 同时存在，让用户选择
    echo "  同时检测到 requirements.txt 和 pyproject.toml，请选择安装方式："
    echo "  1) pip install -r /src/requirements.txt  （使用 requirements.txt）"
    echo "  2) pip install /src                      （使用 pyproject.toml）"
    echo "────────────────────────────────────────────────────"
    printf "请选择 [1/2]（默认 1）: "
    read -r user_dep_choice
    case "${user_dep_choice}" in
        2) DEFAULT_INSTALL_CMD="pip install --target /target --no-cache-dir /src" ;;
        *) DEFAULT_INSTALL_CMD="pip install --target /target --no-cache-dir -r /src/requirements.txt" ;;
    esac
elif [[ "${DETECT_CMD}" == "NONE" ]]; then
    echo "  未检测到 requirements.txt / pyproject.toml / setup.py"
    echo "  请手动输入安装命令，或确保项目目录包含依赖配置文件。"
    DEFAULT_INSTALL_CMD=""
else
    DEFAULT_INSTALL_CMD="${DETECT_CMD}"
    echo "  建议命令: ${DEFAULT_INSTALL_CMD}"
fi

echo "────────────────────────────────────────────────────"
printf "回车确认，或输入自定义安装命令: "
read -r user_install_input

INSTALL_CMD="${user_install_input:-${DEFAULT_INSTALL_CMD}}"
if [[ -z "${INSTALL_CMD}" ]]; then
    echo "错误: 未指定安装命令，退出。"; exit 1
fi
echo "    使用命令: ${INSTALL_CMD}"

# ---------------------------------------------------------------------------
# 交互 2：确认 / 修改待复制的文件和目录列表
# ---------------------------------------------------------------------------
EXCLUDE_PATTERNS=('.git' '.venv' 'venv' '__pycache__' 'lib' '*.egg-info' '*.tar.gz' '.DS_Store')

_is_excluded() {
    local name="$1"
    for pat in "${EXCLUDE_PATTERNS[@]}"; do
        case "${name}" in
            ${pat}) return 0 ;;
        esac
    done
    return 1
}

DEFAULT_COPY=()
while IFS= read -r entry; do
    name="$(basename "${entry}")"
    _is_excluded "${name}" || DEFAULT_COPY+=("${name}")
done < <(find "${SRC_DIR}" -maxdepth 1 \( -type f -o -type d \) ! -path "${SRC_DIR}" | sort)

echo ""
echo "── 将复制以下文件/目录到包内 ──────────────────────"
for item in "${DEFAULT_COPY[@]}"; do
    echo "    ${item}"
done
echo "────────────────────────────────────────────────────"
printf "回车确认，或输入新列表（空格分隔）: "
read -r user_copy_input

if [[ -n "${user_copy_input}" ]]; then
    read -ra COPY_LIST <<< "${user_copy_input}"
else
    COPY_LIST=("${DEFAULT_COPY[@]}")
fi

# ---------------------------------------------------------------------------
# 交互 3：确认 / 修改 Python 启动命令
# ---------------------------------------------------------------------------
echo ""
echo "── Python 启动命令 ─────────────────────────────────"
echo "    python ${ENTRY_CMD}"
echo "  支持两种格式："
echo "    主文件:   app.py              → python app.py"
echo "    模块启动: -m uvicorn app:main → python -m uvicorn app:main"
echo "────────────────────────────────────────────────────"
printf "回车确认，或输入新启动命令: "
read -r user_entry_input
[[ -n "${user_entry_input}" ]] && ENTRY_CMD="${user_entry_input}"
echo "    使用命令: python ${ENTRY_CMD}"

# ---------------------------------------------------------------------------
# 交互 4：选择 Python 版本
# ---------------------------------------------------------------------------
echo ""
echo "── Python 版本 ─────────────────────────────────────"
echo "  1) 3.10"
echo "  2) 3.12（默认）"
echo "  3) 3.13"
echo "  4) 其它（需手动指定 Docker 镜像）"
echo "────────────────────────────────────────────────────"
printf "请选择 [1/2/3/4]（默认 2）: "
read -r user_py_choice

case "${user_py_choice}" in
    1) PYTHON_VERSION="3.10"; CUSTOM_IMAGE=false ;;
    3) PYTHON_VERSION="3.13"; CUSTOM_IMAGE=false ;;
    4) PYTHON_VERSION="";     CUSTOM_IMAGE=true  ;;
    *) PYTHON_VERSION="3.12"; CUSTOM_IMAGE=false ;;
esac

if ${CUSTOM_IMAGE}; then
    echo "    已选择其它版本，后续需手动填写 Docker 镜像地址"
else
    echo "    使用 Python ${PYTHON_VERSION}"
fi

# ---------------------------------------------------------------------------
# 交互 5：确认 / 修改 Docker 镜像（仅用于构建下载依赖，不是运行时镜像）
# ---------------------------------------------------------------------------
if ${CUSTOM_IMAGE}; then
    DEFAULT_IMAGE=""
else
    DEFAULT_IMAGE="apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/python:${PYTHON_VERSION}-slim_${TARGET_ARCH}"
fi

echo ""
echo "── Docker 构建镜像（仅用于下载安装依赖包，非运行时镜像）──"
if [[ -n "${DEFAULT_IMAGE}" ]]; then
    echo "    ${DEFAULT_IMAGE}"
else
    echo "    （请填写 Docker 镜像地址）"
fi
echo "────────────────────────────────────────────────────"
if [[ -n "${DEFAULT_IMAGE}" ]]; then
    printf "回车确认，或输入新镜像名: "
else
    printf "请输入 Docker 镜像地址: "
fi
read -r user_image_input

PYTHON_IMAGE="${user_image_input:-${DEFAULT_IMAGE}}"
if [[ -z "${PYTHON_IMAGE}" ]]; then
    echo "错误: 必须指定 Docker 镜像地址，退出。"; exit 1
fi
echo "    使用镜像: ${PYTHON_IMAGE}"

# ---------------------------------------------------------------------------
# 交互 6：确认 / 修改 pip 镜像源
# ---------------------------------------------------------------------------
DEFAULT_PIP_INDEX="https://mirrors.aliyun.com/pypi/simple/"

echo ""
echo "── pip 镜像源 ──────────────────────────────────────"
echo "    ${DEFAULT_PIP_INDEX}"
echo "────────────────────────────────────────────────────"
printf "回车确认，或输入新镜像源 URL（留空则不指定）: "
read -r user_pip_input

PIP_INDEX="${user_pip_input:-${DEFAULT_PIP_INDEX}}"
if [[ -n "${PIP_INDEX}" ]]; then
    echo "    使用镜像源: ${PIP_INDEX}"
    PIP_HOST="$(echo "${PIP_INDEX}" | sed 's|https\?://||' | cut -d'/' -f1)"
    # 将镜像源参数注入到安装命令中
    INSTALL_CMD="${INSTALL_CMD} -i ${PIP_INDEX} --trusted-host ${PIP_HOST}"
else
    echo "    不使用镜像源（使用 pip 默认源）"
fi

# ---------------------------------------------------------------------------
# 1. 创建临时目录结构
# ---------------------------------------------------------------------------
echo ""
rm -rf "${TMP_DIR}"
mkdir -p "${APP_DIR}/lib"

# ---------------------------------------------------------------------------
# 2. 复制源代码
# ---------------------------------------------------------------------------
echo "[1/3] 复制源代码..."
for item in "${COPY_LIST[@]}"; do
    src_path="${SRC_DIR}/${item}"
    if [[ -e "${src_path}" ]]; then
        cp -r "${src_path}" "${APP_DIR}/${item}"
    else
        echo "      警告: '${item}' 不存在，已跳过"
    fi
done
echo "      完成"

# ---------------------------------------------------------------------------
# 3. 用 Docker 在目标 Linux 平台内安装依赖到 lib/
#    始终挂载源码目录为 /src（供 pyproject.toml / setup.py 模式使用）
# ---------------------------------------------------------------------------
echo "[2/3] 安装依赖到 lib/（Docker ${DOCKER_PLATFORM}）..."

docker run --rm \
    --platform "${DOCKER_PLATFORM}" \
    -v "${APP_DIR}/lib:/target" \
    -v "${SRC_DIR}:/src:ro" \
    "${PYTHON_IMAGE}" \
    sh -c "${INSTALL_CMD}"
echo "      lib/ 目录大小: $(du -sh "${APP_DIR}/lib" | cut -f1)"

# ---------------------------------------------------------------------------
# 4. 生成启动脚本
# ---------------------------------------------------------------------------
echo "[3/3] 生成启动脚本 (start.sh)..."

if [[ "${ENTRY_CMD}" == *.py ]]; then
    EXEC_LINE="exec python \"\${SCRIPT_DIR}/${ENTRY_CMD}\" \"\$@\""
else
    EXEC_LINE="cd \"\${SCRIPT_DIR}\" && exec python ${ENTRY_CMD} \"\$@\""
fi

cat > "${APP_DIR}/start.sh" << STARTSCRIPT
#!/bin/sh
# 启动脚本 — 将内嵌 lib/ 加入 PYTHONPATH 后运行应用
# 启动命令: python ${ENTRY_CMD}
set -eu

SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"

export PYTHONPATH="\${SCRIPT_DIR}/lib\${PYTHONPATH:+:\${PYTHONPATH}}"

${EXEC_LINE}
STARTSCRIPT
chmod +x "${APP_DIR}/start.sh"
find "${APP_DIR}" -maxdepth 1 -name "*.sh" -exec chmod +x {} +

# ---------------------------------------------------------------------------
# 5. 打包压缩
# ---------------------------------------------------------------------------
COPYFILE_DISABLE=1 tar -czf "${OUTPUT_FILE}" -C "${TMP_DIR}" "${APP_NAME}"

# ---------------------------------------------------------------------------
# 6. 清理
# ---------------------------------------------------------------------------
rm -rf "${TMP_DIR}"

echo ""
echo "✓ 打包完成: ${OUTPUT_FILE}"
echo "  大小: $(du -sh "${OUTPUT_FILE}" | cut -f1)"
echo ""
echo "解压并运行："
echo "  tar -xzf ${OUTPUT_FILE}"
echo "  cd ${APP_NAME}"
echo "  ./start.sh"
