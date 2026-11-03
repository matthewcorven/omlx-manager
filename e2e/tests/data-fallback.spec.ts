import { test, expect, visibleModels, waitForDashboardReady } from '../fixtures';

test.describe('data source fallback', () => {
  test('serves live rows from the committed CSVs when no stub is installed', async ({
    page,
    backend,
  }) => {
    const live = await backend.liveRows('generative-text');
    expect(live.length).toBeGreaterThan(0);

    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await expect(page.locator('#alert-banner .alert-info')).toHaveCount(0);
    const models = await visibleModels(page);
    expect(models.length).toBe(live.length);
    for (const model of models) expect(model).not.toContain('stub/');
  });

  test('falls back to embedded data and explains why when the CSV is unreachable', async ({
    page,
  }) => {
    await page.route('**/results/*.csv', (route) => route.abort());
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await expect(page.locator('#alert-banner .alert-info')).toContainText(
      'Loaded embedded benchmark data',
    );
    const models = await visibleModels(page);
    expect(models.length).toBeGreaterThan(0);
    expect(models.some((m) => m.includes('Qwen3.8-27B-oQ4e-mtp'))).toBe(true);
  });

  test('a 404 on the CSV also triggers the embedded fallback', async ({ page }) => {
    await page.route('**/results/*.csv', (route) =>
      route.fulfill({ status: 404, body: 'not found' }),
    );
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await expect(page.locator('#alert-banner .alert-info')).toContainText(
      'Loaded embedded benchmark data',
    );
  });

  test('a category is fetched once per page load, not on every interaction', async ({
    page,
    backend,
  }) => {
    await backend.stub('generative-text');
    let requests = 0;
    page.on('request', (req) => {
      if (req.url().includes('/results/generative-text.csv')) requests++;
    });

    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    expect(requests).toBe(1);

    await page.locator('#search-input').fill('alpha');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(1);
    await page.locator('#search-input').fill('');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(3);

    expect(requests).toBe(1);
  });
});
