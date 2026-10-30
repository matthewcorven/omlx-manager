# Work Routing

How to decide who handles what.

## Routing Table

| Work Type | Route To | Examples |
|-----------|----------|----------|
| Triage, approvals, model-selection decisions, ground-rule disputes, unmatched work | Lead | Approve a download, pick next candidate, update `docs/model-candidates.md` |
| Model search, download, disk/size accounting | Scout | `disk_guard.sh`, `/admin/api/hf/download`, verify landed files |
| Benchmarking and settings tuning (one model per instance, serialized) | Tuner | Baseline, sweep, `results/<model>/final.json` |
| Decision-model and OCR evaluation | Evaluator | Score Clef/d3-* on labelled corpus; OCR regression gate |
| Server health, troubleshooting, scripts, approved shuttles | Ops | 409/OOM/port issues, `scripts/`, shuttle to external volume |
| Docs and results reporting | Docs | `docs/`, README, `results/COMPARISON.md` |

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

0. **AGENTS.md ground rules override everything below:** never delete `$OMLX_CACHE_DIR`; `disk_guard.sh` before every download (60 GB floor); one model per agent; never edit `$OMLX_HOME/settings.json`; no concurrent benchmarks; record everything in `results/<model>/`. Benchmarks/evals are strictly serialized.
1. **Bounded, not eager** — one accountable owner per item; no anticipatory spawns that would touch a model or the server.
2. **Scribe always runs** after substantial work, always as `mode: "background"`. Never blocks.
3. **Quick facts → coordinator answers directly.** Don't spawn an agent for "what port does the server run on?"
4. **When two agents could handle it**, pick the one whose domain is the primary concern.
5. **"Team, ..." → Lead first.** Fan out only read-only/doc work in parallel; never run two Tuner/Evaluator instances against the server at once.
6. **No anticipatory downstream work** on models: Tuner starts only after Scout's verified download and Lead's approval.
7. **Issue-labeled work** — when a `squad:{member}` label is applied to an issue, route to that member. The Lead handles all `squad` (base label) triage.
