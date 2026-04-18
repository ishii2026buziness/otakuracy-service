#!/usr/bin/env bash
set -uo pipefail

PACKAGE_DIR=/app
LOG_FILE="/data/pipeline-$(date +%Y%m%d).log"

cd "$PACKAGE_DIR"
source .venv/bin/activate

echo "=== otakuracy start: $(date -Iseconds) ===" | tee -a "$LOG_FILE"

PYTHONPATH=/app/src:/common/src python -m cli_v2 run 2>&1 | tee -a "$LOG_FILE"
PIPELINE_EXIT=${PIPESTATUS[0]}

echo "=== otakuracy end: $(date -Iseconds) exit=$PIPELINE_EXIT ===" | tee -a "$LOG_FILE"

# Write Prometheus metrics
TS=$(date +%s)
if [ "$PIPELINE_EXIT" = "0" ]; then STATUS=1; else STATUS=0; fi
cat > /metrics/otakuracy.prom << METRICS
# HELP pipeline_last_run_status 1=success 0=failure
# TYPE pipeline_last_run_status gauge
pipeline_last_run_status{pipeline="otakuracy"} $STATUS
# HELP pipeline_last_run_timestamp_seconds Unix timestamp of last run attempt
# TYPE pipeline_last_run_timestamp_seconds gauge
pipeline_last_run_timestamp_seconds{pipeline="otakuracy"} $TS
METRICS

exit "$PIPELINE_EXIT"
