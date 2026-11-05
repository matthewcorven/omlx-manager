#!/usr/bin/env python3
"""Re-profile a batch of models on the installed oMLX, strictly serialized.

Runs `reprofile_model.py` once per model, unloading between models so that two
models are never resident at once (that would change the memory situation under
which the original numbers were taken). Stops the whole batch if a model's
settings drifted, because that means the comparison is invalid and the rest of
the batch would be measuring the wrong config.

Usage
  python3 reprofile_batch.py --models A B C
  python3 reprofile_batch.py --from-plan            # use .reprofile/plan.json
  python3 reprofile_batch.py --from-plan --modality generative-text

Exit codes: 0 all measured, 1 any refusal, 2 any error.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
PLAN = REPO_ROOT / ".reprofile" / "plan.json"
STATE_DIR = REPO_ROOT / ".reprofile"


def api_get(path: str, timeout: float = 60.0):
    import urllib.request
    base = __import__("os").environ.get("OMLX_BASE_URL", "http://127.0.0.1:8001")
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.load(r)


def api_post(path: str, timeout: float = 600.0):
    import urllib.request
    base = __import__("os").environ.get("OMLX_BASE_URL", "http://127.0.0.1:8001")
    req = urllib.request.Request(base + path, data=b"{}",
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def unload_all() -> None:
    for m in api_get("/admin/api/models").get("models", []):
        if m.get("loaded"):
            try:
                api_post(f"/admin/api/models/{m['id']}/unload")
                print(f"  unloaded {m['id']}")
            except Exception as e:  # noqa: BLE001
                print(f"  unload failed for {m['id']}: {e}")


def from_plan(modality: str | None) -> list[str]:
    if not PLAN.is_file():
        raise SystemExit("no plan — run `release_reprofile.py plan` first")
    plan = json.loads(PLAN.read_text())
    out = []
    for row in plan.get("reprofile", []):
        if not row.get("on_disk"):
            continue
        if modality and modality not in row.get("modalities", []):
            continue
        out.append(row["name"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=[])
    ap.add_argument("--from-plan", action="store_true")
    ap.add_argument("--modality", help="filter when using --from-plan")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=256)
    args = ap.parse_args()

    models = args.models
    if args.from_plan:
        models = from_plan(args.modality)
    if not models:
        raise SystemExit("no models to run")

    STATE_DIR.mkdir(exist_ok=True)
    log = STATE_DIR / f"batch-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.log"
    print(f"batch: {len(models)} model(s), log -> {log.relative_to(REPO_ROOT)}")

    worst = 0
    with log.open("w") as lf:
        for i, model in enumerate(models, 1):
            print(f"\n[{i}/{len(models)}] {model}", flush=True)
            lf.write(f"\n===== {model} =====\n")
            unload_all()
            proc = subprocess.run(
                [sys.executable, str(HERE / "reprofile_model.py"),
                 "--model", model, "--runs", str(args.runs),
                 "--max-tokens", str(args.max_tokens)],
                capture_output=True, text=True,
            )
            lf.write(proc.stdout + proc.stderr)
            lf.flush()
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:]
            print(f"  exit {proc.returncode}  {tail[0] if tail else ''}")
            if proc.returncode == 1:
                print("  settings drift — stopping the batch so the rest is "
                      "not measured against a wrong config")
                worst = max(worst, 1)
                break
            worst = max(worst, proc.returncode)

    unload_all()
    print(f"\nbatch finished (worst exit {worst})")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
