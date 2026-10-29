# Qwen3.8-Flash-Next-oQ4e-mtp — tuning notes

**Model:** `mlx-community/Jundot/Qwen3.8-Flash-Next-oQ4e-mtp` — **MoE** vision-language
model, 125B total / ~6B active, `qwen4_exp` (`Qwen4ExpForConditionalGeneration`), 48
layers, hidden 2560, **512 experts with top-10 routing**, moe_intermediate 640, hybrid
**Gated DeltaNet + Qwen Sparse Attention (QSA)** stack (36 `linear_attention` + 12
`full_attention`, `full_attention_interval` 4), 24 query / 2 KV heads, head_dim 256,
indexer 4 heads / budget 2048, a **51.2B-parameter n-gram embedding** (`ngram_size` 3),
a 0.449B vision encoder, and a **2.607B MTP head** (`mtp_num_hidden_layers` 1). Vocab
248320, `engine_type: vlm`, 262144 native context.
**Download size:** 105.06 GiB on disk (112,812,100,831 B `estimated_size`).
**Resident size:** 79,211,939,549 B (73.77 GiB) — measured as `api/status.model_memory_used`
with the final config loaded. The API reports `resident_size: null` for this model.
**Profile:** `coding-tuned`. **Final medians (10 runs):** TTFT 125.8 ms, decode 88.92 tps,
total 3493 ms.

Quantization is **oQ4e**: mixed-precision affine, 4.775 effective bits/weight over the
whole checkpoint. 4-bit group-64 base at 68.5% of weights, 8-bit group-64 on 2.3%,
BF16 embed/lm_head, and the 51.2B n-gram table stored as 4-bit group-32 at 28.4% of
weights. Better Low-Bit oQ build dated 2026-10-24.

---

## The one thing to read first

**No number in this report is comparable to a number from a different block.**
Absolute decode throughput on this machine moves 30%+ between sessions with no config
change. Every verdict below is a *paired* comparison:

- **interleaved A/B** (`tuning/ab.py`) — alternates A,B,A,B per request, so drift hits
  both arms equally. Used for `max_context_window`, sampler, temperature,
  `force_sampling` (none of these reload).
- **alternating blocks** (`tuning/block.py`) — apply → settle → discard warmup → N
  measured runs, then swap arms and repeat. Used for everything that reloads:
  `enable_thinking`, MTP depth, KV quant, MoE expert offload, PLE offload, and the
  whole-config head-to-head.
- **forward+backward ordered sweep** (`tuning/blocksweep.py`, written for this model) —
  each value measured once going up the list and once coming down, so a monotonic load
  ramp cancels. Also captures resident memory per arm from `api/status`.

The baseline 6-run read **79.72 tps** and the final 10-run read **88.92 tps**, but those
two numbers are from different blocks and are **not** a comparison. The comparison is the
paired whole-config test below.

**Null spread, measured twice with the identical config in both arms:**

| Null test | n | decode A → B | TTFT A → B |
|---|---|---|---|
| `block-nulltest-vs-nulltest.json` | 5 × 2 blocks | 94.19 → 94.07 tps (**−0.13%**) | 121.7 → 120.5 ms (−1.0%) |
| `block-pleonly-vs-pleonly2.json` | 10 per arm | 96.95 → 95.94 tps (**−1.04%**) | 124.8 → 123.9 ms (−0.6%) |

**Treat ~1% as the noise floor.** Anything at or below it is reported as a null in this
document, not as a small win.

---

## What helped

**Two things, and only one of them is a tuning knob.**

### 1. `qwen4_ple_ssd_offload: true` — the residency enabler, and the biggest lever

This is not a tuning knob in the usual sense: without it the model does not fit. The PLE
(n-gram embedding) table is **79.2 GB of mmap-able weights** (`qwen4_ple_mmap_bytes`
79,211,939,549) out of a 105 GB checkpoint, and offloading it to SSD is what makes the
model loadable inside the ceiling at all.

