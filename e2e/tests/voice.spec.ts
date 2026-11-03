import {
  test,
  expect,
  selectTab,
  visibleModels,
  waitForDashboardReady,
  kpiCard,
  rowFor,
} from '../fixtures';

const VOICE_TAB = 'Conversational Voice';

test.describe('conversational voice category', () => {
  test('renders voice rows with realtime KPIs and a status badge', async ({ page, backend }) => {
    await backend.stub('voice');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);

    await selectTab(page, VOICE_TAB);
    await waitForDashboardReady(page);

    // Primary sort is real-time factor descending: 9.50 before 1.20.
    expect(await visibleModels(page)).toEqual(['stub/voice-fast', 'stub/voice-slow']);

    await expect(kpiCard(page, 'Best Real-Time Factor')).toContainText('9.50');
    await expect(kpiCard(page, 'Best Real-Time Factor')).toContainText('stub/voice-fast');
    await expect(kpiCard(page, 'Lowest First Audio')).toContainText('90');
    await expect(kpiCard(page, 'Best Round-Trip WER')).toContainText('2.00%');
    await expect(kpiCard(page, 'Gate Qualified')).toContainText('1 / 2');

    await expect(rowFor(page, 'stub/voice-fast').locator('.badge-pass')).toHaveText(
      'PASS - 3/3 turns completed',
    );
    await expect(rowFor(page, 'stub/voice-slow').locator('.badge-fail')).toHaveText(
      'FAIL - turn timeout',
    );
  });

  test('sorting by first audio latency reorders the voice table', async ({ page, backend }) => {
    await backend.stub('voice');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    await selectTab(page, VOICE_TAB);
    await waitForDashboardReady(page);

    await page.locator('#table-headers th[data-key="First Audio Latency (ms)"]').click();
    await expect(
      page.locator('#table-headers th[data-key="First Audio Latency (ms)"] .sort-icon'),
    ).toHaveText('▼');
    expect(await visibleModels(page)).toEqual(['stub/voice-slow', 'stub/voice-fast']);

    await page.locator('#table-headers th[data-key="First Audio Latency (ms)"]').click();
    await expect(
      page.locator('#table-headers th[data-key="First Audio Latency (ms)"] .sort-icon'),
    ).toHaveText('▲');
    expect(await visibleModels(page)).toEqual(['stub/voice-fast', 'stub/voice-slow']);
  });

  test('status filter isolates failing voice turns and search matches the voices column', async ({
    page,
    backend,
  }) => {
    await backend.stub('voice');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    await selectTab(page, VOICE_TAB);
    await waitForDashboardReady(page);

    await page.locator('#status-filter').selectOption('fail');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(1);
    expect(await visibleModels(page)).toEqual(['stub/voice-slow']);

    await page.locator('#status-filter').selectOption('all');
    await page.locator('#search-input').fill('6 languages');
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(1);
    expect(await visibleModels(page)).toEqual(['stub/voice-slow']);
  });

  test('a voice row expands to show its realtime notes', async ({ page, backend }) => {
    await backend.stub('voice');
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    await selectTab(page, VOICE_TAB);
    await waitForDashboardReady(page);

    await rowFor(page, 'stub/voice-fast').click();
    const details = page.locator('#table-body tr.details-row.show');
    await expect(details).toHaveCount(1);
    await expect(details).toContainText('Fast stub row');
    await expect(details).toContainText('stub/voice-fast');
  });

  test('an empty voice table shows the empty state instead of a blank panel', async ({
    page,
    backend,
  }) => {
    await backend.stubRaw(
      'voice',
      'Model,Quant,Params,Resident Size,Turn TTFT (ms),First Audio Latency (ms),Reply Audio (ms),Speech Real-Time Factor,Transcript WER,Voices/Languages,Quality/Status,Notes',
    );
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    await selectTab(page, VOICE_TAB);

    await expect(page.locator('#table-body')).toContainText(
      'No benchmark records match your filter criteria.',
    );
    await expect(page.locator('#table-body tr.data-row')).toHaveCount(0);
  });

  test('the voice tab falls back to embedded data when the CSV is unreachable', async ({
    page,
  }) => {
    await page.route('**/results/*.csv', (route) => route.abort());
    await page.goto('/dashboard/index.html');
    await waitForDashboardReady(page);
    await selectTab(page, VOICE_TAB);
    await waitForDashboardReady(page);

    await expect(page.locator('#alert-banner .alert-info')).toContainText(
      'Loaded embedded benchmark data',
    );
    const models = await visibleModels(page);
    expect(models.some((m) => m.includes('LFM3-Omni-2B-MLX-4bit'))).toBe(true);
  });
});
