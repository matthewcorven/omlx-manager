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
| `Jundot/gemma-4-31B-it-oQ4e-mtp` | oQ4e | dense 30.7B | 18.60 GiB | 18.88 GiB | 267.7 ms / 56.10 tps | 297.0 ms / 40.06 tps | ctx native, MTP on adaptive depth, KV off, DFlash off, temp 0.2 / top_p 0.95 / top_k 64, `force_sampling: false`, thinking off | 3/3 pass |
| `Jundot/gemma-4-26B-A4B-it-oQ8e-mtp` | oQ8e | MoE 26.23B / 4.82B active | 26.86 GiB | 26.93 GiB | 116.0 ms / 113.18 tps | 117.3 ms / 118.6 tps | ctx native, MTP on **fixed depth 4**, KV off, DFlash off, temp 0.2 / top_p 0.95 / top_k 64, `force_sampling: false`, thinking off | 3/3 pass |
| `Jundot/Qwen3.6-35B-A3B-oQ8e-mtp` | oQ8e | MoE 35.1B / ~3B active | 36 GiB | 37.75 GiB | 74.2 ms / 161.22 tps | 77.4 ms / 183.89 tps | ctx native, MTP on depth 4, KV off, **ANE prefill off**, temp 0.6 / top_p 0.95 / top_k 20, `force_sampling: false`, thinking off | 3/3 pass |

**Count: 6 models fully tested and tuned.**

The rows are **not** comparable head-to-head. Ornith's 146 tps vs Qwen's 60 tps
is not a 2.4× speed advantage — Qwen's final 5-run was taken with downloads
active and Ornith's with the machine quiet. The honest statement is that both
were measured on their own terms, and that the *decisions* in each row are sound
because each came from a paired comparison.

What the four models agree on, and where they diverge:

- **Thinking off is a hard constraint for all five, for three different reasons.**
  Qwen never emitted an answer with thinking on (all 300 tokens went to
  `reasoning_content`); Ornith unbudgeted emitted zero content tokens in 2/2 runs,
  and a 512-token budget cost 65× time-to-first-answer-token
  (`thinking_budget_tokens` is a floor, not a cap); flint always streams ~250
  reasoning tokens first, so TTFT 250 ms hides a 3.8–14.8 s TTFC. On
  gemma-4-31B thinking **works properly** — real reasoning, real answer — and is
  still rejected at 48× TTFC. gemma-4-26B-A4B also works properly and is rejected
  at 84× TTFC (8.95 s vs 0.106 s to the first content token). "Thinking is broken"
  is not a universal property of this server; "thinking is too slow for small
  coding tasks" is.
- **KV quantization is model-dependent, and usually a loss.** A real win on
  Qwen3.8-27B (4-bit + `skip_last` beat quant-off 60.62 vs 48.61 tps); a clear
  loss on Ornith (14–16% slower in every quantized variant) and on flint
  (16–18% decode). On gemma-4-31B it is neutral-to-negative with no memory
  argument. Do not assume it from one model.
- **Context: 32768 helped Qwen and did nothing for the other three.** Native was
  kept for Ornith (58.8 vs 59.0 ms — inside noise), flint (null at 34 tokens, 16k
  and 20k), and gemma-4-31B (null at 49 tokens and ~8k). The Qwen3.8 "smaller
  window is faster" result has **not** reproduced once. Treat it as
  model-specific, not a general rule.
- **Speculative decoding needs a draft head, and MTP is the dominant lever when
  it exists.** Ornith has no MTP head and both `dflash_draft_model` and
  `specprefill_draft_model` are null, so those flags are no-ops — DFlash landed
  inside noise, SpecPrefill was 1.9% slower. On Qwen and gemma-4-31B, MTP is worth
  ~2–2.4× decode. Which spec lever exists, not which is "better", drives the
  outcome.
- **Depth tuning does not transfer.** Qwen3.8-27B gained +7% from hard-coding
  depth 6 over adaptive. gemma-4-31B loses 21–36% at every fixed depth 1–6 and
  only ties at depth 8. gemma-4-26B-A4B gains ~+4% from fixed depth 4 — the same
  direction as Qwen, the opposite of its 31B sibling, on the same `gemma4` arch.
  Qwen3.6-35B-A3B is a **null**: the agent's two paired tests read +1.0% and
  +0.7%, but three coordinator re-runs read +8.2%, −2.4% (arms swapped) and
  +3.8%, and a null test with the identical config in both arms produced a 1.8%
  spread. Re-sweep depth per model; never carry a number across, not even between
  two gemmas, and check the null spread before believing a ~1% effect.
- **ANE prefill is available on Qwen3.6-35B-A3B and buys nothing.** It is the one
  model in the set with `ane_prefill_backend: qwen` (default fraction 0.53), so it
  was the distinctive TTFT lever to test. It compiles and runs, and it is a null
  on short prompts, a null at 8k and 32k padding, and 0.4–6% *worse* on a
  cache-defeated cold ~21.7k-token prefill. Rejected. Note the trap that hid this
  for every earlier model: the default benchmark prompt is identical each run, so
  the prefix cache serves the whole prefill and TTFT measures cache restore, not
  prefill — any prefill-path knob looks null until you defeat the cache with a
  per-request nonce.

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

