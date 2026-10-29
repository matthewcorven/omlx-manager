# Tuning log — Qwen3.6-35B-A3B-oQ8e-mtp

Chronological. Every measurement is labelled with its method and `n`. Nothing here is a
cross-block comparison.

---

## 0. Setup

- Read `AGENTS.md`, `.github/skills/omlx-model-tuning/SKILL.md`,
  `.github/skills/omlx-model-settings/SKILL.md`, the gemma-4-26B `final.json` / `NOTES.md`,
  and the five harnesses from `results/gemma-4-31B-it-oQ4e-mtp/tuning/`.
- Verified server: v0.7.3rc1 at `http://127.0.0.1:8001`, `ok`, 9 models discovered.
- Benchmark queue: `GET /admin/api/bench/accuracy/queue/status` → `running: false`.
- `du -sh ~/.omlx/cache` → **19 GB** of 185 GB max. Safe. (Ended the pass at 47 GB.)
- 299 Gi free disk.
- Captured `settings-start.json` from `GET /admin/api/models` → `.settings`
  (`GET .../settings` returns 405 on this build).
- Copied the five harnesses into `tuning/` and `sed`'d `gemma-4-31B-it-oQ4e-mtp` →
  `Qwen3.6-35B-A3B-oQ8e-mtp`. `sweep.py` has no `MODEL` constant (it imports from
  `block.py`).

### Model facts confirmed from disk, not assumed

- `config.json`: `qwen3_5_moe_text`, 40 layers, hidden 2048, 256 experts top-8,
  `moe_intermediate_size` 512, vocab 248320, `max_position_embeddings` 262144,
  **`mtp_num_hidden_layers` 1**, `tie_word_embeddings` false, 16 q heads / 2 kv heads,
  head_dim 256.
- `layer_types`: **30 `linear_attention` + 10 `full_attention`**, `full_attention_interval` 4
  → the hybrid Gated DeltaNet + Gated Attention stack.
- MTP head is *inside* the 8 shards: 42 `language_model.mtp.*` keys in
  `model.safetensors.index.json`. There is no separate `model-mtp.safetensors` (unlike the
  gemmas).
- `oq_imatrix_report.json`: oQ8e, 8-bit affine group 64, calibrated on
  `oqe_code_multilingual` (128 samples × 512), 523 entries applied, expert coverage
  `active_ratio` 1.0 / `zero_count_experts` 0.
- `generation_config.json`: temp 1.0 / top_p 0.95 / top_k 20.
- 36 GB on disk, `estimated_size` 40535237244.

### Loaded the model

`POST /admin/api/models/Qwen3.6-35B-A3B-oQ8e-mtp/load` → 17 s.
`api/status.model_memory_used` went to 65.92 GB of 89.06 GB max (gemma-4-26B 28.17 +
Qwen 37.75). `resident_size`, `native_context` and `path` all return `null` in the models
list for this model — resident size has to be taken from the status delta.

---

## 1. Smoke test

First run on defaults came back `ttfc=None, reasoning=4` — thinking was live despite
`enable_thinking: null`. Put `enable_thinking: false` →
`requires_reload: false, auto_unloaded: false` (no reload). Re-smoke:
`ttft=197.4 ms, ttfc=197.4 ms, reasoning=0`.

Coherence with a real prompt: returned `string[::-1]`, 0 reasoning chars, `finish: stop`.

---

## 2. Baseline

`tuning/runs.py ../baseline.json 3 300` — one discarded warmup, then 3 measured runs.
`ttft 72.4 ms, decode 182.37 tps, total 1714.6 ms, ct 300, reasoning 0`.

`runs.py` resolves relative output paths against `REPO` (the repo root), so the file
landed in the repo parent and had to be moved into the results dir. Same trap hit again
on `final-runs.json` later.

---

## 3. Thinking — rejected, and it is the whole story

Wrote `tuning/thinking.py`: interleaved A/B, streaming, `max_tokens 900`, measures **TTFC**
(time to first *content* token) separately from TTFT.

