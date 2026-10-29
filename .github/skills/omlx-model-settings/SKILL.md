---
name: omlx-model-settings
description: Read and apply per-model settings on oMLX 0.7.3rc1 — the complete ModelSettingsRequest field reference with semantics and when to use each knob, plus profiles, profile templates, optimal-settings lookup, recipes, reset, generation_config, and load/unload. Use when tuning context window, thinking budget, MTP/DFlash/SpecPrefill, MoE expert offload, KV cache quantization, ANE prefill, sampling defaults, or when a settings change needs a reload.
---

# oMLX per-model settings

Verified against a live oMLX 0.7.3rc1 server on `http://127.0.0.1:8001`.
Success paths that require a loaded real model are marked **unverified** — no
model was downloaded while writing this.

## Setup

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=http://127.0.0.1:8001
```

## The single most important gotcha

**There is no `GET /admin/api/models/{id}/settings`.**

```sh
curl -s -w '\n[%{http_code}]\n' $OMLX/admin/api/models/MarkItDown/settings
# {"detail":"Method Not Allowed"}
# [405]
```

Settings are **embedded in the model list**:

```sh
curl -s $OMLX/admin/api/models | jq '.models[] | select(.id=="<model_id>") | .settings'
```

`GET /admin/api/models` returns `{"models":[...]}`. Each real model entry carries
a `settings` object (a serialized `ModelSettings`). The virtual builtin
`MarkItDown` entry has **no** `settings` key at all.

## Reading current settings

```sh
MODEL='<model_id>'

# full settings object
curl -s $OMLX/admin/api/models | jq --arg m "$MODEL" '.models[] | select(.id==$m) | .settings'

# just the knobs that matter for latency
curl -s $OMLX/admin/api/models | jq --arg m "$MODEL" '.models[] | select(.id==$m) | .settings
  | {max_context_window, max_tokens, temperature, top_p, top_k, min_p, repetition_penalty,
     enable_thinking, thinking_budget_enabled, thinking_budget_tokens,
     mtp_enabled, dflash_enabled, specprefill_enabled,
     moe_expert_offload_enabled, moe_expert_offload_resident_fraction,
     turboquant_kv_enabled, turboquant_kv_bits, index_cache_freq, ttl_seconds}'
```

Useful sibling fields on the same entry (not settings, but needed for tuning):

```sh
curl -s $OMLX/admin/api/models | jq --arg m "$MODEL" '.models[] | select(.id==$m)
  | {id, model_type, config_model_type, engine_type, model_context_length,
     estimated_size_formatted, actual_size_formatted, loaded, is_loading, pinned,
     dflash_compatible, dflash_compatible_reason,
     mtp_compatible, mtp_compatible_reason,
     moe_expert_offload_supported, moe_offload_allows_mtp,
     activation_fp16_supported, is_paroquant, paroquant_reason,
     qwen4_ple_ssd_offload_supported, deepseek_v41_engram_ssd_offload_supported}'
```

`config_model_type` is what gates the model-family-specific settings (see
"Silent coercion" below). `dflash_compatible` / `mtp_compatible` tell you whether
the speculative-decoding knobs will do anything at all.

## Applying settings

```sh
curl -s -X PUT $OMLX/admin/api/models/$MODEL/settings \
  -H 'Content-Type: application/json' \
  -d '{"max_context_window": 65536, "max_tokens": 8192}' | jq
```

Response:

```json
{"success":true,"model_id":"<model_id>","settings":{...},"model_type":"llm",
 "engine_type":"mlx","requires_reload":false,"auto_unloaded":false,
 "auto_reloaded":false,"reload_deferred":false}
```

### Partial-update semantics

The handler uses pydantic's `model_fields_set`, so:

- **Field omitted** → left unchanged.
- **Field sent as `null`** → reset to the default / disabled.
- **Field sent with a value** → applied.

`extra="forbid"` is set on the request model. Any unknown key is a hard error:

```sh
curl -s -w '\n[%{http_code}]\n' -X PUT $OMLX/admin/api/models/$MODEL/settings \
  -H 'Content-Type: application/json' -d '{"bogus_field":1}'
