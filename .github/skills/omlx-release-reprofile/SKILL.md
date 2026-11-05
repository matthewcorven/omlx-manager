---
name: omlx-release-reprofile
description: Re-profile an existing oMLX model set against a newly installed oMLX release. Use when a new oMLX version (or release candidate) is installed and you need to (a) find and download models the new version supports that you do not have, (b) re-benchmark models already profiled under the older version, and (c) keep a catalogue of release-named models that still do not fit this Mac so they are re-probed on every future release. Covers release-note triage, the installed-vs-recorded version check, Hugging Face re-probing of previously unobtainable models, paired re-measurement, and the version-stamping gap in the current results schema.
---

# Re-profiling an oMLX model set for a new release

This skill is the **release-delta workflow**. It is not a first-pass tuning
skill — that is `.github/skills/omlx-model-tuning`. Here the models are already
chosen and tuned; a new server version landed, and the job is to answer three
questions:

1. **What does the new release support that this Mac could not run before?**
   Download and profile it.
2. **What did the new release change about models already tuned?** Re-measure
   them on their existing final settings.
3. **Which release-named models still do not fit?** Catalogue them, with the
   smallest known build and the reason, so the next release re-probes them.

Question 3 is a standing obligation, not a nicety. A model that was 291 GB on
disk last release may ship a smaller quant next release. If it is not written
down, nobody re-checks it, and the campaign silently stops growing.

## Setup

```sh
cd <repo>
export PATH="$HOME/.omlx/bin:$PATH"
OMLX=${OMLX_BASE_URL:-http://127.0.0.1:8001}
S=.github/skills/omlx-release-reprofile/scripts

curl -s $OMLX/api/status | jq '{status, version, models_discovered}'
omlx --version
```

The installed CLI version and the running server version must agree. If they do
not, the app is serving an older build than the CLI reports — restart before
trusting any measurement.

## Step 0 — read the release, and know what it does *not* say

Fetch the release body:

```
https://github.com/jundot/omlx/releases/tag/<tag>
```

Triage every claim into one of four buckets. The distinction is what keeps this
workflow honest:

| Bucket | Example from 0.7.4.dev1 | What you do |
|---|---|---|
| **New model support** | Ming-3.0-tts / Ming-3.0 Tiny load as TTS models | Search HF, download the smallest fitting build, profile |
| **Speedup for a model you have** | Qwen3.8 Flash-Next decode +3-5% after long prompts; DeepSeek prefill +43% | Re-measure, expect a delta, do **not** re-tune |
| **Speedup for hardware you do not have** | Prefill Accelerator (M3 Ultra + M5 Max pair) | Record as not-applicable; do not chase it |
| **Correctness / API only** | trailing assistant message continues as prefill | Note it; no measurement |

**Release benchmark numbers are not your numbers.** They are taken on M3/M5
Ultra and M5 Max. A "+62% decode" headline measured on an M3 Ultra can be a
rounding error on an M4 Max, and vice versa. Treat the release table as a
*hypothesis about direction*, never as a target to reproduce.

The release body is also frequently truncated or image-heavy. Do not build a
workflow that depends on parsing it perfectly — pass the model families in
explicitly (Step 2).

## Step 1 — installed version vs recorded version

```sh
python3 $S/release_reprofile.py status
```

Output tells you three things: the installed version, the number of rows per
modality, and which models were last recorded against a *different* version.

**Known gap, and it is the important one:** the results schema has **no version
column**. `version_stamps()` therefore reconstructs the version from prose in
`Notes` and from `results/<model>/final.json`. On a repo that never recorded a
version, it returns nothing and `status` says so explicitly. Treat that as
"every row is stale", not as "everything is current".

When you finish a run, **record the version**. Until the schema grows a column,
the place for it is the `Notes` field of the recorded row:

```sh
python3 scripts/record_model_result.py --type generative-text --update \
  --data '<row json with Notes ending "Re-profiled on oMLX 0.7.4.dev1.">'
```

That is enough for the next release's `status` to find it.

## Step 2 — re-probe what did not fit last time

This is the step that makes the workflow repeatable. Every release, re-ask
Hugging Face about every model you previously gave up on.

```sh
python3 $S/release_reprofile.py discover \
  --tag v0.7.4.dev1 \
  --family DeepSeek-V4.1-Flash \
  --family GLM-5.3-Flash \
  --family MiniMax-M3.1-Flash \
  --family Ling-3.1-flash
```

`--family` is repeatable; families accumulate in `.reprofile/catalogue.json`, so
a later release only needs `discover` with no arguments and it re-probes
everything already catalogued.

