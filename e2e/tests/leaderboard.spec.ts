import {
  test,
  expect,
  CATEGORIES,
  selectTab,
  visibleModels,
  waitForDashboardReady,
  kpiCard,
} from '../fixtures';

test.describe('leaderboard shell', () => {
  test('renders the default category with KPI cards and rows', async ({ page, backend }) => {
    await backend.stub('generative-text');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await expect(page.locator('#category-tabs .tab-button.active')).toHaveText('Generative Text');
    await expect(page.locator('#kpi-container .kpi-card')).toHaveCount(4);
    await expect(kpiCard(page, 'Top Throughput')).toContainText('210.0');
    await expect(kpiCard(page, 'Tuned Candidates')).toContainText('3');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(3);
  });

  test('every category tab renders its own rows', async ({ page, backend }) => {
    for (const category of CATEGORIES) await backend.stub(category);
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    const labels: Record<string, string> = {
      'generative-text': 'Generative Text',
      ocr: 'OCR & Non-LLM',
      decision: 'Decision Models',
      'image-generation': 'Image Generation',
      voice: 'Conversational Voice',
    };

    for (const category of CATEGORIES) {
      await selectTab(page, labels[category]);
      await waitForDashboardReady(page);
      const models = await visibleModels(page);
      expect(models.length).toBeGreaterThan(0);
      for (const model of models) expect(model).toContain('stub/');
    }
  });

  test('a category with no matching rows shows the empty state instead of a blank table', async ({
    page,
    backend,
  }) => {
    await backend.stubRaw(
      'generative-text',
      'Model,Quant,Params,Download Size,Resident Size,Baseline TTFT (ms),Baseline Decode (tps),Final TTFT (ms),Final Decode (tps),Final Settings,Quality Pass Rate,Notes',
    );
    await page.goto('/dashboard/index.html');

    await expect(page.locator('#table-body')).toContainText(
      'No benchmark records match your filter criteria.',
    );
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(0);
  });
});
