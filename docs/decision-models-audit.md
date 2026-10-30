# Decision Models Comprehensive Audit & Multi-Modal Verification Report

**Status:** Completed & Synchronized  
**Date:** October 2024  
**Applies To:** All 8 Decision Model Candidates (`d3-edge`, `d3-lite`, `d3-nano`, `d3-mini`, `d3-flash`, `clef-flash-oQ4e`, `clef-oQ4e`, `openjev`) and the Reference Chat Baseline (`Qwen3.8-27B-oQ4e-mtp`).

---

## 1. Executive Summary

Decision models evaluated through oMLX's `/v1/systemone` and `/v1/decisions` endpoints output probability distributions over typed option sets rather than autoregressive text tokens. This audit verifies performance across a unified 4-gate evaluation harness:
- **Gate 1:** Accuracy (argmax alignment with ground truth).
- **Gate 2:** Expected Calibration Error (ECE / probability calibration across 10 confidence bins).
- **Gate 3:** Log Loss (penalizing confident misclassifications).
- **Gate 4:** Multi-Modal Media Score (image perception and video temporal motion tracking).

All 8 candidates and the chat baseline have been audited and updated in the centralized repository schema (`results/decision.csv` and `results/decision.md`).

---

## 2. Four-Gate Unified Results Leaderboard

| Model | Size | Gate 1 (Acc) | Gate 2 (ECE) | Gate 3 (Log Loss) | Gate 4 (Image / Video Score) | Mean TTFT | Status & Deployment Recommendation |
|---|---|---|---|---|---|---|---|
| `vllm-sr/d3-flash` | 16.8 GB | **0.9429** | **0.0802** | **0.1200** | 0.955 (Image) / 1.000 (Video) | 153.4 ms | **PASS** — Best overall quality; honest on ambiguous items (ambig conf 0.652); near-zero video Brier (0.0003). |
| `vllm-sr/d3-mini` | 9.1 GB | **0.9143** | **0.0766** | **0.1500** | 0.955 (Image) / 1.000 (Video) | 86.3 ms | **PASS** — Optimal size-to-accuracy balance; zero video error (0.0000 Brier). |
| `Jundot/clef-flash-oQ4e` | 6.6 GB | **0.8571** | **0.0901** | **0.2970** | 1.000 (Image) / Reject (Video) | 231.7 ms | **PASS** — Solid image accuracy; beats chat baseline Brier; video unsupported. |
| `vllm-sr/d3-nano` | 4.5 GB | **0.8286** | **0.1315** | **0.3562** | 0.955 (Image) / 1.000 (Video) | 37.9 ms | **PASS** — Leading lightweight d3 model under 5 GB; perfect video tracking (0.0000 Brier). |
| `vllm-sr/d3-edge` | 1.2 GB | **0.7714** | **0.1156** | **0.3763** | 0.773 (Image) / Degenerate (Video) | **12.9 ms** | **PASS (Text Only)** — Fastest latency (12.9 ms); failed vision/video gates. |
| `Jundot/clef-oQ4e` | 17.5 GB | **0.9429** | **0.0819** | **0.1711** | **1.000 (Image)** / Reject (Video) | 794.1 ms | **FAIL** — Dominated by `d3-flash` on text latency/size; top image precision. |
| `openjev/openjev` | 54.7 GB | **0.8571** | **0.0998** | **0.3412** | 0.955 (Image) / Reject (Video) | 467.0 ms | **FAIL** — No quality gain over 27B baseline despite 54.7 GB footprint. |
| `vllm-sr/d3-lite` | 1.7 GB | **0.7143** | **0.1240** | **0.3906** | 0.818 (Image) / 1.000 (Video) | 22.2 ms | **FAIL** — Strictly dominated across all text metrics by `d3-edge`. |
| `Qwen3.8-27B-oQ4e-mtp` | 16.6 GB | 0.8571 | 0.0496 | 0.2766 | 1.000 (Image) / Unsupported (Video) | 536.0 ms | *Reference Baseline* — Standard chat model baseline on `/v1/systemone`. |

---

## 3. Analysis of Critical Findings & Gate Anomalies

### 1. Motion Blindness & Degenerate Gate Failure (`d3-edge`)
- In Gate 4 video evaluation, `vllm-sr/d3-edge` achieved 0.812 accuracy, but closer inspection revealed a **Degenerate Gate Failure**: it answered "false" to all motion questions at 0.80–0.97 confidence.
- It lacks temporal visual feature integration and is completely blind to motion. It is unsafe for multi-modal tasks.

### 2. Multi-Modal Modality Rejection (Clef & OpenJev)
- Both `Jundot/clef-oQ4e`, `Jundot/clef-flash-oQ4e`, and `openjev/openjev` reject video payload inputs outright with HTTP 400.
- Conversely, `Jundot/clef-oQ4e` achieves the lowest Brier score across all models on still images (**0.0006 Brier, 1.000 accuracy**), outperforming even the 27B chat baseline.

### 3. Ambiguity Honest Scoring
- On undecidable / ambiguous items (`img-ambiguous` and text undecidables), `vllm-sr/d3-flash` exhibited the most honest confidence estimation (**0.652**), whereas overconfident models scored 0.92–0.99.

### 4. Non-Exercisable Candidates (LiquidAI d1 family)
- `LiquidAI/d1-2B`, `LiquidAI/d1-Omni-2B`, and `LiquidAI/d1-2B-MLX-8bit` require engine changes introduced in PR #4937 that are absent in oMLX 0.7.3rc1. They remain recorded as blocked pending upstream release integration.

---

## 4. Verification & Audit Sign-Off

All metrics have been verified against:
- `scripts/decision_corpus.py` (39 items)
- `scripts/decision_media_corpus.py` (25 image items, 16 video items)
- Atomic synchronization confirmed between `results/decision.csv` and `results/decision.md`.
