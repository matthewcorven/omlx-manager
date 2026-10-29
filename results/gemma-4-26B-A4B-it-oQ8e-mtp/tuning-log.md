# Tuning log — `gemma-4-26B-A4B-it-oQ8e-mtp`

MoE 26.23B total / 4.82B active, `gemma4`, oQ8e + MTP head, vision-capable, 262144
native context. Host: M4 Max / 128 GB. Server `http://127.0.0.1:8001` (0.7.3rc1).

## Measurement methodology

Sequential whole-config blocks cannot separate a config effect from machine drift, so
every verdict below is a *paired* comparison:

1. **Interleaved A/B** (`tuning/ab.py`) — alternate the two settings per request so
   drift lands equally on both arms. Valid **only** for knobs that do not force a
   reload. Used for context, sampling, `force_sampling`, and thinking.
2. **Alternating blocks** (`tuning/block.py`) — reload-requiring knobs cannot be
   interleaved because every switch is a cold load. Apply, load, discard one warmup,
   take N runs, switch arms, repeat A,B,A,B. Used for MTP off/on, the depth
   finalists, and the whole-config head-to-head.
3. **Forward+backward ordering** (`tuning/sweep.py`) — run the config list forward
   then backward and pool. Exposes step changes in machine load that a single pass
   would silently attribute to the config. Used for the MTP and KV sweeps.
4. **Warmup discard is mandatory.** After a cold load the first request is slower.

**Consequence: no number in this log is comparable to a number in a different block.**

## Sequence

### 0. Preflight
- `du -sh ~/.omlx/cache` → 16G, well under the limit.
- Model unloaded, benchmark slot free, server `ok`.
- `moe-offload-fit?mtp_enabled=true` → `{"status":"resident","max_percent":null,
  "bytes":0}` → **MoE offload not applicable**, recorded and not tuned.
- `activation_fp16_supported: false` → knob not probed.
- `dflash_draft_model` / `specprefill_draft_model` → both null.
- Saved `settings-start.json`.

### 1. Load + smoke test
Model loaded at 26.93 GiB resident. One streamed request returned coherent
`merge_intervals` code, `finish_reason: stop`, 0 reasoning chars, TTFT 600 ms (cold),
94.35 tps. Coherent → proceed.

### 2. Thinking pinned off, baseline
`enable_thinking: false` applied (no reload needed). `baseline.json`: **TTFT 116.0 ms,
decode 113.18 tps, total 2743.3 ms** over 3 runs at `max_tokens 300`.

### 3. Thinking A/B (`tuning/thinking-ab.json`)
Interleaved, n=3 per arm, `max_tokens 900`, streamed.

| arm | TTFT | TTFC | content | reasoning | finish |
|---|---|---|---|---|---|
| off | 106.2 ms | 106.2 ms | 1135-1181 chars | 0 | stop |
| on | 333.4 ms | **8951.0 ms** | 1 char | 2773-2868 chars | length |

Thinking genuinely works (real `reasoning_content`) but costs 84x to the first
content token and eats the entire budget. **Verdict: thinking off, pinned.**

### 4. MTP off vs on (`tuning/block-mtp-off-vs-mtp-on-adaptive.json`)
Alternating blocks, n=3 × 2 blocks:

| arm | TTFT | decode |
|---|---|---|
| MTP off | 83.6 ms | 76.71 tps |
| MTP on, adaptive | 118.4 ms | 113.00 tps |

MTP on wins +47% decode for +35 ms TTFT. **KEEP MTP on.** Output read on both arms:
coherent Python both sides, so the speedup is real.

### 5. MTP depth sweep (`tuning/mtp-sweep.json`)
Forward+backward, n=2 each direction (n=4 pooled):

| config | TTFT | decode |
|---|---|---|
| off | 75.2 ms | 81.88 |
| adaptive | 116.9 ms | 112.14 |
| d1 | 104.7 ms | 97.07 |
| d2 | 103.6 ms | 108.85 |
| d3 | 112.9 ms | 112.32 |
| **d4** | **102.1 ms** | **119.03** |
| d6 | 103.7 ms | 101.00 |
| d8 | 109.3 ms | 93.44 |

Single clear peak at depth 4 — unlike the 31B, where fixed depths lost and only d8
tied.

### 6. Depth finalists (alternating blocks, n=5 × 2 = 10 per arm)
`tuning/block-mtp-adaptive-vs-mtp-d4.json`: adaptive 109.72 tps / 120.3 ms vs
**d4 119.28 tps / 107.4 ms** → d4 wins on both axes (+8.7% decode, −13 ms TTFT).

`tuning/block-mtp-d3-vs-mtp-d4.json`: d3 116.83 tps / 107.7 ms vs d4 118.35 tps /
105.2 ms → d4 slightly better on both. **KEEP fixed depth 4.**

