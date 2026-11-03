# Work Routing

How to decide who handles what.

## Routing Table

| Work Type | Route To | Examples |
|-----------|----------|----------|
| Triage, approvals, model-selection decisions, ground-rule disputes, unmatched work | Lead | Approve a download, pick next candidate, update `docs/model-candidates.md`, enforce benchmark invariant |
| Model search, download, disk/size accounting | Scout | `disk_guard.sh`, `/admin/api/hf/download`, verify landed files |
| Benchmarking and settings tuning (one model per instance, serialized) | Tuner | Baseline, sweep, record via `scripts/record_model_result.py --type generative-text` |
| Decision-model, OCR, and Image-gen evaluation | Evaluator | Score on labelled corpus, record via `scripts/record_model_result.py --type [ocr\|decision\|image-generation]` |
| Server health, troubleshooting, scripts, approved shuttles | Ops | 409/OOM/port issues, `scripts/`, shuttle to external volume |
| Docs, schemas, results reporting, and dashboard | Docs | `docs/`, README, `results/*.{csv,md}` validation via `--validate-all`, `dashboard/` |
| Tests and coverage (E2E/Playwright, edge cases, regression gating) | Docs | `e2e/`, `npm run e2e`, `docs/E2E.md` |

Escalation: unmatched work or ownership disputes go to Lead.

## Issue Routing

| Label | Action | Who |
|-------|--------|-----|
| `squad` | Triage: analyze issue, assign `squad:{member}` label | Lead |
| `squad:{name}` | Pick up issue and complete the work | Named member |

### How Issue Assignment Works

1. When a GitHub issue gets the `squad` label, the **Lead** triages it — analyzing content, assigning the right `squad:{member}` label, and commenting with triage notes.
2. When a `squad:{member}` label is applied, that member picks up the issue in their next session.
3. Members can reassign by removing their label and adding another member's label.
4. The `squad` label is the "inbox" — untriaged issues waiting for Lead review.

## Rules

0. **AGENTS.md ground rules override everything below:** never delete `$OMLX_CACHE_DIR`; `disk_guard.sh` before every download (60 GB floor); one model per agent; never edit `$OMLX_HOME/settings.json`; no concurrent benchmarks; **all benchmark results must be recorded ONLY EVER via `scripts/record_model_result.py`** into `results/*.csv` and `results/*.md`; ad-hoc unvalidated markdown tables are strictly prohibited; benchmarks/evals are strictly serialized.
1. **Bounded, not eager** — one accountable owner per item; no anticipatory spawns that would touch a model or the server.
2. **Scribe always runs** after substantial work, always as `mode: "background"`. Never blocks.
3. **Quick facts → coordinator answers directly.** Don't spawn an agent for "what port does the server run on?"
4. **When two agents could handle it**, pick the one whose domain is the primary concern.
5. **"Team, ..." → Lead first.** Fan out only read-only/doc work in parallel; never run two Tuner/Evaluator instances against the server at once.
6. **No anticipatory downstream work** on models: Tuner starts only after Scout's verified download and Lead's approval.
7. **Issue-labeled work** — when a `squad:{member}` label is applied to an issue, route to that member. The Lead handles all `squad` (base label) triage.
8. **Benchmark Invariant Enforcement** — every commit touching benchmark metrics must be verified using `python3 scripts/record_model_result.py --validate-all`. The Lead rejects any submission with unvalidated or manually edited tables.
