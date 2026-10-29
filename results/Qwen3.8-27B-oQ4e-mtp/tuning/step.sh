#!/bin/bash
# Apply a settings patch, reload if required, warm up, then measure 3 runs.
# Usage: step.sh <label> '<json patch>'
set -euo pipefail
OMLX=http://127.0.0.1:8001
MODEL=Qwen3.8-27B-oQ4e-mtp
LABEL="$1"
PATCH="$2"
DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$DIR/../../.." && pwd)"
cd "$REPO"

echo "=== $LABEL: $PATCH"
RESP=$(curl -s -X PUT "$OMLX/admin/api/models/$MODEL/settings" \
  -H 'Content-Type: application/json' -d "$PATCH")
echo "$RESP" | jq -c '{success, requires_reload, auto_unloaded, auto_reloaded, reload_deferred, error: .detail}'

curl -s "$OMLX/admin/api/models" | jq --arg m "$MODEL" \
  '.models[]|select(.id==$m)|.settings' > "$DIR/$LABEL-settings.json"

NEED_RELOAD=$(echo "$RESP" | jq -r '.requires_reload // false')
if [ "$NEED_RELOAD" = "true" ] || [ "$(echo "$RESP" | jq -r '.auto_unloaded // false')" = "true" ]; then
  echo "-- explicit unload/load"
  curl -s -X POST "$OMLX/admin/api/models/$MODEL/unload" | jq -c . || true
  for i in $(seq 1 60); do
    L=$(curl -s "$OMLX/admin/api/models" | jq -r --arg m "$MODEL" '.models[]|select(.id==$m)|.loaded')
    [ "$L" = "false" ] && break; sleep 1
  done
  curl -s -X POST "$OMLX/admin/api/models/$MODEL/load" | jq -c .
  for i in $(seq 1 240); do
    L=$(curl -s "$OMLX/admin/api/models" | jq -r --arg m "$MODEL" '.models[]|select(.id==$m)|.loaded')
    [ "$L" = "true" ] && break; sleep 1
  done
  echo "-- loaded=$L"
fi

echo "-- warmup"
python3 scripts/measure.py --model "$MODEL" --runs 1 --max-tokens 300 \
  --out "$DIR/$LABEL-warmup.json" 2>&1 | tail -3
echo "-- measure"
python3 scripts/measure.py --model "$MODEL" --runs 3 --max-tokens 300 \
  --out "$DIR/$LABEL.json" 2>&1 | tail -20