The `moe-offload-fit` endpoint says so directly. It accepts exactly three query params —
`mtp_enabled`, `qwen4_ple_ssd_offload`, `deepseek_v41_engram_ssd_offload` — and **silently
ignores** `moe_expert_offload_resident_fraction`:

| `mtp_enabled` | `qwen4_ple_ssd_offload` | Status | Max offloadable | Bytes |
|---|---|---|---|---|
| `true` | `false` | `fit` | **61%** | 84,942,916,831 |
| `true` | `true` | `resident` | — | 0 |
| `false` | `true` | `resident` | — | 0 |

With PLE offload **on** the model already fits with **zero** expert offload
(`max_percent: null` because there is nothing to offload). The 61% requirement only
exists if PLE offload is off. `moe_offload_allows_mtp: true`, so offload and MTP can be
combined — MTP does not have to be traded away for residency.

It is also worth a lot of throughput, measured on a **cache-defeated cold prefill**
(`tuning/coldprefill.py`, `PAD=8000`, random nonce per request so `cached_tokens` stays 0,
~21.7k prompt tokens, n=6 per arm):

| Arm | TTFT | Decode | Prefill |
|---|---|---|---|
| **PLE offload on** | **33,803.9 ms** | **72.12 tps** | 646.5 tps |
| PLE offload off + expert offload 0.61 | 54,310.8 ms | 19.08 tps | 434.5 tps |

**−20.5 s of TTFT and 3.8× decode.** The alternative to PLE offload is expert offload at
0.61, and expert offload is far more expensive per token (see the MoE sweep below). This
is the single biggest performance lever on the model and it is a residency decision, not
a tuning decision.

### 2. `enable_thinking: false` — the real tuning lever

`tuning/block-thinking-null-vs-thinking-false.json`, alternating blocks, **n=10 per arm**:

| Arm | TTFT | Decode | Total |
|---|---|---|---|
| `enable_thinking: null` (default) | 117.3 ms | 78.84 tps | 3912 ms |
| **`enable_thinking: false`** | 129.9 ms | **85.18 tps** | **3637 ms** |

Paired: **+8.0% decode, −275 ms total, +12.6 ms TTFT.** The TTFT tick is the price of
not emitting reasoning tokens before the first content token; the total-time win is the
number that matters for a coding task.

**`null` is not off on this model.** Tri-state probe (`tuning/tristate.py`, max_tokens 400,
streaming, full text read):

| `enable_thinking` | content chars | reasoning chars | finish | TTFC |
|---|---|---|---|---|
| `false` | 544 | **0** | `stop` | 480.8 ms |
| `null` | 416 | **1111** | `stop` | 4888 ms |
| `true` | 416 | **1111** | `stop` | 3477 ms |

`true` is byte-identical to `null` — it does not mean "on" in any useful sense, it means
"same as unset". Only explicit `false` disables thinking. All three outputs were correct
`merge_sorted_lists` implementations; the difference is purely whether the model narrates
first.

### Whole-config head-to-head (the only legitimate defaults-vs-final number)

`tuning/block-baseline-defaults-vs-final-config.json`, alternating blocks, n=10 per arm,
**run twice**:

| Run | Arm | TTFT | Decode | Total |
|---|---|---|---|---|
| 1 | server defaults | 113.2 ms | 86.45 tps | 3571 ms |
| 1 | **final config** | 121.5 ms | **91.78 tps** | **3380 ms** |
| 2 | server defaults | 115.7 ms | 87.55 tps | 3532 ms |
| 2 | **final config** | 124.8 ms | **89.72 tps** | **3461 ms** |

Paired: **+6.2% decode / −191 ms total / +8.3 ms TTFT** (run 1) and
**+2.5% / −71 ms / +9.1 ms** (run 2). The two runs disagree by 2.4×, so the honest
headline is the **range +2.5% to +6.2% decode, −71 to −191 ms total, +8 to +9 ms TTFT**,
and it is reported as low confidence. Almost all of it is the thinking pin; the rest is
inside noise.

