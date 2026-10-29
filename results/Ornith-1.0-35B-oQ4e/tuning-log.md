# Tuning log — `Ornith-1.0-35B-oQ4e`

Model: `Jundot/Ornith-1.0-35B-oQ4e`, oQ4e 4-bit, 20.64 GB on disk / 19.86 GB
resident, native context 262144, `model_type: vlm`, `config_model_type:
qwen3_5_moe`. True MoE — 256 experts, 8 per token, 40 layers, hybrid
linear/full attention (full every 4th layer). **No MTP head**
(`mtp_num_hidden_layers: 0`, `mtp_compatible: false`).

## Measurement methodology

The previous model's session proved that absolute throughput on this machine
drifts enormously (88 → 22 tps with no config change), so **no number in this
log is comparable to a number from a different block**. Every verdict below is a
paired comparison:

| Knob class | Harness | Why |
| --- | --- | --- |
| Does not reload (`max_context_window`, `enable_thinking`) | `tuning/ab.py`, `tuning/ab_ttfc.py` | interleaved single-request A/B cancels drift |
| Forces a reload (`dflash_enabled`, `specprefill_enabled`, `turboquant_*`) | `tuning/block.py` | alternating A,B,A,B blocks with warmup discard |
| Multi-value reload sweep (KV quant) | `tuning/sweep.py` | forward then backward ordering, pooled medians |

`ab_ttfc.py` is a new variant of `ab.py` written for this model: `ab.py` only
parses `ttft/decode/total`, and the thinking stage needs **time to first
*content* token** (`ttfc`), because with thinking on the first token is a
reasoning token and the user-visible answer starts much later — or never.

This session was quiet throughout (decode 127–155 tps, no step change), unlike
the Qwen3.8 session.

## Baseline

Defaults, `enable_thinking: false`, one warmup discarded, 3 runs, `max_tokens 300`:

| | TTFT | TTFC | decode | total |
| --- | --- | --- | --- | --- |
| median | 52.0 ms | 52.0 ms | 146.72 tps | 2090.3 ms |

Thinking is **on by default** (`thinking_default: true`). The first two probes
before disabling it produced `ttfc=None` — zero content tokens, the entire
300-token budget spent in `reasoning_content`. See the thinking stage below.

## Sweep results

### 1. Context window — KEPT native 262144

Interleaved paired A/B, 5 samples per arm, `max_context_window` does not reload.

| variant | TTFT | decode |
| --- | --- | --- |
| native 262144 | 58.8 ms | 151.90 tps |
| 32768 | 59.0 ms | 151.24 tps |

**Null result.** The Qwen3.8-27B finding that 32768 is faster on both TTFT and
decode does **not** reproduce here — 32768 is 0.3% slower on TTFT and 0.4%
slower on decode, both inside noise. Native context is kept, which is also the
better default for a model whose selling point is a 262144 window.

### 2. Thinking budget — HARD CONSTRAINT, thinking off

Interleaved paired A/B, `max_tokens 1500`, 3 samples/arm (budgeted) and 2
samples/arm (unbudgeted).

| variant | TTFT | TTFC | decode |
| --- | --- | --- | --- |
| thinking off | 62.2 ms | **62.2 ms** | 145.52 tps |
| thinking on, budget 512 | 61.0 ms | **4076.1 ms** | 131.95 tps |
| thinking on, unbudgeted | 58.4 ms | **null (0/2 runs)** | 142.81 tps |

Two distinct failure modes:

1. **Unbudgeted thinking never answers.** 1500 completion tokens, all of them
   `reasoning_content`, `ttfc` null in 2/2 runs. This is exactly the Qwen3.8
   behaviour and it is a hard constraint, not a preference.
2. **A budget does not cap, it floors.** With `thinking_budget_tokens: 512` the
   model still spent ~500 reasoning tokens before emitting an answer, so
   time-to-answer was 4076 ms — **65x worse** than thinking off — and decode was
   9% slower on top.

Verdict: `enable_thinking: false`. For small coding tasks there is no
configuration of thinking on this model that is usable.

### 3. DFlash — REJECTED

Alternating blocks, 3 runs × 2 blocks. `dflash_enabled` sets `requires_reload:
true` and `auto_unloaded: true`, so this must never be interleaved per request.

| variant | TTFT | decode |
| --- | --- | --- |
| DFlash off | 59.7 ms | 148.75 tps |
| DFlash on | 59.4 ms | 148.85 tps |

