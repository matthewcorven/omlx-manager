# Non-LLM models

The four LLM/VLM models in the campaign get a full tuning sweep. These two do
not — there is no decode throughput to optimize. They need only a smoke test,
and both failed it.

| Model | Type | Status | Cause |
|---|---|---|---|
| `jinaai/jina-reranker-v3.5` | reranker | **FAIL** — fixable | Wrong artifact: Transformers checkpoint, not the MLX conversion |
| `mlx-community/Unlimited-OCR-2-8bit` | VLM (OCR) | **FAIL** — blocked upstream | Needs unmerged mlx-vlm DASH attention |

Both failures share a shape: the checkpoint defines a custom architecture
(`JinaForRanking`'s projector head, `UnlimitedOCRForCausalLM`'s DASH router) that
the mlx-vlm bundled in oMLX 0.7.3rc1 does not build, so weight loading rejects
unexpected parameters.

Only the reranker has an in-scope remedy — the model card lists an MLX
conversion, so it is a re-download. That is deferred until the benchmark slot is
free, because an active download skews throughput measurements by as much as
4× on this machine.