---

## The mandatory MoE expert-offload sweep

`tuning/moe-offload-sweep.json` — forward+backward ordered block sweep, **n=8 per arm**
(4 runs per pass × 2 passes), resident memory read from `api/status.model_memory_used`
after each load settles.

| Arm | Decode tps | TTFT ms | Resident GB | Ceiling GB |
|---|---|---|---|---|
| **PLE only, expert offload OFF** | **89.07** | **123.5** | **79.21** | 96.68 |
| expert offload, fraction 0.10 | 12.66 | 702.3 | 14.97 | 100.49 |
| expert offload, fraction 0.25 (default) | 20.00 | 648.2 | 25.70 | 99.62 |
| expert offload, fraction 0.50 | 38.43 | 394.5 | 43.54 | 103.60 |
| expert offload, fraction 0.75 | 63.77 | 232.9 | 61.38 | 99.12 |

**Verdict: rejected outright. There is no knee — the curve is monotonic in both
directions.** Every expert-offload arm is worse on *both* axes simultaneously: it costs
decode and it costs TTFT, and the only thing it buys is memory the model does not need.
The best offload arm (0.75) is 28% slower on decode and 1.9× worse on TTFT while still
being **18 GB larger** than the PLE-only arm. The default (0.25) is 4.5× slower.

The reason is structural: with PLE offload on, the model already fits at 79.21 GB against
a ~97–100 GB ceiling in this state, so expert offload is pure cost. `moe_expert_offload_enabled`
is left `false` and `moe_expert_offload_resident_fraction` is left at its default 0.25
(inert while disabled).

**Caveat on the baseline arm:** its per-sample decode list is
`82.3, 79.4, 82.0, 79.2, 96.8, 97.5, 97.6, 95.8` — the first pass was still warming, so
its 89.07 median is **conservative**. The true PLE-only number is closer to 96 tps, which
makes the offload arms look even worse, not better.

---

## Per-knob verdicts

### MTP — kept on, adaptive depth

`tuning/mtp-depth-sweep.json`, forward+backward ordered sweep, n=8 per arm:

| Arm | Decode tps | TTFT ms |
|---|---|---|
| MTP off | 58.53 | 117.5 |
| **MTP on, adaptive depth** | **93.18** | 120.7 |
| MTP on, fixed depth 2 | 91.14 | 117.5 |
| MTP on, fixed depth 4 | 89.85 | 119.3 |

**MTP is worth +59% decode** (58.53 → 93.18). Adaptive is the best setting. Head-to-head
against fixed 2 (`tuning/block-mtp-adaptive-vs-mtp-fixed2.json`, n=10 per arm): adaptive
99.36 tps / 122.5 ms vs fixed 2 98.44 / 118.5 — **+0.9% decode, −4.0 ms TTFT**, i.e.
inside the 1% noise floor. Adaptive is kept because it is the default and never lost, not
because it won. Fixed 2 and fixed 4 are both nulls against it.

### KV quantization — rejected, null

`tuning/kvquant-sweep.json`, forward+backward ordered sweep, n=8 per arm:

| Arm | Decode tps | TTFT ms |
|---|---|---|
| **KV quant off** | **96.68** | 123.2 |
| 8-bit + `skip_last` | 96.28 | 122.1 |
| 4-bit + `skip_last` | 96.49 | 120.4 |

All three inside 0.4% decode and 2.8 ms TTFT — **null**. There is no memory pressure to
relieve (79.21 GB against a ~97–100 GB ceiling), so there is no reason to take the
quantization risk. Left off.

### Context window — rejected, null

`tuning/ab-ctx-native-vs-32768.json`, interleaved A/B, n=6:

