import {
  test,
  expect,
  CATEGORIES,
  selectTab,
  rowFor,
  waitForDashboardReady,
  visibleModels,
} from '../fixtures';
import fs from 'node:fs/promises';
import path from 'node:path';

/**
 * Guards the invariant that the dashboard's embedded fallback is *generated*
 * from the committed CSVs, not maintained by hand.
 *
 * The fallback used to be a hand-edited copy of every table. It silently went
 * stale: it still served pre-0.7.4 numbers and did not contain models added
 * after it was written, so anyone opening the dashboard from `file://` or
 * hitting a failed fetch saw a different leaderboard than the repo contained.
 */
test.describe('embedded data freshness', () => {
  test('every live model appears in the offline fallback', async ({ page, backend }) => {
    const labels: Record<string, string> = {
      'generative-text': 'Generative Text',
      ocr: 'OCR & Non-LLM',
      decision: 'Decision Models',
      'image-generation': 'Image Generation',
      voice: 'Conversational Voice',
    };

    // The page fetches every CSV up front, so the offline path is exercised
    // only when all of them are unreachable. That is also how a real
    // `file://` open behaves.
    await page.route('**/results/*.csv', (route) => route.abort());
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    await expect(page.locator('#alert-banner .alert-info')).toContainText(
      'Loaded embedded benchmark data',
    );

    for (const category of CATEGORIES) {
      const live = await backend.liveRows(category);
      expect(live.length, `${category} has live rows`).toBeGreaterThan(0);

      await selectTab(page, labels[category]);

      // Switching tabs re-renders asynchronously, so poll until the rendered
      // model set matches the committed CSV rather than reading too early.
      const expected = live.map((r) => r.Model.trim()).sort();
      await expect
        .poll(
          async () => (await visibleModels(page)).map((m) => m.trim()).sort(),
          { message: `${category}: offline fallback must match the committed CSV` },
        )
        .toEqual(expected);
    }
  });

  test('the generated block contains no duplicated closing brace', async () => {
    // A real bug: the generator once appended `};` on top of the JSON's own
    // `}`, producing `}; };` and a page that threw "Unexpected token '}'".
    const html = await fs.readFile(
      path.join(process.cwd(), 'dashboard', 'index.html'),
      'utf8',
    );
    const start = html.indexOf('const EMBEDDED_DATA = ');
    expect(start).toBeGreaterThan(-1);
    const end = html.indexOf('const CONFIG = ', start);
    const block = html.slice(start, end);
    expect(block.match(/^\};$/gm) ?? []).toHaveLength(1);
  });

  test('the offline fallback renders rows rather than a blank table', async ({ page }) => {
    await page.route('**/results/*.csv', (route) => route.abort());
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await expect(page.locator('#alert-banner .alert-info')).toContainText(
      'Loaded embedded benchmark data',
    );
    const models = await visibleModels(page);
    expect(models.length).toBeGreaterThan(0);
  });
});

test.describe('oMLX version column', () => {
  test('a row detail panel shows the oMLX version it was measured on', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await rowFor(page, 'stub/alpha-7b').click();
    const details = page.locator('#table-body tr.details-row.show');
    await expect(details).toHaveCount(1);
    await expect(details).toContainText('oMLX Version');
    await expect(details).toContainText('0.7.4.dev1');
  });

  test('a row without a recorded version says so instead of rendering "undefined"', async ({
    page,
    backend,
  }) => {
    const header =
      'Model,Quant,Params,Download Size,Resident Size,oMLX Version,Baseline TTFT (ms),Baseline Decode (tps),Final TTFT (ms),Final Decode (tps),Final Settings,Quality Pass Rate,Notes';
    await backend.stubRaw(
      'generative-text',
      [
        header,
        'stub/no-version,oQ4e,dense 1B,1.0 GiB,1.0 GiB,,10.0,20.0,9.0,25.0,"ctx 8192",3/3 pass,Row without a stamp',
      ].join('\n'),
    );
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await rowFor(page, 'stub/no-version').click();
    const details = page.locator('#table-body tr.details-row.show');
    await expect(details).toContainText('not recorded');
    await expect(details).not.toContainText('undefined');
  });

  test('every committed row carries an oMLX version', async ({ backend }) => {
    for (const category of CATEGORIES) {
      const rows = await backend.liveRows(category);
      const missing = rows.filter((r) => !(r['oMLX Version'] || '').trim()).map((r) => r.Model);
      expect(missing, `${category} rows without an oMLX Version`).toEqual([]);
    }
  });
});
