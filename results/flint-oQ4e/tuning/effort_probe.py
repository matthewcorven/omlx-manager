#!/usr/bin/env python3
"""Does reasoning_effort change flint's reasoning length / TTFC?

think-probe.json showed every thinking lever was a no-op on a trivial prompt.
This re-tests on the real coding prompts, where a reasoning budget would
actually bite, and records TTFC (first *content* token) per effort level.
"""
import json, os, sys, time, urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "flint-oQ4e"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else "effort-probe.json"

PROMPT = ("This function should return the average of a list of numbers, but it crashes on "
          "an empty list and returns the wrong value for integers. Find the bug and give the "
          "corrected function.\n\n```python\ndef average(nums):\n    total = 0\n    for n in nums:\n"
          "        total += n\n    return total / len(nums)\n```\n\nOutput only the corrected code.")


def ask(extra):
    body = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": 3000, "temperature": 0.2, "top_p": 0.95, "top_k": 20,
            "stream": True, **extra}
    req = urllib.request.Request(f"{OMLX}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    content, reasoning, finish = [], [], None
    t0 = time.time()
    ttft = ttfc = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            d = line[5:].strip()
            if d == "[DONE]":
                break
            try:
                ev = json.loads(d)
            except json.JSONDecodeError:
                continue
            for ch in ev.get("choices") or []:
                dl = ch.get("delta") or {}
                if dl.get("reasoning_content"):
                    ttft = ttft or (time.time() - t0) * 1000
                    reasoning.append(dl["reasoning_content"])
                if dl.get("content"):
                    ttft = ttft or (time.time() - t0) * 1000
                    ttfc = ttfc or (time.time() - t0) * 1000
                    content.append(dl["content"])
                if ch.get("finish_reason"):
                    finish = ch["finish_reason"]
    return {"extra": extra, "reasoning_chars": len("".join(reasoning)),
            "content_chars": len("".join(content)), "finish_reason": finish,
            "ttft_ms": round(ttft, 1) if ttft else None,
            "ttfc_ms": round(ttfc, 1) if ttfc else None,
            "content": "".join(content)}


def main():
    arms = [("default", {}),
            ("budget-512-on", {"thinking_budget_enabled": True, "thinking_budget_tokens": 512}),
            ("budget-512-on", {"thinking_budget_enabled": True, "thinking_budget_tokens": 512}),
            ("budget-512-on", {"thinking_budget_enabled": True, "thinking_budget_tokens": 512}),
            ("default", {}),
            ("default", {})]
    out = []
    for label, extra in arms:
        r = ask(extra)
        r["label"] = label
        out.append(r)
        print(f"{label:14} reasoning={r['reasoning_chars']:5}c content={r['content_chars']:4}c "
              f"ttfc={r['ttfc_ms']}ms finish={r['finish_reason']}", flush=True)
    with open(os.path.join(HERE, OUT), "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