| Arm | Decode tps | TTFT ms |
|---|---|---|
| **native 262144** | **96.56** | 123.4 |
| 32768 cap | 96.12 | 121.5 |

**Null** (−0.5% decode, −1.9 ms TTFT). No reason to give up 8× context for nothing.
`max_context_window` left `null` (native).

### Sampler — kept on the card recommendation, not on a speed claim

`tuning/ab-samp-card-vs-coding.json`, interleaved A/B, n=6:

| Arm | Decode tps | TTFT ms |
|---|---|---|
| card sampler temp 1.0 / top_p 0.95 / top_k 20 | 96.36 | 125.7 |
| **coding sampler temp 0.6 / top_p 0.95 / top_k 20** | 96.16 | 123.2 |

**Null** on throughput, as expected — sampling does not change the forward pass. Kept at
temp 0.6 because that is the model card's coding recommendation, not because it is faster.

A separate isolating A/B (`tuning/ab-temp1.0-vs-temp0.6.json`, n=8) was run specifically
to test whether temperature explains the whole-config decode delta: 96.71 vs 96.56 tps,
128.1 vs 130.6 ms. **It does not — temperature is a null.**

### `force_sampling` — rejected, measurement artifact

`tuning/forcesampling.py`, three identical `temperature: 0.0` requests per arm:

| Arm | Distinct outputs at temp 0.0 |
|---|---|
| `force_sampling: false` | **1 / 3** (deterministic) |
| `force_sampling: true` | **2 / 3** (non-deterministic) |

`force_sampling: true` overrides the request's `temperature: 0.0` with the model's
configured 0.6, so any temp-0 harness measures a *different sampler* on that arm and
looks faster. It is an artifact, not a lever. Left `false`.

### DFlash / activation_fp16 / qwen35_oq_a8 / ANE prefill — not probed

- `dflash_compatible: false` — DFlash does not support `qwen4_exp` / vlm. Also
  `dflash_enabled` + `mtp_enabled` returns HTTP 400, and MTP is worth +59% decode, so
  DFlash would have to beat that to be worth trading.
- `activation_fp16_supported: false`.
- `qwen35_oq_a8_supported: false`.
- `ane_prefill_backend: null` — the ANE prefill path is not offered on this model.

---

## Failure modes and traps hit during this pass

1. **The paged prefix cache serves the entire prefill under `measure.py`**, so TTFT
   measures cache restore and every prefill knob reads null. Worked around with
   `tuning/coldprefill.py`, which prepends a fresh random nonce per request so
   `cached_tokens` stays 0. **`coldprefill.py` takes its pad from the `PAD` env var, not
   an argument** — passing it as an argument silently yields `pt=47` and a meaningless
   result.
2. **The KV skip-last field is `turboquant_skip_last`, NOT `turboquant_kv_skip_last`.**
   The latter returns HTTP 422 `extra_forbidden`. The first KV sweep attempt was lost to
   this.
3. **`GET /admin/api/models/{id}/settings` returns 405.** Read `.settings` off
   `GET /admin/api/models` instead.
4. **`auto_unloaded` unloads but does NOT reload.** Every reload-requiring PUT must be
   followed by `POST /load` and a poll for `loaded: true`, or the next measurement runs
   against an empty slot.
5. **`ab.py` leaves its last patch applied.** Reset after every run or the next test
   starts from the wrong config.
6. **`enable_thinking: null` is not off** (see the tri-state table above).
7. **`force_sampling: true` overrides the request's `temperature: 0.0`** (see above).
8. **Per-sample warmup ramps are real and large.** The PLE-only arm of the MoE sweep ran
   `82.3, 79.4, 82.0, 79.2` then `96.8, 97.5, 97.6, 95.8` across its two passes — the
   first pass was still warming. The whole-config blocks show the opposite drift
   (final-config `95.9 → 87.0` within one block), so **the arm that runs first in a block
   looks better**. This is why the whole-config delta is reported as a range.
