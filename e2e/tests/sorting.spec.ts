import { test, expect, visibleModels, waitForDashboardReady } from '../fixtures';

test.describe('column sorting', () => {
  test('default sort is descending by final decode throughput', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    // gamma 210 > beta 150 > alpha 60
    expect(await visibleModels(page)).toEqual([
      'stub/gamma-3b',
      'stub/beta-30b',
      'stub/alpha-7b',
    ]);
    await expect(
      page.locator('#table-headers th[data-key="Final Decode (tps)"] .sort-icon'),
    ).toHaveText('▼');
  });

  test('clicking the active header flips direction', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await page.locator('#table-headers th[data-key="Final Decode (tps)"]').click();
    await expect(
      page.locator('#table-headers th[data-key="Final Decode (tps)"] .sort-icon'),
    ).toHaveText('▲');
    expect(await visibleModels(page)).toEqual([
      'stub/alpha-7b',
      'stub/beta-30b',
      'stub/gamma-3b',
    ]);
  });

  test('clicking a different header sorts by it descending first', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await page.locator('#table-headers th[data-key="Model"]').click();
    await expect(page.locator('#table-headers th[data-key="Model"] .sort-icon')).toHaveText('▼');
    expect(await visibleModels(page)).toEqual([
      'stub/gamma-3b',
      'stub/beta-30b',
      'stub/alpha-7b',
    ]);
  });

  test('switching tabs resets sorting to that category default', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await backend.stub('ocr');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await page.locator('#table-headers th[data-key="Model"]').click();
    await expect(page.locator('#table-headers th[data-key="Model"] .sort-icon')).toHaveText('▼');

    await page.locator('#category-tabs .tab-button', { hasText: 'OCR & Non-LLM' }).click();
    await waitForDashboardReady(page);

    // OCR primarySort is CER ascending, so the lower error rate comes first.
    await expect(
      page.locator('#table-headers th[data-key="CER (Character Error Rate)"] .sort-icon'),
    ).toHaveText('▲');
    expect(await visibleModels(page)).toEqual(['stub/ocr-good', 'stub/ocr-bad']);
  });
});
