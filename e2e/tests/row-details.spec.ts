import { test, expect, rowFor, waitForDashboardReady } from '../fixtures';

test.describe('row detail panels', () => {
  test('clicking a row expands its detail panel', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    const details = page.locator('#row-generative-text-0-details');
    await expect(details).not.toHaveClass(/show/);

    await page.locator('#table-body tr.data-row').first().click();
    await expect(details).toHaveClass(/show/);
    await expect(details).toContainText('Model Identifier & Size');
    await expect(details).toContainText('Evaluation Notes & Findings');
  });

  test('clicking the same row again collapses it', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    const row = page.locator('#table-body tr.data-row').first();
    const details = page.locator('#row-generative-text-0-details');

    await row.click();
    await expect(details).toHaveClass(/show/);
    await row.click();
    await expect(details).not.toHaveClass(/show/);
  });

  test('expanding a second row collapses the first', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await page.locator('#table-body tr.data-row').nth(0).click();
    await expect(page.locator('#row-generative-text-0-details')).toHaveClass(/show/);

    await page.locator('#table-body tr.data-row').nth(1).click();
    await expect(page.locator('#row-generative-text-0-details')).not.toHaveClass(/show/);
    await expect(page.locator('#row-generative-text-1-details')).toHaveClass(/show/);
  });

  test('detail panel shows the row-specific notes', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await rowFor(page, 'stub/beta-30b').click();
    const details = page.locator('#table-body tr.details-row.show');
    await expect(details).toHaveCount(1);
    await expect(details).toContainText('Beta stub row');
    await expect(details).toContainText('ctx native, MTP on');
  });
});
