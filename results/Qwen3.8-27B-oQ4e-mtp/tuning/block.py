#!/usr/bin/env python3
"""Block-based A/B for knobs that force a model reload.

Interleaving is impossible for reload-requiring knobs (every switch is a cold
load), so this runs alternating blocks A,B,A,B... Each block = apply settings,
wait for load, discard a warmup, then N measured runs. Alternating blocks keeps
slow drift spread across both arms.
"""
import json, os, statistics, subprocess, sys, time, urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "Qwen3.8-27B-oQ4e-mtp"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))

def get(path):
    with urllib.request.urlopen(f"{OMLX}{path}", timeout=60) as r:
        return json.load(r)

def put(patch):
    req = urllib.request.Request(
        f"{OMLX}/admin/api/models/{MODEL}/settings",
        data=json.dumps(patch).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)

def wait_loaded(timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        m = [x for x in get("/admin/api/models")["models"] if x["id"] == MODEL][0]
        if m["loaded"] and not m.get("is_loading"):
            return True
        time.sleep(2)
    raise RuntimeError("model did not load")

def load():
    urllib.request.urlopen(
        urllib.request.Request(
            f"{OMLX}/admin/api/models/{MODEL}/load", method="POST"),
        timeout=120).read()
    wait_loaded()

def apply_and_settle(patch):
    # auto_unloaded means the server dropped the model but does NOT bring it
    # back; we must issue the load ourselves.
    put(patch)
    m = [x for x in get("/admin/api/models")["models"] if x["id"] == MODEL][0]
    if not m["loaded"]:
        load()

def one_run():
    last = None
    for _ in range(3):
        r = subprocess.run(
            ["python3", "scripts/measure.py", "--model", MODEL,
             "--runs", "1", "--max-tokens", "300"],
            capture_output=True, text=True, cwd=REPO)
        lines = [l for l in r.stdout.splitlines() if l.startswith("run 1:")]
        if lines:
            d = dict(kv.split("=") for kv in lines[0].split()[2:])
            f = lambda k, s: float(d[k].removesuffix(s))
            return {"ttft_ms": f("ttft", "ms"), "decode_tps": f("decode", "tps"),
                    "total_ms": f("total", "ms")}
        last = (r.stdout + r.stderr)[-300:]
        time.sleep(3)
    raise RuntimeError(f"measure failed: {last}")

def main():
    label_a, patch_a = sys.argv[1], json.loads(sys.argv[2])
    label_b, patch_b = sys.argv[3], json.loads(sys.argv[4])
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    blocks = int(sys.argv[6]) if len(sys.argv) > 6 else 2
    arms = {"A": (label_a, patch_a, []), "B": (label_b, patch_b, [])}
    for b in range(blocks):
        for k in ("A", "B"):
            lbl, patch, acc = arms[k]
            apply_and_settle(patch)
            one_run()  # warmup, discarded
            got = [one_run() for _ in range(n)]
            acc.extend(got)
            med = statistics.median(x["decode_tps"] for x in got)
            print(f"  block{b+1} {k} {lbl:20} decode_median={med:6.2f}tps "
                  f"ttft={statistics.median(x['ttft_ms'] for x in got):7.1f}ms")
    print()
    res = {}
    for k, (lbl, patch, acc) in arms.items():
        t = statistics.median(x["ttft_ms"] for x in acc)
        d = statistics.median(x["decode_tps"] for x in acc)
        tot = statistics.median(x["total_ms"] for x in acc)
        res[k] = {"label": lbl, "patch": patch, "n": len(acc),
                  "ttft_ms": round(t, 1), "decode_tps": round(d, 2),
                  "total_ms": round(tot, 0), "samples": acc}
        print(f"{k} {lbl:20} ttft={t:7.1f}ms decode={d:6.2f}tps total={tot:7.0f}ms (n={len(acc)})")
    with open(os.path.join(HERE, f"block-{label_a}-vs-{label_b}.json"), "w") as f:
        json.dump(res, f, indent=2)

if __name__ == "__main__":
    main()