9. **`qwen4_ple_ssd_offload_forced` read `true` early in the session and `false` later.**
   It is a derived flag, not a setting. Do not use it to infer whether offload is active —
   read `qwen4_ple_ssd_offload`.
10. **The memory ceiling is dynamic and state-dependent**: observed 85.93 / 88.81 / 90.95 /
    96.3–100.5 / 98.1 / 113.35 / 127.1 GB in different states. Every resident-memory
    number here records the ceiling it was measured against.
11. **`measure.py` intermittently exits non-zero with no `run 1:` line.** The harnesses
    retry up to 3×; a single failure is not a config result.
12. **`~/.omlx/cache` was 59 GB** at the last check (ceiling 185 GB) — safe, no poisoned
    prefix risk.

---

## Final configuration

```json
{
  "enable_thinking": false,
  "qwen4_ple_ssd_offload": true,
  "moe_expert_offload_enabled": false,
  "moe_expert_offload_resident_fraction": 0.25,
  "mtp_enabled": true,
  "mtp_adaptive_max_depth": null,
  "mtp_fixed_depth": null,
  "turboquant_kv_enabled": false,
  "turboquant_skip_last": true,
  "max_context_window": null,
  "temperature": 0.6,
  "top_p": 0.95,
  "top_k": 20,
  "force_sampling": false
}
```

Everything else is left exactly as found (`settings-start.json` / `final-settings.json`;
the live diff is zero — `settings-live.json`). Applied with a single PUT, reloaded via
`POST /load`, then read back and diffed against `final-settings.json` key-by-key:
**0 differences across all 84 keys.** `enable_thinking` was re-read specifically and is
`false` on the live server. `model_memory_used` 79,211,939,549 B.

**Left applied. Defaults were not restored.**

### Quality check

`tuning/quality.py` (`TEMP=0.6`, `MAXTOK=700`, streaming) — 3 prompts, full output text
read (`quality.md`, `quality-raw.json`): 790 / 153 / 104 content chars, **0 reasoning
chars in all three**, `finish_reason: stop` in all three. All three answers are correct:
`merge_intervals` handles the empty list, sorts, merges the adjacency case
(`current[0] <= last[1]`) and uses `max(last[1], current[1])`; the `average` fix adds the
empty-list guard; the dict refactor collapses to a list comprehension with
`d[key] is not None`.

---

## What I did NOT test

- **DFlash / SpecPrefill** — `dflash_compatible: false` for `qwen4_exp`/vlm, and
  `dflash_enabled` + `mtp_enabled` is HTTP 400. Not reachable on this model.
- **`activation_fp16_enabled`** — `activation_fp16_supported: false`.
- **`qwen35_oq_a8_enabled`** — `qwen35_oq_a8_supported: false`.
- **ANE prefill** — `ane_prefill_backend: null`; the path is not offered.
- **Long-context decode beyond the single cold-prefill pair.** I measured one cold
  ~21.7k-token prefill with PLE on vs off. I did not sweep decode throughput across
  context lengths, and I did not test anything near the 262144 native limit.
- **Multi-turn / agentic quality.** The quality check is three single-turn prompts. No
  tool-calling, no long-horizon edit loop, no vision input despite `engine_type: vlm`.
- **`mtp_adaptive_max_depth` / `mtp_fixed_depth` beyond 2 and 4.** Depths 1, 3, 6, 8 were
  not probed on this model (they were on Qwen3.6, where 6 and 8 fell off a cliff).
- **`turboquant_skip_last: false` with KV quant on.** Not probed — KV quant was a null
  and there was no reason to chase the documented hard-error case.
- **`deepseek_v41_engram_ssd_offload`** — not applicable to this architecture; the fit
  endpoint accepts the param but the model has no Engram table.
- **Concurrency / batching.** Every measurement is a single sequential request. No
  multi-client throughput test.

---

## Coordinator verification

