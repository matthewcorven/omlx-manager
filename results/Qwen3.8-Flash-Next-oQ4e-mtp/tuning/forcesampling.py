#!/usr/bin/env python3
"""force_sampling artifact check.

`force_sampling: true` makes the server ignore the request's `temperature: 0.0`
and use the model's configured temperature instead. That turns every temp-0
harness into a sampling harness, which is a measurement artifact rather than a
lever. The test is determinism, not speed: three identical temp-0 requests
should return byte-identical text when force_sampling is off, and diverge when
it is on.
"""
import json, os, sys, urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "Qwen3.8-Flash-Next-oQ4e-mtp"
HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT = ("Write a Python function merge_sorted_lists(a, b) that merges two "
          "sorted lists into one sorted list. Return only the code.")


def put(patch):
    req = urllib.request.Request(
        f"{OMLX}/admin/api/models/{MODEL}/settings",
        data=json.dumps(patch).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def ask():
    payload = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}],
               "max_tokens": 200, "temperature": 0.0, "stream": False}
    req = urllib.request.Request(f"{OMLX}/v1/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.load(r)
    return d["choices"][0]["message"].get("content") or ""


def main():
    out = {}
    for label, patch in [
        ("force_sampling=false", {"force_sampling": False, "temperature": 1.0}),
        ("force_sampling=true", {"force_sampling": True, "temperature": 1.0}),
    ]:
        put(patch)
        texts = [ask() for _ in range(3)]
        uniq = len({t.strip() for t in texts})
        out[label] = {"distinct_outputs": uniq, "texts": texts}
        print(f"{label}: {uniq}/3 distinct outputs")
        for i, t in enumerate(texts):
            print(f"  [{i}] {t.strip()[:90]!r}")
    with open(os.path.join(HERE, "force-sampling.json"), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
