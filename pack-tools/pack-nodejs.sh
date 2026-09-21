#!/bin/sh
# 以 sh 调用时自动切换到完整 bash 执行（脚本使用了 bash 特有语法）
[ -z "${BASH_VERSION:-}" ] && exec bash "$0" "$@"
# shellcheck disable=SC3010
[[ -o posix ]] && exec bash "$0" "$@"
# =============================================================================
# pack-nodejs.sh — Node.js 应用离线打包脚本（Docker 构建 Linux 原生依赖）
#
# 原理：
#   1. 用 Docker 在目标 Linux 平台容器内执行 npm ci --omit=dev，
#      确保含原生模块（node-gyp）的依赖与目标系统二进制兼容
#   2. 将源码 + node_modules/ + 其他应用文件打包为 tar.gz
#
# 启动模式（打包时选择）：
#   tsx 调试模式  — tsx src/index.ts，修改 .ts 文件重启即生效，无需重新编译
#   编译生产模式  — tsc 编译后 node dist/index.js，启动快、内存占用低
#
# 环境要求：
#   - Docker Desktop（必须）
#   - macOS / Linux：直接运行
#   - Windows：请在 Git Bash 或 WSL2 终端中执行，不支持 CMD / PowerShell
#
# 用法：
#   ./pack-nodejs.sh [选项]
#
# 选项：
#   -s DIR   源代码目录（必填）
#   -a ARCH  目标架构 amd64|arm64（默认：amd64；可用 TARGET_ARCH 环境变量）
#   -o DIR   输出目录（默认：<src>/../）
#   -h       显示帮助信息
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 打包原理说明（运行时展示）
# ---------------------------------------------------------------------------
cat << 'INTRO'
╔══════════════════════════════════════════════════════════════════════════════╗
║                    pack-nodejs.sh  打包说明                                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  目标：打出一个可在云上 Linux 环境直接运行的离线包，包含全部依赖，           ║
║        部署时无需联网下载任何内容。                                          ║
║                                                                              ║
║  为什么需要 Docker：                                                         ║
║    部分 npm 包含原生模块（通过 node-gyp 编译的 C/C++ 扩展）。               ║
║    在 macOS 上 npm install 得到的是 macOS 格式二进制，无法在 Linux 上运行。  ║
║    通过 Docker 在目标 Linux 平台容器内执行 npm ci，                          ║
║    可确保 node_modules 与云上环境兼容。                                      ║
║                                                                              ║
║  启动模式：                                                                  ║
║    tsx 调试模式  — 直接运行 TypeScript，改完代码重启即生效                   ║
║    编译生产模式  — 打包时预编译，运行时 node dist/，启动更快                 ║
║                                                                              ║
║  包内容：源码 + node_modules/（全部依赖）                                    ║
║  启动方式：./start.sh，无需在目标机器上安装任何依赖，完全离线运行。          ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
INTRO

# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR=""
OUTPUT_DIR=""
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
        -a) TARGET_ARCH="$2"; shift 2 ;;
        -o) OUTPUT_DIR="$2";  shift 2 ;;
        -h|--help) usage ;;
        *) echo "未知选项: $1（-h 查看帮助）"; exit 1 ;;
    esac
done

if [[ -z "${SRC_DIR}" ]]; then
    echo "错误: 请用 -s DIR 指定 Node.js 项目目录（-h 查看帮助）"
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
if [[ ! -f "${SRC_DIR}/package.json" ]]; then
    echo "错误: 未找到 package.json: ${SRC_DIR}/package.json"; exit 1
fi
if ! command -v docker &>/dev/null; then
    echo "错误: 未检测到 docker 命令，请先安装并启动 Docker Desktop。"; exit 1
fi
if ! command -v npm &>/dev/null; then
    echo "错误: 未检测到 npm 命令，请先安装 Node.js。"; exit 1
fi

echo "=================================================="
echo "  Node.js 应用打包"
echo "  包名:     ${APP_NAME}"
echo "  源目录:   ${SRC_DIR}"
echo "  目标平台: ${DOCKER_PLATFORM}"
echo "  输出文件: ${OUTPUT_FILE}"
echo "=================================================="

