---
name: omlx-decision-eval
description: Evaluate an oMLX decision model (Clef, OpenJev, Decision 3.0 d3-*, LiquidAI d1-*) against a labelled corpus. Use when a decision model needs a baseline, when comparing decision models to each other or to a chat-model baseline, when probabilities look wrong, or when deciding whether a decision model is worth its residency. Covers the corpus and what it cannot measure, the scoring harness, the four gates, determinism, and the knobs that actually exist.
---

# Evaluating a decision model

A decision model answers a typed question about a state with a **probability
distribution over options**. It does not generate text. Clef, OpenJev, Decision
3.0 (`d3-*`) and LiquidAI `d1-*` are served through `POST /v1/systemone` and
`POST /v1/decisions`.

Decision models cannot be tuned the way a text model is. There is no decode loop,
no sampling, and no reasoning budget — `engine_pool.py` explicitly skips
speculative setup when `engine_type == "decision"` because "decision models never
decode". The axes that matter are **accuracy**, **calibration**, **latency** and
**capability envelope**, and calibration is the one you cannot eyeball.

So the deliverable is not a `final.json` of tok/s. It is a **scored baseline
against ground truth**, plus a comparison against a chat model answering the same
questions through the same endpoint.

Full process: [`docs/decision-model-methodology.md`](../../../docs/decision-model-methodology.md).

## The one rule that invalidates everything else

**A score is only meaningful if the answer is a real distribution.** Four gates
run before any number is trusted:

| Gate | Catches | Failure looks like |
|---|---|---|
| **error** | the request never produced an answer | HTTP 400 / 500 |
| **schema** | answer shape does not match the question type | `noul` answer with no `noul` key; `choice` keys not matching criteria |
| **degenerate** | probabilities are not a distribution | sum ≠ 1, NaN, negative |
| **truncation** | the state did not fit | HTTP **413** / `DecisionContextLengthError` |

The harness exits non-zero on any gate failure, so a gate failure cannot be
mistaken for a low score.

## Determinism comes first

Decision models are deterministic. The same request must return bit-identical
probabilities. Run `--determinism` before believing anything:

```sh
python3 scripts/decision_eval.py --model <id> --determinism
```

**Variance is an engine bug, not noise**, and it invalidates every other number
in the run.

## The chat-model baseline is mandatory

`/v1/systemone` does not require a decision model. For a non-decision model oMLX
answers the same questions from **next-token letter probabilities**
(`_chat_model_decisions` in `server.py`). That is the baseline that matters: a
decision model is only worth its residency if it beats a chat model already on
disk.

```sh
python3 scripts/decision_eval.py --model vllm-sr/d3-edge \
    --baseline Qwen3.8-27B-oQ4e-mtp --out results/decision/d3-edge.json
```

Measured on this box across all eight servable checkpoints, the baseline is not a
formality — it is the discriminator. `d3-edge` is 40× faster (12.9 ms vs 536 ms
median) and **loses on every quality metric** (brier 0.2514 vs 0.1838); without
the baseline its 0.771 accuracy looks like a result. `clef-oQ4e` and `openjev`
look respectable in isolation and are both dominated once compared. Only
`d3-mini` (brier 0.1034) and `d3-flash` (0.0764) beat the baseline outright.

The full sweep is in `results/decision/README.md`; the decision rule it produced
is: short/lexical/argmax → `d3-edge`; long-context or probability-consuming →
`d3-mini`; best quality with tail latency tolerated → `d3-flash`.

## Metrics

| Metric | Meaning | Reference |
|---|---|---|
| `accuracy` | argmax equals truth | 0.5 on balanced binary by chance |
| `brier` | mean squared error of p(truth) | **0.25 = constant 0.5 guess** |
| `logloss` | mean −log p(truth) | punishes confident errors hardest |
| `ece` | expected calibration error, 10 bins | 0 = perfectly calibrated |
| `ambiguous_confidence` | p(chosen) on undecidable items | **0.5 = honest** |
| `latency_ms` | median and p95 per request | — |

`brier` and `ece` are the metrics that matter. Accuracy alone cannot tell a model
that knows the answer from one that always says yes on a balanced corpus.

## The corpus

`scripts/decision_corpus.py` generates 39 seeded items in 8 families:

| Family | n | Isolates |
|---|---|---|
| `sentiment` | 4 | the floor — below 1.0 here is a real fault |
| `arithmetic` | 6 | verifiable answer, no lexical shortcut |
| `negation` | 4 | polarity flips |
| `ordering` | 4 | comparison against a threshold |
| `multilabel` | 6 | choice among 4 options |
| `graded` | 5 | score on an ordered 5-level scale |
| `longstate` | 6 | arithmetic buried in padding — a drop is a context fault |
| `ambiguous` | 4 | undecidable; **confidence here is the signal** |

Regenerate with `python3 scripts/decision_corpus.py --out results/decision/corpus.json`.
Never hand-edit the corpus — regenerate so ground truth stays reproducible.

### The media corpora

Text is one of three. Every checkpoint in the sweep carries a vision tower, so a
text-only score says nothing about the modality the model shipped with.

`scripts/decision_media_corpus.py` generates 25 images and 16 clips from the same
seed:

| Family | n | Isolates |
|---|---|---|
| `img-count` | 6 | counting objects — the only image family that separates the d3 ladder |
| `img-colour` | 4 | colour identification |
| `img-spatial` | 4 | left/right/above/below |
| `img-text` | 4 | reading a rendered word |
| `img-shape` | 4 | shape identification |
| `img-ambiguous` | 3 | **defective** — see below |
| `vid-motion` | 4 | static vs moving; **the clips share their first frame** |
| `vid-direction` | 4 | direction of travel |
| `vid-appear` | 4 | object appears mid-clip; first half identical |
| `vid-colourchange` | 4 | colour changes mid-clip; first frame identical |