+0.07% decode, −0.5% TTFT — inside noise. `dflash_compatible` is `true` but
`dflash_draft_model` is `null`, so there is no draft to speculate with; the flag
alone does nothing. Rejected.

### 4. SpecPrefill — REJECTED

Alternating blocks, 3 runs × 2 blocks.

| variant | TTFT | decode |
| --- | --- | --- |
| SpecPrefill off | 62.4 ms | 150.47 tps |
| SpecPrefill on | 60.9 ms | 147.66 tps |

The 2.4% TTFT lead is inside noise and comes with a 1.9% decode regression.
`specprefill_draft_model` is also `null`. Rejected.

**Speculative decoding is a dead end on this model.** There is no MTP head, and
both remaining levers require a draft model that is not configured. This is
recorded as an explicit negative result rather than left untested.

### 5. MoE expert offload — NOT APPLICABLE

`moe_expert_offload_supported: true` and the model is a genuine MoE, but it sits
at 19.86 GB resident against an `model_memory_max` of 89.23 GB. Expert offload
exists to relieve residency pressure; there is none. Considered and deliberately
not enabled — enabling it would only add SSD traffic.

### 6. KV quantization (TurboQuant) — KEPT off

Forward+backward sweep, 3 runs × 2 passes per config.

| variant | TTFT | decode |
| --- | --- | --- |
| KV quant off | 60.3 ms | **151.63 tps** |
| 8-bit + skip_last | 62.2 ms | 129.03 tps |
| 4-bit + skip_last | 62.6 ms | 130.11 tps |
| 4-bit, no skip_last | 62.2 ms | 126.98 tps |

Every TurboQuant configuration loses **14–16% decode** with no TTFT benefit.
This is the sharpest divergence from Qwen3.8-27B, where KV quant was a real win.
`skip_last` is worth ~2.5% decode *within* the quantized family (130.11 vs
126.98) — the previous model's finding reproduces in direction — but it cannot
rescue a family that is 14% behind off. KV quant stays off.

### 7. Sampling — applied, no speed measurement

Model card / `generation_config.json`: `temperature 1.0`, `top_p 0.95`,
`top_k 20`, `do_sample: true`. Applied verbatim with `force_sampling: true` so
the profile's sampler is authoritative over the generation config. No invented
values, no speed measurement (sampling does not affect throughput).

### 8. Quality guardrail — PASSED

All three fixed prompts pass at the final config. See `quality.md`.

## Final configuration

```json
{
  "enable_thinking": false,
  "max_context_window": null,
  "dflash_enabled": false,
  "specprefill_enabled": false,
  "turboquant_kv_enabled": false,
  "moe_expert_offload_enabled": false,
  "temperature": 1.0,
  "top_p": 0.95,
  "top_k": 20,
  "force_sampling": true
}
```

Applied live and verified: `final-settings.json` diffed against `.settings` from
`GET /admin/api/models` — **0 diffs** across all 10 keys.

Final medians on the applied config (3 runs, warmup discarded, `max_tokens 300`):
TTFT 48.0 ms, TTFC 48.0 ms, decode 146.34 tps, total 2091.7 ms.

## Failure modes hit

- **Thinking is on by default and silently produces zero content tokens.** Every
  measurement before `enable_thinking: false` was meaningless.
- **`thinking_budget_tokens` is a floor in practice, not a cap** — a 512-token
  budget still yielded ~500 reasoning tokens and a 4076 ms ttfc.
- **`dflash_enabled` sets `requires_reload: true` + `auto_unloaded: true`.** It
  must never be interleaved per request; use `block.py`. This is the exact bug
  that produced the previous agent's bogus ~2900 ms TTFTs.
- **`auto_unloaded: true` unloads but does not reload** — the harness must
  `POST /load` and poll. `block.py` already does.
- **`dflash_enabled` XOR `mtp_enabled`** (HTTP 400); a leftover `dflash_enabled:
  true` blocks later MTP PUTs.
- **`measure.py` intermittently exits non-zero with no `run 1:` line** — retry
  up to 3×.
- **`measure.py` prints `ttfc=None`** when no content token arrives; that is the
  only signal that thinking swallowed the whole budget.
- `ab_ttfc.py` initially crashed on `ttfc=None` because it did
  `float("None".removesuffix("ms"))`; fixed to return `None` explicitly.
