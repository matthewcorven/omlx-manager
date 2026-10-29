# Qwen3.6-35B-A3B-oQ8e-mtp — tuning notes

**Model:** `mlx-community/Jundot/Qwen3.6-35B-A3B-oQ8e-mtp` — **MoE** 35.1B total /
~3B active, `qwen3_5_moe`, 40 layers, hidden 2048, 256 experts with top-8 routing,
moe_intermediate 512, hybrid **Gated DeltaNet + Gated Attention** stack (30
`linear_attention` + 10 `full_attention`, `full_attention_interval` 4), 16 query /
2 KV heads, head_dim 256, untied embeddings, vocab 248320, fused image handling
(`engine_type: vlm`), 262144 native context, **MTP head present**
(`mtp_num_hidden_layers` 1, 0.845B params).
**Download size:** 36 GiB on disk (40,535,237,244 B `estimated_size`).
**Resident size:** 40,535,237,244 B (measured as the `api/status.model_memory_used`
delta across the load; the API reports `resident_size: null` for this model).
**Profile:** `coding-tuned`. **Final medians (5 runs):** TTFT 76.7 ms, decode 183.72 tps,
total 1703.5 ms.

Quantization is **oQ8e**: 8-bit affine group-64 base with imatrix calibration
(`oq_imatrix_report.json`, `oqe_code_multilingual`, 128×512 samples, 523 entries
applied), with per-layer group-128 overrides on the DeltaNet projections.

---

## The one thing to read first

**No number in this report is comparable to a number from a different block.**
Absolute decode throughput on this machine moves 30%+ between sessions with no
config change. Every verdict below is a *paired* comparison:

- **interleaved A/B** (`tuning/ab.py`) — alternates A,B,A,B per request, so drift
  hits both arms equally. Used for `max_context_window`, sampler, `force_sampling`,
  `enable_thinking` (none of these reload).
- **alternating blocks** (`tuning/block.py`) — apply → settle → discard warmup →
  N measured runs, then swap arms and repeat. Used for everything that reloads:
  MTP depth, KV quant, ANE prefill, and the whole-config head-to-head.
- **forward+backward ordering** (`tuning/sweep.py`) — each value measured once going
  up the list and once coming down, so a monotonic load ramp cancels.

The baseline 3-run read **182.37 tps** and the final 5-run read **183.72 tps**, but
those two numbers are from different blocks and are **not** a comparison. The
comparison is the paired whole-config test below.

---

## What helped

**Exactly one thing: turning thinking off.** That is the whole gain, and it is large
because it is not really a throughput knob — it is a "the model can answer at all"
knob.

### Whole-config head-to-head (the only legitimate defaults-vs-final number)

`tuning/block-baseline-defaults-vs-final-config.json`, alternating blocks, n=5 × 2
blocks = **n=10 per arm**:

| Arm | TTFT | Decode | Total |
|---|---|---|---|
| server defaults (adaptive MTP, card sampler, thinking unset) | 74.2 ms | 161.22 tps | 1929 ms |
| **final config** (depth 4, temp 0.6, thinking off) | 77.4 ms | **183.89 tps** | **1704 ms** |

Paired: **+14.1% decode, −225 ms total, +3.2 ms TTFT.** The TTFT tick is the price of
`mtp_fixed_depth: 4` (see below) and is small next to the decode gain.

The 14% is attributable almost entirely to `enable_thinking`, not to MTP depth or the
sampler, and that was verified directly rather than assumed:

`tuning/ab-thinking-null-vs-off.json`, interleaved n=5, with `mtp_fixed_depth: 4` and
the coding sampler held constant in both arms:

| Arm | TTFT | Decode |
|---|---|---|
| `enable_thinking: null` | 76.3 ms | 171.72 tps |
| `enable_thinking: false` | 76.9 ms | **183.97 tps** |

