# `vllm-sr/d3-nano`

| | |
|---|---|
| Family | d3 (Decision 3.0) |
| Download | 4.5 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 (backbone `max_position_embeddings`) |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | d3-nano | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | 0.829 | **0.857** |
| brier | 0.2346 | **0.1838** |
| logloss | 0.3562 | **0.2766** |
| ece | 0.1315 | **0.0496** |
| mean confidence | 0.8940 | 0.8879 |
| ambiguous confidence | 0.7398 | 0.7198 |
| latency median | **37.9 ms** | 519.3 ms |
| latency p95 | 654.5 ms | **544.2 ms** |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | d3-nano acc | d3-nano brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.000 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.000 | 1.000 | 0.0001 |
| multilabel | 6 | 1.000 | 0.000 | 1.000 | 0.0012 |
| negation | 4 | 1.000 | 0.001 | 1.000 | 0.0161 |
| arithmetic | 6 | 0.833 | 0.261 | 0.833 | **0.235** |
| graded | 5 | 0.600 | **0.516** | 0.600 | 0.629 |
| longstate | 6 | 0.500 | 0.676 | **0.667** | **0.301** |

## What the numbers say

**`d3-nano` is the first d3 checkpoint that is actually better than its smaller
siblings.** Accuracy 0.829 vs 0.771 (`d3-edge`) and 0.714 (`d3-lite`); Brier
0.2346 vs 0.2514 and 0.2546. It is the first d3 model to beat the constant-0.5
Brier floor of 0.25. The size ordering finally holds: 1.2 GB → 1.7 GB → 4.5 GB
gives 0.771 → 0.714 → 0.829.

**But it is still not calibrated.** ECE 0.1315 is the *worst* of the three d3
checkpoints (0.116, 0.124, 0.132) and 2.6× the baseline's 0.0496. Mean
confidence 0.894 against 0.829 accuracy is a 6.5-point overconfidence gap. The
Brier improvement over `d3-edge` comes from being right more often, not from
reporting better numbers.

**`longstate` is where it breaks, and it breaks loudly.** 0.500 accuracy with
Brier 0.676 — the worst single cell in the sweep. It gets 3 of 6 right and is
confident about all of them (mean confidence 0.768). `noul-longstate-05` is
answered `true` at p=0.941 and is false. Compare `d3-edge` at 0.333/0.522 and
`d3-lite` at 0.167/0.514: accuracy improves with size but the *calibration* on
long context gets worse, because the model stops hedging as it gets bigger.

**`graded` is the one family where d3 beats the baseline on Brier** (0.516 vs
0.629) at equal accuracy (0.600). Both are poor on the 0–4 scale; d3-nano is
merely less confidently wrong. This is the only quality cell where a d3
checkpoint wins outright.

**Latency p95 is now worse than the baseline** (654 ms vs 544 ms). The median is
still 13.7× better, but the tail has crossed over. At 4.5 GB the model no longer
fits the "always fast" story — the p95 is dominated by the longstate items, where
the baseline's p95 also spikes.

## Recommendation

**`d3-nano` is the best d3 checkpoint measured so far and the only one worth
considering.** It is the smallest d3 model that beats the 0.25 Brier floor, and it
matches the 27B baseline on `arithmetic` and `graded` accuracy at 1/14th the
median latency.

Use it for **argmax-only classification** — routing, intent buckets, yes/no gates
— where the answer is short and lexical. Do not use it for long-context state
tracking (0.500 accuracy, 0.676 Brier) and do not consume its probabilities
without recalibration: ECE 0.132 means a stated 0.9 is closer to 0.77 in practice.

If calibrated probabilities are required, the 27B baseline remains the correct
choice. The honest middle is d3-nano for the argmax plus a recalibration layer
(Platt or isotonic on a held-out split) if the number itself is consumed.

## Modality

d3 accepts images and video. Both were scored — see
[`media/README.md`](media/README.md).

| Corpus | Acc | Brier | ECE | Median ms | p95 ms |
|---|---|---|---|---|---|
| image (25 items) | 0.955 | 0.0876 | 0.0540 | 637 | 664 |
| video (16 items) | **1.000** | **0.0000** | 0.0035 | 446 | 461 |

| Image family | Acc | Brier | Conf |
|---|---|---|---|
| `img-colour` | 1.000 | 0.0001 | 0.991 |
| `img-spatial` | 1.000 | 0.0000 | 0.999 |
| `img-shape` | 1.000 | 0.0000 | 0.998 |
| `img-text` | 1.000 | 0.0617 | 0.875 |
| `img-count` | 0.833 | 0.2801 | 0.930 |

| Video family | Acc | Brier | Conf |
|---|---|---|---|
| `vid-appear` | 1.000 | 0.0000 | 0.997 |
| `vid-colourchange` | 1.000 | 0.0000 | 0.997 |
| `vid-direction` | 1.000 | 0.0000 | 0.997 |
| `vid-motion` | 1.000 | 0.0001 | 0.995 |

**d3-nano is the best video model in the sweep and the best value on images.**
Brier 0.0000 on video is not a rounding artefact — it is 16 items, all correct,
all at 0.995+ confidence. On images it is 0.955 accuracy at 637 ms and 4.5 GB,
which is the best accuracy-per-GB in the sweep: `d3-flash` needs 16.8 GB and
1743 ms to reach the same 0.955.

**Counting is its only image weakness**, and it is the same one-item miss as
`d3-mini`, `d3-flash` and `openjev` — the off-by-one distractor. Its Brier on
that family (0.2801) is the worst of the four because it is confident (0.930)
while wrong, where `d3-flash` is less so.

**This is the model the text sweep under-rated.** In text it was "best d3 so
far" at 0.829 accuracy, mid-ladder. On media it is the only checkpoint that is
both perfect on video and near-perfect on images, at 4.5 GB.

## Caveats

The text corpus is 39 items and the media corpora are 25 images and 16 clips;
treat every per-family cell as directional. Single-request latency only —
`DecisionEngine` serialises behind an `asyncio.Lock`, so this says nothing about
throughput under concurrency. The p95 figures are measured while no download was
active; an active download inflates latency up to 4×. See "What this corpus
cannot measure" in the methodology.
