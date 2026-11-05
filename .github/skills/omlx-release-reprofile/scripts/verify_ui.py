#!/usr/bin/env python3
"""Gate a re-profile run on the dashboard actually rendering the new data.

A re-profile is not finished when the CSVs validate. The dashboard is the thing
a human looks at, and it has two independent ways to be wrong even with perfect
CSVs:

1. **The committed tables parse but the page throws.** A generated or
   hand-edited `EMBEDDED_DATA` block that is syntactically invalid renders a
   blank page while every CSV still validates.
2. **The offline fallback drifts.** `EMBEDDED_DATA` is what the page serves from
   `file://` or after a failed fetch. If it is not regenerated from the CSVs,
   the fallback shows old numbers and misses new models.

So this gate does two things, in this order:

- **Data parity** — every model in `results/*.csv` must appear in the offline
  fallback. This is cheap and catches the "UI did not load the new data" case
  specifically, without needing a browser.
- **Full-breadth UI suite** — `npm run e2e`, the whole Playwright suite. This is
  delegated, not reimplemented: the suite is the single source of truth for
  dashboard behaviour, and this gate only decides whether it is safe to run and
  reports its result.

Run it:
  python3 .github/skills/omlx-release-reprofile/scripts/verify_ui.py
  python3 ... verify_ui.py --skip-e2e      # parity only, for a fast loop

Exit codes: 0 pass, 1 the UI is broken or stale, 2 could not run the checks.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RESULTS = REPO_ROOT / "results"
DASHBOARD = REPO_ROOT / "dashboard" / "index.html"
CATEGORIES = ["generative-text", "ocr", "decision", "image-generation", "voice"]


def live_models(category: str) -> list[str]:
    path = RESULTS / f"{category}.csv"
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        return [r["Model"].strip() for r in csv.DictReader(f) if r.get("Model")]


def extract_embed(html: str) -> dict[str, str]:
    """Pull the EMBEDDED_DATA object out of the page and parse it as JSON.

    Parsing is the point: an invalid block is exactly the failure this gate
    exists to catch, and JSON.parse failing is a clearer signal than a browser
    console error discovered later.
    """
    start = html.find("const EMBEDDED_DATA = ")
    if start == -1:
        raise ValueError("no EMBEDDED_DATA block in dashboard/index.html")
    start += len("const EMBEDDED_DATA = ")
    end = html.find("const CONFIG = ", start)
    block = html[start:end].strip()
    # Trailing `;` and any stray duplicate `};` are handled here so a page that
    # is *nearly* right still gets a precise diagnosis rather than a parse dump.
    block = block.rstrip(";").strip()
    if block.endswith("};"):
        block = block[:-2].rstrip()
    if not block.endswith("}"):
        raise ValueError(
            "EMBEDDED_DATA does not close with '}'; the block is truncated "
            "or has a duplicated terminator"
        )
    return json.loads(block)


def check_parity() -> list[str]:
    """Return a list of problems; empty means the fallback matches the CSVs."""
    html = DASHBOARD.read_text(encoding="utf-8")
    problems: list[str] = []

    try:
        embed = extract_embed(html)
    except (ValueError, json.JSONDecodeError) as e:
        return [f"EMBEDDED_DATA is not parseable: {e}"]

    for category in CATEGORIES:
        models = live_models(category)
        if not models:
            continue
        body = embed.get(category)
        if body is None:
            problems.append(f"{category}: missing from EMBEDDED_DATA")
            continue
        for model in models:
            if model not in body:
                problems.append(
                    f"{category}: {model} is in the CSV but not in the offline fallback"
                )
    return problems


def run_e2e() -> int:
    print("running the full Playwright suite (npm run e2e) ...")
    proc = subprocess.run(["npm", "run", "e2e"], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    summary = [l for l in tail if re.search(r"\b(passed|failed)\b", l)]
    print("\n".join(summary[-4:]) or "\n".join(tail[-6:]))
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-e2e", action="store_true",
                    help="only check CSV/fallback parity")
    args = ap.parse_args()

    if not DASHBOARD.is_file():
        print(f"dashboard not found: {DASHBOARD}", file=sys.stderr)
        return 2

    problems = check_parity()
    if problems:
        print("UI DATA PARITY: FAIL", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        print("\nFix with: python3 scripts/record_model_result.py --generate-embed",
              file=sys.stderr)
        return 1
    print("UI DATA PARITY: PASS — every recorded model is in the offline fallback")

    if args.skip_e2e:
        return 0

    rc = run_e2e()
    if rc != 0:
        print("UI SUITE: FAIL — the dashboard suite did not pass. A re-profile "
              "is not complete until it does; report this rather than updating "
              "results as though the UI were fine.", file=sys.stderr)
        return 1
    print("UI SUITE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