How a verdict is reached (`_candidate_ok` in the script):

- **publisher must be trusted** — `Jundot/` or `mlx-community/`. A 95 GB build
  from an unknown uploader is a different product, not a cheaper variant, and
  ranking benchmarks across them is meaningless.
- **fragments are rejected** — `overlay`, `adapter`, `lora`, `gguf`,
  `mlx-serve`, `abliterat`, `uncensored`, `reap`. An overlay repo is a *delta*
  on another repo; measured alone it looks impossibly small. This is the failure
  mode that made a first version of this script report DeepSeek V4.1 as
  "fits at 1.0 GB".
- **implausibly small is rejected** — below 1.2 GB, the smallest legitimate
  entry in this campaign (a 1.2B reranker).
- **verdict** is then `fits` / `too-large` / `unsupported` / `absent`, against a
  **96 GB** resident ceiling (the campaign's ~89.6 GB practical limit plus
  headroom; 128 GB total is not the number that binds).

Inspect what it found:

```sh
python3 $S/release_reprofile.py catalog
```

Real output shape from the 0.7.4 run:

```
DeepSeek-V4.1-Flash  too-large  291.8  mlx-community/DeepSeek-V4.1-Flash-1017-oQ2e-mtp
GLM-5.3-Flash        too-large  102.7  Jundot/GLM-5.3-Flash-oQ2e-mtp
MiniMax-M3.1-Flash   too-large  173.7  mlx-community/MiniMax-M3.1-Flash-Text-3bit
Ling-3.1-flash       too-large  179.9  mlx-community/Ling-3.1-flash-1019-oQ2e-mtp
Qwen3.8-Flash-Next   fits        78.5  Jundot/Qwen3.8-Flash-Next-oQ2.5e-fp16-mtp
```

That last line is the whole point of the step: Flash-Next had *already been
profiled* at oQ4e (105 GB), but a smaller oQ2.5e build existed at 78.5 GB. A
`fits` verdict on a family you already run is a **variant to consider**, not an
automatic download.

## Step 3 — build the plan

```sh
python3 $S/release_reprofile.py plan --scope stale   # only version-stale rows
python3 $S/release_reprofile.py plan --scope all     # everything (default this run)
```

Writes `.reprofile/plan.json` with three lists: `reprofile`, `download`,
`not_feasible`. Commit nothing here — `.reprofile/` is working state.

**Scope is a policy choice for the operator, not for the script.** Always offer
both:

| Scope | Use when |
|---|---|
| `all` | You want a full before/after across every modality — the most thorough, and the option to present even when a narrower default is cheaper. |
| `stale` | Only rows whose recorded version differs from the installed one. Cheap; correct when the repo already stamps versions. |

A modality sweep is expensive: 7 generative models at 3 runs each is ~30-45
minutes of pure measurement plus loads. Do not quietly pick the cheap one.

## Step 4 — download the genuinely new models first

Downloads skew every measurement on this machine — observed 88 → 22 tok/s with
no config change, driven by HF I/O. So download first, measure after the queue
drains.

```sh
./scripts/disk_guard.sh <size_gb>        # 60 GB floor, mandatory
curl -s -X POST $OMLX/admin/api/hf/download -H 'Content-Type: application/json' \
  -d '{"repo_id":"mlx-community/Ming-3.0-tts-tiny-4bit"}'
```

Poll to completion, then re-discover:

```sh
curl -s $OMLX/admin/api/hf/tasks | jq -r '.tasks[]|[.repo_id,.status,(.progress|tostring)+"%"]|@tsv'
curl -s -X POST $OMLX/admin/api/reload
```

Only one download runs at a time, machine-wide. See `omlx-model-download` for
the full endpoint reference.

### New modalities need their own evaluator

0.7.4 added TTS. A TTS model has **no decode loop and no TTFT in the text
sense** — its metric is real-time factor (`audio_seconds / wall_seconds`), so it
does not belong in `generative-text.csv`. Use the matching evaluator:

| Model kind | Evaluator | Results file |
|---|---|---|
| text / VLM chat | `scripts/measure.py` | `generative-text.csv` |
| OCR / document parse | `scripts/ocr_eval.py` | `ocr.csv` |
| decision classifier | `scripts/decision_eval.py` | `decision.csv` |
| realtime voice (`/v1/realtime`) | `scripts/voice_eval.py` | `voice.csv` |
| image generation | `scripts/image_eval.py` | `image-generation.csv` |

There is **no committed evaluator for plain `/v1/audio/speech` TTS yet.** Until
there is, measure RTF with the same contract (1 discarded warmup, 3 runs,
median) and record it in `voice.csv` with `Notes` naming the endpoint, or add a
`tts` type to `scripts/record_model_result.py`. Do not invent a new CSV.

