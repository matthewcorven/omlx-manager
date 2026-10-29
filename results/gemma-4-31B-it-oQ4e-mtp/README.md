# `gemma-4-31B-it-oQ4e-mtp` — tuning result

Dense Gemma 4 30.7B, oQ4e, with a real MTP head. Tuned for small coding tasks.

| | |
|---|---|
| Repo | `mlx-community/Jundot/gemma-4-31B-it-oQ4e-mtp` |
| Quant | oQ4e, 4-bit affine group-64 base (5-bit on most attn/mlp projections, 6-bit on a few, BF16 embed/lm_head) |
| Architecture | `gemma4` **dense**, 60 layers, hidden 5376, sliding-window 1024, tied embeddings, vocab 262144, vision-capable |
| MTP | **yes** — `model-mtp.safetensors`, 0.47B draft head |
| Native context | 262144 |
| On disk | 18.60 GiB |
| Resident | 18.88 GiB |
| Profile | coding-tuned |

## Headline

**MTP is the only lever that matters, and it was already on by default.** Turning it
off halves decode throughput (50.62 → 21.45 tps). Every other knob was neutral or
negative. The final config is the default config with three deliberate changes:
thinking pinned off, a temp-0.2 coding sampler, and `force_sampling: false`.

| | TTFT | Decode | Total (300 tok) |
|---|---|---|---|
| Baseline (defaults) | 267.7 ms | 56.10 tps | 5579 ms |
| Final | 297.0 ms | 40.06 tps | 7692 ms |
| **Paired A/B, n=6 each** | **316.3 vs 319.5 ms** | **37.06 vs 37.39 tps** | 8403 vs 8307 ms |

The two absolute rows are **not** comparable — the machine drifted ~30% slower over
the pass. The paired interleaved A/B is the valid comparison and shows the two
configs equal within 1%. That is the honest result: the performance was already in
the MTP default, and the tuning pass confirmed it rather than improving on it.

## What helped

**MTP on, adaptive depth (kept).** 50.62 tps vs 21.45 tps with MTP off — a 2.4×
decode win. Every fixed depth lost to the adaptive default:

| Depth | Decode | vs adaptive |
|---|---|---|
| off | 21.45 tps | −58% |
| 1 | 32.47 tps | −36% |
| 2 | 36.50 tps | −28% |
| 3 | 38.73 tps | −23% |
| 4 | 40.01 tps | −21% |
| 6 | 39.50 tps | −22% |
| 8 | 45.66 tps | ties (49.72 vs 49.47 over 9 blocks each) |
| **adaptive (default)** | **50.62 tps** | — |

Depth 8 was re-tested with alternating blocks (n=9 per arm) and landed inside noise,
so the default is kept rather than replaced with a hand-picked number. This is the
**opposite** of the Qwen3.8-27B result, where depth 6 beat adaptive by 7%.

## What was rejected

- **KV quantization.** With MTP on: 8-bit costs 5% decode and 21 ms TTFT; 4-bit is
  inside noise on decode and also 21 ms worse on TTFT. There is no memory argument
  either — 18.88 GB resident is far under the ~89.6 GB ceiling.
- **KV 4-bit without `skip_last`.** Does not run at all under MTP — hard server error,
  see below.
- **`max_context_window: 32768`.** A genuine no-op at both a 49-token prompt
  (297.9 vs 300.3 ms, 41.98 vs 41.51 tps) and an ~8k prompt (451.6 vs 458.2 ms,
  29.14 vs 30.43 tps). Native 262144 is kept because it is free and accepts prompts
  a 32768 cap would reject.
- **`force_sampling: true`.** The one sampling knob with a real cost: 39.49 vs
  42.29 tps, −6.6% decode. Left `false`.
- **`enable_thinking: true`.** Unlike every other model in this repo, thinking
  **actually works** here — the template has a real switch and the model emits
  genuine `reasoning_content`. It is still rejected: **15.9 s to the first content
  token vs 0.33 s** with it off, a 48× latency penalty no small coding task can
  absorb. With `max_tokens: 700` the budget is exhausted by reasoning before the
  answer completes.
