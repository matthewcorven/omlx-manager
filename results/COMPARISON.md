# Cross-model comparison

Living table. One row per model, added when its `final.json` and `NOTES.md` land.

**Read the caveats before using any number here.** Absolute decode throughput on
this machine slides with background load — 88 → 22 tps over a single session with
no config change, driven by Hugging Face download I/O and WindowServer. Only
*paired* comparisons (interleaved A/B, alternating blocks, forward+backward
sweeps) are trustworthy within a model. Across models, treat the numbers as
order-of-magnitude only.

## Tested and tuned

| Model | Quant | Params | DL | Resident | Baseline TTFT / decode | Final TTFT / decode | Final settings | Quality |
|---|---|---|---|---|---|---|---|---|
| `Jundot/Qwen3.8-27B-oQ4e-mtp` | oQ4e | dense 27.8B | 15.81 GiB | 16.60 GiB | 233.6 ms / 78.33 tps | 252.0 ms / 59.65 tps | ctx 32768, MTP on depth 6, KV 4-bit + `skip_last`, temp 0.2 / top_p 0.95 / top_k 20, thinking off | 3/3 pass |
| `Jundot/Ornith-1.0-35B-oQ4e` | oQ4e | MoE 35B | 21.1 GB | 19.96 GB | 52.0 ms / 146.72 tps | 48.0 ms / 146.34 tps | ctx native, all spec/quant/offload off, temp 1.0 / top_p 0.95 / top_k 20, thinking off | 3/3 pass |
| `Jundot/flint-oQ4e` | oQ4e | MoE 2.5B active | 22 GB | 22.84 GB | 251.0 ms / 114.6 tps | 252.0 ms / 113.23 tps | ctx native, KV off, no MTP/draft head, temp 1.0 / top_p 0.95 / top_k 20, `activation_fp16_enabled: false` | 3/3 pass |

**Count: 3 models fully tested and tuned.**

The rows are **not** comparable head-to-head. Ornith's 146 tps vs Qwen's 60 tps
is not a 2.4× speed advantage — Qwen's final 5-run was taken with downloads
active and Ornith's with the machine quiet. The honest statement is that both
were measured on their own terms, and that the *decisions* in each row are sound
because each came from a paired comparison.

What the two models agree on, and where they diverge:

- **Thinking off is a hard constraint for both.** Qwen never emitted an answer
  with thinking on (all 300 tokens went to `reasoning_content`); Ornith unbudgeted
  emitted zero content tokens in 2/2 runs, and a 512-token budget cost 65×
  time-to-first-answer-token. `thinking_budget_tokens` is a floor, not a cap.
- **KV quantization is model-dependent.** A real win on Qwen3.8-27B (4-bit +
  `skip_last` beat quant-off 60.62 vs 48.61 tps) and a clear loss on Ornith
  (14–16% slower in every quantized variant). Do not assume it from one model.
- **Context: 32768 helped Qwen, did nothing for Ornith.** Native was kept for
  Ornith (58.8 ms / 151.90 tps vs 59.0 ms / 151.24 tps — inside noise), so the
  Qwen3.8 "smaller window is faster" result did **not** reproduce. Treat that
  finding as model-specific, not a general rule.
- **Speculative decoding needs a draft head.** Ornith has no MTP head and both
  `dflash_draft_model` and `specprefill_draft_model` are null, so those flags are
  no-ops — DFlash landed inside noise, SpecPrefill was 1.9% slower. On Qwen, MTP
  was the single dominant lever (2× decode). Which spec lever exists, not which
  is "better", drives the outcome.

Notes on the Qwen3.8-27B row:

- Baseline was measured on a quiet machine; the final 5-run was measured later
  with downloads active. The 78.33 → 59.65 tps drop is machine load, **not** a
  regression. Every setting decision behind the final config came from a paired
  comparison within a single block.
- MTP was already enabled at baseline, so there is no "turn MTP on" gain to
  claim — the win is depth tuning. Depth 6 beat the adaptive default by +7%
  decode and −6% total wall time for a 3% TTFT cost.
