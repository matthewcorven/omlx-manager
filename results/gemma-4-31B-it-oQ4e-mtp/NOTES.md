# gemma-4-31B-it-oQ4e-mtp — tuning notes

**Model:** `mlx-community/Jundot/gemma-4-31B-it-oQ4e-mtp` — **dense** 30.7B, `gemma4`,
60 layers, hidden 5376, sliding-window 1024, tied embeddings, vocab 262144,
vision-capable (`engine_type: vlm`), 262144 native context, **real MTP head**
(`model-mtp.safetensors`, 0.47B).
**Download size:** 18.60 GiB (19,971,960,832 B). **Resident size:** 18.88 GiB (20,270,118,688 B).
**Profile:** `coding-tuned`. **Final medians (5 runs):** TTFT 297.0 ms, decode 40.06 tps, total 7691.6 ms.

---

## The one thing to read first

**No number in this report is comparable to a number from a different block.**
Absolute decode slid from 56.1 tps at baseline to 40.06 tps at the final 5-run with
**no config change between the two ends of that range** — a ~30% drift over the pass.
Every verdict below is a *paired* comparison:

- **interleaved A/B** (`tuning/ab.py`) for knobs that do not require a reload —
  alternating single requests so drift hits both arms equally;
- **alternating blocks** (`tuning/block.py`) for knobs that do require a reload —
  A,B,A,B blocks of N runs each, medians per block, compared block-to-block;
- **forward+backward ordering** (`tuning/sweep.py`) for multi-value sweeps — each
  value measured once going up and once coming down, so a monotonic load ramp
  cancels out and a step change shows up as a fwd/bwd disagreement.

The baseline and final configs were additionally compared **head-to-head in one
interleaved A/B** (n=6 each) precisely because their separately-measured medians
differ by 29%: baseline 316.3 ms / 37.06 tps vs final 319.5 ms / 37.39 tps. They are
equal within 1%. The 56.1 → 40.06 gap is drift, not a regression.

---

## What helped

**MTP is the whole ballgame — and it was already on.** Turning it off halves decode:
**21.45 tps vs 50.62 tps** at essentially the same TTFT (243.6 vs 271.0 ms). There is
no "enable MTP" gain to claim; the baseline already had it. What the sweep could
actually do was tune its depth — and it could not improve on the default.

| Depth | Decode | vs adaptive |
|---|---|---|
| off | 21.45 tps | −58% |
| 1 | 32.47 tps | −36% |
| 2 | 36.50 tps | −28% |
| 3 | 38.73 tps | −23% |
| 4 | 40.01 tps | −21% |
| 6 | 39.50 tps | −22% |
| 8 | 45.66 tps | ties (see below) |
| **adaptive (default)** | **50.62 tps** | — |

Depth 8 was the only fixed depth that came close, so it was re-tested with
alternating blocks (n=9 per arm): **auto 49.47 tps / 284.1 ms vs d8 49.72 tps /
272.0 ms** — inside noise. Depth 4 was re-tested the same way and lost decisively
(**auto 44.05 tps vs d4 38.45 tps**, −13%). The adaptive default is kept rather than
replaced with a hand-picked number.

This is the **opposite** of the Qwen3.8-27B result, where depth 6 beat adaptive by
+7%. Depth tuning is model-specific; do not carry it across.

## What didn't

**KV quantization.** With MTP on, quant-off was the best arm in both sweep
directions:

| Variant | TTFT | Decode |
|---|---|---|
| **off** | **264.9 ms** | **52.02 tps** |
| 8-bit + `skip_last` | 285.7 ms | 49.33 tps |
| 4-bit + `skip_last` | 286.2 ms | 51.28 tps |
| 4-bit, `skip_last: false` | — | hard error |

8-bit costs 5% decode and 21 ms TTFT. 4-bit is inside noise on decode and also 21 ms
worse on TTFT. There is no memory argument either: 18.88 GB resident sits far under
the ~89.6 GB ceiling. Rejected.

**4-bit KV without `skip_last` does not run at all under MTP.** Hard server error —
see failure modes. `skip_last` must stay `true` whenever KV quant is on.

**`max_context_window: 32768`.** A genuine no-op at both prompt lengths:

| Prompt | native 262144 | 32768 |
|---|---|---|
| 49 tokens | 300.3 ms / 41.51 tps | 297.9 ms / 41.98 tps |
| ~8k tokens (`--context-pad 8000`) | 458.2 ms / 30.43 tps | 451.6 ms / 29.14 tps |

Native is kept because it is free and accepts prompts a 32768 cap would reject with
HTTP 400. This matches Ornith and flint, and contradicts Qwen3.8-27B where 32768 was
a real 3.5% TTFT win.

**`force_sampling: true`.** The one sampling knob with a real cost: **39.49 vs
42.29 tps, −6.6% decode**, and 2.4 ms worse TTFT. Left `false`.

**`enable_thinking: true`.** This is the interesting negative result. Unlike flint,
Qwen3.8-27B and Ornith — where thinking was broken or a no-op — thinking **genuinely
works here**. `chat_template.jinja` has a real `enable_thinking` switch (line 186),
and with `chat_template_kwargs: {"enable_thinking": true}` the model emits real
`reasoning_content` (1,962–2,519 chars across three runs) and then an answer.

