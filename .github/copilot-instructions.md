# Copilot instructions

Repository-wide operating instructions live in [`AGENTS.md`](../AGENTS.md). Read
that first; it governs model selection, benchmarking, storage, and the results
recording invariant.

## E2E / Playwright

- Standards, fixtures, and selector conventions: [`docs/E2E.md`](../docs/E2E.md).
- Run the suite with `npm run e2e`; typecheck with `npm run e2e:typecheck`.
- Playwright is the only permitted E2E UI automation tool.
- Never commit `playwright-report/`, `blob-report/`, `test-results/`,
  `playwright-reports/`, or `.e2e-logs/`.
- To read a CI report, use the `playwright-report-retrieval` plugin
  (`list_failed_tests`, `fetch_report`) rather than downloading and unzipping
  artifacts by hand. The plugin is enabled in
  [`.github/copilot/settings.json`](copilot/settings.json).