- Thinking must stay **off**: with it on, all 300 completion tokens went to
  `reasoning_content` and no answer was ever emitted.
- DFlash was rejected: mutually exclusive with MTP, and tested with MTP off it
  landed inside noise at 2.2× slower than MTP.
- Full detail: [`Qwen3.8-27B-oQ4e-mtp/NOTES.md`](Qwen3.8-27B-oQ4e-mtp/NOTES.md),
  [`tuning-log.md`](Qwen3.8-27B-oQ4e-mtp/tuning-log.md),
  [`quality.md`](Qwen3.8-27B-oQ4e-mtp/quality.md).

Notes on the Ornith-1.0-35B row:

- **Nothing helped.** Every performance knob was tested with paired comparisons
  and every one was neutral or negative. The final config is the default config
  plus two changes: thinking off (a correctness fix — without it the model never
  emits an answer) and the model card's sampler.
- MoE expert offload was considered and is **not applicable**: 19.96 GB resident
  is far under the ~89.6 GB ceiling, so there is no residency pressure to relieve.
- Quality passed 3/3 with 0 reasoning tokens and `finish_reason: stop`.
- **Live-setting drift, unexplained:** `enable_thinking` reverted to `true` on its
  own after the final config was applied and verified. It was re-applied,
  reloaded, and re-diffed to 0 diffs, and the live value is confirmed `false`
  now. The cause was not identified — re-verify this key before any future
  benchmark on this model.
- Full detail: [`Ornith-1.0-35B-oQ4e/NOTES.md`](Ornith-1.0-35B-oQ4e/NOTES.md),
  [`tuning-log.md`](Ornith-1.0-35B-oQ4e/tuning-log.md),
  [`quality.md`](Ornith-1.0-35B-oQ4e/quality.md).

## Downloaded, tuning not yet started

All of these are on disk and pass a load smoke test or are queued for one. None
has a `final.json` yet.

| Model | On disk | Resident | MoE | MTP | Native ctx | Smarts | Status |
|---|---|---|---|---|---|---|---|
| `mlx-community/flint-oQ4e` | 22.84 GB | — | — | — | 262144 | — | next in queue |
| `Jundot/gemma-4-31B-it-oQ4e-mtp` | 19.50 GB | 21.53 GB | no | yes | 262144 | 4.929 | queued |
| `Jundot/gemma-4-26B-A4B-it-oQ8e-mtp` | 28.17 GB | — | yes | yes | 262144 | — | queued |
| `Jundot/Qwen3.6-35B-A3B-oQ8e-mtp` | 37.75 GB | — | yes | yes | 262144 | — | queued |
| `Jundot/Qwen3.8-Flash-Next-oQ4e-mtp` | 105.06 GB | 112.81 GB | yes | yes | 262144 | 5.327 | **resident-bound, see below** |

Not coding models, downloaded for other roles: `jinaai/jina-reranker-v3.5`
(1.17 GB, reranker), `mlx-community/Unlimited-OCR-2-8bit` (3.84 GB, OCR).

## Rejected / deferred

| Model | DL | Resident | Reason |
|---|---|---|---|
| `Jundot/GLM-5.3-Flash-oQ2e-mtp` | 102.7 GB | 115.82 GB | **Deferred — resident-memory-bound, MoE offload support unverified.** 321.3B total / 25.4B active MoE, 860205 native ctx, MTP. Resident exceeds the ~89.6 GB ceiling by ~26 GB. `GET /admin/api/models/{id}/moe-offload-fit` requires the model to be locally registered, so it cannot answer until 110 GB is downloaded — which is a poor trade to make on an unverified lever. Relocation to `/Volumes/NVMe` does **not** help: that relieves disk, not unified memory. Revisit only if a smaller quant or a confirmed offload fraction appears. |

## Open issue: `Qwen3.8-Flash-Next-oQ4e-mtp` is resident-bound

It is downloaded (105.06 GB on disk) but its resident size is **112.81 GB**
against a ~89.6 GB practical ceiling, and it sits in the server's `unlock` tier
requiring `wired_limit`. It is the single largest consumer of internal disk and
cannot be loaded at its default residency.