## Step 5 — re-measure the existing models

```sh
python3 $S/reprofile_batch.py --from-plan --modality generative-text --runs 3
```

The batch runner unloads everything between models, stops on settings drift,
and logs to `.reprofile/batch-*.log`. Single model:

```sh
python3 $S/reprofile_model.py --model Qwen3.8-27B-oQ4e-mtp --runs 3
```

What it does, and why each part exists:

1. **Settings drift check, before timing.** `enable_thinking`, `mtp_enabled`,
   `dflash_enabled`, `turboquant_kv_enabled`, `moe_expert_offload_enabled`,
   `max_context_window` are compared to the model's recorded `final.json`. A
   release that silently drops one of these produces a *plausible* number for
   the *wrong config*. `enable_thinking` reverting to `true` on its own is a
   real failure this repo has hit. On drift the script refuses and exits 1.
2. **Explicit load + wait.** A settings PUT containing a reload key unloads
   without reloading. Timing a cold model inflates TTFT by seconds.
3. **One discarded warmup.** On 0.7.4 the first plain-text request after a load
   also builds the grammar compiler (worth 0.31-0.37 s), which a warmup absorbs.
4. **N runs through `scripts/measure.py`'s own `post_stream`.** Imported, not
   reimplemented, so units and token accounting match every recorded row.
5. **Delta against the recorded median**, printed and written to
   `.reprofile/rerun/<model>.<version>.json`.

**Do not re-tune.** Re-profiling answers "did it change", not "is this optimal".
If the delta is large enough to suggest the old tuning decision was wrong, that
is a *new* tuning task under `omlx-model-tuning`, with paired A/B — not a
silent settings change made mid-reprofile.

## Step 6 — decide what to record

For each model, compare rerun vs recorded:

| Signal | Meaning | Action |
|---|---|---|
| within ±5% on TTFT and decode | noise; version changed nothing for this model | Refresh the row's `Notes` with the new version stamp only |
| decode up >5%, TTFT flat/slightly better | release improved it | Update row with new numbers, note the version |
| decode **down** >5% with identical settings | regression **or** machine load | Check for concurrent downloads/benchmarks first; only then call it a regression |
| settings drift | config changed | Fix settings, re-run, and record the drift in `NOTES.md` |
| TTFT wildly high (seconds) | cold model, reload, or saturated SSD cache | See "Reading a result that looks wrong" in `omlx-model-tuning` |

**The absolute-number trap applies here too.** If the original row was measured
on a quiet machine and the rerun happens with a download running, the delta is
weather, not the release. Record what you can prove; say "measured under load"
when you cannot.

Record through the invariant, never by hand:

```sh
python3 scripts/record_model_result.py --type generative-text --update --data '<json>'
python3 scripts/record_model_result.py --validate-all
```

### The `oMLX Version` column is required

Every table now has an **`oMLX Version`** column, so a row states which server
release produced it. Supply it in the row JSON you pass to `--update`:

```sh
python3 scripts/record_model_result.py --type generative-text --update --data \
  '{"Model":"Jundot/flint-oQ4e","oMLX Version":"0.7.4.dev1", ...}'
```

`record_model_result.py` refuses no row for a missing version (the schema does
not mark it mandatory yet), so an omission will silently leave a blank cell —
which `release_reprofile.py status` correctly reports as **unverified**, not as
current. Set it on every row you touch.

Adding the column to a table that predates it is a one-shot migration:

```sh
python3 scripts/record_model_result.py --migrate-add-version 0.7.4.dev1
```

That backfills every existing row with the version they were actually measured
on and regenerates both the Markdown and the dashboard embed. Only run it when
that statement is true.

## Step 7 — report the not-feasible set

`plan.json`'s `not_feasible` list is a deliverable, not a leftover. Each entry
needs the smallest known build, its size, and the reason. Add or refresh the
table in `docs/model-candidates.md` and keep the prose reason, so the next
operator does not re-derive a 291 GB dead end.

A model is `too-large` when its **smallest** matching build exceeds the resident
ceiling. Disk is not the constraint — `docs/model-candidates.md` already says
this, and it is still the most common mistake: moving a 292 GB model to the NVMe
does not make it load on a 128 GB machine, and MoE offload reduces residency
without making a 292 GB download practical.

## Step 8 — verify the dashboard actually shows the new data

A re-profile is **not** done when the CSVs validate. The dashboard is what a
human reads, and it can be wrong while every table is perfect:

- the page can throw and render blank,
- and its offline fallback (`EMBEDDED_DATA`, baked into `dashboard/index.html`)
  can go stale — showing pre-release numbers and missing models added since it
  was last written. That is not hypothetical: the fallback was hand-maintained
  and was still serving pre-0.7.4 numbers with no Ming-3.0 row at all.

The fallback is now **generated** from the CSVs. `record_model_result.py`
refreshes it on every write, and `--generate-embed` rebuilds it on demand:

```sh
python3 scripts/record_model_result.py --generate-embed
```

Gate the run on it:

```sh
python3 $S/verify_ui.py              # parity + the full Playwright suite
python3 $S/verify_ui.py --skip-e2e   # parity only, for a fast loop
```

`verify_ui.py` does exactly two things and delegates the rest:

1. **Data parity** — parses `EMBEDDED_DATA` as JSON (an unparseable block is
   the blank-page failure, and a clear JSON error beats a browser console
   message later), then asserts every model in every `results/*.csv` appears in
   the offline fallback. This is the direct answer to "did the UI load the new
   data".
2. **Full-breadth suite** — runs `npm run e2e`, the whole Playwright suite.
   This is deliberately a *call*, not a reimplementation: `e2e/` is the single
   source of truth for dashboard behaviour (`docs/E2E.md`). Never add release
   checks inside the suite that only make sense for one release; the suite must
   stay a general regression net that this skill happens to invoke.

It exits non-zero on either failure. **Do not record a run as complete if it
fails** — report it instead. A stale or broken UI means the numbers exist but
nobody can see them.

## Checks before you call it done

```sh
python3 scripts/record_model_result.py --validate-all      # tables in sync
python3 $S/verify_ui.py                                    # UI loads the new data
python3 $S/release_reprofile.py status                     # versions current
git status --short                                          # only intended paths
```

- [ ] Every `fits` catalogue entry either downloaded or explicitly deferred with a reason
- [ ] Every re-profiled row carries the new version stamp
- [ ] Every `too-large` entry is in `docs/model-candidates.md` with its smallest build
- [ ] `--validate-all` passes
- [ ] Every touched row has a non-empty `oMLX Version`
- [ ] `verify_ui.py` passes (parity **and** the Playwright suite)
- [ ] No `.reprofile/` working state committed
- [ ] Only one benchmark ran at a time (the batch runner enforces this)

## Failure modes seen for real

| Symptom | Cause | Fix |
|---|---|---|
| Dozens of already-tuned models missing from `/admin/api/models` | Server lost read access to the removable volume: `Permission denied: '/Volumes/NVMe'` in `server.log` | `omlx restart`. Verify with `models_discovered`, not by trusting the volume listing — the CLI's own Python reads the same path fine, which makes it look healthy |
| `pad_context` silently approximating | Old `measure.py` posted `{"text": ...}` to `/tokenize` | Fixed in-repo (posts `prompt`); verify if you see `tokenize failed` on stderr |
| Catalogue says a 292 GB model "fits at 1.0 GB" | Overlay/partial repo ranked as a whole model | Trusted-publisher + fragment filters (Step 2) |
| A dep version (`mlx-vlm 0.7.11`) read as the oMLX version | Naive `0.7.x` regex over `Notes` | Anchored regex that ignores foreign-package prefixes |
| Re-profile says "settings match" but TTFT is 3x worse | Benchmark slot contention or saturated SSD cache | Check `bench/active`, `du -sh ~/.omlx/cache` |
| Dashboard renders blank, every CSV still validates | `EMBEDDED_DATA` is syntactically invalid (a duplicated `};` from a bad generator) | `verify_ui.py` parses it as JSON and names the problem; fix the generator, not the page by hand |
| Offline/dashboard shows old numbers or is missing a new model | Fallback was hand-maintained and drifted | `python3 scripts/record_model_result.py --generate-embed`, then re-run `verify_ui.py` |
| E2E expects fewer rows than the table now has | Test hard-coded a row count instead of comparing against the CSV | Assert against `backend.liveRows(category)`, never a literal count |
| E2E passes but a model is invisible in the UI | Model column is the only place it can appear and the table paginated it away | Confirm via the detail panel and search; the parity gate covers the fallback, not rendering |
| Model loads but returns empty `content` with `finish_reason: length` | Reasoning budget consumed the whole `max_tokens` | Stream with `max_tokens >= 350` for quality checks |

## What this skill does not do

- It does not re-tune. Settings stay as recorded; only measurement is repeated.
- It does not benchmark two models concurrently.
- It does not touch `~/.omlx/settings.json` or `model_dirs` mid-run.
- It does not parse release notes automatically; families are supplied.