| Arm | TTFT | TTFC | content | reasoning | finish |
|---|---|---|---|---|---|
| `enable_thinking: true` | 57.1 ms | **null** | **0 ch** | 2397 ch | `length` ×3 |
| `enable_thinking: false` | 59.1 ms | 59.1 ms | 1095 ch | 0 | `stop` ×3 |

Escalated to `max_tokens 3000` (`thinking-probe-3000.json`): TTFT 92.2 ms, TTFC **null**,
content **0 ch**, reasoning **10583 ch**, `finish: length`, 16696.9 ms elapsed. It never
leaves the reasoning channel.

`thinking_budget_tokens` is a floor, not a cap — not usable as a workaround. Not tried
as one.

**Dead end worth recording:** `enable_thinking: null` is not "off". A plain 300-token
`measure.py` request with `null` reports `ttfc=None, reasoning=10`. Confirmed the
throughput consequence later in §3b.

### 3b. Isolating the thinking-null effect (paired)

`ab.py`, interleaved n=5, with `mtp_fixed_depth: 4` and the coding sampler held constant
in both arms so only `enable_thinking` varies:

| Arm | TTFT | Decode |
|---|---|---|
| `enable_thinking: null` | 76.3 ms | 171.72 tps |
| `enable_thinking: false` | 76.9 ms | **183.97 tps** |

**+7.1% decode from the pin alone.** This is what the whole-config delta is made of.

---

## 4. MTP depth

`PUT mtp_fixed_depth` → `requires_reload: true, auto_unloaded: true, auto_reloaded: false`.
So this is a `block.py`/`sweep.py` knob, and the model must be re-loaded by hand after
each PUT.

`tuning/sweep.py 3 mtp-sweep.json` (forward then backward, n=6 per value):

| Variant | TTFT | Decode |
|---|---|---|
| adaptive | 73.2 ms | 181.48 |
| fixed 1 | 69.8 | 141.01 |
| fixed 2 | 70.9 | 176.28 |
| fixed 3 | 73.7 | 182.81 |
| **fixed 4** | 73.2 | **183.13** |
| fixed 6 | 91.2 | 163.55 |
| fixed 8 | 108.5 | 123.12 |

A clear plateau at 3–4 and a cliff past 5. `mtp_num_hidden_layers` is 1 here (gemmas: 4),
which is why the peak is a plateau. Server log confirms the mechanism:
`accept=217/249 (87.1%) depth[d1=67/73,d2=60/67,d3=49/60,d4=41/49]`.

Head-to-head, `block-mtp-adaptive-vs-mtp-fixed4.json`, alternating blocks n=10/arm:
**fixed 4 182.96 tps / 72.9 ms vs adaptive 181.19 tps / 73.6 ms** (+1.0%, better on both).

Repeated later with thinking off in both arms (`block-adaptive-recheck-vs-fixed4-recheck.json`,
n=10/arm): **183.45 / 77.2 ms vs 182.14 / 76.0 ms** (+0.7%, decode better, TTFT 1.2 ms worse).

**+0.7% to +1.0% is the honest size of this win — edge of noise.** Kept, but not
headlined.

---

## 5. KV quant

First 3-arm sweep (`kv-sweep.json`, n=6): off 73.5 / 185.45; 8-bit+skip 73.5 / 185.62;
4-bit+skip 74.1 / 176.32.

The playbook says `turboquant_skip_last: false` is a hard runtime error under MTP. Probed
it rather than assuming: the PUT succeeded, the model loaded, and three streamed requests
(pad 0 / 300 tok, pad 8000 / 300 tok, pad 0 / 900 tok) all produced coherent
`merge_intervals` code with **no SSE error** (`kv-4bit-noskip-probe.json`,
`kv-4bit-noskip-probe2.json`, `error: null` on all three). **The documented failure mode
does not reproduce on this model.** Recorded as "did not reproduce", not as the gemma text.

So re-ran as a full 4-arm sweep (`kv-sweep-4arm.json`, n=6):

