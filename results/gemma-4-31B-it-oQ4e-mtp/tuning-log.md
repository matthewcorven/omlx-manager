# Tuning log — `gemma-4-31B-it-oQ4e-mtp`

Dense 30.7B `gemma4`, oQ4e + MTP head, vision-capable, 262144 native context.
Host: M4 Max / 128 GB. Server `http://127.0.0.1:8001` (0.7.3rc1).

## Measurement methodology

Absolute throughput drifted ~30% over this pass (56.1 tps at baseline, 40.06 tps at
the final 5-run, no config change between the ends of that range). Sequential
whole-config blocks cannot separate a config effect from that drift, so every verdict
below is a *paired* comparison:

1. **Interleaved A/B** (`tuning/ab.py`) — alternate the two settings per request so
   drift lands equally on both arms. Valid **only** for knobs that do not force a
   reload. Used for context, sampling, `force_sampling`, and the final
   baseline-vs-final check.
2. **Alternating blocks** (`tuning/block.py`) — reload-requiring knobs cannot be
   interleaved because every switch is a cold load. Apply, load, discard one warmup,
   take N runs, switch arms, repeat A,B,A,B. Used for the MTP depth finalists.
3. **Forward+backward ordering** (`tuning/sweep.py`) — run the config list forward
   then backward and pool. Exposes step changes in machine load that a single pass
   would silently attribute to the config. Used for the MTP and KV sweeps.
4. **Warmup discard is mandatory.** After a cold load the first request is slower;
   steady state recovers within a few runs.

**Consequence: no number in this log is comparable to a number in a different
block.**

### One contamination event, and it cost nothing

The coordinator restarted the oMLX server while smoke-testing an unrelated reranker,
which unloaded every model. This was noticed when a `POST /load` reported
`loaded: true` for ~105 s and then flipped to `loaded: false` with no request in
flight. **No measurement was in flight at the time**, so nothing was discarded; the
baseline was taken after the restart on a freshly loaded model. No restart fell
inside any kept run.

### One self-inflicted invalid sweep

The first KV sweep ran with **MTP off**, left over from the last arm of the MTP
sweep. Every arm landed at ~20.6 tps and the sweep was meaningless. It is kept on
disk as `tuning/kv-sweep.json` and is **not cited as evidence anywhere**. The valid
re-run is `tuning/kv-sweep-mtpon.json`. Lesson: assert the full settings state at the
start of a sweep, not just the knob under test.

---

## Chronological log

### 0. Preflight

- `du -sh ~/.omlx/cache` → 6.6 G. Healthy, nowhere near the 185 GB ceiling.
- Server up, 9 models registered, bench slot free.
- Model present at `~/.omlx/models/mlx-community/Jundot/gemma-4-31B-it-oQ4e-mtp`,
  19,971,960,832 B on disk.
- `model-mtp.safetensors` present (939 MB) → MTP is genuinely available.
- `chat_template.jinja` line 186 has a real `enable_thinking` switch.
- `moe-offload-fit` → HTTP 400 (dense). Expected.
- `activation_fp16_supported: false` — so `activation_fp16_enabled` is not a lever
  here and was left `false` without a sweep.

### 1. Smoke test and coherence check

- `measure.py --smoke` → `ttft=242.4 ms decode=0.0 tps` (16-token budget, expected).
- Streaming 400-token `merge_intervals` request → coherent Python, `finish: length`,
  0 reasoning chars. The model is not corrupt.

### 2. Baseline (defaults)

`runs.py`, 5 runs after one discarded warmup, `max_tokens 300`:

**TTFT 267.7 ms, decode 56.10 tps, prefill 183.1 tps, total 5579.1 ms.**

Defaults as discovered: MTP on with adaptive depth, KV quant off, native context,
card sampler (temp 1.0 / top_p 0.95 / top_k 64), `force_sampling: false`, thinking off.

### 3. MTP sweep (`sweep.py`, forward+backward, n=4 per arm)

| Arm | TTFT | Decode | Total |
|---|---|---|---|
| mtp-off | 243.6 ms | 21.45 tps | 14244 ms |
| **mtp-on-auto** | **271.0 ms** | **50.62 tps** | **6219 ms** |
| d1 | 296.1 ms | 32.47 tps | 9538 ms |
| d2 | 285.0 ms | 36.50 tps | 8478 ms |
| d3 | 269.6 ms | 38.73 tps | 7998 ms |
| d4 | 275.9 ms | 40.01 tps | 7747 ms |
| d6 | 277.6 ms | 39.50 tps | 7854 ms |
| d8 | 281.4 ms | 45.66 tps | 6831 ms |

MTP is a **2.4× decode win**. Adaptive beats every fixed depth 1–6 by 21–36%.
Depth 8 is the only close one.

### 4. MTP depth finalists (`block.py`, alternating blocks, n=9 per arm)

| Block | A | B | Verdict |
|---|---|---|---|
| auto vs d8 | 49.47 tps / 284.1 ms | 49.72 tps / 272.0 ms | tie — keep adaptive |
| auto vs d4 | 44.05 tps / 294.9 ms | 38.45 tps / 282.2 ms | d4 loses 13% |

