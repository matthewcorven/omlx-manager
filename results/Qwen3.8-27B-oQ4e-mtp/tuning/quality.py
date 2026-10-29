#!/usr/bin/env python3
"""Run the three fixed quality-guardrail prompts and dump raw outputs."""
import json, os, sys, urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "Qwen3.8-27B-oQ4e-mtp"
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


def ask(prompt):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 700,
        "temperature": 0.2,
        "top_p": 0.95,
        "top_k": 20,
        "stream": False,
    }).encode()
    req = urllib.request.Request(f"{OMLX}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def main():
    out = []
    for name, prompt in PROMPTS:
        resp = ask(prompt)
        msg = resp["choices"][0]["message"]
        out.append({
            "name": name,
            "prompt": prompt,
            "content": msg.get("content") or "",
            "reasoning_content": msg.get("reasoning_content") or "",
            "finish_reason": resp["choices"][0].get("finish_reason"),
            "usage": resp.get("usage"),
        })
        print(f"{name}: {len(out[-1]['content'])} chars content, "
              f"{len(out[-1]['reasoning_content'])} chars reasoning, "
              f"finish={out[-1]['finish_reason']}", flush=True)
    with open(os.path.join(HERE, "quality-raw.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
