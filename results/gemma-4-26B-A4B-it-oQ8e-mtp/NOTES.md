# gemma-4-26B-A4B-it-oQ8e-mtp — tuning notes

**Model:** `mlx-community/Jundot/gemma-4-26B-A4B-it-oQ8e-mtp` — **MoE** 26.23B total /
4.82B active, `gemma4`, 30 layers, hidden 2816, 128 experts with top-8 routing,
moe_intermediate 704, sliding-window 1024 on 5 of every 6 layers, tied embeddings,
vocab 262144, vision-capable (`engine_type: vlm`), 262144 native context, **real MTP
head** (`model-mtp.safetensors`, `mtp_num_hidden_layers` 4).
**Download size:** 26.86 GiB (28,835,597,716 B). **Resident size:** 26.93 GiB (28,920,467,328 B).
**Profile:** `coding-tuned`. **Final medians (5 runs):** TTFT 117.3 ms, decode 118.6 tps, total 2635.8 ms.

---

## The one thing to read first

**No number in this report is comparable to a number from a different block.**
Every verdict below is a *paired* comparison:

- **interleaved A/B** (`tuning/ab.py`) for knobs that do not require a reload —
  context window, sampler, `force_sampling`;
- **alternating blocks** (`tuning/block.py`) for knobs that do require a reload —
  the MTP depth finalists and the whole-config head-to-head;
- **forward+backward ordering** (`tuning/sweep.py`) for multi-value sweeps — each
  value measured once going up and once coming down, so a monotonic load ramp
  cancels out and a step change shows up as a fwd/bwd disagreement.

Drift was mild this pass (the baseline 5-run read 113.18 tps, the final 5-run read
118.6 tps) but the two configs were still compared head-to-head in one paired
alternating-block test, because that is the only legitimate way to compare them.

---

## What helped

**MTP was already on, and its depth is the one real gain.** Turning MTP off costs
32% decode (paired blocks: **76.71 tps vs 113.00 tps**, n=6 per arm) — there is no
"enable MTP" win to claim. What the sweep could tune was the draft depth, and this
model differs from gemma-4-31B:

| Depth | Decode (fwd+bwd sweep, n=4) | vs depth 4 |
|---|---|---|
| off | 81.88 tps | −31% |
| 1 | 97.07 tps | −18% |
| 2 | 108.85 tps | −9% |
| 3 | 112.32 tps | −6% |
| **4** | **119.03 tps** | — |
| 6 | 101.00 tps | −15% |
| 8 | 93.44 tps | −22% |
| adaptive (default) | 112.14 tps | −6% |

Depth 4 won the sweep, so it was re-tested against adaptive with alternating blocks
(n=10 per arm): **d4 119.28 tps / 107.4 ms vs adaptive 109.72 tps / 120.3 ms** —
a paired **+8.7% decode and −13 ms TTFT**. Depth 3, the runner-up, lost its own
head-to-head against depth 4 (116.83 vs 118.35 tps, 107.7 vs 105.2 ms).

This is the **opposite** of the gemma-4-31B result, where every fixed depth lost
21-36% and only depth 8 tied adaptive. Depth tuning is model-specific; do not carry
it across models.

## What did nothing

- **KV quant** — off wins. With MTP at depth 4: 8-bit+skip 111.54 tps / 105.0 ms,
  4-bit+skip 115.07 tps / 105.7 ms, off 118.04 tps / 99.8 ms. Both quantized arms
  are worse on decode *and* TTFT, and there is no memory argument (26.93 GiB
  resident on a 128 GB machine). 4-bit without `skip_last` does not run at all.
- **Context window** — a genuine null result at both prompt lengths.
  Short prompt: native 104.7 ms / 121.38 tps vs 32768 106.2 ms / 121.31 tps.
  ~8k prompt (`--context-pad 8000`): native 178.9 ms / 96.93 tps vs 32768 181.3 ms /
  96.92 tps. Differences are inside the interleaved noise, so native 262144 is kept
  because it is free.
- **Sampling** — throughput-neutral. Card sampler 118.22 tps / 117.5 ms vs coding
  sampler (temp 0.2) 116.90 tps / 113.7 ms. Both produce correct code on all three
  guardrail prompts; the coding sampler is kept for determinism.
