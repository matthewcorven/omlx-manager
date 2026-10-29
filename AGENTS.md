# AGENTS.md

Operating instructions for agent sessions working in this repo.

## Mission

Select, download, verify, benchmark, and tune local LLMs on oMLX 0.7.3rc1 for
**small coding tasks** on an **M4 Max / 128 GB** Mac. Leave each model on a
settings profile that balances decode speed against time-to-first-token.

## Ground rules

1. **Never delete `~/.omlx/cache`.** It is a shared 185 GB SSD cache. Clearing it
   destroys other work.
2. **Check free disk before every download.** Run `scripts/disk_guard.sh <GB>`.
   Abort if free space would drop below 60 GB after the download.
3. **One model per agent.** A model-tuning agent owns exactly one model. It must
   not download, load, or change settings for any other model.
4. **Do not edit `~/.omlx/settings.json`** (global server config). Per-model
   changes go through `/admin/api/models/{id}/settings` only. In particular,
   **never** call `POST /admin/api/global-settings` with `model_dirs` during a
   benchmark — it unloads every loaded model and re-discovers.
5. **Do not run two benchmarks at once.** oMLX returns 409; concurrent runs
   corrupt measurements.
6. **Record everything.** Every measurement goes into `results/<model>/`. A
   tuning run without recorded numbers did not happen.

## Environment

```sh
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=http://127.0.0.1:8001
```

- Server: `omlx start` / `omlx stop` / `omlx restart`. Health: `GET /api/status`.
- Model dir: `~/.omlx/models/mlx-community`
- Per-model settings: `~/.omlx/model_settings.json` (read-only for agents; write
  via the API).
- OpenAPI: `GET /openapi.json`

## Skills

Load the relevant skill before acting:

| Task | Skill |
|---|---|
| Find, download, verify, or delete a model | `.github/skills/omlx-model-download` |
| Read or change per-model settings | `.github/skills/omlx-model-settings` |
| Run benchmarks or measure TTFT | `.github/skills/omlx-benchmark` |
| Something is broken | `.github/skills/omlx-troubleshooting` |

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

## Coordinator duties

- Track free disk; approve or reject downloads.
- Ensure only one benchmark runs at a time.
- Keep `docs/model-candidates.md` and `results/` in sync.
- Do not let two agents touch the same model.
- Manage the two model directories: internal SSD for active work, and
  `/Volumes/NVMe/omlx-models` (1 TB external) for models already tested. Both
  are registered in `model.model_dirs`, so a model on the external volume can be
  loaded directly — moving a model there does not make it unusable.
- Never change `model_dirs` while any benchmark is running.
