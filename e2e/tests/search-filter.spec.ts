import { test, expect, visibleModels, waitForDashboardReady } from '../fixtures';

test.describe('search and status filtering', () => {
  test('search narrows rows to matching models', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    expect(await visibleModels(page)).toHaveLength(3);

    await page.locator('#search-input').fill('beta');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(1);
    expect(await visibleModels(page)).toEqual(['stub/beta-30b']);
  });

  test('search matches any column, not just the model name', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    // "MoE 30B" only appears in the Params column of the beta row.
    await page.locator('#search-input').fill('MoE 30B');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(1);
    expect(await visibleModels(page)).toEqual(['stub/beta-30b']);
  });

  test('status filter isolates failing rows and combines with search', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await page.locator('#status-filter').selectOption('fail');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(0);

    await page.locator('#status-filter').selectOption('pass');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(3);

    await page.locator('#search-input').fill('gamma');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(1);
    expect(await visibleModels(page)).toEqual(['stub/gamma-3b']);
  });

  test('a search with no matches shows the empty state and recovers when cleared', async ({
    page,
    backend,
  }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await page.locator('#search-input').fill('no-such-model-anywhere');
    await expect(page.locator('#table-body')).toContainText(
      'No benchmark records match your filter criteria.',
    );

    await page.locator('#search-input').fill('');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(3);
  });
});
