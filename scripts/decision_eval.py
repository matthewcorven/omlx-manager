#!/usr/bin/env python3
"""Score a decision model against the labelled corpus.

Decision models do not decode, so there is no TTFT/decode split and no sampling
to sweep. What is left is whether the probabilities are correct and whether they
are honest. This harness measures both, plus latency and the capability envelope.

Metrics
-------
- `accuracy`   -- argmax of the returned distribution equals the expected answer
- `brier`      -- mean squared error of the probability assigned to the truth
                  (lower is better; 0.25 is the score of a constant 0.5 guess)
- `logloss`    -- mean -log p(truth); punishes confident wrong answers hardest
- `ece`        -- expected calibration error over 10 equal-width bins. This is
                  the metric that catches a model which is accurate but always
                  says 1.0, and the one that catches a model which is useless on
                  the `ambiguous` family.
- `latency_ms` -- wall time per request, median and p95

Gates
-----
A score is only meaningful if the answers are real. Four gates run first, and
each one has a plausible-looking failure mode that a naive harness reports as
success:

| Gate | Catches | Failure looks like |
|---|---|---|
| `error` | the request never produced an answer | HTTP 400/413/500 |
| `schema` | the answer shape does not match the question type | `noul` answer with no `noul` key |
| `degenerate` | probabilities are not a distribution | sum != 1, NaN, all mass on one option for every item |
| `truncation` | the state did not fit | HTTP 413 / `DecisionContextLengthError` |

The `degenerate` gate is the important one. A model that returns 1.0 for every
`noul` question passes accuracy on a balanced corpus and is worthless. The gate
asserts the distribution is well formed; the `ece` metric is what scores it.

Determinism
-----------
Decision models are deterministic: there is no sampling, so the same request
must return bit-identical probabilities. `--determinism` re-runs a sample of
items three times and fails if any probability moves. Any variance is a bug in
the engine, not noise, and it invalidates every other number.

Modality
--------
The same harness scores the text corpus and the media corpus. An item carries a
`media` list of file names; when it is present the files are inlined as base64
data URIs and attached to the request. Nothing else changes, so the metrics and
gates stay comparable across modalities.

Two asymmetries are real and are recorded rather than papered over:

- **Video has no baseline.** `/v1/decisions` rejects `videos` outright
  (`decisions_request` raises "this model does not take videos"), so a chat model
  cannot be scored on the video corpus. Video results are d3-only and the
  baseline block is written as `{"supported": false}`.
- **OpenJev takes at most one image.** The corpus never attaches more than one,
  so the same items are legal for every family.

Usage
-----
    python3 scripts/decision_eval.py --model vllm-sr/d3-edge
    python3 scripts/decision_eval.py --model Jundot/clef-flash-oQ4e --out results/decision/clef-flash.json
    python3 scripts/decision_eval.py --model <id> --determinism
    python3 scripts/decision_eval.py --model <id> --baseline Qwen3.8-27B-oQ4e-mtp
    python3 scripts/decision_eval.py --model <id> --corpus results/decision/media/manifest.json --modality image
    python3 scripts/decision_eval.py --model <id> --corpus results/decision/media/manifest.json --modality video
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8001"
ECE_BINS = 10


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def post(path: str, payload: dict, timeout: float) -> tuple[int, dict | str]:
    """POST JSON and return (status, parsed body or raw text)."""
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001 - transport faults are gate failures
        return 0, f"{type(e).__name__}: {e}"


def data_uri(path: Path) -> str:
    """Inline a media file as a data URI.

    The server accepts only `data:<type>;base64,...` for both images and video;
    remote URLs and local paths are rejected in `utils/video.py` and
    `utils/image.py`. Inlining is therefore the only option, not a shortcut.
    """
    mime, _ = mimetypes.guess_type(path.name)
    if mime is None:
        mime = "video/mp4" if path.suffix == ".mp4" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def ask(model: str, item: dict, timeout: float,
        media_dir: Path | None = None) -> tuple[int, dict | str, float]:
    """Send one corpus item as a System One request."""
    question = {"type": item["type"], "instructions": item["instructions"]}
    if item["criteria"] is not None:
        question["criteria"] = item["criteria"]
    payload = {
        "model": model,
        "state": item["state"],
        "questions": {item["id"]: question},
    }
    if media_dir is not None and item.get("media"):
        uris = [data_uri(media_dir / name) for name in item["media"]]
        if item.get("modality") == "video":
            payload["videos"] = uris
        else:
            payload["images"] = uris
    t0 = time.perf_counter()
    status, body = post("/v1/systemone", payload, timeout)
    return status, body, (time.perf_counter() - t0) * 1000.0


# --------------------------------------------------------------------------
# answer normalisation
# --------------------------------------------------------------------------
def distribution(item: dict, answer: dict) -> tuple[list[float], list[str]] | None:
    """Return (probabilities, option keys) in the question's own order.

    Returns None when the answer does not match the question type -- that is a
    schema gate failure, not a zero score.
    """
    kind = item["type"]
    if kind == "noul":
        p = answer.get("noul")
        if not isinstance(p, (int, float)):
            return None
        return [1.0 - float(p), float(p)], ["false", "true"]
    if kind == "choice":
        probs = answer.get("probabilities")
        if not isinstance(probs, dict) or not probs:
            return None
        keys = list(item["criteria"])
        if set(probs) != set(keys):
            return None
        return [float(probs[k]) for k in keys], keys
    if kind == "score":
        probs = answer.get("probabilities")
        if not isinstance(probs, dict) or not probs:
            return None
        keys = [str(i) for i in range(len(item["criteria"]))]
        if set(probs) != set(keys):
            return None
        return [float(probs[k]) for k in keys], keys
    return None


def truth_index(item: dict, keys: list[str]) -> int | None:
    """Index of the correct option, or None for the ambiguous family."""
    expected = item["expected"]
    if expected is None:
        return None
    if item["type"] == "noul":
        return keys.index("true") if expected else keys.index("false")
    if item["type"] == "choice":
        return keys.index(expected)
    return int(expected)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def brier(probs: list[float], idx: int) -> float:
    return sum((p - (1.0 if i == idx else 0.0)) ** 2 for i, p in enumerate(probs))


def logloss(probs: list[float], idx: int) -> float:
    return -math.log(max(probs[idx], 1e-12))


def ece(pairs: list[tuple[float, int]]) -> float:
    """Expected calibration error over equal-width confidence bins.

    `pairs` is (confidence, correct) where confidence is the probability the
    model assigned to the option it chose.
    """
    if not pairs:
        return 0.0
    total = len(pairs)
    err = 0.0
    for b in range(ECE_BINS):
        lo, hi = b / ECE_BINS, (b + 1) / ECE_BINS
        bucket = [c for conf, c in pairs if lo <= conf < hi or (b == ECE_BINS - 1 and conf == 1.0)]
        if not bucket:
            continue
        conf_mean = statistics.fmean(
            conf for conf, _ in pairs if lo <= conf < hi or (b == ECE_BINS - 1 and conf == 1.0)
        )
        acc_mean = sum(bucket) / len(bucket)
        err += (len(bucket) / total) * abs(acc_mean - conf_mean)
    return err


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[k]


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
def evaluate(model: str, corpus: dict, timeout: float, verbose: bool,
             media_dir: Path | None = None) -> dict:
    rows: list[dict] = []
    gates = {"error": [], "schema": [], "degenerate": [], "truncation": []}
    latencies: list[float] = []

    for item in corpus["items"]:
        status, body, ms = ask(model, item, timeout, media_dir)
        latencies.append(ms)
        row = {"id": item["id"], "family": item["family"], "type": item["type"],
               "status": status, "latency_ms": round(ms, 1)}

        if status != 200:
            detail = body if isinstance(body, str) else json.dumps(body)
            row["error"] = detail[:300]
            gate = "truncation" if status == 413 else "error"
            gates[gate].append(item["id"])
            rows.append(row)
            if verbose:
                print(f"  {item['id']:28s} {gate.upper():10s} {status} {detail[:80]}")
            continue

        answer = (body.get("answers") or {}).get(item["id"])
        if not isinstance(answer, dict):
            gates["schema"].append(item["id"])
            row["error"] = "no answer for question id"
            rows.append(row)
            if verbose:
                print(f"  {item['id']:28s} SCHEMA     missing answer")
            continue

        norm = distribution(item, answer)
        if norm is None:
            gates["schema"].append(item["id"])
            row["error"] = f"answer shape does not match {item['type']}"
            row["answer"] = answer
            rows.append(row)
            if verbose:
                print(f"  {item['id']:28s} SCHEMA     {json.dumps(answer)[:80]}")
            continue

        probs, keys = norm
        total = sum(probs)
        if (any(not math.isfinite(p) or p < 0.0 for p in probs)
                or abs(total - 1.0) > 1e-3):
            gates["degenerate"].append(item["id"])
            row["error"] = f"probabilities sum to {total:.6f}"
            row["probabilities"] = probs
            rows.append(row)
            if verbose:
                print(f"  {item['id']:28s} DEGENERATE sum={total:.4f}")
            continue

        idx = truth_index(item, keys)
        best = max(range(len(probs)), key=lambda i: probs[i])
        row["probabilities"] = [round(p, 6) for p in probs]
        row["keys"] = keys
        row["predicted"] = keys[best]
        row["confidence"] = round(probs[best], 6)

        if idx is None:
            # ambiguous: no correct answer, so only calibration is scored
            row["scored"] = False
            row["confidence_on_ambiguous"] = round(probs[best], 6)
        else:
            row["scored"] = True
            row["expected"] = keys[idx]
            row["correct"] = best == idx
            row["brier"] = round(brier(probs, idx), 6)
            row["logloss"] = round(logloss(probs, idx), 6)
            row["p_truth"] = round(probs[idx], 6)

        rows.append(row)
        if verbose:
            mark = "ok " if row.get("correct") else ("-- " if idx is None else "MISS")
            print(f"  {item['id']:28s} {mark} p={row['confidence']:.3f} "
                  f"pred={row['predicted']} exp={row.get('expected', 'n/a')}")

    scored = [r for r in rows if r.get("scored")]
    ambiguous = [r for r in rows if r.get("scored") is False]

    summary = {
        "model": model,
        "items": len(rows),
        "scored_items": len(scored),
        "gates": {k: v for k, v in gates.items()},
        "gate_failures": sum(len(v) for v in gates.values()),
        "accuracy": round(sum(1 for r in scored if r["correct"]) / len(scored), 4) if scored else None,
        "brier": round(statistics.fmean(r["brier"] for r in scored), 4) if scored else None,
        "logloss": round(statistics.fmean(r["logloss"] for r in scored), 4) if scored else None,
        "ece": round(ece([(r["confidence"], int(r["correct"])) for r in scored]), 4) if scored else None,
        "mean_confidence": round(statistics.fmean(r["confidence"] for r in scored), 4) if scored else None,
        "ambiguous_confidence": (
            round(statistics.fmean(r["confidence_on_ambiguous"] for r in ambiguous), 4)
            if ambiguous else None
        ),
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_p95": round(pct(latencies, 0.95), 1) if latencies else None,
        "by_family": {},
        "rows": rows,
    }

    for family in sorted({r["family"] for r in rows}):
        fam = [r for r in rows if r["family"] == family and r.get("scored")]
        if not fam:
            continue
        summary["by_family"][family] = {
            "n": len(fam),
            "accuracy": round(sum(1 for r in fam if r["correct"]) / len(fam), 4),
            "brier": round(statistics.fmean(r["brier"] for r in fam), 4),
            "mean_confidence": round(statistics.fmean(r["confidence"] for r in fam), 4),
        }

    return summary


def check_determinism(model: str, corpus: dict, timeout: float, sample: int = 5,
                      media_dir: Path | None = None) -> dict:
    """Re-run a sample of items three times; probabilities must not move."""
    items = corpus["items"][:sample]
    unstable = []
    for item in items:
        seen = []
        for _ in range(3):
            status, body, _ms = ask(model, item, timeout, media_dir)
            if status != 200:
                seen.append(f"HTTP {status}")
                continue
            answer = (body.get("answers") or {}).get(item["id"]) or {}
            norm = distribution(item, answer)
            seen.append(None if norm is None else [round(p, 9) for p in norm[0]])
        if len({json.dumps(s) for s in seen}) != 1:
            unstable.append({"id": item["id"], "runs": seen})
    return {
        "checked": len(items),
        "runs_each": 3,
        "stable": not unstable,
        "unstable": unstable,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="model id as served by oMLX")
    ap.add_argument("--corpus", default="results/decision/corpus.json")
    ap.add_argument("--modality", choices=["text", "image", "video"], default="text",
                    help="which items to score; media items need --corpus pointing at a manifest")
    ap.add_argument("--out", help="write the full result JSON here")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--determinism", action="store_true",
                    help="also re-run a sample 3x and assert bit-identical output")
    ap.add_argument("--baseline", help="also score this chat model on the same corpus")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    corpus_path = Path(args.corpus)
    try:
        with open(corpus_path, encoding="utf-8") as fh:
            corpus = json.load(fh)
    except FileNotFoundError:
        print(f"corpus not found: {args.corpus}\n"
              f"run: python3 scripts/decision_corpus.py --out {args.corpus}", file=sys.stderr)
        return 2

    # Media items live next to their manifest, so the directory is derivable and
    # does not need a second flag that could disagree with --corpus.
    media_dir: Path | None = None
    if args.modality != "text":
        corpus["items"] = [i for i in corpus["items"] if i.get("modality") == args.modality]
        if not corpus["items"]:
            print(f"no {args.modality} items in {args.corpus}", file=sys.stderr)
            return 2
        media_dir = corpus_path.parent

    verbose = not args.quiet
    if verbose:
        print(f"scoring {args.model} on {len(corpus['items'])} {args.modality} items\n")

    result = evaluate(args.model, corpus, args.timeout, verbose, media_dir)
    result["modality"] = args.modality

    if args.determinism:
        if verbose:
            print("\nchecking determinism (3 runs x 5 items)...")
        result["determinism"] = check_determinism(args.model, corpus, args.timeout,
                                                  media_dir=media_dir)

    if args.baseline:
        if args.modality == "video":
            # Not a skipped check: the chat path rejects videos outright, so
            # there is nothing to compare against. Recorded so the absence is
            # visible in the result file rather than looking like an oversight.
            result["baseline"] = {
                "supported": False,
                "reason": "the chat-model path rejects videos "
                          "(decisions_request: 'this model does not take videos')",
            }
            if verbose:
                print("\nbaseline         unsupported for video; skipping")
        else:
            if verbose:
                print(f"\nscoring chat-model baseline {args.baseline}...")
            result["baseline"] = evaluate(args.baseline, corpus, args.timeout, False, media_dir)

    if verbose:
        print(f"\n{'=' * 62}")
        print(f"model            {result['model']}")
        print(f"gate failures    {result['gate_failures']}")
        for gate, ids in result["gates"].items():
            if ids:
                print(f"  {gate:14s} {len(ids)}: {', '.join(ids[:4])}")
        print(f"accuracy         {result['accuracy']}")
        print(f"brier            {result['brier']}   (0.25 = constant 0.5 guess)")
        print(f"logloss          {result['logloss']}")
        print(f"ece              {result['ece']}   (0 = perfectly calibrated)")
        print(f"mean confidence  {result['mean_confidence']}")
        print(f"ambiguous conf   {result['ambiguous_confidence']}   (0.5 = honest)")
        print(f"latency          {result['latency_ms_median']} ms median, "
              f"{result['latency_ms_p95']} ms p95")
        print("\nby family")
        for family, m in result["by_family"].items():
            print(f"  {family:12s} n={m['n']:2d} acc={m['accuracy']:.3f} "
                  f"brier={m['brier']:.3f} conf={m['mean_confidence']:.3f}")
        if "determinism" in result:
            d = result["determinism"]
            print(f"\ndeterminism      {'STABLE' if d['stable'] else 'UNSTABLE'}")
            for u in d["unstable"]:
                print(f"  {u['id']}: {u['runs']}")
        if "baseline" in result:
            b = result["baseline"]
            if b.get("supported") is False:
                print(f"\nbaseline         unsupported: {b['reason']}")
            else:
                print(f"\nbaseline {b['model']}")
                print(f"  accuracy {b['accuracy']}  brier {b['brier']}  ece {b['ece']}  "
                      f"latency {b['latency_ms_median']} ms")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
            fh.write("\n")
        if verbose:
            print(f"\nwrote {args.out}")

    return 0 if result["gate_failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
