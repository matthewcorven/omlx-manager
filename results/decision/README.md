# Decision models

Decision models answer typed questions with probabilities instead of generating
text. They are **not tuned** — there is no decode loop, no sampling, and no
reasoning budget. The process is in
[`docs/decision-model-methodology.md`](../../docs/decision-model-methodology.md);
the corpus and harness are `scripts/decision_corpus.py` and
`scripts/decision_eval.py`.

Every model is scored on the same 39-item labelled corpus, and every model is
compared against a **chat-model baseline** answering the same questions through
the same `/v1/systemone` endpoint. A decision model that loses to the baseline on
`brier` is not earning its residency.

## Results

| Model | Family | Size | Acc | Brier | ECE | Ambig conf | Latency (med) | Gates | Status |
|---|---|---|---|---|---|---|---|---|---|
| `vllm-sr/d3-edge` | d3 | 1.2 GB | 0.771 | 0.2514 | 0.116 | 0.770 | 12.9 ms | 0 | **PASS** — scored |
| `vllm-sr/d3-lite` | d3 | 1.7 GB | 0.714 | 0.2546 | 0.124 | 0.784 | 22.2 ms | 0 | **FAIL** — dominated by d3-edge |
| `vllm-sr/d3-nano` | d3 | 4.5 GB | 0.829 | 0.2346 | 0.132 | 0.740 | 37.9 ms | 0 | **PASS** — best d3 so far |
| `Jundot/clef-flash-oQ4e` | clef | 6.6 GB | 0.857 | **0.1742** | 0.090 | 0.928 | 231.7 ms | 0 | **PASS** — beats baseline Brier |
| `vllm-sr/d3-mini` | d3 | 9.1 GB | **0.914** | **0.1034** | 0.077 | 0.788 | 86.3 ms | 0 | **PASS** — best overall |
| `vllm-sr/d3-flash` | d3 | 16.8 GB | **0.943** | **0.0764** | 0.080 | **0.652** | 153.4 ms | 0 | **PASS** — best quality |
| `Jundot/clef-oQ4e` | clef | 17.5 GB | 0.943 | 0.1003 | 0.082 | 0.676 | 794.1 ms | 0 | **FAIL** — dominated by d3-flash |
| `openjev/openjev` | openjev | 54.7 GB | 0.857 | 0.1987 | 0.100 | 0.898 | 467.0 ms | 0 | **FAIL** — no better than baseline |
| `Qwen3.8-27B-oQ4e-mtp` | *baseline* | 15 GB | 0.857 | 0.1838 | 0.050 | 0.720 | 536 ms | 0 | reference |

Lower `brier` and `ece` are better. `brier` 0.25 is the score of a constant 0.5
guess. `ambiguous_confidence` 0.5 is honest; higher means the model asserts
confidence on undecidable items.

## The headline

**The sweep has a clear winner and a clear loser, and neither is the biggest
model.**

`vllm-sr/d3-flash` (16.8 GB) is the best-quality decision model measured:
accuracy 0.943, Brier 0.0764, logloss 0.120 — all three beat the 27B chat
baseline (0.857 / 0.1838 / 0.277) by wide margins, at 3.6× the median speed. It is
also the only model in the sweep that is *less* confident on undecidable items
(0.652) than the baseline (0.720), which is the property that makes a probability
usable for escalation.

`openjev/openjev` (54.7 GB) is the largest checkpoint in the sweep and does not
beat the baseline on any quality metric. 54.7 GB buys accuracy 0.857 — exactly the
baseline's — with a worse Brier (0.1987 vs 0.1838) and a 1.1× latency advantage
that is noise. Size is not the axis.

**The d3 family has a monotone size/quality curve above `d3-lite`:**

| Size | Model | Accuracy | Brier |
|---|---|---|---|
| 1.2 GB | d3-edge | 0.771 | 0.2514 |
| 1.7 GB | d3-lite | 0.714 | 0.2546 |
| 4.5 GB | d3-nano | 0.829 | 0.2346 |
| 9.1 GB | d3-mini | 0.914 | 0.1034 |
| 16.8 GB | d3-flash | 0.943 | 0.0764 |

`d3-lite` is the only inversion and it is dominated by `d3-edge` on every axis.
The 262K context window only becomes usable at 9 GB and up: `longstate` accuracy
is 0.333 / 0.167 / 0.500 / 1.000 / 1.000 across that ladder.

**Brier 0.25 is the score of a constant 0.5 guess.** `d3-edge` (0.2514) and
`d3-lite` (0.2546) are both *worse than guessing* despite 0.771 and 0.714
accuracy — they are confidently wrong. `d3-nano` (0.2346) is the first d3
checkpoint to clear the floor.

## Decision rule

| Workload | Model | Why |
|---|---|---|
| short, lexical, argmax only, tight p95 | `d3-edge` | 12.9 ms median, p95 109 ms, 0.771 acc |
| long context, arithmetic, probability consumed | `d3-mini` | 0.914 acc, 0.1034 Brier, 86 ms median |
| best quality, tail latency tolerable | `d3-flash` | 0.943 acc, 0.0764 Brier, honest ambiguity |
| calibrated probabilities, no long context | `clef-flash-oQ4e` | 0.1742 Brier, but 0.928 ambiguous conf |
| pure multi-label, short inputs | `openjev` | Brier 0.0000 on that family — verify on a larger corpus first |

Do not deploy `d3-lite` (dominated by `d3-edge`), `clef-oQ4e` (dominated by
`d3-flash` on quality, latency and disk), or `openjev` (no quality win at 54.7 GB).

**`graded` (0–4 ordinal) is unsolved by every model in the sweep** — 0.400–0.600
accuracy across all eight checkpoints and the baseline. Five items cannot separate
models on a five-way ordinal scale; that family needs a larger corpus before any
conclusion is drawn.

## Not exercisable on 0.7.3rc1

| Model | Size | Cause |
|---|---|---|
| `LiquidAI/d1-2B` | 3.9 GB | `omlx/engine/decision.py` maps only `clef`/`openjev`/`d3`; `omlx/models/d1.py` absent from 0.7.3rc1 |
| `LiquidAI/d1-Omni-2B` | 4.4 GB | same |
| `LiquidAI/d1-2B-MLX-8bit` | 2.2 GB | same |

d1 support is in `main` (PR #4937) but not in this release. These are recorded as
blocked rather than scored — a score from a build that cannot load the checkpoint
would be fabricated.

## Per-model write-ups

- [`d3-edge.md`](d3-edge.md)
- [`d3-lite.md`](d3-lite.md)
- [`d3-nano.md`](d3-nano.md)
- [`clef-flash-oQ4e.md`](clef-flash-oQ4e.md)
- [`d3-mini.md`](d3-mini.md)
- [`d3-flash.md`](d3-flash.md)
- [`clef-oQ4e.md`](clef-oQ4e.md)
- [`openjev.md`](openjev.md)
