#!/usr/bin/env python3
"""Probe flint's request-level thinking controls.

flint's chat template has no `enable_thinking` switch at all — only assistant
turns with pre-filled reasoning are rendered, the model is never told not to
think. So the settings-level `enable_thinking` key is a no-op here and the only
levers are the request-level ones: `reasoning_effort` and `thinking_budget`.

Non-streaming, one request per arm: this probe only counts tokens, it does not
measure latency.
"""
import json
import sys
import urllib.request

OMLX = "http://127.0.0.1:8001"
MODEL = "flint-oQ4e"
PROMPT = (
    "Write a Python function `merge_intervals(intervals)` that merges "
    "overlapping closed intervals and returns them sorted. Include a docstring "
    "and three doctest examples. Output only the code."
)


def probe(label, extra):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 4000,
        "temperature": 0,
    }
    payload.update(extra)
    req = urllib.request.Request(
        f"{OMLX}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            d = json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"{label:28} ERROR {type(e).__name__}: {e}")
        return None
    if "choices" not in d:
        print(f"{label:28} {d}")
        return None
    u = d["usage"]
    c = d["choices"][0]["message"]
    row = {
        "label": label,
        "extra": extra,
        "completion_tokens": u["completion_tokens"],
        "reasoning_tokens": u["completion_tokens_details"]["reasoning_tokens"],
        "content_chars": len(c.get("content") or ""),
        "reasoning_chars": len(c.get("reasoning_content") or ""),
        "finish_reason": d["choices"][0]["finish_reason"],
        "gen_tps": u.get("generation_tokens_per_second"),
    }
    print(f"{label:28} ct={row['completion_tokens']:5} rt={row['reasoning_tokens']:5} "
          f"content_chars={row['content_chars']:5} finish={row['finish_reason']:6} "
          f"tps={row['gen_tps']}")
    return row


def main():
    arms = [
        ("plain", {}),
        ("reasoning_effort=low", {"reasoning_effort": "low"}),
        ("reasoning_effort=medium", {"reasoning_effort": "medium"}),
        ("reasoning_effort=high", {"reasoning_effort": "high"}),
        ("reasoning_effort=xhigh", {"reasoning_effort": "xhigh"}),
        ("reasoning_effort=max", {"reasoning_effort": "max"}),
        ("enable_thinking=false", {"enable_thinking": False}),
        ("ctk.enable_thinking=false", {"chat_template_kwargs": {"enable_thinking": False}}),
        ("thinking_budget=64", {"thinking_budget": 64}),
    ]
    out = [r for r in (probe(lbl, ex) for lbl, ex in arms) if r]
    with open("results/flint-oQ4e/tuning/think-probe.json", "w") as f:
        json.dump(out, f, indent=2)
    print("wrote results/flint-oQ4e/tuning/think-probe.json")


if __name__ == "__main__":
    sys.exit(main())
