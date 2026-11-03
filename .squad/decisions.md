# Squad Decisions

## Active Decisions

### 2026-11-03 — Adopt Playwright E2E for the dashboard

**Decision:** Adopt Playwright E2E, scoped to `dashboard/index.html`.

**Why:** The dashboard is a real interactive SPA (category tabs, search, status
filter, sortable headers, expandable detail rows, KPI cards) and it is fully
static — the only network calls are `fetch`es for `results/*.csv`, with an
`EMBEDDED_DATA` fallback. That makes it deterministic and free to test: no omlx
server, no model load, no paid inference. The CLI and `scripts/` stay on Python
`unittest`; Playwright is not the right tool for them.

**Ownership:** Docs owns E2E (it already owns `dashboard/`). No second testing
owner is created. Standards live in `docs/E2E.md`; the tester charter points at
it rather than restating it.

**Consequences:** `package.json`, `playwright.config.ts`, `e2e/`, and
`.github/workflows/e2e.yml` are now repo-local Layer A artifacts. Standards,
report handling, and the never-commit list live in `docs/E2E.md` — this entry
does not restate them. CI reports are read with the
`playwright-report-retrieval` plugin from `corven-agent-tools` (Layer C —
consumed, never modified).

## Governance

- All meaningful changes require team consensus
- Document architectural decisions here
- Keep history focused on work, decisions focused on direction
