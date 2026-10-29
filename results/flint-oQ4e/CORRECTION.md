# Correction: flint-oQ4e corruption diagnosis

The first tuning pass on this model concluded that `activation_fp16_enabled: true`
gave a ~2.9x decode speedup, and that a separate "persistent word salad" fault
required purging the oMLX cache. **Both parts of that conclusion were wrong.**

## What was actually happening

Two independent corruption sources were conflated.

### 1. `activation_fp16_enabled: true` is the corrupt path, not the fast path

Measured on a clean cache, same prompts, only this knob changed:

| activation_fp16_enabled | output | TTFT | reason chunks |
|---|---|---|---|
| `false` | correct Python + SQL | 1756 / 1765 ms | 8 |
| `true` | `"cef pourquoi dissolvingertime(rowot's剛umenicalacar스크 breakouts..."` | 66 / 60 ms | 0 |

The apparent speedup is an artifact of emitting noise: with the activations
corrupted the model never enters its reasoning phase, so it starts streaming
garbage almost immediately. The server reports
`activation_fp16_supported: false` for this model and that signal is correct.
**Trust it over any measured speedup.**

### 2. The SSD prefix cache serves poisoned prefixes when saturated

The cache was at 185 GB against `cache.ssd_cache_max_size = 185GB`
(84 GB of it `_gdn_sidecars`). With that cache in place, coherent output was
impossible *even with `activation_fp16_enabled: false`* — the reverted setting
still produced word salad on the first probe after reload.

Moving the cache aside (`~/.omlx/cache` -> `~/.omlx/cache-quarantine-<epoch>`,
contents preserved, nothing deleted) and reloading produced correct output
immediately on the same prompts and settings. This also matches the server's
own repeated log line, `Invalidated 11-13 SSD index entries with stale layer
cache signature`.

The quarantine directory can be deleted once no further forensics are wanted.

## Harness lesson

`measure.py`'s non-streaming mode with `max_tokens` of 120-150 makes this model
look empty or truncated: flint spends the entire budget on `reasoning_content`
(625-707 chunks observed) and returns `content: ""` with
`finish_reason: length`. Quality checks on flint **must** stream and use
`max_tokens >= 350`.

## Status

`activation_fp16_enabled: false`, cache cold, verified coherent:
`def dedupe(lst): ...` returned correctly on a 350-token budget.
The earlier `final-settings.json` / `settings-live.json` in this directory were
produced under the inverted conclusion and are **not** a valid recommendation;
they are retained only as evidence of the error.
