# oMLX 0.7.3rc1 — API Reference

Compact but complete reference for the oMLX HTTP API, derived from the shipped
Python source at `/Applications/oMLX.app/Contents/Resources/omlx/` and verified
live against a running server on `http://127.0.0.1:8001`.

Everything marked **verified** was executed against the live server. Everything
marked **unverified** requires a real (non-virtual) model to be downloaded and
loaded, which was out of scope for this reference.

---

## 1. Conventions

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=http://127.0.0.1:8001
```

### Base URL and route families

| Prefix | Purpose |
| --- | --- |
| `/api/*` | Public status/health (`/api/status`) |
| `/admin/api/*` | Admin control plane (models, settings, downloads, benchmarks) |
| `/v1/*` | OpenAI-compatible inference (`/v1/chat/completions`, `/v1/models`, …) |
| `/tokenize`, `/detokenize` | Also aliased as `/v1/tokenize`, `/v1/detokenize` |

### Authentication

`require_admin` (`admin/auth.py:386`) short-circuits to **allowed** when *both*
of these hold:

1. `global_settings.auth.skip_api_key_verification == True`
2. the server is bound to a loopback address (`is_loopback_bind`, `utils/network.py:131`)

This machine satisfies both (`server.host = "127.0.0.1"`,
`auth.skip_api_key_verification = true`), so **all `/admin/api/*` calls work
unauthenticated**. Verified.

Other accepted credentials, in order:

- `Cookie: omlx_admin_session=<token>` (set by `POST /api/login`)
- `Authorization: Bearer <api_key>`

`network_auth_error` refuses to let `skip_api_key_verification` be enabled on a
non-loopback bind, so this bypass cannot leak onto the LAN.

`allow_unauthenticated_inference` is a **separate** flag governing `/v1/*`
(currently `false`; inference still works because of the loopback bypass).

### Error shapes

Two distinct shapes exist:

```jsonc
// FastAPI HTTPException — most admin routes
{"detail": "Model not found: MarkItDown"}

// Pydantic validation failure (422) — request body rejected
{"detail": [{"type": "extra_forbidden", "loc": ["body", "bogus_field"],
             "msg": "Extra inputs are not permitted", "input": 1}]}

// OpenAI-style — /v1/* and /tokenize
{"error": {"message": "Model 'MarkItDown' not found. Available models: (none)",
           "type": "not_found_error", "param": null, "code": null}}
```

Bench validation errors arrive as a **400** whose `detail` is the raw pydantic
message string (not a list):

```json
{"detail":"1 validation error for BenchmarkRequest\nprompt_lengths\n  Value error, Invalid prompt length 1234. Must be one of [1024, 4096, 8192, 16384, 32768, 65536, 131072, 200000] [type=value_error, input_value=[1234], input_type=list]\n    For further information visit https://errors.pydantic.dev/2.14/v/value_error"}
```

---

## 2. Server lifecycle and health

### `GET /api/status` — verified

```sh
curl -s $OMLX/api/status | jq
```

```json
{
  "status": "ok",
  "version": "0.7.3rc1",
  "uptime_seconds": 324.6,
  "models_discovered": 0,
  "models_loaded": 0,
  "models_loading": 0,
  "default_model": null,
  "loaded_models": [],
  "total_requests": 0,
  "active_requests": 0,
  "waiting_requests": 0,
  "total_prompt_tokens": 0,
  "total_completion_tokens": 0,
  "total_cached_tokens": 0,
  "cache_efficiency": 0.0,
  "avg_prefill_tps": 0.0,
  "avg_generation_tps": 0.0,
  "model_memory_used": 0,
  "model_memory_max": 96693283900,
  "model_memory_used_formatted": "0B",
  "model_memory_max_formatted": "90.05GB",
  "custom_kernels": {
    "attention": {"available": true, "import_error": null},
    "lowbit": {"available": true, "import_error": null},
    "quant_matmul": {"available": true, "import_error": null},
    "sparse_index": {"available": true, "import_error": null}
  },
  "ane_prefill": {"patch_available": true, "configured_models": 0, "models": []}
}
```

> **`model_memory_max` is dynamic.** Observed values across one session:
> 89.25 → 89.73 → 89.60 → 89.64 → 90.05 GB. It tracks current system pressure.
> Never hardcode it; read it live.

### `GET /admin/api/global-settings` — verified

Returns the whole `settings.json` tree. Top-level keys:

```
base_path, server, model, memory, scheduler, cache, mcp, usage, huggingface,
modelscope, network, sampling, auth, claude_code, integrations,
external_engines, system, ui, idle_timeout
```

Relevant sub-objects on this machine:

```json
{
  "server": {"host": "127.0.0.1", "port": 8001, "log_level": "info",
             "server_aliases": ["localhost", "127.0.0.1", "coremacmax.local", "192.168.10.121"],
             "sse_keepalive_mode": "chunk", "auto_start_on_launch": true,
             "burst_decode_mode": "aggressive", "preserve_mid_system_cache": true,
             "gpu_keep_warm_interval": 0.5, "distributed_inference_enabled": false,
             "distributed_inference_active": false, "max_audio_upload_size": "100MB"},
  "memory": {"prefill_memory_guard": true, "memory_guard_tier": "balanced",
             "memory_guard_custom_ceiling_gb": 0.0},
  "sampling": {"max_context_window": 32768, "max_context_window_policy": null,
               "max_tokens": 32768, "temperature": 1.0, "top_p": 0.95,
               "top_k": 0, "repetition_penalty": 1.0},
  "model": {"model_dirs": ["/Users/core/.omlx/models/mlx-community"],
            "model_dir": "/Users/core/.omlx/models/mlx-community",
            "effective_model_dirs": ["/Users/core/.omlx/models/mlx-community",
                                     "/Users/core/.cache/huggingface/hub"],
            "model_fallback": false, "hide_helper_models": false},
  "cache": {"enabled": true, "ssd_cache_dir": "/Users/core/.omlx/cache",
            "ssd_cache_max_size": "185GB", "ssd_cache_auto_size_bytes": 343803785856,
            "hot_cache_only": false, "hot_cache_write_through": false,
            "ane_compile_cache": false, "gdn_snapshot_storage": "auto",
            "gdn_ssd_split_enabled": true, "gdn_ssd_pending_max_size": "512MB",
            "gdn_sidecar_precision": "fp32", "hot_cache_max_size": "0",
            "initial_cache_blocks": 256},
  "auth": {"api_key_set": true, "api_key": "<redacted>",
           "skip_api_key_verification": true,
           "allow_unauthenticated_inference": false, "sub_keys": []},
  "idle_timeout": {"idle_timeout_seconds": 900}
}
```

### `POST /admin/api/reload` — verified

Re-discovers models from the configured directories and preloads pinned ones.
Safe and idempotent; use it after a download completes.

```sh
curl -s -X POST $OMLX/admin/api/reload
# {"status":"ok","message":"Re-discovered 0 models from 2 directories"}
```

500 on failure.

### `POST /api/login`

Body `{"api_key": "...", "remember": false}`. 400 if no API key is configured,
401 on invalid key, 429 on lockout. Sets the `omlx_admin_session` cookie.

---

## 3. Model inventory

### `GET /admin/api/models` — verified

```sh
curl -s $OMLX/admin/api/models | jq '.models[] | {id, loaded, engine_type, model_type}'
```

Response wrapper is `{"models": [...]}`. Each entry carries:

| Group | Keys |
| --- | --- |
| Identity | `id`, `model_path`, `display_name`, `source_type`, `source_repo_id`, `model_format`, `source_path` |
| State | `loaded`, `is_loading`, `pinned`, `is_default`, `is_hidden`, `is_favorite`, `is_helper`, `last_access` |
| Size | `estimated_size`, `estimated_size_formatted`, `actual_size`, `actual_size_formatted` |
| Type | `engine_type`, `model_type`, `config_model_type`, `model_context_length`, `thinking_default`, `preserve_thinking_default`, `reasoning_efforts` |
| Capability | `dflash_compatible`, `dflash_compatibility_reason`, `mtp_compatible`, `mtp_compatibility_reason`, `moe_expert_offload_supported`, `moe_offload_allows_mtp`, `activation_fp16_supported`, `is_paroquant`, `paroquant_reason` |
| Qwen4 PLE | `qwen4_ple_ssd_offload_supported`, `qwen4_ple_ssd_offload_forced`, `qwen4_ple_resident_bytes`, `qwen4_ple_mmap_bytes` |
| DeepSeek V4.1 | `deepseek_v41_engram_ssd_offload_supported`, `deepseek_v41_engram_ssd_offload_forced`, `deepseek_v41_engram_resident_bytes`, `deepseek_v41_engram_mmap_bytes` |
| Cluster | `distributed`, `cluster`, `external_engines` |
| Settings | `settings` (full `ModelSettings.to_dict()`), `exposed_profiles` |

A **virtual builtin** entry is always appended:

```json
{"id":"MarkItDown","model_path":"builtin://markitdown","display_name":"MarkItDown",
 "loaded":true,"is_loading":false,"estimated_size":0,"estimated_size_formatted":"0 B",
 "actual_size":0,"actual_size_formatted":null,"pinned":false,"is_default":false,
 "engine_type":"markitdown","model_type":"markitdown","config_model_type":"markitdown",
 "thinking_default":null,"preserve_thinking_default":null,"source_type":"builtin",
 "source_repo_id":null,"last_access":null,"external_engines":[],
 "dflash_compatible":false,"dflash_compatibility_reason":"",
 "mtp_compatible":false,"mtp_compatibility_reason":"",
 "is_paroquant":false,"paroquant_reason":"","virtual":true}
```

It has **no `settings` key** and is **not** in the engine pool, so every
per-model route returns `404 {"detail":"Model not found: MarkItDown"}` for it.

### `GET /v1/models` — verified

```json
{"object":"list","data":[{"id":"MarkItDown","object":"model",
  "created":1793241149,"owned_by":"omlx","max_model_len":null}]}
```

### `GET /v1/models/status` — verified

```json
{"final_ceiling":96810003750,"current_model_memory":0,"model_count":1,
 "loaded_count":1,"load_seconds_per_gb_estimate":null,"load_time_observations":0,
 "models":[{"id":"MarkItDown","model_path":"builtin://markitdown","loaded":true,
   "is_loading":false,"loading_started_at":null,"estimated_size":0,"actual_size":0,
   "pinned":false,"engine_type":"markitdown","model_type":"markitdown",
   "config_model_type":"markitdown","thinking_default":null,
   "preserve_thinking_default":null,"source_type":"builtin","source_repo_id":null,
   "last_access":null,"max_context_window":null,"max_tokens":null,
   "is_favorite":false,"is_hidden":false}]}
```

`final_ceiling` is the memory ceiling the admission controller will enforce.

---

## 4. Hugging Face download

Implementation: `admin/hf_downloader.py`. Routes: `admin/routes.py:7803+`.

### `POST /admin/api/hf/download`

```jsonc
{
  "repo_id": "owner/model",   // required, exactly two path segments
  "hf_token": "",             // optional; empty = anonymous
  "files": null               // null = whole repo; or ["config.json", "model.safetensors", ...]
}
```

Response:

```json
{"success": true, "task": { /* DownloadTask.to_dict() */ }}
```

**Where files land:** `<model_dir>/<repo_id>`, i.e.
`/Users/core/.omlx/models/mlx-community/<owner>/<model>`.

Behaviour:

- Only **one download runs at a time** (semaphore). Others sit at `pending`.
- A second in-progress download for the same repo (case-insensitive) → **400**.
- Invalid `repo_id` (not exactly 2 segments, or containing `.`/`..`) → **400**:

```json
{"detail":"Invalid repository ID: 'notarepo'. Expected format: 'owner/model' (e.g., 'mlx-community/Llama-3-8B-4bit')"}
```

### `GET /admin/api/hf/tasks` — verified

```sh
curl -s $OMLX/admin/api/hf/tasks | jq
```

```json
{"tasks":[{"task_id":"de40277a-5178-44d7-8112-4c2e4aba27e2",
  "repo_id":"Jundot/Qwen3.8-27B-oQ4e-mtp","status":"downloading","progress":14.9,
  "total_size":16994900596,"downloaded_size":2533897434,"speed_bps":32767156.3,
  "eta_seconds":373,"error":"","created_at":1793241068.296722,
  "started_at":1793241068.299349,"completed_at":0.0,"retry_count":0,
  "files":null,"gguf_files":[],"gguf_model_id":null}]}
