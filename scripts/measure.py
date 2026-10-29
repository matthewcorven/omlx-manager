#!/usr/bin/env python3
"""Measure TTFT and decode throughput against an oMLX server.

Streams a chat completion and times the first content token and the last one.
Reports median over N runs. Designed for small-coding-task comparisons, so the
default prompt is a short code-writing request.

Usage:
    python3 scripts/measure.py --model <model_id> [--runs 3] [--out FILE]
    python3 scripts/measure.py --model <id> --smoke          # 1 run, tiny prompt
    python3 scripts/measure.py --model <id> --prompt-file p.txt
    python3 scripts/measure.py --model <id> --max-tokens 256 --context-pad 8000
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

SMOKE_PROMPT = "Reply with exactly: OK"


def post_stream(base: str, payload: dict, timeout: float) -> dict:
    """Send a streaming chat completion and time it."""
    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    ttft = None          # first token of any kind (reasoning or content)
    ttfc = None          # first *content* token
    last = None
    chunks = 0
    reasoning_chunks = 0
    text_parts: list[str] = []
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
                    if ttft is None:
                        ttft = now - t0
                    last = now
                    reasoning_chunks += 1
                piece = delta.get("content")
                if piece:
                    if ttft is None:
                        ttft = now - t0
                    if ttfc is None:
                        ttfc = now - t0
                    last = now
                    chunks += 1
                    text_parts.append(piece)
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]

    end = time.perf_counter()
    if ttft is None:
        raise RuntimeError("no tokens received (neither reasoning nor content)")

    prompt_tokens = (usage or {}).get("prompt_tokens")
    completion_tokens = (usage or {}).get("completion_tokens") or (chunks + reasoning_chunks)
    decode_span = (last - t0 - ttft) if last else 0.0
    decode_tps = (completion_tokens - 1) / decode_span if decode_span > 0 else 0.0

    return {
        "ttft_ms": round(ttft * 1000, 1),
        "ttfc_ms": round(ttfc * 1000, 1) if ttfc is not None else None,
        "decode_tps": round(decode_tps, 2),
        "prefill_tps": round(prompt_tokens / ttft, 1) if prompt_tokens and ttft else None,
        "total_ms": round((end - t0) * 1000, 1),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_chunks": reasoning_chunks,
        "finish_reason": finish,
        "text": "".join(text_parts),
    }


def pad_context(base: str, model: str, target_tokens: int) -> str:
    """Build filler text of roughly target_tokens using the server tokenizer."""
    filler = "The quick brown fox jumps over the lazy dog. " * 8
    # grow until tokenize reports enough
    text = filler
    for _ in range(12):
        try:
            req = urllib.request.Request(
                f"{base}/tokenize",
                data=json.dumps({"model": model, "prompt": text}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                n = len(json.load(r).get("tokens", []))
        except Exception as e:  # noqa: BLE001
            print(f"tokenize failed ({e}); estimating from chars", file=sys.stderr)
            n = len(text) // 4
        if n >= target_tokens:
            return text
        text = text * 2
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001")
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--context-pad", type=int, default=0,
                    help="prepend filler text of ~N tokens to the prompt")
    ap.add_argument("--prompt-file")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()

    prompt = SMOKE_PROMPT if args.smoke else DEFAULT_PROMPT
    if args.prompt_file:
        prompt = open(args.prompt_file).read()
    if args.context_pad:
        prompt = pad_context(args.base, args.model, args.context_pad) + "\n\n" + prompt

    runs = 1 if args.smoke else args.runs
    results = []
    for i in range(runs):
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 16 if args.smoke else args.max_tokens,
            "temperature": args.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            r = post_stream(args.base, payload, args.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:800]
            print(f"run {i+1}: HTTP {e.code}: {body}", file=sys.stderr)
            return 2
        except Exception as e:  # noqa: BLE001
            print(f"run {i+1}: {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        results.append(r)
        print(f"run {i+1}: ttft={r['ttft_ms']}ms ttfc={r['ttfc_ms']}ms "
              f"decode={r['decode_tps']}tps prefill={r['prefill_tps']}tps "
              f"total={r['total_ms']}ms pt={r['prompt_tokens']} "
              f"ct={r['completion_tokens']} reasoning={r['reasoning_chunks']}")

    summary = {
        "model": args.model,
        "runs": runs,
        "max_tokens": 16 if args.smoke else args.max_tokens,
        "temperature": args.temperature,
        "context_pad": args.context_pad,
        "ttft_ms_median": round(statistics.median(r["ttft_ms"] for r in results), 1),
        "ttfc_ms_median": (round(statistics.median(r["ttfc_ms"] for r in results), 1)
                           if all(r["ttfc_ms"] is not None for r in results) else None),
        "decode_tps_median": round(statistics.median(r["decode_tps"] for r in results), 2),
        "total_ms_median": round(statistics.median(r["total_ms"] for r in results), 1),
        "samples": results,
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "samples"}, indent=2))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
