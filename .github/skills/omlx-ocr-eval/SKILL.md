---
name: omlx-ocr-eval
description: Evaluate and tune an oMLX OCR / document-parsing model (Unlimited-OCR, DeepSeek-OCR, and similar vision-to-markup models) against ground truth. Use when an OCR model needs a baseline, a settings sweep, a regression gate, or a final config — or when OCR output looks wrong and you need to tell a model fault from a processor misconfiguration. Covers the synthetic corpus, the scoring harness, the three gates, and the knobs that actually exist.
---

# Evaluating an OCR model

OCR models cannot be tuned the way a text model is. There is no decode-throughput
target to chase: measured decode on `Unlimited-OCR-2-8bit` is ~230 tok/s, an order
of magnitude above the text models in this repo, and the wall clock is dominated by
prefill and by how many tiles the processor cuts the page into. The axes that matter
are **accuracy**, **latency**, and **memory** — and accuracy is the only one you
cannot eyeball.

So the deliverable is not a `final.json` of tok/s. It is a **scored baseline against
ground truth**, plus a config that is proven not to degrade it.

## The one rule that invalidates everything else

**A score is only meaningful if the output is real OCR.** Three gates run before any
number is trusted, and each one has already caught a real fault on this box:

| Gate | Catches | Failure looks like |
|---|---|---|
| **error** | the request never produced output | `Cache corruption not recoverable: 'TurboQuantKVCache' object has no attribute 'dash_state'` |
| **degenerate** | output is not OCR at all | `11. 11. 11. ...` for 8192 tokens, `finish_reason: stop` |
| **truncation** | the page did not fit the budget | `finish_reason: length` |

The degenerate gate is the important one and the least obvious. At
`max_crops: 4` the model answers a dense real page with a repeated token and
**stops cleanly** — no error, no truncation, a plausible-looking `stop`. A harness
that only checks `finish_reason` reports success. Always assert that the output
contains `<BLOCK>` markup and does not collapse into a repeated token.

## Why a synthetic corpus

Real scanned documents have no ground truth without hand-labelling, and
hand-labelling is not reproducible across sessions. `scripts/ocr_corpus.py` renders
known text at known coordinates with PIL, so ground truth is exact and free, and the
corpus regenerates byte-identically on any machine with the same fonts.

Pages are 1024×1024 to match the model's `candidate_resolutions`. Boxes are recorded
in the model's own **0–1000 normalised space**, which is what
`<BLOCK>label[x0, y0, x1, y1]` emits — not pixels. Do not score in pixels.

Twelve pages, chosen so each isolates one failure mode:

| Page | Isolates |
|---|---|
| `clean` | the floor — anything below 1.0 here is a real fault |
| `dense` | many blocks, tight leading |
| `table` | cell structure; the model emits one HTML block, truth has one block per cell |
| `twocol` | reading order across columns |
| `small` | 11 px type |
| `lowcontrast` | ink at 150/255 on 246/255 paper |
| `rotated` | 3° skew; ground truth is rotated with the pixels |
| `mixed` | text + table + footer on one page |
| `mixedcase` | `O0Il1\|S5B8` — the only page that still scores above zero CER |
| `handwriting` | italic serif, the closest synthetic stand-in for a scan |
| `noise` | 24 000 salt-and-pepper pixels |
| `multipage` | text running past the bottom, to exercise `cross_*` labels |

**The corpus saturates.** Eleven of twelve pages score CER 0.0000 on
`Unlimited-OCR-2-8bit`. That is a good result for the model and a weak regression
gate for the harness — a corpus that is already perfect cannot show a small
degradation. When a knob needs to be *proven* harmless, score a real dense asset as
well (see "When the corpus saturates" below).

## Metrics

Per page and aggregated, from `scripts/ocr_eval.py`:

- **cer** — character error rate over recognised text only. Scoring the raw stream
  would count the markup itself as errors.
- **block_recall / block_precision** — matched blocks over truth / over emitted.
- **iou** — mean IoU of matched boxes, in 0–1000 space.
- **order_tau** — Kendall tau of matched blocks' reading order; 1.0 is perfect.
- **wall_ms** — end-to-end, which is the latency that matters.

Matching is greedy on `0.6 × text similarity + 0.4 × IoU`, so a block that is found
but mis-boxed still counts as found.

## The knobs that actually exist

Most of the text-model settings are inert here. What is left:

| Knob | Where | Verdict |
|---|---|---|
| `temperature` | model settings | **must be 0.** Anything else makes the run non-reproducible and the score meaningless |
| `max_tokens` | request | **≥ 8192** for one page, 16384 for several. The model README says so; 400–1200 truncates real pages |
| `max_crops` | `processor_config.json` | **leave at 16.** See below — this is the trap |
| `page_layout` | `processor_config.json` | leave `true` |
| `turboquant_kv_enabled` | model settings | **broken on this model.** Errors out; see below |
| `max_context_window` | model settings | no effect on a single page |
| `enable_thinking` | model settings | not applicable |
| `moe_expert_offload` | model settings | only under residency pressure; not an accuracy knob |
| `mtp` / `dflash` / `specprefill` | model settings | not applicable to this architecture |