```

`status` ∈ `pending | downloading | completed | failed | cancelled`.
`progress` is a percentage (0–100). `eta_seconds` is `null`/absent when unknown.
`eta_speed_bps` and `token` exist on the dataclass but are **never serialized**.

### `POST /admin/api/hf/cancel/{task_id}`

`{"success": true}` or **404** `{"detail":"Task not found or not cancellable"}`.

### `POST /admin/api/hf/retry/{task_id}`

Body `{"hf_token": ""}`. Resumes from files already on disk; increments
`retry_count`.

### `DELETE /admin/api/hf/task/{task_id}`

Removes a **completed/failed/cancelled** task row. **404**
`{"detail":"Task not found or still active"}` otherwise.

### `DELETE /admin/api/hf/models/{model_name}`

Deletes the model from disk, cancels any in-flight download writing there,
unloads it if loaded, and refreshes the pool. **404** `{"detail":"Model not found"}`.

### `GET /admin/api/hf/models` — verified

```json
{"models":[{"name":"Qwen3.8-27B-oQ4e-mtp",
  "path":"/Users/core/.omlx/models/mlx-community/Jundot/Qwen3.8-27B-oQ4e-mtp",
  "display_name":"Jundot/Qwen3.8-27B-oQ4e-mtp","size":417247417,
  "size_formatted":"397.9 MB","repo_id":"Jundot/Qwen3.8-27B-oQ4e-mtp",
  "source_type":"local"}]}
