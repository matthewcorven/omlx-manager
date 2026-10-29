#!/usr/bin/env python3
"""Interleaved A/B sampling to cancel slow drift.

Alternates two settings values round-robin, one request each, so drift
affects both arms equally. Reports per-arm median over N samples.
"""
import json, os, statistics, subprocess, sys, time, urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

OMLX = "http://127.0.0.1:8001"
MODEL = "Qwen3.8-Flash-Next-oQ4e-mtp"

def put(patch):
    req = urllib.request.Request(
        f"{OMLX}/admin/api/models/{MODEL}/settings",
        data=json.dumps(patch).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

PAD = int(os.environ.get("PAD", "0"))


def measure():
    last_err = None
    for attempt in range(3):
        cmd = ["python3", "scripts/measure.py", "--model", MODEL,
               "--runs", "1", "--max-tokens", "300"]
        if PAD:
            cmd += ["--context-pad", str(PAD)]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        lines = [l for l in r.stdout.splitlines() if l.startswith("run 1:")]
        if lines:
            line = lines[0]
            break
        last_err = (r.stdout + r.stderr).strip()[-300:]
        time.sleep(3)
    else:
        raise RuntimeError(f"measure failed 3x: {last_err}")
    d = dict(kv.split("=") for kv in line.split()[2:])
    f = lambda k, suf: float(d[k].removesuffix(suf))
    return {"ttft_ms": f("ttft", "ms"), "decode_tps": f("decode", "tps"),
            "total_ms": f("total", "ms")}

def main():
    label_a, patch_a = sys.argv[1], json.loads(sys.argv[2])
    label_b, patch_b = sys.argv[3], json.loads(sys.argv[4])
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 5
    out = sys.argv[6] if len(sys.argv) > 6 else f"ab-{label_a}-vs-{label_b}.json"
    arms = {"A": (label_a, patch_a, []), "B": (label_b, patch_b, [])}
    put(patch_a)
    measure()  # discard warmup
    for i in range(n):
        for k in ("A", "B"):
            lbl, patch, acc = arms[k]
            put(patch)
            m = measure()
            acc.append(m)
            print(f"  {i+1} {k} {lbl:22} ttft={m['ttft_ms']:.1f} "
                  f"decode={m['decode_tps']:.2f} total={m['total_ms']:.0f}")
    print()
    res = {}
    for k, (lbl, patch, acc) in arms.items():
        t = statistics.median(x["ttft_ms"] for x in acc)
        d = statistics.median(x["decode_tps"] for x in acc)
        tot = statistics.median(x["total_ms"] for x in acc)
        res[k] = {"label": lbl, "patch": patch, "n": len(acc),
                  "ttft_ms": round(t, 1), "decode_tps": round(d, 2),
                  "total_ms": round(tot, 0), "samples": acc}
        print(f"{k} {lbl:22} ttft={t:6.1f}ms decode={d:6.2f}tps total={tot:7.0f}ms")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), out)
    with open(path, "w") as f:
        json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
