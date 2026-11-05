#!/usr/bin/env python3
"""Re-measure a model on the currently installed oMLX and record the delta.

This is the execution half of `omlx-release-reprofile`. It does not decide
*which* settings are best — those were decided by the original tuning pass. It
answers a narrower question: **does the installed server produce different
numbers on the settings we already chose, and did any of those settings stop
being applied?**

That distinction matters because a new release can change behaviour without
changing settings:

- throughput may move because kernels changed (0.7.4: DeepSeek prefilled 43%
  faster, Qwen3.8 Flash-Next decoded 3-5% faster after long prompts);
- a setting may silently stop sticking (a real, previously observed failure:
  `enable_thinking` reverted to `true` on its own);
- a capability flag may change (`mtp_compatible`, `dflash_compatible`), which
  invalidates part of the old sweep.

So each model goes through: verify applied settings -> load -> warmup ->
N paired runs -> compare against recorded medians -> write a delta report.

Usage
-----
  python3 reprofile_model.py --model Qwen3.8-27B-oQ4e-mtp
  python3 reprofile_model.py --model flint-oQ4e --runs 5
  python3 reprofile_model.py --model X --dry-run

Exit codes: 0 measured, 1 refused (settings drifted / load failed), 2 error.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import measure  # noqa: E402  the repo's own harness, so units match results

BASE_URL = measure.omlx_config.BASE_URL
STATE_DIR = REPO_ROOT / ".reprofile"
RESULTS = REPO_ROOT / "results"


def api(path: str, timeout: float = 60.0):
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
        return json.load(r)


def post(path: str, body: dict | None = None, timeout: float = 600.0):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE_URL + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def version() -> str:
    return api("/api/status", timeout=10).get("version", "unknown")


def model_state(model_id: str) -> dict | None:
    for m in api("/admin/api/models").get("models", []):
        if m.get("id") == model_id:
            return m
    return None


def wait_loaded(model_id: str, want: bool, timeout: float = 900.0) -> bool:
    """Block until the model's loaded flag matches `want`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        m = model_state(model_id)
        if m and bool(m.get("loaded")) is want:
            return True
        time.sleep(2)
    return False


def bench_slot_free() -> bool:
    active = api("/admin/api/bench/active")
    ctx = api("/admin/api/bench/context/active")
    return not active.get("running") and not ctx.get("running")