```

`source_type` ∈ `local | hf_cache | builtin`. GGUF rows add `model_format`.

### `GET /admin/api/hf/search` — verified

Query params: `q` (**required**), `sort`, `limit` (capped at 100),
`mlx_only`, `model_format` (`mlx|gguf|all`), `min_params`, `max_params`,
`min_size`, `max_size`, `sort_by_size`, `sort_ascending`.

```sh
curl -s "$OMLX/admin/api/hf/search?q=qwen3&limit=2" | jq
```

```json
{"models":[
  {"repo_id":"OBLITERATUS/Qwen3.8-27B-OBLITERATED","name":"OBLITERATUS/Qwen3.8-27B-OBLITERATED",
   "architecture":"qwen35","downloads":509909,"likes":1578,"trending_score":44,
   "size":55562855904,"size_formatted":"51.7 GB","params":27781427952,"params_formatted":"27.8B"},
  {"repo_id":"orcarouter/Qwen3.8-27B-Uncensored-MLX","name":"orcarouter/Qwen3.8-27B-Uncensored-MLX",
   "architecture":null,"downloads":57814,"likes":1604,"trending_score":21,
   "size":94568784658,"size_formatted":"88.1 GB","params":27356728560,"params_formatted":"27.4B"}],
 "total":2,"hf_token_invalid":false}
```

Missing `q` → **400** `{"detail":"Query parameter 'q' is required"}`.

### `GET /admin/api/hf/model-info?repo_id=...` — verified

Optional `X-HF-Token` header. Top-level keys:

```
repo_id, name, model_card, description, files, layout, download_all_size,
unsupported_reason, tags, pipeline_tag, params, params_formatted, size,
size_formatted, downloads, likes, created_at, updated_at, is_adapter, disk_free
```

Each `files[]` entry:

```json
{"name":"config.json","size":939,"size_formatted":"0.9 KB","group":null,
 "mmproj":null,"kind":"other","required":true,"preselected":true,"local":false}
```

`kind` distinguishes weights / tokenizer / other; `required` and `preselected`
drive the default file selection; `local` is true when the file already exists
on disk. `disk_free` is the free bytes on the model volume.

Missing `repo_id` → **400** `{"detail":"Query parameter 'repo_id' is required"}`.

### `GET /admin/api/hf/recommended` — verified

`{"trending":[{repo_id, name, architecture, downloads, likes, trending_score, size, size_formatted, params, params_formatted}, ...]}`

### `GET /admin/api/hf/recommendations` — verified

The authoritative "what fits this exact Mac" endpoint.

```json
{"device":{"chip":"Apple M4 Max","generation":"M4","variant":"Max","gpu_cores":40,
  "memory_bytes":137438953472,"bandwidth_gbps":546,"prefers_fp16":false},
 "memory":{"total_bytes":137438953472,"tier":"balanced","guard_enabled":true,
  "reserve_bytes":8589934592,"aggressive_reserve_bytes":2748779069,
  "static_ceiling_bytes":128849018880,"wired_limit_set":false,"binding":"metal",
  "suggested_wired_limit_mb":124518,
  "scenarios":{
    "now":{"tier":"balanced","metal_cap_bytes":115448725504,"ceiling_bytes":115448725504,"usable_bytes":105675956551},
    "memory_guard":{"tier":"aggressive","metal_cap_bytes":115448725504,"ceiling_bytes":115448725504,"usable_bytes":111448392826},
    "wired_limit":{"tier":"balanced","metal_cap_bytes":128849018880,"ceiling_bytes":128849018880,"usable_bytes":118004226457},
    "both":{"tier":"aggressive","metal_cap_bytes":130566586368,"ceiling_bytes":130566586368,"usable_bytes":126112717864}}},
 "sections":{"best":[...],"bigger":[],"precise":[...],"faster":[...],"unlock":[...]},
 "author":"Jundot","fetched_at":1793240820.376121,"stale":false,
 "disk":{"model_dir":"/Users/core/.omlx/models/mlx-community","free_bytes":489263915008}}
```

Each `sections.*[]` row:

```json
{"repo_id":"Jundot/Qwen3.8-27B-oQ4e-mtp","name":"Qwen3.8-27B","model_type":"qwen3_5",
 "level":4.0,"fp16":false,"mtp":true,"vision":true,"audio":false,"moe":false,
 "total_params":27781427952,"active_params":27781427952,"downloads":31041,
 "download_bytes":16971681558,"resident_bytes":17820265635,"table_on_ssd":false,
 "table_bytes":0,"max_context":262144,"model_max_context":262144,"smarts":4.737,
 "smarts_level":3.0,"speed_level":4,"tokens_per_second":36.2,
 "base_name":"Qwen3.8-Flash-Next","relative_speed":0.7}
```

`unlock` rows additionally carry `kind` (`fits` | `table_in_memory`) and
`needs` (e.g. `["wired_limit"]`).

---

## 5. Per-model settings

### Reading settings

> **There is no `GET /admin/api/models/{id}/settings`.** It returns
> **405** `{"detail":"Method Not Allowed"}`. Verified.

Read settings from `GET /admin/api/models` and pick the entry:

```sh
curl -s $OMLX/admin/api/models \
  | jq '.models[] | select(.id=="<model_id>") | .settings'
```

### `PUT /admin/api/models/{id}/settings`

Body is `ModelSettingsRequest` (`admin/routes.py:356`) with
`model_config = ConfigDict(extra="forbid")` — **any unknown field is a 422**.

```json
{"detail":[{"type":"extra_forbidden","loc":["body","bogus_field"],
            "msg":"Extra inputs are not permitted","input":1}]}
```

**Partial-update semantics:** the handler inspects
`request.model_fields_set`. A field that is *absent* is left untouched; a field
that is *present and `null`* is reset to its default. So
`{"temperature": 0.2}` changes only temperature, while
`{"thinking_budget_tokens": null}` clears it.

Response:

```json
{"success": true,
 "model_id": "<id>",
 "settings": { /* full ModelSettings.to_dict() */ },
 "model_type": "llm",
 "engine_type": "mlx",
 "requires_reload": false,
 "auto_unloaded": false,
 "auto_reloaded": false,
 "reload_deferred": false}
