# Ornith-1.0-35B-oQ4e — tuning notes

`Jundot/Ornith-1.0-35B-oQ4e` · oQ4e 4-bit · 20.64 GB disk / 19.86 GB resident ·
native context 262144 · VLM engine · `qwen3_5_moe` · **no MTP head**.

## The one thing to read first

**On this model, nothing helps.** The final config is the default config with
thinking turned off and the model card's sampler applied. Every performance knob
was tested and every one of them was neutral or negative. That is the finding,
and it is a real one — do not spend another session re-testing these.

## What helped

- **`enable_thinking: false`** — the only change that matters, and it is a
  correctness fix rather than a speed win. With thinking on the model either
  never emits an answer at all, or takes 65x longer to reach the first answer
  token. See below.
- **`force_sampling: true` with the card's sampler** (temp 1.0 / top_p 0.95 /
  top_k 20) — no speed effect, but it makes the profile authoritative instead of
  the generation config.

## What didn't

- **Context 32768** — 59.0 ms / 151.24 tps vs native 58.8 ms / 151.90 tps. The
  Qwen3.8-27B result that 32768 is faster does **not** reproduce. Keep native.
- **DFlash** — +0.07% decode, inside noise. `dflash_compatible: true` is
  misleading: `dflash_draft_model` is `null`, so there is no draft to speculate
  with.
- **SpecPrefill** — −1.9% decode. Same problem, `specprefill_draft_model` null.
- **TurboQuant KV, all four configs** — 14–16% *slower* decode, no TTFT benefit.
  This is the biggest divergence from Qwen3.8-27B, where KV quant was a win.
  `skip_last` is worth ~2.5% within the quantized family but cannot rescue it.
- **MoE expert offload** — not applicable. True MoE, but 19.86 GB resident
  against an 89.23 GB ceiling. No residency pressure to relieve.

## Surprises

1. **`thinking_budget_tokens` is a floor, not a cap.** A 512-token budget still
   produced ~500 reasoning tokens and a 4076 ms time-to-first-answer-token. If
   you were hoping to keep thinking and just bound it, you cannot.
2. **`dflash_compatible: true` does not mean DFlash works.** It means the
   architecture *could* take a draft. Without `dflash_draft_model` the flag is a
   no-op, and the block A/B confirms it: 148.75 vs 148.85 tps.
3. **KV quantization is architecture-dependent, not a free win.** The same
   TurboQuant path that gave Qwen3.8-27B +25% decode costs this model 14%. Always
   measure it per model; never carry it over.
4. **The model is fast and small.** 146 tps decode at 19.86 GB resident, with
   48 ms TTFT. It does not need help — it needs thinking turned off.

## Failure modes hit

- Thinking is on by default (`thinking_default: true`) and silently produces
  zero content tokens. `measure.py` reports `ttfc=None`; that is the only signal.
- `dflash_enabled` sets `requires_reload: true` **and** `auto_unloaded: true`.
  Never interleave it per request — use `block.py`. This is the exact bug that
  produced the previous agent's bogus ~2900 ms TTFTs.
- `auto_unloaded: true` unloads but does not reload; the harness must `POST
  /load` and poll.
- `dflash_enabled` XOR `mtp_enabled` (HTTP 400); a leftover `dflash_enabled:
  true` blocks later MTP PUTs.
- `measure.py` intermittently exits non-zero with no `run 1:` line — retry up to
  3×.

## Recommendation

Ship the final config as-is:

```json
{
  "enable_thinking": false,
  "max_context_window": null,
  "dflash_enabled": false,
  "specprefill_enabled": false,
  "turboquant_kv_enabled": false,
  "moe_expert_offload_enabled": false,
  "temperature": 1.0,
  "top_p": 0.95,
  "top_k": 20,
  "force_sampling": true
}
```

Final medians: **TTFT 48.0 ms, decode 146.34 tps, total 2091.7 ms** for 300
tokens. All three quality-guardrail prompts pass. This is the best
time-to-first-token of any model tuned in this repo so far, and it is achieved by
removing things rather than adding them.
