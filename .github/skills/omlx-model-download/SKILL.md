---
name: omlx-model-download
description: Find, download, verify, and delete MLX models on oMLX 0.7.3rc1 via the admin HTTP API. Use when searching Hugging Face for a model, starting or monitoring a download, checking what landed on disk, accounting for disk space, or removing a model. Covers /admin/api/hf/search, /model-info, /download, /tasks, /cancel, /retry, /models, and DELETE /hf/models/{name}.
---

# oMLX model download

Everything here is verified against a live oMLX 0.7.3rc1 server on
`http://127.0.0.1:8001` unless explicitly marked **unverified**.

## Setup

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=http://127.0.0.1:8001
```

Confirm the server is up before anything else:

```sh
curl -s $OMLX/api/status | jq '{status, version, models_discovered, models_loaded}'
# {"status":"ok","version":"0.7.3rc1","models_discovered":0,"models_loaded":0}
```

Auth: `/admin/api/*` needs no credentials on this machine because the server is
bound to loopback **and** `auth.skip_api_key_verification` is `true`. If you ever
get `401`, see the troubleshooting skill.

## Where files land

```
<model_dir>/<repo_id>
```

With the default config that is:

```
/Users/core/.omlx/models/mlx-community/<owner>/<model>
```

e.g. `Jundot/Qwen3.8-27B-oQ4e-mtp` →
`/Users/core/.omlx/models/mlx-community/Jundot/Qwen3.8-27B-oQ4e-mtp`.

The model directory is `model.model_dirs[0]` from
`GET /admin/api/global-settings`. Do not change it.

## Step 1 — disk accounting (mandatory)

`AGENTS.md` requires a disk check before every download, with a **60 GB floor**.

```sh
cd <repo>
./scripts/disk_guard.sh 40
# free=450GB needed=40GB after=410GB floor=60GB
# OK
```

Exit code `1` means refuse:

```sh
./scripts/disk_guard.sh 500
# free=450GB needed=500GB after=-50GB floor=60GB
# REFUSED: would leave -50GB, below the 60GB floor
```

Get the exact download size from `model-info` (step 2) and pass **that** number
in GB, rounded up. `download_all_size` is bytes.

```sh
NEEDED_GB=$(( ($(curl -s "$OMLX/admin/api/hf/model-info?repo_id=<owner>/<model>" \
  | jq -r .download_all_size) + 1073741823) / 1073741824 ))
./scripts/disk_guard.sh "$NEEDED_GB"
```

Also check the server's own view of free space:

```sh
curl -s $OMLX/admin/api/hf/recommendations | jq '.disk'
# {"model_dir":"/Users/core/.omlx/models/mlx-community","free_bytes":489263915008}
```

## Step 2 — search Hugging Face

`q` is **required**; omitting it is a 400.

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

Compact table:

```sh
curl -s "$OMLX/admin/api/hf/search?q=qwen3&limit=20&mlx_only=true" \
  | jq -r '.models[] | [.repo_id, .size_formatted, .params_formatted, (.downloads|tostring)] | @tsv' \
  | column -t -s $'\t'
```

Query parameters:

| Param | Values | Notes |
| --- | --- | --- |
| `q` | string | **Required.** 400 `{"detail":"Query parameter 'q' is required"}` if missing |
| `limit` | int | Capped at 100 |
| `sort` | `trending`, … | Default `trending` |
| `mlx_only` | bool | `true` filters to MLX-convertible repos |
| `model_format` | `mlx` \| `gguf` \| `all` | |
| `min_params` / `max_params` | int | Parameter-count filter |
| `min_size` / `max_size` | int | Byte-size filter |
| `sort_by_size` / `sort_ascending` | bool | |

`hf_token_invalid: true` means the configured HF token was rejected — searches
still work anonymously.

### What actually fits this machine

`GET /admin/api/hf/recommendations` is the authoritative "fits my Mac" endpoint.
It knows the chip, GPU cores, memory, bandwidth, and the current memory-guard
tier.

```sh
curl -s $OMLX/admin/api/hf/recommendations \
  | jq '{device, memory: {tier: .memory.tier, scenarios: .memory.scenarios},
         best: [.sections.best[] | {repo_id, download_bytes, resident_bytes, tokens_per_second, smarts}]}'
```

```json
{"device":{"chip":"Apple M4 Max","generation":"M4","variant":"Max","gpu_cores":40,
  "memory_bytes":137438953472,"bandwidth_gbps":546,"prefers_fp16":false},
 "memory":{"tier":"balanced",
   "scenarios":{
     "now":{"tier":"balanced","metal_cap_bytes":115448725504,"ceiling_bytes":115448725504,"usable_bytes":105675956551},
     "memory_guard":{"tier":"aggressive","metal_cap_bytes":115448725504,"ceiling_bytes":115448725504,"usable_bytes":111448392826},
     "wired_limit":{"tier":"balanced","metal_cap_bytes":128849018880,"ceiling_bytes":128849018880,"usable_bytes":118004226457},
     "both":{"tier":"aggressive","metal_cap_bytes":130566586368,"ceiling_bytes":130566586368,"usable_bytes":126112717864}}},
 "best":[{"repo_id":"Jundot/Qwen3.8-27B-oQ4e-mtp","download_bytes":16971681558,
   "resident_bytes":17820265635,"tokens_per_second":36.2,"smarts":4.737}]}
```

Sections: `best`, `bigger`, `precise`, `faster`, `unlock`. `unlock` rows carry
`kind` (`fits` | `table_in_memory`) and `needs` (e.g. `["wired_limit"]`).

`GET /admin/api/hf/recommended` is the simpler trending list:

```sh
curl -s $OMLX/admin/api/hf/recommended | jq -r '.trending[] | [.repo_id, .size_formatted] | @tsv'
```

## Step 3 — inspect the repo before downloading

```sh
curl -s "$OMLX/admin/api/hf/model-info?repo_id=mlx-community/Qwen3-8B-4bit" | jq
```

```json
{"repo_id":"mlx-community/Qwen3-8B-4bit","name":"Qwen3-8B-4bit",
 "model_card":"...","description":"...",
 "files":[{"name":"config.json","size":939,"size_formatted":"0.9 KB","group":null,
           "mmproj":null,"kind":"other","required":true,"preselected":true,"local":false}],
 "layout":"safetensors","download_all_size":4623784971,"unsupported_reason":null,
 "tags":["mlx","safetensors"],"pipeline_tag":"text-generation",
 "params":8190738432,"params_formatted":"8.2B",
 "size":4607835174,"size_formatted":"4.3 GB",
 "downloads":123456,"likes":789,
 "created_at":"...","updated_at":"...","is_adapter":false,
 "disk_free":489263759360}
```

Key fields:

| Field | Meaning |
| --- | --- |
| `download_all_size` | Bytes for the full repo — use this for the disk check |
| `layout` | `safetensors` \| `gguf` \| … |
| `unsupported_reason` | Non-null means oMLX cannot run this repo; **do not download** |
| `is_adapter` | LoRA/adapter, not a standalone model |
| `files[].required` | Must be downloaded |
| `files[].preselected` | Default selection when you pass an explicit `files` list |
| `files[].local` | Already on disk |
| `files[].kind` | `weights` / `tokenizer` / `other` |
| `disk_free` | Free bytes on the model volume |

Missing `repo_id` → 400 `{"detail":"Query parameter 'repo_id' is required"}`.

## Step 4 — start the download

```sh
curl -s -X POST $OMLX/admin/api/hf/download \
  -H 'Content-Type: application/json' \
  -d '{"repo_id":"mlx-community/Qwen3-8B-4bit"}' | jq
```

```json
{"success":true,"task":{"task_id":"de40277a-5178-44d7-8112-4c2e4aba27e2",
  "repo_id":"mlx-community/Qwen3-8B-4bit","status":"pending","progress":0.0,
  "total_size":0,"downloaded_size":0,"speed_bps":0.0,"eta_seconds":null,
  "error":"","created_at":1793241068.296722,"started_at":0.0,"completed_at":0.0,
  "retry_count":0,"files":null,"gguf_files":[],"gguf_model_id":null}}
```

Request body:

| Field | Type | Meaning |
| --- | --- | --- |
| `repo_id` | string | **Required.** Exactly `owner/model` |
| `hf_token` | string | Optional; `""` = anonymous. Needed for gated repos |
| `files` | `list[str]` \| `null` | `null` = whole repo. Otherwise repo-relative paths, e.g. `["config.json","model.safetensors","tokenizer.json"]` |

Partial download (skip the fp16 originals, grab only the 4-bit weights):

```sh
curl -s -X POST $OMLX/admin/api/hf/download -H 'Content-Type: application/json' -d '{
  "repo_id":"mlx-community/Qwen3-8B-4bit",
  "files":["config.json","model.safetensors","tokenizer.json","tokenizer_config.json"]
}'
```

### Rules the server enforces

- **Only one download runs at a time.** Everything else sits at `pending`.
  This queue is **shared with every other agent on the machine** — a new
  download can wait behind many others. Check the queue first (step 5).
- A second in-progress download for the same repo (case-insensitive) → **400**.
- `repo_id` must be exactly two path segments and must not contain `.` or `..`:

```json
{"detail":"Invalid repository ID: 'notarepo'. Expected format: 'owner/model' (e.g., 'mlx-community/Llama-3-8B-4bit')"}
```

## Step 5 — poll progress

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

Readable table:

```sh
curl -s $OMLX/admin/api/hf/tasks | jq -r '
  .tasks[] | [.repo_id, .status, (.progress|tostring)+"%",
    ((.downloaded_size/1048576|floor|tostring)+"/"+(.total_size/1048576|floor|tostring)+" MB"),
    (if .speed_bps then ((.speed_bps/1048576*10|floor)/10|tostring)+" MB/s" else "-" end),
    (if .eta_seconds then ((.eta_seconds/60*10|floor)/10|tostring)+" min" else "-" end)]
  | @tsv' | column -t -s $'\t'
```

```
Jundot/Qwen3.8-27B-oQ4e-mtp  downloading  37.5%  6075/16207 MB  39.4 MB/s  4.6 min
Jundot/Ornith-1.0-35B-oQ4e    pending       0.0%     0/0 MB       0 MB/s  -
```

Watch one repo until it finishes:

```sh
REPO='mlx-community/Qwen3-8B-4bit'
while :; do
  read -r STATUS PROGRESS < <(curl -s $OMLX/admin/api/hf/tasks \
    | jq -r --arg r "$REPO" '.tasks[] | select(.repo_id==$r) | "\(.status) \(.progress)"')
  echo "$(date +%H:%M:%S) $STATUS ${PROGRESS}%"
  case "$STATUS" in completed|failed|cancelled) break;; esac
  sleep 10
done
```

`status` ∈ `pending | downloading | completed | failed | cancelled`.
`progress` is a **percentage** (0–100), not a fraction. `eta_seconds` is `null`
while queued. `eta_speed_bps` and `token` exist on the dataclass but are never
serialized.

### Cancel / retry / remove

```sh
# cancel (stops the transfer, keeps partial files)
curl -s -X POST $OMLX/admin/api/hf/cancel/<task_id>
# {"success":true}
# 404 {"detail":"Task not found or not cancellable"}

# retry (resumes from files already on disk, increments retry_count)
curl -s -X POST $OMLX/admin/api/hf/retry/<task_id> \
  -H 'Content-Type: application/json' -d '{"hf_token":""}'

# remove a finished/failed/cancelled task row (does NOT delete files)
curl -s -X DELETE $OMLX/admin/api/hf/task/<task_id>
# 404 {"detail":"Task not found or still active"}
```

`DELETE /admin/api/hf/task/{id}` refuses while the task is `pending` or
`downloading` — cancel first.

## Step 6 — verify what landed on disk

```sh
curl -s $OMLX/admin/api/hf/models | jq
```

```json
{"models":[{"name":"Qwen3.8-27B-oQ4e-mtp",
  "path":"/Users/core/.omlx/models/mlx-community/Jundot/Qwen3.8-27B-oQ4e-mtp",
  "display_name":"Jundot/Qwen3.8-27B-oQ4e-mtp","size":417247417,
  "size_formatted":"397.9 MB","repo_id":"Jundot/Qwen3.8-27B-oQ4e-mtp",
  "source_type":"local"}]}
```

`source_type` ∈ `local` (in the model dir) | `hf_cache` (found in
`~/.cache/huggingface/hub`) | `builtin` (the virtual `MarkItDown`). GGUF rows add
`model_format`.

> A **partially downloaded** model appears here with a small `size`. That is
> expected — it is not a complete model until the task reports `completed`.

Cross-check on the filesystem:

```sh
MODEL_DIR=$(curl -s $OMLX/admin/api/global-settings | jq -r '.model.model_dir')
du -sh "$MODEL_DIR/<owner>/<model>"
ls -la "$MODEL_DIR/<owner>/<model>"
```

A complete MLX model has at minimum `config.json`, `tokenizer.json` (or
`tokenizer.model`), `tokenizer_config.json`, and one or more
`*.safetensors` plus `model.safetensors.index.json` when sharded.

Force re-discovery so the engine pool sees it:

```sh
curl -s -X POST $OMLX/admin/api/reload
# {"status":"ok","message":"Re-discovered 1 models from 2 directories"}
```

Then confirm it is a real (non-virtual) model:

```sh
curl -s $OMLX/admin/api/models | jq -r '.models[] | [.id, .source_type, .estimated_size_formatted, (.loaded|tostring)] | @tsv'
```

## Step 7 — delete a model

```sh
curl -s -X DELETE $OMLX/admin/api/hf/models/<model_name>
# {"success":true,"message":"Model '<model_name>' deleted"}
# 404 {"detail":"Model not found"}
```

`<model_name>` is the `name` field from `GET /admin/api/hf/models` (the bare
model name, not the `owner/model` repo id).

What the server does, in order:

1. Cancels any in-flight download writing into that directory.
2. Unloads the model if it is loaded.
3. `rmtree`s the directory.
4. Refreshes the engine pool.

It refuses (400) if the path is a symlink or not a directory, and validates the
resolved path stays inside the model dir.

> **Never delete `~/.omlx/cache`.** It is a shared 185 GB SSD cache. Deleting a
> model does not touch it, and neither should you.

## Disk-space accounting cheat sheet

```sh
# free space on the data volume (what disk_guard.sh uses)
df -g /System/Volumes/Data | awk 'NR==2 {print $4 " GB free"}'

# what oMLX thinks is free
curl -s $OMLX/admin/api/hf/recommendations | jq '.disk.free_bytes / 1073741824 | floor'

# how much the model dir currently uses
du -sh "$(curl -s $OMLX/admin/api/global-settings | jq -r '.model.model_dir')"

# per-model sizes as oMLX sees them
curl -s $OMLX/admin/api/hf/models | jq -r '.models[] | [.name, .size_formatted] | @tsv'
```

Budget for **two** numbers, not one:

- `download_bytes` — transient disk cost while downloading
- `resident_bytes` — RAM cost once loaded (from `/hf/recommendations`)

A model can fit on disk and still not fit in memory. Check
`memory.scenarios.now.usable_bytes` against `resident_bytes` before committing.

## Gotchas

| Symptom | Cause | Fix |
| --- | --- | --- |
| Task stuck at `pending` forever | Only one download runs at a time; the queue is shared machine-wide | Check `GET /admin/api/hf/tasks` for the active one; wait or cancel it |
| `400 Invalid repository ID` | Not exactly `owner/model`, or contains `.`/`..` | Fix the id |
| `400` on a second download of the same repo | Duplicate in-progress guard | Poll the existing task instead |
| Model listed with a tiny size | Download still in progress | Wait for `status: completed` |
| Model downloaded but not in `/admin/api/models` | Pool not refreshed | `POST /admin/api/reload` |
| `unsupported_reason` non-null | oMLX cannot run that repo | Pick a different repo |
| `DELETE /hf/task/{id}` → 404 "still active" | Task is pending/downloading | `POST /hf/cancel/{id}` first |
| `hf_token_invalid: true` in search | Configured HF token rejected | Anonymous search still works; set a valid token for gated repos |

## Not verifiable without downloading

The following were **not** executed here (no model was downloaded, per the task
rules) and are documented from source only:

- The `completed` state of a task and its final `progress: 100.0`.
- `POST /admin/api/hf/retry/{task_id}` success path.
- `DELETE /admin/api/hf/models/{name}` success path (only the 404 was verified).
- The `files: [...]` partial-download path.

Everything else above — search, model-info, recommendations, tasks, models,
cancel/remove 404s, invalid-repo 400, disk_guard — was run live.