Notes on the gemma-4-31B-it-oQ4e-mtp row:

- **The model was already tuned by its defaults.** MTP was on at adaptive depth out
  of the box, and no fixed depth beat it: depths 1–6 lose 21–36% decode, and depth 8
  only ties it (49.72 vs 49.47 tps over 9 alternating blocks each). The final config
  differs from the defaults in three ways — thinking pinned off, the coding sampler,
  and `force_sampling: false` — and is throughput-identical to the defaults in a
  paired A/B (37.39 vs 37.06 tps, 319.5 vs 316.3 ms TTFT).
- **MTP is a 2.4× decode win** (50.62 vs 21.45 tps) and, unlike Ornith, the draft head
  is real here (`model-mtp.safetensors`, 0.47B).
- **KV quant is a clear loss.** 8-bit costs 5% decode and 21 ms TTFT; 4-bit is inside
  noise on decode and also 21 ms worse on TTFT. 4-bit **without** `skip_last` does not
  run at all under MTP — hard error, `_QuantizedStateProxy` passed into
  `scaled_dot_product_attention`.
- **Context capping is a null result** at both 49 tokens and ~8k tokens, matching
  Ornith and flint and contradicting Qwen3.8-27B. Native kept.
- **`force_sampling: true` costs 6.6% decode** (39.49 vs 42.29 tps). Left `false`.
- **Thinking genuinely works on this model** — the only one in this repo where it
  does. Real `reasoning_content`, real answer. Still rejected: 15.9 s to the first
  content token vs 0.33 s, a 48× penalty, and a 700-token budget is exhausted by
  reasoning before the answer completes.
- **DFlash is unavailable in practice**: mutually exclusive with MTP (HTTP 400), and
  with MTP off and no draft model it is a no-op at 21.71 tps.
- **MoE expert offload is N/A** — `moe-offload-fit` returns HTTP 400 for this dense
  model. Recorded as not-applicable, not as an error.
- Full detail: [`gemma-4-31B-it-oQ4e-mtp/NOTES.md`](gemma-4-31B-it-oQ4e-mtp/NOTES.md),
  [`tuning-log.md`](gemma-4-31B-it-oQ4e-mtp/tuning-log.md),
  [`quality.md`](gemma-4-31B-it-oQ4e-mtp/quality.md).

Notes on the gemma-4-26B-A4B-it-oQ8e-mtp row:

- **The defaults were already good; the win is MTP draft depth.** MTP was on at
  adaptive depth out of the box, and turning it off costs 32% decode (76.71 vs
  113.00 tps). Pinning `mtp_fixed_depth: 4` beats adaptive by ~+4% decode and
  −10 ms TTFT in a paired alternating-block test. Depths 1, 2, 6 and 8 all lose
  9–22%, so the curve is a single peak at 4.
- **This is the opposite of gemma-4-31B on the same architecture.** The 31B loses
  at every fixed depth 1–6; the 26B-A4B gains at 4. Depth must be re-swept per
  model even within one family.
- **KV quant is a loss.** 8-bit costs 5.5% decode and 5 ms TTFT; 4-bit with
  `skip_last` costs 2.5% decode and 6 ms TTFT. 4-bit **without** `skip_last` is a
  hard runtime error under MTP (`_QuantizedStateProxy` passed into
  `scaled_dot_product_attention`) — the same failure gemma-4-31B showed.
- **Context capping is a null result** at 49 tokens and at ~8k tokens, matching
  Ornith, flint and gemma-4-31B. Native kept.
- **Thinking works properly and is rejected at 84× TTFC** — 8.95 s to the first
  content token vs 0.106 s, and a 900-token budget is spent entirely on reasoning.
- **MoE expert offload is N/A** — `moe-offload-fit` returns `resident` with 0
  bytes; 26.93 GiB sits far under the ceiling.
- **Coordinator correction:** the agent reported +8.7% for depth 4 over adaptive;
  independent re-measurement gives **+3.8%**. The direction and the setting are
  right, the magnitude was inflated by a low adaptive arm. See the verification
  section in the model's `NOTES.md`.
- Full detail: [`gemma-4-26B-A4B-it-oQ8e-mtp/NOTES.md`](gemma-4-26B-A4B-it-oQ8e-mtp/NOTES.md),
  [`tuning-log.md`](gemma-4-26B-A4B-it-oQ8e-mtp/tuning-log.md),
  [`quality.md`](gemma-4-26B-A4B-it-oQ8e-mtp/quality.md).

Notes on the Qwen3.6-35B-A3B-oQ8e-mtp row:

- **The +14% is a configuration correction, not a tuning win.** The model ships
  with `enable_thinking: null`, and on this model `null` is **not** off: a plain
  300-token request emits reasoning chunks and no content, and with
  `enable_thinking: true` it never emits a content token at all (0 content chars,
  2397 reasoning chars at max_tokens 900; still 0 content and 10583 reasoning
  chars in 16.7 s at 3000, `finish_reason: length` every time). Pinning it to
  `false` is worth +7.1% decode on its own and is the difference between an
  answer and no answer. The paired whole-config test (n=10/arm) reads 183.89 vs
  161.22 tps, −225 ms total, +3.2 ms TTFT — coordinator re-measurement gives
  +14.0%, −226 ms, +3.2 ms.
