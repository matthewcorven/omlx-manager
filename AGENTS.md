# AGENTS.md

Operating instructions for agent sessions working in this repo.

## Mission

Select, download, verify, benchmark, and tune local LLMs on oMLX 0.7.3rc1 for
**small coding tasks** on an **M4 Max / 128 GB** Mac. Leave each model on a
settings profile that balances decode speed against time-to-first-token.

## Ground rules

1. **Never delete `$OMLX_CACHE_DIR`.** It is a shared 185 GB SSD cache. Clearing it
   destroys other work.
2. **Check free disk before every download.** Run `scripts/disk_guard.sh <GB>`.
   Abort if free space would drop below 60 GB after the download.
3. **One model per agent.** A model-tuning agent owns exactly one model. It must
   not download, load, or change settings for any other model.
4. **Do not edit `$OMLX_HOME/settings.json`** (global server config). Per-model
   changes go through `/admin/api/models/{id}/settings` only. In particular,
   **never** call `POST /admin/api/global-settings` with `model_dirs` during a
   benchmark — it unloads every loaded model and re-discovers.
5. **Do not run two benchmarks at once.** oMLX returns 409; concurrent runs
   corrupt measurements.
6. **Record everything via `scripts/record_model_result.py` (STRICT INVARIANT).**
   All benchmark results across all modalities (`generative-text`, `ocr`, `decision`,
   `image-generation`, `voice`) must be recorded **ONLY EVER** by running
   `scripts/record_model_result.py`. Ad-hoc, manually edited, or unvalidated
   markdown tables are strictly prohibited and deprecated. Every dataset commit
   must pass `python3 scripts/record_model_result.py --validate-all`.