def recorded_final(name: str) -> dict | None:
    """The model's recorded final.json, if the campaign produced one."""
    direct = RESULTS / name / "final.json"
    if direct.is_file():
        return json.loads(direct.read_text())
    for cand in RESULTS.glob("*/final.json"):
        try:
            data = json.loads(cand.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if (data.get("model_id") == name
                or (data.get("repo_id") or "").split("/")[-1] == name):
            return data
    return None


# Settings that must survive a release upgrade. These are the ones the campaign
# deliberately chose (thinking off everywhere; MTP per model). A flip here is a
# correctness problem, not a performance one, so it is checked before timing.
CRITICAL = ("enable_thinking", "mtp_enabled", "dflash_enabled",
            "turboquant_kv_enabled", "moe_expert_offload_enabled",
            "max_context_window")


def settings_drift(model_id: str, expected: dict) -> list[dict]:
    """Compare the live settings against the intended final config."""
    m = model_state(model_id) or {}
    live = m.get("settings") or {}
    drift = []
    for key in CRITICAL:
        if key not in expected:
            continue
        want = expected[key]
        got = live.get(key)
        # `null` means "engine default" and is a legitimate recorded value.
        if want != got:
            drift.append({"key": key, "expected": want, "live": got})
    return drift


def measure_runs(model_id: str, runs: int, max_tokens: int) -> dict:
    """N streaming runs through the repo harness, warmup discarded."""
    payload_base = {
        "model": model_id,
        "messages": [{"role": "user", "content": measure.DEFAULT_PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    # One discarded warmup: the first request after a load pays shader
    # compilation and (on 0.7.4) a one-time grammar-compiler build.
    try:
        measure.post_stream(BASE_URL, payload_base, 900.0)
    except Exception as e:  # noqa: BLE001
        return {"error": f"warmup failed: {type(e).__name__}: {e}"}

    samples = []
    for i in range(runs):
        try:
            samples.append(measure.post_stream(BASE_URL, payload_base, 900.0))
        except Exception as e:  # noqa: BLE001
            return {"error": f"run {i+1} failed: {type(e).__name__}: {e}"}

    def med(key):
        vals = [s[key] for s in samples if s.get(key) is not None]
        return round(statistics.median(vals), 2) if vals else None

    return {
        "runs": runs,
        "max_tokens": max_tokens,
        "ttft_ms": med("ttft_ms"),
        "decode_tps": med("decode_tps"),
        "total_ms": med("total_ms"),
        "prompt_tokens": samples[0].get("prompt_tokens"),
        "samples": samples,
    }


def pct(new: float | None, old: float | None) -> float | None:
    if not new or not old:
        return None
    return round((new - old) / old * 100, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="oMLX model id")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--dry-run", action="store_true",
                    help="check settings and load, do not time")
    ap.add_argument("--out", help="override output path")
    args = ap.parse_args()

    ver = version()
    m = model_state(args.model)
    if not m:
        print(f"refusing: model {args.model!r} is not registered on the server",
              file=sys.stderr)
        return 1

    rec = recorded_final(args.model)
    expected = (rec or {}).get("settings") or {}
    drift = settings_drift(args.model, expected)

    report = {
        "model_id": args.model,
        "omlx_version": ver,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recorded_version_stamp": (rec or {}).get("omlx_version"),
        "settings_drift": drift,
        "recorded": (rec or {}).get("final_medians"),
    }

    if drift:
        print("REFUSING to time: settings have drifted from the recorded "
              "final config.", file=sys.stderr)
        for d in drift:
            print(f"  {d['key']}: expected {d['expected']!r}, "
                  f"live {d['live']!r}", file=sys.stderr)
        print("Fix the settings (or record why they changed) before "
              "re-profiling, or the comparison is meaningless.", file=sys.stderr)
        report["status"] = "refused-settings-drift"
        _write(report, args, ver)
        return 1

    if args.dry_run:
        print(f"ok: {args.model} is registered, settings match, "
              f"would time {args.runs} runs on {ver}")
        return 0

    if not bench_slot_free():
        print("refusing: a benchmark or context benchmark is running",
              file=sys.stderr)
        return 2

    # Load explicitly and wait: a PUT with a reload key unloads without
    # reloading, and a cold model corrupts TTFT.
    if not m.get("loaded"):
        print(f"loading {args.model} ...", flush=True)
        post(f"/admin/api/models/{args.model}/load")
        if not wait_loaded(args.model, True):
            print("load timed out", file=sys.stderr)
            report["status"] = "load-timeout"
            _write(report, args, ver)
            return 2
    wait_loaded(args.model, True)

    print(f"timing {args.runs} runs (+1 warmup) ...", flush=True)
    result = measure_runs(args.model, args.runs, args.max_tokens)
    if "error" in result:
        print(result["error"], file=sys.stderr)
        report["status"] = "error"
        report["error"] = result["error"]
        _write(report, args, ver)
        return 2

    report["status"] = "measured"
    report["rerun"] = result
    rec_med = report.get("recorded") or {}
    report["delta"] = {
        "ttft_pct": pct(result.get("ttft_ms"), rec_med.get("ttft_ms")),
        "decode_pct": pct(result.get("decode_tps"), rec_med.get("decode_tps")),
    }
    print(json.dumps(report["rerun"], indent=2))
    print(f"delta vs recorded: "
          f"ttft {report['delta']['ttft_pct']}%  "
          f"decode {report['delta']['decode_pct']}%")
    _write(report, args, ver)
    return 0


def _write(report: dict, args, ver: str) -> None:
    out = Path(args.out) if args.out else (
        STATE_DIR / "rerun" / f"{args.model}.{ver}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"wrote {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}")


if __name__ == "__main__":
    raise SystemExit(main())