```

**Unverified** (needs a real model): the success path above. The 404/422 paths
are verified.

#### `requires_reload`

`requires_reload` is true when the model is loaded **and** any of:

- `model_type_override` was sent and the resulting `engine_type` changed
- the engine runtime signature changed (`_engine_runtime_signature`,
  `engine_pool.py:1243` — covers all ANE-prefill controls and other
  engine-construction fields)
- any of these were sent: `index_cache_freq`, `dflash_enabled`,
  `dflash_draft_model`, `dflash_draft_quant_enabled`,
  `dflash_draft_quant_weight_bits`, `dflash_draft_quant_group_size`,
  `dflash_draft_window_size`, `dflash_block_size`, `dflash_verify_mode`,
  `trust_remote_code`

When true the server calls `request_unload(abort_active=False)`. If the engine
is busy the unload is deferred and `reload_deferred` becomes `true`. If the
model was pinned and got unloaded, it is reloaded immediately and
`auto_reloaded` becomes `true`.

#### Silent model-family coercion

These fields are **silently stored as `false`** unless the model's
`config_model_type` matches — no error is raised:

| Field | Required `config_model_type` |
| --- | --- |
| `qwen4_ple_ssd_offload` | `qwen4_exp` |
| `qwen4_gdn_decode_wide_proj` | `qwen4_exp` |
| `deepseek_v41_ced_prefill_enabled` | `deepseek_v41` |
| `deepseek_v41_engram_ssd_offload` | `deepseek_v41` |

#### Other validation rules

- `max_tool_result_tokens`, `thinking_budget_tokens`: `0` or `null` → stored as `None` (disabled).
- `mtp_adaptive_max_depth`, `mtp_fixed_depth`: must be `1..8`
  (`MAX_LIGHTNING_MTP_DRAFT_TOKENS = 8`) or `null`, else **400**.
- `model_alias`: empty string → `None`. Conflicts with another model's alias, a
  model directory name, or an exposed profile → **400**.
- `model_type_override` on a GGUF model → **400** `"A GGUF model's type comes from its file"`.
  Valid values: `llm, vlm, embedding, reranker, audio_stt, audio_tts, audio_sts, decision`.
- `turboquant_kv_bits` ∈ `{2, 2.5, 3, 3.5, 4, 6, 8}`.
- `gpu_power_limit_w` is range-validated.
- `dflash_verify_mode` ∈ `{adaptive, dflash, off}`; the legacy value `ddtree` is
  normalized to `adaptive`.
- `reasoning_parser` must be a known xgrammar builtin (`qwen`, `harmony`, `llama`, …).

#### Mutual exclusions (enforced in `ModelSettings.__post_init__`)

- `mtp_enabled` **XOR** `dflash_enabled`
- `vlm_mtp_enabled` **XOR** {`dflash_enabled`, `specprefill_enabled`,
  `mtp_enabled`, `turboquant_kv_enabled`}
- `vlm_mtp_enabled` **XOR** processor-backed settings (guided grammar, thinking
  budget, penalties)
- `qwen35_oq_a8_enabled` **XOR** `qwen35_ane_prefill_enabled`
- `turboquant_kv_enabled` + `vlm_mtp_enabled` → **400**
  `"vlm_mtp_enabled and KV cache compression cannot both be enabled."`
- `qwen35_oq_a8_min_tokens` must be ≥ 1

### Full `ModelSettingsRequest` field table

Defaults are the dataclass defaults in `model_settings.py:236`.

#### Sampling and generation

| Field | Type / default | What it does | When to use |
| --- | --- | --- | --- |
| `model_alias` | `str \| None` | Alternate id the model answers to on `/v1/*`. Must be unique across models, model dirs, and exposed profiles. | Short stable name for scripts. |
| `model_type_override` | `"llm"\|"vlm"\|"embedding"\|"reranker"\|"decision"\|None` | Forces the engine type instead of inferring from `config.json`. Rejected for GGUF. | Misdetected architecture. |
| `max_context_window` | `int \| None` | KV-cache context length. Caps how much prompt+output fits. Larger = more KV memory and slower prefill. | **Primary TTFT/memory knob.** 32K–64K is plenty for small coding tasks. |
| `max_tokens` | `int ≥ 1 \| None` | Default completion cap when the request omits `max_tokens`. | Bound worst-case latency. |
| `temperature` | `float \| None` | Sampling temperature. | `0` for deterministic benchmarking; model-card value for real work. |
| `top_p` | `float \| None` | Nucleus sampling. | Model-card value. |
| `top_k` | `int \| None` | Top-k sampling; `0` disables. | Model-card value. |
| `min_p` | `float \| None` | Min-p sampling floor. | Model-card value. |
| `repetition_penalty` | `float \| None` | Repetition penalty. | `1.0` = off. |
| `presence_penalty` | `float \| None` | OpenAI-style presence penalty. | Rarely needed. |
| `force_sampling` | `bool = False` | Apply the configured sampler even when the request omits sampling params (otherwise the model's own generation config wins). | Make a profile's sampling authoritative. |
| `max_tool_result_tokens` | `int \| None` | Truncates tool-result content injected into the prompt. `0`/`null` = disabled. | Agent loops with huge tool outputs — big TTFT saver. |
| `chat_template_kwargs` | `dict \| None` | Extra kwargs passed to `apply_chat_template`. | Enable/disable template features (e.g. `enable_thinking`). |
| `forced_ct_kwargs` | `dict \| None` | Kwargs forced onto every chat-template render, overriding request values. | Pin template behaviour server-side. |
| `ttl_seconds` | `int \| None` | Idle TTL before the model is unloaded. | Free memory between tasks. |
| `index_cache_freq` | `int \| None` | Sparse-index cache rebuild frequency. **Engine-construction field** → forces reload. | Long-context sparse attention tuning. |
| `enable_thinking` | `bool \| None` | Default for reasoning/thinking mode. | **Off for latency-sensitive coding**, on for hard tasks. |
| `preserve_thinking` | `bool \| None` | Keep prior-turn reasoning in context. | Multi-turn reasoning continuity. |
| `cache_reasoning_output` | `bool \| None` | Cache reasoning output for reuse. | Agent loops. |

#### Thinking budget

| Field | Type / default | What it does | When to use |
| --- | --- | --- | --- |
| `thinking_budget_enabled` | `bool = False` | Enables a hard cap on reasoning tokens. | Bound worst-case TTFT on thinking models. |
| `thinking_budget_tokens` | `int \| None` | The cap. `0`/`null` = disabled. | 512–2048 for coding; 8192+ for hard problems. |

#### KV cache compression (TurboQuant)

| Field | Type / default | What it does | When to use |
| --- | --- | --- | --- |
| `turboquant_kv_enabled` | `bool = False` | Quantize the KV cache. Shrinks KV memory, may cost quality. | Only when the model does not fit at the desired context. |
| `turboquant_kv_scheme` | `"turboquant"\|"affine4"\|"affine8"` = `"turboquant"` | Quantization scheme. | `turboquant` is the tuned default. |
| `turboquant_kv_bits` | `2\|2.5\|3\|3.5\|4\|6\|8` = `4` | Bits per KV element. | 4 is the safe point; below 3 hurts quality. |
| `turboquant_skip_last` | `bool = True` | Keep the last N layers unquantized. | Leave on — protects output quality cheaply. |

#### ANE prefill (Qwen3.5 family)

| Field | Type / default | What it does |
| --- | --- | --- |
| `qwen35_ane_prefill_enabled` | `bool = False` | Run prefill on the Apple Neural Engine instead of the GPU. |
| `qwen35_ane_prefill_sequence_length` | `int = 2048` | ANE chunk length. |
| `qwen35_ane_prefill_tail_padding_min_tokens` | `int = 0` | Minimum tail padding. |
| `qwen35_ane_prefill_fraction` | `float \| None` | Fraction of layers offloaded to ANE. |
| `qwen35_ane_prefill_shared_fraction` | `float = 1.0` | Fraction of shared layers. |
| `qwen35_ane_prefill_fused_down` | `bool = False` | Fuse the down projection. |
| `qwen35_ane_prefill_max_layers` | `int = 64` | Layer cap. |
| `qwen35_ane_prefill_dual_ane` | `bool = True` | Use both ANE engines. |
| `qwen35_ane_prefill_gdn` | `bool = True` | Include GDN layers. |
| `qwen35_ane_prefill_gdn_fraction` | `float = 0.50` | GDN layer fraction. |
| `qwen35_ane_prefill_gdn_max_layers` | `int = 48` | GDN layer cap. |
| `qwen35_ane_prefill_cpu_enabled` | `bool = False` | Also use CPU for prefill. |
| `qwen35_ane_prefill_cpu_fraction` | `float = 0.135` | CPU layer fraction. |
| `qwen35_ane_prefill_cpu_down_fraction` | `float = 0.0` | CPU down-projection fraction. |
| `qwen35_ane_prefill_cpu_gdn_fraction` | `float = 0.0` | CPU GDN fraction. |
| `qwen35_ane_prefill_cpu_threads` | `int = 8` | CPU threads. |
| `qwen35_ane_prefill_cpu_shared_resource` | `bool = True` | Share the CPU resource with other work. |

All of these are **engine-construction fields** — changing any forces a reload.

#### oQ A8 activations (Qwen3.5 family)

| Field | Type / default | What it does |
| --- | --- | --- |
| `qwen35_oq_a8_enabled` | `bool = False` | INT8 activations for prefill. **M5-series hardware only** — the kernels refuse to load on M4 and older. Changes numerics. Prefill only. |
| `qwen35_oq_a8_min_tokens` | `int = 128` (≥ 1) | Minimum prompt length before A8 kicks in. |

#### MoE expert offload

| Field | Type / default | What it does | When to use |
| --- | --- | --- | --- |
| `moe_expert_offload_enabled` | `bool = False` | Keep a fraction of MoE experts in host memory / on SSD instead of resident. | Only when the model does not fit resident. Costs decode speed. |
| `moe_expert_offload_resident_fraction` | `float = 0.25` | Fraction of experts kept resident. | Raise it as far as memory allows. |

Use `GET /admin/api/models/{id}/moe-offload-fit` to find the largest residency
that still leaves prompt room.

#### SpecPrefill

| Field | Type / default | What it does |
| --- | --- | --- |
| `specprefill_enabled` | `bool = False` | Draft-model-assisted prefill: a small draft model scores tokens so the big model only prefills the important ones. |
| `specprefill_draft_model` | `str \| None` | Draft model id. |
| `specprefill_keep_pct` | `float` (0.1–0.5) | Fraction of tokens kept. |
| `specprefill_threshold` | `int = 8192` | Prompt length above which SpecPrefill engages. |

#### DFlash (draft-model speculative decode)

| Field | Type / default | What it does |
| --- | --- | --- |
| `dflash_enabled` | `bool = False` | Speculative decoding with a DFlash draft. **Mutually exclusive with `mtp_enabled`.** |
| `dflash_draft_model` | `str \| None` | Draft model id or path. |
| `dflash_draft_quant_enabled` | `bool` | Quantize the draft model. |
| `dflash_draft_quant_weight_bits` | `2\|4\|8` | Draft weight bits. |
| `dflash_draft_quant_group_size` | `32\|64\|128` | Draft quantization group size. |
| `dflash_draft_window_size` | `int \| None` | Draft attention window. |
| `dflash_block_size` | `int \| None` | Draft block size. |
| `dflash_verify_mode` | `"adaptive"\|"dflash"\|"off"` | Verification strategy. `ddtree` is normalized to `adaptive`. |

#### MTP (Lightning MTP / multi-token prediction)

| Field | Type / default | What it does |
| --- | --- | --- |
| `mtp_enabled` | `bool = False` | Use the model's bundled MTP head for speculative decode. **Mutually exclusive with `dflash_enabled`.** |
| `mtp_adaptive_max_depth` | `int 1..8 \| None` | Adaptive draft depth ceiling. |
| `mtp_fixed_depth` | `int 1..8 \| None` | Fixed draft depth. |
| `vlm_mtp_enabled` | `bool = False` | MTP for vision-language models. Mutually exclusive with DFlash, SpecPrefill, MTP, and TurboQuant KV. |
| `vlm_mtp_draft_model` | `str \| None` | VLM draft model. |
| `vlm_mtp_draft_block_size` | `int \| None` | VLM draft block size. |

#### Model-family SSD offload

| Field | Type / default | What it does |
| --- | --- | --- |
| `qwen4_ple_ssd_offload` | `bool = False` | Qwen4 PLE tables on SSD. **Silently forced `false`** unless `config_model_type == "qwen4_exp"`. |
| `qwen4_gdn_decode_wide_proj` | `bool = False` | Wide GDN decode projection. Same coercion. |
| `deepseek_v41_engram_ssd_offload` | `bool = False` | DeepSeek V4.1 Engram tables on SSD. **Silently forced `false`** unless `config_model_type == "deepseek_v41"`. |
| `deepseek_v41_ced_prefill_enabled` | `bool = False` | DeepSeek V4.1 CED prefill. Same coercion. |

#### Hardware and misc

| Field | Type / default | What it does |
| --- | --- | --- |
| `gpu_power_limit_w` | `int \| None` | GPU power cap in watts. Range-validated. |
| `activation_fp16_enabled` | `bool = False` | Float16 activations instead of the default precision. Faster on some models, changes numerics. |
| `external_engine` | `str \| None` | Route this model to an external engine instead of the built-in MLX engine. |
| `reasoning_parser` | `str \| None` | xgrammar reasoning parser (`qwen`, `harmony`, `llama`, …) used to split reasoning from content. |
| `guided_grammar_enabled` | `bool = False` | Constrain output with a grammar. |
| `guided_grammar` | `str \| None` | The grammar itself. **Never imported from recipes/snapshots.** |
| `is_pinned` | `bool = False` | Keep loaded; auto-reload after settings changes. |
| `is_default` | `bool = False` | Default model for requests that omit `model`. |
| `is_hidden` | `bool = False` | Hide from model listings. |
| `is_favorite` | `bool = False` | UI favourite flag. |
| `trust_remote_code` | `bool = False` | Allow `trust_remote_code` at load time. **Engine-construction field** → forces reload. |
| `embedding_audio_enabled` | `bool = False` | Enable audio embedding. |
| `embedding_audio_max_seconds` | `float > 0` | Audio embedding length cap. |
| `display_name` | `str \| None` | UI name. |
| `description` | `str \| None` | UI description. |
| `active_profile_name` | `str \| None` | Which profile is currently applied. |

### `GET /admin/api/models/{id}/generation_config`

Returns the model's recommended sampling settings plus its native context
length, read from `config.json` (`max_position_embeddings` / `max_seq_len` /
`seq_length` / `n_positions`, with a nested `text_config` fallback).

Returns `{}` for helper, cluster, and non-LLM/VLM models. **404** if the model
is unknown or has no config files. **Unverified** (needs a real model).

### `GET /admin/api/models/{id}/moe-offload-fit`

Query params: `mtp_enabled`, `qwen4_ple_ssd_offload`,
`deepseek_v41_engram_ssd_offload`. Returns the largest expert-offload residency
that still leaves prompt room. **400**
`"Model does not support MoE expert offload: <id>"` when unsupported.

### `POST /admin/api/models/{id}/import-mtplx`

Imports an MTPLX side-car MTP head. **400** on `ValueError`.

---

## 6. Load / unload

### `POST /admin/api/models/{id}/load`

| Status | Body |
| --- | --- |
| 200 | `{"status":"ok","model_id":"<id>","message":"Loaded <id>"}` |
| 200 | `{"status":"ok","model_id":"<id>","message":"Already loaded: <id>"}` |
| 404 | `{"detail":"Model not found: <id>"}` |
| 409 | `{"detail":"Model is already loading: <id>"}` |
| 500 | load failure (message from the exception) |
| 503 | `{"detail":"Engine pool not initialized"}` |

**Unverified** success path; 404 verified.

### `POST /admin/api/models/{id}/unload`

| Status | Body |
| --- | --- |
| 200 | `{"status":"ok","model_id":"<id>","message":"Unloaded <id>"}` |
| 202 | `{"status":"unloading","model_id":"<id>","message":"Aborting active requests before unloading <id>"}` |
| 400 | model not loaded |
| 409 | model still loading |

**Unverified** success path; 404 verified.

### Memory errors

`exceptions.py`:

- `ModelTooLargeError` — `Model '<id>' (<size>) does not fit under the <binding> memory ceiling (<ceiling>). <advice>.`
- `InsufficientMemoryError` — current usage leaves no room
- `ModelLoadingError` — `"already being loaded"`
- `ModelUnavailableError`, `ModelBusyError`

---

## 7. Profiles, templates, snapshots, recipes

### `GET /admin/api/models/{id}/profiles`

`{"profiles":[...]}`. Each profile dict gains `model_id` and
`has_engine_fields`. **404** if the model is unknown (verified).

### `POST /admin/api/models/{id}/profiles`

```jsonc
{"name": "coding-fast", "display_name": "Coding fast", "api_name": null,
 "description": null, "settings": {"temperature": 0.2, "max_context_window": 32768},
 "also_save_as_template": false, "source_template": null, "expose_as_model": false}
```

→ `{"profile": {...}}`. **400** invalid name, **409** conflict.

### `PUT /admin/api/models/{id}/profiles/{name}`

```jsonc
{"new_name": null, "display_name": null, "api_name": null, "description": null,
 "settings": {}, "source_template": null, "expose_as_model": null,
 "also_save_as_template": false}
```

→ `{"profile": {...}}`. **404** if missing.

### `DELETE /admin/api/models/{id}/profiles/{name}`

→ `{"deleted": true, "name": "..."}`. **404** if missing.

### `POST /admin/api/models/{id}/profiles/{name}/apply`

→ `{"model_id": "...", "settings": {...}}`. **400**/**404**.