- **`force_sampling`** — 114.86 tps false vs 113.70 tps true. Costs 1%, stays false.
- **MoE expert offload** — **not applicable.** `moe-offload-fit?mtp_enabled=true`
  returns `{"status":"resident","max_percent":null,"bytes":0}`, i.e. the model fits
  entirely in RAM and there is nothing to offload. (`moe_offload_allows_mtp` is also
  false, so offload and MTP can never be combined here.)
- **DFlash / SpecPrefill** — **no-ops.** `dflash_draft_model` and
  `specprefill_draft_model` are both null, so there is nothing to draft from, and
  `dflash_enabled: true` with MTP on is an HTTP 400 (`mtp_enabled and
  dflash_enabled cannot both be True`).

## Thinking is a real switch and still unusable

Unlike several models in this repo, `enable_thinking: true` genuinely works here:
the template switches and the model emits **2.7-2.9k chars of real
`reasoning_content`**. But:

| | thinking off | thinking on |
|---|---|---|
| TTFT | 106.2 ms | 333.4 ms |
| **TTFC** (first content token) | **106.2 ms** | **8951.0 ms** |
| content | 1135-1181 chars | 1 char |
| reasoning | 0 chars | 2773-2868 chars |
| finish_reason | stop | length (at 900 tokens) |

That is an **84x latency penalty** to the first character of answer, and with a
900-token budget the model spends all of it thinking and returns one character of
code. Pinned `enable_thinking: false`.

**Note on empty content:** a run that returns `content: ""` with
`finish_reason: length` after a long reasoning block is a *reasoning-budget
artifact*, not corruption. The reasoning length has to be checked before drawing any
conclusion.

## Final config

The defaults with three deliberate changes: **MTP depth pinned to 4**, the
**coding sampler** (temp 0.2 / top_p 0.95 / top_k 64), and **thinking pinned off**.
Everything else stays at the server default: KV quant off, native context,
`force_sampling` false, `activation_fp16_enabled` false.

```json
{
  "enable_thinking": false,
  "mtp_enabled": true,
  "mtp_fixed_depth": 4,
  "mtp_adaptive_max_depth": null,
  "turboquant_kv_enabled": false,
  "turboquant_kv_bits": 4.0,
  "turboquant_skip_last": true,
  "max_context_window": null,
  "temperature": 0.2,
  "top_p": 0.95,
  "top_k": 64,
  "force_sampling": false,
  "activation_fp16_enabled": false,
  "dflash_enabled": false
}
```

Live settings were diffed against this JSON after the reload: **zero differences**
on all 14 keys. `enable_thinking` was re-read after the final benchmark and is still
`false`.

## Failure modes

1. **4-bit KV without `skip_last` is a hard runtime error under MTP.** The PUT
   succeeds (`requires_reload`, `auto_unloaded`), the model loads, then the first
   decode returns an SSE error event:
   `scaled_dot_product_attention(): incompatible function arguments ... Invoked with
   types: mlx.core.array, mlx_vlm.turboquant._QuantizedStateProxy,
   mlx_vlm.turboquant._QuantizedStateProxy`. The quantized KV state is passed
   straight into attention without being materialized. `skip_last` must stay true
   whenever KV quant is on.
2. **`dflash_enabled` + `mtp_enabled` → HTTP 400** (`mtp_enabled and
   dflash_enabled cannot both be True; choose one speculative-decoding path per
   model`).
3. **DFlash / SpecPrefill are no-ops** — both draft models are null.
4. **`activation_fp16_enabled` is not supported here**
   (`activation_fp16_supported: false`) and was not probed. On flint this knob
   produced a 26x apparent speedup that was actually numerical corruption.
5. **Thinking burns the whole budget** — 900 tokens of reasoning, one character of
   answer, `finish_reason: length`.

## Corruption checks performed

- Every request was **streamed** and the actual text read, not just the numbers.
- The largest speedup in this pass (MTP on vs off, +47%) was verified by reading the
  streamed code output on both arms — coherent Python on both, so it is real.
- `~/.omlx/cache` was 16G throughout, far under the limit, so a saturated-cache
  fault is not implicated in anything here.
- The three guardrail prompts (`quality.md`) all returned coherent, correct code
  with empty `reasoning_content` and `finish_reason: stop`.
