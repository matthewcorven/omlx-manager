#!/usr/bin/env python3
"""
scripts/migrate_historical_results.py

Migrate historical benchmark data into centralized CSV and sibling Markdown files
via record_model_result.py to preserve project invariants.
"""

import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import record_model_result as rmr

TEXT_MODELS = [
    {
        "Model": "Jundot/Qwen3.8-27B-oQ4e-mtp",
        "Quant": "oQ4e",
        "Params": "dense 27.8B",
        "Download Size": "15.81 GiB",
        "Resident Size": "16.60 GiB",
        "Baseline TTFT (ms)": 233.6,
        "Baseline Decode (tps)": 78.33,
        "Final TTFT (ms)": 252.0,
        "Final Decode (tps)": 59.65,
        "Final Settings": "ctx 32768, MTP on depth 6, KV 4-bit + skip_last, temp 0.2 / top_p 0.95 / top_k 20, thinking off",
        "Quality Pass Rate": "3/3 pass",
        "Notes": "Baseline on quiet machine; final measured during active downloads (machine load, not regression)"
    },
    {
        "Model": "Jundot/Ornith-1.0-35B-oQ4e",
        "Quant": "oQ4e",
        "Params": "MoE 35B",
        "Download Size": "21.1 GB",
        "Resident Size": "19.96 GB",
        "Baseline TTFT (ms)": 52.0,
        "Baseline Decode (tps)": 146.72,
        "Final TTFT (ms)": 48.0,
        "Final Decode (tps)": 146.34,
        "Final Settings": "ctx native, all spec/quant/offload off, temp 1.0 / top_p 0.95 / top_k 20, thinking off",
        "Quality Pass Rate": "3/3 pass",
        "Notes": "Default config already near optimal. Thinking off required for answer generation"
    },
    {
        "Model": "Jundot/flint-oQ4e",
        "Quant": "oQ4e",
        "Params": "MoE 2.5B active",
        "Download Size": "22 GB",
        "Resident Size": "22.84 GB",
        "Baseline TTFT (ms)": 251.0,
        "Baseline Decode (tps)": 114.6,
        "Final TTFT (ms)": 252.0,
        "Final Decode (tps)": 113.23,
        "Final Settings": "ctx native, KV off, no MTP/draft head, temp 1.0 / top_p 0.95 / top_k 20, activation_fp16_enabled: false",
        "Quality Pass Rate": "3/3 pass",
        "Notes": "Streams ~250 reasoning tokens first when thinking enabled; thinking off eliminates 3.8-14.8s TTFC hide"
    },
    {
        "Model": "Jundot/gemma-4-31B-it-oQ4e-mtp",
        "Quant": "oQ4e",
        "Params": "dense 30.7B",
        "Download Size": "18.60 GiB",
        "Resident Size": "18.88 GiB",
        "Baseline TTFT (ms)": 267.7,
        "Baseline Decode (tps)": 56.10,
        "Final TTFT (ms)": 297.0,
        "Final Decode (tps)": 40.06,
        "Final Settings": "ctx native, MTP on adaptive depth, KV off, DFlash off, temp 0.2 / top_p 0.95 / top_k 64, force_sampling: false, thinking off",
        "Quality Pass Rate": "3/3 pass",
        "Notes": "Tuned by defaults; fixed depth loses 21-36% decode; thinking off avoids 48x TTFC delay"
    },
    {
        "Model": "Jundot/gemma-4-26B-A4B-it-oQ8e-mtp",
        "Quant": "oQ8e",
        "Params": "MoE 26.23B / 4.82B active",
        "Download Size": "26.86 GiB",
        "Resident Size": "26.93 GiB",
        "Baseline TTFT (ms)": 116.0,
        "Baseline Decode (tps)": 113.18,
        "Final TTFT (ms)": 117.3,
        "Final Decode (tps)": 118.6,
        "Final Settings": "ctx native, MTP on fixed depth 4, KV off, DFlash off, temp 0.2 / top_p 0.95 / top_k 64, force_sampling: false, thinking off",
        "Quality Pass Rate": "3/3 pass",
        "Notes": "MTP fixed depth 4 yields +4% decode; thinking off eliminates 84x TTFC delay"
    },
    {
        "Model": "Jundot/Qwen3.6-35B-A3B-oQ8e-mtp",
        "Quant": "oQ8e",
        "Params": "MoE 35.1B / ~3B active",
        "Download Size": "36 GiB",
        "Resident Size": "37.75 GiB",
        "Baseline TTFT (ms)": 74.2,
        "Baseline Decode (tps)": 161.22,
        "Final TTFT (ms)": 77.4,
        "Final Decode (tps)": 183.89,
        "Final Settings": "ctx native, MTP on depth 4, KV off, ANE prefill off, temp 0.6 / top_p 0.95 / top_k 20, force_sampling: false, thinking off",
        "Quality Pass Rate": "3/3 pass",
        "Notes": "MTP depth 4; ANE prefill rejected (neutral on short, worse on cold prefill)"
    },
    {
        "Model": "Jundot/Qwen3.8-Flash-Next-oQ4e-mtp",
        "Quant": "oQ4e",
        "Params": "MoE 125B / ~6B active",
        "Download Size": "105.06 GiB",
        "Resident Size": "73.77 GiB",
        "Baseline TTFT (ms)": 115.0,
        "Baseline Decode (tps)": 86.50,
        "Final TTFT (ms)": 123.1,
        "Final Decode (tps)": 96.56,
        "Final Settings": "ctx native, PLE SSD offload on, MoE expert offload off, MTP on adaptive depth, KV off, temp 0.6 / top_p 0.95 / top_k 20, force_sampling: false, thinking off",
        "Quality Pass Rate": "3/3 pass",
        "Notes": "PLE SSD offload active; resident fits under ceiling; thinking off"
    }
]