### `POST /admin/api/models/{id}/profile-templates/{name}/apply`

→ `{"model_id": "...", "settings": {...}}`. **400**/**404**.

### `GET /admin/api/profile-fields` — verified

```json
{"universal":["max_context_window","max_tokens","temperature","top_p","top_k",
  "min_p","repetition_penalty","presence_penalty","force_sampling",
  "enable_thinking","preserve_thinking","cache_reasoning_output",
  "thinking_budget_enabled","thinking_budget_tokens","gpu_power_limit_w",
  "reasoning_parser","guided_grammar_enabled","guided_grammar",
  "max_tool_result_tokens","chat_template_kwargs","forced_ct_kwargs"],
 "model_specific":["turboquant_kv_enabled","turboquant_kv_scheme",
  "turboquant_kv_bits","turboquant_skip_last","qwen35_ane_prefill_enabled",
  "qwen35_ane_prefill_sequence_length","qwen35_ane_prefill_tail_padding_min_tokens",
  "qwen35_ane_prefill_fraction","qwen35_ane_prefill_shared_fraction",
  "qwen35_ane_prefill_fused_down","qwen35_ane_prefill_max_layers",
  "qwen35_ane_prefill_dual_ane","qwen35_ane_prefill_gdn",
  "qwen35_ane_prefill_gdn_fraction","qwen35_ane_prefill_gdn_max_layers",
  "qwen35_ane_prefill_cpu_enabled","qwen35_ane_prefill_cpu_fraction",
  "qwen35_ane_prefill_cpu_down_fraction","qwen35_ane_prefill_cpu_gdn_fraction",
  "qwen35_ane_prefill_cpu_threads","qwen35_ane_prefill_cpu_shared_resource",
  "qwen35_oq_a8_enabled","qwen35_oq_a8_min_tokens","moe_expert_offload_enabled",
  "moe_expert_offload_resident_fraction","dflash_enabled","dflash_draft_model",
  "dflash_draft_quant_enabled","dflash_draft_quant_weight_bits",
  "dflash_draft_quant_group_size","dflash_draft_window_size","dflash_block_size",
  "dflash_verify_mode","mtp_enabled","mtp_adaptive_max_depth","mtp_fixed_depth",
  "vlm_mtp_enabled","vlm_mtp_draft_model","vlm_mtp_draft_block_size",
  "specprefill_enabled","specprefill_draft_model","specprefill_keep_pct",
  "specprefill_threshold","index_cache_freq"]}
```

`universal` = 21 fields safe to share across models. `model_specific` = 45
fields that only make sense for a matching architecture.

### `GET /admin/api/profile-templates` — verified

```json
{"templates":[{"name":"nemotronlongcoding","display_name":"nemotronlongcoding",
  "description":null,"created_at":"2026-08-14T20:22:11.339923+00:00",
  "updated_at":"2026-08-14T20:22:11.339923+00:00",
  "settings":{"max_tool_result_tokens":0,"max_tokens":4096,
    "thinking_budget_tokens":8192,"top_p":0.9,"force_sampling":true,
    "enable_thinking":true,"temperature":0.105,"top_k":40,
    "thinking_budget_enabled":false,"max_context_window":32768,"min_p":0}}]}
```

### `POST /admin/api/profile-templates`

`{"name","display_name","description","settings"}` → `{"template": {...}}`.
`PUT`/`DELETE /admin/api/profile-templates/{name}` mirror it.

### `POST /admin/api/models/{id}/settings/reset`

Resets every field to `engine_pool.recommended_sampling_settings(entry)`.

### `POST /admin/api/models/{id}/settings/recipe`

```json
{"recipe": "omlx-recipe:1:<base64url>"}
```

Max 9000 chars. Applies the decoded snapshot, dropping unsupported features
(reported in `skipped`).

Recipe codec (`admin/recipe.py`): `omlx-recipe:<version>:<base64url(zlib.compress(json, 9))>`.
Version must be `1`. Limits: 8192 encoded chars, 16384 decoded bytes, 120 keys,
500-char string values. `guided_grammar*` is in `SNAPSHOT_EXCLUDED_FIELDS` and is
never imported.

### `GET /admin/api/models/{id}/settings/optimal`

Proxies omlx.ai for community benchmark rows matching this model + device.

```json
{"found": true, "model_name": "...",
 "device": {"chip_name": "...", "chip_variant": "...", "memory_gb": 128},
 "context_length": 32768, "by_pp": [...], "by_tg": [...], "search_url": "..."}
```

**404** if the model is unknown (verified).

### `POST /admin/api/models/{id}/settings/optimal`

```json
{"benchmark_id": "abc123"}
```

`benchmark_id` must match `^[a-z0-9]{1,16}$`. Applies that benchmark row's
`model_settings` snapshot. **400** if the row has no snapshot.

All three snapshot endpoints (`reset`, `recipe`, `optimal` POST) return:

```json
{ /* endpoint-specific result */, "applied": {...}, "skipped": [...], "changed": true }
```

### `POST /admin/api/presets/refresh`

Proxies the omlx.ai preset bundle. **502** on failure.

---

## 8. Benchmarks

Two independent benchmark families. **Only one benchmark of any kind may run at
a time** — a second `start` returns **409**.

### Throughput benchmark

#### `POST /admin/api/bench/start`

Body = `BenchmarkRequest` (`admin/benchmark.py:109`):

```jsonc
{
  "model_id": "<id>",              // required
  "prompt_lengths": [1024, 4096],  // subset of VALID_PROMPT_LENGTHS
  "generation_length": 128,        // tokens to generate per test
  "batch_sizes": [],               // subset of VALID_BATCH_SIZES
  "context_profile": "code_python",
  "warmup_mode": "quick",
  "align_prompt_to_ane": false,
  "force_lm_engine": false,
  "external": null
}
```

| Constant | Values |
| --- | --- |
| `VALID_PROMPT_LENGTHS` | `1024, 4096, 8192, 16384, 32768, 65536, 131072, 200000` |
| `VALID_BATCH_SIZES` | `2, 4, 8` |
| `context_profile` | `code_python`, `code_mixed`, `novel_ko`, `novel_en`, `novel_ja` |
| `warmup_mode` | `quick`, `ane_2048` |

Response:

```json
{"bench_id": "a1b2c3", "status": "started", "total_tests": 4}
```

`total_tests = len(prompt_lengths) + len(batch_sizes) * 2`.

Errors: **409** if any benchmark is already running; **404**
`{"detail":"Model not found: <id>"}`; **400** with the pydantic message in
`detail` for validation failures (verified).

#### `GET /admin/api/bench/{bench_id}/stream`

Server-Sent Events. Each event is `data: {json}\n\n`; keepalives are
`: keepalive`. The stream replays buffered events first, then attaches live.

Event types:

| `type` | Payload |
| --- | --- |
| `progress` | `{type, phase, message, current, total}` |
| `result` | `{type:"result", data:{...}}` |
| `done` | `{type:"done", summary:{model_id, context_profile, total_time, total_tests}}` |
| `upload` / `upload_done` / `upload_skipped` | upload phase bookkeeping |
| `error` | `{type:"error", ...}` |

Phases: `idle`, `upload`, `unload`, `load`, `warmup`, `single`, `batch`, `cleanup`.

#### `GET /admin/api/bench/{bench_id}/results`

```json
{"bench_id":"a1b2c3","status":"completed","context_profile":"code_python",
 "results":[...],"error":null,"upload_state":null}
