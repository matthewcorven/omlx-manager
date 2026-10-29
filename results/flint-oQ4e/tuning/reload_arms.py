#!/usr/bin/env python3
"""Interleaved multi-arm reload probe.

Each arm is applied, then measured in its own load, and the arm order is
reversed on alternate cycles so slow drift lands on both arms. Used because a
reload-requiring knob cannot be interleaved per request.
"""
import json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from block import apply_and_settle, one_run, HERE

def main():
    out, cycles, n = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    arms = []
    for i in range(4, len(sys.argv), 2):
        arms.append((sys.argv[i], json.loads(sys.argv[i + 1])))
    acc = {lbl: [] for lbl, _ in arms}
    for c in range(cycles):
        order = arms if c % 2 == 0 else list(reversed(arms))
        for lbl, patch in order:
            apply_and_settle(patch)
            one_run()
            got = [one_run() for _ in range(n)]
            acc[lbl].extend(got)
            d = statistics.median(x["decode_tps"] for x in got)
            print(f"  cyc{c+1} {lbl:24} decode={d:6.2f}tps "
                  f"ttft={statistics.median(x['ttft_ms'] for x in got):7.1f}ms",
                  flush=True)
    print()
    res = {}
    for lbl, patch in arms:
        s = acc[lbl]
        res[lbl] = {"patch": patch, "n": len(s),
                    "decode_tps": round(statistics.median(x["decode_tps"] for x in s), 2),
                    "ttft_ms": round(statistics.median(x["ttft_ms"] for x in s), 1),
                    "min_decode": round(min(x["decode_tps"] for x in s), 2),
                    "max_decode": round(max(x["decode_tps"] for x in s), 2),
                    "samples": s}
        print(f"{lbl:24} decode={res[lbl]['decode_tps']:6.2f}tps "
              f"[{res[lbl]['min_decode']:.2f}..{res[lbl]['max_decode']:.2f}] "
              f"ttft={res[lbl]['ttft_ms']:7.1f}ms (n={len(s)})")
    with open(os.path.join(HERE, out), "w") as f:
        json.dump(res, f, indent=2)
        f.write("\n")

if __name__ == "__main__":
    main()
