# Unified Model Results Schema Specification

This document defines the canonical schemas, field definitions, validation constraints, and formatting invariants for all model benchmark results recorded in this repository.

All results must reside in centralized sibling CSV and Markdown files in `results/`.
**Project Invariant:** All entries and updates to these files must be recorded strictly via `scripts/record_model_result.py` to ensure schema enforcement and continuous synchronization between CSV and Markdown formats.

---

## Architecture & Synchronization Invariant

1. **Sibling Files**: Each model family has a pair of files in `results/`:
   - `results/<model_type>.csv` — Machine-readable, comma-delimited record.
   - `results/<model_type>.md` — Human-readable GitHub-flavored Markdown table.
2. **Atomic Synchronization**: Any addition or modification must update both files simultaneously. Manual edits to Markdown or CSV tables without the CLI tool are prohibited.
3. **Escaping & Formatting**:
   - In CSV, fields containing commas, quotes, or semicolons must be enclosed in standard RFC 4180 double quotes (`"..."`).
   - In Markdown, pipes (`|`) must be escaped (`\|`) or omitted from field values.
   - Headers and columns must strictly match between the CSV and sibling Markdown files.

---

## 1. Generative Text Models

Target Files:
- `results/generative-text.csv`
- `results/generative-text.md`

### Column Specification

| Column Header | Type | Units / Format | Nullable | Description & Constraints |
|---|---|---|---|---|
| `Model` | string | Identifier | No | Canonical Hugging Face or registry model ID (e.g., `Jundot/Qwen3.8-27B-oQ4e-mtp`). |
| `Quant` | string | Category | No | Quantization format (e.g., `oQ4e`, `oQ8e`, `FP16`, `BF16`, `4-bit`). |
| `Params` | string | Parameter count | No | Total and active parameters (e.g., `dense 27.8B`, `MoE 35.1B / ~3B active`). |
| `Download Size` | string | Size with unit | No | Disk footprint (e.g., `15.81 GiB`, `21.1 GB`). |
| `Resident Size` | string | Size with unit | No | VRAM / Unified memory footprint when loaded (e.g., `16.60 GiB`, `19.96 GB`). |
| `Baseline TTFT (ms)` | float | Milliseconds | No | Time to First Token under default configuration (>= 0.0). |
| `Baseline Decode (tps)`| float | Tokens / sec | No | Decode throughput under default configuration (> 0.0). |
| `Final TTFT (ms)` | float | Milliseconds | No | Time to First Token after optimal tuning (>= 0.0). |
| `Final Decode (tps)` | float | Tokens / sec | No | Decode throughput after optimal tuning (> 0.0). |
| `Final Settings` | string | Text summary | No | Key tuned flags (e.g., context window, MTP depth, KV quant, samplers, thinking state). |
| `Quality Pass Rate` | string | Ratio / Status | No | Verification pass count (e.g., `3/3 pass`, `Pass`). |
| `Notes` | string | Free-form text | Yes | Relevant tuning insights, caveats, machine load notes, or references to model directories. |

### Validation Rules
- `Baseline TTFT (ms)` and `Final TTFT (ms)` must be non-negative numeric floats.
- `Baseline Decode (tps)` and `Final Decode (tps)` must be positive numeric floats.
- Thinking mode behavior must be documented in `Final Settings` (e.g., `thinking off` or `thinking budget`).

---

## 2. OCR Models

Target Files:
- `results/ocr.csv`
- `results/ocr.md`

### Column Specification

