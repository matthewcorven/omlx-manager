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

## Caveats

- The change lives in the app bundle, not this repo, so an oMLX upgrade will
  overwrite it. Re-apply if a future release still bundles mlx-vlm < 0.7.11.
- The vendored `deepseekocr` shadows the wheel's for any model loaded in the
  same process. No `deepseekocr` / `deepseekocr_2` model is on disk, so this is
  inert; if one is added later, re-check it.
- The patch is process-global once applied, but it is only applied when an
  `unlimited-ocr` model loads, and it only shadows two model packages.
- Backup of the pre-change vendor tree: `/tmp/ocr_vendor_backup/` (transient).
