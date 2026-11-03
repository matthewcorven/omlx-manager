import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CanvasError, createCanvas, joinSession } from "@github/copilot-sdk/extension";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const dashboardHtmlPath = path.join(repoRoot, "dashboard", "index.html");
const resultsDir = path.join(repoRoot, "results");

const allowedCsvFiles = new Set([
    "generative-text.csv",
    "ocr.csv",
    "decision.csv",
    "image-generation.csv",
    "voice.csv",
]);

const validCategories = new Set([
    "generative-text",
    "ocr",
    "decision",
    "image-generation",
    "voice",
]);

const servers = new Map();

function getOpenEntry(instanceId) {
    const entry = servers.get(instanceId);
    if (!entry) {
        throw new CanvasError("dashboard_not_open", "Open the oMLX Dashboard canvas before invoking this action.");
    }
    return entry;
}

function broadcast(entry, event, data) {
    for (const client of entry.clients) {
        client.write(`event: ${event}\n`);
        client.write(`data: ${JSON.stringify(data)}\n\n`);
    }
}

async function computeSummaryStats() {
    const categories = [
        { key: "generative-text", file: "generative-text.csv" },
        { key: "ocr", file: "ocr.csv" },
        { key: "decision", file: "decision.csv" },
        { key: "image-generation", file: "image-generation.csv" },
    ];
    const categoryCounts = {};
    let totalModels = 0;

    for (const cat of categories) {
        try {
            const content = await readFile(path.join(resultsDir, cat.file), "utf8");
            const lines = content.trim().split(/\r?\n/).filter((l) => l.trim().length > 0);
            const count = Math.max(0, lines.length - 1);
            categoryCounts[cat.key] = count;
            totalModels += count;
        } catch {
            categoryCounts[cat.key] = 0;
        }
    }

    return {
        categories: categoryCounts,
        totalModels,
        timestamp: new Date().toISOString(),
    };
}

async function renderDashboardHtml(entry) {
    const originalHtml = await readFile(dashboardHtmlPath, "utf8");
    const categoryJson = JSON.stringify(entry.category || "generative-text");

    const injection = `
<script>
(() => {
  const initialCategory = ${categoryJson};

  function applyCategory(cat) {
    if (!cat) return;
    const btn = document.querySelector(\`.tab-button[data-tab="\${cat}"]\`);
    if (btn) btn.click();
  }

  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', () => {
      if (initialCategory) setTimeout(() => applyCategory(initialCategory), 50);
    });
  } else {
    if (initialCategory) setTimeout(() => applyCategory(initialCategory), 50);
  }

  try {
    const sse = new EventSource('/events');
    sse.addEventListener('switch_tab', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.category) applyCategory(data.category);
      } catch (err) {}
    });
    sse.addEventListener('reload', () => {
      window.location.reload();
    });
  } catch (err) {}
})();
</script>
</body>`;

    return originalHtml.replace("</body>", injection);
}

async function streamFile(res, filePath, contentType) {
    const fileStat = await stat(filePath).catch(() => undefined);
    if (!fileStat?.isFile()) {
        res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
        res.end("Not found");
        return;
    }

    res.writeHead(200, {
        "content-type": contentType,
        "cache-control": "no-cache",
    });
    const stream = createReadStream(filePath);
    stream.on("error", () => {
        if (!res.headersSent) {
            res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
            res.end("Error reading file");
        } else {
            res.destroy();
        }
    });
    stream.pipe(res);
}