| Column Header | Type | Units / Format | Nullable | Description & Constraints |
|---|---|---|---|---|
| `Model` | string | Identifier | No | Canonical model ID or name (e.g., `mlx-community/Unlimited-OCR-2-8bit`). |
| `Quant` | string | Category | No | Quantization format (e.g., `8bit`, `4bit`, `FP16`). |
| `Checkpoint/Package` | string | Version / Source | No | Specific backend library, commit, or package version (e.g., `mlx-vlm 0.7.11 DASH`). |
| `Resident Size` | string | Size with unit | No | Resident memory consumption during document inference (e.g., `4.8 GB`). |
| `CER (Character Error Rate)` | float | Ratio [0.0 - 1.0] | No | Mean character error rate against ground truth corpus. |
| `WER (Word Error Rate)` | float | Ratio [0.0 - 1.0] | No | Mean word error rate against ground truth corpus (or N/A if unsupported). |
| `Avg Page Latency (s)`| float | Seconds | No | Mean wall-clock time per document page (> 0.0). |
| `Max Tokens` | integer | Tokens count | No | Maximum token limit configured (>= 512). |
| `Quality/Status` | string | Status enum | No | Verification status (`PASS`, `FAIL`, `DEGRADED`, `PASS - fixed`). |
| `Notes` | string | Free-form text | Yes | Corpus details (e.g., 12-page synthetic corpus, crop settings, layout parsing). |

### Validation Rules
- `CER` must be a float between `0.0` and `1.0`.
- `WER` must be a float between `0.0` and `1.0` or `N/A`.
- `Avg Page Latency (s)` must be a positive float.
- `Max Tokens` must be a positive integer.

---

## 3. Decision Models

Target Files:
- `results/decision.csv`
- `results/decision.md`

### Column Specification

| Column Header | Type | Units / Format | Nullable | Description & Constraints |
|---|---|---|---|---|
| `Model` | string | Identifier | No | Canonical model identifier (e.g., `vllm-sr/d3-flash`, `Jundot/clef-oQ4e`). |
| `Quant` | string | Category | No | Quantization format (e.g., `oQ4e`, `BF16`, `native`). |
| `Params` | string | Parameter count | No | Active or total parameter size (e.g., `16.8 GB`, `0.5B`, `8B`). |
| `Resident Size` | string | Size with unit | No | Resident memory during evaluation (e.g., `16.8 GB`, `1.2 GB`). |
| `Gate 1 (Accuracy)` | float | Ratio [0.0 - 1.0] | No | Overall classification accuracy on standard 39-item corpus. |
| `Gate 2 (ECE / Calibration)` | float | Ratio [0.0 - 1.0] | No | Expected Calibration Error (lower is better; e.g., `0.0802`). |
| `Gate 3 (Log Loss)` | float | Score (>= 0.0) | No | Cross-entropy / logarithmic loss on predicted probabilities. |
| `Gate 4 (Media Score)` | string | Score / Status | No | Image/Video multi-modal evaluation score or status (e.g., `0.955 (Image)` or `N/A (text-only)`). |
| `Mean TTFT` | string | Latency with unit| No | Median or mean time to evaluate decision token (e.g., `153.4 ms`). |
| `Samples` | integer | Sample count | No | Number of evaluation items evaluated (e.g., `39`, `35`). |
| `Notes` | string | Free-form text | Yes | Gate status (`0 gate failures`, `PASS - best quality`, `dominated by d3-edge`). |

### Validation Rules
- `Gate 1 (Accuracy)` and `Gate 2 (ECE / Calibration)` must be floats between `0.0` and `1.0`.
- `Gate 3 (Log Loss)` must be a non-negative float.
- `Samples` must be a positive integer.

---

## 4. Image Generation Models (Extensible Specification)

Target Files:
- `results/image-generation.csv`
- `results/image-generation.md`

### Column Specification

| Column Header | Type | Units / Format | Nullable | Description & Constraints |
|---|---|---|---|---|
| `Model` | string | Identifier | No | Canonical image generation model (e.g., `FLUX.1-schnell-4bit`, `SDXL-Turbo`). |
| `Quant` | string | Category | No | Quantization level (e.g., `4bit`, `8bit`, `FP16`). |
| `Steps` | integer | Step count | No | Default or benchmark inference steps (e.g., `4`, `20`, `30`). |
| `Resolution` | string | Width x Height | No | Benchmark image resolution (e.g., `512x512`, `1024x1024`). |
| `TTFT/Step Latency` | string | Latency / step | No | Time per denoising step or first step latency (e.g., `45.2 ms/step`). |
| `Total Latency` | string | Total time | No | End-to-end image generation time (e.g., `1.82 s`, `1820 ms`). |
| `VRAM/Resident` | string | Size with unit | No | Peak unified memory / VRAM consumption during sampling (e.g., `9.4 GB`). |
| `Quality/CLIP` | string | Score / Metric | No | Standard CLIP score or perceptual quality metric (e.g., `0.324 CLIP`, `N/A`). |
| `Notes` | string | Free-form text | Yes | Scheduler used (e.g., DPMSolver, Euler), prompt details, or compilation notes. |