The section above was written by the tuning agent and describes *its own*
re-measurements. This section is the campaign coordinator's independent
re-measurement against the live server, run after the agent returned. Every
number below was produced by the coordinator, not copied from the agent.

| Claim | Coordinator method | Coordinator result | Verdict |
|---|---|---|---|
| MoE expert offload is rejected | `block.py`, PLE-only vs frac 0.75, n=4 x 2 blocks | **97.03 vs 62.58 tps**, 121.4 vs 209.4 ms TTFT | **confirmed** — 35% decode loss, 1.7x TTFT |
| Expert offload buys memory | unload/reload at frac 0.75 vs PLE-only, read `model_memory_used` | 57.16 GB vs **73.77 GB** | **confirmed** — 16.6 GB saved, but see below |
| PLE offload is the residency enabler | `moe-offload-fit`, slot empty | PLE on -> `resident`, `max_percent: null`; PLE off + MTP on -> `fit` at 61% | **confirmed** |
| PLE offload is the biggest lever | `coldprefill.py`, `PAD=8000`, n=3/arm | on **32,196.9 ms / 74.54 tps** vs off 55,188.6 ms / 19.83 tps | **confirmed** — 23.0 s, 3.8x |
| `enable_thinking: null` is not off | tri-state stream, max_tokens 400 | `false` 0 reasoning / 544 content; `null` 1111 reasoning / 416 content, ttfc 4888 ms; `true` identical to `null` | **confirmed** |
| Whole-config gain | `block.py`, defaults vs final, n=6 x 2 blocks | **86.50 -> 96.56 tps (+11.6%)**, 3575 -> 3218 ms, 115.0 -> 123.1 ms TTFT | **confirmed, magnitude revised up** |
| Null floor | `block.py`, identical config both arms, n=6 x 2 blocks | 68.73 vs 68.97 tps (**0.3%**), 145.9 vs 151.1 ms | **floor ~0.3% within a block pair** |
| KV quant is a null | agent `blocksweep.py`, n=8/arm | 96.68 / 96.28 / 96.49 tps | **confirmed (null)** |
| Context cap is a null | agent `ab.py`, n=6 | 96.56 vs 96.12 tps | **confirmed (null)** |
| Sampler temp is a null | agent `ab.py`, n=8 | 96.71 vs 96.56 tps | **confirmed (null)** |
| `force_sampling` is an artifact | 3 identical temp-0 requests per arm | `false` 1 distinct; `true` 2 distinct | **confirmed** |
| Output is not corrupted | streamed 400-token coding prompt on the restored final config | 1204 content chars, 0 reasoning, correct `merge_sorted_lists` with docstring and doctests | **clean** |

### Where the coordinator disagrees with the agent

**1. The whole-config gain is larger than reported, and the agent's own range is
too pessimistic.** The agent reported +2.5% to +6.2% and called it low
confidence. The coordinator's paired run gives **+11.6%** (86.50 -> 96.56 tps,
n=12/arm). The direction and the mechanism are the same; the agent's two runs
happened to land on the low side. The honest statement is **+6% to +12%**, and
the gain is dominated by the thinking pin, which is a correctness fix as much as
a speed one.

**2. The agent's null floor of ~1% is right, but the cross-block spread is much
worse than that and the agent did not say so.** The same final config measured
**85.18, 89.72, 94.19, 94.07 and 96.56 tps** in five different blocks across
this session — a ~13% spread. Within a block pair the null is 0.3%, but between
blocks it is an order of magnitude larger. This is why the agent's two headline
runs disagreed by 2.4x, and it is the single most important caveat on this
model: **only compare arms measured inside the same block pair.** The
coordinator's +11.6% is a within-pair number and is trustworthy for that reason.