async function handleRequest(entry, req, res) {
    const url = new URL(req.url ?? "/", entry.url);

    if (url.pathname === "/events") {
        res.writeHead(200, {
            "content-type": "text/event-stream; charset=utf-8",
            "cache-control": "no-cache",
            connection: "keep-alive",
        });
        entry.clients.add(res);
        req.on("close", () => entry.clients.delete(res));
        return;
    }

    if (url.pathname === "/api/summary") {
        const stats = await computeSummaryStats();
        res.writeHead(200, {
            "content-type": "application/json; charset=utf-8",
            "cache-control": "no-store",
        });
        res.end(JSON.stringify(stats));
        return;
    }

    // Serve CSV datasets
    const baseName = path.basename(url.pathname);
    if (allowedCsvFiles.has(baseName)) {
        await streamFile(res, path.join(resultsDir, baseName), "text/csv; charset=utf-8");
        return;
    }

    // Serve index.html
    if (url.pathname === "/" || url.pathname === "/index.html") {
        const html = await renderDashboardHtml(entry);
        res.writeHead(200, {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-cache",
        });
        res.end(html);
        return;
    }

    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    res.end("Not found");
}

async function startServer(instanceId, category) {
    const entry = {
        clients: new Set(),
        category: validCategories.has(category) ? category : "generative-text",
        server: undefined,
        url: undefined,
    };

    const server = createServer((req, res) => {
        handleRequest(entry, req, res).catch((err) => {
            res.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
            res.end(err instanceof Error ? err.message : "Internal server error");
        });
    });
    entry.server = server;

    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const addr = server.address();
    const port = typeof addr === "object" && addr ? addr.port : 0;
    entry.url = `http://127.0.0.1:${port}/`;
    servers.set(instanceId, entry);
    return entry;
}

await joinSession({
    canvases: [
        createCanvas({
            id: "omlx-dashboard",
            displayName: "oMLX Benchmark Dashboard",
            description: "Interactive multi-modal benchmark leaderboard and dashboard for oMLX models.",
            inputSchema: {
                type: "object",
                properties: {
                    category: {
                        type: "string",
                        enum: ["generative-text", "ocr", "decision", "image-generation", "voice"],
                        description: "Initial category tab to display upon opening.",
                    },
                },
                additionalProperties: false,
            },
            actions: [
                {
                    name: "switch_tab",
                    description: "Switch the active category tab on the dashboard.",
                    inputSchema: {
                        type: "object",
                        properties: {
                            category: {
                                type: "string",
                                enum: ["generative-text", "ocr", "decision", "image-generation", "voice"],
                                description: "Category tab to switch to.",
                            },
                        },
                        required: ["category"],
                        additionalProperties: false,
                    },
                    handler: (ctx) => {
                        const entry = getOpenEntry(ctx.instanceId);
                        const category = ctx.input?.category;
                        if (!validCategories.has(category)) {
                            throw new CanvasError("invalid_category", `Unknown category: ${category}`);
                        }
                        entry.category = category;
                        broadcast(entry, "switch_tab", { category });
                        return { activeCategory: entry.category };
                    },
                },
                {
                    name: "reload_data",
                    description: "Reload all benchmark results from CSV datasets in the dashboard.",
                    handler: (ctx) => {
                        const entry = getOpenEntry(ctx.instanceId);
                        broadcast(entry, "reload", {});
                        return { reloaded: true };
                    },
                },
                {
                    name: "get_summary",
                    description: "Get summary statistics across all benchmark categories.",
                    handler: async () => {
                        return await computeSummaryStats();
                    },
                },
            ],
            open: async (ctx) => {
                let entry = servers.get(ctx.instanceId);
                if (!entry) {
                    entry = await startServer(ctx.instanceId, ctx.input?.category);
                } else if (ctx.input?.category && validCategories.has(ctx.input.category)) {
                    entry.category = ctx.input.category;
                    broadcast(entry, "switch_tab", { category: entry.category });
                }
                return {
                    title: "oMLX Benchmark Dashboard",
                    url: entry.url,
                };
            },
            onClose: async (ctx) => {
                const entry = servers.get(ctx.instanceId);
                if (entry) {
                    servers.delete(ctx.instanceId);
                    if (entry.server) {
                        await new Promise((resolve) => entry.server.close(resolve));
                    }
                }
            },
        }),
    ],
});
