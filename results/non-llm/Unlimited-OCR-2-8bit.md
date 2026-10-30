# Unlimited-OCR-2-8bit — smoke test

**Status: PASS — fixed by updating oMLX's vendored `unlimited_ocr` package to
the mlx-vlm 0.7.11 implementation.**

## Original symptom

```
POST /admin/api/models/Unlimited-OCR-2-8bit/load
{"detail":"Model 'Unlimited-OCR-2-8bit' failed to load: VLM load failed:
Received 60 parameters not in model:
language_model.model.layers.0.self_attn.dash_router.head_cls,
language_model.model.layers.0.self_attn.dash_router.k_norm.weight,
language_model.model.layers.0.self_attn.dash_router.k_proj.weight,
language_model.model.layers.0.self_attn.dash_router.q_norm.weight, ..."}
```

## Root cause

The checkpoint sets `sparse_attention_config.training_stage: "dash"` and
`use_sparse_attention: true`, so its decoder is DASH block-sparse attention
(page2d RoPE plus a per-layer router) rather than the R-SWA ring cache of the
original Unlimited-OCR.

oMLX 0.7.3rc1 bundles **mlx-vlm 0.7.10**. DASH landed in **mlx-vlm 0.7.11**.
The 0.7.10 `models/unlimited_ocr/` package exists but has no `dash.py`, so the
60 `dash_router.*` tensors have no destination and are rejected as unexpected
parameters. The earlier note that the bundled mlx-vlm "has no `dash_router`
module" was directionally right but imprecise: the module exists, the DASH
implementation does not.

## Why a full mlx-vlm wheel swap was rejected

Replacing the bundled mlx-vlm with 0.7.11 would change the inference stack for
every model in the campaign:

- `models/qwen3_5/language.py` adds `and h.shape[1] > 1` to the single-row
  decode fast path — a decode-path change for the Qwen3.5 family, which
  includes two tuned models.
- `models/minimax_m3_vl/language.py` is a large rewrite.
- `utils.py` changes model-type remapping and quantization handling.
- 0.7.11 requires `mlx-audio>=0.6.2` (bundled: 0.5.7) and `datasets` (absent).

## The fix that was applied

oMLX already ships a compat patch at
`/Applications/oMLX.app/Contents/Resources/omlx/patches/mlx_vlm_unlimited_ocr_compat/`.
It prepends `vendor/mlx_vlm` to `mlx_vlm.__path__` and
`mlx_vlm.models.__path__`, so a vendored package shadows the wheel's, and it is
applied **only** when `for_vlm and model_type == "unlimited-ocr"`
(`omlx/utils/model_loading.py:828-836`). That makes it a surgical extension
point: nothing the seven tuned LLMs use is touched.

The vendored `unlimited_ocr` package was an oMLX-modified fork of 0.7.10. It was
updated to the 0.7.11 implementation, preserving the three oMLX modifications:

1. `language.py` — `RingSlidingKVCache.memory_profile` removed, along with the
   now-unused `replace` / `ceil` imports. Safe: oMLX never calls
   `.memory_profile(`.
2. `unlimitedocr.py` — `from transformers import AutoProcessor` plus
   `AutoProcessor.register("unlimited-ocr", UnlimitedOCRProcessor)`.
3. `processing_unlimitedocr.py` — `default_chat_template` property removed.

Files changed under `vendor/mlx_vlm/models/`:

| File | Change |
|---|---|
| `unlimited_ocr/dash.py` | **new** — DASH router, page2d RoPE, sparse attention, dash cache |
| `unlimited_ocr/config.py` | 0.7.11 — `sparse_attention_config` on `TextConfig`, `layer_norm_eps` on `VisionConfig` |
| `unlimited_ocr/language.py` | 0.7.11 + oMLX mod 1 |
| `unlimited_ocr/unlimitedocr.py` | 0.7.11 + oMLX mod 2 |
| `unlimited_ocr/processing_unlimitedocr.py` | 0.7.11 + oMLX mod 3 |
| `deepseekocr/` | **new vendored copy** — 0.7.10 base with 0.7.11 `vision.py` and `sam.py` |

