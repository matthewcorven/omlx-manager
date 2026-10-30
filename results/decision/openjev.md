# `openjev/openjev`

| | |
|---|---|
| Family | openjev |
| Download | 54.7 GB |
| `engine_type` | `decision` (confirmed via `/admin/api/models`) |
| Context | 262144 |
| Scored | 2026-10-29, oMLX 0.7.3rc1 |

## Result

| Metric | openjev | baseline `Qwen3.8-27B-oQ4e-mtp` |
|---|---|---|
| accuracy | 0.857 | 0.857 |
| brier | 0.1987 | **0.1838** |
| logloss | 0.3412 | **0.2766** |
| ece | 0.0998 | **0.0496** |
| mean confidence | 0.9570 | 0.8879 |
| ambiguous confidence | 0.8976 | **0.7198** |
| latency median | **467.0 ms** | 526.5 ms |
| latency p95 | **7468.5 ms** | 8526.5 ms |
| gate failures | 0 | 0 |
| determinism | **STABLE** | — |

## By family

| Family | n | openjev acc | openjev brier | baseline acc | baseline brier |
|---|---|---|---|---|---|
| sentiment | 4 | 1.000 | 0.000 | 1.000 | 0.0003 |
| ordering | 4 | 1.000 | 0.000 | 1.000 | 0.0001 |
| multilabel | 6 | 1.000 | **0.000** | 1.000 | 0.0012 |
| negation | 4 | 1.000 | 0.001 | 1.000 | 0.0161 |
| arithmetic | 6 | 0.833 | 0.307 | 0.833 | **0.235** |
| graded | 5 | 0.600 | **0.540** | 0.600 | 0.629 |
| longstate | 6 | 0.667 | 0.401 | 0.667 | **0.301** |

## What the numbers say

**`openjev` is the largest checkpoint in the sweep and it does not win.** 54.7 GB
buys accuracy 0.857 — exactly the baseline's — with Brier 0.1987, which is *worse*
than the baseline's 0.1838. It is the only model in the sweep that is both
enormous and no better than the chat model it replaces.

**It is the most overconfident model measured.** Mean confidence 0.957 against
0.857 accuracy is a 10-point gap, the largest in the sweep. Ambiguous confidence
0.8976 is second only to clef-flash's 0.9281. On the four undecidable items it
asserts 0.90 confidence. This is a model that has learned to always commit hard.

**`longstate` is not solved at 54.7 GB.** 0.667 accuracy with Brier 0.401 — worse
than the baseline's 0.301 and far worse than d3-mini's 0.004 at 9.1 GB. The
openjev architecture does not use its 262K window as well as d3 does, and no
amount of parameters fixes it here.

**`arithmetic` is also worse than the baseline** (Brier 0.307 vs 0.235) at equal
accuracy. Same pattern: right answers, worse numbers.

**The latency story is the only place it is not last.** 467 ms median against the
baseline's 527 ms — a 1.1× advantage, which is noise. p95 7469 ms vs 8527 ms is
also within noise. **openjev is not meaningfully faster than the 27B chat model.**

**`multilabel` Brier 0.0000 is the single best cell in the sweep** — perfect
probabilities on six items. That is the one thing openjev does better than
everything else, and it is not enough to justify 54.7 GB.

## Recommendation

**Do not deploy `openjev`.** It is dominated on quality by `d3-flash` (Brier
0.0764 vs 0.1987 at 16.8 GB) and `d3-mini` (0.1034 at 9.1 GB), dominated on
latency by every d3 checkpoint, and it is not faster than the chat baseline it
would replace. At 54.7 GB it is also the single largest thing in the sweep.

The one honest use case: if a workload is pure multi-label classification with
short inputs and the probabilities are consumed, openjev's 0.0000 Brier on that
family is genuinely the best measured. That is a narrow enough case that it should
be verified on a larger corpus before any deployment decision.

## Caveats

Text-only corpus. OpenJev accepts at most one image per request and none of that
is scored here. Single-request latency only — `DecisionEngine` serialises behind
an `asyncio.Lock`, so this says nothing about throughput under concurrency. The
p95 figure is measured with no download active; the 7.5 s tail is dominated by
the longstate items. See "What this corpus cannot measure" in the methodology.