**The offload lever is confirmed available on this model.** Querying
`GET /admin/api/models/Qwen3.8-Flash-Next-oQ4e-mtp/moe-offload-fit`:

| `mtp_enabled` | Status | Max offloadable | Bytes | Reserve |
|---|---|---|---|---|
| `true` | `fit` | 20% | 55,680,273,631 | 4 GiB |
| `false` | `fit` | 21% | 55,343,520,991 | 4 GiB |

So ~55.7 GB of experts can live off-heap with MTP on, taking resident from
112.81 GB to roughly **57 GB** — comfortably under the ~89.6 GB ceiling. The
question is no longer *whether* it can be made to fit but *what it costs in
decode throughput*, which is exactly what a tuning sweep measures.

Note the asymmetry with GLM: the same query on GLM would have needed 110 GB
downloaded first, and GLM's ceiling gap is ~26 GB. Here the gap is ~23 GB and
the model is already local, so this is the cheaper place to settle the question.

Two options, neither taken yet:

1. Test `moe_expert_offload_enabled` at the reported 20% ceiling, then sweep the
   resident fraction downward to find the throughput/footprint knee. This needs
   the model local, which it now is.
2. If the offloaded configuration is unusable in throughput terms, shuttle the
   105 GB to `/Volumes/NVMe` and treat it as available-but-not-resident.

## Storage

| Volume | Size | Free | Role |
|---|---|---|---|
| Internal (`/`) | 1.8 TiB | 180 GiB | active downloads and tuning |
| `/Volumes/NVMe` | 931 GiB | 931 GiB | finished models, registered in `model.model_dirs` |

Internal free space fell from 396 GiB to 180 GiB as the download set completed.
The NVMe volume is still empty; shuttling finished models there is the next
reclaim step. Both directories are registered, so a shuttled model still loads —
moving it is a disk operation only, never a "make it usable" step.

## How rows get added

Per `AGENTS.md`, a model only gets a row in **Tested and tuned** when its
`final.json` and `NOTES.md` are written and committed, with:

- repo_id, quant, download and resident size
- baseline TTFT / decode
- the sweep table (variant → TTFT, decode, verdict)
- the final settings JSON plus a rationale
- failure modes hit

Every setting verdict must come from a paired comparison. A number measured in
one block is never compared to a number from another block.

Notes on the flint-oQ4e row:

- **The corrected baseline is the final config.** Every wired-up knob was
  measured paired and lost or tied, so nothing was changed. The 1.2% gap between
  baseline and final is drift, measured on the same config twice.
- **`activation_fp16_enabled` is a corruption switch on this model, not a
  speedup.** The first tuning pass recorded a 26× TTFT win from `true`; it was
  the model emitting noise without ever entering its reasoning phase. See
  [`flint-oQ4e/CORRECTION.md`](flint-oQ4e/CORRECTION.md).
- **A saturated SSD prefix cache was a second, independent fault.** At
  185 GB / 185 GB the cache served poisoned prefixes and broke coherence even
  with the safe setting. Quarantining the cache fixed it.
- **KV quant cost 16–18% decode** (114.94 → 94.22–96.78 tps) plus 5–11 ms TTFT.
  A 2.5B-active MoE is bandwidth-bound; dequant per step costs more than the
  bandwidth saved.
- **`max_context_window: 32768` was a null result** at 34 tokens, 16k and 20k
  prompts, with byte-identical `model_memory_used`. Native was kept because it
  is free and accepts prompts that 32768 rejects with HTTP 400.
- **`thinking_budget_enabled` / `_tokens` are not enforced on flint.** The API
  accepts and echoes them; measured reasoning length was unchanged.
- **TTFT 250 ms is misleading for this model.** TTFC is 3.8–14.8 s because it
  always streams ~250 reasoning tokens first. Reasoning-length variance
  (3.7k–8.9k chars) dominates everything a setting can control — the throughput
  knobs are worth 0–20% of decode, the reasoning phase 15–60× that.
