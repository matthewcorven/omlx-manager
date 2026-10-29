#!/bin/sh
# Move a finished model between the internal SSD and the external NVMe volume.
#
# Both directories are registered in model.model_dirs, so a model loads from
# wherever it sits — shuttling is purely a disk-space move, never a "make it
# usable" step. It does NOT change resident memory: a model over the ~89.6 GB
# ceiling stays over it after the move. Use MoE expert offload for that.
#
# Usage:
#   scripts/shuttle_model.sh <model_id>            internal -> external
#   scripts/shuttle_model.sh --back <model_id>     external -> internal
#   scripts/shuttle_model.sh --dry-run <model_id>  show the move only
#
# Exit codes: 0 moved/ok, 1 refused (loaded, mid-sweep, missing), 2 usage.
set -eu

OMLX="${OMLX:-http://127.0.0.1:8001}"
INTERNAL="${INTERNAL_MODELS:-$HOME/.omlx/models/mlx-community}"
EXTERNAL="${EXTERNAL_MODELS:-/Volumes/NVMe/omlx-models}"

BACK=0
DRY=0
MODEL=""

for arg in "$@"; do
  case "$arg" in
    --back) BACK=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) MODEL="$arg" ;;
  esac
done

if [ -z "$MODEL" ]; then
  echo "usage: shuttle_model.sh [--back] [--dry-run] <model_id>" >&2
  exit 2
fi

if [ "$BACK" -eq 1 ]; then
  SRC_ROOT="$EXTERNAL"; DST_ROOT="$INTERNAL"; DIRECTION="external -> internal"
else
  SRC_ROOT="$INTERNAL"; DST_ROOT="$EXTERNAL"; DIRECTION="internal -> external"
fi

# --- locate the model directory -------------------------------------------
# Layout is <root>/<org>/<model_id>; fall back to a flat <root>/<model_id>.
find_model() {
  root="$1"
  for candidate in "$root"/*/"$MODEL" "$root/$MODEL"; do
    [ -d "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

if ! SRC=$(find_model "$SRC_ROOT"); then
  echo "REFUSED: '$MODEL' not found under $SRC_ROOT" >&2
  echo "  (already shuttled? try the other direction with --back)" >&2
  exit 1
fi

REL="${SRC#"$SRC_ROOT"/}"
DST="$DST_ROOT/$REL"

if [ -e "$DST" ]; then
  echo "REFUSED: destination already exists: $DST" >&2
  exit 1
fi

# --- refuse while the model is loaded or a benchmark is running -----------
LOADED=$(curl -s -m 10 "$OMLX/admin/api/models" 2>/dev/null | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print('unknown'); raise SystemExit
ms = d if isinstance(d,list) else d.get('models',[])
for m in ms:
    if m.get('id')=='$MODEL':
        print('yes' if m.get('loaded') else 'no'); raise SystemExit
print('absent')
" 2>/dev/null || echo unknown)

case "$LOADED" in
  yes)
    echo "REFUSED: '$MODEL' is loaded. Unload it first:" >&2
    echo "  curl -s -X POST $OMLX/admin/api/models/$MODEL/unload" >&2
    exit 1 ;;
  unknown)
    echo "WARNING: could not read model state from $OMLX; assuming unloaded" >&2 ;;
esac

# A benchmark in flight means files must not move under it.
if ps aux | grep -E "measure\.py|ab\.py" | grep -v grep >/dev/null 2>&1; then
  echo "REFUSED: a benchmark appears to be running; never move a model mid-run" >&2
  exit 1
fi

SIZE=$(du -sh "$SRC" 2>/dev/null | awk '{print $1}')
echo "shuttle: $MODEL  ($SIZE)  $DIRECTION"
echo "  from: $SRC"
echo "  to:   $DST"

if [ "$DRY" -eq 1 ]; then
  echo "dry-run: no files moved"
  exit 0
fi

# --- move -----------------------------------------------------------------
mkdir -p "$DST_ROOT"
# Same volume: rename is atomic and instant. Cross volume: copy then remove.
if [ "$(df -P "$SRC" | awk 'NR==2{print $1}')" = "$(df -P "$DST_ROOT" | awk 'NR==2{print $1}')" ]; then
  mv "$SRC" "$DST"
else
  # rsync preserves the HF cache symlinks and blob layout that oMLX expects.
  # macOS ships rsync 2.6.9, which lacks --info=progress2; --progress works there.
  # --partial keeps resumable chunks, but a killed rsync leaves a partial tree
  # behind, so the copy is verified before the source is removed.
  rsync -aH --progress --partial "$SRC/" "$DST/" || {
    echo "FAILED: rsync did not complete; leaving source in place" >&2
    rm -rf "$DST"
    exit 1
  }
  SRC_N=$(find "$SRC" -type f | wc -l | tr -d ' ')
  DST_N=$(find "$DST" -type f | wc -l | tr -d ' ')
  if [ "$SRC_N" != "$DST_N" ]; then
    echo "FAILED: copy incomplete ($DST_N/$SRC_N files); leaving source in place" >&2
    rm -rf "$DST"
    exit 1
  fi
  rm -rf "$SRC"
fi

# Drop now-empty org directory so the tree stays tidy.
rmdir "$(dirname "$SRC")" 2>/dev/null || true

echo "moved. verifying oMLX still sees it..."
curl -s -m 10 "$OMLX/admin/api/models" 2>/dev/null | python3 -c "
import json,os,sys
d=json.load(sys.stdin)
ms = d if isinstance(d,list) else d.get('models',[])
for m in ms:
    if m.get('id')=='$MODEL':
        p = m.get('path') or m.get('model_path') or ''
        print('  indexed at:', p or '(path not reported)')
        if p and not os.path.isdir(p):
            print('  STALE INDEX — that path no longer exists; restart the server')
            print('  so it re-indexes model_dirs, then re-check with a real request.')
        elif p:
            print('  path exists on disk')
        break
else:
    print('  NOT VISIBLE — restart the server so it re-indexes model_dirs')
" 2>/dev/null || echo "  (could not verify; check GET /admin/api/models)"
