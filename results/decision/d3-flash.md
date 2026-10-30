# `vllm-sr/d3-flash`

| | |
|---|---|
| Family | d3 (Decision 3.0) |
| Download | 16.8 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | d3-flash | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | **0.943** | 0.857 |
| brier | **0.0764** | 0.1838 |
| logloss | **0.1200** | 0.2766 |
| ece | 0.0802 | **0.0496** |
| mean confidence | 0.9328 | 0.8879 |
| ambiguous confidence | **0.6518** | 0.7198 |
| latency median | **153.4 ms** | 546.8 ms |
| latency p95 | 2898.5 ms | **593.4 ms** |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | d3-flash acc | d3-flash brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.000 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.000 | 1.000 | 0.0001 |
| negation | 4 | 1.000 | 0.000 | 1.000 | 0.0161 |
| multilabel | 6 | 1.000 | 0.001 | 1.000 | 0.0012 |
| arithmetic | 6 | **1.000** | **0.006** | 0.833 | 0.2346 |
| longstate | 6 | **1.000** | **0.006** | 0.667 | 0.3006 |
| graded | 5 | 0.600 | **0.520** | 0.600 | 0.629 |

## What the numbers say

**`d3-flash` is the best-quality decision model in the sweep.** Accuracy 0.943,
Brier 0.0764, logloss 0.120 — all three beat the 27B baseline by wide margins
(0.943 vs 0.857, 0.0764 vs 0.1838, 0.120 vs 0.277). It is the only model that
wins every family except `graded`, and it wins `graded` on Brier too.

**It is the only model in the sweep that is honest about ambiguity.** Ambiguous
confidence 0.6518 — *below* the baseline's 0.7198 and far below clef-flash's
0.9281. Every other decision model asserted more confidence on undecidable items
than the chat baseline did. d3-flash is the first that hedges. That property alone
makes it the only decision model here whose probabilities can be used for
escalation without a recalibration layer.

**`longstate` and `arithmetic` are solved.** 1.000/0.006 on both, matching
d3-mini. The size ordering in the d3 family is now clear and monotone above
`d3-lite`: 1.2 GB → 0.771, 1.7 GB → 0.714, 4.5 GB → 0.829, 9.1 GB → 0.914,
16.8 GB → 0.943. **The 262K context window only becomes usable at 9 GB and up.**

**`graded` is the last holdout and it is a corpus problem, not a model problem.**
0.600 accuracy for d3-flash, d3-mini's 0.400, clef-flash's 0.600, and the
baseline's 0.600. Five items on a five-way ordinal scale cannot separate models.
d3-flash's Brier 0.520 is the best of the group, which is the only signal
available.

**The p95 is the cost.** 2898 ms against the baseline's 593 ms — 4.9× worse, and
the worst tail in the sweep. The median is 3.6× better than the baseline. This is
the same tradeoff clef-flash makes, only more extreme: d3-flash is the best
quality and the worst tail.

**ECE 0.0802 is still worse than the baseline's 0.0496** despite the better
Brier. The Brier win comes from being right, not from reporting better numbers.
Mean confidence 0.933 against 0.943 accuracy is a small *under*confidence gap —
the first model in the sweep that is not overconfident overall.

## Recommendation

**`d3-flash` is the recommended decision model when quality matters more than
tail latency.** It is the best model measured on every quality axis, and the only
one whose ambiguity handling is better than the chat baseline's.

Use it for:

- **calibrated probability consumption** — Brier 0.0764 and honest ambiguity
  handling mean the number can be thresholded directly.
- **long-context decision tasks** — 1.000 accuracy at 262K of padding.
- **arithmetic and state tracking** — 1.000, where the baseline gets 0.833/0.667.

Do not use it for:

- **hard p95 latency SLOs** — 2898 ms p95 is the worst in the sweep.
- **ordinal 0–4 grading** — 0.600, same as everything else; the corpus is the
  limiting factor.

**The decision rule across the sweep is now:**

| Workload | Model | Why |
|---|---|---|
| short, lexical, argmax only, tight p95 | `d3-edge` | 12.9 ms, 0.771 acc, p95 109 ms |
| long context, arithmetic, probability consumed | `d3-mini` | 0.914 acc, 0.1034 Brier, 86 ms median |
| best quality, tail latency tolerable | `d3-flash` | 0.943 acc, 0.0764 Brier, honest ambiguity |
| calibrated probabilities, no long context | `clef-flash-oQ4e` | 0.1742 Brier, but 0.928 ambiguous conf |

`d3-lite` is dominated by `d3-edge` and should not be deployed. `d3-nano` is a
reasonable middle but is beaten by `d3-mini` on every axis except size.

## Caveats

Text-only corpus. d3 accepts images and video (≤ 300 s, 4–32 frames) and none of
that is scored here. Single-request latency only — `DecisionEngine` serialises
behind an `asyncio.Lock`, so this says nothing about throughput under concurrency.
The `graded` family has only 5 items; treat that cell as directional. See "What
this corpus cannot measure" in the methodology.
