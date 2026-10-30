# Decision models on images and video

The text sweep in `results/decision/` answers whether a decision model's
probabilities are right about words. It says nothing about pixels, and every
checkpoint in that sweep carries a vision tower, so the question was open. This
directory closes it.

Two corpora, both synthetic and both seeded, so ground truth is known by
construction and the files regenerate byte-identically:

| Corpus | Items | Families | Scored by |
|---|---|---|---|
| image | 25 | `img-count`, `img-colour`, `img-spatial`, `img-text`, `img-shape`, `img-ambiguous` | all 8 checkpoints + chat baseline |
| video | 16 | `vid-motion`, `vid-direction`, `vid-appear`, `vid-colourchange` | d3 only |

Regenerate with:

```sh
"$OMLX_PYTHON" scripts/decision_media_corpus.py --out results/decision/media
```

The stock `python3` cannot run this: it has no Pillow and no OpenCV. The app
bundle's interpreter is the only one on this machine with both. See
[Development](../../../README.md#development) for the variable defaults.

## Headline

**Vision is not a differentiator on still images, and it is a hard capability
cliff on video.**

On images, six of the eight checkpoints and the chat baseline all land at
0.955–1.000 accuracy. The two that do not are the two smallest d3 checkpoints,
and they fail in a specific, diagnosable way rather than degrading gracefully.
On video, the field collapses to four models: Clef and OpenJev reject the
modality outright, and of the four d3 checkpoints that accept it, `d3-edge`
cannot see motion at all.

The single most useful number here is not accuracy. It is that **`d3-edge`
answers "true" to all six counting questions and "false" to all four
motion questions** — a constant answer per family, at 0.80–0.97 confidence. It
is not uncertain; it is blind and confident. That is exactly the failure the
`degenerate` gate exists to catch, and it is why the gate is checked before any
score is read.

## Image results

25 items, 22 scored, 3 ambiguous. Sorted by Brier.

| Model | Acc | Brier | ECE | Ambig conf | Median ms | p95 ms | Gates |
|---|---|---|---|---|---|---|---|
| `Jundot/clef-oQ4e` | 1.000 | 0.0006 | 0.0122 | 0.995 | 5650 | 6162 | 0 |
| `Qwen3.8-27B-oQ4e-mtp` *(baseline)* | 1.000 | 0.0031 | 0.0207 | 0.980 | 5842 | 6062 | 0 |
| `vllm-sr/d3-flash` | 0.955 | 0.0343 | 0.0414 | 0.999 | 1743 | 1810 | 0 |
| `Jundot/clef-flash-oQ4e` | 1.000 | 0.0452 | 0.0831 | 0.994 | 2005 | 2080 | 0 |
| `vllm-sr/d3-mini` | 0.955 | 0.0701 | 0.0606 | 1.000 | 1038 | 1066 | 0 |
| `openjev/openjev` | 0.955 | 0.0785 | 0.0418 | 0.989 | 5226 | 5335 | 0 |
| `vllm-sr/d3-nano` | 0.955 | 0.0876 | 0.0540 | 0.994 | 637 | 664 | 0 |
| `vllm-sr/d3-lite` | 0.818 | 0.2771 | 0.0853 | 0.966 | 267 | 272 | 0 |
| `vllm-sr/d3-edge` | 0.773 | 0.3260 | 0.1309 | 0.980 | 211 | 228 | 0 |

### By family

| Model | count | colour | spatial | text | shape |
|---|---|---|---|---|---|
| `clef-oQ4e` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| *baseline* | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-flash` | 0.833 | 1.000 | 1.000 | 1.000 | 1.000 |
| `clef-flash-oQ4e` | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-mini` | 0.833 | 1.000 | 1.000 | 1.000 | 1.000 |
| `openjev` | 0.833 | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-nano` | 0.833 | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-lite` | 0.667 | 1.000 | 1.000 | 0.500 | 1.000 |
| `d3-edge` | 0.500 | 1.000 | 1.000 | 0.500 | 1.000 |

**Counting is the only family that separates the d3 ladder.** Every model above
`d3-lite` gets exactly one of six count items wrong, and it is the same item
class: the off-by-one distractors. `d3-edge` gets three of six wrong and
`d3-lite` two of six. Nothing else in the image corpus discriminates.

**`img-text` is a resolution cliff, not a capability gradient.** At the 96 px
font the corpus originally used, `d3-edge` scored 0.500 and `d3-flash` only
reached 0.59 on a present word — the items were measuring legibility. At 200 px
every model except `d3-edge` and `d3-lite` reads perfectly. The corpus now uses
200 px, and the two that still fail are failing to read, not failing to see.

**`img-ambiguous` is the corpus's weakest family.** Every model, including the
baseline, answers the no-information images at 0.98–1.00 confidence. The images
are coarse noise with no object in them, and every model is certain there is no
dog. That is arguably correct behaviour — the question is answerable and the
answer is "no" — so this family is not measuring what it was meant to measure.
It is recorded as a corpus defect, not a model result, and it should be replaced
with genuinely undecidable images (occluded, ambiguous between two readings)
before any calibration claim is drawn from it.

## Video results

16 items, all scored. d3 only.

| Model | Acc | Brier | ECE | Median ms | p95 ms | Gates |
|---|---|---|---|---|---|---|
| `vllm-sr/d3-mini` | 1.000 | 0.0000 | 0.0018 | 859 | 906 | 0 |
| `vllm-sr/d3-nano` | 1.000 | 0.0000 | 0.0035 | 446 | 461 | 0 |
| `vllm-sr/d3-flash` | 1.000 | 0.0003 | 0.0063 | 1444 | 1519 | 0 |
| `vllm-sr/d3-lite` | 1.000 | 0.0539 | 0.1148 | 207 | 224 | 0 |
| `vllm-sr/d3-edge` | 0.812 | 0.3642 | 0.2655 | 159 | 162 | 0 |
| `Jundot/clef-oQ4e` | — | — | — | — | — | 16 |
| `Jundot/clef-flash-oQ4e` | — | — | — | — | — | 16 |
| `openjev/openjev` | — | — | — | — | — | 16 |

**There is no baseline row, and that is not an omission.** The chat-model path
rejects video outright — `decisions_request` raises `"this model does not take
videos"` — so no chat model can be scored on this corpus. The harness records
`{"supported": false}` in the result file so the absence is visible rather than
looking like a forgotten run.

**Clef and OpenJev fail all 16 items with the same 400.** `clef.py` rejects
`videos` in `encode()`, and OpenJev inherits the same refusal. This is a
capability boundary, not a bug, and it is the reason the video table has four
rows and not eight.

### By family

| Model | motion | direction | appear | colourchange |
|---|---|---|---|---|
| `d3-mini` | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-nano` | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-flash` | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-lite` | 1.000 | 1.000 | 1.000 | 1.000 |
| `d3-edge` | **0.500** | 0.750 | 1.000 | 1.000 |

**`vid-motion` is the family that matters, and it is the only one that
discriminates.** The static and moving clips are constructed to share their
first frame, so a model that reads one frame cannot tell them apart. `d3-edge`
answers "false" to all four at 0.95–0.98 confidence — it is reading the first
frame and stopping. Every other d3 checkpoint scores 1.000.

**`vid-colourchange` does not discriminate, and that is informative.** The
steady and changing clips also share their first frame, but every model gets it
right, including `d3-edge`. The difference from `vid-motion` is that the colour
change is a large, high-contrast, whole-object change, while motion is a
position change that requires comparing two frames. `d3-edge` can detect "this
looks different from what I expect" but not "this moved".

**`vid-direction` is the only family where `d3-edge` is uncertain rather than
wrong.** Its mean confidence is 0.452 — it does not know — and it gets three of
four. That is honest behaviour, and it is the one place in either corpus where
`d3-edge`'s probabilities are informative about its own competence.

## What this changes about the text-sweep conclusions

The text sweep named `d3-flash` best-quality and `d3-edge` the fast option for
"short, lexical, argmax only" workloads. The media results narrow that:

- **`d3-edge`'s fast-path recommendation does not survive contact with images.**
  It is 8× faster than `d3-flash` on images (211 ms vs 1743 ms) and it is wrong
  on a third of them, with high confidence. The text-sweep rule said "argmax
  only, tight p95" — that rule is now unsafe for any workload where the input
  can contain an image. The rule needs a modality qualifier.
- **`d3-lite` is confirmed dominated, and more severely than in text.** It is
  the only model that fails both `img-count` and `img-text`, and it is slower
  than `d3-edge` while being no more accurate on video.
- **`clef-oQ4e` wins the image table outright** (Brier 0.0006, ECE 0.0122) and
  is the only model that beats the chat baseline on images. In text it was
  dominated by `d3-flash` on every axis. The domination does not extend to
  images: `clef-oQ4e` is 3.2× slower than `d3-flash` but 57× better on Brier.
  That is a real trade, not a domination.
- **`openjev` is no longer purely dominated.** It matches `d3-flash` on image
  accuracy (0.955) at 3× the latency and 2.3× the Brier, so it is still the
  worse choice — but it is not the catastrophic outlier the text sweep made it
  look like. Its 54.7 GB buys nothing here either.
- **The chat baseline is strong on images** (Brier 0.0031, second best) and
  costs 5842 ms. Any decision model claiming an image workload has to beat that
  on quality or latency, and only `clef-oQ4e` beats it on quality.

## What this corpus cannot measure

- **Real photographs.** Every image is drawn, every clip is rendered. A model
  that scores 1.000 here has demonstrated it can read synthetic geometry and
  synthetic text; it has not demonstrated anything about photographs, natural
  texture, lighting, or occlusion. The corpus is a floor, not a ceiling.
- **Video beyond 4 seconds and 4 families.** d3 samples at 2 fps and caps at 32
  frames, so a 4 s clip is 8 sampled frames. Longer clips, higher frame rates,
  and audio are all untested.
- **Multiple images per request.** OpenJev accepts at most one, so the corpus
  never sends more than one. Cross-image reasoning is untested for every family.
- **Concurrency.** `DecisionEngine` serialises requests behind a lock, so every
  latency here is single-request latency and says nothing about throughput.
- **`img-ambiguous` calibration.** As noted above, the family does not work as
  designed and its numbers should not be cited.

## Files

| Path | Contents |
|---|---|
| `manifest.json` | the 41 items with ground truth, committed |
| `*.png`, `*.mp4` | the media, committed (1.3 MB total) |
| `runs/image-*.json` | full per-item results, one file per model |
| `runs/video-*.json` | full per-item results, d3 only |

The media is committed rather than generated on demand because regenerating it
needs Pillow and OpenCV, which the stock interpreter does not have. 1.3 MB is
cheap enough that a clone should not need the app bundle to read the corpus.
