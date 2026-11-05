#!/usr/bin/env python3
"""Release-driven re-profiling for oMLX.

Given a new oMLX release, this determines three things and nothing else:

1. **What changed in the server** — installed version vs. what the results
   tables were last recorded against.
2. **What is already catalogued** — which models have rows and which do not.
3. **What newly fits this Mac** — by re-probing Hugging Face for every model
   previously catalogued as unobtainable, plus the families the release names.

It never benchmarks, never downloads, and never mutates `results/`. It writes a
single idempotent plan file (`.reprofile/plan.json`) that the operator (or the
skill's driver script) then executes. Keeping discovery and execution apart is
deliberate: discovery is cheap, safe, and re-runnable, while execution holds the
benchmark slot and costs hours.

Subcommands
-----------
  status     Installed vs. recorded version, per-modality inventory.
  discover   Re-probe every blocked/absent model on Hugging Face; update the
             catalogue. This is the command that satisfies the standing rule
             that an unavailable "fitting" variant must be retried on every
             release.
  plan       Build `.reprofile/plan.json` from status + discover output.
  catalog    Print the catalogue (blocked / absent / retried).

Usage
-----
  python3 .github/skills/omlx-release-reprofile/scripts/release_reprofile.py status
  python3 ... .py discover --tag v0.7.4
  python3 ... .py plan --scope all
  python3 ... .py catalog

Exit codes: 0 ok, 1 usage/IO error, 2 server unreachable.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------
# paths — repo-relative, never hardcoded to a working directory
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[4]
RESULTS = REPO_ROOT / "results"
STATE_DIR = REPO_ROOT / ".reprofile"
PLAN_PATH = STATE_DIR / "plan.json"
CATALOGUE_PATH = STATE_DIR / "catalogue.json"

BASE_URL = os.environ.get("OMLX_BASE_URL", "http://127.0.0.1:8001").rstrip("/")

# Modalities that record model rows. Ordered so the driver can schedule the
# cheap ones first; `generative-text` is the expensive one.
MODALITIES = ["generative-text", "ocr", "decision", "voice", "image-generation"]

# A model whose smallest fitting build exceeds this cannot run on an
# M4 Max / 128 GB at any quant. The resident ceiling is what binds, not disk.
RESIDENT_CEILING_GB = 96.0


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def api(path: str, timeout: float = 60.0):
    """GET a JSON endpoint on the oMLX server."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.URLError as e:
        raise SystemExit(f"server unreachable at {BASE_URL}: {e}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"non-JSON from {path}: {e}")


def installed_version() -> str:
    try:
        return api("/api/status", timeout=10).get("version", "unknown")
    except SystemExit:
        raise
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------
# results inventory
# --------------------------------------------------------------------------
def _rows(modality: str) -> list[dict]:
    path = RESULTS / f"{modality}.csv"
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _norm(model: str) -> str:
    """Reduce a results-table model id to a comparable bare name.

    Rows appear as `Jundot/Qwen3.8-27B-oQ4e-mtp`, `Qwen3.8-27B-oQ4e-mtp`, or
    with a ` (baseline)` suffix. The bare name is what oMLX uses as a model id.
    """
    name = model.split("/")[-1].strip()
    return re.sub(r"\s*\((baseline|.*?)\)\s*$", "", name, flags=re.I).strip()


def inventory() -> dict:
    """Every model that already has a row, per modality, with its recorded row."""
    inv: dict[str, dict] = {}
    for modality in MODALITIES:
        for row in _rows(modality):
            key = _norm(row.get("Model", ""))
            if not key:
                continue
            entry = inv.setdefault(key, {"name": key, "modalities": {}})
            entry["modalities"][modality] = {
                "raw_model": row.get("Model"),
                "quant": row.get("Quant"),
                "notes": row.get("Notes", ""),
            }
    return inv


# An oMLX version as it appears in prose: `0.7.3`, `0.7.3rc1`, `0.7.4.dev1`.
# The leading `0.7` is required so unrelated dependency versions (e.g.
# `mlx-vlm 0.7.11`) are not mistaken for a server version.
_OMLX_VERSION = re.compile(r"\b0\.7\.\d+(?:rc\d+|\.dev\d+|[a-z]{2,4}\d+)?\b")
# Third-party packages that ship their own `0.7.x`; a version immediately after
# one of these is not an oMLX version.
_FOREIGN = re.compile(r"(mlx-vlm|mlx_vlm|mlx-audio|mlx_audio|mlx-audio)\s*"
                      r"$", re.I)


def _extract_versions(text: str) -> list[str]:
    """oMLX versions mentioned in `text`, ignoring dependency versions."""
    out = []
    for m in _OMLX_VERSION.finditer(text):
        before = text[: m.start()]
        if _FOREIGN.search(before):
            continue
        out.append(m.group(0))
    return out


def version_stamps() -> dict[str, list[str]]:
    """Which oMLX version each results row was recorded against.

    The schema has no dedicated version column, so the version is read from
    `Notes` where a row records it, and from each `results/<model>/final.json`
    when present. Rows with no stamp are reported as `unknown` rather than
    silently assumed current.
    """
    stamps: dict[str, list[str]] = {}
    for modality in MODALITIES:
        for row in _rows(modality):
            key = _norm(row.get("Model", ""))
            text = " ".join(str(v) for v in row.values())
            found = _extract_versions(text)
            if found:
                stamps.setdefault(key, []).extend(found)

    for final in RESULTS.glob("*/final.json"):
        try:
            data = json.loads(final.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        key = _norm(data.get("model_id") or data.get("repo_id") or final.parent.name)
        found = _extract_versions(json.dumps(data))
        if found:
            stamps.setdefault(key, []).extend(found)
    return {k: sorted(set(v)) for k, v in stamps.items()}


# --------------------------------------------------------------------------
# server model set
# --------------------------------------------------------------------------
def discovered_models() -> dict[str, dict]:
    """Locally registered models, keyed by bare id."""
    out = {}
    for m in api("/admin/api/models").get("models", []):
        if str(m.get("model_path", "")).startswith("builtin://"):
            continue
        name = _norm(m.get("id") or m.get("display_name") or "")
        entry = {
            "id": m.get("id"),
            "name": name,
            "model_type": m.get("model_type"),
            "config_model_type": m.get("config_model_type"),
            "estimated_size_formatted": m.get("estimated_size_formatted"),
            "model_path": m.get("model_path"),
            "loaded": bool(m.get("loaded")),
        }
        out[name] = entry
    return out


# --------------------------------------------------------------------------
# discovery — the part that must run on every release
# --------------------------------------------------------------------------
def hf_search(query: str, limit: int = 10) -> list[dict]:
    """Search Hugging Face through the server. Returns [] on any failure."""
    path = "/admin/api/hf/search?" + urllib.parse.urlencode(
        {"q": query, "limit": limit}
    )
    try:
        return api(path, timeout=45).get("models", [])
    except SystemExit:
        raise
    except Exception:
        return []


def hf_model_info(repo_id: str) -> dict | None:
    """Size / support metadata for one repo, or None if it does not exist."""
    path = "/admin/api/hf/model-info?" + urllib.parse.urlencode({"repo_id": repo_id})
    try:
        return api(path, timeout=45)
    except SystemExit as e:
        # A 404 is a legitimate "not published yet", not a fatal error.
        if "not found" in str(e).lower():
            return None
        raise
    except Exception:
        return None


def _size_gb(info: dict | None) -> float | None:
    if not info:
        return None
    b = info.get("download_all_size") or info.get("size")
    return round(b / 1024**3, 1) if b else None


# Repos that are fragments or re-cuts, never a runnable whole model. An
# "overlay" is a delta on top of another repo, and an adapter is not a model.
_FRAGMENT = re.compile(r"overlay|adapter|lora|gguf|mlx-serve|"
                       r"glade|abliterat|uncensored|reap", re.I)

# Publishers whose builds are the reference for this campaign's results.
# A Jundot oQ build is what has always been benchmarked here; a build from an
# unknown uploader is a different product, not a cheaper variant of it.
_TRUSTED = ("jundot/", "mlx-community/")


def _candidate_ok(repo_id: str, info: dict) -> bool:
    """Whether a HF repo is a plausible whole model worth cataloguing."""
    rid = repo_id.lower()
    if not rid.startswith(_TRUSTED):
        return False
    if _FRAGMENT.search(rid):
        return False
    if info.get("unsupported_reason") or info.get("is_adapter"):
        return False
    # A whole model this small is a partial upload or a metadata mismatch;
    # the smallest legitimate entry in this campaign is a ~1.2 GB reranker.
    if (_size_gb(info) or 0) < 1.2:
        return False
    return True


def reprobe(entry: dict, release_families: list[str]) -> dict:
    """Re-check one catalogue entry against Hugging Face.

    `entry` carries `repo_id` (what was checked last time), `family` (what to
    search for if that repo is gone), and `smallest_gb` (what the smallest build
    cost last time). The result always says *why* a verdict was reached, so a
    future run does not have to re-derive it.
    """
    repo_id = entry.get("repo_id")
    family = entry.get("family") or (repo_id.split("/")[-1] if repo_id else "")
    result = dict(entry)
    result["checked_with"] = installed_version()
    result["attempts"] = []

    if repo_id:
        info = hf_model_info(repo_id)
        result["attempts"].append({"repo_id": repo_id, "found": info is not None,
                                   "size_gb": _size_gb(info)})
        if info:
            result["unsupported_reason"] = info.get("unsupported_reason")
            result["smallest_gb"] = _size_gb(info)
            result["verdict"] = _verdict(result["smallest_gb"],
                                         result.get("unsupported_reason"))
            return result

    # The exact repo is gone or was never pinned: search the family for any
    # smaller build that might now fit.
    best = None
    for cand in hf_search(family, limit=20):
        info = hf_model_info(cand["repo_id"])
        if not info:
            continue
        gb = _size_gb(info)
        result["attempts"].append({"repo_id": cand["repo_id"], "found": True,
                                   "size_gb": gb})
        if not _candidate_ok(cand["repo_id"], info):
            continue
        if best is None or gb < best["size_gb"]:
            best = {"repo_id": cand["repo_id"], "size_gb": gb,
                    "params": info.get("params_formatted")}

    if best:
        result["best_candidate"] = best
        result["smallest_gb"] = best["size_gb"]
        result["verdict"] = _verdict(best["size_gb"], None)
    else:
        result["verdict"] = "absent"

    result["now_fits"] = result["verdict"] == "fits"
    return result


def _verdict(size_gb: float | None, unsupported: str | None) -> str:
    if unsupported:
        return "unsupported"
    if size_gb is None:
        return "absent"
    # Download size is the conservative proxy: an oQ quant's on-disk size is
    # within a few GB of its resident footprint, and resident size is what
    # actually bounds a 128 GB machine.
    return "fits" if size_gb <= RESIDENT_CEILING_GB else "too-large"


def release_families(tag: str) -> list[str]:
    """Model families named by a release.

    The release body is not readable from a static page reliably (images,
    truncated notes), so families are supplied explicitly by the operator via
    `--family` and persisted here for the next run. This function returns what
    is already known plus anything passed in.
    """
    return []


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def load_catalogue() -> dict:
    if CATALOGUE_PATH.is_file():
        try:
            return json.loads(CATALOGUE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {"entries": [], "history": []}


def save_catalogue(cat: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    CATALOGUE_PATH.write_text(json.dumps(cat, indent=2) + "\n")


def cmd_status(args) -> int:
    version = installed_version()
    inv = inventory()
    local = discovered_models()
    stamps = version_stamps()
    cat = load_catalogue()

    stale = {k: v for k, v in stamps.items() if version not in v}

    print(f"installed oMLX : {version}")
    print(f"server URL     : {BASE_URL}")
    print(f"models on disk : {len(local)}")
    print(f"catalogued rows: {len(inv)}")
    print()

    print("Per modality:")
    for modality in MODALITIES:
        rows = _rows(modality)
        print(f"  {modality:<18} {len(rows):>3} rows")
    print()

    if not stamps:
        print("No results row records an oMLX version yet.")
        print("Treat every row as stale and re-profile it against "
              f"{version}.")
    else:
        print("Models whose recorded version is not the installed one:")
        for name in sorted(stale):
            print(f"  {name:<34} recorded {', '.join(stamps[name])}")
        if not stale:
            print("  (none — every stamped row matches the installed version)")
    print()

    blocked = [e for e in cat.get("entries", []) if e.get("verdict") != "fits"]
    if blocked:
        print(f"Catalogue: {len(blocked)} model(s) previously unavailable for this Mac")
        for e in blocked:
            print(f"  {e.get('name','?'):<34} {e.get('verdict'):<12} "
                  f"{e.get('smallest_gb','?')} GB")
    else:
        print("Catalogue: empty — run `discover` to record today's unobtainable models.")
    return 0


def cmd_discover(args) -> int:
    cat = load_catalogue()
    entries = cat.get("entries", [])
    if not args.family:
        print("No --family given; re-probing every existing catalogue entry only.")
    for fam in args.family:
        if not any(e.get("family") == fam for e in entries):
            entries.append({"name": fam, "family": fam, "repo_id": None,
                            "verdict": "absent", "smallest_gb": None})

    families = [e.get("family") for e in entries if e.get("family")]
    out = []
    for entry in entries:
        print(f"  probing {entry.get('name','?')} ...", end=" ", flush=True)
        r = reprobe(entry, families)
        was = entry.get("verdict")
        r["first_seen"] = entry.get("first_seen") or installed_version()
        print(f"{r.get('verdict')} ({r.get('smallest_gb')} GB)"
              + ("  <-- CHANGED" if was and was != r.get("verdict") else ""))
        out.append(r)

    cat["entries"] = out
    cat.setdefault("history", []).append({
        "version": installed_version(),
        "reprobed": len(out),
        "now_fitting": [e["name"] for e in out if e.get("now_fits")],
    })
    save_catalogue(cat)
    print(f"\nWrote {CATALOGUE_PATH.relative_to(REPO_ROOT)}")
    return 0


def cmd_plan(args) -> int:
    version = installed_version()
    inv = inventory()
    local = discovered_models()
    stamps = version_stamps()
    cat = load_catalogue()

    to_reprofile = []
    for name, meta in sorted(inv.items()):
        recorded = stamps.get(name, [])
        # With no stamp anywhere in the repo, every row is unverified against
        # the installed version, so `stale` degenerates to "all".
        if args.scope == "all" or version not in recorded:
            present = name in local
            to_reprofile.append({
                "name": name,
                "modalities": sorted(meta["modalities"]),
                "recorded_version": recorded,
                "on_disk": present,
                "model_id": local[name]["id"] if present else None,
                "reason": ("version-stamp mismatch" if recorded
                           else "no version stamp recorded"),
            })

    # Catalogued models that now fit are the highest-value work: they are the
    # ones a previous release literally could not run.
    newly_fitting = [e for e in cat.get("entries", [])
                     if e.get("now_fits") and e.get("best_candidate")]

    plan = {
        "generated_for_version": version,
        "scope": args.scope,
        "reprofile": to_reprofile,
        "download": [
            {"name": e["name"], "repo_id": e["best_candidate"]["repo_id"],
             "size_gb": e["best_candidate"]["size_gb"]}
            for e in newly_fitting
        ],
        "not_feasible": [
            {"name": e.get("name"), "verdict": e.get("verdict"),
             "smallest_gb": e.get("smallest_gb"),
             "evidence": e.get("best_candidate") or e.get("repo_id")}
            for e in cat.get("entries", []) if e.get("verdict") in
            ("too-large", "unsupported", "absent")
        ],
    }
    STATE_DIR.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2) + "\n")

    print(f"plan for oMLX {version} (scope={args.scope})")
    print(f"  re-profile : {len(plan['reprofile'])} model(s)")
    for row in plan["reprofile"]:
        print(f"      {row['name']:<34} {','.join(row['modalities']):<28} "
              f"{'on disk' if row['on_disk'] else 'MISSING'}")
    print(f"  download   : {len(plan['download'])} newly-fitting model(s)")
    for row in plan["download"]:
        print(f"      {row['repo_id']:<44} {row['size_gb']} GB")
    print(f"  not feasible: {len(plan['not_feasible'])} catalogued model(s)")
    print(f"\nWrote {PLAN_PATH.relative_to(REPO_ROOT)}")
    return 0


def cmd_catalog(args) -> int:
    cat = load_catalogue()
    entries = cat.get("entries", [])
    if not entries:
        print("catalogue is empty — run `discover` first")
        return 0
    print(f"{'name':<40} {'verdict':<12} {'smallest':<10} {'checked':<14} repo")
    for e in entries:
        print(f"{e.get('name','?'):<40} {e.get('verdict','?'):<12} "
              f"{str(e.get('smallest_gb','?'))+' GB':<10} "
              f"{e.get('checked_with','?'):<14} "
              f"{(e.get('best_candidate') or {}).get('repo_id') or e.get('repo_id')}")
    return 0


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="installed vs recorded version, inventory")

    d = sub.add_parser("discover", help="re-probe catalogued models on Hugging Face")
    d.add_argument("--tag", help="release tag this run is for, e.g. v0.7.4.dev1")
    d.add_argument("--family", action="append", default=[],
                   help="model family to (re)catalogue; repeatable")

    p = sub.add_parser("plan", help="write .reprofile/plan.json")
    p.add_argument("--scope", choices=["all", "stale"], default="stale",
                   help="all models, or only those whose version stamp is stale")

    sub.add_parser("catalog", help="print the unobtainable-model catalogue")

    args = ap.parse_args()
    handler = {"status": cmd_status, "discover": cmd_discover,
               "plan": cmd_plan, "catalog": cmd_catalog}[args.cmd]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