- **MTP depth 4 over adaptive is a null.** See the depth bullet above. Left
  applied because it never hurt and depths 6/8 cost 11%/33%, but not a gain.
- **KV quant is a loss** (off 190.96 vs 8-bit+skip 185.81 / 4-bit+skip 176.84 /
  4-bit no-skip 177.69 tps, n=6 × 4 arms). Note `turboquant_skip_last: false`
  under MTP did **not** reproduce the hard error the gemmas showed — 3 coherent
  requests, `error: null`.
- **Context capping is a null** at 49 tokens and ~8k, matching every model except
  Qwen3.8-27B.
- **ANE prefill is available and rejected** — see the ANE bullet above.
- **`force_sampling` is a measurement trap, not a lever.** It overrides the
  request's `temperature: 0.0` with the model's 0.6, so a harness that relies on
  determinism sees an apparent +4% that is really just sampling variance.
  Verified: with it off, three identical temp-0 requests return the same string;
  with it on, three different strings.
- **MoE expert offload is N/A** — `moe-offload-fit` returns `resident`, 37.75 GiB
  sits under the ceiling.
- Full detail: [`Qwen3.6-35B-A3B-oQ8e-mtp/NOTES.md`](Qwen3.6-35B-A3B-oQ8e-mtp/NOTES.md),
  [`tuning-log.md`](Qwen3.6-35B-A3B-oQ8e-mtp/tuning-log.md),
  [`quality.md`](Qwen3.6-35B-A3B-oQ8e-mtp/quality.md).

## Downloaded, tuning not yet started

All of these are on disk and pass a load smoke test or are queued for one. None
has a `final.json` yet.

| Model | On disk | Resident | MoE | MTP | Native ctx | Smarts | Status |
|---|---|---|---|---|---|---|---|
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

1. Test `moe_expert_offload_enabled` at the reported ceiling, then sweep the
   resident fraction downward to find the throughput/footprint knee. This needs
   the model local, which it now is.
2. If the offloaded configuration is unusable in throughput terms, shuttle the
   105 GB to `/Volumes/NVMe` and treat it as available-but-not-resident.

### Re-probed 2026-10-29 — the numbers above are stale, and the lever is bigger

The table above was taken before the model was registered. Re-querying the live
server now that it is local gives a **different and more favourable** answer:

| `mtp_enabled` | `qwen4_ple_ssd_offload` | Status | Max offloadable | Bytes |
|---|---|---|---|---|
| `true` | `false` | `fit` | **16%** | 52,893,355,231 |
| `false` | `false` | `fit` | **18%** | 53,067,537,631 |
| `true` | `true` | `fit` | **63%** | 52,875,560,669 |
| `false` | `true` | `fit` | **64%** | 53,038,130,909 |

Two corrections to the earlier reading:

- The ceiling is **16%**, not 20%, with MTP on and PLE off. The 20%/21% figures
  were pre-registration estimates.
- `qwen4_ple_ssd_offload` is **forced on** for this model
  (`qwen4_ple_ssd_offload_forced: true`, `config_model_type: qwen4_exp`), and it
  changes the answer by a factor of four: 16% → **63%**. The PLE embedding table
  is 79.2 GB of mmap-able weights (`qwen4_ple_mmap_bytes`), so offloading it
  frees the room that lets 63% of experts stay resident instead of 16%.

`moe_offload_allows_mtp: true` here, unlike gemma-4-26B — offload and MTP can be
combined, so the MTP gain does not have to be traded away for residency.

The `bytes` field is the off-heap expert payload and is roughly constant across
all four rows (~52.9 GB); what changes is how much of the *rest* of the model
stays resident. So the sweep to run is over `moe_expert_offload_resident_fraction`
with PLE offload on, not over the offload on/off switch.

## Storage

| Volume | Size | Free | Role |
|---|---|---|---|
| Internal (`/`) | 1.8 TiB | 299 GiB | active downloads and tuning |
| `/Volumes/NVMe` | 931 GiB | 850 GiB | finished models, registered in `model.model_dirs` |

Internal free space fell from 396 GiB to 180 GiB as the download set completed,
then recovered to 299 GiB once the four finished models were shuttled to NVMe
(81 GiB there: Ornith 20G, Qwen3.8-27B 16G, gemma-4-31B 19G, gemma-4-26B 27G).
Both directories are registered, so a shuttled model still loads — moving it is
a disk operation only, never a "make it usable" step.

**Shuttling needs a server restart to re-index.** The move itself is a plain
`mv`, but oMLX caches the model path from its last scan. After a shuttle,
`GET /admin/api/models` still reports the old internal path until the server is
restarted; loading from that stale path fails. Restart, confirm the reported
path is the NVMe one and exists, then load and serve one real request to prove
it. `scripts/shuttle_model.sh` now checks the reported path for existence and
says "STALE INDEX" instead of printing the old path as if it were fine.

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
