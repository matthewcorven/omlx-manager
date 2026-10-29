#!/bin/bash
# Discard one warmup run, then measure 5 runs. Usage: measure5.sh <label>
set -euo pipefail
cd "$(dirname "$0")/../../.."
L="$1"
python3 scripts/measure.py --model Qwen3.8-27B-oQ4e-mtp --runs 1 --max-tokens 300 >/dev/null 2>&1
python3 scripts/measure.py --model Qwen3.8-27B-oQ4e-mtp --runs 5 --max-tokens 300 \
  --out "results/Qwen3.8-27B-oQ4e-mtp/tuning/$L.json" 2>&1 | grep -E '^run|_median'