| Arm | TTFT | Decode |
|---|---|---|
| **off** | 71.4 ms | **190.96** |
| 8-bit + skip | 74.6 | 185.81 |
| 4-bit + skip | 72.7 | 176.84 |
| 4-bit no-skip | 72.8 | 177.69 |

Off wins on both axes. No memory argument: 40.5 GB resident against a ~101 GB ceiling.
Rejected.

---

## 6. Context window

`ab.py`, interleaved n=5. Short prompt: native 71.6 / 190.62 vs 32768 72.2 / 187.55.
With `PAD=8000`: native 164.0 / 160.43 vs 32768 164.1 / 159.45. **Null both times**, as
expected. Kept native.

**Trap:** `ab.py` leaves its last patch applied, so `max_context_window: 32768` stayed on
the model. The later 32k ANE test then died with
`Prompt is too long: 41008 > 32768 maximum context length`. Reset to `null` after every
`ab.py` run.

---

## 7. ANE prefill — the model-specific lever, and it is a null

`PUT qwen35_ane_prefill_enabled` → `requires_reload: true, auto_unloaded: true` → block
harness.

The path is genuinely active. Server log at load:
`Warmed 142 ANE procedures in 0.1s`, `Eagerly compiled 41 MLP and 30 GDN procedures into 2
instance-pinned ANE programs (sequence_length=2048)`, `Capped ANE GDN output rows from
requested 0.500 to 0.333`.

- `block.py` short prompt, n=10/arm: off 74.0 / 173.79, on 73.2 / 183.41 → **looked like a
  +5.5% win. It is not.** Per-sample inspection shows block-1 arm A at 164.2, 164.8, 163.6,
  164.7, 166.6 tps while everything else — including block-2 arm A — sits at 181–184. One
  cold block landed entirely in one arm. Discarded as a drift artifact.
- `sweep.py 3 ane-sweep.json` (off / on-tail0 / on-tail1024, n=6): 75.4 / 176.74,
  75.2 / 179.52, 75.7 / 177.66 → **null**.
- `PAD=8000 block.py` n=8/arm: off 163.8 / 167.38 vs on 161.7 / 167.66 → **null**.
- `PAD=32000 block.py` n=6/arm: off 475.3 / 140.78 vs on 481.4 / 140.45 → **null**.
- `qwen35_ane_prefill_tail_padding_min_tokens`: 2048 → HTTP 400
  `ANE tail padding threshold must be zero or less than the ANE prompt block`. 1024
  accepted, and included in the sweep above to bring the short prompt onto the ANE path.

### 7b. The prefix cache was faking every prefill measurement

Server log for a `PAD=32000` run:
`Prefix cache restore ... cached=41001 suffix=7 blocks=11`. **The entire prefill is served
from cache**, so `measure.py`'s TTFT is measuring a cache lookup, and *any* prefill-path
knob will read null under it. This is why the four tests above are not sufficient on their
own.

Wrote `tuning/coldprefill.py`: prepends a fresh random nonce to every request so the
prefix cache always misses.

**First version was wrong.** It reported `decode=4.7 tps` for a request the server itself
timed at `142.7 tok/s` / `generation_duration 2.12 s` for 300 tokens. Two bugs:
(1) this server coalesces the SSE stream — **11 chunks for 300 tokens** — so chunk-counting
under-reports decode by ~28×; (2) the elapsed span still contained the 16 s prefill.
Fixed to read `generation_tokens_per_second` and `time_to_first_token` straight out of the
per-request `usage` block. Also noted `PAD=8000` in `coldprefill.py` produces ~21.7k prompt
tokens, not 8000 (nonce sizing overshoots) — the numbers are labelled by real prompt token
count, not by the requested pad.

Cold result, `coldprefill-ane-off-cold8k-vs-ane-on-cold8k.json`, alternating blocks
n=6/arm, ~21.7k prompt tokens, `cached_tokens: 0`, prefill ~1310 tok/s, TTFT ~16.7 s:

| Arm | TTFT | Decode |
|---|---|---|
| ANE off | **16673.6 ms** | 146.87 tps |
| ANE on | 16741.7 ms | 142.75 tps |

**ANE prefill is 0.4% worse — a confirmed null, even when prefill genuinely dominates.**
Rejected, left `false` as found.

---

## 8. Sampling and force_sampling

`ab.py`, interleaved n=5:

| Arm | TTFT | Decode |
|---|---|---|
| card temp 1.0 / top_p 0.95 / top_k 20 | 91.9 ms | 160.54 tps |
| coding temp 0.6 / top_p 0.95 / top_k 20 | 102.5 ms | 160.77 tps |

Throughput-neutral, as it must be. Kept the coding sampler on the **model card's
recommendation**, not on a speed claim. Note the harness cannot validate it at all:
`measure.py` sends its own `temperature` in every payload and `force_sampling` is `false`,
so the per-model sampler is never exercised.

`force_sampling`, n=8 (`ab-force-sampling-n8.json`): off 80.8 / 173.21, on 85.2 / 180.45.
Looks like +4.2% decode. **It is an artifact.** The only thing `force_sampling` does to a
`temperature: 0.0` request is override it with the model's 0.6, so the on-arm samples
(less repetition, better MTP acceptance) and the off-arm is greedy. Direct probe: two
identical `temperature: 0.0` requests are **identical** with `force_sampling: false` and
**different** with `true`. Rejected — device of the measurement, and it makes benchmark
runs non-deterministic.

---

## 9. Whole-config head-to-head

`block.py`, alternating blocks, n=5 × 2 blocks = **n=10 per arm**. This is the only
legitimate defaults-vs-final comparison and the number quoted in `final.json`.

| Arm | TTFT | Decode | Total |
|---|---|---|---|
| server defaults (adaptive MTP, card sampler, thinking `null`) | 74.2 ms | 161.22 tps | 1929 ms |
| **final config** (depth 4, temp 0.6, thinking `false`) | 77.4 ms | **183.89 tps** | **1704 ms** |

**+14.1% decode, −225 ms total, +3.2 ms TTFT.** Almost all of it is `enable_thinking`
(§3b: +7.1% on its own); the MTP depth and sampler contributions are ~1% and ~0%.

---

## 10. Apply the final config and verify

Single PUT of the changed keys only (`temperature: 0.6`, `enable_thinking: false`,
`mtp_fixed_depth: 4`) → `requires_reload: false, auto_unloaded: false`. No reload.

Read back `.settings` from `GET /admin/api/models` into `settings-live.json` and diffed
key-by-key against `final-settings.json`.

- First diff: **1 difference** — `turboquant_kv_bits` intended 4.0 / live 8.0. That was my
  error, not a failed PUT: I had seeded `final-settings.json` from the *gemma* settings and
  it carried the gemma's `4.0`. This model's start value is `8.0`. Corrected the intended
  file, not the server.
- Second diff: **0 differences.** `enable_thinking` re-read specifically: `false`.

(The brief warns that `enable_thinking` has reverted from `false` to `true` on its own after
a verified apply on another model. Re-checked at the very end of the pass, after all
subsequent PUTs: still `false`.)

Warmup, then `runs.py ../final-runs.json 5 300` → `final-runs.json`:
`ttft 76.7 ms, decode 183.72 tps, total 1703.5 ms, reasoning 0` on all 5.

---

## 11. Quality check

`tuning/quality.py` with `TEMP=0.6 MAXTOK=700`, streamed, 3 prompts, full text read:

| Prompt | content | reasoning | finish |
|---|---|---|---|
| pure-function | 910 ch | 0 | stop |
| bug-fix | 147 ch | 0 | stop |
| refactor | 104 ch | 0 | stop |

All correct — see `quality.md` / `quality-raw.json`. Empty `reasoning_content` on all three
is the direct proof that the thinking pin is actually in force.

---

## 12. Left applied

Final settings are live on the server. Defaults were **not** restored. No `git add`, no
`git commit`.