- **DFlash.** Mutually exclusive with MTP (HTTP 400). With MTP off and
  `dflash_draft_model: null` it is a no-op at 21.71 tps.
- **MoE expert offload.** Not applicable — `moe-offload-fit` returns HTTP 400 for
  this dense model (`enable_moe_block: false`). Recorded as N/A, not an error.

## Sampling

Both samplers produce correct code on all three guardrail prompts and are
throughput-neutral (49.02 vs 48.42 tps). The coding sampler is kept for determinism:

```
temperature 0.2, top_p 0.95, top_k 64, force_sampling false
```

## Failure modes hit

- `turboquant_kv_enabled: true` + `turboquant_kv_bits: 4.0` + `turboquant_skip_last: false`
  is a hard error under MTP: `scaled_dot_product_attention(): incompatible function
  arguments ... Invoked with types: mlx.core.array, mlx_vlm.turboquant._QuantizedStateProxy,
  mlx_vlm.turboquant._QuantizedStateProxy`. The quantized KV state reaches attention
  without being materialized. `skip_last` must stay `true` whenever KV quant is on.
- `dflash_enabled: true` + `mtp_enabled: true` → HTTP 400, mutually exclusive.
- `dflash_enabled: true` with MTP off and no draft model → loads, but is a no-op.
- `moe-offload-fit` → HTTP 400 for a dense model. Correct, not a bug.
- `enable_thinking: true` works but costs 15.9 s to first content token.
- Reload-requiring settings unload the model; `auto_unloaded` does not reload it.
  `POST /load` and poll until `loaded: true`.
- `measure.py` intermittently exits non-zero with no `run 1:` line; retry up to 3×.
- `GET /admin/api/models/{id}/settings` returns 405. Read `.settings` off
  `GET /admin/api/models`.

## Measurement caveat

Absolute throughput drifted ~30% over this pass (56.1 tps at baseline, 40.06 tps at
the final 5-run, with no config change between the ends of that range). No number
here is comparable to a number from a different block. Every verdict is a paired
comparison: interleaved A/B for non-reloading knobs, forward+backward ordering for
the reload-requiring MTP and KV sweeps, alternating blocks for the MTP depth
finalists. Baseline and final were additionally compared head-to-head in one
interleaved A/B precisely because their separately-measured medians differ by 29%
while the paired test shows them equal within 1%.

**A server restart by the coordinator fell inside this pass**, between the load
verification and the first measurement. No measurement was in flight, so nothing
was discarded; the baseline was taken after the restart on a freshly loaded model.

## Final settings

See [`final.json`](final.json) and [`settings-live.json`](settings-live.json). Live
`.settings` was read back from `GET /admin/api/models` after applying the config and
diffed against `final.json`: **0 differences across all 84 keys**.

```json
{
  "mtp_enabled": true,
  "mtp_adaptive_max_depth": null,
  "dflash_enabled": false,
  "turboquant_kv_enabled": false,
  "max_context_window": null,
  "enable_thinking": false,
  "temperature": 0.2,
  "top_p": 0.95,
  "top_k": 64,
  "force_sampling": false,
  "moe_expert_offload_enabled": false,
  "activation_fp16_enabled": false
}
```

## Quality

3/3 pass on the fixed guardrail prompts (pure function, bug fix, refactor), all with
`finish_reason: stop` and 0 reasoning tokens. Raw output in
[`tuning/quality-raw.json`](tuning/quality-raw.json).

## Files

| File | Contents |
|---|---|
| `final.json` | Full deliverable: sweep table, settings, rationale, failure modes |
| `settings-live.json` | `.settings` read back from the live server |
| `settings-start.json` | `.settings` as discovered before tuning |
| `baseline.json` | 5-run baseline on defaults |
| `final-runs.json` | 5-run measurement on the final config |
| `tuning/` | Harnesses and raw sweep output |