**+7.1% decode from pinning thinking off.** And a single-request spot check confirms
the mechanism: with `enable_thinking: null` on a plain 300-token request, the model
emitted **10 reasoning chunks** (`ttfc=None`, `reasoning=10`), i.e. `null` is *not*
"off" on this model even though `thinking_default: true` and the server appears to
treat an unset value as "let the template decide". With `false` it emitted zero.

### MTP depth

`mtp_num_hidden_layers` is **1** here, unlike the gemmas' 4, so the depth curve is
different: it plateaus at 3–4 and falls off a cliff past 5.

`tuning/sweep.py 3 mtp-sweep.json` (adaptive, 1, 2, 3, 4, 6, 8 — forward then
backward, n=6 per value):

| Variant | TTFT | Decode | vs best |
|---|---|---|---|
| adaptive (default) | 73.2 ms | 181.48 tps | −0.9% |
| fixed 1 | 69.8 ms | 141.01 tps | −23% |
| fixed 2 | 70.9 ms | 176.28 tps | −3.7% |
| fixed 3 | 73.7 ms | 182.81 tps | −0.2% |
| **fixed 4** | 73.2 ms | **183.13 tps** | — |
| fixed 6 | 91.2 ms | 163.55 tps | −11% |
| fixed 8 | 108.5 ms | 123.12 tps | −33% |

Head-to-head against adaptive, `tuning/block-mtp-adaptive-vs-mtp-fixed4.json`,
alternating blocks n=10/arm: **fixed 4 182.96 tps / 72.9 ms vs adaptive 181.19 tps /
73.6 ms** (+1.0%, better on both axes). Repeated later with thinking off held in both
arms (`block-adaptive-recheck-vs-fixed4-recheck.json`, n=10/arm): **183.45 vs 182.14
tps** (+0.7%), TTFT 77.2 vs 76.0 ms.

**Honest read: the depth-4 win is ~1% and inside plausible noise.** It is a *kept*
recommendation of the same magnitude the gemma-4-26B pass claimed for its depth-4
choice (+8.7% there, so much clearer). It is not a headline number here. Adaptive is
a defensible alternative and the difference between the two configs is not what the
14% comes from. The cliff is real though — 6 and 8 cost 11% and 33%, so if you ever
pin a depth, pin 4 and never above 5.

#### Coordinator re-measurement — the +1% does not reproduce

Three further paired runs were made against the live server, and the depth-4
advantage did not hold up:

| Run | adaptive | fixed 4 | Result |
|---|---|---|---|
| `block-coord-adaptive-vs-coord-fixed4.json` (n=12/arm) | 173.11 | 187.25 | fixed 4 +8.2% |
| `block-coord-fixed4b-vs-coord-adaptiveb.json` (n=12/arm, arms swapped) | 183.87 | 179.56 | **adaptive +2.4%** |
| `block-coord-adaptive3-vs-coord-fixed4-3.json` (n=15/arm, 3 blocks) | 180.24 | 187.03 | fixed 4 +3.8% |
| `block-coord-null-A-vs-coord-null-B.json` (n=15/arm, **identical config both arms**) | 181.53 | 178.22 | null spread 1.8% |

The first run's +8.2% is a warmup ramp, not a config effect: the adaptive arm's
samples climb 145.6 → 181.5 across the block while fixed 4 is flat 182.8–190.5.
Swapping the arms reverses the sign. The null test — the *same* config in both
arms — produces a 1.8% spread, which is the same size as the effect being claimed.

**Verdict: MTP depth 4 vs adaptive is a null result on this model.** The sweep's
ordering (fixed 4 first at 183.13 vs adaptive 181.48) is within the noise floor
established by the null test. `mtp_fixed_depth: 4` is left applied because it is
harmless and the cliff above 5 is real, but it must not be reported as a gain.
The whole-config +14% is unaffected — it is the thinking pin, and that was
re-verified independently (see below).

## What did nothing, or was rejected

### ANE prefill — the model-specific lever, and it is a null

