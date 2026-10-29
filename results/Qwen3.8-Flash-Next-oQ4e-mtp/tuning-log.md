# Tuning log — Qwen3.8-Flash-Next-oQ4e-mtp

Chronological. Every command that produced a number in `final.json` / `NOTES.md`.
`OMLX=http://127.0.0.1:8001`, `PATH=$HOME/.omlx/bin:$PATH`. `timeout` is not available
on this box and was never used.

---

## 0. Context read

- `AGENTS.md` — ground rules. Line 13: never delete `~/.omlx/cache` (shared 185 GB cache).
- `.github/skills/omlx-model-tuning/SKILL.md` — paired-comparison rule, reload semantics,
  per-knob decision rules, 11-step procedure, deliverable layout, `final.json` schema.
- `.github/skills/omlx-model-settings/SKILL.md` — field reference (MoE offload ~242-264,
  PLE SSD offload ~318-323, MTP depth 1..8 ~294-302, KV compression ~197-204).
- `results/Qwen3.6-35B-A3B-oQ8e-mtp/final.json` + `NOTES.md` — shape/format examples.

## 1. Live state captured

- `GET /admin/api/models` → full `.settings` for the model, saved as `settings-start.json`.
- Model facts: `config_model_type: qwen4_exp`, `engine_type: vlm`, `model_context_length`
  262144, `estimated_size` 112,812,100,831 B, `actual_size` 75,686,205,496 B,
  `mtp_compatible: true`, `moe_expert_offload_supported: true`,
  `moe_offload_allows_mtp: true`, `dflash_compatible: false`,
  `activation_fp16_supported: false`, `qwen35_oq_a8_supported: false`,
  `ane_prefill_backend: null`, `thinking_default: true`, `thinking_forced: false`,
  `thinking_modes: [auto, on_unlimit, on_limit, off]`,
  `reasoning_levels: [off, low, medium, xhigh]`, `reasoning_effort_default: low`.
- `qwen4_ple_mmap_bytes` 79,211,939,549; `qwen4_ple_resident_bytes` 112,812,100,831.
- Read `config.json` (nested `text_config`), `generation_config.json`, `README.md`.

## 2. Harnesses reviewed

`tuning/ab.py`, `block.py`, `sweep.py`, `runs.py`, `quality.py`, `coldprefill.py`, and
`scripts/measure.py`. Signatures confirmed:

- `ab.py <labelA> <patchA> <labelB> <patchB> [n] [out]` — interleaved; **leaves its last
  patch applied**.
- `block.py <labelA> <patchA> <labelB> <patchB> [n] [blocks]` — alternating blocks;
  env `MAXTOK` (300), `PAD` (0).
- `sweep.py <runs> <out.json> '<label>=<json>' ...` — forward then backward.
- `coldprefill.py` — pad from the **`PAD` env var**, not an argument.
- `quality.py` — env `TEMP` (0.2), `TOP_P`, `TOP_K`, `MAXTOK` (700).
- `runs.py <out> [runs] [max_tokens] [context_pad]`.

## 3. Thinking tri-state probe

Wrote `tuning/tristate.py` (single streamed request per arm, `max_tokens` 400, full text
read). Result → `tuning/tristate-thinking.json`:

| `enable_thinking` | content | reasoning | finish | TTFC |
|---|---|---|---|---|
| `false` | 544 chars | 0 | `stop` | 480.8 ms |
| `null` | 416 chars | 1111 | `stop` | 4888 ms |
| `true` | 416 chars | 1111 | `stop` | 3477 ms |

**`null` is not off. `true` is identical to `null`.** All three outputs correct.

## 4. Null test #1

`block.py nulltest '{}' nulltest '{}' 5 2` → `tuning/block-nulltest-vs-nulltest.json`.
94.19 vs 94.07 tps (**−0.13%**), 121.7 vs 120.5 ms TTFT (−1.0%).
**Noise floor ≈ 1%.**

## 5. `moe-offload-fit` re-probe

`GET /admin/api/models/Qwen3.8-Flash-Next-oQ4e-mtp/moe-offload-fit?mtp_enabled=…&qwen4_ple_ssd_offload=…`
— reproduced the coordinator's table exactly. PLE on → `resident` / `max_percent: null` /
`bytes: 0`. PLE off + MTP on → `fit` at 61% (84,942,916,831 B). The endpoint accepts only
`mtp_enabled`, `qwen4_ple_ssd_offload`, `deepseek_v41_engram_ssd_offload` and **silently
ignores** `moe_expert_offload_resident_fraction`.

