# Invalid measurements — do not cite as evidence

These files were produced by harnesses that were later found to be unsound.
They are kept only so the record is honest.

## `ab-mtpdefault-vs-mtpadapt2.json`, `ab-mtpdefault2-vs-mtpadapt4.json`, `ab-mtpon-vs-mtpoff.json`

**Cause: reload-per-request bug in `ab.py`.** `ab.py` re-PUT the settings patch
before *every* request. `mtp_enabled`, `mtp_adaptive_max_depth` and
`turboquant_kv_enabled` all return `requires_reload: true` / `auto_unloaded: true`
on a real change, so every single request cold-reloaded the model. The tell was
TTFT exploding to ~2900 ms and prefill collapsing to ~56 tps.

Consequence: the "depth 2 is +2%", "depth 4 is worse" and the first MTP on/off
verdicts are **not** measurements of those configs. They are measurements of
cold-load latency.

`ab.py` remains valid for knobs that do **not** reload — `max_context_window`
is the only one used here, so `ab-native-vs-ctx32768.json` stands.

## `contaminated/*`

**Cause: coordinator-induced unload.** The coordinator added
`/Volumes/NVMe/omlx-models` as a second model dir via
`POST /admin/api/global-settings`, which unloads all models and re-discovers.
Measurements spanning that window are unusable.

## `A1-ctx-native.json`, `A2-ctx-native.json`, `B1-ctx32768.json`

Sequential whole-config blocks. Superseded: decode drifted 68.77 -> 61.19 tps
with **no config change**, so sequential blocks cannot separate config effect
from drift. Replaced by interleaved `ab.py` sampling.