This is the one knob no previously-tuned model exercised (`ane_prefill_backend: "qwen"`,
`ane_prefill_default_fraction: 0.53`). It is genuinely active — the server log shows
`Warmed 142 ANE procedures in 0.1s at load`, `Eagerly compiled 41 MLP and 30 GDN
procedures into 2 instance-pinned ANE programs (sequence_length=2048)`,
`Capped ANE GDN output rows from requested 0.500 to 0.333`. It reloads
(`requires_reload: true, auto_unloaded: true`), so everything below is alternating blocks.

| Test | ANE off | ANE on | Verdict |
|---|---|---|---|
| short prompt, `tail_padding 0` vs `1024` (sweep.py, n=6) | 75.4 ms / 176.74 tps | 75.2 / 179.52 | null |
| short prompt head-to-head (n=10/arm) | 74.0 / 173.79 | 73.2 / 183.41 | **not trusted** — see below |
| `--context-pad 8000` (n=8/arm) | 163.8 ms / 167.38 | 161.7 / 167.66 | null |
| `--context-pad 32000` (n=6/arm) | 475.3 ms / 140.78 | 481.4 / 140.45 | null |
| **cold prefill, ~21.7k tokens, cache defeated (n=6/arm)** | **16673.6 ms / 146.87** | **16741.7 / 142.75** | **null** |

The short-prompt head-to-head is the one that looked like a win (173.79 → 183.41), and
it is a **drift artifact**: block 1 arm A ran cold (samples 164.2, 164.8, 163.6, 164.7,
166.6 tps) while everything after it — including block 2 arm A — sat at 181–184 tps.
The harness spread the cold block across one arm. Discard block 1 and the two arms are
identical. That is recorded in `tuning-log.md` as a dead end, not a result.

**The important methodological finding on this model:** with the stock
`measure.py` prompt, the paged prefix cache serves the *entire* prefill. The server log
for a `--context-pad 32000` run reads `Prefix cache restore ... cached=41001 suffix=7
blocks=11`, so the measured TTFT is cache restore, not prefill, and *every* prefill-path
knob will look null. `tuning/coldprefill.py` exists to defeat this: it prefixes each
request with a fresh random nonce so the cache always misses. Under that harness the
prompt was ~21.7k tokens with `cached_tokens: 0`, TTFT ~16.7 s, prefill ~1310 tok/s —
and ANE prefill still bought nothing (16673.6 vs 16741.7 ms, i.e. 0.4% *worse*, well
inside noise).

**ANE prefill verdict: rejected — no measurable TTFT gain at 8k, 32k, or on a cold
~21.7k-token prefill, and no decode gain.** It is left `false` (as it was found).
The lever is real and the kernels do compile and run; the hardware just does not beat
the GPU path on this MoE shape. Confirmed null, not an untested knob.

### KV quantization

Four arms, `tuning/sweep.py` forward+backward, n=6 each
(`tuning/kv-sweep-4arm.json`):

| Arm | TTFT | Decode |
|---|---|---|
| **off** | 71.4 ms | **190.96 tps** |
| 8-bit + `skip_last` | 74.6 ms | 185.81 tps |
| 4-bit + `skip_last` | 72.7 ms | 176.84 tps |
| 4-bit, `skip_last: false` | 72.8 ms | 177.69 tps |

KV quant is rejected: it costs 2.7–7.4% decode for a memory saving this model does not
need (40.5 GB resident against a ~101 GB ceiling). Note the 4-bit rows are *internally
consistent* in decode (~177) but the 4-bit-skip arm's absolute position in the sweep is
not comparable to the first 3-arm sweep (`kv-sweep.json` read 185.45 for off and 176.32
for 4-bit-skip) — different blocks. The ordering is stable across both sweeps, which is
the usable signal.

**Failure mode that did NOT reproduce.** The playbook documents
`turboquant_skip_last: false` with KV quant on as a hard runtime error under MTP
("the quantized KV state is passed into attention unmaterialized"). On this model it
runs fine: `POST /load` succeeded and three streamed requests — pad 0 / 300 tok, pad
8000 / 300 tok, pad 0 / 900 tok — all returned coherent `merge_intervals` code with no
SSE error event (`tuning/kv-4bit-noskip-probe.json`,
`tuning/kv-4bit-noskip-probe2.json`, all `error: null`). The documented error is a
gemma-specific path, not a Qwen3.5-MoE one; it was not carried forward as a claim.