# {"detail":[{"type":"extra_forbidden","loc":["body","bogus_field"],
#             "msg":"Extra inputs are not permitted","input":1}]}
# [422]
```

Unknown model (including the virtual `MarkItDown`) → 404:

```json
{"detail":"Model not found: MarkItDown"}
```

### `requires_reload`

`requires_reload` is `true` when the model is currently loaded **and** any of:

- `model_type_override` was sent and the resulting `engine_type` changed, or
- the engine runtime signature changed (any engine-construction-time field), or
- any of these were sent: `index_cache_freq`, `dflash_enabled`,
  `dflash_draft_model`, `dflash_draft_quant_enabled`,
  `dflash_draft_quant_weight_bits`, `dflash_draft_quant_group_size`,
  `dflash_draft_window_size`, `dflash_block_size`, `dflash_verify_mode`,
  `trust_remote_code`.

When `requires_reload` is true the server:

1. Calls `request_unload(abort_active=False)` — in-flight requests finish first.
2. Sets `reload_deferred = not auto_unloaded` (true when the engine was busy).
3. If the model was **pinned** and got unloaded, reloads it →
   `auto_reloaded: true`.

So a reload-requiring change on a busy pinned model is applied but deferred; poll
`GET /admin/api/models` until `loaded` is true again.

## Full field reference

Grouped by purpose. Defaults in parentheses. "Reload" = changing it while loaded
triggers `requires_reload`.

### Identity & routing

| Field | Type / default | What it does |
| --- | --- | --- |
| `model_alias` | str \| null | Alternate id the model answers to on `/v1/*`. Empty string → `null`. **400** if it collides with another model's alias, a model directory name, or an exposed profile name. |
| `model_type_override` | `llm`\|`vlm`\|`embedding`\|`reranker`\|`audio_stt`\|`audio_tts`\|`audio_sts`\|`decision`\|null | Force the engine type when auto-detection is wrong. **400** on a GGUF model ("A GGUF model's type comes from its file"). Changing it can change `engine_type` → reload. |
| `display_name` | str \| null | UI label only. |
| `description` | str \| null | UI text only. |
| `is_pinned` | bool (false) | Keep loaded; survives LRU eviction and is preloaded on `POST /admin/api/reload`. |
| `is_default` | bool (false) | Default model for clients that do not name one. |
| `is_hidden` | bool (false) | Hide from `/v1/models` and the UI. |
| `is_favorite` | bool (false) | UI sort only. |
| `active_profile_name` | str \| null | Which profile is currently applied (bookkeeping). |
| `external_engine` | str \| null | Route to an external engine instead of the local MLX engine. |

### Context & generation limits

| Field | Type / default | What it does |
| --- | --- | --- |
| `max_context_window` | int \| null | **The single biggest TTFT lever.** Total prompt+output budget. `null` = model native. Lower it to cut KV-cache memory and prefill work; raise it only if the model supports it. |
| `max_tokens` | int ≥ 1 \| null | Default cap on generated tokens per request. Does not affect TTFT; caps worst-case decode time. |
| `ttl_seconds` | int \| null | Idle seconds before the model is unloaded. `null` = global `idle_timeout.idle_timeout_seconds` (900). |
| `index_cache_freq` | int \| null | **Reload.** How often the prompt-prefix index cache is refreshed. Higher = fewer cache rebuilds, staler prefix reuse. |
| `max_tool_result_tokens` | int \| null | Truncate tool results before they enter the prompt. `0` or `null` → disabled (`None`). Directly reduces prompt tokens for agentic coding loops. |

### Sampling

| Field | Type / default | What it does |
| --- | --- | --- |
| `temperature` | float (1.0) | Randomness. Coding: 0.0–0.3. |
| `top_p` | float (0.95) | Nucleus cutoff. |
| `top_k` | int (0) | 0 = disabled. |
| `min_p` | float (0.0) | Min-probability floor; often better than `top_p` for code. |
| `repetition_penalty` | float (1.0) | >1 penalizes repeats. Keep at 1.0 for code. |
| `presence_penalty` | float (0.0) | OpenAI-style presence penalty. |
| `force_sampling` | bool (false) | Apply these sampling values even when the request supplies its own. |
| `chat_template_kwargs` | dict \| null | Extra kwargs passed to the chat template (e.g. `{"enable_thinking": false}`). |
| `forced_ct_kwargs` | dict \| null | Kwargs forced onto every chat-completion request. |

### Thinking / reasoning

| Field | Type / default | What it does |
| --- | --- | --- |
| `enable_thinking` | bool \| null | Default for hybrid-reasoning models. `null` = model default. **Turning thinking off is the largest single TTFT win on reasoning models.** |
| `preserve_thinking` | bool \| null | Keep prior-turn reasoning blocks in context. Off = shorter prompts, lower TTFT, less continuity. |
| `cache_reasoning_output` | bool \| null | Cache reasoning output for reuse. |
| `thinking_budget_enabled` | bool (false) | Enable a hard cap on reasoning tokens. |
| `thinking_budget_tokens` | int \| null | The cap. `0` or `null` → stored as `None` (disabled). |
| `reasoning_parser` | str \| null | Which parser splits reasoning from content. Built-ins include `qwen`, `harmony`, `llama`, … Validated against the xgrammar builtin list. |

### Guided decoding

| Field | Type / default | What it does |
| --- | --- | --- |
| `guided_grammar_enabled` | bool (false) | Constrain output with a grammar. |
| `guided_grammar` | str \| null | The grammar itself. **Never imported from recipes/snapshots** (`SNAPSHOT_EXCLUDED_FIELDS`). |

### KV cache compression (TurboQuant)

| Field | Type / default | What it does |
| --- | --- | --- |
| `turboquant_kv_enabled` | bool (false) | Compress the KV cache. Shrinks memory so you can hold a bigger context; costs a little decode speed. |
| `turboquant_kv_scheme` | `turboquant`\|`affine4`\|`affine8` (`turboquant`) | Quantization scheme. |
| `turboquant_kv_bits` | 2 \| 2.5 \| 3 \| 3.5 \| 4 \| 6 \| 8 (4) | Bits per KV element. Lower = less memory, more quality loss. Validated. |
| `turboquant_skip_last` | bool (true) | Leave the last N layers uncompressed for quality. |

Mutually exclusive with `vlm_mtp_enabled` → 400
`"vlm_mtp_enabled and KV cache compression cannot both be enabled."`

### ANE prefill (Qwen3.5 family)

Offloads prompt prefill to the Apple Neural Engine. **This is a TTFT knob.**

| Field | Default | What it does |
| --- | --- | --- |
| `qwen35_ane_prefill_enabled` | false | Master switch. |
| `qwen35_ane_prefill_sequence_length` | 2048 | ANE tile length. |
| `qwen35_ane_prefill_tail_padding_min_tokens` | 0 | Pad short prompts up to this to use the ANE path. |
| `qwen35_ane_prefill_fraction` | null | Fraction of layers to prefill on ANE. `null` = auto. |
| `qwen35_ane_prefill_shared_fraction` | 1.0 | Fraction of shared layers. |
| `qwen35_ane_prefill_fused_down` | false | Fuse the down projection. |
| `qwen35_ane_prefill_max_layers` | 64 | Layer cap. |
| `qwen35_ane_prefill_dual_ane` | true | Use both ANE partitions. |
| `qwen35_ane_prefill_gdn` | true | Include GDN layers. |
| `qwen35_ane_prefill_gdn_fraction` | 0.50 | Fraction of GDN layers. |
| `qwen35_ane_prefill_gdn_max_layers` | 48 | GDN layer cap. |
| `qwen35_ane_prefill_cpu_enabled` | false | Also use CPU for part of prefill. |
| `qwen35_ane_prefill_cpu_fraction` | 0.135 | CPU layer fraction. |
| `qwen35_ane_prefill_cpu_down_fraction` | 0.0 | CPU down-projection fraction. |
| `qwen35_ane_prefill_cpu_gdn_fraction` | 0.0 | CPU GDN fraction. |
| `qwen35_ane_prefill_cpu_threads` | 8 | CPU threads. |
| `qwen35_ane_prefill_cpu_shared_resource` | true | Share the CPU resource with other work. |

### oQ A8 (Qwen3.5, **M5-series only**)

| Field | Default | What it does |
| --- | --- | --- |
| `qwen35_oq_a8_enabled` | false | INT8-activation prefill. **Kernels refuse to load on M4 and older** — on this M4 Max the setting is refused. Changes numerics. Prefill only. |
| `qwen35_oq_a8_min_tokens` | 128 | Minimum prompt length to use the A8 path. Must be ≥ 1. |

Mutually exclusive with `qwen35_ane_prefill_enabled`.

### MoE expert offload

Keeps a fraction of MoE experts in RAM and streams the rest from SSD. Lets a
model bigger than the memory ceiling run, at a decode-speed cost.

| Field | Default | What it does |
| --- | --- | --- |
| `moe_expert_offload_enabled` | false | Master switch. Only valid when `moe_expert_offload_supported` is true. |
| `moe_expert_offload_resident_fraction` | 0.25 | Fraction of experts kept resident. Higher = faster, more RAM. |

Ask the server for the best value:

```sh
curl -s "$OMLX/admin/api/models/$MODEL/moe-offload-fit" | jq
# 400 {"detail":"Model does not support MoE expert offload: <id>"} when unsupported
```

Optional query params: `mtp_enabled`, `qwen4_ple_ssd_offload`,
`deepseek_v41_engram_ssd_offload`. It returns the largest residency that still
leaves prompt room.

Note `moe_offload_allows_mtp` on the model entry — some MoE models cannot combine
offload with MTP.

### SpecPrefill

Draft-model-assisted prompt compression: a small draft model scores prompt
tokens and the low-value ones are dropped before the big model prefills.
**A TTFT knob for long prompts.**

| Field | Default | What it does |
| --- | --- | --- |
| `specprefill_enabled` | false | Master switch. |
| `specprefill_draft_model` | null | Draft model id. Path is validated. |
| `specprefill_keep_pct` | 0.1–0.5 | Fraction of prompt tokens kept. Lower = faster prefill, more information loss. |
| `specprefill_threshold` | 8192 | Only engage above this prompt length. |

### DFlash (block speculative decoding)

| Field | Default | What it does |
| --- | --- | --- |
| `dflash_enabled` | false | **Reload.** Master switch. Requires `dflash_compatible`. |
| `dflash_draft_model` | null | **Reload.** Draft model id. |
| `dflash_draft_quant_enabled` | false | **Reload.** Quantize the draft model. |
| `dflash_draft_quant_weight_bits` | 2 \| 4 \| 8 | **Reload.** |
| `dflash_draft_quant_group_size` | 32 \| 64 \| 128 | **Reload.** |
| `dflash_draft_window_size` | int \| null | **Reload.** |
| `dflash_block_size` | int \| null | **Reload.** Tokens speculated per step. |
| `dflash_verify_mode` | `adaptive`\|`dflash`\|`off` (`adaptive`) | **Reload.** `ddtree` is accepted and normalized to `adaptive`. |

Mutually exclusive with `mtp_enabled`.

### MTP (multi-token prediction)

| Field | Default | What it does |
| --- | --- | --- |
| `mtp_enabled` | false | Use the model's built-in MTP head for speculative decode. Requires `mtp_compatible`. |
| `mtp_adaptive_max_depth` | 1..8 \| null | Adaptive speculation depth cap. Out of range → **400**. |
| `mtp_fixed_depth` | 1..8 \| null | Fixed depth instead of adaptive. Out of range → **400**. |

`MAX_LIGHTNING_MTP_DRAFT_TOKENS = 8`. Mutually exclusive with `dflash_enabled`.

### VLM MTP

| Field | Default | What it does |
| --- | --- | --- |
| `vlm_mtp_enabled` | false | MTP for vision-language models. |
| `vlm_mtp_draft_model` | null | Draft model. |
| `vlm_mtp_draft_block_size` | int \| null | Block size. |

`vlm_mtp_enabled` is mutually exclusive with **all** of: `dflash_enabled`,
`specprefill_enabled`, `mtp_enabled`, `turboquant_kv_enabled`, and every
processor-backed setting (guided grammar, thinking budget, penalties).

### Model-family SSD offload

| Field | Default | What it does |
| --- | --- | --- |
| `qwen4_ple_ssd_offload` | false | Qwen4 PLE embedding table offload to SSD. Only sticks when `config_model_type == "qwen4_exp"`. |
| `qwen4_gdn_decode_wide_proj` | false | Qwen4 GDN wide projection. Same gate. |
| `deepseek_v41_engram_ssd_offload` | false | DeepSeek V4.1 Engram table offload. Only when `config_model_type == "deepseek_v41"`. |
| `deepseek_v41_ced_prefill_enabled` | false | DeepSeek V4.1 CED prefill. Same gate. |

### Hardware & misc

| Field | Default | What it does |
| --- | --- | --- |
| `gpu_power_limit_w` | int \| null | Cap GPU power draw. Validated. Lower = cooler/quieter, slower. |
| `activation_fp16_enabled` | false | Keep activations in fp16. Only when `activation_fp16_supported`. |
| `trust_remote_code` | false | **Reload.** Allow `trust_remote_code` model code. |
| `embedding_audio_enabled` | false | Audio embeddings for embedding models. |
| `embedding_audio_max_seconds` | > 0 | Audio clip cap. |

## Silent coercion — read this before debugging

Four settings are **silently stored as `False`** when the model family does not
match. No error, no warning, and the response echoes `false`:

| Setting | Required `config_model_type` |
| --- | --- |
| `qwen4_ple_ssd_offload` | `qwen4_exp` |
| `qwen4_gdn_decode_wide_proj` | `qwen4_exp` |
| `deepseek_v41_ced_prefill_enabled` | `deepseek_v41` |
| `deepseek_v41_engram_ssd_offload` | `deepseek_v41` |

If you set one and the response shows `false`, that is why. Check
`config_model_type` on the model entry first.

## Mutual exclusions (enforced in `ModelSettings.__post_init__`)

| Cannot combine | Result |
| --- | --- |
| `mtp_enabled` + `dflash_enabled` | rejected |
| `vlm_mtp_enabled` + any of `dflash_enabled`, `specprefill_enabled`, `mtp_enabled`, `turboquant_kv_enabled` | rejected |
| `vlm_mtp_enabled` + processor-backed settings (guided grammar, thinking budget, penalties) | rejected |
| `qwen35_oq_a8_enabled` + `qwen35_ane_prefill_enabled` | rejected |
| `turboquant_kv_enabled` + `vlm_mtp_enabled` | 400 `"vlm_mtp_enabled and KV cache compression cannot both be enabled."` |
| `qwen35_oq_a8_min_tokens` < 1 | rejected |

## Recommended sampling defaults for a model

```sh
curl -s $OMLX/admin/api/models/$MODEL/generation_config | jq
```

Returns the engine's `recommended_sampling_settings(entry)` merged with
`max_context_window` read from the model's `config.json`
(`max_position_embeddings` / `max_seq_len` / `seq_length` / `n_positions`, with a
nested `text_config` fallback).

404 if the model is unknown or has no config files. Returns `{}` for helper,
cluster, and non-LLM/VLM models.

## Reset to recommended

```sh
curl -s -X POST $OMLX/admin/api/models/$MODEL/settings/reset | jq
```

Resets every field to `engine_pool.recommended_sampling_settings(entry)`.
Response is `{...result, "applied": {...}, "skipped": [...], "changed": bool}`.

## Profiles

A profile is a named settings bundle stored per model.

```sh
# list
curl -s $OMLX/admin/api/models/$MODEL/profiles | jq
# {"profiles":[{"name":"...","display_name":"...","settings":{...},
#               "model_id":"<id>","has_engine_fields":true, ...}]}

# create
curl -s -X POST $OMLX/admin/api/models/$MODEL/profiles \
  -H 'Content-Type: application/json' -d '{
    "name":"coding-fast",
    "display_name":"Coding fast",
    "description":"thinking off, 64k ctx",
    "settings":{"max_context_window":65536,"enable_thinking":false,"temperature":0.2},
    "also_save_as_template":false,
    "expose_as_model":false
  }' | jq
# {"profile":{...}}
# 400 invalid name, 409 conflict

# update
curl -s -X PUT $OMLX/admin/api/models/$MODEL/profiles/coding-fast \
  -H 'Content-Type: application/json' -d '{"display_name":"Coding fast v2"}'
# 404 if missing

# apply
curl -s -X POST $OMLX/admin/api/models/$MODEL/profiles/coding-fast/apply | jq
# {"model_id":"<id>","settings":{...}}

# delete
curl -s -X DELETE $OMLX/admin/api/models/$MODEL/profiles/coding-fast
# {"deleted":true,"name":"coding-fast"}
```

`CreateProfileRequest`: `name`, `display_name`, `api_name?`, `description?`,
`settings{}`, `also_save_as_template` (false), `source_template?`,
`expose_as_model` (false).

`UpdateProfileRequest`: `new_name?`, `display_name?`, `api_name?`,
`description?`, `settings?`, `source_template?`, `expose_as_model?`,
`also_save_as_template` (false).

`expose_as_model: true` makes the profile answer on `/v1/*` as its own model id.

## Profile templates (cross-model)

```sh
curl -s $OMLX/admin/api/profile-templates | jq
```

```json
{"templates":[{"name":"qwen3_8-27b-4bit-mtp","display_name":"Qwen3.8 27B 4bit MTP",
  "description":"...","created_at":"...","updated_at":"...",
  "settings":{"mtp_enabled":true,"max_context_window":65536,"temperature":0.6}}]}
```

```sh
# apply a template to a model
curl -s -X POST $OMLX/admin/api/models/$MODEL/profile-templates/<template>/apply | jq
# {"model_id":"<id>","settings":{...}}

# create / update / delete a template
curl -s -X POST $OMLX/admin/api/profile-templates -H 'Content-Type: application/json' \
  -d '{"name":"my-tpl","display_name":"My template","description":"","settings":{"temperature":0.2}}'
curl -s -X PUT  $OMLX/admin/api/profile-templates/my-tpl -H 'Content-Type: application/json' -d '{"display_name":"Renamed"}'
curl -s -X DELETE $OMLX/admin/api/profile-templates/my-tpl
```

Which fields are allowed in a profile:

```sh
curl -s $OMLX/admin/api/profile-fields | jq
# {"universal":[21 fields],"model_specific":[44 fields]}
```

`universal` (21): `max_context_window max_tokens temperature top_p top_k min_p
repetition_penalty presence_penalty force_sampling enable_thinking
preserve_thinking cache_reasoning_output thinking_budget_enabled
thinking_budget_tokens gpu_power_limit_w reasoning_parser guided_grammar_enabled
guided_grammar max_tool_result_tokens chat_template_kwargs forced_ct_kwargs`

`model_specific` (44): `turboquant_kv_enabled turboquant_kv_scheme
turboquant_kv_bits turboquant_skip_last qwen35_ane_prefill_enabled
qwen35_ane_prefill_sequence_length qwen35_ane_prefill_tail_padding_min_tokens
qwen35_ane_prefill_fraction qwen35_ane_prefill_shared_fraction
qwen35_ane_prefill_fused_down qwen35_ane_prefill_max_layers
qwen35_ane_prefill_dual_ane qwen35_ane_prefill_gdn
qwen35_ane_prefill_gdn_fraction qwen35_ane_prefill_gdn_max_layers
qwen35_ane_prefill_cpu_enabled qwen35_ane_prefill_cpu_fraction
qwen35_ane_prefill_cpu_down_fraction qwen35_ane_prefill_cpu_gdn_fraction
qwen35_ane_prefill_cpu_threads qwen35_ane_prefill_cpu_shared_resource
qwen35_oq_a8_enabled qwen35_oq_a8_min_tokens moe_expert_offload_enabled
moe_expert_offload_resident_fraction dflash_enabled dflash_draft_model
dflash_draft_quant_enabled dflash_draft_quant_weight_bits
dflash_draft_quant_group_size dflash_draft_window_size dflash_block_size
dflash_verify_mode mtp_enabled mtp_adaptive_max_depth mtp_fixed_depth
vlm_mtp_enabled vlm_mtp_draft_model vlm_mtp_draft_block_size
specprefill_enabled specprefill_draft_model specprefill_keep_pct
specprefill_threshold index_cache_freq`

## Recipes (shareable settings snapshots)

A recipe is a compressed, base64url-encoded settings snapshot:
`omlx-recipe:1:<base64url(zlib.compress(json,9))>`.

```sh
curl -s -X POST $OMLX/admin/api/models/$MODEL/settings/recipe \
  -H 'Content-Type: application/json' \
  -d '{"recipe":"omlx-recipe:1:eJx..."}' | jq
# {...result, "applied":{...}, "skipped":[...], "changed":true}
```

Limits: 9000 chars in the request, 8192 encoded / 16384 decoded bytes, 120 keys,
500-char string values. Version must be `1`. `guided_grammar*` is never imported
from a snapshot — it appears in `skipped`.

## Optimal settings from the omlx.ai benchmark database

```sh
curl -s $OMLX/admin/api/models/$MODEL/settings/optimal | jq
```

```json
{"found":true,"model_name":"...",
 "device":{"chip_name":"Apple M4 Max","chip_variant":"Max","memory_gb":128},
 "context_length":131072,
 "by_pp":[{"benchmark_id":"abc123","pp":8192,"tg":128,"ttft_ms":1234.5,"gen_tps":36.2,"settings":{...}}],
 "by_tg":[...],
 "search_url":"https://omlx.ai/..."}
```

Apply one row's snapshot:

```sh
curl -s -X POST $OMLX/admin/api/models/$MODEL/settings/optimal \
  -H 'Content-Type: application/json' -d '{"benchmark_id":"abc123"}' | jq
```

`benchmark_id` must match `^[a-z0-9]{1,16}$`. 400 if that row has no settings
snapshot. Both endpoints proxy omlx.ai and need network access.

## Load / unload

```sh
# load
curl -s -X POST $OMLX/admin/api/models/$MODEL/load | jq
# {"status":"ok","model_id":"<id>","message":"Loaded <id>"}
# or {"status":"ok","model_id":"<id>","message":"Already loaded: <id>"}
# 409 {"detail":"Model is already loading: <id>"}
# 404 {"detail":"Model not found: <id>"}
# 503 if the engine pool is not initialized
# 500 on load failure (e.g. ModelTooLargeError)

# unload
curl -s -X POST $OMLX/admin/api/models/$MODEL/unload | jq
# {"status":"ok","model_id":"<id>","message":"Unloaded <id>"}
# 202 {"status":"unloading","model_id":"<id>",
#      "message":"Aborting active requests before unloading <id>"}
# 400 if not loaded, 409 if still loading
```

A **202** means requests were in flight and are being aborted. Poll
`GET /admin/api/models` until `loaded` is false.

## Re-discover models

```sh
curl -s -X POST $OMLX/admin/api/reload
# {"status":"ok","message":"Re-discovered 0 models from 2 directories"}
```

Safe and idempotent. Preloads pinned models. Run it after a download completes.

## Memory ceiling

Never hardcode the ceiling — it is recomputed on every read:

```sh
curl -s $OMLX/api/status | jq '{model_memory_max, model_memory_max_gb: (.model_memory_max/1073741824*100|floor/100)}'
# {"model_memory_max":96251467006,"model_memory_max_gb":89.64}
```

Observed values drift between 89.2 and 90.1 GB on this machine. Compare against
`estimated_size` / `actual_size` on the model entry before loading.

## Tuning order for coding workloads (TTFT-first)

1. `max_context_window` — cut it to what the task actually needs.
2. `enable_thinking` / `thinking_budget_tokens` — off or capped.
3. `max_tool_result_tokens` — truncate tool output.
4. `specprefill_enabled` — long prompts only.
5. `mtp_enabled` or `dflash_enabled` — decode speed, not TTFT.
6. `moe_expert_offload_*` — only if the model does not fit.
7. `turboquant_kv_*` — buy context with quality.
8. Sampling (`temperature`, `top_p`, `min_p`) — last.

## Not verifiable without a loaded model

Documented from source, **not** executed here:

- `PUT .../settings` success response (only 404 and 422 were verified).
- `requires_reload` / `auto_unloaded` / `auto_reloaded` / `reload_deferred` in a
  real response.
- `load` / `unload` success and 202 paths.
- Profiles CRUD success paths (only 404 on the virtual model was verified).
- `settings/reset`, `settings/recipe`, `settings/optimal` success paths.
- `generation_config` success (404 verified on the virtual model).
- `moe-offload-fit` success (400 verified on the virtual model).

Verified live: the 405 on `GET .../settings`, the 422 `extra_forbidden` shape,
the 404 `{"detail":"Model not found: MarkItDown"}` on every per-model route for
the virtual model, `GET /admin/api/profile-fields`, `GET
/admin/api/profile-templates`, `POST /admin/api/reload`, and the dynamic
`model_memory_max`.