```

**404** `{"detail":"Benchmark not found: <id>"}` (verified).

#### `POST /admin/api/bench/{bench_id}/cancel`

`{"status":"cancelled","bench_id":"a1b2c3"}`. **404** if unknown (verified).

#### `GET /admin/api/bench/active` — verified

```json
{"running":false,"bench_id":null,"model_id":null,"context_profile":null}
```

(also carries `force_lm_engine` and `external` when running)

#### Result shapes

Single test (`_compute_single_metrics`, `admin/benchmark.py:613`):

```json
{"test_type":"single","pp":4096,"tg":128,
 "ttft_ms":412.3,"tpot_ms":18.42,"gen_tps":54.3,"processing_tps":9938.1,
 "e2e_latency_s":2.771,"total_throughput":1523.4,
 "peak_memory_bytes":17820265635,"prompt_tokens":4096,
 "completion_tokens":128,"cached_tokens":0,"system_metrics":{...}}
```

Rounding: `ttft_ms` 1dp, `tpot_ms` 2dp, `gen_tps` 1dp, `processing_tps` 1dp,
`e2e_latency_s` 3dp, `total_throughput` 1dp.

Null rules:

- `gen_tps` and `tpot_ms` are `null` when `completion_tokens < 16`
  (`_MIN_TG_TOKENS = 16`) or generation timing was not measured.
- `ttft_ms` and `processing_tps` are `null` when the first token was never observed.

Batch test:

```json
{"test_type":"batch","pp":1024,"tg":128,"pp_tps":...,"tg_tps":...,
 "avg_ttft_ms":...,"e2e_latency_s":...,"peak_memory_bytes":...,
 "total_gen_tokens":...,"batch_size":4}
