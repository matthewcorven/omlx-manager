---
name: omlx-model-tuning
description: End-to-end procedure for tuning one oMLX 0.7.3rc1 model for small coding tasks and leaving it at a good balance of decode throughput and time-to-first-token. Use when a new model needs a baseline, a settings sweep, a final config, and a results directory — or when a tuning run produced numbers that look wrong. Covers the paired-comparison measurement contract, the reload semantics that silently corrupt TTFT, per-knob decision rules learned from completed models, and the deliverable layout.
---

# Tuning one model on oMLX

This is the per-model playbook. It assumes you have read
`docs/tuning-methodology.md` (the measurement contract) and
`docs/omlx-api-reference.md` (API ground truth). It records what three
completed tuning runs actually established, including where they disagree.

Companion skills: `omlx-model-settings` (field reference), `omlx-benchmark`
(server benchmark endpoints), `omlx-troubleshooting` (when a call fails),
`omlx-model-download` (getting the model first).

## The one rule that invalidates everything else

**Never compare a number from one block to a number from another block.**

Absolute decode throughput on this machine is not stable. It was observed to
slide from 88 to 22 tok/s across a single session with no config change, driven
by Hugging Face download I/O and WindowServer load. A 2x difference between two
blocks can be pure weather.

Every verdict must come from a *paired* comparison: the two variants measured
inside one block, close together, on the same machine state.

Three harnesses exist, copied and adapted per model from
`results/Qwen3.8-27B-oQ4e-mtp/tuning/`:

| Harness | Use for | Shape |
|---|---|---|
| `ab.py` | knobs that do **not** reload | interleaved single requests A,B,A,B,... |
| `block.py` | knobs that **do** reload | alternating blocks of N runs, warmup discarded per block |
| `sweep.py` | multi-value sweeps | forward then backward ordering, to cancel drift |

`measure.py` intermittently exits non-zero with no `run 1:` line. Retry up to
three times with a short sleep before treating it as a real failure.

## Reload semantics — the trap that produces fake results

These keys return `requires_reload: true` or `auto_unloaded: true` on PUT:

- `mtp_enabled`
- `mtp_adaptive_max_depth`
- `turboquant_kv_enabled`
- `dflash_enabled`

`max_context_window` does **not** reload.

**Never re-PUT a patch containing a reload key before every request.** The
original Qwen harness did exactly that and produced ~2900 ms TTFTs that looked
like a catastrophic regression; every request was paying a cold model load.
`block.py` exists to fix this: apply the patch once, reload once, warm up, then
take N measurements.

Two more traps:

- **`auto_unloaded: true` unloads but does not reload.** After such a PUT you
  must `POST /admin/api/models/{id}/load` and wait for `loaded: true`.
- **`dflash_enabled` and `mtp_enabled` are mutually exclusive** — HTTP 400. A
  leftover DFlash flag silently blocks subsequent MTP PUTs.

`GET /admin/api/models/{id}/settings` returns **405**. Read the `.settings`
object off `GET /admin/api/models` instead.

## Per-knob decision rules

These are the outcomes actually measured, not theory. They do not transfer
uniformly — the disagreements are the point.

### Thinking — turn it off, always

`enable_thinking: true` is broken on every model tested. Qwen3.8-27B put all 300
completion tokens into `reasoning_content` and never emitted an answer.
Ornith emitted zero content tokens in 2/2 unbudgeted runs. The only signal is
`ttfc_ms: null` — TTFT looks fine because reasoning tokens are streaming.

`thinking_budget_tokens` is a **floor, not a cap**. A 512-token budget cost 65x
time-to-first-answer-token on Ornith (4076 ms vs 62 ms). Do not use it as a
workaround for thinking being slow; use it as evidence that thinking must be off.

Test it once per model to check whether the model behaves differently, then set
`enable_thinking: false` and document it as a hard constraint.

### Context window — model-specific, do not assume

