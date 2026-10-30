# Standardized OCR & Non-LLM Model Evaluation Methodology

**Status:** Official Specification & Audit Report  
**Date:** October 2024  
**Applies To:** Vision-to-Markup / OCR Models (`mlx-community/Unlimited-OCR-2-8bit`, future VLM candidates) and Non-LLM Cross-Encoders (`jinaai/jina-reranker-v3.5-mlx`).

---

## 1. Overview & Evaluation Principles

Unlike autoregressive generative text models, OCR and document-parsing vision-language models (VLMs) cannot be evaluated purely on decode throughput. On `Unlimited-OCR-2-8bit`, token generation speed (~230 tok/s) is dominated by prefill latency and image tiling during dynamic preprocessing. 

The primary evaluation dimensions are:
1. **Accuracy:** Text transcription fidelity (CER, WER) and spatial bounding-box alignment (IoU).
2. **Layout & Structural Integrity:** Block recognition precision, recall, and reading order correlation ($\tau$).
3. **Latency:** Per-page end-to-end wall-clock latency across diverse document layouts.
4. **Residency & Memory Footprint:** VRAM / unified memory footprint during active inference.

---

## 2. Standardized Ground-Truth Corpus

To eliminate non-reproducible manual labelling variances, the standardized evaluation suite utilizes `scripts/ocr_corpus.py`. The corpus generates 12 deterministic test pages rendered via PIL at 1024×1024 resolution. Ground truth blocks and bounding boxes are logged in the model's native 0–1000 normalized coordinate space: `<BLOCK>label[x0, y0, x1, y1]<FORK>text`.

| Page ID | Document Format / Test Condition | Target Verification |
|---|---|---|
| `clean` | Standard clean printed text | Baseline transcription floor |
| `dense` | High-density multi-paragraph text | Spatial separation under tight line leading |
| `table` | Multi-column, multi-row financial table | Tabular layout parsing and delimiter alignment |
| `twocol` | Split two-column magazine layout | Reading order across vertical columns |
| `small` | 11px small typography | Sub-pixel character recognition limits |
| `lowcontrast` | Light gray ink on tinted paper | Optical sensitivity under poor contrast |
| `rotated` | 3° skewed page rotation | Angular compensation and bounding box fidelity |
| `mixed` | Combined header, text, table, footer | Multi-element composition parsing |
| `mixedcase` | Glyph confusion set (`O0Il1\|S5B8`) | Disambiguation of visually ambiguous glyphs |
| `handwriting` | Italic serif font styling | Simulated script/cursive baseline recognition |
| `noise` | 24,000 salt-and-pepper noise pixels | Resilience against optical scan artifacts |
| `multipage` | Overflowing continuous multi-page | Multi-page separator tags and cross-page labels |

---

## 3. Evaluation Harness & Metrics Formulation

The evaluation runner `scripts/ocr_eval.py` assesses responses using the following standardized metrics:

- **Character Error Rate (CER):** Levenshtein distance between predicted text and ground truth, normalized by ground truth length:
  $$\text{CER} = \frac{S + D + I}{N}$$
- **Word Error Rate (WER):** Word-level edit distance normalized by total reference words.
- **Intersection over Union (IoU):** Overlap ratio between predicted and ground truth bounding boxes in $[0, 1000]^2$ coordinate space.
- **Block Precision & Recall:** Proportion of correctly detected document blocks matched at $\text{IoU} \ge 0.5$.
- **Reading Order Kendall's Tau ($\tau$):** Rank correlation measuring whether the sequence of emitted text blocks matches the human reading order.
- **Determinism:** Bit-exact reproducibility across multiple inference runs at `temperature: 0`.

---

## 4. The Three Mandatory Quality Gates

Before any metric is recorded, the output must pass three automated gates:

1. **Error Gate:** The request must return HTTP 200 with complete JSON output, free of attention cache crashes or kernel faults.
2. **Degenerate Output Gate:** The output must not degenerate into repetitive token loops (e.g., `11. 11. 11. ...` emitted for 8192 tokens with `finish_reason: stop`). The output must contain valid `<BLOCK>` tags and meaningful token distributions.
3. **Truncation Gate:** The response must complete with `finish_reason: stop`. Responses terminating with `finish_reason: length` indicate insufficient `max_tokens` budget.

---

## 5. Benchmark Results & Configuration Sweep

### Standardized Model: `mlx-community/Unlimited-OCR-2-8bit`
- **Architecture:** DASH Sparse Attention Vision-Language Model
- **Resident Size:** 2.15 GiB
- **Input Resolution:** 1024×1024 (multi-page parsing, `max_crops: 16`)
- **Mean Wall-Clock Latency:** 1133.5 ms per page
- **Mean CER:** 0.0012 (0.12%)
- **Mean WER:** 0.0019 (0.19%)
- **Precision / Recall / Tau:** 1.000 / 1.000 / 1.000
- **Mean IoU:** 0.877
- **Quality Gate:** 3/3 Pass (Deterministic across runs)

### Hyperparameter Findings & Incompatibilities
1. **TurboQuant KV Cache Incompatibility:** Enabling `turboquant_kv_enabled: true` throws an unrecoverable exception: `'TurboQuantKVCache' object has no attribute 'dash_state'`. The DASH attention sparse router requires full-precision state caching; KV quantization is strictly unsupported for this architecture.
2. **Tile Preprocessing (`max_crops`):** Reducing `max_crops` from 16 to 4 reduces latency on simple pages but triggers total degeneracy on dense high-resolution pages (>2048px), causing infinite loop repetition of dummy tokens. `max_crops: 16` is retained as the production configuration.

### Non-LLM Companion Model: `jinaai/jina-reranker-v3.5-mlx`
- Non-LLM models that do not output text generation or bounding boxes (such as cross-encoder rerankers) are benchmarked on inference latency and memory footprint:
  - **Architecture:** BERT-based Cross-Encoder Reranker
  - **Resident Size:** 1.20 GiB
  - **Mean Latency:** 12.4 ms per query-document pair
  - **CER / WER:** Recorded as 0.0 / N/A with clear status notes.

---

## 6. Centralized Storage & Synchronization

All verified OCR and non-LLM benchmark metrics are committed to:
- `results/ocr.csv`
- `results/ocr.md`
Validated atomically via `scripts/record_model_result.py --validate-all`.
