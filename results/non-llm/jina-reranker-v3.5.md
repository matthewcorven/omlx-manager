# jina-reranker-v3.5 — smoke test

**Status: PASS — fixed by replacing the Transformers checkpoint with the MLX
conversion (`jinaai/jina-reranker-v3.5-mlx`).**

## Original symptom (first pass)

```
POST /v1/rerank
{"error":{"message":"Model 'jina-reranker-v3.5' is unavailable after a previous
load failure: Received 2 parameters not in model: projector.0.weight,
projector.2.weight."}}
```

## Diagnosis

The first download was `jinaai/jina-reranker-v3.5`, the **Transformers**
checkpoint, not an MLX conversion. It ships a custom `modeling.py` defining
`JinaForRanking`, a subclass of `Qwen3ForCausalLM` that adds a two-layer
projection head:

```python
self.projector = nn.Sequential(
    nn.Linear(config.hidden_size, config.hidden_size // 2, bias=False),  # projector.0
    nn.ReLU(),
    nn.Linear(config.hidden_size // 2, 512, bias=False),                 # projector.2
)
```

The safetensors file genuinely contains `projector.0.weight` and
`projector.2.weight` (312 tensors total, single-file checkpoint).

oMLX routes this by `model_type: qwen3` to `mlx_vlm`'s generative-text reranker
path (`_RERANKER_KINDS` maps `qwen3 -> GENERATIVE_TEXT`), which loads a plain
Qwen3 language model. That loader has no `projector` module, so weight loading
fails with the two unexpected parameters.

Ruled out, with evidence:

- **Not an override problem.** `model_type_override: "reranker"` was applied
  (`PUT` returned `success: true`) and a full server restart cleared the
  load-failure cache; the load fails identically. The value is already correct —
  oMLX reports `model_type: reranker`, `engine_type: reranker`.
- **Not a corrupt download.** The tensors are present and named as `modeling.py`
  expects; the mismatch is in oMLX's loader, not the files.
- **Not a config gap.** `config.json` has `architectures: ["JinaForRanking"]`
  but no projector entries; the head is defined only in `modeling.py`, which MLX
  loading does not execute.

## Fix applied

1. Downloaded `jinaai/jina-reranker-v3.5-mlx` (1.21 GB, 1,205,219,351 bytes) via
   `POST /admin/api/hf/download`. It ships `model.safetensors` plus a separate
   `projector.safetensors`, so the head is a first-class weight file rather than
   an unexpected parameter.
2. Smoke-tested it **before** removing anything — it answered correctly.
3. Removed the Transformers directory
   `~/.omlx/models/mlx-community/jinaai/jina-reranker-v3.5` (1.1 GB) so it stops
   failing on every load attempt.
4. Restarted oMLX so the model index dropped the removed path. After restart the
   model list contains only `jina-reranker-v3.5-mlx`.

## Verification

```sh
curl -s -X POST $OMLX/v1/rerank -H 'Content-Type: application/json' -d '{
  "model":"jina-reranker-v3.5-mlx",
  "query":"how do I reverse a string in python",
  "documents":["Use s[::-1] to reverse a string.",
               "The capital of France is Paris.",
               "Bake at 350F for 20 minutes."]}'
```

Result — HTTP 200, three scored results, Python document ranked first:

| Rank | Document | Score |
|---|---|---|
| 1 | `Use s[::-1] to reverse a string.` | 0.4715 |
| 2 | `Bake at 350F for 20 minutes.` | -0.1342 |
| 3 | `The capital of France is Paris.` | -0.1693 |

`usage.total_tokens: 221`. The same response was reproduced after the restart,
so the result is not a warm-cache artifact.

## Notes

- The model id changed: use `jina-reranker-v3.5-mlx`, not `jina-reranker-v3.5`.
- The download was run only while the benchmark slot was idle, per the campaign
  rule that downloads skew throughput by up to 4x.