### Extensibility Provisions
As new multi-modal image architectures are onboarded (e.g., Diffusion Transformers, Rectified Flow models, Autoregressive image generators), additional optional columns may be appended using the `--extend-schema` hook in `scripts/record_model_result.py`:
- `Guidance Scale` (float)
- `Scheduler` (string)
- `Throughput (images/min)` (float)

---

## 5. Conversational Voice Models

Target Files:
- `results/voice.csv`
- `results/voice.md`

Conversational voice models are served over the oMLX `/v1/realtime` WebSocket
(`api/audio_routes.py`), not the chat completions path. They have no decode loop
in the text sense: the model consumes 24 kHz PCM16 audio and emits audio slots,
so throughput is expressed as a real-time factor rather than tokens/second.

### Column Specification

| Column Header | Type | Units / Format | Nullable | Description & Constraints |
|---|---|---|---|---|
| `Model` | string | Identifier | No | Canonical voice model (e.g., `LiquidAI/LFM3-Omni-2B-MLX-4bit`). |
| `Quant` | string | Category | No | Quantization level (e.g., `4bit`, `8bit`, `FP16`). |
| `Params` | string | Architecture summary | No | Parameter count and architecture (e.g., `dense 2.2B omni`, `MoE 30B-A3B omni`). |
| `Resident Size` | string | Size with unit | No | Resident unified-memory footprint at load (e.g., `1.92 GB`). |
| `Turn TTFT (ms)` | float | Milliseconds | No | Send-to-`response.created` latency for one committed turn. Must be `>= 0`. |
| `First Audio Latency (ms)` | float | Milliseconds | No | Send-to-first-`response.output_audio.delta` latency. Must be `>= 0`. |
| `Reply Audio (ms)` | float | Milliseconds | No | Duration of the generated reply audio. Must be `> 0`. |
| `Speech Real-Time Factor` | float | Ratio (x) | No | Reply audio duration / wall-clock generation time. `> 1` is faster than real time. Must be `> 0`. |
| `Transcript WER` | float | Ratio `0.0`–`1.0` | Yes | Word error rate of a TTS → realtime → ASR round trip. Use `N/A` when not measured. |
| `Voices/Languages` | string | Free-form text | No | Built-in realtime voices, TTS voices, and language coverage. |
| `Quality/Status` | string | Status label | No | Gate outcome, e.g. `PASS - 3/3 turns completed`, `FAIL - turn timeout`. |
| `Notes` | string | Free-form text | Yes | Run count, prompt audio length, and interpretation of the metrics. |

### Validation Rules

- `Turn TTFT (ms)` and `First Audio Latency (ms)` must be non-negative floats.
- `Reply Audio (ms)` must be a positive float.
- `Speech Real-Time Factor` must be a positive float.
- `Transcript WER` must be a float in `[0.0, 1.0]` or the literal `N/A`.
- `Notes` must remain single-line: the dashboard's CSV parser splits on newlines
  before applying quote handling, so embedded newlines break rendering.

### Measurement Contract

Voice numbers are produced by `scripts/voice_eval.py`, which drives a real
`/v1/realtime` session: `session.update` → 40 ms `input_audio_buffer.append`
frames → `input_audio_buffer.commit` → `response.create`. Server-side turn
detection is rejected by oMLX, so every turn is explicitly committed. Use
`--runs 3` and the same prompt audio for every comparison, exactly as with the
text modality.