### 7. KV quant sweep with MTP at depth 4 (`tuning/kv-sweep-mtpon.json`)
Forward+backward, n=4 pooled:

| arm | TTFT | decode |
|---|---|---|
| **off** | **99.8 ms** | **118.04** |
| 8-bit + skip_last | 105.0 ms | 111.54 |
| 4-bit + skip_last | 105.7 ms | 115.07 |

KV off wins on both axes; there is no memory pressure to justify either quantized
arm. **KEEP KV quant off.**

### 8. 4-bit KV without skip_last — probe (`tuning/kv-4bit-noskip-*.json`)
PUT succeeded (`requires_reload`, `auto_unloaded`), model loaded, first decode
returned an SSE error event:

```
scaled_dot_product_attention(): incompatible function arguments ...
Invoked with types: mlx.core.array, mlx_vlm.turboquant._QuantizedStateProxy,
mlx_vlm.turboquant._QuantizedStateProxy
```

Recorded as a failure mode, then reverted to `turboquant_kv_enabled: false` with
`skip_last: true`, reloaded, and confirmed decode works again (116.28 tps, coherent
code).

### 9. Context window (`tuning/ab-ctx.json`, `tuning/ab-ctx-8k.json`)
Interleaved, n=5 each.

| prompt | native 262144 | 32768 |
|---|---|---|
| short (49 tok) | 104.7 ms / 121.38 tps | 106.2 ms / 121.31 tps |
| ~8k (`--context-pad 8000`) | 178.9 ms / 96.93 tps | 181.3 ms / 96.92 tps |

Null result at both lengths. **KEEP native 262144** — free, and accepts prompts a
32768 cap would reject.

### 10. Sampling (`tuning/ab-sampling.json`, `tuning/ab-force-sampling.json`)
Interleaved, n=5 each.

| arm | TTFT | decode |
|---|---|---|
| card temp 1.0 / 0.95 / 64 | 117.5 ms | 118.22 tps |
| coding temp 0.2 / 0.95 / 64 | 113.7 ms | 116.90 tps |
| force_sampling false | 111.0 ms | 114.86 tps |
| force_sampling true | 115.9 ms | 113.70 tps |

Sampling is throughput-neutral (within noise both ways); the coding sampler is kept
for determinism, `force_sampling` stays false because it costs 1% for no benefit.

### 11. DFlash / SpecPrefill
`dflash_draft_model` and `specprefill_draft_model` are both null → **no-ops**, nothing
to draft from. `dflash_enabled: true` with MTP on returns **HTTP 400**:
`mtp_enabled and dflash_enabled cannot both be True; choose one speculative-decoding
path per model` (`tuning/dflash-with-mtp-put.json`). Reverted.

### 12. MoE offload
**Not applicable** — `moe-offload-fit?mtp_enabled=true` returns
`{"status":"resident","max_percent":null,"bytes":0}`. The model fits resident, so
there is nothing to offload. Not tuned.

### 13. Final config applied and verified
Final config PUT, model reloaded (`loaded: true`), then live settings diffed against
the intended JSON: **zero differences on all 14 keys**. `enable_thinking` re-read
after the final benchmark: still `false`.

### 14. Final measurement and quality
`final-runs.json`: 5 runs → TTFT 117.3 ms, decode 118.6 tps, total 2635.8 ms.

Paired whole-config head-to-head (`tuning/block-baseline-defaults-vs-final-config.json`,
alternating blocks, n=6 per arm):

| config | TTFT | decode |
|---|---|---|
| server defaults | 120.3 ms | 118.52 tps |
| **final config** | **114.2 ms** | **123.06 tps** |

+3.8% decode and −6 ms TTFT, paired. The tuning bought a real but modest gain — most
of the performance was already in the MTP default.

Quality guardrails (`quality.md`, `quality-raw.json`): 3 prompts, streamed,
`max_tokens 700`, coding sampler. All three returned correct code, empty
`reasoning_content`, `finish_reason: stop`.

## Incidents and traps hit

- **`runs.py` writes its output relative to the repo root**, not the tuning directory,
  so `final-runs.json` first landed one level above the repo. Moved into place.
- **Reload traps are real.** `mtp_*`, `turboquant_kv_*` and `dflash_enabled` PUTs
  return `auto_unloaded` without `auto_reloaded`; the model must be re-`POST /load`ed
  and polled to `loaded && !is_loading` before measuring. Re-PUTting a reload patch
  before every request pays a cold load every time and fakes a ~2900 ms TTFT — that
  was avoided by only re-PUTting non-reloading knobs inside `ab.py`.
- **Polling bug avoided:** a shell `case "$s" in True*)` on a JSON-derived string
  starting with lowercase `true` never matches. Polling here matched `"True False"`
  exactly.