```

### Context benchmark

#### `POST /admin/api/bench/context/start`

```json
{"model_id": "<id>", "target_tokens": 131072}
```

`VALID_TARGET_TOKENS = [16384, 32768, 65536, 131072, 262144, 524288]`.

Response: `{"bench_id":"...","status":"started","target_tokens":131072}`.

**400 if Memory Guard is disabled** (`final_ceiling <= 0`) — the benchmark
refuses to run without a ceiling to test against.

#### `GET /admin/api/bench/context/{id}/stream`

Same SSE framing as the throughput stream.

#### `GET /admin/api/bench/context/{id}/results`

```json
{"bench_id":"...","status":"completed","phase":"cleanup","progress":100,
 "message":"...","error":null,
 "result":{"model_id":"...","target_tokens":131072,"native_context_length":262144,
   "measured_tokens":131072,"verified_tokens":131072,"verified_prompt_tokens":131072,
   "applied_tokens":131072,"applied":true,"capped_by":null,"attempts":1,
   "extended":false,"prefill_tps":1719.4,"duration_s":76.2,
   "prefill_priority":"normal"}}
```

`done` summary: `{model_id, applied_tokens, total_time}`.

#### `POST /admin/api/bench/context/{id}/cancel`

Same shape as the throughput cancel.

#### `GET /admin/api/bench/context/active` — verified

```json
{"running":false,"bench_id":null,"model_id":null}
```

---

## 9. Inference

### `POST /v1/chat/completions`

Non-streaming — verified:

```json
{"id":"chatcmpl-f5fe5b02","object":"chat.completion","created":1793241151,
 "model":"MarkItDown",
 "choices":[{"index":0,"message":{"role":"assistant","content":"hi"},
             "finish_reason":"stop"}],
 "usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,
          "input_tokens":0,"output_tokens":0}}
