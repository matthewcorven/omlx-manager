#!/usr/bin/env python3
"""Interleaved A/B for enable_thinking, streaming, measuring time to first
CONTENT token (ttfc) separately from time to first token of any kind (ttft).

enable_thinking does not reload on this model, so interleaving is valid.
"""
import json, os, statistics, sys, time, urllib.request

from quality import ask, OMLX, MODEL, HERE

PROMPT = ("Write a Python function `merge_intervals(intervals)` that merges "
          "overlapping closed intervals and returns them sorted. Include a "
          "docstring and three doctest examples. Output only the code.")
MAXTOK = int(os.environ.get("MAXTOK", "900"))


def put(patch):
    req = urllib.request.Request(
        f"{OMLX}/admin/api/models/{MODEL}/settings",
        data=json.dumps(patch).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    out = sys.argv[2] if len(sys.argv) > 2 else "thinking-ab.json"
    arms = {"A": ("enable_thinking true", {"enable_thinking": True}, []),
            "B": ("enable_thinking false", {"enable_thinking": False}, [])}
    put(arms["A"][1])
    ask(PROMPT)  # warmup, discarded
    for i in range(n):
        for k in ("A", "B"):
            lbl, patch, acc = arms[k]
            put(patch)
            r = ask(PROMPT)
            acc.append(r)
            print(f"  {i+1} {k} {lbl:22} ttft={r['ttft_ms']} ttfc={r['ttfc_ms']} "
                  f"content={len(r['content'])}ch reasoning={len(r['reasoning_content'])}ch "
                  f"finish={r['finish_reason']} elapsed={r['elapsed_ms']}", flush=True)
    res = {}
    for k, (lbl, patch, acc) in arms.items():
        def med(key):
            vals = [x[key] for x in acc if x[key] is not None]
            return round(statistics.median(vals), 1) if vals else None
        res[k] = {"label": lbl, "patch": patch, "n": len(acc),
                  "ttft_ms": med("ttft_ms"), "ttfc_ms": med("ttfc_ms"),
                  "elapsed_ms": med("elapsed_ms"),
                  "content_chars": med("content") if False else
                  round(statistics.median(len(x["content"]) for x in acc), 0),
                  "reasoning_chars": round(statistics.median(len(x["reasoning_content"]) for x in acc), 0),
                  "finish_reasons": [x["finish_reason"] for x in acc],
                  "samples": acc}
        print(f"{k} {lbl:22} ttft={res[k]['ttft_ms']}ms ttfc={res[k]['ttfc_ms']}ms "
              f"content={res[k]['content_chars']}ch reasoning={res[k]['reasoning_chars']}ch")
    with open(os.path.join(HERE, out), "w") as f:
        json.dump(res, f, indent=2)


if __name__ == "__main__":
    main()
