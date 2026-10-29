# Non-LLM models

The LLM/VLM models in the campaign get a full tuning sweep. These two do not —
there is no decode throughput to optimize. They need only a smoke test.

| Model | Type | Status | Cause |
|---|---|---|---|
| `jinaai/jina-reranker-v3.5-mlx` | reranker | **PASS** — fixed | Replaced the Transformers checkpoint with the MLX conversion |
| `mlx-community/Unlimited-OCR-2-8bit` | VLM (OCR) | **PASS** — fixed | Updated oMLX's vendored `unlimited_ocr` package to the mlx-vlm 0.7.11 implementation |

Both first-pass failures shared a shape: the checkpoint defines a custom
architecture (`JinaForRanking`'s projector head, `UnlimitedOCRForCausalLM`'s DASH
router) that the mlx-vlm bundled in oMLX 0.7.3rc1 does not build, so weight
loading rejects unexpected parameters.

Both are now resolved.

**Reranker.** The model card lists an MLX conversion, so the fix was a
re-download. That was deferred until the benchmark slot was free, because an
active download skews throughput measurements by as much as 4x on this machine.
It has since been done: `jinaai/jina-reranker-v3.5-mlx` is downloaded,
smoke-tested (Python document ranked first, 0.4715), and the Transformers
directory removed. See [`jina-reranker-v3.5.md`](jina-reranker-v3.5.md).

**OCR.** The blocker was mlx-vlm 0.7.10 lacking DASH attention, which landed in
0.7.11. A full wheel swap was rejected because 0.7.11 also changes the Qwen3.5
decode path and needs two dependencies the bundle lacks. Instead, oMLX's own
`mlx_vlm_unlimited_ocr_compat` patch — which vendors a shadow copy of the
`unlimited_ocr` package and is applied only for `model_type == "unlimited-ocr"` —
was updated to the 0.7.11 implementation, preserving its three oMLX
modifications. The model now loads and produces correct structured OCR. All
seven tuned LLMs were regression-tested afterwards and are unaffected. See
[`Unlimited-OCR-2-8bit.md`](Unlimited-OCR-2-8bit.md).