# ---------------------------------------------------------------------------
# 交互 1：选择启动模式
# ---------------------------------------------------------------------------
echo ""
echo "── 启动模式 ─────────────────────────────────────────────────────"
echo "  1) tsx 调试模式   tsx src/index.ts"
echo "                    修改 .ts 文件后重启即生效，无需重新编译"
echo "  2) 编译生产模式   node dist/index.js"
echo "                    打包时执行 tsc 编译，启动快、内存占用低"
echo "────────────────────────────────────────────────────"
printf "请选择 [1/2]（默认 1）: "
read -r user_mode_input

case "${user_mode_input}" in
    2) START_MODE="prod" ;;
    *) START_MODE="tsx"  ;;
esac

if [[ "${START_MODE}" == "prod" ]]; then
    echo "    已选: 编译生产模式（node dist/index.js）"
    DEFAULT_ENTRY="dist/index.js"
    ENTRY_HINT="node <入口文件>，如: dist/index.js"
else
    echo "    已选: tsx 调试模式（tsx src/index.ts）"
    DEFAULT_ENTRY="src/index.ts"
    ENTRY_HINT="tsx <入口文件>，如: src/index.ts"
fi

# ---------------------------------------------------------------------------
# 交互 2：确认 / 修改启动入口文件
# ---------------------------------------------------------------------------
echo ""
echo "── 启动入口文件 ──────────────────────────────────────────────────"
echo "    ${ENTRY_HINT}"
echo "    默认: ${DEFAULT_ENTRY}"
echo "────────────────────────────────────────────────────"
printf "回车确认，或输入新入口文件路径: "
read -r user_entry_input

ENTRY_FILE="${user_entry_input:-${DEFAULT_ENTRY}}"
echo "    使用入口: ${ENTRY_FILE}"

# ---------------------------------------------------------------------------
# 交互 3：确认 / 修改待复制的文件和目录列表
# ---------------------------------------------------------------------------

# 忽略规则（node_modules 由 Docker 安装，dist 视模式而定，均不手动复制）
EXCLUDE_PATTERNS=('.git' '.venv' 'venv' 'node_modules' 'dist' '*.tar.gz' '.DS_Store'
                  '*.log' '.env*' 'Dockerfile'
                  '*.sh' 'README*' '*.md' 'build_image.sh' 'push_base_image.sh'
                  'deployAndRunInPlatform.md')

if [[ "${START_MODE}" == "prod" ]]; then
    EXCLUDE_HINT="（node_modules/ 由 Docker 安装，dist/ 由 tsc 编译生成，已自动排除）"
else
    EXCLUDE_HINT="（node_modules/ 由 Docker 安装，dist/ 调试模式不需要，已自动排除）"
fi

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
echo "── 将复制以下文件/目录到包内 ──────────────────────────────────"
echo "   ${EXCLUDE_HINT}"
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
# 交互 4：确认 / 修改 Docker 镜像（仅用于安装 npm 依赖，非运行时镜像）
# ---------------------------------------------------------------------------
DEFAULT_IMAGE="apaas-registry.cn-hangzhou.cr.aliyuncs.com/agentrun/nodejs-base:20"

echo ""
echo "── Docker 构建镜像（仅用于安装 npm 依赖，非运行时镜像）──────────"
echo "    ${DEFAULT_IMAGE}"
echo "────────────────────────────────────────────────────"
printf "回车确认，或输入新镜像名: "
read -r user_image_input

NODE_IMAGE="${user_image_input:-${DEFAULT_IMAGE}}"
echo "    使用镜像: ${NODE_IMAGE}"

# ---------------------------------------------------------------------------
# Step 1: 编译 TypeScript（仅生产模式）
# ---------------------------------------------------------------------------
if [[ "${START_MODE}" == "prod" ]]; then
    echo ""
    echo "[1/4] 编译 TypeScript..."
    cd "${SRC_DIR}"
    npm run build
    echo "      完成"
    TOTAL_STEPS=4
else
    TOTAL_STEPS=3
fi

# ---------------------------------------------------------------------------
# Step N: 复制应用文件到临时目录
# ---------------------------------------------------------------------------
if [[ "${START_MODE}" == "prod" ]]; then
    STEP_COPY="2"