`deepseekocr` had to be vendored rather than patched in place because it is
shared with `deepseekocr_2`; the 0.7.11 changes there are `quick_gelu` in the
CLIP `MLP` (matching the checkpoint's reference `deepencoder.py`) and
antialiased bicubic positional-embedding interpolation, plus align-corners=False
relative-position indices in `sam.py`. The rest of the package is byte-identical
between 0.7.10 and 0.7.11, as are `base.py`, `cache.py`, and `kernels.py`.

## Verification

Load succeeds with no unexpected-parameter error. Two real requests on the
checkpoint's own assets, `max_tokens` 1200 and 900, temperature 0, prompt
`Multi page parsing.`:

`assets/leaderboard.png` — 290 completion tokens, `finish_reason: stop`:

```
<PAGE><BLOCK>header[55, 13, 150, 28]<FORK>Unlimited OCR 2 (Ours)
<BLOCK>header[180, 13, 234, 28]<FORK>Qwen3.8-Max
<BLOCK>header[264, 13, 342, 28]<FORK>Qwen-3.8-Flash-Next
...
<BLOCK>footer[873, 976, 961, 992]<FORK>ReadOrder (1-Edit)
```

`assets/Unlimited-OCR2.png` — 431 completion tokens, `finish_reason: stop`:

```
<PAGE><BLOCK>image_caption[51, 24, 138, 62]<FORK>(a) R-SWA
<BLOCK>image_caption[202, 19, 405, 51]<FORK>Visual token cost overload
<BLOCK>image_caption[529, 24, 626, 62]<FORK>(b) SR-SWA
<BLOCK>image_caption[663, 19, 948, 51]<FORK>Human-like selection of visual tokens
...
```

Both outputs are the documented `<PAGE>` / `<BLOCK>label[x0, y0, x1, y1]<FORK>text`
format, with labels and coordinates that match the images. Not garbage, not
repetition.

Regression check: all seven tuned LLMs were loaded and served a real request
after the change — `Qwen3.8-27B-oQ4e-mtp`, `Ornith-1.0-35B-oQ4e`, `flint-oQ4e`,
`gemma-4-31B-it-oQ4e-mtp`, `gemma-4-26B-A4B-it-oQ8e-mtp`,
`Qwen3.6-35B-A3B-oQ8e-mtp`, `Qwen3.8-Flash-Next-oQ4e-mtp`. All returned `OK`.

## Evaluation

The smoke test above proves the model loads and emits the right format. It does
not prove the model is *accurate*, and accuracy is the only thing an OCR model
can be tuned for. There is no OCR benchmark in oMLX's accuracy suite
(`VALID_BENCHMARKS` in `admin/accuracy_benchmark.py` is text-only), so the
evaluation is a custom harness against a synthetic ground-truth corpus. The
process is documented in
[`.github/skills/omlx-ocr-eval`](../../.github/skills/omlx-ocr-eval/SKILL.md).

### Corpus

`scripts/ocr_corpus.py` renders 12 pages at 1024×1024 with PIL, recording every
block's text and box in the model's 0–1000 normalised space. Ground truth is
exact and the corpus regenerates deterministically. 76 ground-truth blocks.

### Baseline

`scripts/ocr_eval.py`, `max_tokens: 8192`, `temperature: 0`, prompt
`Multi page parsing.`, `max_crops: 16`. Full run in
[`Unlimited-OCR-2-8bit/baseline.json`](Unlimited-OCR-2-8bit/baseline.json).

| Page | CER | Recall | Precision | IoU | τ | ms |
|---|---|---|---|---|---|---|
| clean | 0.0000 | 1.00 | 1.00 | 0.922 | 1.0 | 1052 |
| dense | 0.0000 | 1.00 | 1.00 | 0.806 | 1.0 | 1419 |
| table | 0.0000 | 1.00 | 1.00 | 0.862 | 1.0 | 1064 |
| twocol | 0.0000 | 1.00 | 1.00 | 0.906 | 1.0 | 1214 |
| small | 0.0000 | 1.00 | 1.00 | 0.766 | 1.0 | 1587 |
| lowcontrast | 0.0000 | 1.00 | 1.00 | 0.921 | 1.0 | 885 |
| rotated | 0.0000 | 1.00 | 1.00 | 0.915 | 1.0 | 870 |
| mixed | 0.0000 | 1.00 | 1.00 | 0.901 | 1.0 | 1135 |
| mixedcase | 0.0148 | 1.00 | 1.00 | 0.891 | 1.0 | 1091 |
| handwriting | 0.0000 | 1.00 | 1.00 | 0.917 | 1.0 | 1031 |
| noise | 0.0000 | 1.00 | 1.00 | 0.823 | 1.0 | 867 |
| multipage | 0.0000 | 1.00 | 1.00 | 0.888 | 1.0 | 1417 |

**Mean CER 0.0012, block recall 1.00, precision 1.00, IoU 0.877, τ 1.0,
1.13 s/page.** All 12 pages `finish_reason: stop`, all deterministic across two
runs at temperature 0.

The only page above zero is `mixedcase`, and the errors are the expected ones —
`O0Il1|S5B8` came back as `O0II1|S5B8` / `00 11 II 5S 8B`. That is a genuine
glyph-confusion limit, not a fault.

### Sweeps

Two knobs were tried. Both were rejected.

**`turboquant_kv_enabled: true`** — every request fails:

```
Cache corruption not recoverable after retries:
'TurboQuantKVCache' object has no attribute 'dash_state'
```

The model uses DASH sparse attention; the TurboQuant cache does not implement
the `dash_state` the attention path needs. Hard incompatibility. Left off.

**`max_crops: 4`** (from `processor_config.json`, not a model setting) — this is
the trap. On the corpus it is indistinguishable from 16, and on a 2048×2048 page
it is 1.8× faster (1.93 s → 1.06 s) with identical scores. On the model's own
`assets/leaderboard.png` (6682×5011, dense small type) it produces:

```
11. 11. 11. 11. 11. 11. ... (8192 tokens, finish_reason: stop)
```

`max_crops: 16` on the same image produces 13 correct blocks in 2.3 s. The
synthetic corpus is too clean to see this because a 1024×1024 page fits one tile
either way. **Left at 16.**

This is why the harness has a degeneracy gate: the failure has no error, no
truncation, and a clean `stop`. Only reading the text catches it.

### Final config

Nothing tuned. The model ships correct: `temperature: 0`, `max_crops: 16`,
`page_layout: true`, `turboquant_kv_enabled: false`, `max_tokens: 8192` per page.
The value of the evaluation is the regression gate, not a settings change.

## Caveats

- The change lives in the app bundle, not this repo, so an oMLX upgrade will
  overwrite it. Re-apply if a future release still bundles mlx-vlm < 0.7.11.
- The vendored `deepseekocr` shadows the wheel's for any model loaded in the
  same process. No `deepseekocr` / `deepseekocr_2` model is on disk, so this is
  inert; if one is added later, re-check it.
- The patch is process-global once applied, but it is only applied when an
  `unlimited-ocr` model loads, and it only shadows two model packages.
- Backup of the pre-change vendor tree: `/tmp/ocr_vendor_backup/` (transient).
