---
name: omlx-benchmark
description: Run throughput and long-context benchmarks on oMLX 0.7.3rc1, stream their SSE progress, read the result metrics, and measure TTFT / decode tok-s for a coding prompt with plain curl. Use when benchmarking a model, comparing settings, validating a tuning change, or measuring time-to-first-token and generation speed.
---

# oMLX benchmarking

Verified against a live oMLX 0.7.3rc1 server on `http://127.0.0.1:8001`.
Bench **execution** requires a loaded real model and is marked **unverified** —
no model was downloaded while writing this. Every request/response *shape* and
every validation error below was verified live.

## Setup

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=http://127.0.0.1:8001
```

## Rule: one benchmark at a time

Only one benchmark of **any** type (throughput, context, accuracy, ANE-tune) may
run at once. A second `start` returns **409**. Always check first:

```sh
curl -s $OMLX/admin/api/bench/active | jq
# {"running":false,"bench_id":null,"model_id":null,"context_profile":null}

curl -s $OMLX/admin/api/bench/context/active | jq
# {"running":false,"bench_id":null,"model_id":null}
```

## Throughput benchmark

### Start

```sh
curl -s -X POST $OMLX/admin/api/bench/start \
  -H 'Content-Type: application/json' -d '{
    "model_id": "<model_id>",
    "prompt_lengths": [1024, 4096, 16384],
    "generation_length": 128,
    "batch_sizes": [],
    "context_profile": "code_python",
    "warmup_mode": "quick",
    "align_prompt_to_ane": false,
    "force_lm_engine": false
  }' | jq
```

```json
{"bench_id":"7f3c1a9e2b4d","status":"started","total_tests":3}
```

`total_tests = len(prompt_lengths) + len(batch_sizes) * 2`.

### Request body (`BenchmarkRequest`)

| Field | Type / default | Notes |
| --- | --- | --- |
| `model_id` | string | **Required.** 404 `{"detail":"Model not found: <id>"}` if unknown |
| `prompt_lengths` | `list[int]` | Each must be in `[1024, 4096, 8192, 16384, 32768, 65536, 131072, 200000]` |
| `generation_length` | int (128) | Tokens to generate per test. **Must be ≥ 16 or `gen_tps` comes back `null`** |
| `batch_sizes` | `list[int]` | Each must be in `[2, 4, 8]`. Empty = no batch tests |
| `context_profile` | enum (`code_python`) | `code_python` \| `code_mixed` \| `novel_ko` \| `novel_en` \| `novel_ja` |
| `warmup_mode` | enum (`quick`) | `quick` \| `ane_2048` |
| `align_prompt_to_ane` | bool (false) | Pad prompts to the ANE tile length |
| `force_lm_engine` | bool (false) | Bypass the VLM/other engine path |
| `external` | object \| null | Benchmark an external engine instead |

Validation errors are pydantic messages inside `detail`:

```json
{"detail":"1 validation error for BenchmarkRequest\nprompt_lengths\n  Value error, Invalid prompt length 999. Must be one of [1024, 4096, 8192, 16384, 32768, 65536, 131072, 200000] [type=value_error, input_value=[999], input_type=list]\n    For further information visit https://errors.pydantic.dev/2.14/v/value_error"}
```

### Stream progress (SSE)

```sh
BENCH_ID=<bench_id>
curl -N -s $OMLX/admin/api/bench/$BENCH_ID/stream
```

Server-sent events, `data: {json}\n\n` per line, with `: keepalive` comments.
The stream **replays** everything already emitted, then attaches live — so you
can connect late and still see the whole run.

Event types:

| `type` | Payload |
| --- | --- |
| `progress` | `{"type":"progress","phase":"single","message":"...","current":2,"total":3}` |
| `result` | `{"type":"result","data":{...}}` |
| `done` | `{"type":"done","summary":{"model_id":"...","context_profile":"code_python","total_time":123.4,"total_tests":3}}` |
| `upload` / `upload_done` / `upload_skipped` | SSD-cache upload phase |
| `error` | `{"type":"error","message":"..."}` |

Phases in order: `idle` → `upload` → `unload` → `load` → `warmup` → `single` →
`batch` → `cleanup`.

Pretty-print the stream:

```sh
curl -N -s $OMLX/admin/api/bench/$BENCH_ID/stream \
  | grep '^data: ' | sed 's/^data: //' | jq -c 'if .type=="result" then {type, pp:.data.pp, tg:.data.tg, ttft_ms:.data.ttft_ms, gen_tps:.data.gen_tps} else . end'
