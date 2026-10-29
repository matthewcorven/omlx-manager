# Tuning methodology

How we go from "model downloaded" to "settings left at a good balance of
throughput and time-to-first-token" for **small coding tasks**.

## 1. What we are optimizing

Small coding tasks are short prompts (a few hundred to a few thousand tokens)
producing short-to-medium outputs (100–600 tokens). For that shape of work the
user-visible latency is:

```
total = TTFT + (completion_tokens / decode_tps)
```

TTFT dominates perceived responsiveness when outputs are short. So the objective
is **not** maximum decode throughput. It is:

1. Keep TTFT low and stable.
2. Keep decode fast enough that a 300-token answer lands in a few seconds.
3. Never trade correctness for speed.

We report both numbers and pick settings on the Pareto front, preferring the
point with the lowest TTFT among those within ~10% of the best decode rate.

## 2. Measurement contract

All numbers come from `scripts/measure.py`, which streams
`POST /v1/chat/completions` and times:

| Metric | Definition |
| --- | --- |
| `ttft_ms` | request send → first non-empty `delta.content` |
| `decode_tps` | `(completion_tokens - 1) / (last_token_time - first_token_time)` |
| `prefill_tps` | `prompt_tokens / ttft` |
| `total_ms` | request send → stream end |

Rules:

- `temperature: 0` so runs are comparable.
- **3 runs minimum**, report the **median**. First run after a load is a warmup
  and is discarded (run it, then start counting).
- One benchmark at a time. oMLX returns `409` on concurrent benchmark jobs, and
  concurrent chat requests would corrupt the timing anyway.
- Record the exact settings JSON alongside every measurement. A number without
  its settings is not a result.

## 3. Baseline

Before changing anything, measure the model on **default settings**:

```sh
python3 scripts/measure.py --model <id> --runs 1 --smoke        # does it answer at all
python3 scripts/measure.py --model <id> --runs 3 --out results/<model>/baseline.json
```

If the smoke run fails, stop and fix loading first — do not tune a broken model.

## 4. The knobs that actually matter

Ordered by expected impact for this workload. Everything is set through
`PUT /admin/api/models/{id}/settings`.

### Context window
`max_context_window` — the single biggest lever on memory and on prefill cost.
A 262144-token window costs KV cache even when unused. For small coding tasks
**32768 is usually plenty**; go to 65536 only if the model is used for
repo-scale context. Lowering this frees memory for weights and larger batches.

### KV cache quantization
`turboquant_kv_enabled`, `turboquant_kv_scheme`, `turboquant_kv_bits`,
`turboquant_kv_skip_last`. Quantizing the KV cache shrinks per-token memory,
which lets a bigger context fit and speeds up attention. `skip_last` protects
the most recent tokens at full precision, which matters for output quality.
Start with the scheme the model's own profile ships, then try one step lower.

### Speculative decoding
`mtp_enabled`, `dflash_enabled`, `specprefill_enabled`. These are the release
notes' headline wins (Ling-3.1-flash +82% decode, Qwen3.8-Flash-Next +24%).
They only work when the checkpoint actually ships the draft head — check
`mtp_compatible` / `dflash_compatible` on `GET /admin/api/models` before
enabling. Enabling an incompatible head either no-ops or errors.

### MoE expert offload
`moe_expert_offload_enabled`, `moe_expert_offload_resident_fraction`. For MoE
models too large to hold fully resident, keeping a fraction of experts on SSD
trades TTFT for the ability to run at all. Higher resident fraction = better
TTFT, more RAM. Use `GET /admin/api/models/{id}/moe-offload-fit` to see what
fits, and only offload when the model does not fit otherwise.

### Sampling
`temperature`, `top_p`, `top_k`, `min_p`, `repetition_penalty`. For coding,
low temperature (0.0–0.3) and `top_p` 0.9–0.95. Sampling settings barely affect
speed; they affect quality. Do not "tune" them for throughput.

### Thinking budget
`enable_thinking`, `thinking_budget_enabled`, `thinking_budget_tokens`. Thinking
tokens are pure TTFT cost for small tasks. **Disable thinking** for this
workload unless the model is materially worse without it. If it must stay on,
cap the budget (e.g. 512) rather than leaving it unbounded.

### Power
`gpu_power_limit_w`. Higher power raises sustained clocks but throttles sooner
and heats the chassis. Leave at default unless measurements show a clear win.

## 5. Tuning procedure

For each model, in this order — stop early when a step stops helping:

1. **Baseline** on defaults. Record.
2. **Context**: set `max_context_window` to 32768. Re-measure. Keep if TTFT
   improves or is neutral (it usually frees memory).
3. **Thinking**: disable thinking (or cap the budget). Re-measure. This is
   usually the largest TTFT win for coding prompts.
4. **Speculative decoding**: enable MTP/DFlash if compatible. Re-measure.
   Keep only if decode improves without TTFT regression.
5. **KV quantization**: try the next-lower bit width. Re-measure. Keep if it
   helps and a spot-check of output quality still looks right.
6. **MoE offload** (MoE models that don't fit): sweep resident fraction
   upward until memory is tight, then back off one step.
7. **Sampling**: set the coding defaults. Verify output quality on 3 fixed
   prompts. No speed measurement needed.

Each step is a single-variable change against the previous best. Never change
two knobs at once — you will not be able to attribute the result.

## 6. Settling

Leave the model on the best measured configuration, then:

- Save it as a named profile: `PUT /admin/api/models/{id}/profiles/{name}`.
- Write `results/<model>/final.json` with the settings and the final medians.
- Write `results/<model>/NOTES.md` explaining what helped, what didn't, and
  anything surprising.

The "good balance" we ship is: **lowest TTFT among configurations within 10% of
the best decode rate**, with thinking off and context at 32768 unless the model
proved it needs more.

## 7. Quality guardrail

Speed numbers are worthless if the model got dumber. Every final configuration
must pass three fixed coding prompts (a pure function, a bug fix, a small
refactor) with output that a human would accept. Record the outputs in
`results/<model>/quality.md`. If a speed win breaks quality, revert it.