The video families are built so a single frame cannot answer them. d3 samples at
2 fps and caps at 32 frames, so "does it use the temporal axis" is a real
question with a real failure mode.

**`img-ambiguous` does not work and its numbers must not be cited.** Coarse noise
with no object in it is answerable, and every model answers it at 0.98–1.00
confidence. A working version needs genuinely undecidable images — occluded, or
ambiguous between two readings.

Regenerate with the app-bundle interpreter, not the stock `python3`:

```sh
/Applications/oMLX.app/Contents/MacOS/omlx-cluster-python \
    scripts/decision_media_corpus.py --out results/decision/media
```

The stock interpreter has no Pillow and no OpenCV. The corpus is committed
(1.3 MB) so a clone does not need the app bundle to read it.

## Knobs: what is real

### Correctness preconditions — not knobs

| Setting | Required | Why |
|---|---|---|
| `model_type_override` | `"decision"` | Otherwise the checkpoint loads as a chat model and the head is never used |
| context | within the model's own limit | Clef `MAX_LENGTH = 16384`; OpenJev/d3 use backbone `max_position_embeddings` |
| `criteria` shape | per family | Each family validates differently and rejects with 400 |

### Real knobs

`max_context_window` (lower it to fail fast), `gpu_power_limit_w` (latency only),
`moe_expert_offload_*` (only if it does not fit resident).

### Inert — do not sweep

`enable_thinking`, `mtp_enabled`, `dflash_enabled`, `specprefill_enabled`,
`temperature`, `top_p`, `top_k`, `turboquant_kv_enabled`. No decode, no sampling —
sweeping these produces identical numbers and wastes a benchmark slot.

## Per-family capability matrix

| | Clef | OpenJev | d3 | d1 |
|---|---|---|---|---|
| In 0.7.3rc1 | yes | yes | yes | **no** |
| Max context | 16384 | backbone | backbone | `text_config.max_position_embeddings` |
| `noul` criteria | object, defaults merged | object, optional | object, **only** `"true"`/`"false"` | — |
| `choice` criteria | non-empty object | non-empty object | 1–255 options | — |
| `score` criteria | non-empty array | array, **≥ 2** | array, **2–10**, distinct | — |
| Images | yes, multiple | **at most one** | yes, multiple | yes |
| Video | rejected (400) | rejected (400) | **yes** (≤ 300 s, 4–32 frames) | rejected |
| `truncate` | **honoured** | ignored (413) | ignored | ignored |

**d1 is not servable on 0.7.3rc1.** `omlx/engine/decision.py` maps only
`{"clef", "openjev", "d3"}` and `omlx/models/d1.py` is absent. Support is in
`main` (PR #4937). Record d1 checkpoints as **not exercisable**, never score them
from a build that cannot load them.

## Procedure

1. `python3 scripts/decision_corpus.py --out results/decision/corpus.json`
2. `./scripts/disk_guard.sh <GB>` before every download.
3. Download **one** checkpoint — an active download skews latency up to 4×.
4. Confirm `engine_type == "decision"` via `/admin/api/models`. If not, stop.
5. `--determinism` first. Gate failure or instability ends the evaluation.
6. Score text, then images, then video, then the baseline — same session.
7. Write `results/decision/<name>.md` with a **Modality** section, and add rows
   to `results/decision/README.md` and `results/decision/media/README.md`.
8. Shuttle the checkpoint to `/Volumes/NVMe/omlx-models` once written up.

```sh
python3 scripts/decision_eval.py --model <id> --out results/decision/<name>.json
python3 scripts/decision_eval.py --model <id> --modality image \
    --corpus results/decision/media/manifest.json --out /tmp/img-<name>.json
python3 scripts/decision_eval.py --model <id> --modality video \
    --corpus results/decision/media/manifest.json --out /tmp/vid-<name>.json
```

Clef and OpenJev reject video with HTTP 400 `"this model does not take videos"`.
Record that as a capability boundary, not a failure. There is no video baseline —
the chat path has no video route, and the harness writes
`{"supported": false}` rather than skipping silently.

## Read the family table, not the aggregate

**A well-formed distribution can still be a blind answer.** `d3-edge` answers
`true` to all six `img-count` items and `false` to all four `img-text` items, at
0.68–0.99 confidence. The `degenerate` gate does not fire, because each answer is
a valid distribution. Only the per-family breakdown shows it.

Before blaming a model for a family result, **validate the family against a model
known to be capable.** The `img-text` family was first drawn at 96 px and made
`d3-flash` look broken (0.59 on a present word); at 200 px it separates 0.89 from
0.01. The same check cleared `vid-motion`: `d3-flash` scores 0.966/0.002 on the
same clips, so `d3-edge`'s 0.500 is real.

## What these corpora cannot measure

State this in every write-up:

- **Open-domain judgement.** Every item is decidable by inspection.
- **Long-context reasoning.** `longstate` tests that a long state does not
  *break* the answer, not that a fact can be found in 100K tokens.
- **Real photographs and real video.** The media corpora are drawn and rendered.
  Synthetic geometry and synthetic text are a floor, not a ceiling.
- **Video beyond 4 s and 4 families.** d3 samples at 2 fps, capped at 32 frames.
- **Cross-image reasoning.** OpenJev takes at most one image, so the corpus never
  sends more than one.
- **Throughput under concurrency.** `DecisionEngine` serialises behind an
  `asyncio.Lock`; this is single-request latency.
- **Instruction-following.** Instructions are short and direct.