```

### Result metrics

Single-test result (`test_type: "single"`):

| Key | Unit | Meaning |
| --- | --- | --- |
| `pp` | int | Prompt length tested |
| `tg` | int | Generation length tested |
| `ttft_ms` | ms, 1 dp | Time to first token. **`null` if the first token was never observed** |
| `tpot_ms` | ms, 2 dp | Time per output token. **`null` if `completion_tokens < 16`** |
| `gen_tps` | tok/s, 1 dp | Decode speed. **`null` if `completion_tokens < 16`** |
| `processing_tps` | tok/s, 1 dp | Prefill speed. `null` when timing was not observed |
| `e2e_latency_s` | s, 3 dp | Wall clock for the whole request |
| `total_throughput` | tok/s, 1 dp | `(prompt + completion) / e2e` |
| `peak_memory_bytes` | int | Peak RSS/GPU memory during the test |
| `prompt_tokens` | int | Actual prompt tokens |
| `completion_tokens` | int | Actual generated tokens |
| `cached_tokens` | int | Prompt tokens served from cache |
| `system_metrics` | object | Host-level counters |

Batch-test result (`test_type: "batch"`, `pp` is always 1024):

| Key | Meaning |
| --- | --- |
| `pp_tps` | Aggregate prefill tok/s across the batch |
| `tg_tps` | Aggregate decode tok/s across the batch |
| `avg_ttft_ms` | Mean TTFT across the batch |
| `e2e_latency_s` | Wall clock |
| `peak_memory_bytes` | Peak memory |
| `total_gen_tokens` | Sum of generated tokens |
| `batch_size` | 2, 4, or 8 |

### Collect results without streaming

```sh
curl -s $OMLX/admin/api/bench/$BENCH_ID/results | jq
```

```json
{"bench_id":"7f3c1a9e2b4d","status":"completed","context_profile":"code_python",
 "results":[{"test_type":"single","pp":1024,"tg":128,"ttft_ms":412.3,
   "tpot_ms":27.61,"gen_tps":36.2,"processing_tps":2483.1,"e2e_latency_s":3.945,
   "total_throughput":292.1,"peak_memory_bytes":17820265635,
   "prompt_tokens":1024,"completion_tokens":128,"cached_tokens":0,
   "system_metrics":{}}],
 "error":null,"upload_state":null}
```

404 `{"detail":"Benchmark not found: abc123"}` for an unknown id.

### Cancel

```sh
curl -s -X POST $OMLX/admin/api/bench/$BENCH_ID/cancel
# {"status":"cancelled","bench_id":"7f3c1a9e2b4d"}
# 404 {"detail":"Benchmark not found: <id>"}
```

## Long-context benchmark

Measures the largest context the model can actually prefill on this machine.

```sh
curl -s -X POST $OMLX/admin/api/bench/context/start \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"<model_id>","target_tokens":131072}' | jq
# {"bench_id":"c9a1...","status":"started","target_tokens":131072}
```

`target_tokens` must be in `[16384, 32768, 65536, 131072, 262144, 524288]`:

```json
{"detail":"1 validation error for ContextBenchmarkRequest\ntarget_tokens\n  Value error, Invalid target 999. Must be one of [16384, 32768, 65536, 131072, 262144, 524288] [type=value_error, input_value=999, input_type=int]\n    For further information visit https://errors.pydantic.dev/2.14/v/value_error"}
```

> **Memory Guard must be enabled.** If the effective ceiling is ≤ 0 the request
> is rejected with 400. Check `memory.prefill_memory_guard` in
> `GET /admin/api/global-settings`.

```sh
curl -s $OMLX/admin/api/global-settings | jq '.memory'
# {"prefill_memory_guard":true,"memory_guard_tier":"balanced","memory_guard_custom_ceiling_gb":0.0}
```

Stream and results:

```sh
curl -N -s $OMLX/admin/api/bench/context/$BENCH_ID/stream
curl -s $OMLX/admin/api/bench/context/$BENCH_ID/results | jq
```

```json
{"bench_id":"c9a1...","status":"completed","phase":"cleanup","progress":100,
 "message":"done","error":null,
 "result":{"model_id":"<id>","target_tokens":131072,"native_context_length":131072,
   "measured_tokens":131072,"verified_tokens":131072,"verified_prompt_tokens":131072,
   "applied_tokens":131072,"applied":true,"capped_by":null,"attempts":1,
   "extended":false,"prefill_tps":2483.1,"duration_s":52.8,
   "prefill_priority":"normal"}}