## Environment

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=${OMLX_BASE_URL:-http://127.0.0.1:8001}
```

- Server: `omlx start` / `omlx stop` / `omlx restart`. Health: `GET /api/status`.
- Model dirs: `$OMLX_MODELS_DIR` (internal SSD) and
  `$OMLX_EXTERNAL_MODELS_DIR` (1 TB external). Both are registered in
  `model.model_dirs`; see **Storage** below.
- Per-model settings: `$OMLX_HOME/model_settings.json` (read-only for agents; write
  via the API).
- OpenAPI: `GET /openapi.json`
- External engine: Splash 1.4.0 at `$OMLX_SPLASH_BIN`, configured in
  `integrations.splash_path`. Status:
  `curl -s $OMLX/admin/api/global-settings | jq .external_engines.splash`

## Storage

Two model directories are registered in `model.model_dirs`, so the model set is
not limited to the internal SSD:

| Volume | Size | Role |
|---|---|---|
| `$OMLX_DATA_VOLUME` (internal) | ~1.8 TB, ~430 GB free | Active download + tuning target |
| `$OMLX_EXTERNAL_MODELS_DIR` (external) | 1 TB, ~931 GB free | Overflow / cold storage for tested models |

Because `$OMLX_EXTERNAL_MODELS_DIR` is a registered model dir, oMLX discovers and
loads models from it directly — **moving a model there does not make it
unusable**, and no copy back to internal is needed to run it. The external volume
is slower than internal SSD, so keep the model currently being tuned internal and
shuttle finished models out.

### Shuttle strategy

The internal SSD is the bottleneck for breadth: each 20–40 GB model eats a large
share of ~430 GB free. Shuttle finished models to the external volume to keep
several candidates resident on disk at once.

```sh
# after a model's final.json + NOTES.md are written and committed
scripts/shuttle_model.sh <model_id>          # internal -> external
scripts/shuttle_model.sh --back <model_id>   # external -> internal
```

Rules for shuttling:

- **Only shuttle a model whose tuning is finished** and whose results are
  committed. A model mid-sweep must stay where it is.
- **Never shuttle while a benchmark is running.** Moving files under a loaded
  model corrupts the run; unload first (`POST /admin/api/models/<id>/unload`).
- **Never change `model_dirs` while a benchmark is running.** That call unloads
  every loaded model and re-discovers.
- Shuttle with the server's own move endpoint when available; otherwise stop the
  server, move the directory, and restart so oMLX re-indexes cleanly.
- After a shuttle, confirm the model still appears in `GET /admin/api/models` and
  loads from its new path before recording it as available.

### Resident-memory ceiling is separate from disk

External disk buys **disk**, not **RAM**. A model that exceeds the ~89.6 GB
resident ceiling still will not fit after being moved to the external volume —
the constraint is unified memory at load time, not free space. For those models
the only lever is **MoE expert offload** (see tuning priority 4), which trades
decode speed for residency. Do not propose "move it to the NVMe" as a fix for a
resident-memory-bound model.

## Skills

Load the relevant skill before acting:

| Task | Skill |
|---|---|
| Find, download, verify, or delete a model | `.github/skills/omlx-model-download` |
| Read or change per-model settings | `.github/skills/omlx-model-settings` |
| Run benchmarks or measure TTFT | `.github/skills/omlx-benchmark` |
| Re-profile everything after an oMLX version upgrade | `.github/skills/omlx-release-reprofile` |
| Evaluate or tune an OCR / document-parsing model | `.github/skills/omlx-ocr-eval` |
| Evaluate a decision model (Clef, OpenJev, d3, d1) | `.github/skills/omlx-decision-eval` |
| Something is broken | `.github/skills/omlx-troubleshooting` |

## External engine: Splash

oMLX can serve a model through an external Splash process instead of loading
weights in-process. Splash runs its own Metal engine with DFlash2 speculative
decoding and covers Qwen3.8-27B, Qwen3.6-35B-A3B, Qwen3.5-122B-A10B
(Ornith-1.5-122B), Qwen3.8-Flash-Next and Flint.

- Splash 1.4.0 is installed at `$OMLX_SPLASH_BIN` and already set in
  `integrations.splash_path`; no setup is needed to use it.
- Settings: `splash_kv_format` (`int8`), `splash_max_memory_gb`,
  `splash_ssd_cache_gb`, `splash_ane_prefill`.
- Splash is a **separate process**, so its peak memory is the Splash process
  footprint, not oMLX's. Do not compare it against in-process resident sizes.
- Splash benchmarks run through its own OpenAI-compatible API, not oMLX's
  token-id path. oMLX deliberately keeps Splash runs out of in-process
  comparison tables — record them separately and label the engine.
- Use Splash when a model is one of the five it supports and you want DFlash2
  speculative decoding, or when you want the model out of oMLX's own memory
  accounting. Otherwise stay in-process so numbers stay comparable.

## Standard model workflow

```sh
# 1. disk check
scripts/disk_guard.sh 40

# 2. download
curl -s -X POST $OMLX/admin/api/hf/download -H 'Content-Type: application/json' \
  -d '{"repo_id":"<repo_id>"}'
# poll
watch -n5 "curl -s $OMLX/admin/api/hf/tasks | jq ."

# 3. verify it loads and answers on defaults
curl -s -X POST $OMLX/admin/api/models/<model_id>/load
python3 scripts/measure.py --model <model_id> --runs 1 --smoke

# 4. baseline
python3 scripts/measure.py --model <model_id> --runs 3 --out results/<model>/baseline.json

# 5. sweep settings (see tuning-methodology.md)
# 6. write results/<model>/final.json + NOTES.md
```

**Decision models do not follow this workflow.** They have no decode loop and no
sampling, so there is nothing to sweep. They are scored against a labelled corpus
and compared to a chat-model baseline instead — see
[`docs/decision-model-methodology.md`](docs/decision-model-methodology.md) and
`.github/skills/omlx-decision-eval`.

## Measurement contract

`scripts/measure.py` reports, per run:

- `ttft_ms` — time from request send to first content token
- `decode_tps` — completion tokens / (last token time − first token time)
- `prefill_tps` — prompt tokens / ttft
- `total_ms`, `prompt_tokens`, `completion_tokens`

Use the same prompt set and `--runs 3` (median reported) for every comparison.
Never compare numbers taken with different prompts or different `max_tokens`.

## Tuning priorities for small coding tasks

In rough order of impact:

1. **Context window** — set to what the task needs (32K–64K is usually enough
   for small coding tasks). Larger context costs KV memory and slows prefill.
2. **Thinking budget** — cap or disable for latency-sensitive coding; enable
   with a budget for harder tasks.
3. **MTP / DFlash / specprefill** — enable when the model ships a draft; large
   decode gains, small TTFT cost.
4. **MoE expert offload** — only when the model does not fit resident; costs
   decode speed.
5. **KV quantization (TurboQuant)** — reduces memory, can hurt quality; test.
6. **Sampling** — use the model card's recommendation; do not invent values.

## Reporting

Each model agent returns:

- repo_id, quant, download size, resident size
- baseline TTFT / decode tok/s
- the sweep table (variant → TTFT, decode, notes)
- the final settings JSON and a one-paragraph rationale
- any failure modes hit
- invocation of `scripts/record_model_result.py` to record the entry

## Centralized Results & Interactive Dashboard

### Canonical Results Invariant
All multi-modal benchmark numbers are centrally maintained under `results/`:
- `results/generative-text.csv` and `results/generative-text.md`
- `results/ocr.csv` and `results/ocr.md`
- `results/decision.csv` and `results/decision.md`
- `results/image-generation.csv` and `results/image-generation.md`
- `results/voice.csv` and `results/voice.md`

Every `.csv` and `.md` pair is kept in 100% atomic synchronization.
**Direct manual edits to these tables are strictly prohibited.**

To record or update benchmark results:
```sh
# Record new result:
python3 scripts/record_model_result.py --type <generative-text|ocr|decision|image-generation|voice> --add --data '<json_data>'

# Update an existing model entry:
python3 scripts/record_model_result.py --type <generative-text|ocr|decision|image-generation|voice> --update --data '<json_data>'

# Validate full repository consistency:
python3 scripts/record_model_result.py --validate-all
```

### Interactive Dashboard
To explore and visualize benchmarks across all modalities, open the static single-page leaderboard dashboard:
```sh
# Serve locally via Python web server:
python3 -m http.server 8000 --directory .
# Open http://localhost:8000/dashboard/ in your browser.
```
The dashboard also runs self-contained directly via `file:///.../dashboard/index.html` using embedded fallback data.

## Coordinator duties

- Enforce the recording invariant: all benchmarks must be committed via `scripts/record_model_result.py` with passing `--validate-all`. Reject ad-hoc markdown tables.
- Track free disk; approve or reject downloads.
- Ensure only one benchmark runs at a time.
- Keep `docs/model-candidates.md` and `results/` in sync.
- Do not let two agents touch the same model.
- Manage the two model directories: internal SSD for active work, and
  `$OMLX_EXTERNAL_MODELS_DIR` (1 TB external) for models already tested. Both
  are registered in `model.model_dirs`, so a model on the external volume can be
  loaded directly — moving a model there does not make it unusable.
- Never change `model_dirs` while any benchmark is running.
- **Shuttle finished models to the external volume.** When a model's
  `final.json` and `NOTES.md` are written and committed, move it to
  `$OMLX_EXTERNAL_MODELS_DIR` to free internal space for the next candidate.
  Unload it first; never move a model mid-sweep or during a benchmark. See
  **Storage → Shuttle strategy**.
- **Do not confuse disk with memory.** The external volume relieves disk
  pressure only. A model over the ~89.6 GB resident ceiling stays over it after
  a move; the fix is MoE expert offload, not relocation. Check resident size
  against the ceiling before approving a download, not just free disk.
- **Serialize tuning agents.** Only one benchmark runs at a time (409), so spawn
  a model's tuning agent only when the previous one has finished its sweep, or
  when the two are explicitly scheduled to alternate.
- **Collect and compare.** Each tuning agent returns `final.json` + `NOTES.md`;
  keep a cross-model comparison table in `results/COMPARISON.md`.
