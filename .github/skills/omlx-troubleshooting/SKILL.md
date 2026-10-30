---
name: omlx-troubleshooting
description: Diagnose and fix common oMLX 0.7.3rc1 failures on macOS Apple Silicon — server not starting, port conflicts, OOM and memory-guard rejections, models not discovered, stalled downloads, 401/404/405/409/422 API errors, and benchmark refusals. Use when an oMLX command or API call fails or a model will not load.
---

# oMLX troubleshooting

Verified against a live oMLX 0.7.3rc1 server on `$OMLX_BASE_URL`.
Every error shape below was reproduced live unless marked **unverified**.

## Setup

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=${OMLX_BASE_URL:-http://127.0.0.1:8001}
```

## Triage order

Work down this list; each step is cheap and rules out a whole class of problems.

```sh
# 1. Is the CLI the expected version?
omlx --version
# 0.7.3rc1

# 2. Is anything listening on the port?
lsof -nP -iTCP:8001 -sTCP:LISTEN
# python3.1 93653 core 4u IPv4 ... TCP 127.0.0.1:8001 (LISTEN)

# 3. Does the server answer?
curl -s -m 5 $OMLX/api/status | jq
# {"status":"ok","version":"0.7.3rc1","models_discovered":0,"models_loaded":0,
#  "model_memory_max":95546847222}

# 4. What does the log say?
tail -50 ~/.omlx/logs/server.log
```

Log locations:

| Path | Contents |
| --- | --- |
| `~/.omlx/logs/server.log` | Live server log (rotated daily as `server.log.YYYY-MM-DD`) |
| `~/.omlx/logs/crash.log` | Crash tracebacks |
| `~/Library/Application Support/oMLX/logs/server.log` | App-managed server log |
| `~/Library/Application Support/oMLX/logs/menubar.log` | Menubar app log |

The server log records every non-2xx response with its reason, which is usually
enough to identify the problem:

```
2026-10-28 22:34:53,838 - omlx.server - WARNING - GET /admin/api/bench/abc123/results → 404: Benchmark not found: abc123
```

## Server will not start

### Symptom: `curl` returns nothing, exit code 000

```sh
curl -s -m 3 -w '[%{http_code}]' http://127.0.0.1:9999/api/status
# [000]
```

Nothing is listening. Start it:

```sh
omlx start
# or, to not block on health:
omlx start --no-wait
# or with a longer budget:
omlx start --timeout 120
```

`omlx start` talks to the macOS app over
`~/Library/Application Support/oMLX/control.sock` and auto-launches
`$OMLX_APP` if needed. It polls until the state is `running` or
`unresponsive`.

### Symptom: `omlx start` prints "Background start is available for the macOS app and Homebrew installs."

The CLI cannot manage a server it did not install. Run it in the foreground
instead:

```sh
omlx serve --port 8001 --host 127.0.0.1
```

`omlx serve` is a **different** server from the managed one: it is foreground,
multi-model, LRU-managed, and takes all its configuration from flags rather than
`~/.omlx/settings.json`. Do not run both on the same port.

### Symptom: server starts then immediately exits

```sh
tail -100 ~/.omlx/logs/server.log
cat ~/.omlx/logs/crash.log
```

Common causes:

- Port already bound (see next section).
- A corrupt `~/.omlx/settings.json` — validate it:
  ```sh
  jq . ~/.omlx/settings.json > /dev/null && echo "settings.json is valid JSON"
  ```
- A model directory that no longer exists. Check:
  ```sh
  curl -s $OMLX/admin/api/global-settings | jq '.model.model_dirs'
  ls -d $OMLX_MODELS_DIR
  ```

### Restart cleanly

```sh
omlx restart --timeout 120
# or
omlx stop && omlx start
```

## Port conflict

### Symptom: `Address already in use` in the log, or the server answers on an unexpected port

```sh
lsof -nP -iTCP:8001 -sTCP:LISTEN
```

If the PID is an old oMLX process:

```sh
omlx stop
# if that does not clear it, kill the specific PID
kill <PID>
```

If it is a different program, either stop it or move oMLX. The port lives in
`~/.omlx/settings.json` under `server.port` — **do not edit that file**; use the
UI or `omlx serve --port <n>` for a foreground instance.

Confirm which port the running server actually uses:

```sh
curl -s $OMLX/admin/api/global-settings | jq '.server | {host, port}'
# {"host":"127.0.0.1","port":8001}
```

## 401 Unauthorized on `/admin/api/*`

`require_admin` skips authentication only when **both** conditions hold:

1. `auth.skip_api_key_verification` is `true`, **and**
2. the server is bound to a loopback address.

```sh
curl -s $OMLX/admin/api/global-settings | jq '{auth: .auth | {api_key_set, skip_api_key_verification, allow_unauthenticated_inference}, host: .server.host}'
# {"auth":{"api_key_set":true,"skip_api_key_verification":true,
#          "allow_unauthenticated_inference":false},"host":"127.0.0.1"}
```

If `skip_api_key_verification` is `false`, or `host` is not loopback, you must
authenticate. Two ways:

```sh
# Bearer token
curl -s -H "Authorization: Bearer $(curl -s $OMLX/admin/api/global-settings | jq -r .auth.api_key)" \
  $OMLX/admin/api/models

# Session cookie
curl -s -c cookies.txt -X POST $OMLX/admin/api/login \
  -H 'Content-Type: application/json' \
  -d '{"api_key":"<key>","remember":true}'
curl -s -b cookies.txt $OMLX/admin/api/models
```

`POST /admin/api/login` returns 400 if no API key is configured, 401 for a wrong
key, and 429 during lockout. It sets the `omlx_admin_session` cookie.

> A wrong `Authorization: Bearer` header is **ignored** when verification is
> skipped — the request still succeeds with 200. Do not use a 200 as proof that
> your key is correct.

`allow_unauthenticated_inference` is a **separate** flag governing `/v1/*`.

## OOM / memory guard rejections

### Symptom: load fails with `ModelTooLargeError`

```
Model '<id>' (<size>) does not fit under the <binding> memory ceiling (<ceiling>). <advice>.
```

The ceiling is **dynamic** — never hardcode it:

```sh
curl -s $OMLX/api/status | jq '{model_memory_max, gb: (.model_memory_max/1073741824*100|floor/100)}'
# {"model_memory_max":95546847222,"gb":89.0}
```

Observed values drift between 89.2 and 90.1 GB on this machine.

Compare against the model's real footprint:

```sh
curl -s $OMLX/admin/api/models | jq --arg m '<model_id>' \
  '.models[] | select(.id==$m) | {estimated_size, estimated_size_formatted, actual_size, actual_size_formatted}'
```

Fixes, in order of preference:

1. **Pick a smaller quantization** (4-bit instead of 8-bit).
2. **Lower `max_context_window`** — the KV cache is a large part of residency.
3. **Enable KV compression**:
   ```sh
   curl -s -X PUT $OMLX/admin/api/models/<id>/settings -H 'Content-Type: application/json' \
     -d '{"turboquant_kv_enabled":true,"turboquant_kv_bits":4}'
   ```
4. **Enable MoE expert offload** (MoE models only):
   ```sh
   curl -s "$OMLX/admin/api/models/<id>/moe-offload-fit" | jq
   curl -s -X PUT $OMLX/admin/api/models/<id>/settings -H 'Content-Type: application/json' \
     -d '{"moe_expert_offload_enabled":true,"moe_expert_offload_resident_fraction":0.25}'
   ```
5. **Raise the memory guard tier** — `memory.memory_guard_tier` in
   `GET /admin/api/global-settings` (`safe` < `balanced` < `aggressive`).
   Changing it is a global-settings edit; do it in the UI, not by hand.

### Symptom: `InsufficientMemoryError`

Another model is already resident and there is no room. Unload it first:

```sh
curl -s -X POST $OMLX/admin/api/models/<other_id>/unload
```

Or let LRU eviction do it — but pinned models are never evicted, so unpin first:

```sh
curl -s -X PUT $OMLX/admin/api/models/<other_id>/settings -H 'Content-Type: application/json' -d '{"is_pinned":false}'
```

### Symptom: context benchmark returns 400

The long-context benchmark refuses to run when Memory Guard is off
(`final_ceiling <= 0`):

```sh
curl -s $OMLX/admin/api/global-settings | jq '.memory'
# {"prefill_memory_guard":true,"memory_guard_tier":"balanced","memory_guard_custom_ceiling_gb":0.0}
```

`prefill_memory_guard` must be `true`.

## Model not discovered

### Symptom: a downloaded model does not appear in `/admin/api/models`

```sh
curl -s -X POST $OMLX/admin/api/reload
# {"status":"ok","message":"Re-discovered 1 models from 2 directories"}
```

Then re-check:

```sh
curl -s $OMLX/admin/api/models | jq -r '.models[] | [.id, .source_type, .estimated_size_formatted] | @tsv'
```

If it is still missing:

```sh
# Is it on disk where oMLX looks?
curl -s $OMLX/admin/api/global-settings | jq '.model | {model_dirs, effective_model_dirs}'
# {"model_dirs":["$OMLX_MODELS_DIR"],
#  "effective_model_dirs":["$OMLX_MODELS_DIR",
#                          "$HF_HOME/hub"]}

# Does the directory have a config.json?
ls -la $OMLX_MODELS_DIR/<owner>/<model>/config.json
```

A model without `config.json` is not discoverable. A **partially downloaded**
model has a `config.json` but no weights — it will appear with a tiny
`estimated_size` and fail to load.

```sh
curl -s $OMLX/admin/api/hf/models | jq -r '.models[] | [.name, .size_formatted, .source_type] | @tsv'
```

### Symptom: the only model listed is `MarkItDown`

That is a **virtual builtin** (`model_path: "builtin://markitdown"`,
`virtual: true`). It is always present, even with zero real models, and it is
**not** in the engine pool. Every per-model route returns 404 for it:

```sh
curl -s -w '\n[%{http_code}]\n' -X PUT $OMLX/admin/api/models/MarkItDown/settings \
  -H 'Content-Type: application/json' -d '{"temperature":0.2}'
# {"detail":"Model not found: MarkItDown"}
# [404]
```

Same 404 for `/load`, `/unload`, `/profiles`, `/settings/optimal`,
`/generation_config`, `/moe-offload-fit`. `/tokenize` returns
`{"error":{"message":"Model 'MarkItDown' not found. Available models: (none)",...}}`.

This is not a bug — download a real model.

## Download stalls

### Symptom: a task sits at `pending` forever

**Only one download runs at a time**, and the queue is shared machine-wide.

```sh
curl -s $OMLX/admin/api/hf/tasks | jq -r '.tasks[] | [.repo_id, .status, (.progress|tostring)+"%"] | @tsv'
```

If another repo is `downloading`, yours is waiting behind it. Either wait, or
cancel the blocker if it is yours:

```sh
curl -s -X POST $OMLX/admin/api/hf/cancel/<task_id>
```

### Symptom: `status: failed`

```sh
curl -s $OMLX/admin/api/hf/tasks | jq -r '.tasks[] | select(.status=="failed") | {repo_id, error, retry_count}'
```

Retry resumes from the files already on disk:

```sh
curl -s -X POST $OMLX/admin/api/hf/retry/<task_id> \
  -H 'Content-Type: application/json' -d '{"hf_token":""}'
```

Common `error` values: network timeouts, 401/403 from a gated repo (needs
`hf_token`), and disk-full.

### Symptom: download is slow or `speed_bps` collapses

Check free disk — a nearly full volume throttles writes:

```sh
df -g "${OMLX_DATA_VOLUME:-/System/Volumes/Data}" | awk 'NR==2 {print $4 " GB free"}'
```

Check the SSD cache is not the bottleneck (it is 185 GB and must not be
deleted):

```sh
curl -s $OMLX/admin/api/global-settings | jq '.cache | {ssd_cache_dir, ssd_cache_max_size, hot_cache_only}'
```

### Symptom: `DELETE /admin/api/hf/task/{id}` returns 404 "Task not found or still active"

The task is still `pending` or `downloading`. Cancel first:

```sh
curl -s -X POST $OMLX/admin/api/hf/cancel/<task_id>
curl -s -X DELETE $OMLX/admin/api/hf/task/<task_id>
```

### Symptom: `400 Invalid repository ID`

```json
{"detail":"Invalid repository ID: 'notarepo'. Expected format: 'owner/model' (e.g., 'mlx-community/Llama-3-8B-4bit')"}
```

The id must be exactly two path segments and must not contain `.` or `..`.

## API error codes

| Code | Shape | Meaning |
| --- | --- | --- |
| 400 | `{"detail":"..."}` | Bad request — validation message in `detail` |
| 401 | `{"detail":"..."}` | Auth required (see above) |
| 404 | `{"detail":"Model not found: <id>"}` | Unknown model, or a virtual builtin |
| 404 | `{"detail":"Benchmark not found: <id>"}` | Unknown bench id |
| 404 | `{"detail":"Task not found or not cancellable"}` | HF cancel on a finished/unknown task |
| 404 | `{"detail":"Task not found or still active"}` | HF task delete while running |
| 404 | `{"detail":"Model not found"}` | HF model delete on an unknown name |
| 405 | `{"detail":"Method Not Allowed"}` | Wrong verb — see the `GET settings` gotcha |
| 409 | `{"detail":"Model is already loading: <id>"}` | Load in progress |
| 409 | `{"detail":"..."}` | A benchmark is already running |
| 422 | `{"detail":[{"type":"extra_forbidden",...}]}` | Unknown field in a settings body |
| 500 | `{"detail":"..."}` | Load failure or internal error |
| 503 | `{"detail":"..."}` | Engine pool not initialized |

### 405 on `GET /admin/api/models/{id}/settings`

**This endpoint does not exist.** Settings are embedded in the model list:

```sh
curl -s $OMLX/admin/api/models | jq --arg m '<model_id>' '.models[] | select(.id==$m) | .settings'
```

### 422 `extra_forbidden`

`ModelSettingsRequest` uses `extra="forbid"`. Any unknown key is rejected:

```json
{"detail":[{"type":"extra_forbidden","loc":["body","bogus_field"],
            "msg":"Extra inputs are not permitted","input":1}]}
```

Check the field name against the settings skill's field table. Common typos:
`max_context` (should be `max_context_window`), `thinking_budget` (should be
`thinking_budget_tokens`), `mtp` (should be `mtp_enabled`).

### 409 on `bench/start`

Another benchmark is running. Check both:

```sh
curl -s $OMLX/admin/api/bench/active
curl -s $OMLX/admin/api/bench/context/active
```

Cancel it:

```sh
curl -s -X POST $OMLX/admin/api/bench/<bench_id>/cancel
```

### 400 on `bench/start` with a pydantic message

The `detail` string lists the valid values:

```json
{"detail":"1 validation error for BenchmarkRequest\nprompt_lengths\n  Value error, Invalid prompt length 999. Must be one of [1024, 4096, 8192, 16384, 32768, 65536, 131072, 200000] ..."}
```

Valid `prompt_lengths`: `1024, 4096, 8192, 16384, 32768, 65536, 131072, 200000`.
Valid `batch_sizes`: `2, 4, 8`.
Valid `context_profile`: `code_python, code_mixed, novel_ko, novel_en, novel_ja`.
Valid `target_tokens`: `16384, 32768, 65536, 131072, 262144, 524288`.

## Settings that silently do nothing

Four settings are **silently stored as `False`** when the model family does not
match. No error is raised and the response echoes `false`:

| Setting | Required `config_model_type` |
| --- | --- |
| `qwen4_ple_ssd_offload` | `qwen4_exp` |
| `qwen4_gdn_decode_wide_proj` | `qwen4_exp` |
| `deepseek_v41_ced_prefill_enabled` | `deepseek_v41` |
| `deepseek_v41_engram_ssd_offload` | `deepseek_v41` |

```sh
curl -s $OMLX/admin/api/models | jq --arg m '<model_id>' '.models[] | select(.id==$m) | .config_model_type'
```

Also check the compatibility flags before enabling speculative decoding:

```sh
curl -s $OMLX/admin/api/models | jq --arg m '<model_id>' '.models[] | select(.id==$m)
  | {dflash_compatible, dflash_compatibility_reason, mtp_compatible, mtp_compatibility_reason,
     moe_expert_offload_supported, moe_offload_allows_mtp, activation_fp16_supported}'
```

`qwen35_oq_a8_enabled` is **M5-series hardware only**. On this M4 Max the kernels
refuse to load and the setting is refused.

## Settings change did not take effect

If `requires_reload` was true, the engine was unloaded and may still be
reloading, or the reload was deferred because requests were in flight:

```sh
curl -s $OMLX/admin/api/models | jq --arg m '<model_id>' '.models[] | select(.id==$m) | {loaded, is_loading}'
```

Wait for `loaded: true, is_loading: false`. If it never comes back, load it
explicitly:

```sh
curl -s -X POST $OMLX/admin/api/models/<model_id>/load
```

## Unload returns 202

```json
{"status":"unloading","model_id":"<id>","message":"Aborting active requests before unloading <id>"}
```

Requests were in flight and are being aborted. Poll until `loaded` is false. A
`400` means it was not loaded; a `409` means it is still loading.

## `omlx diagnose` fails

`diagnose` requires a target:

```sh
omlx diagnose menubar
```

`omlx diagnose` with no argument prints the usage error. The only target in
0.7.3rc1 is `menubar` (checks Tahoe ControlCenter visibility).

## `/tokenize` returns 400

The body takes `messages` (chat) or `prompt` (completion) — **not `text`**:

```json
{"error":{"message":"body -> TokenizeChatRequest -> messages: Field required; body -> TokenizeCompletionRequest -> prompt: Field required","type":"invalid_request_error","param":"messages","code":null}}
```

```sh
curl -s $OMLX/tokenize -H 'Content-Type: application/json' \
  -d '{"model":"<model_id>","prompt":"def f():\n    return 1\n"}'
```

> `scripts/measure.py` in this repo sends `{"model","text"}` and therefore always
> falls back to `len(text)//4` token estimation. Context-padded measurements are
> approximate until that is fixed.

## Streaming `usage` never arrives

Add `stream_options.include_usage: true`. The usage object rides on the
**penultimate** chunk, which has an empty `choices` array:

```
data: {"choices":[],"usage":{...}}
data: [DONE]
```

Filter with `select(.usage != null)`, not by reading the last chunk.

## Nuclear reset (last resort)

Only if the server is wedged and you have already read the log:

```sh
omlx stop --timeout 60
omlx start --timeout 120
```

If that fails, quit the oMLX app from the menubar and relaunch it. **Never**
delete `~/.omlx/cache` (185 GB shared SSD cache) and never hand-edit
`~/.omlx/settings.json` — use the UI.

## Not verifiable without a loaded model

Documented from source, **not** reproduced here:

- `ModelTooLargeError` / `InsufficientMemoryError` / `ModelLoadingError` message
  text at runtime (the formats are from `exceptions.py`).
- The 409 "already loading" and 500 load-failure paths.
- The 202 unload path.
- A real `requires_reload` cycle.

Verified live: the 000 connection failure, `lsof` output, `omlx --version`,
`omlx start/stop --help`, `omlx diagnose --help`, the 404 on every per-model
route for the virtual `MarkItDown`, the 405 on `GET .../settings`, the 422
`extra_forbidden` shape, the 404s for unknown bench ids and HF tasks/models, the
400 pydantic messages for bench validation, the `/tokenize` body-shape error, the
`auth` and `memory` global-settings blocks, and the log file locations.
