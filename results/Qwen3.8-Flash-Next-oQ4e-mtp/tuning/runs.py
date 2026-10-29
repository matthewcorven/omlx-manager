#!/usr/bin/env python3
"""Record what a finished block of measure.py runs looks like, saving raw JSON.

One warmup discarded, then N runs, each recorded individually.
"""
import json
import os
import statistics
import subprocess
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
OMLX = "http://127.0.0.1:8001"
MODEL = "Qwen3.8-Flash-Next-oQ4e-mtp"


def measure(max_tokens, context_pad=0):
    last = None
    for _ in range(3):
        cmd = ["python3", "scripts/measure.py", "--model", MODEL,
               "--runs", "1", "--max-tokens", str(max_tokens)]
        if context_pad:
            cmd += ["--context-pad", str(context_pad)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        lines = [l for l in r.stdout.splitlines() if l.startswith("run 1:")]
        if lines:
            d = dict(kv.split("=") for kv in lines[0].split()[2:])

            def f(k, suf):
                v = d[k].removesuffix(suf)
                return None if v == "None" else float(v)

            return {"ttft_ms": f("ttft", "ms"), "ttfc_ms": f("ttfc", "ms"),
                    "decode_tps": f("decode", "tps"), "total_ms": f("total", "ms"),
                    "prefill_tps": f("prefill", "tps"),
                    "prompt_tokens": int(d["pt"]),
                    "completion_tokens": int(d["ct"]),
                    "reasoning_chunks": int(d["reasoning"])}
        last = (r.stdout + r.stderr)[-300:]
        time.sleep(3)
    raise RuntimeError(f"measure failed 3x: {last}")


def main():
    out = sys.argv[1]
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    max_tokens = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    context_pad = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    measure(max_tokens, context_pad)  # warmup, discarded
    samples = []
    for i in range(runs):
        m = measure(max_tokens, context_pad)
        samples.append(m)
        print(f"  run {i+1}: ttft={m['ttft_ms']}ms decode={m['decode_tps']}tps "
              f"total={m['total_ms']}ms ct={m['completion_tokens']} "
              f"reasoning={m['reasoning_chunks']}", flush=True)

    def med(k):
        return round(statistics.median(x[k] for x in samples), 2)

    summary = {
        "model": MODEL,
        "runs": runs,
        "max_tokens": max_tokens,
        "context_pad": context_pad,
        "ttft_ms_median": med("ttft_ms"),
        "decode_tps_median": med("decode_tps"),
        "prefill_tps_median": med("prefill_tps"),
        "total_ms_median": med("total_ms"),
        "completion_tokens_median": med("completion_tokens"),
        "reasoning_chunks_median": med("reasoning_chunks"),
        "samples": samples,
    }
    path = out if os.path.isabs(out) else os.path.join(REPO, out)
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"median ttft={summary['ttft_ms_median']}ms decode={summary['decode_tps_median']}tps "
          f"total={summary['total_ms_median']}ms -> wrote {path}")


if __name__ == "__main__":
    main()
