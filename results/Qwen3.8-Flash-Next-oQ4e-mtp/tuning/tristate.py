#!/usr/bin/env python3
"""Thinking tri-state probe: stream one request per value of enable_thinking
(false / null / true) and record the actual text, not just the setting name.

`enable_thinking: null` is NOT off on several Qwen builds: it emits reasoning
chunks while measure.py reports ttfc=None and a normal-looking ttft_ms. The only
reliable signal is the generated text, so this prints it.

Usage: ./tristate.py <out.json> [max_tokens]
"""
import json, os, sys, time, urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "Qwen3.8-Flash-Next-oQ4e-mtp"
HERE = os.path.dirname(os.path.abspath(__file__))

PROMPT = ("Write a Python function `merge_sorted_lists(a, b)` that merges two "
          "sorted lists into one sorted list. Include a docstring. Output only "
          "the code.")


def put(patch):
    req = urllib.request.Request(
        f"{OMLX}/admin/api/models/{MODEL}/settings",
        data=json.dumps(patch).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def ask(max_tokens):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": True,
    }).encode()
    req = urllib.request.Request(f"{OMLX}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
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
        "content_chars": len("".join(content)),
        "reasoning_chars": len("".join(reasoning)),
        "finish_reason": finish,
        "ttft_ms": round(ttft, 1) if ttft else None,
        "ttfc_ms": round(ttfc, 1) if ttfc else None,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
    }


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "tristate.json"
    max_tokens = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    results = {}
    for label, value in (("false", False), ("null", None), ("true", True)):
        put({"enable_thinking": value})
        time.sleep(1.0)
        r = ask(max_tokens)
        results[label] = {"enable_thinking": value, "max_tokens": max_tokens, **r}
        print(f"{label:5} content={r['content_chars']:5}ch reasoning={r['reasoning_chars']:6}ch "
              f"finish={r['finish_reason']} ttft={r['ttft_ms']}ms ttfc={r['ttfc_ms']}ms "
              f"elapsed={r['elapsed_ms']}ms", flush=True)
    with open(os.path.join(HERE, out), "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
