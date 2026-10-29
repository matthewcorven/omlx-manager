# Non-LLM models

The four LLM/VLM models in the campaign get a full tuning sweep. These two do
not — there is no decode throughput to optimize. They need only a smoke test.

| Model | Type | Status | Cause |
|---|---|---|---|
| `jinaai/jina-reranker-v3.5-mlx` | reranker | **PASS** — fixed | Replaced the Transformers checkpoint with the MLX conversion |
| `mlx-community/Unlimited-OCR-2-8bit` | VLM (OCR) | **FAIL** — blocked upstream | Needs unmerged mlx-vlm DASH attention |

Both first-pass failures shared a shape: the checkpoint defines a custom
architecture (`JinaForRanking`'s projector head, `UnlimitedOCRForCausalLM`'s DASH
router) that the mlx-vlm bundled in oMLX 0.7.3rc1 does not build, so weight
loading rejects unexpected parameters.

Only the reranker had an in-scope remedy — the model card lists an MLX
conversion, so it was a re-download. That was deferred until the benchmark slot
was free, because an active download skews throughput measurements by as much as
4x on this machine. It has since been done: `jinaai/jina-reranker-v3.5-mlx` is
downloaded, smoke-tested (Python document ranked first, 0.4715), and the
Transformers directory removed. See
[`jina-reranker-v3.5.md`](jina-reranker-v3.5.md).

The OCR model remains blocked: the fix is an upstream mlx-vlm release, not
anything this repo can do.