### Thinking

`tuning/thinking.py`, interleaved, streaming, `max_tokens 900`, n=3. Time to first
**content** token (TTFC) is measured separately from TTFT:

| Arm | TTFT | **TTFC** | content | reasoning | finish |
|---|---|---|---|---|---|
| `enable_thinking: true` | 57.1 ms | **null** | **0 ch** | 2397 ch | `length` ×3 |
| `enable_thinking: false` | 59.1 ms | 59.1 ms | 1095 ch | 0 | `stop` ×3 |

Escalated to `max_tokens 3000` (`thinking-probe-3000.json`): TTFT 92.2 ms, **TTFC null**,
**0 content chars**, **10583 reasoning chars**, `finish_reason: length`,
`elapsed_ms: 16696.9`. The model never leaves `reasoning_content` even with 3000 tokens
of budget. `thinking_budget_tokens` is a *floor*, not a cap, so it cannot be used to cut
this short — do not try.

So on this model **`enable_thinking: true` produces no answer at all** within any
sensible budget. This is the single highest-impact setting on the model and the reason
the final config beats the defaults by 14%.

### Context window

`tuning/ab.py`, interleaved n=5, native 262144 vs capped 32768:

| Prompt | native | 32768 |
|---|---|---|
| short (~47 tok) | 71.6 ms / 190.62 tps | 72.2 ms / 187.55 tps |
| `--context-pad 8000` | 164.0 ms / 160.43 tps | 164.1 ms / 159.45 tps |

Null in both cases, as expected. Kept native.

### Sampling and `force_sampling`

`tuning/ab.py`, interleaved n=5:

| Arm | TTFT | Decode |
|---|---|---|
| card temp 1.0 / top_p 0.95 / top_k 20 | 91.9 ms | 160.54 tps |
| coding temp 0.6 / top_p 0.95 / top_k 20 | 102.5 ms | 160.77 tps |

Throughput-neutral, as it must be — sampling happens on the logits and does not change
the forward pass. The coding sampler is **kept on the model-card recommendation**, not on
a throughput claim. It cannot be validated with `measure.py` at all: `measure.py` sends
`temperature` in every request payload and `force_sampling` is `false`, so the per-model
sampler is never actually exercised by the benchmark.

`force_sampling`, n=8 (`ab-force-sampling-n8.json`): off 80.8 ms / 173.21 tps, on
85.2 ms / 180.45 tps. Looks like +4.2% decode — **it is not a throughput effect.** The
only thing `force_sampling` changes for a `temperature: 0.0` request is that it overrides
the request's deterministic sampling with the model's `temp 0.6`, so the on-arm is
sampling and the off-arm is greedy, and greedy output hits repeated low-entropy tokens
that MTP drafts cheaply. Direct probe: two identical `temperature: 0.0` requests are
**identical** with `force_sampling: false` and **different** with `force_sampling: true`.
Recorded as "rejected — device of the measurement, not a real speedup; also makes
benchmark runs non-deterministic". Kept `false`.

### Levers that are not applicable on this model

- **MoE expert offload** — `GET /admin/api/models/{id}/moe-offload-fit?mtp_enabled=true`
  → `{"status":"resident","max_percent":null,"bytes":0}`. The model fits in RAM
  (40.5 GB of ~101 GB). Nothing to offload; not tuned. `moe_offload_allows_mtp: false`.
- **DFlash / SpecPrefill** — `dflash_compatible: true` but `dflash_draft_model` and
  `specprefill_draft_model` are both `null`, so both are no-ops. DFlash also returns
  HTTP 400 when combined with `mtp_enabled: true`. Splash would need a separate DFlash2
  draft repo; it is not downloaded and was not fetched. Not probed, recorded as no-op.
