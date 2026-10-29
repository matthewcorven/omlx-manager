# jina-reranker-v3.5 — smoke test

**Status: FAILED — wrong artifact downloaded. Fix is a re-download, deferred until
the benchmark slot is free (downloads skew throughput measurements).**

## Symptom

```
POST /v1/rerank
{"error":{"message":"Model 'jina-reranker-v3.5' is unavailable after a previous
load failure: Received 2 parameters not in model: projector.0.weight,
projector.2.weight."}}
```

## Diagnosis

We have `jinaai/jina-reranker-v3.5`, which is the **Transformers** checkpoint, not
an MLX conversion. It ships a custom `modeling.py` defining `JinaForRanking`, a
subclass of `Qwen3ForCausalLM` that adds a two-layer projection head:

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

## Fix

The model card states an MLX conversion exists:

> GGUF ... and MLX versions are now available.

Download `jinaai/jina-reranker-v3.5-mlx` in place of the Transformers repo and
re-run the smoke test. The current directory
(`~/.omlx/models/mlx-community/jinaai/jina-reranker-v3.5`, 1.1 GB) should be
removed once the replacement is verified, so it stops failing on every load
attempt.

## Smoke test to run after the fix

```sh
curl -s -X POST $OMLX/v1/rerank -H 'Content-Type: application/json' -d '{
  "model":"jina-reranker-v3.5",
  "query":"how do I reverse a string in python",
  "documents":["Use s[::-1] to reverse a string.",
               "The capital of France is Paris.",
               "Bake at 350F for 20 minutes."]}'
```

Pass criteria: HTTP 200, three scored results, and the Python document ranked
first.
