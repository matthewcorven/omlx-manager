# oMLX Model Tuning — M4 Max 128 GB

A reproducible workflow for selecting, downloading, benchmarking, and tuning local
models on **oMLX 0.7.3rc1** for small coding tasks on an Apple **M4 Max / 128 GB**
unified memory Mac.

The model set is derived from the
[oMLX v0.7.3rc1 release notes](https://github.com/jundot/omlx/releases/tag/v0.7.3rc1)
and the PRs/commits they reference.

## Hardware

| | |
|---|---|
| Chip | Apple M4 Max, 40 GPU cores |
| Memory | 128 GB unified (~546 GB/s) |
| oMLX model memory ceiling | ~89.6 GB (balanced guard tier) |
| Model dirs | `~/.omlx/models/mlx-community` + `/Volumes/NVMe/omlx-models` |
| SSD cache | `~/.omlx/cache` (185 GB budget) |
| Server | `http://127.0.0.1:8001` |

### Storage

Two model directories are registered, so the model set is not limited to the
internal SSD:

| Volume | Size | Role |
|---|---|---|
| `/System/Volumes/Data` (internal) | ~1.8 TB, ~430 GB free | Active download + tuning target |
| `/Volumes/NVMe` (external, `/dev/disk4`) | 1 TB, ~931 GB free | Overflow / cold storage for tested models |

`/Volumes/NVMe/omlx-models` is registered as a second entry in
`model.model_dirs`, so oMLX discovers and loads models from it directly — no
copying back is needed to run a model that lives there.

> **Warning:** `POST /admin/api/global-settings` with `model_dirs` **unloads all
> loaded models and re-discovers**. Never call it while a benchmark is running.
> `model_dirs` is a **top-level** field, not nested under `model`.

### Shuttle strategy

The internal SSD is the bottleneck for breadth — each 20–40 GB model takes a
large share of ~430 GB free. Finished models are shuttled to the external volume
so several candidates can stay on disk at once:

```sh
scripts/shuttle_model.sh <model_id>            # internal -> external
scripts/shuttle_model.sh --back <model_id>     # external -> internal
scripts/shuttle_model.sh --dry-run <model_id>  # show the move only
```

The script refuses to move a model that is loaded or has a benchmark running,
and verifies oMLX still sees the model at its new path afterwards. Shuttle only
after `final.json` and `NOTES.md` are written and committed.

### Disk is not memory

The external volume relieves **disk** pressure only. A model over the ~89.6 GB
resident ceiling stays over it after a move — the constraint is unified memory at
load time. For those models the only lever is **MoE expert offload**, which
trades decode speed for residency. Do not propose "move it to the NVMe" as a fix
for a resident-memory-bound model.

### External engine: Splash

oMLX can serve a model through an external [Splash](https://github.com/incoai/splash)
process instead of loading weights in-process. Splash runs its own Metal engine
with DFlash2 speculative decoding and covers Qwen3.8-27B, Qwen3.6-35B-A3B,
Qwen3.5-122B-A10B (Ornith-1.5-122B), Qwen3.8-Flash-Next and Flint.

Splash 1.4.0 is installed at `/opt/homebrew/bin/splash` and configured in
`integrations.splash_path`. Check status with:

```sh
curl -s $OMLX/admin/api/global-settings | jq .external_engines.splash
```

Relevant settings: `splash_kv_format` (`int8`), `splash_max_memory_gb`,
`splash_ssd_cache_gb`, `splash_ane_prefill`. Because Splash is a separate
process, its peak memory is measured as the Splash process footprint, and its
benchmarks run through its own OpenAI-compatible API rather than oMLX's
token-id path — so Splash runs are kept out of in-process comparison tables.

## What this repo contains

```
README.md                     this file
AGENTS.md                     operating instructions for agent sessions
docs/
  model-candidates.md         every model named in the release notes + HF sizes
  omlx-api-reference.md       complete oMLX REST API + settings field reference
  tuning-methodology.md       how models are benchmarked and tuned
.github/skills/
  omlx-model-download/        search, download, verify, delete models
  omlx-model-settings/        per-model settings, profiles, optimal lookup
  omlx-benchmark/             throughput/context benches + TTFT measurement
  omlx-troubleshooting/       failure modes and fixes
scripts/
  measure.py                  TTFT + decode tok/s harness for a coding prompt
  disk_guard.sh               free-space check before a download
  shuttle_model.sh            move a finished model internal <-> external NVMe
results/
  <model>/                    per-model benchmark + tuning results
```

## Workflow

1. **Select** — `docs/model-candidates.md` ranks candidates by fit, speed, and
   coding quality. The coordinator picks a set that fits in free disk space.
2. **Download** — via the oMLX admin API (`/admin/api/hf/download`), polling
   `/admin/api/hf/tasks`. See `.github/skills/omlx-model-download`.
3. **Verify** — load the model, send one short chat completion on default
   settings, confirm it responds and reports sane `usage`.
4. **Baseline** — measure TTFT and decode tok/s with `scripts/measure.py`.
5. **Tune** — sweep the settings that matter for coding (context window,
   thinking budget, MTP/DFlash, MoE offload, KV quantization, sampling) and
   record each variant in `results/<model>/`.
6. **Settle** — leave the model on the best performance / time-to-first-token
   balance, not the raw fastest decode.

## Quick start

```sh
export PATH="$HOME/.omlx/bin:$PATH"
omlx start                       # managed server on :8001
curl -s http://127.0.0.1:8001/api/status | jq .

# download a model
curl -s -X POST http://127.0.0.1:8001/admin/api/hf/download \
  -H 'Content-Type: application/json' \
  -d '{"repo_id":"Jundot/Qwen3.8-27B-oQ4e-mtp"}'

# measure
python3 scripts/measure.py --model Qwen3.8-27B-oQ4e-mtp --runs 3
```

## Results

Per-model findings live in `results/`. Each directory holds:

- `baseline.json` — default-settings measurement
- `sweep.jsonl` — one line per settings variant tried
- `final.json` — the settings left in place, with rationale
- `NOTES.md` — human-readable summary

## Notes

- The SSD cache directory is shared and already populated; do not clear it.
- `model_memory_max` is the guard ceiling, not physical RAM. Models whose
  resident size exceeds it will be refused or will thrash.
- oMLX's own recommendation API (`/admin/api/hf/recommendations`) is the
  ground truth for what fits this machine.