## 6. Mandatory MoE expert-offload sweep

Wrote `tuning/blocksweep.py` — forward+backward ordered block sweep that imports
`apply_and_settle` / `one_run` from `block.py` and additionally captures resident memory
from `GET /api/status.model_memory_used` after each load settles.

`blocksweep.py` over 5 arms, n=4 × 2 passes = **n=8 per arm** →
`tuning/moe-offload-sweep.json`:

| Arm | Decode tps | TTFT ms | Resident GB | Ceiling GB |
|---|---|---|---|---|
| PLE only, expert offload OFF | 89.07 | 123.5 | 79.21 | 96.68 |
| fraction 0.10 | 12.66 | 702.3 | 14.97 | 100.49 |
| fraction 0.25 | 20.00 | 648.2 | 25.70 | 99.62 |
| fraction 0.50 | 38.43 | 394.5 | 43.54 | 103.60 |
| fraction 0.75 | 63.77 | 232.9 | 61.38 | 99.12 |

Monotonic in both directions. **Rejected.** Per-sample PLE-only list
`82.3, 79.4, 82.0, 79.2, 96.8, 97.5, 97.6, 95.8` shows a warmup ramp in pass 1, so the
89.07 median is conservative.

## 7. Null test #2

`block.py pleonly '{}' pleonly2 '{}' 10 1` → `tuning/block-pleonly-vs-pleonly2.json`.
96.95 vs 95.94 tps (**−1.04%**), 124.8 vs 123.9 ms. Confirms the ~1% floor.

## 8. MTP depth sweep

`blocksweep.py` over mtp-off / adaptive / fixed2 / fixed4, n=8 per arm →
`tuning/mtp-depth-sweep.json`:

| Arm | Decode tps | TTFT ms |
|---|---|---|
| MTP off | 58.53 | 117.5 |
| adaptive | 93.18 | 120.7 |
| fixed 2 | 91.14 | 117.5 |
| fixed 4 | 89.85 | 119.3 |

MTP worth **+59% decode**. Adaptive best.

## 9. KV quant sweep

First attempt → **HTTP 422 `extra_forbidden`**: the field is `turboquant_skip_last`, not
`turboquant_kv_skip_last`. Retried → `tuning/kvquant-sweep.json`, n=8 per arm:

| Arm | Decode tps | TTFT ms |
|---|---|---|
| off | 96.68 | 123.2 |
| 8-bit + skip | 96.28 | 122.1 |
| 4-bit + skip | 96.49 | 120.4 |

All within 0.4% — **null**. Rejected.

## 10. Context window A/B

`ab.py ctx-native '{"max_context_window":null}' ctx-32768 '{"max_context_window":32768}' 6`
→ `tuning/ab-ctx-native-vs-32768.json`. 96.56 vs 96.12 tps, 123.4 vs 121.5 ms — **null**.
Native kept.

## 11. Sampler A/B

`ab.py samp-card '{"temperature":1.0,...}' samp-coding '{"temperature":0.6,...}' 6` →
`tuning/ab-samp-card-vs-coding.json`. 96.36 vs 96.16 tps — **null**. Coding sampler kept
on the model-card recommendation, not on a speed claim.

## 12. `force_sampling` artifact check

Wrote `tuning/forcesampling.py` — three identical `temperature: 0.0` requests per arm →
`tuning/force-sampling.json`. `false` → **1/3** distinct outputs (deterministic);
`true` → **2/3** distinct. Confirms `force_sampling: true` overrides the request
temperature with the model's 0.6. **Artifact, rejected.**

## 13. MTP adaptive vs fixed 2 head-to-head

`block.py mtp-adaptive '{"mtp_fixed_depth":null}' mtp-fixed2 '{"mtp_fixed_depth":2}' 10 1`
→ `tuning/block-mtp-adaptive-vs-mtp-fixed2.json`. Adaptive 99.36 tps / 122.5 ms vs fixed 2
98.44 / 118.5. **+0.9% decode, −4.0 ms TTFT — inside noise.** Adaptive kept as the
default, not as a win.