```

Streaming with `"stream_options": {"include_usage": true}` — verified exact
6-event sequence for a one-token reply:

```
data: {"id":"chatcmpl-430fd9eb","object":"chat.completion.chunk","created":1793241151,"model":"MarkItDown","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-430fd9eb","object":"chat.completion.chunk","created":1793241151,"model":"MarkItDown","choices":[{"index":0,"delta":{"role":"assistant"}}]}

data: {"id":"chatcmpl-430fd9eb","object":"chat.completion.chunk","created":1793241151,"model":"MarkItDown","choices":[{"index":0,"delta":{"content":"hi"}}]}

data: {"id":"chatcmpl-430fd9eb","object":"chat.completion.chunk","created":1793241151,"model":"MarkItDown","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: {"id":"chatcmpl-430fd9eb","object":"chat.completion.chunk","created":1793241151,"model":"MarkItDown","choices":[],"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,"input_tokens":0,"output_tokens":0}}

data: [DONE]
```

Note the **penultimate chunk** carries `usage` with `choices: []`. The first
chunk has `content: ""` — do not count it as a token.

### `Usage` object (`api/openai_models.py:482`)

oMLX extends the OpenAI `Usage` with timing fields, all in **seconds**:

| Field | Meaning |
| --- | --- |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | Standard counts |
| `input_tokens`, `output_tokens` | Aliases |
| `prompt_tokens_details.cached_tokens` | Prefix-cache hits |
| `prompt_tokens_details.audio_tokens` | Audio tokens |
| `completion_tokens_details.reasoning_tokens` | Reasoning tokens |
| `model_load_duration` | Load time; `null` when ≤ 1.0 s |
| `time_to_first_token` | Model TTFT (2dp) |
| `time_to_first_visible_token` | TTFT after output filters (chat streaming only) |
| `total_time` | Whole request (2dp) |
| `prompt_eval_duration` | Prefill duration |
| `generation_duration` | Decode duration |
| `prompt_tokens_per_second` | `(prompt_tokens - cached_tokens) / prompt_eval_duration` |
| `generation_tokens_per_second` | `completion_tokens / generation_duration` |

**TTFT and tok/s can be read straight out of `usage`** — no client-side timing
needed. `prompt_tokens_per_second` deliberately excludes cached tokens because
those were restored, not computed.

### `POST /tokenize` (also `/v1/tokenize`)

Body is **either**:

```json
{"model": "<id>", "messages": [{"role": "user", "content": "hi"}]}
```

**or**

```json
{"model": "<id>", "prompt": "hi"}
```

> **`text` is not a field.** Sending `{"model","text"}` returns **400**:
> `{"error":{"message":"body -> TokenizeChatRequest -> messages: Field required; body -> TokenizeCompletionRequest -> prompt: Field required", ...}}`

Response: `{"count": N, "max_model_len": M, "tokens": [...], "token_strs": null}`.
`return_token_strs: true` populates `token_strs`. The context window is not
enforced; `max_model_len` reports it instead.

`POST /detokenize` (also `/v1/detokenize`) is the inverse.

---

## 10. CLI

```sh
export PATH="$HOME/.omlx/bin:$PATH"
omlx --version   # 0.7.3rc1
```

Subcommands: `{start, stop, restart, serve, launch, diagnose, cluster}`.

### `omlx start` / `stop` / `restart` — managed background server

These control the **macOS app**, not a foreground process. They talk to the Unix
socket `~/Library/Application Support/oMLX/control.sock` with
`{"command": "<cmd>"}\n`, auto-launching `/Applications/oMLX.app` via `open -gj`
if needed, then poll `status` until the state is `running` or `unresponsive`.

| Flag | Applies to | Meaning |
| --- | --- | --- |
| `--timeout SECONDS` | all three | Wait for the requested state (default 60) |
| `--no-wait` | `start`, `restart` | Return after sending the request |

Homebrew installs delegate to `brew services`. Other installs print
"Background start is available for the macOS app and Homebrew installs."

### `omlx serve` — foreground multi-model server

A **different** server: foreground, LRU memory management, its own flags. It
does not use the app control socket and does not share the app's lifecycle.

Key flags: `--model-dir`, `--host`, `--port`, `--log-level`,
`--sse-keepalive-mode {chunk,comment,off}`, `--max-concurrent-requests`,
`--embedding-batch-size`, `--memory-guard {off,safe,balanced,aggressive}`,
`--memory-guard-gb`, `--paged-ssd-cache-dir`, `--paged-ssd-cache-max-size`,
`--hot-cache-max-size`, `--no-cache`, `--initial-cache-blocks`, `--mcp-config`,
`--hf-endpoint`, `--hf-cache/--no-hf-cache`, `--ms-endpoint`, `--http-proxy`,
`--https-proxy`, `--no-proxy`, `--ca-bundle`, `--base-path`, `--api-key`,
`--headless`.

Models are discovered from **subdirectories** of `--model-dir`; each needs a
`config.json` and `*.safetensors`.

### Other subcommands

- `omlx diagnose menubar` — the target is **required**; checks Tahoe
  ControlCenter visibility.
- `omlx launch <tool> [--model] [--host] [--port] [--api-key] [--tools-profile] [--opus/--sonnet/--haiku] [--cross-session]`
  — configures Claude Code, Copilot, Codex, OpenCode, OpenClaw, Hermes, Pi,
  Mistral Vibe, DeepSeek Harness to point at the running server. `omlx launch list`
  shows the options.
- `omlx cluster {status,worker-smoke,collective-smoke,pipeline-smoke,plan}` —
  distributed diagnostics. Does not configure interfaces or initialize JACCL.

---

## 11. Gotcha index

| Symptom | Cause | Fix |
| --- | --- | --- |
| `405 {"detail":"Method Not Allowed"}` on `GET .../settings` | The route does not exist | Read `settings` from `GET /admin/api/models` |
| `404 {"detail":"Model not found: MarkItDown"}` on every per-model route | `MarkItDown` is a **virtual builtin**, not in the engine pool | Use a real downloaded model |
| `422 extra_forbidden` on `PUT .../settings` | `ModelSettingsRequest` forbids unknown fields | Check the field name against §5 |
| `400` on `mtp_adaptive_max_depth` | Must be `1..8` or `null` | Clamp to 8 |
| Setting appears to save but stays `false` | Model-family coercion (`qwen4_*`, `deepseek_v41_*`) | Check `config_model_type` in `GET /admin/api/models` |
| `409` on `bench/start` | Another benchmark is running | Poll `GET /admin/api/bench/active` and `.../context/active` |
| `400` on `bench/context/start` | Memory Guard disabled | Enable `memory.prefill_memory_guard` |
| `gen_tps: null` in bench results | `completion_tokens < 16` | Raise `generation_length` |
| `400` on `/tokenize` | Sent `text` instead of `messages`/`prompt` | Use the correct body shape |
| `400` on `hf/download` | `repo_id` not `owner/model` | Fix the id |
| Download stuck at `pending` | Only one download runs at a time | Wait, or cancel the active one |
| `model_memory_max` changes between calls | It is dynamic | Read it live, never hardcode |
