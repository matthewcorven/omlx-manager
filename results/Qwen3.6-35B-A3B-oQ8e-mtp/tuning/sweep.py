#!/usr/bin/env python3
"""Ordered sweep over reload-requiring configs.

Reload knobs cannot be interleaved, so a sweep is inherently sequential and
exposed to drift. Mitigation: run the list forward, then backward, and take the
median of all samples per config. Usage:

  ./sweep.py <runs_per_config> <out.json> '<label>=<json>' '<label>=<json>' ...
"""
import json, os, statistics, sys

from block import apply_and_settle, one_run, HERE


def main():
    n = int(sys.argv[1])
    out = sys.argv[2]
    configs = []
    for spec in sys.argv[3:]:
        label, patch = spec.split("=", 1)
        configs.append((label, json.loads(patch)))

    acc = {label: [] for label, _ in configs}
    order = configs + list(reversed(configs))
    for i, (label, patch) in enumerate(order):
        apply_and_settle(patch)
        one_run()  # warmup, discarded
        got = [one_run() for _ in range(n)]
        acc[label].extend(got)
        print(f"  pass{i+1:02d} {label:22} decode={statistics.median(x['decode_tps'] for x in got):6.2f}tps "
              f"ttft={statistics.median(x['ttft_ms'] for x in got):7.1f}ms", flush=True)

    print()
    res = {}
    for label, patch in configs:
        s = acc[label]
        t = statistics.median(x["ttft_ms"] for x in s)
        d = statistics.median(x["decode_tps"] for x in s)
        res[label] = {"patch": patch, "n": len(s), "ttft_ms": round(t, 1),
                      "decode_tps": round(d, 2),
                      "total_ms": round(statistics.median(x["total_ms"] for x in s), 0),
                      "samples": s}
        print(f"{label:22} ttft={t:7.1f}ms decode={d:6.2f}tps (n={len(s)})")
    with open(os.path.join(HERE, out), "w") as f:
        json.dump(res, f, indent=2)


if __name__ == "__main__":
    main()
