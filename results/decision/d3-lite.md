# `vllm-sr/d3-lite`

| | |
|---|---|
| Family | d3 (Decision 3.0) |
| Download | 1.7 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 (backbone `max_position_embeddings`) |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | d3-lite | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | 0.714 | **0.857** |
| brier | 0.2546 | **0.1838** |
| logloss | 0.3906 | **0.2766** |
| ece | 0.1240 | **0.0496** |
| mean confidence | 0.8383 | 0.8879 |
| ambiguous confidence | 0.7838 | 0.7198 |
| latency median | **22.2 ms** | 517.8 ms |
| latency p95 | **204.5 ms** | 535.3 ms |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | d3-lite acc | d3-lite brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.000 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.000 | 1.000 | 0.0001 |
| multilabel | 6 | 1.000 | 0.033 | 1.000 | 0.0012 |
| negation | 4 | 1.000 | 0.002 | 1.000 | 0.0161 |
| arithmetic | 6 | 0.667 | 0.448 | **0.833** | 0.2346 |
| graded | 5 | 0.400 | 0.586 | **0.600** | 0.6293 |
| longstate | 6 | **0.167** | 0.514 | **0.667** | 0.3006 |

## What the numbers say

**`d3-lite` is strictly worse than `d3-edge` at 1.4× the size.** Accuracy 0.714
vs 0.771, Brier 0.2546 vs 0.2514, ECE 0.124 vs 0.116, and 22.2 ms vs 12.9 ms
median latency. There is no axis on which the larger checkpoint wins. This is the
clearest result of the sweep so far: **size does not buy quality in the d3 family
at the small end** — it buys nothing measurable and costs latency.

**`longstate` collapses harder than on `d3-edge`.** 0.167 accuracy (1 of 6) with
mean confidence 0.525 — the model is at chance and knows it, which is at least
honest, but it means the 262K context window is not usable context. `d3-edge`
managed 0.333 on the same six items. The smaller model degrades faster with
padding, which is the opposite of what a "lite" tier is usually sold as.

**`graded` is the one family where it beats the baseline on Brier** (0.586 vs
0.629) while losing on accuracy (0.400 vs 0.600). Both models are badly
miscalibrated on the 0–4 scale; `d3-lite` is simply less confidently wrong. That
is not a win worth having.

**The lexical families are still perfect.** sentiment, ordering, multilabel and
negation all at 1.000 accuracy with Brier ≤ 0.033. Same pattern as `d3-edge`:
small decision heads are excellent at short, lexical, single-hop classification
and unreliable at anything requiring state or arithmetic.

**Brier 0.2546 is worse than a constant 0.5 guess** (0.25), same as `d3-edge`.
Neither small d3 checkpoint produces usable probabilities.

## Recommendation

**Do not deploy `d3-lite`.** `d3-edge` is smaller, faster, and better on every
quality metric. If a d3-tier model is wanted for latency-bound argmax
classification, `d3-edge` is the correct choice and `d3-lite` should be skipped
entirely.

The general recommendation from `d3-edge` still holds: use the d3 family for
argmax-only routing and intent buckets, never for consumed probabilities, and
never for long-context state tracking.

## Caveats

Text-only corpus. d3 accepts images and video (≤ 300 s, 4–32 frames) and none of
that is scored here. Single-request latency only — `DecisionEngine` serialises
behind an `asyncio.Lock`, so this says nothing about throughput under concurrency.
See "What this corpus cannot measure" in the methodology.
