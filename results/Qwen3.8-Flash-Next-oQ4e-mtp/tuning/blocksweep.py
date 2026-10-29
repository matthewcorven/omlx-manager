#!/usr/bin/env python3
"""Forward+backward ordered block sweep with resident-memory capture.

The point of this sweep is the throughput/footprint knee, not raw speed: a
config that is 3% slower but 20 GB smaller is a real result on a 128 GB box.

`moe_expert_offload_enabled` and `moe_expert_offload_resident_fraction` both
require a reload, so this uses block.py's apply_and_settle (apply -> wait for
unload -> POST /load -> poll loaded) and never ab.py.

Resident memory is read from GET /api/status.model_memory_used immediately
after the arm settles and again after its measured runs; the max of the two is
recorded, because the first reading can land before the allocator has finished.

Usage: ./moe_sweep.py <runs_per_arm> <out.json> '<label>=<json>' ...
Order is forward then backward, like sweep.py, to cancel drift.
"""
import json, os, statistics, sys, urllib.request

from block import apply_and_settle, one_run, HERE, OMLX


def mem():
    with urllib.request.urlopen(f"{OMLX}/api/status", timeout=60) as r:
        s = json.load(r)
    return {"used": s.get("model_memory_used"), "max": s.get("model_memory_max")}


def main():
    n = int(sys.argv[1])
    out = sys.argv[2]
    configs = []
    for spec in sys.argv[3:]:
        label, patch = spec.split("=", 1)
        configs.append((label, json.loads(patch)))

    acc = {label: [] for label, _ in configs}
    mems = {label: [] for label, _ in configs}
    order = configs + list(reversed(configs))
    for i, (label, patch) in enumerate(order):
        apply_and_settle(patch)
        m0 = mem()
        one_run()  # warmup, discarded
        got = [one_run() for _ in range(n)]
        m1 = mem()
        acc[label].extend(got)
        mems[label].append({"used": max(m0["used"] or 0, m1["used"] or 0),
                            "max": m1["max"]})
        print(f"  pass{i+1:02d} {label:14} decode={statistics.median(x['decode_tps'] for x in got):6.2f}tps "
              f"ttft={statistics.median(x['ttft_ms'] for x in got):7.1f}ms "
              f"resident={(max(m0['used'] or 0, m1['used'] or 0))/1e9:6.2f}GB "
              f"ceiling={(m1['max'] or 0)/1e9:6.2f}GB", flush=True)

    print()
    res = {}
    for label, patch in configs:
        s = acc[label]
        used = max(m["used"] for m in mems[label])
        res[label] = {
            "patch": patch, "n": len(s),
            "ttft_ms": round(statistics.median(x["ttft_ms"] for x in s), 1),
            "decode_tps": round(statistics.median(x["decode_tps"] for x in s), 2),
            "total_ms": round(statistics.median(x["total_ms"] for x in s), 0),
            "resident_bytes": used,
            "resident_gb": round(used / 1e9, 2),
            "ceiling_gb": round(max(m["max"] for m in mems[label]) / 1e9, 2),
            "samples": s,
        }
        print(f"{label:14} ttft={res[label]['ttft_ms']:7.1f}ms "
              f"decode={res[label]['decode_tps']:6.2f}tps "
              f"resident={res[label]['resident_gb']:6.2f}GB (n={len(s)})")
    with open(os.path.join(HERE, out), "w") as f:
        json.dump(res, f, indent=2)


if __name__ == "__main__":
    main()