## 14. Whole-config head-to-head (run 1)

`block.py baseline-defaults '<defaults>' final-config '<final>' 10 1` →
`tuning/block-baseline-defaults-vs-final-config.json`. Defaults 86.45 tps / 113.2 ms /
3571 ms vs final 91.78 / 121.5 / 3380. **+6.2% decode, −191 ms total, +8.3 ms TTFT.**

## 15. Thinking null vs false head-to-head

`block.py thinking-null '{"enable_thinking":null}' thinking-false '{"enable_thinking":false}' 10 1`
→ `tuning/block-thinking-null-vs-thinking-false.json`. null 78.84 tps / 117.3 ms /
3912 ms vs false 85.18 / 129.9 / 3637. **+8.0% decode, −275 ms total, +12.6 ms TTFT.**
This is the real lever.

## 16. Quality guardrails

`TEMP=0.6 MAXTOK=700 python3 tuning/quality.py` → `tuning/quality-raw.json`. 790 / 153 /
104 content chars, **0 reasoning chars**, `finish=stop` in all three. All three correct.
Full text in `quality.md`.

## 17. Single-block baseline and final runs

- `runs.py baseline-runs.json 6 300 0` (defaults) → 79.72 tps / 119.9 ms / 3870 ms /
  79.21 GB resident, ceiling 98.6 GB.
- `runs.py final-runs.json 10 300 0` (final) → 88.92 tps / 125.8 ms / 3493 ms /
  79.21 GB resident, ceiling 98.52 GB.

Both copied to the deliverable root as `baseline.json` / `final-runs.json`. **These are
single-block numbers and are not comparable to each other.**

## 18. Final config applied and read back

Single PUT with the final patch → `requires_reload: true, auto_unloaded: true` →
`POST /load` → polled `loaded: true`. Read back `GET /admin/api/models` →
`settings-live.json`; extracted `.settings` → `final-settings.json` (84 keys). Key-by-key
diff against the intended patch: **0 differences**. `model_memory_used` 79,211,939,549 B.

## 19. Cold prefill, PLE on vs off

`PAD=8000 python3 tuning/coldprefill.py` (random nonce per request, `cached_tokens` 0,
~21.7k prompt tokens), alternating blocks, n=6 per arm →
`tuning/coldprefill-ple-on-vs-ple-off.json`:

| Arm | TTFT | Decode | Prefill |
|---|---|---|---|
| PLE on | 33,803.9 ms | 72.12 tps | 646.5 tps |
| PLE off + expert offload 0.61 | 54,310.8 ms | 19.08 tps | 434.5 tps |

**−20.5 s TTFT, 3.8× decode.** The single biggest lever on the model.

## 20. Final config restored after the cold-prefill run

The cold-prefill test left PLE offload off. Re-applied the final patch, `POST /load`,
polled `loaded: true`, re-read and re-diffed live settings: **0 differences**.

## 21. Temperature isolation A/B

`ab.py temp1.0 '{"temperature":1.0}' temp0.6 '{"temperature":0.6}' 8` →
`tuning/ab-temp1.0-vs-temp0.6.json`. 96.71 vs 96.56 tps, 128.1 vs 130.6 ms — **null**.
Run specifically to test whether temperature explains the whole-config decode delta.
**It does not.**

## 22. Whole-config head-to-head (run 2)

Repeated step 14 → defaults 87.55 tps / 115.7 ms / 3532 ms vs final 89.72 / 124.8 / 3461.
**+2.5% decode, −71 ms total, +9.1 ms TTFT.** The two runs disagree by 2.4×, so the
headline is reported as the range **+2.5% to +6.2%** and flagged low confidence.

## 23. Deliverables written

`final.json`, `NOTES.md`, `tuning-log.md`, `quality.md`, `baseline.json`,
`final-runs.json`, `final-settings.json`, `settings-start.json`, `settings-live.json`,
`quality-raw.json`, and every `tuning/*.json`.

## 24. Final state

Model loaded, `is_loading: false`, final config applied and read back with 0 differences.
`model_memory_used` 79,211,939,549 B (73.77 GiB) against `model_memory_max`
101,902,725,696 B (94.9 GiB) in this state. **Left applied; defaults not restored.**
No commits made.