Adaptive depth kept. No fixed depth is worth hard-coding.

### 5. KV sweep — first attempt (INVALID)

Ran with MTP off. All arms ~20.6 tps. Discarded; kept as `tuning/kv-sweep.json`
for the record only.

### 6. KV sweep with MTP on (`sweep.py`, forward+backward, n=4)

| Arm | TTFT | Decode | Total |
|---|---|---|---|
| **kv-off** | **264.9 ms** | **52.02 tps** | **6022 ms** |
| kv-8bit-skip | 285.7 ms | 49.33 tps | 6343 ms |
| kv-4bit-skip | 286.2 ms | 51.28 tps | 6117 ms |
| kv-4bit-noskip | — | — | **hard error** |

The `kv-4bit-noskip` arm died with `RuntimeError: no tokens received`. A direct probe
gave the real cause:

```
scaled_dot_product_attention(): incompatible function arguments
Invoked with types: mlx.core.array, mlx_vlm.turboquant._QuantizedStateProxy,
                    mlx_vlm.turboquant._QuantizedStateProxy
```

The quantized KV state reaches attention without being materialized. **4-bit KV
without `skip_last` does not run under MTP.** KV quant rejected: 8-bit costs 5%
decode, 4-bit is inside noise on decode, both cost 21 ms TTFT, and there is no
memory pressure to relieve.

### 7. Context A/B (`ab.py`, interleaved, n=5)

| Arm | TTFT | Decode |
|---|---|---|
| native 262144 | 300.3 ms | 41.51 tps |
| 32768 | 297.9 ms | 41.98 tps |

Inside noise. Re-run at `PAD=8000` (n=3):

| Arm | TTFT | Decode |
|---|---|---|
| native | 458.2 ms | 30.43 tps |
| 32768 | 451.6 ms | 29.14 tps |

Also inside noise. Native kept — free, and accepts prompts a 32768 cap rejects.

Note: `ab.py` takes **6 positional args** (`label_a patch_a label_b patch_b n out`),
not the `label=json` form `sweep.py` uses. The first invocation failed with
`JSONDecodeError`.

### 8. Sampling quality (`quality.py`, 3 guardrail prompts, streaming, `max_tokens 700`)

- Card sampler (1.0 / 0.95 / 64): 3/3 correct, `finish: stop`, 0 reasoning.
  TTFT 607 / 915 / 900 ms.
- Coding sampler (0.2 / 0.95 / 64): 3/3 correct, `finish: stop`, 0 reasoning.
  TTFT 287 / 245 / 220 ms.

Both pass. Coding sampler kept for determinism.

### 9. Sampling throughput A/Bs (`ab.py`, interleaved, n=5)

| Comparison | A | B | Verdict |
|---|---|---|---|
| card vs coding sampler | 49.02 tps / 281.5 ms | 48.42 tps / 282.2 ms | neutral |
| `force_sampling` off vs on | **42.29 tps / 309.3 ms** | 39.49 tps / 311.7 ms | **on costs 6.6%** |

`force_sampling` set to `false`.

### 10. Thinking A/B (`ab.py`-style paired, n=3, `max_tokens 700`, streaming)

| Arm | TTFC | Reasoning chars | Finish |
|---|---|---|---|
| off | **326.1 ms** | 0 | length |
| on | **15,879.8 ms** | 1,962–2,519 | length |

Thinking **works** on this model — real `reasoning_content`, then an answer — but
costs **48×** time-to-first-content-token and exhausts a 700-token budget before the
answer completes. Rejected; `enable_thinking: false`.

### 11. DFlash probes

- `dflash_enabled: true` + `mtp_enabled: true` → **HTTP 400** "MTP and DFlash cannot
  both be enabled".
- `dflash_enabled: true`, MTP off, `dflash_draft_model: null` → loads, but **21.71 tps**,
  indistinguishable from MTP off. No-op. Rejected.

### 12. MoE offload

`GET /admin/api/models/gemma-4-31B-it-oQ4e-mtp/moe-offload-fit` → **HTTP 400**.
Correct for a dense model. Recorded as N/A.

### 13. Final config applied

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

`requires_reload: true, auto_unloaded: true` → `POST /load`, polled to
`loaded: true`, `actual_size` 20,270,118,688.

- Final 5-run: **TTFT 297.0 ms, decode 40.06 tps, total 7691.6 ms.**
- Final quality: **3/3 pass.**

### 14. Final paired baseline-vs-final A/B (`ab.py`, interleaved, n=6 each)

| Arm | TTFT | Decode | Total |
|---|---|---|---|
| baseline-defaults | 316.3 ms | 37.06 tps | 8403 ms |
| final-temp0.2 | 319.5 ms | 37.39 tps | 8307 ms |

**Statistically identical.** The 56.1 → 40.06 tps gap between the separately-measured
baseline and final is pure machine drift, not a regression. This is the only valid
baseline-vs-final comparison in the pass.

### 15. Live settings read back

`GET /admin/api/models` → `.settings` for this model, 84 keys, written to
`settings-live.json`. Diffed against `final.json`'s `settings`: **0 differences**.
