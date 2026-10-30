# `vllm-sr/d3-mini`

| | |
|---|---|
| Family | d3 (Decision 3.0) |
| Download | 9.1 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | d3-mini | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | **0.914** | 0.857 |
| brier | **0.1034** | 0.1838 |
| logloss | **0.1500** | 0.2766 |
| ece | 0.0766 | **0.0496** |
| mean confidence | 0.9447 | 0.8879 |
| ambiguous confidence | 0.7875 | **0.7198** |
| latency median | **86.3 ms** | 524.6 ms |
| latency p95 | 1148.6 ms | **593.9 ms** |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | d3-mini acc | d3-mini brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.000 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.000 | 1.000 | 0.0001 |
| negation | 4 | 1.000 | 0.000 | 1.000 | 0.0161 |
| multilabel | 6 | 1.000 | 0.015 | 1.000 | **0.0012** |
| arithmetic | 6 | **1.000** | **0.000** | 0.833 | 0.2346 |
| longstate | 6 | **1.000** | **0.004** | 0.667 | 0.3006 |
| graded | 5 | 0.400 | 0.700 | **0.600** | **0.629** |

## What the numbers say

**This is the first decision model in the sweep that clearly beats the chat
baseline on quality.** Accuracy 0.914 vs 0.857, Brier 0.1034 vs 0.1838 (a 44%
reduction), logloss 0.150 vs 0.277. It is not a narrow win like clef-flash's
Brier-only edge — d3-mini wins on accuracy, Brier and logloss simultaneously, at
6× the median speed.

**`longstate` and `arithmetic` flip completely.** d3-mini scores 1.000/0.004 on
longstate and 1.000/0.000 on arithmetic. Every smaller d3 checkpoint failed both:
d3-edge 0.333/0.522 and 0.667/0.539, d3-lite 0.167/0.514 and 0.667/0.448,
d3-nano 0.500/0.676 and 0.833/0.261. The baseline manages 0.667/0.301 and
0.833/0.235. **The 9 GB checkpoint is the first d3 model that can actually use its
262K context window** — the smaller ones advertise the window and cannot read it.

**`graded` is now the only failure, and it is worse than the baseline.** 0.400
accuracy, Brier 0.700 — the worst graded cell in the sweep, worse than d3-lite's
0.586. d3-mini is confidently wrong on the 0–4 ordinal scale (mean confidence
0.708 against 0.400 accuracy). Every model in the sweep fails `graded`; d3-mini
fails it hardest. This is the one family where the corpus needs more items before
any conclusion is drawn.

**ECE 0.0766 is still 1.5× the baseline's 0.0496**, and mean confidence 0.945
against 0.914 accuracy is a 3-point overconfidence gap. The probabilities are
good enough to consume but not as good as the baseline's. `ambiguous` confidence
0.7875 is the second-best in the sweep (clef-flash 0.928, d3-nano 0.740, baseline
0.720) — it is overconfident on undecidable items but not catastrophically so.

**The p95 is still worse than the baseline** (1149 ms vs 594 ms), same pattern as
clef-flash. The median is 6× better; the tail is 2× worse. Long-context items
dominate the tail for every decision model measured.

## Recommendation

**`d3-mini` is the recommended decision model for this machine.** It is the only
checkpoint in the sweep that beats the 27B chat baseline on accuracy, Brier and
logloss at the same time, and it does so at 86 ms median — 6× faster than the
baseline and 2.7× faster than clef-flash.

Use it for:

- **calibrated probability consumption** — thresholds, escalation scores, anything
  that multiplies probabilities. Brier 0.1034 is a real number, not a coin flip.
- **long-context decision tasks** — it is the only d3 checkpoint that holds
  accuracy at 262K of padding.
- **arithmetic and state tracking** — 1.000 on both, where every smaller d3 model
  and the baseline fail.

Do not use it for:

- **ordinal 0–4 grading** — 0.400 accuracy, Brier 0.700. Use the baseline (0.600)
  or fix the corpus first.
- **hard p95 latency SLOs** — 1149 ms p95 is worse than the baseline's 594 ms.

If the workload is pure argmax routing with no long context, `d3-edge` at 12.9 ms
is still the right answer and d3-mini's quality advantage is wasted. The decision
rule is: **short and lexical → d3-edge; long, arithmetic, or probability-consuming
→ d3-mini.**

## Modality

d3 accepts images and video. Both were scored — see
[`media/README.md`](media/README.md).

| Corpus | Acc | Brier | ECE | Median ms | p95 ms |
|---|---|---|---|---|---|
| image (25 items) | 0.955 | 0.0701 | 0.0606 | 1038 | 1066 |
| video (16 items) | **1.000** | **0.0000** | 0.0018 | 859 | 906 |

| Image family | Acc | Brier | Conf |
|---|---|---|---|
| `img-colour` | 1.000 | 0.0000 | 0.999 |
| `img-spatial` | 1.000 | 0.0000 | 0.999 |
| `img-shape` | 1.000 | 0.0000 | 1.000 |
| `img-text` | 1.000 | 0.0342 | 0.917 |
| `img-count` | 0.833 | 0.2344 | 0.945 |

| Video family | Acc | Brier | Conf |
|---|---|---|---|
| `vid-appear` | 1.000 | 0.0000 | 0.999 |
| `vid-colourchange` | 1.000 | 0.0000 | 0.998 |
| `vid-direction` | 1.000 | 0.0000 | 0.999 |
| `vid-motion` | 1.000 | 0.0000 | 0.997 |

**d3-mini is the best image model per GB in the sweep.** 0.955 accuracy and
0.0701 Brier at 9.1 GB and 1038 ms — `d3-flash` needs 16.8 GB and 1743 ms for the
same accuracy and a better Brier (0.0343), and `clef-oQ4e` needs 17.5 GB and
5650 ms for a much better one (0.0006). If the constraint is disk, this is the
image model.

**Video is perfect and cheap.** Brier 0.0000 across all 16 items at 859 ms, which
is 1.7× `d3-flash`'s speed for the same result. `d3-nano` is faster still (446 ms)
at the same Brier, so on video alone `d3-nano` wins; `d3-mini` wins when the same
checkpoint must also handle text, where it is 0.914 against `d3-nano`'s 0.829.

**Its one image miss is the counting distractor**, same as every model above
`d3-lite`. Its confidence on that family (0.945) is the highest of the four that
miss it, so it is the most overconfident about the one thing it gets wrong.

## Caveats

The text corpus is 39 items and the media corpora are 25 images and 16 clips;
treat every per-family cell as directional. The `graded` family has only 5 items.
Single-request latency only — `DecisionEngine` serialises behind an
`asyncio.Lock`, so this says nothing about throughput under concurrency. See
"What this corpus cannot measure" in the methodology.
