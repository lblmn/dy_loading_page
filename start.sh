#!/usr/bin/env bash
# LinkLab 启动脚本（Linux / macOS）
#
# 前置：Python 3.10+，零第三方依赖。
# 步骤：cp config.example.env .env → 按注释修改 → ./start.sh
# 生产部署：设置 LINKLAB_HOST=0.0.0.0，用 Nginx/Caddy 终止 HTTPS 并反代到本机端口，
#           同时设 LINKLAB_PUBLIC_BASE_URL 与 LINKLAB_SECURE_COOKIE=1。
#           切勿把本服务的端口直接暴露到公网（它不提供 TLS）。
# 健康检查：curl http://127.0.0.1:8787/healthz
# 数据备份：定期备份 linklab.db（或 LINKLAB_DB 指向的文件）；删掉它等于重置系统。
# 自动化测试：不要对生产库跑 tests/smoke_test.py，会写入并删除数据。
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export LINKLAB_HOST="${LINKLAB_HOST:-127.0.0.1}"
export LINKLAB_PORT="${LINKLAB_PORT:-8787}"

exec python3 server.py