OCR_MODELS = [
    {
        "Model": "mlx-community/Unlimited-OCR-2-8bit",
        "Quant": "8bit",
        "Checkpoint/Package": "mlx-vlm 0.7.11 DASH",
        "Resident Size": "4.8 GB",
        "CER (Character Error Rate)": 0.0012,
        "WER (Word Error Rate)": "N/A",
        "Avg Page Latency (s)": 1.13,
        "Max Tokens": 8192,
        "Quality/Status": "PASS - fixed, scored",
        "Notes": "12-page synthetic corpus; mean IoU 0.877; reading order perfect"
    },
    {
        "Model": "jinaai/jina-reranker-v3.5-mlx",
        "Quant": "BF16",
        "Checkpoint/Package": "MLX conversion",
        "Resident Size": "1.2 GB",
        "CER (Character Error Rate)": 0.0,
        "WER (Word Error Rate)": "N/A",
        "Avg Page Latency (s)": 0.05,
        "Max Tokens": 512,
        "Quality/Status": "PASS - fixed (reranker)",
        "Notes": "Non-LLM reranker smoke test passed (rank 1 score 0.4715)"
    }
]

DECISION_MODELS = [
    {
        "Model": "vllm-sr/d3-edge",
        "Quant": "native",
        "Params": "1.2 GB",
        "Resident Size": "1.2 GB",
        "Gate 1 (Accuracy)": 0.7714,
        "Gate 2 (ECE / Calibration)": 0.1156,
        "Gate 3 (Log Loss)": 0.3763,
        "Gate 4 (Media Score)": "0.773 (Image) / Degenerate (Video)",
        "Mean TTFT": "12.9 ms",
        "Samples": 39,
        "Notes": "PASS - scored. Blind to video motion (degenerate gate failure on video)"
    },
    {
        "Model": "vllm-sr/d3-lite",
        "Quant": "native",
        "Params": "1.7 GB",
        "Resident Size": "1.7 GB",
        "Gate 1 (Accuracy)": 0.7143,
        "Gate 2 (ECE / Calibration)": 0.1240,
        "Gate 3 (Log Loss)": 0.3906,
        "Gate 4 (Media Score)": "0.818 (Image)",
        "Mean TTFT": "22.2 ms",
        "Samples": 39,
        "Notes": "FAIL - dominated by d3-edge"
    },
    {
        "Model": "vllm-sr/d3-nano",
        "Quant": "native",
        "Params": "4.5 GB",
        "Resident Size": "4.5 GB",
        "Gate 1 (Accuracy)": 0.8286,
        "Gate 2 (ECE / Calibration)": 0.1315,
        "Gate 3 (Log Loss)": 0.3562,
        "Gate 4 (Media Score)": "0.955 (Image)",
        "Mean TTFT": "37.9 ms",
        "Samples": 39,
        "Notes": "PASS - best d3 under 5 GB"
    },
    {
        "Model": "Jundot/clef-flash-oQ4e",
        "Quant": "oQ4e",
        "Params": "6.6 GB",
        "Resident Size": "6.6 GB",
        "Gate 1 (Accuracy)": 0.8571,
        "Gate 2 (ECE / Calibration)": 0.0901,
        "Gate 3 (Log Loss)": 0.2970,
        "Gate 4 (Media Score)": "1.000 (Image) / Reject (Video)",
        "Mean TTFT": "231.7 ms",
        "Samples": 39,
        "Notes": "PASS - beats baseline Brier; rejects video modality"
    },
    {
        "Model": "vllm-sr/d3-mini",
        "Quant": "native",
        "Params": "9.1 GB",
        "Resident Size": "9.1 GB",
        "Gate 1 (Accuracy)": 0.9143,
        "Gate 2 (ECE / Calibration)": 0.0766,
        "Gate 3 (Log Loss)": 0.1500,
        "Gate 4 (Media Score)": "0.955 (Image)",
        "Mean TTFT": "86.3 ms",
        "Samples": 39,
        "Notes": "PASS - best overall performance-to-size"
    },
    {
        "Model": "vllm-sr/d3-flash",
        "Quant": "native",
        "Params": "16.8 GB",
        "Resident Size": "16.8 GB",
        "Gate 1 (Accuracy)": 0.9429,
        "Gate 2 (ECE / Calibration)": 0.0802,
        "Gate 3 (Log Loss)": 0.1200,
        "Gate 4 (Media Score)": "0.955 (Image)",
        "Mean TTFT": "153.4 ms",
        "Samples": 39,
        "Notes": "PASS - best quality; honest on ambiguity (ambig conf 0.652)"
    },
    {
        "Model": "Jundot/clef-oQ4e",
        "Quant": "oQ4e",
        "Params": "17.5 GB",
        "Resident Size": "17.5 GB",
        "Gate 1 (Accuracy)": 0.9429,
        "Gate 2 (ECE / Calibration)": 0.0819,
        "Gate 3 (Log Loss)": 0.1711,
        "Gate 4 (Media Score)": "1.000 (Image) / Reject (Video)",
        "Mean TTFT": "794.1 ms",
        "Samples": 39,
        "Notes": "FAIL - dominated by d3-flash; rejects video modality"
    },
    {
        "Model": "openjev/openjev",
        "Quant": "native",
        "Params": "54.7 GB",
        "Resident Size": "54.7 GB",
        "Gate 1 (Accuracy)": 0.8571,
        "Gate 2 (ECE / Calibration)": 0.0998,
        "Gate 3 (Log Loss)": 0.3412,
        "Gate 4 (Media Score)": "0.955 (Image) / Reject (Video)",
        "Mean TTFT": "467.0 ms",
        "Samples": 39,
        "Notes": "FAIL - no better than chat baseline despite 54.7 GB size"
    },
    {
        "Model": "Jundot/Qwen3.8-27B-oQ4e-mtp (baseline)",
        "Quant": "oQ4e",
        "Params": "dense 27.8B",
        "Resident Size": "16.6 GB",
        "Gate 1 (Accuracy)": 0.8571,
        "Gate 2 (ECE / Calibration)": 0.0496,
        "Gate 3 (Log Loss)": 0.2766,
        "Gate 4 (Media Score)": "1.000 (Image)",
        "Mean TTFT": "536.0 ms",
        "Samples": 39,
        "Notes": "Reference chat baseline on /v1/systemone"
    }
]


def run_migration():
    print("Migrating Generative Text models...")
    for item in TEXT_MODELS:
        rmr.add_result("generative-text", item)

    print("Migrating OCR & Non-LLM models...")
    for item in OCR_MODELS:
        rmr.add_result("ocr", item)

    print("Migrating Decision models...")
    for item in DECISION_MODELS:
        rmr.add_result("decision", item)

    print("Migration finished. Running validation across all files...")
    ok = rmr.validate_all_results()
    if not ok:
        print("[ERROR] Validation failed after migration!")
        sys.exit(1)
    print("[SUCCESS] All historical models migrated and validated successfully.")


if __name__ == "__main__":
    run_migration()
