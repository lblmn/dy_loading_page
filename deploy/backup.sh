#!/usr/bin/env bash
# SQLite 在线一致性备份：用 Python 标准库 sqlite3 的 backup()（不需要 sqlite3 CLI）。
# 用法：./deploy/backup.sh [备份目录]，默认 ./backups；保留最近 14 天。
# 建议 cron：17 3 * * * /opt/linklab/deploy/backup.sh /opt/linklab/backups
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="${LINKLAB_DB:-$ROOT/linklab.db}"
DEST="${1:-$ROOT/backups}"

if [ ! -f "$DB" ]; then
  echo "数据库不存在：$DB" >&2
  exit 1
fi

mkdir -p "$DEST"
OUT="$DEST/linklab-$(date +%Y%m%d-%H%M%S).db"
python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1])
dst = sqlite3.connect(sys.argv[2])
try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
PY
chmod 600 "$OUT"
find "$DEST" -name 'linklab-*.db' -mtime +14 -delete
echo "备份完成：$OUT"
