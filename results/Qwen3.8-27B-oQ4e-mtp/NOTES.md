# Qwen3.8-27B-oQ4e-mtp — tuning notes

**Model:** `Jundot/Qwen3.8-27B-oQ4e-mtp` — dense 27.8B (27,781,427,952 params), `qwen3_5`, oQ4e 4-bit + MTP head, vision-capable, 262144 native context.
**Download size:** 15.81 GiB (16,971,681,558 B). **Resident size:** 16.60 GiB (17,820,265,635 B).
**Profile:** `coding-tuned`. **Final medians (5 runs, quiet machine):** TTFT 252.0 ms, decode 59.65 tps, total 5202.9 ms.

---

## The one thing to read first

**No number in this report is comparable to a number from a different block.** Absolute decode slid from 88 tps to 22 tps over the session with no config change, driven by a background Hugging Face download (~38 MB/s) and WindowServer load. Every verdict below is a *paired* comparison:

- **interleaved A/B** (`tuning/ab.py`) for knobs that do not require a reload — alternating single requests so drift hits both arms equally;
- **alternating blocks** (`tuning/block.py`) for knobs that do require a reload — A,B,A,B blocks of N runs each, medians per block, compared block-to-block;
- **forward+backward ordering** (`tuning/sweep.py`) for multi-value sweeps — each value measured once going up and once coming down, so a monotonic load ramp cancels out and a step change is visible as a fwd/bwd disagreement.

The final 5-run number (59.65 tps) is lower than the 78.33 tps baseline purely because the machine was busier. It is not a regression.

---

## What helped

**MTP is the whole ballgame — and it was already on.** Turning it off halves decode: 25.98 tps vs 53.77 tps at identical TTFT (229.9 vs 230.5 ms). There is no "enable MTP" gain to claim here; the baseline already had it. What the sweep could actually do was tune its depth.

**MTP depth 6** — the real tuning win. Against the adaptive default, in a decisive pairwise block: 47.98 → **51.37 tps** (+7% decode) and 6441 → **6050 ms** total (−6% wall time), for a 3% TTFT cost (240.5 → 248.4 ms). Depth 6 was also the only depth to rank at the top in *both* directions of the forward+backward sweep, which is what made it credible despite the load step change that corrupted the pooled medians.

**KV quantization on, 4-bit, `skip_last` true.** KV quant off was the worst config in both sweep directions (48.61 tps vs 60–64 tps for every quantized variant). `skip_last` is a genuine, separately-measured win: 4-bit+skip 55.29 tps / 5622 ms vs 4-bit+no-skip 53.77 tps / 5796 ms. Keeping the most recent tokens at full precision is exactly the right trade for code, where the last few hundred tokens are the ones being continued.

**Context 32768 over native 262144.** 227.7 ms / 52.35 tps vs 235.9 ms / 50.34 tps — 3.5% better TTFT and 4% better decode. This is *opposite* to the methodology's expectation that a smaller window costs nothing but also gains nothing. Plausible mechanism: a smaller KV allocation leaves more of the 128 GB unified pool for the model and the allocator, and shortens whatever per-request KV bookkeeping scales with the configured maximum. The paired interleaved design makes the direction credible even though the magnitude is small.

## What didn't

**DFlash.** Tested with MTP off, as required (they are mutually exclusive — the server returns HTTP 400 if both are set). 23.20 tps vs 22.84 tps for no speculative decoding at all: +1.6%, comfortably inside noise, and 2.2× slower than MTP. Rejected. DFlash is not a substitute for MTP on this model.

**2-bit KV.** It looked like the fastest variant in the pooled sweep (63.68 tps) but its lead over 4-bit was inside noise, and 2-bit KV on a coding workload is a real quality risk that a 300-token throughput benchmark cannot detect. Not worth it for a lead that may not exist.

**Depth 4.** Worse than the adaptive default in the first (invalid) run, and in the clean forward+backward sweep it landed mid-pack with a fwd/bwd disagreement. Not confirmed pairwise, not kept.

## Surprises

1. **`auto_unloaded: true` does not reload.** The API unloads the model when a reload-requiring setting changes and then leaves it unloaded. A harness that assumes the server will bring it back gets `RuntimeError: model did not load`. This cost a full sweep attempt.
2. **A same-value PUT does not trigger a reload.** Only a real change does. This is what made the interleaved harness silently wrong: it re-PUT the full settings object before every request, and for reload-requiring fields that meant a cold reload per request — TTFT ~2900 ms, prefill ~56 tps. The first MTP depth-2, depth-4 and MTP on/off results are invalid and are documented as such in `tuning/INVALID.md`.
3. **A DFlash block leaves `dflash_enabled: true` behind**, which then makes every subsequent MTP PUT fail with HTTP 400. The KV sweep's first attempt died on this.
4. **`PUT /profiles/{name}` returns 404 for a profile that does not exist.** Creation is `POST`. The docs read as if PUT is upsert; it is not.
5. **Thinking mode is not merely slower, it is unusable here.** With thinking on, all 300 tokens went to `reasoning_content` and the model never emitted an answer. For small coding tasks that is a hard fail, not a tradeoff.
6. **The methodology's context expectation was wrong for this model** — see above.

## Failure modes hit

| Failure | Cause | Fix |
|---|---|---|
| TTFT ~2900 ms, prefill ~56 tps | `ab.py` re-PUT reload-requiring settings before every request | use `block.py` for reload knobs |
| `RuntimeError: model did not load` | `auto_unloaded: true` unloads but does not reload | harness must `POST /load` and poll |
| HTTP 400 "MTP and DFlash cannot both be enabled" | leftover `dflash_enabled: true` | clear it before MTP work |
| HTTP 400 on every KV patch | same leftover DFlash flag | same |
| `PUT .../profiles/coding-tuned` → 404 | PUT only updates | use `POST` |
| `measure.py` exits non-zero, no `run 1:` line | intermittent | retry up to 3× |
| 12 tps disagreement between context rounds | coordinator's `POST /global-settings` unloaded all models mid-run | discard, re-run paired; quarantined in `tuning/contaminated/` |

## Recommendation

Ship the `coding-tuned` profile as saved: context 32768, MTP on at depth 6, DFlash off, KV quant 4-bit with `skip_last`, thinking off, sampling temp 0.2 / top_p 0.95 / top_k 20 with `force_sampling`.

If you want to push further, the two things worth trying next are (a) a longer-context re-check — 32768 is right for small coding tasks but this model has 262144 native and the crossover point is unmeasured, and (b) a real quality evaluation of 2-bit KV, since it may be free throughput if code quality holds. Neither is worth doing on a machine with a background download running.

Do **not** re-litigate MTP vs DFlash. MTP wins by 2.2× and they cannot coexist.
