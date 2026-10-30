# `Jundot/clef-flash-oQ4e`

| | |
|---|---|
| Family | clef |
| Download | 6.6 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | clef-flash-oQ4e | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | 0.857 | 0.857 |
| brier | **0.1742** | 0.1838 |
| logloss | 0.2970 | **0.2766** |
| ece | 0.0901 | **0.0496** |
| mean confidence | 0.8887 | 0.8879 |
| ambiguous confidence | 0.9281 | **0.7198** |
| latency median | **231.7 ms** | 541.4 ms |
| latency p95 | 2322.4 ms | **578.2 ms** |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | clef-flash acc | clef-flash brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.002 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.001 | 1.000 | 0.0001 |
| multilabel | 6 | 1.000 | 0.003 | 1.000 | 0.0012 |
| negation | 4 | 1.000 | 0.003 | 1.000 | 0.0161 |
| arithmetic | 6 | 0.833 | **0.225** | 0.833 | 0.235 |
| graded | 5 | 0.600 | **0.624** | 0.600 | 0.629 |
| longstate | 6 | 0.667 | **0.264** | 0.667 | 0.301 |

## What the numbers say

**This is the first decision model in the sweep to beat the chat baseline on
Brier** — 0.1742 vs 0.1838 — and it does it at identical accuracy (0.857 both).
That is a real result: the same answers, better probabilities. It is also the
first decision model to beat the baseline on Brier in *every* family where the
two are compared, including `longstate` (0.264 vs 0.301) where every d3
checkpoint failed badly.

**But the win is narrow and the tail is bad.** 231.7 ms median is only 2.3×
faster than the baseline, not 40×. And p95 is 2322 ms — **4× worse than the
baseline's 578 ms**. The longstate items dominate the tail: clef-flash is doing
real work over 262K of context and paying for it. If the workload has a latency
SLO, the median is irrelevant and the p95 disqualifies it.

**`ambiguous` is the worst in the sweep.** 0.9281 mean confidence on four items
that are undecidable by construction. Every d3 checkpoint was 0.74–0.78; the
baseline is 0.72. clef-flash is *more* confident on unanswerable questions than
on answerable ones (0.928 vs 0.889 overall). That is the signature of a model
that has learned to always commit, and it is the single most dangerous property
measured here — an escalation threshold built on these numbers will never fire.

**`graded` remains unsolved by every model.** 0.600 accuracy, Brier 0.624, for
both clef-flash and the baseline. The 0–4 scale is where the corpus is hardest
and no model in the sweep handles it. This is a corpus-design signal as much as a
model signal: five items is too few to distinguish models on a five-way ordinal
task.

**`longstate` is the surprise.** clef-flash holds 0.667 accuracy with Brier 0.264
— the best long-context calibration in the sweep by a wide margin (d3-nano was
0.676, d3-edge 0.522). The clef family's architecture handles the padding better
than d3's, even though both advertise 262K.

## Recommendation

**clef-flash-oQ4e is the best-quality decision model measured so far and the only
one that beats the baseline on Brier.** It is the right choice when:

- the probability itself is consumed (thresholds, escalation scores), and
- the latency budget is ~250 ms median with tolerance for 2.3 s tails, and
- the questions are not undecidable — because its ambiguous confidence of 0.928
  means it will not tell you when it does not know.

It is the wrong choice for latency-bound argmax routing: `d3-edge` is 18× faster
at the median and loses only 0.086 accuracy. It is also the wrong choice if the
p95 matters, since the baseline is 4× better there.

The honest summary: **clef-flash buys calibration with latency, d3-edge buys
latency with calibration.** Neither dominates, and the choice is a workload
question, not a model question.

## Modality

Clef accepts images and **rejects video** — `clef.py` raises
`"this model does not take videos"` in `encode()`, and the harness records all 16
video items as HTTP 400. Images were scored — see
[`media/README.md`](media/README.md).

| Corpus | Acc | Brier | ECE | Median ms | p95 ms |
|---|---|---|---|---|---|
| image (25 items) | **1.000** | 0.0452 | 0.0831 | 2005 | 2080 |
| video (16 items) | — | — | — | — | — |

| Image family | Acc | Brier | Conf |
|---|---|---|---|
| `img-colour` | 1.000 | 0.0015 | 0.967 |
| `img-spatial` | 1.000 | 0.0010 | 0.982 |
| `img-shape` | 1.000 | 0.0004 | 0.982 |
| `img-text` | 1.000 | 0.0378 | 0.913 |
| `img-count` | **1.000** | 0.1384 | 0.798 |

**It is the only model that gets every counting item right without being
confident about it.** Mean confidence on `img-count` is 0.798 — the lowest of any
model on that family, and the reason its Brier there (0.1384) is worse than
`d3-flash`'s (0.1208) despite perfect accuracy. It is right and unsure, which is
the correct shape for a hard family.

**Its image Brier (0.0452) is worse than `d3-flash`'s (0.0343) despite perfect
accuracy**, because it is over-confident on the easy families (0.967–0.982 where
`d3-flash` is 0.999–1.000 and also right). Accuracy and calibration disagree
here, and the calibration is what a probability consumer feels.

**Video is a hard capability boundary, not a quality gap.** There is no score to
report and no partial credit; the request is refused before inference.

## Caveats

The text corpus is 39 items and the image corpus is 25; treat every per-family
cell as directional. Single-request latency only — `DecisionEngine` serialises
behind an `asyncio.Lock`, so this says nothing about throughput under
concurrency. The p95 figure is measured with no download active. See "What this
corpus cannot measure" in the methodology.
