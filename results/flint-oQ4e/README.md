# flint-oQ4e — coding-tuned profile

Re-tune of `flint-oQ4e` after the prior pass reached an inverted conclusion
(see [`CORRECTION.md`](CORRECTION.md)). This pass re-established a trustworthy
baseline on the corrected config and swept every knob that is actually wired up
on this model.

**Result: the corrected baseline is the final config.** No knob beat it.

| | TTFT | decode | total (300 tok) |
| --- | --- | --- | --- |
| baseline | 251.0 ms | 114.6 tps | 2859.9 ms |
| final | 252.0 ms | 113.23 tps | 2895.0 ms |

The 1.2% gap between those two rows is the same configuration measured twice —
that is the scale of run-to-run drift, and it is why every verdict below is a
paired comparison rather than a comparison of absolute numbers.

## What was swept

| knob | verdict | why |
| --- | --- | --- |
| KV quant (8-bit, 4-bit, ±skip_last) | **rejected** | 16–18% decode loss (114.94 → 94.22–96.78 tps) and 5–11 ms worse TTFT. This model is bandwidth-bound on a 2.5B-active MoE; dequantizing KV every step costs more than the bandwidth it saves. |
| `max_context_window` native vs 32768 | **native kept** | No-op at 34 tokens, 16k and 20k prompts (≤1.7 ms TTFT, ≤0.35 tps), and resident memory is byte-identical at 22.84 GB either way. Native is free and accepts prompts 32768 rejects outright. |
| MTP / DFlash / spec-prefill | **not applicable** | `mtp_compatible: false` ("model has no MTP heads in config"), no `model-mtp.safetensors` in the model dir, `dflash_compatible: false`, `specprefill_draft_model: null`. No draft head exists, so these settings are inert. |
| sampling (card vs temp 0.2) | **card kept** | Sampling does not affect throughput. Both samplers produced correct code on all three guardrail prompts, so the model's own `generation_config.json` (temp 1.0 / top_p 0.95 / top_k 20) wins and `force_sampling` stays `false`. |
| `reasoning_effort` low→max | **rejected** | No effect. `max` produced the *shortest* reasoning of the six arms, so the spread is variance, not a lever. |
| `thinking_budget_enabled` + tokens | **rejected** | Accepted by `PUT` and echoed back, but not enforced on flint. Reasoning length unchanged within variance across 256/512/1024 and three repeats at 512. |
| `enable_thinking: false` | **kept (required)** | A no-op: `chat_template.jinja` has no such switch and flint always reasons. Kept `false` per the task contract. |
| `activation_fp16_enabled` | **never swept** | `activation_fp16_supported: false`. `true` is a corruption switch on this model, not a speedup. |

## The number that actually matters: TTFC, not TTFT

Flint always reasons. On a small coding task it streams ~250 tokens of
`reasoning_content` before the first `content` token, so:

- **TTFT** (first token of any kind) ≈ 250 ms
- **TTFC** (first *content* token) ≈ 3.8–14.8 s

TTFC is the user-visible latency, and it is dominated by reasoning-length
variance (3.7k–8.9k characters run to run) that no setting on this model
controls. The throughput knobs above are worth ~0–20% of decode; the reasoning
phase is worth 15–60× that. If TTFC matters, the lever is the prompt, not the
settings.

## Files

- [`final.json`](final.json) — the deliverable: metadata, baseline, final medians, full sweep, settings, rationale, failure modes.
- [`settings-live.json`](settings-live.json) — read back from `GET /admin/api/models` → `.settings` **after** the final config was applied and the model reloaded. Byte-identical to `final.json`'s `settings` object.
- [`final-settings.json`](final-settings.json) — same object, kept for the naming the prior pass used.
- [`baseline.json`](baseline.json) — the 3-run baseline on the corrected config.
- [`final-runs.json`](final-runs.json) — the 3-run measurement on the applied final config.
- [`tuning/`](tuning/) — harnesses and raw sweep output. `ab.py` (interleaved A/B), `block.py` (alternating blocks for reload-requiring knobs), `sweep.py` (forward+backward), `runs.py`, `quality.py` (streaming guardrail), `effort_probe.py` (thinking-lever probe).

## Reproducing

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=http://127.0.0.1:8001

# baseline / final
python3 results/flint-oQ4e/tuning/runs.py results/flint-oQ4e/final-runs.json 3 300 0

# context (non-reloading → interleaved)
cd results/flint-oQ4e/tuning
./ab.py ctx-native '{"max_context_window":null}' ctx-32768 '{"max_context_window":32768}' 6 out.json
PAD=20000 ./ab.py ctx-native-pad20k '{"max_context_window":null}' ctx-32768-pad20k '{"max_context_window":32768}' 3 out-pad20k.json

# KV quant (reloading → forward+backward sweep)
./sweep.py 3 kv-sweep-retune.json \
  'kv-off={"turboquant_kv_enabled":false}' \
  'kv-8bit-skip={"turboquant_kv_enabled":true,"turboquant_kv_bits":8,"turboquant_skip_last":true}' \
  'kv-4bit-skip={"turboquant_kv_enabled":true,"turboquant_kv_bits":4,"turboquant_skip_last":true}' \
  'kv-4bit-noskip={"turboquant_kv_enabled":true,"turboquant_kv_bits":4,"turboquant_skip_last":false}'

# quality guardrail (streaming, max_tokens >= 350 is mandatory)
TEMP=1.0 TOP_P=0.95 TOP_K=20 MAXTOK=3000 python3 quality.py quality-raw.json
```

## Traps

- `max_tokens` below ~350 makes flint spend the whole budget on
  `reasoning_content` and return `content: ""` with `finish_reason: length`.
  That is not corruption.
- `--context-pad 30000` expands to ~41k tokens, which `max_context_window:
  32768` rejects with HTTP 400. Check pad size against the cap under test.
- Changing a reload-requiring setting unloads the model; `auto_unloaded` does
  not reload it. `POST /load` and poll until `loaded: true`.
- `GET /admin/api/models/{id}/settings` returns 405. Read `.settings` off
  `GET /admin/api/models`.
- `measure.py` intermittently exits non-zero with no `run 1:` line. Retry up to 3×.
