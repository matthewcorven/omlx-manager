import { defineConfig, devices } from '@playwright/test';

const IS_CI = !!process.env.CI;

const PORT = Number(process.env.E2E_PORT ?? 4321);
const BASE_URL = process.env.E2E_BASE_URL ?? `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: './e2e/tests',
  fullyParallel: true,
  forbidOnly: IS_CI,
  retries: IS_CI ? 1 : 0,
  workers: IS_CI ? 2 : undefined,
  timeout: 30_000,
  expect: { timeout: 15_000 },

  reporter: IS_CI
    ? [['blob'], ['github']]
    : [['html', { open: 'on-failure' }], ['list']],

  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1`,
    url: `${BASE_URL}/dashboard/index.html`,
    reuseExistingServer: !IS_CI,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 5_000 },
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