- **`activation_fp16_enabled`** — `activation_fp16_supported: false`. Left `false`,
  not probed. (On flint this knob produced a fake 26× speedup that was numerical
  corruption.)
- **`qwen35_oq_a8_*` (INT8-activation prefill)** — `qwen35_oq_a8_supported: false`, the
  kernels refuse to load on M4. Left `false`, not probed.

---

## Failure modes and methodology traps hit this pass

1. **Prefix cache masks all prefill tuning.** `measure.py` re-sends an identical prompt
   every run, so the server logs `Prefix cache restore ... cached=41001 suffix=7` and
   TTFT measures cache lookup. Any prefill knob (ANE) reads null. Defeated with
   `tuning/coldprefill.py` (random nonce per request).
2. **`auto_unloaded: true` does not reload.** `mtp_fixed_depth`, `qwen35_ane_prefill_enabled`
   and `turboquant_kv_enabled` all PUT back `requires_reload: true, auto_unloaded: true,
   auto_reloaded: false`. The model must be re-`POST`ed to `/load` and polled. `block.py`'s
   `apply_and_settle()` does this; doing it by hand and skipping the load pays a cold
   load on the next request, which fakes a ~2700 ms TTFT.
3. **The auto-unload is asynchronous.** `loaded` can still read `true` for a moment after
   the PUT. Loading too early races the teardown. `wait_unloaded()` exists for this.
4. **`ab.py` leaves its last patch applied.** After the context A/B,
   `max_context_window: 32768` was still on the model and the next 32k test died with
   `Prompt is too long: 41008 > 32768`. Always reset `max_context_window: null` after an
   `ab.py` run.
5. **One cold block can fake a whole verdict.** The short-prompt ANE head-to-head had a
   cold block-1 A (164 tps against ~183 everywhere else) and manufactured a +5.5% win.
   Always look at the per-sample list, not just the arm median.
6. **`GET /admin/api/models/{id}/settings` returns 405.** Read `.settings` off
   `GET /admin/api/models`.
7. **`GET /admin/api/models/{id}/model-info` returns 404** on this build; the working
   path is `/admin/api/hf/model-info`.
8. **`resident_size`, `native_context` and `path` are `null`** in the models list for this
   model. Resident size has to come from the `api/status.model_memory_used` delta.
9. **`coldprefill.py` first reported 4.7 tps** for a request the server itself timed at
   `142.7 tok/s` and `generation_duration 2.12s` for 300 tokens. Cause: the SSE stream is
   coalesced to **11 chunks for 300 tokens**, so chunk-counting under-reports decode by
   ~28×, and the elapsed span included the prefill. Fixed to read
   `generation_tokens_per_second` from the per-request `usage` block. Any harness that
   counts SSE chunks on this server will be wrong; use `usage`.
10. **`enable_thinking: null` is not off.** It emits reasoning chunks while `measure.py`
    reports `ttfc=None` and a plausible-looking TTFT. If you see `ttfc: null` with a
    normal `ttft_ms`, that is thinking, not speed.
11. **`~/.omlx/cache` grew to 47 GB** over this pass (from 19 GB), still far under the
    185 GB max. No coherence risk, but it is a different number than the brief's 19 GB.

---

## Final configuration

```json
{
  "enable_thinking": false,
  "mtp_enabled": true,
  "mtp_fixed_depth": 4,
  "mtp_adaptive_max_depth": null,
  "turboquant_kv_enabled": false,
  "turboquant_skip_last": true,
  "max_context_window": null,
  "qwen35_ane_prefill_enabled": false,
  "qwen35_ane_prefill_tail_padding_min_tokens": 0,
  "temperature": 0.6,
  "top_p": 0.95,
  "top_k": 20,
  "force_sampling": false
}
```

Everything else is left exactly as found (see `settings-start.json` /
`final-settings.json`; the live diff is zero — `settings-live.json`).

