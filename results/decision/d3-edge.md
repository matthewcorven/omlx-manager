# `vllm-sr/d3-edge`

| | |
|---|---|
| Family | d3 (Decision 3.0) |
| Download | 1.2 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 (backbone `max_position_embeddings`) |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | d3-edge | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | 0.771 | **0.857** |
| brier | 0.2514 | **0.1838** |
| logloss | 0.3763 | **0.2766** |
| ece | 0.1156 | **0.0496** |
| mean confidence | 0.7988 | 0.8879 |
| ambiguous confidence | 0.7702 | 0.7198 |
| latency median | **12.9 ms** | 536.3 ms |
| latency p95 | **108.7 ms** | 9066.0 ms |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | d3-edge acc | d3-edge brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.000 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.052 | 1.000 | 0.0001 |
| multilabel | 6 | 1.000 | 0.010 | 1.000 | 0.0012 |
| negation | 4 | 0.750 | 0.136 | **1.000** | 0.0161 |
| graded | 5 | **0.800** | **0.324** | 0.600 | 0.6293 |
| arithmetic | 6 | 0.667 | 0.539 | **0.833** | 0.2346 |
| longstate | 6 | 0.333 | 0.522 | **0.667** | 0.3006 |

## What the numbers say

**It is a latency model, not a quality model.** 12.9 ms median against 536 ms is
a 40× advantage, and it holds at p95 (109 ms vs 9.1 s). If the workload is
"classify this ticket into one of four buckets", d3-edge is the right answer and
the baseline is not even close to viable.

**But its probabilities are not usable as probabilities.** Brier 0.2514 is worse
than emitting 0.5 for every item. The failure is concentrated in `arithmetic`
(0.539) and `longstate` (0.522) — the two families where it is both wrong and
confident. `noul-arithmetic-05` (`17 + 26 = 41`) is answered `true` at p=0.865.
That is not a near-miss; it is a confident inversion.

**`longstate` is the most alarming result.** The same six arithmetic items score
0.667 when short and 0.333 when buried in padding, with confidence *dropping*
from 0.727 to 0.594. The model is not truncating — there were no 413s — it is
simply losing the signal. A 262K context window does not mean 262K of usable
context.

**`ambiguous` confirms the calibration problem.** 0.770 mean confidence on four
items that are undecidable by construction. The baseline is also overconfident
(0.720) but less so, and its overall ECE is 2.3× better.

**It wins where the task is lexical.** `multilabel` (1.000, brier 0.010) and
`sentiment` (1.000, brier 0.000) are perfect. Intent classification over four
options is exactly what a small decision head is good at.

## Recommendation

Use `d3-edge` for **high-volume, latency-bound classification where the argmax is
all you need** — routing, intent buckets, yes/no gates. Do not use it where the
probability itself is consumed: thresholds, escalation scores, or anything that
multiplies probabilities together. Its Brier score says the number is not
calibrated.

If calibrated probabilities are required, the 27B baseline is better on quality
and 40× worse on latency; the honest middle is to use d3-edge for the argmax and
reserve the baseline for the cases that need a real probability.

## Modality

d3 accepts images and video. Both were scored — see
[`media/README.md`](media/README.md).

| Corpus | Acc | Brier | ECE | Median ms | p95 ms |
|---|---|---|---|---|---|
| image (25 items) | 0.773 | 0.3260 | 0.1309 | 211 | 228 |
| video (16 items) | 0.812 | 0.3642 | 0.2655 | 159 | 162 |

| Image family | Acc | Brier | Conf |
|---|---|---|---|
| `img-colour` | 1.000 | 0.0043 | 0.949 |
| `img-spatial` | 1.000 | 0.0004 | 0.988 |
| `img-shape` | 1.000 | 0.0392 | 0.890 |
| `img-count` | **0.500** | 0.5897 | 0.801 |
| `img-text` | **0.500** | 0.8644 | 0.942 |

| Video family | Acc | Brier | Conf |
|---|---|---|---|
| `vid-appear` | 1.000 | 0.0781 | 0.822 |
| `vid-colourchange` | 1.000 | 0.0002 | 0.990 |
| `vid-direction` | 0.750 | 0.4707 | 0.452 |
| `vid-motion` | **0.500** | 0.9079 | 0.968 |

**d3-edge is not a vision model, and the failure is degenerate rather than
degraded.** It answers `true` to all six counting questions and `false` to all
four text questions — a constant answer per family, at 0.68–0.99 confidence. It
is not uncertain about the images; it is not looking at them. The `degenerate`
gate does not fire because each individual answer is a well-formed distribution,
which is exactly why the per-family breakdown has to be read and not just the
aggregate.

The one place it is honest is `vid-direction`, where mean confidence drops to
0.452 and it gets three of four. That is the only family in either corpus where
its probabilities carry information about its own competence.

**The text-sweep recommendation does not survive this.** "Short, lexical, argmax
only, tight p95" was written against a text corpus. 211 ms per image is 8× faster
than `d3-flash` and wrong on a third of them, confidently. Any workload whose
input can contain an image must not route to `d3-edge`.

## Caveats

The text corpus is 39 items and the media corpora are 25 images and 16 clips;
treat every per-family cell as directional. Single-request latency only —
`DecisionEngine` serialises behind an `asyncio.Lock`, so this says nothing about
throughput under concurrency. See "What this corpus cannot measure" in the
methodology.
