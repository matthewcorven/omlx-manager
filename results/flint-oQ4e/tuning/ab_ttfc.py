#!/usr/bin/env python3
"""Interleaved A/B that also records time-to-first-CONTENT-token (ttfc).

ab.py only parses ttft/decode/total; the thinking stage needs ttfc, because
with thinking on the first token is a reasoning token and the user-visible
answer starts much later (or never).
"""
import json, os, statistics, subprocess, sys, time, urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
HERE = os.path.dirname(os.path.abspath(__file__))
OMLX = "http://127.0.0.1:8001"
MODEL = "flint-oQ4e"


def put(patch):
    req = urllib.request.Request(
        f"{OMLX}/admin/api/models/{MODEL}/settings",
        data=json.dumps(patch).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def measure(max_tokens):
    last = None
    for _ in range(3):
        r = subprocess.run(
            ["python3", "scripts/measure.py", "--model", MODEL,
             "--runs", "1", "--max-tokens", str(max_tokens)],
            capture_output=True, text=True, cwd=REPO)
        lines = [l for l in r.stdout.splitlines() if l.startswith("run 1:")]
        if lines:
            d = dict(kv.split("=") for kv in lines[0].split()[2:])
            def f(k, suf):
                v = d[k].removesuffix(suf)
                return None if v == "None" else float(v)
            return {"ttft_ms": f("ttft", "ms"), "ttfc_ms": f("ttfc", "ms"),
                    "decode_tps": f("decode", "tps"), "total_ms": f("total", "ms"),
                    "completion_tokens": int(d["ct"]),
                    "reasoning_chunks": int(d["reasoning"])}
        last = (r.stdout + r.stderr)[-300:]
        time.sleep(3)
    raise RuntimeError(f"measure failed 3x: {last}")


def main():
    label_a, patch_a = sys.argv[1], json.loads(sys.argv[2])
    label_b, patch_b = sys.argv[3], json.loads(sys.argv[4])
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    max_tokens = int(sys.argv[6]) if len(sys.argv) > 6 else 1500
    arms = {"A": (label_a, patch_a, []), "B": (label_b, patch_b, [])}
    put(patch_a)
    measure(max_tokens)  # warmup, discarded
    for i in range(n):
        for k in ("A", "B"):
            lbl, patch, acc = arms[k]
            put(patch)
            m = measure(max_tokens)
            acc.append(m)
            print(f"  {i+1} {k} {lbl:20} ttft={m['ttft_ms']} ttfc={m['ttfc_ms']} "
                  f"decode={m['decode_tps']} ct={m['completion_tokens']} "
                  f"reasoning={m['reasoning_chunks']}", flush=True)
    print()
    res = {}
    for k, (lbl, patch, acc) in arms.items():
        ttfc = [x["ttfc_ms"] for x in acc if x["ttfc_ms"] is not None]
        res[k] = {
            "label": lbl, "patch": patch, "n": len(acc), "max_tokens": max_tokens,
            "ttft_ms": round(statistics.median(x["ttft_ms"] for x in acc), 1),
            "ttfc_ms": round(statistics.median(ttfc), 1) if ttfc else None,
            "ttfc_n": len(ttfc),
            "decode_tps": round(statistics.median(x["decode_tps"] for x in acc), 2),
            "total_ms": round(statistics.median(x["total_ms"] for x in acc), 0),
            "samples": acc,
        }
        print(f"{k} {lbl:20} ttft={res[k]['ttft_ms']}ms ttfc={res[k]['ttfc_ms']}ms "
              f"decode={res[k]['decode_tps']}tps (ttfc n={res[k]['ttfc_n']}/{res[k]['n']})")
    with open(os.path.join(HERE, f"abttfc-{label_a}-vs-{label_b}.json"), "w") as f:
        json.dump(res, f, indent=2)


if __name__ == "__main__":
    main()
