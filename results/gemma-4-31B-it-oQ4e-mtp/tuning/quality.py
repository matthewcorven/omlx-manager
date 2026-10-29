#!/usr/bin/env python3
"""Run the three fixed quality-guardrail prompts and dump raw outputs."""
import json, os, sys, time, urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "gemma-4-31B-it-oQ4e-mtp"
HERE = os.path.dirname(os.path.abspath(__file__))

PROMPTS = [
    ("pure-function", "Write a Python function `merge_intervals(intervals)` that takes a list of "
     "[start, end] pairs, merges all overlapping or adjacent intervals, and returns the result "
     "sorted by start. Include a docstring. Output only the code."),
    ("bug-fix", "This function should return the average of a list of numbers, but it crashes on "
     "an empty list and returns the wrong value for integers. Find the bug and give the corrected "
     "function.\n\n```python\ndef average(nums):\n    total = 0\n    for n in nums:\n        total += n\n    return total / len(nums)\n```\n\nOutput only the corrected code."),
    ("refactor", "Refactor this into something more readable without changing behaviour. Output "
     "only the refactored code.\n\n```python\ndef proc(d, k):\n    r = []\n    for i in range(len(k)):\n        if k[i] in d:\n            if d[k[i]] != None:\n                r.append((k[i], d[k[i]]))\n    return r\n```"),
]


TEMP = float(os.environ.get("TEMP", "0.2"))
TOP_P = float(os.environ.get("TOP_P", "0.95"))
TOP_K = int(os.environ.get("TOP_K", "20"))
MAXTOK = int(os.environ.get("MAXTOK", "700"))
OUT = sys.argv[1] if len(sys.argv) > 1 else "quality-raw.json"


def ask(prompt):
    """Stream the completion. Flint spends its first ~250 tokens on
    reasoning_content, so a non-streaming call with a small budget returns an
    empty content field; streaming also gives us TTFT/TTFC."""
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAXTOK,
        "temperature": TEMP,
        "top_p": TOP_P,
        "top_k": TOP_K,
        "stream": True,
    }).encode()
    req = urllib.request.Request(f"{OMLX}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    content, reasoning, finish = [], [], None
    t0 = time.time()
    ttft = ttfc = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                ev = json.loads(data)
            except json.JSONDecodeError:
                continue
            for ch in ev.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("reasoning_content"):
                    if ttft is None:
                        ttft = (time.time() - t0) * 1000
                    reasoning.append(d["reasoning_content"])
                if d.get("content"):
                    if ttft is None:
                        ttft = (time.time() - t0) * 1000
                    if ttfc is None:
                        ttfc = (time.time() - t0) * 1000
                    content.append(d["content"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    return {
        "content": "".join(content),
        "reasoning_content": "".join(reasoning),
        "finish_reason": finish,
        "ttft_ms": round(ttft, 1) if ttft else None,
        "ttfc_ms": round(ttfc, 1) if ttfc else None,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


def main():
    out = []
    for name, prompt in PROMPTS:
        resp = ask(prompt)
        out.append({"name": name, "prompt": prompt, **resp,
                    "sampler": {"temperature": TEMP, "top_p": TOP_P, "top_k": TOP_K,
                                "max_tokens": MAXTOK}})
        print(f"{name}: {len(resp['content'])} chars content, "
              f"{len(resp['reasoning_content'])} chars reasoning, "
              f"finish={resp['finish_reason']} ttft={resp['ttft_ms']}ms "
              f"ttfc={resp['ttfc_ms']}ms", flush=True)
    with open(os.path.join(HERE, OUT), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