It is still rejected: **15,879.8 ms to the first content token vs 326.1 ms** with it
off — a **48×** latency penalty. With `max_tokens: 700` the budget is exhausted by
reasoning before the answer completes (`finish_reason: length`, 1–2 content chunks).
No small coding task can absorb 16 s of preamble.

**DFlash.** Mutually exclusive with MTP — `dflash_enabled: true` + `mtp_enabled: true`
returns HTTP 400. With MTP off and `dflash_draft_model: null` it loads but is a
**no-op**: 21.71 tps, indistinguishable from MTP off. There is no DFlash draft model
on disk. Rejected.

**MoE expert offload.** Not applicable. `GET /admin/api/models/gemma-4-31B-it-oQ4e-mtp/moe-offload-fit`
returns HTTP 400 — correct for a dense model (`enable_moe_block: false`). Recorded as
N/A, not as an error to fix.

## Sampling

Both samplers produce correct code on all three guardrail prompts and are
throughput-neutral (temp 1.0: 49.02 tps / 281.5 ms; temp 0.2: 48.42 tps / 282.2 ms).
The coding sampler is kept for determinism:

```
temperature 0.2, top_p 0.95, top_k 64, force_sampling false
```

## Surprises

1. **Thinking works on this model.** Every other model in this repo either ignores
   `enable_thinking` or never emits an answer with it on. Here it is a real switch
   with real reasoning — and still unusable at 48× TTFC. Worth knowing that "thinking
   is broken" is not a universal property of this server.
2. **The adaptive MTP depth is genuinely good.** On Qwen3.8-27B the adaptive default
   was beatable by a fixed depth. Here it beats every fixed depth 1–6 by 21–36% and
   only ties depth 8. The default is the right answer, which is a result too.
3. **`force_sampling` is not free.** It is easy to assume it only affects sampling
   distribution. It costs 6.6% decode.
4. **`auto_unloaded: true` does not reload.** The API unloads the model when a
   reload-requiring setting changes and leaves it unloaded. `POST /load` and poll
   until `loaded: true`.
5. **A model can report `loaded: true` and then unload itself.** This happened ~105 s
   after a load with no request in flight. The cause was a **server restart by the
   coordinator** smoke-testing an unrelated reranker, not an idle TTL. No measurement
   was in flight, so nothing was discarded — but it is a reminder to re-verify
   `loaded` immediately before every measurement block.
6. **The KV sweep's first attempt was silently invalid.** It ran with MTP off,
   left over from the last arm of the MTP sweep, so every arm landed at ~20.6 tps and
   the whole sweep was meaningless. Re-run with MTP on. Always assert the full
   settings state at the start of a sweep, not just the knob under test.

## Failure modes hit

| Failure | Cause | Fix |
|---|---|---|
| `scaled_dot_product_attention(): incompatible function arguments ... _QuantizedStateProxy` | `turboquant_kv_bits: 4.0` + `turboquant_skip_last: false` + MTP | keep `skip_last: true` whenever KV quant is on |
| HTTP 400 "MTP and DFlash cannot both be enabled" | `dflash_enabled: true` with MTP on | they are mutually exclusive; pick MTP |
| DFlash loads but does nothing (21.71 tps) | `dflash_draft_model: null` | no draft model on disk; not usable |
| `moe-offload-fit` → HTTP 400 | dense model, `enable_moe_block: false` | expected; record as N/A |
| `RuntimeError: model did not load` | `auto_unloaded: true` unloads but does not reload | harness must `POST /load` and poll |
| `measure.py` exits non-zero, no `run 1:` line | intermittent | retry up to 3× |
| `GET .../settings` → 405 | endpoint not implemented | read `.settings` off `GET /admin/api/models` |
| Whole KV sweep at ~20.6 tps | MTP left off from the previous sweep's last arm | assert full settings state before a sweep |
| `NameError: name 'null' is not defined` writing `final.json` | JSON `null` used inside a Python dict literal | use `None` |

## Recommendation

Ship the `coding-tuned` profile as saved: MTP on at adaptive depth, DFlash off, KV
quant off, native context, thinking off, sampling temp 0.2 / top_p 0.95 / top_k 64
with `force_sampling: false`.

The honest summary is that **this model was already tuned by its defaults**. The
final config differs from the defaults in three ways — thinking pinned off, the
coding sampler, and `force_sampling: false` — and its throughput is statistically
identical to the defaults (37.39 vs 37.06 tps paired). The value of the pass is the
negative results: it establishes that MTP adaptive depth is optimal here, that KV
quant and context capping are dead ends, and that thinking is real but far too slow.

If you want to push further, the two things worth trying are (a) a longer-context
re-check — native is kept but the crossover where a 32768 cap starts to help is
unmeasured, and (b) a real quality evaluation of 4-bit KV, since it is
throughput-neutral and would halve KV memory if code quality holds. Neither is worth
doing on a machine that is drifting 30% per pass.

Do **not** re-litigate MTP vs DFlash. MTP wins by 2.4× and they cannot coexist.