- Qwen3.8-27B: `max_context_window: 32768` won — 3.5% TTFT and 4% decode over
  native 262144.
- Ornith-1.0-35B: **null result.** Native 58.8 ms / 151.90 tps vs 32768 59.0 ms
  / 151.24 tps. Kept native.

So "a smaller window is faster" did not reproduce. Measure it; expect either.

### KV cache quantization — model-specific, and often a loss

- Qwen3.8-27B: a real win. 4-bit + `turboquant_skip_last: true` beat quant-off
  (60.62 vs 48.61 tps). `skip_last` alone was worth ~2.5% within the family.
- Ornith-1.0-35B: a clear **loss**. 8-bit + skip_last −15% decode, 4-bit +
  skip_last −14%, 4-bit without skip_last −16%. All reverted.

Sweep all four arms (off / 8-bit+skip / 4-bit+skip / 4-bit no-skip) with
`block.py`. Do not carry a verdict from one model to another.

### Speculative decoding — only if a draft head exists

Check first, before spending time:

- is there an `mtp_enabled` setting that the model accepts, and is there a
  `model-mtp.safetensors` in the model directory?
- are `dflash_draft_model` and `specprefill_draft_model` non-null?

If both draft fields are null, DFlash and SpecPrefill are **no-ops**. On Ornith
they were, and DFlash landed inside noise while SpecPrefill was 1.9% slower.
State that in one line and move on.

On Qwen3.8-27B, MTP was the single dominant lever (~2x decode) — but it was
already on at baseline, so the real gain came from depth tuning:
`mtp_adaptive_max_depth: 6` beat the adaptive default by +7% decode and −6% total
wall time for a 3% TTFT cost.

### MoE expert offload — only when resident pressure exists

The lever relieves unified memory, not disk. Use it only when resident size
approaches the ~89.6 GB practical ceiling.

Check availability without loading, once the model is locally registered:

```sh
curl -s "$OMLX/admin/api/models/<id>/moe-offload-fit?mtp_enabled=true"
# {"status":"fit","max_percent":20,"bytes":55680273631,"reserve_bytes":4294967296}
```

This endpoint 404s `"Model not found"` unless the model is downloaded and
registered — you cannot probe a model you have not downloaded. It also returns
400 `"Model does not support MoE expert offload: <id>"` for dense models.

If the model is small enough that residency is not a problem, the honest verdict
is **not applicable**, as on Ornith at 19.96 GB. Do not tune a lever that has no
problem to solve.

### Sampling — start from the model card

Do not inherit another model's sampler. Read the card.

- Qwen3.8 family: thinking `temp 1.0 / top_p 0.95 / top_k 20 / min_p 0.0`;
  non-thinking `temp 0.7 / top_p 0.80 / top_k 20 / presence_penalty 1.5`.
- Qwen3.6-35B-A3B: precise coding `temp 0.6 / top_p 0.95 / top_k 20`.
- Gemma-4 family: `temp 1.0 / top_p 0.95 / top_k 64`.
- Ornith: `temp 0.6 / top_p 0.95 / top_k 20` precise; `temp 1.0 / top_p 0.95`
  broad.

Qwen3.8-27B ended on `temp 0.2` after sampling sweeps; Ornith kept the card's
`temp 1.0 / top_p 0.95 / top_k 20 / force_sampling true`. Sampling is cheap to
sweep and the card value is a starting point, not a verdict.

## Procedure

1. **Confirm the model is present and unloaded.** `GET /admin/api/models`, check
   `loaded` and read `.settings` for the current state.
2. **Confirm the benchmark slot is free.** Only one agent benchmarks at a time;
   a second `bench/start` returns 409. Check
   `GET /admin/api/bench/accuracy/queue/status` for `running: false` and an
   empty queue.
3. **Smoke test on defaults.** Confirm it loads and answers coherently.
4. **Baseline** on defaults with thinking off: one warmup discarded, 3 runs.
5. **Read the model's own card** for native context and sampler.
6. **Sweep only the levers that exist for this model**, each paired: thinking,
   context, spec decode (if a head exists), KV quant (4 arms), MoE offload (only
   under residency pressure), sampling.
