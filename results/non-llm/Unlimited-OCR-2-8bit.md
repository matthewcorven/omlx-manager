# Unlimited-OCR-2-8bit — smoke test

**Status: FAILED — requires an mlx-vlm feature that is not in oMLX 0.7.3rc1.
Not fixable from this repo; no action taken.**

## Symptom

```
POST /admin/api/models/Unlimited-OCR-2-8bit/load
{"detail":"Model 'Unlimited-OCR-2-8bit' failed to load: VLM load failed:
Received 60 parameters not in model:
language_model.model.layers.0.self_attn.dash_router.head_cls,
language_model.model.layers.0.self_attn.dash_router.k_norm.weight,
language_model.model.layers.0.self_attn.dash_router.k_proj.weight,
language_model.model.layers.0.self_attn.dash_router.q_norm.weight, ..."}
```

## Diagnosis

The model card states the requirement plainly:

> Unlimited-OCR-2 support (page2d RoPE and DASH block-sparse attention) is being
> upstreamed to mlx-vlm. Until it is released, install from the branch that adds it:
> `pip install -U "git+https://github.com/shuuul/mlx-vlm.git"`

The 60 unexpected parameters are the per-layer DASH router, which the card says
stays in bfloat16 alongside the SAM and CLIP vision towers. The bundled mlx-vlm
in `/Applications/oMLX.app` has no `dash_router` module, so it cannot load them.

This is not a download or config problem: the checkpoint is a legitimate
`mlx-community` conversion (8-bit affine, group size 64) and the tensors match
what the model's own `dash_attention.py` defines.

## Why no fix is attempted

Fixing it means installing a forked mlx-vlm into the oMLX app bundle, which
replaces the inference stack for **every** model in the campaign. That is far
too invasive to do for one non-LLM model, and it would invalidate the tuning
results already recorded for the three LLMs.

## What would unblock it

- An oMLX release bundling the upstreamed mlx-vlm that includes DASH attention.
- Or a separate venv running `shuuul/mlx-vlm` directly for OCR only, outside
  oMLX, if OCR is actually needed. The card's CLI invocation works there:

  ```sh
  mlx_vlm.generate --model mlx-community/Unlimited-OCR-2-8bit --image page.png \
      --prompt "Multi page parsing." --max-tokens 8192 --temperature 0
  ```

The 3.8 GB download is retained; it is not harmful and will work after an oMLX
upgrade.
