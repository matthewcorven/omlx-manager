#!/usr/bin/env python3
"""Coordinator-side claim check: stream one request and show the real output.

Tuning agents have returned confident wrong conclusions (an inverted
activation-precision finding, a reasoning-budget artifact read as corruption, a
fault blamed on a saturated cache that was only half the cause). This script
exists so the coordinator can re-measure a headline claim against the live
server and *read the text* before recording it.

It prints TTFT, time-to-first-content-token, decode tok/s, reasoning length,
finish_reason, and the actual completion text, so a "large speedup" can be
distinguished from a model that never entered its reasoning phase.

Usage:
    python3 scripts/verify_claim.py --model <id>
    python3 scripts/verify_claim.py --model <id> --runs 3 --max-tokens 400
    python3 scripts/verify_claim.py --model <id> --prompt "Write a binary search"
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PROMPT = (
    "Write a Python function `merge_intervals(intervals)` that merges "
    "overlapping closed intervals and returns them sorted. Include a docstring "
    "and three doctest examples. Output only the code."
)


def stream_once(base: str, model: str, prompt: str, max_tokens: int,
                temperature: float, timeout: float) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    ttft = ttfc = last = None
    content: list[str] = []
    reasoning: list[str] = []
    usage = None
    finish = None

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("usage"):
                usage = obj["usage"]
            for choice in obj.get("choices") or []:
                delta = choice.get("delta") or {}
                now = time.perf_counter()
                if delta.get("reasoning_content"):
                    ttft = ttft or now - t0
                    last = now
                    reasoning.append(delta["reasoning_content"])
                piece = delta.get("content")
                if piece:
                    ttft = ttft or now - t0
                    ttfc = ttfc or now - t0
                    last = now
                    content.append(piece)
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]

    if ttft is None:
        raise RuntimeError("no tokens received (neither reasoning nor content)")

    completion_tokens = (usage or {}).get("completion_tokens") or (
        len(content) + len(reasoning))
    span = (last - t0 - ttft) if last else 0.0
    return {
        "ttft_ms": round(ttft * 1000, 1),
        "ttfc_ms": round(ttfc * 1000, 1) if ttfc is not None else None,
        "decode_tps": round((completion_tokens - 1) / span, 2) if span > 0 else 0.0,
        "total_ms": round((time.perf_counter() - t0) * 1000, 1),
        "prompt_tokens": (usage or {}).get("prompt_tokens"),
        "completion_tokens": completion_tokens,
        "reasoning_chars": len("".join(reasoning)),
        "finish_reason": finish,
        "text": "".join(content),
        "reasoning_head": "".join(reasoning)[:400],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--out")
    args = ap.parse_args()

    runs = []
    for i in range(args.runs):
        try:
            r = stream_once(args.base, args.model, args.prompt, args.max_tokens,
                            args.temperature, args.timeout)
        except urllib.error.HTTPError as e:
            print(f"run {i+1}: HTTP {e.code}: "
                  f"{e.read().decode('utf-8', 'replace')[:800]}", file=sys.stderr)
            return 2
        except Exception as e:  # noqa: BLE001
            print(f"run {i+1}: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        runs.append(r)
        print(f"run {i+1}: ttft={r['ttft_ms']}ms ttfc={r['ttfc_ms']}ms "
              f"decode={r['decode_tps']}tps total={r['total_ms']}ms "
              f"ct={r['completion_tokens']} reasoning_chars={r['reasoning_chars']} "
              f"finish={r['finish_reason']}")

    summary = {
        "model": args.model,
        "runs": args.runs,
        "max_tokens": args.max_tokens,
        "ttft_ms_median": round(statistics.median(r["ttft_ms"] for r in runs), 1),
        "ttfc_ms_median": (round(statistics.median(r["ttfc_ms"] for r in runs), 1)
                           if all(r["ttfc_ms"] is not None for r in runs) else None),
        "decode_tps_median": round(statistics.median(r["decode_tps"] for r in runs), 2),
        "samples": runs,
    }
    print()
    print("--- actual output (read this before believing any number) ---")
    print(runs[-1]["text"] or "<EMPTY CONTENT>")
    if runs[-1]["reasoning_chars"]:
        print("--- reasoning head ---")
        print(runs[-1]["reasoning_head"])
    print()
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