```

| Field | Meaning |
| --- | --- |
| `native_context_length` | What the model's `config.json` claims |
| `measured_tokens` | What the harness actually built |
| `verified_tokens` | Tokens confirmed by the tokenizer |
| `applied_tokens` | Context window actually applied to the engine |
| `applied` | Whether the target was reached |
| `capped_by` | What stopped it (`memory_guard`, `native_context`, …) |
| `attempts` | Retries after a memory-guard rejection |
| `extended` | Whether the context window had to be raised above the default |
| `prefill_tps` | Prefill throughput at that length |
| `duration_s` | Wall clock |

Cancel: `POST /admin/api/bench/context/{id}/cancel`.

## Measuring TTFT and decode tok/s with curl

**You do not need client-side timing.** oMLX puts the timings in the `usage`
object of the final streaming chunk. This is the most reliable measurement path.

### The recipe

```sh
MODEL='<model_id>'
PROMPT='Write a Python function that merges two sorted lists in O(n) time. Include a docstring and type hints.'

curl -N -s $OMLX/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg m "$MODEL" --arg p "$PROMPT" '{
        model: $m,
        messages: [{role:"user", content:$p}],
        max_tokens: 256,
        temperature: 0.2,
        stream: true,
        stream_options: {include_usage: true}
      }')" \
  | grep '^data: ' | sed 's/^data: //' | grep -v '^\[DONE\]' \
  | jq -c 'select(.usage != null) | .usage'
```

> The `grep -v '^\[DONE\]'` is required — the final `data: [DONE]` line is not
> JSON and makes `jq` abort with `parse error: Invalid numeric literal`.
> Equivalent alternative: `jq -R 'fromjson? // empty'` instead of the two greps.

```json
{"prompt_tokens":38,"completion_tokens":256,"total_tokens":294,
 "input_tokens":38,"output_tokens":256,
 "prompt_tokens_details":{"cached_tokens":0,"audio_tokens":0},
 "completion_tokens_details":{"reasoning_tokens":0},
 "model_load_duration":null,
 "time_to_first_token":0.4123,
 "time_to_first_visible_token":0.4123,
 "total_time":7.4812,
 "prompt_eval_duration":0.0153,
 "generation_duration":7.0689,
 "prompt_tokens_per_second":2483.1,
 "generation_tokens_per_second":36.2}
```

Read directly:

| Field | Unit | Meaning |
| --- | --- | --- |
| `time_to_first_token` | **seconds** | TTFT |
| `time_to_first_visible_token` | seconds | First token after output filters (chat streaming only) |
| `prompt_eval_duration` | seconds | Prefill time |
| `generation_duration` | seconds | Decode time |
| `prompt_tokens_per_second` | tok/s | `(prompt_tokens - cached_tokens) / prompt_eval_duration` |
| `generation_tokens_per_second` | tok/s | `completion_tokens / generation_duration` |
| `total_time` | seconds | End to end |
| `model_load_duration` | seconds \| null | `null` when the load took ≤ 1.0 s |
| `prompt_tokens_details.cached_tokens` | int | Prompt tokens served from the prefix cache |
| `completion_tokens_details.reasoning_tokens` | int | Reasoning tokens (thinking models) |

Convert to the units the repo reports in:

```sh
... | jq '{ttft_ms: (.time_to_first_token*1000|round),
           decode_tps: (.generation_tokens_per_second*10|round/10),
           prefill_tps: (.prompt_tokens_per_second*10|round/10),
           total_ms: (.total_time*1000|round),
           prompt_tokens, completion_tokens, cached_tokens: .prompt_tokens_details.cached_tokens}'
```

Verified output for a synthetic usage object:

```json
{"ttft_ms":210,"decode_tps":36.2,"prefill_tps":100,"total_ms":300,
 "prompt_tokens":8,"completion_tokens":1,"cached_tokens":0}
```

`generation_tokens_per_second` is `null` for very short generations, so guard
the multiply if you may generate fewer than ~16 tokens:

```sh
jq '{ttft_ms: (.time_to_first_token*1000|round),
     decode_tps: (if .generation_tokens_per_second then (.generation_tokens_per_second*10|round/10) else null end)}'
```

### Streaming chunk sequence (verified)

A 1-token reply produces exactly six SSE events:

```
data: {"choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}
data: {"choices":[{"index":0,"delta":{"role":"assistant"}}]}
data: {"choices":[{"index":0,"delta":{"content":"hi"}}]}
data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
data: {"choices":[],"usage":{...}}
data: [DONE]
```

The **penultimate** chunk carries `usage` and has an **empty `choices` array** —
that is why you must `select(.usage != null)` rather than reading the last
`choices[0]`. `stream_options.include_usage: true` is required.

### Non-streaming

```sh
curl -s $OMLX/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model":"<model_id>",
  "messages":[{"role":"user","content":"hi"}],
  "max_tokens":16
}' | jq
```

```json
{"id":"chatcmpl-...","object":"chat.completion","created":1793241081,
 "model":"<model_id>",
 "choices":[{"index":0,"message":{"role":"assistant","content":"hi"},"finish_reason":"stop"}],
 "usage":{"prompt_tokens":8,"completion_tokens":1,"total_tokens":9,
   "time_to_first_token":0.21,"generation_tokens_per_second":null, ...}}