7. **Choose the final config** as a balance of decode throughput and TTFT.
   Justify any TTFT cost accepted for a decode gain.
8. **Apply, reload, then diff live settings against the intended JSON.** The
   diff must be zero. A PUT returning 200 does not mean the value stuck.
9. **Re-verify `enable_thinking`.** It has reverted from `false` to `true` on its
   own after a verified apply. Cause unidentified. Re-read it before and after
   any benchmark on a previously tuned model.
10. **Quality check** — 3 prompts, confirm coherent answers, empty
    `reasoning_content`, `finish_reason: stop`.
11. **Leave the settings applied.** Do not restore defaults.

## Deliverables

Create `results/<model_id>/` matching the completed models:

```
NOTES.md              narrative: what was tested, rejected, and why; failure modes
final.json            machine-readable result (schema below)
baseline.json         baseline runs
final-runs.json       N runs on the applied final config
final-settings.json   the intended settings object
settings-live.json    read back from the server after apply
settings-start.json   settings before any change
quality.md            the 3-prompt check
quality-raw.json      raw responses
tuning-log.md         chronological, including dead ends
tuning/               adapted harnesses and every raw sweep JSON
```

`final.json` keys: `model_id`, `repo_id`, `quant`, `architecture`,
`native_context`, `download_size`, `resident_size`, `model_path`, `profile`,
`baseline`, `final_medians`, `sweep`, `settings`, `rationale`, `failure_modes`,
`measurement_caveat`. Each `sweep` row is
`{stage, variant, ttft_ms, decode_tps, verdict}`.

`final.json` and `NOTES.md` must both be committed before the model counts as
tuned, and only then does it get a row in `results/COMPARISON.md`.

## Committing

Commit in stages as results land; do not let sweep JSONs accumulate untracked.
Prefix messages with the model name. Stage specific paths — never `git add -A`,
because other agents' work may be in the tree.

## Reading a result that looks wrong

Before believing a surprising number, check in this order:

1. Was the model cold? Look for a reload immediately before the run.
2. Was another block's number used as the comparison? That is invalid.
3. Was a download or another benchmark running concurrently?
4. Is `ttfc_ms` null while `ttft_ms` looks normal? That is thinking, not speed.
5. Did the harness discard a warmup?

## Two ways a model can look corrupt when it isn't

Both were hit for real on `flint-oQ4e` and both cost a full tuning pass.

### 1. Reasoning budget starves content

With a non-streaming request and `max_tokens` of 120-150, a thinking-capable
model spends the entire budget on `reasoning_content` and returns
`content: ""` with `finish_reason: length`. That looks exactly like
corruption. Always check `reasoning_len` / reasoning chunk count before
concluding anything, and for quality checks **stream and use
`max_tokens >= 350`**.

### 2. A saturated SSD prefix cache serves poisoned prefixes

If `~/.omlx/cache` is at its `cache.ssd_cache_max_size` limit, coherence can
break on a config that is otherwise fine — reloading does not help, which
makes it look like a model or setting fault. Symptoms: word salad that
survives a settings revert and a reload, plus server log lines like
`Invalidated N SSD index entries with stale layer cache signature`.

Recovery: unload the model, move `~/.omlx/cache/*` to a quarantine directory
(preserve it, do not delete), reload, re-probe. Check the size before every
tuning pass:

```sh
du -sh ~/.omlx/cache
```

### Corollary: a suspiciously large speedup deserves a coherence check first

`activation_fp16_enabled: true` on flint gave TTFT 60-66 ms against
1756 ms for `false` — a 26x gap. It was pure noise: the corrupted model never
entered its reasoning phase, so it began streaming garbage immediately. When a
knob produces a speedup of that magnitude, read the output before recording
the number, and trust `activation_fp16_supported: false` over any measurement.