Applied once with a single PUT (`requires_reload: false, auto_unloaded: false`), then read
back and diffed against `final-settings.json` key-by-key: **0 differences.**
`enable_thinking` was re-read specifically and is `false` on the live server.

**Left applied. Defaults were not restored.**

### Quality check

`RUN` `tuning/quality.py` (now `TEMP=0.6`, `MAXTOK=700`, streaming) — 3 prompts, full
output text read (`quality.md`, `quality-raw.json`): 910 / 147 / 104 content chars, **0
reasoning chars in all three**, `finish_reason: stop` in all three. All three answers are
correct: `merge_intervals` sorts and merges with the adjacency case (`current[0] <=
last[1] + 1`), the `average` fix adds the empty-list guard, and the dict refactor collapses
to a list comprehension with `d[key] is not None`.

---

## Coordinator verification

Every headline claim was re-measured against the live server before this result was
recorded. What was checked and what it showed:

| Claim | Method | Coordinator result | Verdict |
|---|---|---|---|
| Whole-config +14.1% decode | `block.py`, n=10/arm, alternating | **+14.0%** (161.04 → 183.63 tps), −226 ms total, +3.2 ms TTFT | **confirmed** |
| `enable_thinking: null` is not off | tri-state stream, max_tokens 400 | `false` → 0 reasoning / 207 content; `null` → 1617 reasoning / **0 content**, `finish=length`; `true` → 1533 reasoning / 0 content | **confirmed** |
| ANE prefill is a null | `coldprefill.py`, PAD=8000, n=6/arm | off 17045 ms / 143.41 tps vs on 18206 ms / 134.69 tps — ANE *worse*, but drift-dominated (15.4 s → 20.1 s within one arm) | **confirmed (null)** |
| `force_sampling` win is an artifact | 3 identical temp-0 requests per arm | `false` → "The Midnight Bean" ×3; `true` → "The Midnight Roast" / "The Daily Grind" / "The Beanery" | **confirmed** |
| MTP depth 4 beats adaptive | 3 further paired runs + null test | +8.2%, −2.4% (swapped), +3.8%; null spread 1.8% | **not reproduced — null** |
| Output is not corrupted | streamed 400-token coding prompt, read the text | 1252 content chars, 0 reasoning, `finish=stop`, correct `merge_sorted_lists` with docstring and doctests | **clean** |

The one correction is the MTP depth claim, which the agent had already flagged as
edge-of-noise and which the coordinator's null test demotes to no effect. The
headline +14% stands, and it is honestly attributed to the thinking pin rather than
to tuning.

---

## Confidence

**High confidence (paired, repeated, effect >> noise):**
- thinking off beats thinking unset, +7.1% decode and "answers vs does not answer"
  (n=5 interleaved; whole-config n=10/arm shows +14.1%).
- KV quant costs decode (n=6 × 4 arms, stable ordering across two sweeps).
- Context window is a null (n=5 × 2 prompt lengths).
- ANE prefill is a null, including on a cache-defeated cold ~21.7k-token prefill (n=6/arm).
- Sampling rate is throughput-neutral (n=5).

**Medium/low confidence:**
- **MTP fixed depth 4 over adaptive is a null result.** The agent's two paired tests
  read +1.0% and +0.7%; the coordinator's three further runs read +8.2%, −2.4%
  (arms swapped) and +3.8%, and a null test with the *same* config in both arms
  produced a 1.8% spread. The effect is not separable from noise. Depth 4 is left
  applied because it never hurt and the cliff above depth 5 is real, but it is not
  a tuning win and must not be quoted as one.
- `force_sampling` "gain" is an artifact of the measurement harness (request
  `temperature: 0.0` being overridden), not a throughput effect.
- The whole-config +14.1% is dominated by `enable_thinking`. If you were to compare
  defaults-with-thinking-off against the final config the delta would be ~1%, which is
  what the MTP-depth and sampler rows independently say. The headline number is honest
  for "defaults as shipped vs final", not for "my tuning found 14%".