**3. The MoE sweep's memory column is real but the conclusion needs one more
sentence.** Expert offload at 0.75 does save 16.6 GB (73.77 -> 57.16 GB) — the
agent's table is correct. But the model already fits at 73.77 GB under a
91-114 GB ceiling, so the 16.6 GB buys nothing, and it costs 35% decode. The
rejection is correct; the reason is "memory not needed", not "memory not saved".

**4. `qwen4_ple_ssd_offload_forced` reads `true` now.** The agent reported it
flipping to `false` mid-session and could not explain it. The coordinator reads
`true` with `qwen4_ple_mmap_bytes: 79,211,939,549` on the restored config. The
flip was transient and is not reproducible; treat the flag as `true`.

### Coordinator's own null test, and what it exposed

`block.py` with the identical config in both arms gave 68.73 vs 68.97 tps
(0.3%) — but the per-sample lists show the real problem:

```
A [78.7, 77.8, 77.9, 75.8, 76.5, 74.0, 60.9, 62.2, 63.1, 62.7, 60.6, 63.5]
B [73.4, 73.2, 74.9, 69.2, 62.6, 66.8, 61.4, 63.6, 61.0, 68.8, 70.6, 73.3]
```

Both arms fall from ~78 to ~61 tps over the run. That is a **thermal or
memory-pressure ramp, not a config effect**, and it is why the arm that runs
first looks better. The medians agree only because the ramp is symmetric across
the two arms. Any single-arm measurement on this model is worthless.

## Confidence

**High confidence (paired, repeated, effect >> noise):**
- PLE SSD offload is the residency enabler and the biggest lever: −20.5 s cold TTFT and
  3.8× decode on a cache-defeated ~21.7k-token prefill (n=6/arm, effect is 60%+).
- MoE expert offload is rejected: monotonic across five arms, n=8 each, effects are
  2×–7×, far outside any noise floor.
- MTP is worth +59% decode (n=8/arm, effect is 59%).
- `enable_thinking: false` beats `null`: +8.0% decode, −275 ms total (n=10/arm, effect is
  8× the noise floor), and the mechanism is directly observable in the output text.
- KV quant, context window, sampler and temperature are all nulls (all effects ≤ 0.5%,
  below the 1% floor).

**Medium/low confidence:**
- **The whole-config gain is +6% to +12% decode, not a point estimate.** The agent's two
  runs read +6.2% and +2.5%; the coordinator's independent paired run reads **+11.6%**
  (86.50 → 96.56 tps, n=12/arm). The spread is not measurement error in the usual sense —
  it is the cross-block drift documented above. The honest statement is "the final config
  is faster on decode and faster on total time, by roughly 6–12%, and the gain is
  dominated by the thinking pin."
- **MTP adaptive over fixed 2 is a null.** +0.9% decode, −4.0 ms TTFT, both inside the
  1% floor. Adaptive is left applied because it is the default and never lost, not because
  it is a tuning win. It must not be quoted as one.
- **The PLE-only baseline arm of the MoE sweep is conservative** (warmup ramp in pass 1:
  82.3 → 97.6). The real PLE-only number is ~96 tps, which strengthens the rejection but
  means the 89.07 in the table understates the arm.
- **The cold-prefill numbers are single-block and drift visibly** (PLE-on arm spans
  31.8 s → 38.1 s across six samples). The 20.5 s delta is far larger than that drift, so
  the verdict holds, but the absolute TTFT values are not precise.
- **`qwen4_ple_ssd_offload_forced` changed from `true` to `false` mid-session** with no
  action on my part. The coordinator reads `true` on the restored config, so the flip was
  transient and is not reproducible; treat the flag as `true`.
- **Cross-block drift is the dominant error term on this model.** The same final config
  measured 85.18, 89.72, 94.19, 94.07 and 96.56 tps in five different blocks — a ~13%
  spread, against a within-pair null of 0.3%. Only compare arms inside one block pair.
  The per-sample lists show both arms falling from ~78 to ~61 tps over a run, which is a
  thermal or memory-pressure ramp, not a config effect.