`max_crops` and `page_layout` are **not oMLX model settings**. They come from the
model's `processor_config.json`; there is no settings plumbing for them. Changing
them means editing that file and reloading the model.

### `max_crops` is the trap

`max_crops: 4` looks like a free win. On a 2048×2048 page it is **1.8× faster**
(1.93 s → 1.06 s) with identical corpus scores, and on three detail-dense 2048×2048
pages it is 1.36× faster (2.03 s → 1.49 s) with identical corpus scores.

It is not a free win. On the model's own `assets/leaderboard.png` (6682×5011, dense
small type) `max_crops: 4` produces `11. 11. 11. ...` for 8192 tokens and stops;
`max_crops: 16` produces 13 correct blocks in 2.3 s.

The reason is the tile grid, and it is worth understanding rather than memorising.
`max_crops` is the **cap** on tiles in `dynamic_preprocess`, which picks the grid
whose aspect ratio is closest to the page and then resizes the page to fit it:

| Page | `max_crops: 4` | `max_crops: 16` |
|---|---|---|
| 1024×1024 (corpus) | 2×2 = 4 tiles, 1280×1280 | 2×2 = 4 tiles, 1280×1280 |
| 2048×2048 | 2×2 = 4 tiles, 1280×1280 | 4×4 = 16 tiles, 2560×2560 |
| 6682×5011 (`leaderboard.png`) | 2×2 = 4 tiles, 1280×1280 | 4×3 = 12 tiles, 2560×1920 |

A 1024×1024 page lands on 2×2 either way, so the corpus **cannot** distinguish the
two settings — it is not that the corpus is too clean, it is that the cap never
binds. The 2048×2048 pages do differ (4 vs 16 tiles) and still score identically,
which is the more interesting result: at 2048×2048 the 4-tile grid downscales only
1.6×, so the text survives. At 6682×5011 the same 4-tile grid downscales **5.2×**
and the text is gone.

**Rule: never lower `max_crops` on the strength of the synthetic corpus alone.**
Score a real dense asset before and after, and read the output text.

### `turboquant_kv_enabled` is broken on this model

Enabling it makes every request fail:

```
Cache corruption not recoverable after retries:
'TurboQuantKVCache' object has no attribute 'dash_state'
```

The model uses DASH sparse attention, and the TurboQuant cache does not implement
the `dash_state` the attention path requires. This is a hard incompatibility, not a
tuning result. Leave it off.

## Procedure

1. **Confirm the model loads and answers.** One request, `max_tokens: 8192`,
   `temperature: 0`, prompt `Multi page parsing.` — read the text, do not just check
   for a 200.
2. **Generate the corpus.**
   `python3 scripts/ocr_corpus.py --out results/non-llm/<model>/corpus`
3. **Baseline.** `python3 scripts/ocr_eval.py --model <id> --corpus <dir> --out
   results/non-llm/<model>/baseline.json`. All three gates must pass. If any page is
   `degenerate` or `truncated`, stop — the config is wrong, not the model.
4. **Sweep one knob at a time.** Reload between settings changes; `max_crops` needs
   an unload/load, not just a settings PUT.
5. **Re-baseline after every revert.** A sweep that does not return to the baseline
   number is measuring drift, not the knob.
6. **Score a real dense asset** for any knob that looked like a win on the corpus.
7. **Record** `baseline.json`, the sweep, and the final config under
   `results/non-llm/<model>/`.
8. **Commit** with explicit paths.

## When the corpus saturates

If every page scores CER 0.0000, the corpus cannot discriminate. Do not conclude the
knob is safe. Instead:

- score a real dense asset (the model's own `assets/` are good candidates) and
  compare block counts and the actual text;
- add a harder page to `scripts/ocr_corpus.py` that targets the specific risk;
- treat a large latency win with unchanged scores as a **corruption suspect** until
  the output text has been read.

## Reading a result that looks wrong

- **`11. 11. 11. ...`** — processor misconfiguration (`max_crops` too low for the
  page), or the wrong prompt. Not model corruption.
- **Numbered list output** — wrong prompt. The correct prompt is
  `Multi page parsing.`; `document parsing.` yields degenerate numbered output.
- **`finish_reason: length`** — the budget is too small. Raise `max_tokens`; do not
  score the page.
- **Empty output with a 200** — check for an `error` object in the stream; oMLX
  emits errors as SSE data frames, not HTTP status codes.
- **CER high but blocks found** — usually a table. The model emits one HTML block
  per table; ground truth has one block per cell. The harness flattens both.

## Deliverables

```
results/non-llm/<model>/
  baseline.json     # full scored run, including raw transcripts
  corpus/
    manifest.json   # ground truth (committed)
    *.png           # derived, gitignored
```

`baseline.json` keeps the raw model output for every page. That is the evidence; a
score without the transcript cannot be re-checked.
