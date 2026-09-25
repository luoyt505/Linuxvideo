#!/usr/bin/env bash
# mediahub 启动脚本
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# 自动加载 .env（若存在），使 HOST / PORT 等生效
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  HOST="${HOST:-0.0.0.0}"
  PORT="${PORT:-8000}"
fi

# 激活虚拟环境（若存在）
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "[WARN] 未找到 .venv，将使用系统 Python。建议先执行 ./install.sh" >&2
fi

mkdir -p data data/cache data/transcoded

echo "[INFO] 启动 mediahub：http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
