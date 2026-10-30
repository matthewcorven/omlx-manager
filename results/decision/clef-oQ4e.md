# `Jundot/clef-oQ4e`

| | |
|---|---|
| Family | clef |
| Download | 17.5 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | clef-oQ4e | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | **0.943** | 0.857 |
| brier | **0.1003** | 0.1838 |
| logloss | **0.1711** | 0.2766 |
| ece | 0.0819 | **0.0496** |
| mean confidence | 0.9172 | 0.8879 |
| ambiguous confidence | **0.6755** | 0.7198 |
| latency median | 794.1 ms | **544.9 ms** |
| latency p95 | 8667.1 ms | **561.1 ms** |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | clef-oQ4e acc | clef-oQ4e brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.000 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.000 | 1.000 | 0.0001 |
| negation | 4 | 1.000 | 0.000 | 1.000 | 0.0161 |
| multilabel | 6 | 1.000 | 0.010 | 1.000 | **0.0012** |
| arithmetic | 6 | **1.000** | **0.066** | 0.833 | 0.2346 |
| longstate | 6 | **1.000** | **0.104** | 0.667 | 0.3006 |
| graded | 5 | 0.600 | **0.485** | 0.600 | 0.629 |

## What the numbers say

**`clef-oQ4e` matches `d3-flash` on accuracy (0.943) and is the second-best model
on Brier (0.1003 vs d3-flash's 0.0764).** It beats the 27B baseline on accuracy,
Brier and logloss. On quality it is a genuine win.

**But it is 5.8× slower than the baseline at the median and 15× slower at p95.**
794 ms median against 545 ms, and 8667 ms p95 against 561 ms. This is the slowest
model in the sweep by a wide margin — slower than the 27B chat model it is trying
to replace. **There is no workload where clef-oQ4e is the right choice over
d3-flash**: d3-flash is 5.2× faster at the median, 3× faster at p95, better on
Brier (0.0764 vs 0.1003), better on logloss (0.120 vs 0.171), and 0.4 GB larger.

**The 17 GB clef checkpoint buys nothing over the 6.6 GB one on quality.** Compare
`clef-flash-oQ4e`: accuracy 0.857 vs 0.943 (clef-oQ4e wins), Brier 0.1742 vs
0.1003 (clef-oQ4e wins), but latency 231.7 ms vs 794.1 ms (clef-flash wins 3.4×)
and p95 2322 ms vs 8667 ms (clef-flash wins 3.7×). The full clef is a quality
purchase at a 3.4× latency cost, and d3-flash dominates both.

**`longstate` is solved but not cleanly.** 1.000 accuracy with Brier 0.104 — the
worst Brier of any 1.000-accuracy cell in the sweep. It gets all six right but
with mean confidence 0.841, so the probabilities are soft. d3-flash does the same
six at Brier 0.006. Same accuracy, 17× better calibration.

**`ambiguous` confidence 0.6755 is the second-best in the sweep** (d3-flash 0.652,
baseline 0.720, clef-flash 0.928). The clef family's larger checkpoint does learn
to hedge, unlike its flash sibling.

**`graded` is again the only failure** — 0.600 accuracy, Brier 0.485, which is the
best graded Brier in the sweep. Still not separable from the baseline at 0.600.

## Recommendation

**Do not deploy `clef-oQ4e`.** It is dominated by `d3-flash` on every axis that
matters: quality (Brier 0.1003 vs 0.0764), median latency (794 vs 153 ms), p95
latency (8667 vs 2899 ms), and disk (17.5 vs 16.8 GB). There is no workload where
it is the correct choice.

It is also dominated by the 27B chat baseline on latency at every percentile,
which is the disqualifying fact: a decision model that is slower than the chat
model it replaces has no reason to exist unless it is dramatically better on
quality, and it is not.

The clef family's useful checkpoint is `clef-flash-oQ4e` (6.6 GB, 232 ms median,
Brier 0.1742) if a clef-family model is wanted for architectural reasons. For
quality, `d3-flash` is the answer.

## Modality

Clef accepts images and **rejects video** — `clef.py` raises
`"this model does not take videos"` in `encode()`, and the harness records all 16
video items as HTTP 400. Images were scored — see
[`media/README.md`](media/README.md).

| Corpus | Acc | Brier | ECE | Median ms | p95 ms |
|---|---|---|---|---|---|
| image (25 items) | **1.000** | **0.0006** | **0.0122** | 5650 | 6162 |
| video (16 items) | — | — | — | — | — |

| Image family | Acc | Brier | Conf |
|---|---|---|---|
| `img-colour` | 1.000 | 0.0001 | 0.991 |
| `img-spatial` | 1.000 | 0.0001 | 0.994 |
| `img-shape` | 1.000 | 0.0002 | 0.989 |
| `img-text` | 1.000 | 0.0001 | 0.994 |
| `img-count` | **1.000** | 0.0020 | 0.977 |

**This is the best image model in the sweep, and it is the only model that beats
the chat baseline on image quality.** Brier 0.0006 against the baseline's 0.0031
and `d3-flash`'s 0.0343; ECE 0.0122 against the baseline's 0.0207. Every family
is at or below 0.0020 Brier, including `img-count`, where every d3 checkpoint
except `clef-flash-oQ4e` misses at least one item.

**The text-sweep verdict inverts here.** In text it was dominated by `d3-flash`
on quality, latency and disk — 0.1003 Brier against 0.0764, 794 ms against
153 ms, 17.5 GB against 16.8 GB. On images it is 57× better on Brier and 3.2×
slower. That is a trade, not a domination, and the text table could not see it.

**The cost is real.** 5650 ms per image is 3.2× `d3-flash` and 3.4× the chat
baseline, and it is the slowest model in the image sweep. A workload that needs
one image classified per request cannot use it; a batch or offline workload
should.

**Video is a hard capability boundary, not a quality gap.** There is no score to
report and no partial credit; the request is refused before inference.

## Caveats

The text corpus is 39 items and the image corpus is 25; treat every per-family
cell as directional. Single-request latency only — `DecisionEngine` serialises
behind an `asyncio.Lock`, so this says nothing about throughput under
concurrency. The p95 figure is measured with no download active. See "What this
corpus cannot measure" in the methodology.
