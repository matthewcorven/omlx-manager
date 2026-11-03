# E2E (Playwright)

End-to-end coverage for the benchmark dashboard. Playwright is the only
permitted E2E UI automation tool in this repo.

## What is under test

`dashboard/index.html` — a single static page that renders the leaderboard from
`results/*.csv`. It has no backend of its own: the only network calls are
`fetch`es for the four CSVs, with an `EMBEDDED_DATA` fallback baked into the
page. That makes the whole surface deterministic and free to test — no omlx
server, no model load, no paid inference.

The CLI and `scripts/` are covered by Python `unittest`
(`scripts/tests/`), not by Playwright.

## Quick start

```sh
npm ci
npx playwright install chromium   # once per machine
npm run e2e                       # headless, HTML report on failure
npm run e2e:headed                # watch it run
npm run e2e:ui                    # Playwright UI mode
npm run e2e:report                # open the last HTML report
npm run e2e:typecheck             # tsc --noEmit over config + specs
```

`webServer` boots `python3 -m http.server 4321 --bind 127.0.0.1` and waits for
`/dashboard/index.html`. Override with `E2E_PORT` or point at an already-running
server with `E2E_BASE_URL` (local runs reuse an existing server; CI never does).

## Fixtures

`e2e/fixtures.ts` exports `test`, `expect`, and two fixtures. Every test arranges
its own state; nothing is shared between tests and no test depends on order.

### `backend` — deterministic data

| Method | Purpose |
|---|---|
| `stub(category)` | Serve the built-in deterministic CSV for that category |
| `stubRaw(category, csv)` | Serve a caller-supplied CSV body |
| `restore()` | Drop interception; the page reads the real committed CSVs |
| `liveRows(category)` | Parse the real `results/<category>.csv` from disk |
| `stubModels(category)` | The model names the stub serves |

Stub rows are always prefixed `stub/` so a test can never mistake fixture data
for real benchmark data. Interception is installed on `**/results/*.csv` and
removed at teardown.

### `fork` — independent page states

`fork.capture(page, name)` snapshots a context's storage state in memory;
`fork.open(name)` returns a fresh page seeded from it. `fork.open(name, { cold: true })`
skips the snapshot. Use this instead of replaying a journey to reach a state.
Snapshots live in a per-test `Map` — never on disk, never shared.

### Helpers

`waitForDashboardReady`, `selectTab`, `visibleModels`, `kpiCard`, `rowFor`.

## Selectors

The dashboard is hand-rolled HTML with no ARIA roles or test ids, so role-based
queries are weak here. Prefer, in order:

1. `#id` — `#search-input`, `#status-filter`, `#table-body`, `#kpi-container`
2. `data-*` — `th[data-key="..."]`, `tr[data-rowid="..."]`
3. Structural classes — `tr.data-row`, `tr.details-row.show`, `.kpi-card`

Row ids are positional (`row-<category>-<index>`), so assert on rendered content
via `rowFor(page, model)` rather than on a hard-coded index whenever the sort
order is not the thing under test.

## Readiness

Wait on rendered output, never on time. `waitForDashboardReady` waits for the
first `tr.data-row`. There is no `waitForTimeout` anywhere in this suite and
none may be added.

## Coverage gate

Every workflow needs a happy path, an alternate path, and an edge case. Current
workflows: leaderboard shell, search/filter, sorting, row details, data-source
fallback. A new dashboard interaction is not done until it has all three.

## What is never committed

`playwright-report/`, `blob-report/`, `test-results/`, `playwright-reports/`,
`.e2e-logs/`. Reports are ephemeral locally and artifacts in CI.

## CI

`.github/workflows/e2e.yml` runs two shards, uploads a blob report per shard,
and merges them into a single `playwright-report` artifact retained for 90 days.
Retrieve it with the `playwright-report-retrieval` plugin — see
`.github/skills/playwright-report-retrieval` (or the plugin's own skill) for
`list_failed_tests` and `fetch_report`.
