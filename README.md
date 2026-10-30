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
| Model dirs | `$OMLX_MODELS_DIR` + `$OMLX_EXTERNAL_MODELS_DIR` |
| SSD cache | `$OMLX_CACHE_DIR` (185 GB budget) |
| Server | `$OMLX_BASE_URL` |

The defaults for these variables match the development machine and are listed
in [Development](#development). Nothing in this repo hardcodes them.

### Storage

Two model directories are registered, so the model set is not limited to the
internal SSD:

| Volume | Size | Role |
|---|---|---|
| `$OMLX_DATA_VOLUME` (internal) | ~1.8 TB, ~430 GB free | Active download + tuning target |
| `$OMLX_EXTERNAL_MODELS_DIR` (external) | 1 TB, ~931 GB free | Overflow / cold storage for tested models |

`$OMLX_EXTERNAL_MODELS_DIR` is registered as a second entry in
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

Splash 1.4.0 is installed at `$OMLX_SPLASH_BIN` and configured in
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
  omlx_config.py              configurable base paths (see Development)
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
curl -s "$OMLX_BASE_URL/api/status" | jq .

# download a model
curl -s -X POST "$OMLX_BASE_URL/admin/api/hf/download" \
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

## Development

Every machine-specific location is a **base path with an environment-variable
override**. The defaults below match the machine this repo was developed on;
override any of them to run the harness elsewhere. No script hardcodes a path,
and every repo-relative path (corpora, results, manifests) is resolved from the
repo root, so run the scripts from there.

`scripts/omlx_config.py` is the single source of truth. Print the resolved
configuration at any time:

```sh
python3 scripts/omlx_config.py          # human-readable, shows env vs default
python3 scripts/omlx_config.py --json   # machine-readable
```

| Variable | Default | Purpose |
|---|---|---|
| `OMLX_BASE_URL` | `http://127.0.0.1:8001` | oMLX HTTP surface used by every harness |
| `OMLX_APP` | `/Applications/oMLX.app` | oMLX app bundle |
| `OMLX_SOURCE_DIR` | `/Applications/oMLX.app/Contents/Resources/omlx` | Shipped Python source, read to verify API and model behaviour |
| `OMLX_PYTHON` | `/Applications/oMLX.app/Contents/MacOS/omlx-cluster-python` | Interpreter with Pillow, numpy, and OpenCV |
| `OMLX_HOME` | `~/.omlx` | oMLX state directory (`settings.json`, `model_settings.json`) |
| `OMLX_MODELS_DIR` | `~/.omlx/models/mlx-community` | Primary model directory |
| `OMLX_EXTERNAL_MODELS_DIR` | `/Volumes/NVMe/omlx-models` | Second model directory (overflow / cold storage) |
| `OMLX_CACHE_DIR` | `~/.omlx/cache` | Shared SSD cache |
| `OMLX_DATA_VOLUME` | `/System/Volumes/Data` | Volume checked for free space |
| `OMLX_FONT_DIR` | `/System/Library/Fonts/Supplemental` | Fonts used to render the OCR and media corpora |
| `OMLX_FFMPEG` | `/opt/homebrew/bin/ffmpeg` | Optional; video is written with OpenCV |
| `OMLX_SPLASH_BIN` | `/opt/homebrew/bin/splash` | External Splash engine |

### Interpreter

The corpus generators need Pillow, numpy, and OpenCV. The `python3` on `PATH`
has none of them; the interpreter bundled with the app does. Use it for
anything that draws a corpus:

```sh
"$OMLX_PYTHON" scripts/decision_media_corpus.py --out results/decision/media
"$OMLX_PYTHON" scripts/ocr_corpus.py --out results/non-llm/<model>/corpus
```

The harnesses themselves are stdlib-only and run under any `python3`.

### Corpora are generated, not edited

Both corpora are seeded and must regenerate byte-identically. Never hand-edit a
generated file — change the generator and regenerate:

```sh
"$OMLX_PYTHON" scripts/decision_media_corpus.py --out /tmp/media-check
diff -r --exclude=README.md --exclude=runs results/decision/media /tmp/media-check
```

An empty diff is the contract. A non-empty one means the seed or a drawing
primitive changed, which invalidates every result scored against the old corpus.

### Historical results are not rewritten

`results/<model>/` and `results/non-llm/` record what was actually run on this
machine, including the absolute paths that were in effect at the time. They are
a log, not configuration, so they keep the literal paths. Only the tooling and
the current documentation use the variables above.

## Notes

- The SSD cache directory is shared and already populated; do not clear it.
- `model_memory_max` is the guard ceiling, not physical RAM. Models whose
  resident size exceeds it will be refused or will thrash.
- oMLX's own recommendation API (`/admin/api/hf/recommendations`) is the
  ground truth for what fits this machine.
