#!/usr/bin/env python3
"""Cold-prefill A/B for prefill-path knobs (ANE prefill).

The default measure.py prompt is identical every run, so the paged prefix cache
serves the whole prefill and TTFT measures cache restore, not prefill. That
makes any prefill-path knob look like a null result. This harness prepends a
unique random nonce to every request so the prefix cache always misses, and
reports TTFT (which is then a real cold prefill) plus decode.

Reload-requiring knobs -> alternating blocks, warmup discarded per block.
"""
import json, os, random, statistics, string, sys, time, urllib.request

from block import apply_and_settle, get, MODEL, OMLX, HERE

WORDS = ("alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo "
         "lima mike november oscar papa quebec romeo sierra tango uniform "
         "victor whiskey xray yankee zulu").split()


def nonce_prompt(target_tokens, tail):
    rnd = random.Random()
    n = max(1, target_tokens // 2)
    filler = " ".join(rnd.choice(WORDS) + str(rnd.randrange(10000)) for _ in range(n))
    return filler + "\n\n" + tail


TAIL = ("Write a Python function `merge_intervals(intervals)` that merges "
        "overlapping closed intervals and returns them sorted. Include a "
        "docstring and three doctest examples. Output only the code.")


def one_run(pad, maxtok):
    prompt = nonce_prompt(pad, TAIL) if pad else TAIL
    body = json.dumps({"model": MODEL,
                       "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": maxtok, "temperature": 0.0, "stream": True,
                       "stream_options": {"include_usage": True}}).encode()
    req = urllib.request.Request(f"{OMLX}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    t0 = time.perf_counter()
    ttft = last = None
    chunks = 0
    pt = None
    usage = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            d = line[5:].strip()
            if d == "[DONE]":
                break
            ev = json.loads(d)
            if ev.get("usage"):
                usage = ev["usage"]
                pt = usage.get("prompt_tokens")
            for ch in ev.get("choices") or []:
                de = ch.get("delta") or {}
                now = time.perf_counter()
                if de.get("content") or de.get("reasoning_content"):
                    if ttft is None:
                        ttft = now - t0
                    last = now
                    chunks += 1
    # The server coalesces SSE deltas (11 chunks for 300 tokens), so chunk
    # counting under-reports decode. Trust the per-request usage block.
    u = usage or {}
    return {"ttft_ms": round(ttft * 1000, 1),
            "decode_tps": round(u.get("generation_tokens_per_second") or 0.0, 2),
            "prompt_tokens": pt,
            "prefill_tps": round(u.get("prompt_tokens_per_second") or 0.0, 1),
            "server_ttft_ms": round((u.get("time_to_first_token") or 0) * 1000, 1),
            "chunks": chunks}


def main():
    label_a, patch_a = sys.argv[1], json.loads(sys.argv[2])
    label_b, patch_b = sys.argv[3], json.loads(sys.argv[4])
    n = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    blocks = int(sys.argv[6]) if len(sys.argv) > 6 else 2
    pad = int(os.environ.get("PAD", "0"))
    maxtok = int(os.environ.get("MAXTOK", "300"))
    arms = {"A": (label_a, patch_a, []), "B": (label_b, patch_b, [])}
    for b in range(blocks):
        for k in ("A", "B"):
            lbl, patch, acc = arms[k]
            apply_and_settle(patch)
            one_run(pad, maxtok)  # warmup, discarded
            got = [one_run(pad, maxtok) for _ in range(n)]
            acc.extend(got)
            print(f"  block{b+1} {k} {lbl:18} ttft_median="
                  f"{statistics.median(x['ttft_ms'] for x in got):7.1f}ms "
                  f"decode={statistics.median(x['decode_tps'] for x in got):6.2f}tps "
                  f"pt={got[0]['prompt_tokens']}", flush=True)
    res = {}
    for k, (lbl, patch, acc) in arms.items():
        res[k] = {"label": lbl, "patch": patch, "n": len(acc),
                  "ttft_ms": round(statistics.median(x["ttft_ms"] for x in acc), 1),
                  "decode_tps": round(statistics.median(x["decode_tps"] for x in acc), 2),
                  "prefill_tps": round(statistics.median(x["prefill_tps"] for x in acc), 1),
                  "prompt_tokens": acc[0]["prompt_tokens"],
                  "samples": acc}
        print(f"{k} {lbl:18} ttft={res[k]['ttft_ms']:7.1f}ms "
              f"decode={res[k]['decode_tps']:6.2f}tps prefill={res[k]['prefill_tps']}tps "
              f"(n={len(acc)})")
    out = f"coldprefill-{label_a}-vs-{label_b}.json"
    with open(os.path.join(HERE, out), "w") as f:
        json.dump(res, f, indent=2)


if __name__ == "__main__":
    main()
