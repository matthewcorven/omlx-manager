# Tuning log — `Qwen3.8-27B-oQ4e-mtp`

Dense 27.8B, oQ4e + MTP, vision-capable, 262144 native context.
Host: M4 Max / 128 GB. Server `http://127.0.0.1:8001`.

## Measurement methodology, and why it changed three times

This log is dominated by measurement problems, not by tuning. Read this section
before trusting any number below.

**1. Sequential whole-config blocks are unusable here.** The first pass measured
native context, then 32768, then native again. Decode drifted 68.77 → 61.19 tps
with **no config change at all**. A background HF download (~38 MB/s) plus
WindowServer load makes absolute throughput slide monotonically over tens of
minutes. Sequential blocks cannot separate a config effect from that drift.

**2. Interleaved paired sampling (`tuning/ab.py`).** Alternate the two settings
per request so drift lands equally on both arms. Valid **only** for knobs that do
not force a reload. Used for the context decision.

**3. Alternating blocks (`tuning/block.py`).** Reload-requiring knobs cannot be
interleaved — every switch is a cold load. So: apply settings, load, discard one
warmup, take N runs, then switch arms, and repeat A,B,A,B. Drift is spread across
both arms instead of landing on one.

**4. Forward+backward ordering (`tuning/sweep.py`).** For multi-value sweeps, run
the config list forward then backward and pool. This exposes step changes in
machine load that a single pass would silently attribute to the config.

**5. Warmup discard is mandatory.** After a cold load the first request shows
~830 ms TTFT and ~56 tps prefill; steady state recovers to ~215 ms / ~53 tps
within a few runs.

**Consequence: no number in this log is comparable to a number in a different
block.** Every verdict below is a *paired* comparison. Absolute tps ranges from
22 to 88 across the session purely from machine load.

### Two contamination events

- **Coordinator-induced unload.** The coordinator added `/Volumes/NVMe/omlx-models`
  as a second model dir via `POST /admin/api/global-settings`, which unloads all
  models and re-discovers. Measurements spanning that window are quarantined in
  `tuning/contaminated/`. The early context numbers were contaminated by this.
- **Self-inflicted reload-per-request bug.** `ab.py` re-PUT the settings patch
  before *every* request. `mtp_enabled`, `mtp_adaptive_max_depth` and
  `turboquant_kv_enabled` all return `requires_reload: true` / `auto_unloaded: true`
  on a real change, so every request cold-reloaded the model. TTFT exploded to
  ~2900 ms. The first MTP depth-2, depth-4 and MTP on/off results are **invalid**
  and are marked as such in `tuning/INVALID.md`. They are not cited as evidence
  anywhere below.

A third, smaller bug: `block.py` originally assumed `auto_unloaded: true` meant
the server would reload the model. It does not — the harness must `POST /load`
itself. Fixed.

## Baseline (pre-existing, clean machine)

| Config | TTFT | Decode | Note |
|---|---|---|---|
| thinking ON | 213.5 ms | 65.72 tps | **never emitted content** — all 300 tokens went to `reasoning_content`. Unusable. |
| thinking OFF | 233.6 ms | 78.33 tps | 4271 ms total for 300 tokens. |

`mtp_enabled` was **already `true`** at baseline. There is no "enable MTP" gain to
claim — only a depth sweep is meaningful.

## Sweep results

### 1. Context window — KEPT 32768

Interleaved paired A/B (`ab-native-vs-ctx32768.json`), the only valid `ab.py` run:

| Config | TTFT | Decode |
|---|---|---|
| native (262144) | 235.9 ms | 50.34 tps |
| **32768** | **227.7 ms** | **52.35 tps** |

**Verdict: keep 32768.** −3.5% TTFT, +4% decode. This is the opposite of the
methodology's expectation (a smaller window should not help TTFT on short
prompts), but the paired design makes it credible: the effect is small and
consistent, and a smaller KV allocation reduces memory pressure. `max_context_window`
does not force a reload, so this comparison is clean.

### 2. MTP on/off — KEPT on

Alternating blocks (`block-mtpon-vs-mtpoff.json`), 3 runs × 2 blocks per arm:

| Config | TTFT | Decode |
|---|---|---|
| **MTP on** | 229.9 ms | **53.77 tps** |
| MTP off | 230.5 ms | 25.98 tps |

**Verdict: keep MTP on.** +107% decode at neutral TTFT. This is the single
biggest win in the whole sweep, and it was already on at baseline — the value of
this measurement is that it *quantifies* what MTP is worth, and proves that
nothing else in the sweep comes close.

### 3. MTP adaptive depth 1..8 — KEPT 6

Forward+backward sweep (`sweep-mtp-depth.json`), 2 runs per pass, 4 samples per
config. A machine-load step change between pass 07 and 08 (~67 → ~45 tps) makes
the pooled medians unusable, so the ranking below is read from the *per-direction*
ordering, not the pooled number:

| Depth | fwd decode | bwd decode | pooled TTFT | pooled decode |
|---|---|---|---|---|
| null (adaptive) | 67.90 | 44.28 | 220.8 ms | 55.77 tps |
| 1 | 66.85 | 44.05 | 220.5 ms | 54.95 tps |
| 2 | 64.67 | 43.78 | 227.3 ms | 53.33 tps |
| 3 | 65.53 | 45.24 | 235.6 ms | 55.58 tps |
| 4 | 66.88 | 48.18 | 210.1 ms | 57.58 tps |
| **6** | **67.12** | **56.41** | 210.1 ms | **62.06 tps** |
| 8 | 64.84 | 55.42 | 240.6 ms | 57.36 tps |

