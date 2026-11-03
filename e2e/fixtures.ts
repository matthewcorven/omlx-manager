import {
  test as base,
  expect,
  type BrowserContextOptions,
  type Page,
  type Route,
} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

export type Category = 'generative-text' | 'ocr' | 'decision' | 'image-generation';

export const CATEGORIES: Category[] = [
  'generative-text',
  'ocr',
  'decision',
  'image-generation',
];

/** Deterministic CSV doubles. The dashboard parses these exactly like the real files. */
export const STUB_CSV: Record<Category, string> = {
  'generative-text': [
    'Model,Quant,Params,Download Size,Resident Size,Baseline TTFT (ms),Baseline Decode (tps),Final TTFT (ms),Final Decode (tps),Final Settings,Quality Pass Rate,Notes',
    'stub/alpha-7b,oQ4e,dense 7B,4.0 GiB,4.2 GiB,100.0,50.0,90.0,60.0,"ctx 32768, thinking off",3/3 pass,Alpha stub row',
    'stub/beta-30b,oQ8e,MoE 30B,18.0 GiB,19.0 GiB,200.0,120.0,180.0,150.0,"ctx native, MTP on",3/3 pass,Beta stub row',
    'stub/gamma-3b,oQ4e,dense 3B,2.0 GiB,2.1 GiB,40.0,200.0,35.0,210.0,"ctx 8192",1/3 pass,Gamma stub row',
  ].join('\n'),
  ocr: [
    'Model,Quant,Checkpoint/Package,Resident Size,CER (Character Error Rate),WER (Word Error Rate),Avg Page Latency (s),Max Tokens,Quality/Status,Notes',
    'stub/ocr-good,8bit,stub-pkg,1.0 GB,0.0010,N/A,0.50,8192,PASS - fixed,Good stub row',
    'stub/ocr-bad,8bit,stub-pkg,2.0 GB,0.2500,N/A,1.50,8192,FAIL - degenerate,Bad stub row',
  ].join('\n'),
  decision: [
    'Model,Quant,Params,Resident Size,Gate 1 (Accuracy),Gate 2 (ECE / Calibration),Gate 3 (Log Loss),Gate 4 (Media Score),Mean TTFT,Samples,Notes',
    'stub/dec-pass,native,1.0 GB,1.0 GB,0.9000,0.0500,0.1000,0.950 (Image),10.0 ms,39,PASS - scored',
    'stub/dec-fail,native,2.0 GB,2.0 GB,0.5000,0.2000,0.5000,0.500 (Image),20.0 ms,39,FAIL - dominated',
  ].join('\n'),
  'image-generation': [
    'Model,Quant,Steps,Resolution,TTFT/Step Latency,Total Latency,VRAM/Resident,Quality/CLIP,Notes',
    'stub/img-fast,8bit,4,1024x1024,100.0 ms/step,1.00 s,4.0 GB,0.3000 CLIP,Fast stub row',
    'stub/img-slow,8bit,20,1024x1024,500.0 ms/step,9.00 s,12.0 GB,0.3500 CLIP,Slow stub row',
  ].join('\n'),
};

export type Backend = {
  /** Intercept every results CSV with the deterministic stub for `category`. */
  stub(category: Category): Promise<void>;
  /** Intercept every results CSV with a caller-supplied body. */
  stubRaw(category: Category, csv: string): Promise<void>;
  /** Remove all interception; the page then reads the real committed CSVs. */
  restore(): Promise<void>;
  /** Read and parse the real committed CSV for `category` from disk. */
  liveRows(category: Category): Promise<Record<string, string>[]>;
  /** Every model name the stub serves for `category`. */
  stubModels(category: Category): string[];
};

export type Fork = {
  capture(page: Page, name: string): Promise<void>;
  open(name: string, opts?: { cold?: boolean }): Promise<Page>;
};

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split(/\r?\n/);
  const parseLine = (line: string): string[] => {
    const out: string[] = [];
    let cur = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuotes && line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (ch === ',' && !inQuotes) {
        out.push(cur.trim());
        cur = '';
      } else {
        cur += ch;
      }
    }
    out.push(cur.trim());
    return out;
  };
  const headers = parseLine(lines[0]);
  return lines
    .slice(1)
    .filter((l) => l.trim())
    .map((line) => {
      const values = parseLine(line);
      const row: Record<string, string> = {};
      headers.forEach((h, i) => (row[h] = values[i] ?? ''));
      return row;
    });
}

export const test = base.extend<{ backend: Backend; fork: Fork }>({
  backend: async ({ page }, use) => {
    const stubbed = new Set<Category>();
    const overrides = new Map<Category, string>();

    const handler = async (route: Route) => {
      const url = route.request().url();
      const match = CATEGORIES.find((c) => url.includes(`/results/${c}.csv`));
      if (!match || !stubbed.has(match)) {
        await route.continue();
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'text/csv',
        body: overrides.get(match) ?? STUB_CSV[match],
      });
    };

    await page.route('**/results/*.csv', handler);

    const backend: Backend = {
      async stub(category) {
        stubbed.add(category);
      },
      async stubRaw(category, csv) {
        stubbed.add(category);
        overrides.set(category, csv);
      },
      async restore() {
        stubbed.clear();
        overrides.clear();
      },
      async liveRows(category) {
        const file = path.join(process.cwd(), 'results', `${category}.csv`);
        return parseCsv(await fs.readFile(file, 'utf8'));
      },
      stubModels(category) {
        return parseCsv(STUB_CSV[category]).map((r) => r.Model);
      },
    };

    await use(backend);

    // Teardown: never leave interception behind for the next test.
    await page.unroute('**/results/*.csv').catch(() => {});
  },

  fork: async ({ browser, baseURL }, use) => {
    // Per-test in-memory snapshots: no shared directory, no cross-test bleed.
    type StorageState = NonNullable<BrowserContextOptions['storageState']>;
    const snapshots = new Map<string, StorageState>();
    const contexts: Awaited<ReturnType<typeof browser.newContext>>[] = [];

    await use({
      async capture(page, name) {
        snapshots.set(name, await page.context().storageState());
      },
      async open(name, opts) {
        const state = opts?.cold ? undefined : snapshots.get(name);
        if (!opts?.cold && !state) {
          throw new Error(`fork.open("${name}") called before fork.capture("${name}")`);
        }
        const context = await browser.newContext({ baseURL, storageState: state });
        contexts.push(context);
        return context.newPage();
      },
    });

    for (const context of contexts) await context.close().catch(() => {});
  },
});

export { expect };

/** Wait until the dashboard has rendered at least one data row. */
export async function waitForDashboardReady(page: Page): Promise<void> {
  await expect(page.locator('#table-body tr.data-row').first()).toBeVisible();
}

/** Click a category tab by its visible label. */
export async function selectTab(page: Page, label: string): Promise<void> {
  await page.locator('#category-tabs .tab-button', { hasText: label }).click();
  await expect(page.locator('#category-tabs .tab-button.active')).toHaveText(label);
}

/** All model names currently rendered in the leaderboard body. */
export async function visibleModels(page: Page): Promise<string[]> {
  return page.locator('#table-body tr.data-row td:first-child').allInnerTexts();
}

/** The KPI card whose label matches `label`. */
export function kpiCard(page: Page, label: string) {
  return page.locator('#kpi-container .kpi-card').filter({ hasText: label });
}

/** A data row whose first cell contains `model`. */
export function rowFor(page: Page, model: string) {
  return page.locator('#table-body tr.data-row').filter({ hasText: model });
}
