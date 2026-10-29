#!/bin/sh
# Refuse to proceed unless there is enough free disk for a download.
# Usage: scripts/disk_guard.sh <needed_gb> [floor_gb]
# Exits 0 if free - needed >= floor (default floor 60 GB), else 1.
set -eu

NEEDED="${1:?usage: disk_guard.sh <needed_gb> [floor_gb]}"
FLOOR="${2:-60}"

FREE_GB=$(df -g /System/Volumes/Data | awk 'NR==2 {print $4}')
AFTER=$((FREE_GB - NEEDED))

echo "free=${FREE_GB}GB needed=${NEEDED}GB after=${AFTER}GB floor=${FLOOR}GB"

if [ "$AFTER" -lt "$FLOOR" ]; then
  echo "REFUSED: would leave ${AFTER}GB, below the ${FLOOR}GB floor" >&2
  exit 1
fi
echo "OK"
