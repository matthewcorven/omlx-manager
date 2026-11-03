# oMLX Benchmark Dashboard Canvas Extension

A GitHub Copilot canvas extension providing an interactive, live leaderboard and benchmark dashboard for oMLX models directly inside the Copilot side panel.

## Features

- **Live Leaderboard:** Displays performance metrics, memory footprints, and quality gates across Generative Text, OCR, Decision Models, and Image Generation.
- **Embedded Loopback Server:** Serves the responsive dashboard UI from `dashboard/index.html` and streams live CSV datasets from `results/`.
- **Canvas Actions:**
  - `switch_tab`: Programmatically switch the active category view (`generative-text`, `ocr`, `decision`, `image-generation`, `voice`).
  - `reload_data`: Trigger an instant refresh of live CSV data without restarting the canvas.
  - `get_summary`: Return real-time summary statistics of audited models across all categories.

## Canvas ID

- **Canvas ID:** `omlx-dashboard`
- **Extension ID:** `project:omlx-dashboard`

## Usage

Agents or host clients can open the canvas using `open_canvas`:

```json
{
  "canvasId": "omlx-dashboard",
  "instanceId": "omlx-dashboard-1",
  "input": {
    "category": "generative-text"
  }
}
```

To invoke actions:

```json
{
  "instanceId": "omlx-dashboard-1",
  "actionName": "switch_tab",
  "input": {
    "category": "decision"
  }
}
```
