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

## Modality

d3 accepts images and video. Both were scored — see
[`media/README.md`](media/README.md).

| Corpus | Acc | Brier | ECE | Median ms | p95 ms |
|---|---|---|---|---|---|
| image (25 items) | 0.818 | 0.2771 | 0.0853 | 267 | 272 |
| video (16 items) | 1.000 | 0.0539 | 0.1148 | 207 | 224 |

| Image family | Acc | Brier | Conf |
|---|---|---|---|
| `img-colour` | 1.000 | 0.0168 | 0.895 |
| `img-spatial` | 1.000 | 0.0001 | 0.995 |
| `img-shape` | 1.000 | 0.0003 | 0.988 |
| `img-count` | 0.667 | 0.4318 | 0.773 |
| `img-text` | **0.500** | 0.8594 | 0.932 |

| Video family | Acc | Brier | Conf |
|---|---|---|---|
| `vid-appear` | 1.000 | 0.0189 | 0.928 |
| `vid-colourchange` | 1.000 | 0.0003 | 0.988 |
| `vid-direction` | 1.000 | 0.0799 | 0.826 |
| `vid-motion` | 1.000 | 0.1166 | 0.799 |

**d3-lite is the only model that fails both `img-count` and `img-text`.** It
answers `false` to all four text questions at 0.92–0.94 confidence — the same
degenerate pattern as `d3-edge`, one rung up the ladder. It gets two of six
counting items wrong, and its confidence on those is 0.51–0.89, so it is at least
less certain than `d3-edge` while being wrong.

**Video is where it recovers, and the recovery is real.** It scores 1.000 on all
four video families, including `vid-motion` where `d3-edge` collapses. Its Brier
(0.0539) is 20× worse than `d3-nano`'s because it is under-confident rather than
wrong — mean confidence 0.799 on `vid-motion` against 0.995 for `d3-nano`. It
sees motion; it just does not trust the answer.

**The domination verdict is unchanged and now stronger.** In text it was
dominated by `d3-edge` on every axis. On images it is slower than `d3-edge`
(267 ms vs 211 ms) and more accurate (0.818 vs 0.773), which is a trade rather
than a domination — but `d3-nano` is 0.955 at 637 ms and 4.5 GB, and `d3-lite`'s
1.7 GB buys nothing that `d3-edge` does not already do faster. On video it is
strictly worse than `d3-nano` on every metric.

## Caveats

The text corpus is 39 items and the media corpora are 25 images and 16 clips;
treat every per-family cell as directional. Single-request latency only —
`DecisionEngine` serialises behind an `asyncio.Lock`, so this says nothing about
throughput under concurrency. See "What this corpus cannot measure" in the
methodology.