```

`generation_tokens_per_second` is `null` for very short generations.

### Using the repo harness

```sh
python3 scripts/measure.py --model "$MODEL" --runs 3
```

It streams with `stream_options.include_usage` and reports `ttft_ms`,
`decode_tps`, `prefill_tps`, `total_ms`, `prompt_tokens`, `completion_tokens`,
`finish_reason`, `text`, plus a median summary.

> **Known bug in `scripts/measure.py`:** its `pad_context()` posts
> `{"model": ..., "text": ...}` to `/tokenize`. The real body is
> `{"model", "messages": [...]}` or `{"model", "prompt": "..."}` — `text` is
> rejected with 400, so `pad_context()` silently falls back to `len(text)//4`
> token estimation. Context-padded runs are therefore approximate. Fix the body
> shape if exact prompt-token counts matter.

Correct token counting:

```sh
curl -s $OMLX/tokenize -H 'Content-Type: application/json' \
  -d '{"model":"<model_id>","prompt":"def f():\n    return 1\n"}' | jq
# {"count":12,"max_model_len":131072,"tokens":[...],"token_strs":[...]}

curl -s $OMLX/tokenize -H 'Content-Type: application/json' \
  -d '{"model":"<model_id>","messages":[{"role":"user","content":"hi"}]}' | jq
```

Sending `text` gives:

```json
{"error":{"message":"body -> TokenizeChatRequest -> messages: Field required; body -> TokenizeCompletionRequest -> prompt: Field required","type":"invalid_request_error","param":"messages","code":null}}
```

## Recording results

`AGENTS.md` requires everything under `results/<model>/`:

```
results/<model>/baseline.json     # first measurement, untouched
results/<model>/sweep.jsonl       # one JSON object per settings change
results/<model>/final.json        # best configuration
results/<model>/NOTES.md          # what you tried and why
```

Append one line per sweep step:

```sh
MODEL='<model_id>'
mkdir -p "results/$MODEL"
CFG=$(curl -s $OMLX/admin/api/models | jq -c --arg m "$MODEL" '.models[]|select(.id==$m)|.settings')
python3 scripts/measure.py --model "$MODEL" --runs 3 --out "results/$MODEL/last.json"
jq -nc --arg model "$MODEL" --argjson cfg "$CFG" \
  --argjson m "$(jq -c . "results/$MODEL/last.json")" \
  '{ts: (now|todate), model: $model, settings: $cfg, metrics: $m}' \
  >> "results/$MODEL/sweep.jsonl"
```

Verified output shape:

```json
{"ts":"2026-10-29T02:36:20Z","model":"x","settings":{"a":1},"metrics":{"ttft_ms":210}}
```

## Gotchas

| Symptom | Cause | Fix |
| --- | --- | --- |
| `409` on `bench/start` | Another benchmark is running | Check `bench/active` and `bench/context/active` |
| `gen_tps` / `tpot_ms` are `null` | `completion_tokens < 16` | Use `generation_length` ≥ 16 (128 is the default) |
| `ttft_ms` is `null` | First token never observed | Usually a failed/aborted run |
| Context bench `400` | Memory Guard disabled | Enable `memory.prefill_memory_guard` |
| `usage` never appears in the stream | `stream_options.include_usage` not set | Add it |
| `jq` on the last chunk fails | Last chunk is `data: [DONE]` | `grep '^data: '` then `select(.usage != null)` |
| `/tokenize` 400 | Sent `text` | Send `messages` or `prompt` |
| Bench `404` | Unknown `model_id` or `bench_id` | `GET /admin/api/models` |

## Not verifiable without a loaded model

Documented from source, **not** executed here:

- `POST /admin/api/bench/start` success response and the full SSE event stream.
- `GET /admin/api/bench/{id}/results` with real result rows.
- `POST /admin/api/bench/{id}/cancel` success.
- The entire context-benchmark flow.
- `usage` timing fields with non-null values (the streaming *shape* was verified
  against the virtual model, but it has no engine, so timings were absent).

Verified live: `bench/active`, `bench/context/active`, the 404 on an unknown
model, the 400 pydantic messages for `prompt_lengths` / `target_tokens` /
`context_profile`, the 404 on unknown `bench_id` for both `results` and `cancel`,
the `/tokenize` body-shape error, and the exact six-event streaming chunk
sequence.