else
    STEP_COPY="1"
fi
echo ""
echo "[${STEP_COPY}/${TOTAL_STEPS}] 复制应用文件..."
rm -rf "${TMP_DIR}"
mkdir -p "${APP_DIR}"

# package.json / package-lock.json 是 npm ci 的必要输入，始终复制
cp "${SRC_DIR}/package.json" "${APP_DIR}/"
[[ -f "${SRC_DIR}/package-lock.json" ]] && cp "${SRC_DIR}/package-lock.json" "${APP_DIR}/"

# 生产模式额外复制编译产物 dist/
if [[ "${START_MODE}" == "prod" ]]; then
    cp -r "${SRC_DIR}/dist" "${APP_DIR}/"
fi

# 复制用户确认的列表（已含上述文件的跳过，避免重复）
ALREADY_COPIED=("package.json" "package-lock.json" "dist")
for item in "${COPY_LIST[@]}"; do
    skip=false
    for ac in "${ALREADY_COPIED[@]}"; do
        [[ "${item}" == "${ac}" ]] && skip=true && break
    done
    ${skip} && continue
    src_path="${SRC_DIR}/${item}"
    if [[ -e "${src_path}" ]]; then
        cp -r "${src_path}" "${APP_DIR}/${item}"
    else
        echo "      警告: '${item}' 不存在，已跳过"
    fi
done
echo "      完成"

# ---------------------------------------------------------------------------
# Step N: 用 Docker 在目标 Linux 平台安装生产依赖
# ---------------------------------------------------------------------------
STEP_NPM="$(( STEP_COPY + 1 ))"
echo "[${STEP_NPM}/${TOTAL_STEPS}] 安装 npm 生产依赖（Docker ${DOCKER_PLATFORM}）..."
docker run --rm \
    --platform "${DOCKER_PLATFORM}" \
    -v "${APP_DIR}:/app" \
    -w /app \
    "${NODE_IMAGE}" \
    sh -c "npm ci --omit=dev"
echo "      node_modules/ 大小: $(du -sh "${APP_DIR}/node_modules" | cut -f1)"

# ---------------------------------------------------------------------------
# Step N: 生成 start.sh
# ---------------------------------------------------------------------------
STEP_START="$(( STEP_NPM + 1 ))"
echo "[${STEP_START}/${TOTAL_STEPS}] 生成 start.sh..."

if [[ "${START_MODE}" == "prod" ]]; then
    cat > "${APP_DIR}/start.sh" << STARTSCRIPT
#!/bin/sh
# 编译生产模式：运行 tsc 编译产物，启动快、内存占用低
set -eu
SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
cd "\${SCRIPT_DIR}"
exec node ${ENTRY_FILE} "\$@"
STARTSCRIPT
else
    cat > "${APP_DIR}/start.sh" << STARTSCRIPT
#!/bin/sh
# tsx 调试模式：直接运行 TypeScript 源码，修改 .ts 文件后重启即生效
set -eu
SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
cd "\${SCRIPT_DIR}"
exec node_modules/.bin/tsx ${ENTRY_FILE} "\$@"
STARTSCRIPT
fi
chmod +x "${APP_DIR}/start.sh"

# ---------------------------------------------------------------------------
# 打包压缩
# ---------------------------------------------------------------------------
COPYFILE_DISABLE=1 tar -czf "${OUTPUT_FILE}" -C "${TMP_DIR}" "${APP_NAME}"
rm -rf "${TMP_DIR}"

echo ""
echo "✓ 打包完成: ${OUTPUT_FILE}"
echo "  大小: $(du -sh "${OUTPUT_FILE}" | cut -f1)"
if [[ "${START_MODE}" == "prod" ]]; then
    echo "  启动模式: 编译生产模式（node ${ENTRY_FILE}）"
else
    echo "  启动模式: tsx 调试模式（tsx ${ENTRY_FILE}）"
fi
echo ""
echo "解压并运行："
echo "  tar -xzf ${OUTPUT_FILE##*/}"
echo "  cd ${APP_NAME}"
echo "  ./start.sh"
echo ""
echo "指定端口启动："
echo "  PORT=3000 ./start.sh"
