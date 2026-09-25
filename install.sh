#!/usr/bin/env bash
# mediahub 一键安装脚本（Ubuntu / Debian）
# 功能：检查 ffmpeg/ffprobe -> 创建虚拟环境 -> 安装依赖 -> 生成 .env
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

info()  { printf '\033[1;34m[INFO]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }
error() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; }

# ---------- 1. 检查 Python ----------
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  error "未找到 $PYTHON_BIN，请先安装 Python 3.10+：sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
info "检测到 Python $PY_VERSION"
"$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
  error "Python 版本过低，需要 3.10 及以上"
  exit 1
}

# ---------- 2. 检查 ffmpeg ----------
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  info "ffmpeg 已安装：$(ffmpeg -version | head -n 1)"
else
  warn "未检测到 ffmpeg / ffprobe。"
  warn "请执行：sudo apt update && sudo apt install -y ffmpeg"
  warn "缺少 ffmpeg 时服务仍可启动，但媒体探测、封面与转码功能不可用。"
fi

# ---------- 3. 创建虚拟环境 ----------
if [ -d "$VENV_DIR" ]; then
  info "虚拟环境已存在：$VENV_DIR"
else
  info "创建虚拟环境：$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR" || {
    error "创建虚拟环境失败，请安装 python3-venv：sudo apt install -y python3-venv"
    exit 1
  }
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ---------- 4. 安装依赖 ----------
info "升级 pip / setuptools / wheel"
pip install --upgrade pip setuptools wheel >/dev/null

info "安装项目依赖（requirements.txt）"
pip install -r requirements.txt

# ---------- 5. 生成 .env ----------
if [ -f .env ]; then
  info ".env 已存在，跳过生成"
else
  cp .env.example .env
  info "已根据 .env.example 生成 .env，请按需修改 MEDIA_DIRS"
fi

# ---------- 6. 杂项 ----------
mkdir -p data data/cache data/transcoded
chmod +x run.sh mediahub-cli install.sh 2>/dev/null || true

info "安装完成。"
echo
echo "  启动服务：  ./run.sh"
echo "  或：        source $VENV_DIR/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo "  扫描媒体：  ./mediahub-cli scan --dir <你的媒体目录>"
echo "  访问界面：  http://localhost:8000"