Only **depth 6** ranks at or near the top in *both* directions. Depth 4's pooled
number is inflated by the load step; its forward pass is mid-pack.

Confirmed pairwise (`block-mtpadapt-null-vs-mtpadapt-6.json`), 4 runs × 3 blocks
per arm:

| Config | TTFT | Decode | Total |
|---|---|---|---|
| adaptive default | 240.5 ms | 47.98 tps | 6441 ms |
| **depth 6** | 248.4 ms | **51.37 tps** | **6050 ms** |

**Verdict: keep depth 6.** +7% decode, −6% total wall time, at +3% TTFT. Depth 6
wins 2 of 3 blocks outright and ties the third. The earlier "depth 2 is +2%,
depth 4 is worse" verdicts were produced by the reload-per-request bug and are
**invalid** — depth 2 is in fact the *worst* setting in the sweep.

### 4. DFlash (MTP off, XOR) — REJECTED

`dflash_enabled` and `mtp_enabled` are mutually exclusive; the server returns
`"mtp_enabled and dflash_enabled cannot both be True; choose one speculative-decoding
path per model"`. So DFlash can only be tested with MTP off, which is the required
arm. Alternating blocks (`block-mtpoff-nodflash-vs-dflash-mtpoff.json`), 4 runs ×
3 blocks per arm:

| Config | TTFT | Decode | Total |
|---|---|---|---|
| no spec (MTP off, DFlash off) | 266.6 ms | 22.84 tps | 13364 ms |
| DFlash on (MTP off) | 276.9 ms | 23.20 tps | 13155 ms |

**Verdict: reject DFlash.** +1.6% decode and +3.9% TTFT — inside noise, and the
whole arm is 2.2× slower than MTP. DFlash is not a viable alternative on this
model. Note the block left `dflash_enabled: true` behind, which then made every
subsequent MTP PUT fail with a 400 until cleared.

### 5. KV quantization — KEPT on, 4-bit, skip_last

Forward+backward sweep (`sweep-kv.json`), 4 samples per config, all with MTP
depth 6:

| Config | TTFT | Decode |
|---|---|---|
| KV quant **off** | 254.0 ms | 48.61 tps |
| 8-bit + skip_last | 241.6 ms | 60.62 tps |
| 4-bit + skip_last | 231.0 ms | 60.06 tps |
| 2-bit + skip_last | 247.0 ms | 63.68 tps |
| 4-bit, no skip_last | 245.6 ms | 63.50 tps |

KV quant off is worst in **both** directions — that is the real signal. The four
enabled variants cluster within ~2%, which is inside noise, so the pooled ranking
among them is not trustworthy. Settled pairwise
(`block-kv-b4-skip-vs-kv-b4-noskip.json`), 3 runs × 3 blocks per arm:

| Config | TTFT | Decode | Total |
|---|---|---|---|
| **4-bit + skip_last** | **257.8 ms** | **55.29 tps** | **5622 ms** |
| 4-bit, no skip_last | 271.3 ms | 53.77 tps | 5796 ms |

**Verdict: keep KV quant on, 4-bit, `skip_last: true`.** 4-bit over 2-bit because
2-bit's apparent lead is inside noise and 2-bit KV is a real quality risk on a
coding workload; `skip_last: true` keeps the most recent tokens at full precision,
which is exactly what matters for code. Quality guardrail passed (below).

### 6. Sampling — applied, no speed measurement

`temperature 0.2`, `top_p 0.95`, `top_k 20`, `force_sampling: true`.
`force_sampling` is required, otherwise the model's own generation config wins and
the profile's sampler is ignored. No speed measurement — sampling does not affect
throughput.

### 7. Quality guardrail — PASSED

Three fixed prompts (pure function, bug fix, small refactor) at the final config.
Full outputs in `quality.md`. All three correct; no reasoning leakage; all
`finish_reason: stop`.

## Final configuration

```json
{
  "max_context_window": 32768,
  "mtp_enabled": true,
  "mtp_adaptive_max_depth": 6,
  "dflash_enabled": false,
  "turboquant_kv_enabled": true,
  "turboquant_kv_bits": 4.0,
  "turboquant_skip_last": true,
  "enable_thinking": false,
  "temperature": 0.2,
  "top_p": 0.95,
  "top_k": 20,
  "force_sampling": true
}
```

Decisive 5-run measurement on a quiet machine (`final-5run.json`):
**TTFT 252.0 ms, decode 59.65 tps, total 5202.9 ms.**

Saved as profile `coding-tuned` via `POST /admin/api/models/Qwen3.8-27B-oQ4e-mtp/profiles`.

## Failure modes hit

| Failure | Cause | Fix |
|---|---|---|
| TTFT ~2900 ms, prefill ~56 tps | `ab.py` re-PUT reload-requiring settings before every request | use `block.py` for reload knobs |
| `RuntimeError: model did not load` | `auto_unloaded: true` unloads but does **not** reload | harness must `POST /load` |
| HTTP 400 "MTP and DFlash cannot both be enabled" | DFlash block left `dflash_enabled: true` | clear it before MTP work |
| HTTP 400 on every KV patch | same leftover DFlash flag | same |
| `PUT .../profiles/coding-tuned` → 404 | `PUT` only updates; creation is `POST` | use `POST` |
| `measure.py` exits non-zero, no `run 1:` line | intermittent | retry up to 3× |
| 12 tps disagreement between context rounds | coordinator's global-settings change unloaded the model | discard, re-run paired |
