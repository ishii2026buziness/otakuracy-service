#!/usr/bin/env bash
# Service entrypoint template
# サービス固有の処理（auth設定等）はこのファイルの上部に追加する
set -euo pipefail

SERVICE_NAME={{SERVICE_NAME}}
PACKAGE_DIR=/app
LOG_FILE="/data/pipeline-$(date +%Y%m%d).log"

# Load .env if present
if [ -f /auth/.env ]; then
    set -a
    source /auth/.env
    set +a
fi

# Symlink output, artifacts, logs to /data for persistence
rm -rf "$PACKAGE_DIR/output" "$PACKAGE_DIR/artifacts" "$PACKAGE_DIR/logs"
mkdir -p /data/output /data/artifacts /data/logs
ln -sf /data/output "$PACKAGE_DIR/output"
ln -sf /data/artifacts "$PACKAGE_DIR/artifacts"
ln -sf /data/logs "$PACKAGE_DIR/logs"

cd "$PACKAGE_DIR"
source .venv/bin/activate

echo "=== $SERVICE_NAME start: $(date -Iseconds) ===" | tee -a "$LOG_FILE"

if [ "$#" -gt 0 ]; then
    cmd=("$@")
else
    cmd=(python -m cli run)
fi

PYTHONPATH=/app/src \
    "${cmd[@]}" 2>&1 | tee -a "$LOG_FILE"

echo "=== $SERVICE_NAME end: $(date -Iseconds) ===" | tee -a "$LOG_FILE"
