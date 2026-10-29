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

**Count: 1 model fully tested and tuned.**

Notes on the one completed row:

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

## Downloaded, tuning not yet started

All of these are on disk and pass a load smoke test or are queued for one. None
has a `final.json` yet.

| Model | On disk | Resident | MoE | MTP | Native ctx | Smarts | Status |
|---|---|---|---|---|---|---|---|
| `Jundot/Ornith-1.0-35B-oQ4e` | 20.64 GB | 22.16 GB | yes | no | 262144 | 3.807 | next in queue |
| `mlx-community/flint-oQ4e` | 22.84 GB | — | — | — | 262144 | — | queued |
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

Two options, neither taken yet:

1. Shuttle it to `/Volumes/NVMe` to reclaim ~105 GB of internal space, and treat
   it as available-but-not-resident.
2. Test `moe_expert_offload_enabled` with a reduced
   `moe_expert_offload_resident_fraction` — it is a true MoE, so the lever
   applies — accepting the decode-speed cost. This needs the model local, which
   it now is.

This is the one model where MoE offload can actually be measured, so it is the
right place to answer the offload question before spending 110 GB on GLM.

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
