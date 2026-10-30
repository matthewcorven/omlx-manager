#!/usr/bin/env python3
"""
scripts/tests/test_record_model_result.py

Automated unit tests for scripts/record_model_result.py.
Verifies schema validation, add, update, CSV/MD sync, and failure modes.
"""

import csv
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import record_model_result as rmr


class TestRecordModelResult(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary test directory
        self.test_dir = tempfile.mkdtemp()
        self.orig_schemas = {}
        # Patch SCHEMAS paths to use temp directory
        for model_type, spec in rmr.SCHEMAS.items():
            self.orig_schemas[model_type] = {
                "csv_file": spec["csv_file"],
                "md_file": spec["md_file"]
            }
            spec["csv_file"] = Path(self.test_dir) / f"{model_type}.csv"
            spec["md_file"] = Path(self.test_dir) / f"{model_type}.md"
            # Initialize empty templates
            rmr.write_csv_and_markdown(model_type, [])

    def tearDown(self):
        # Restore schemas
        for model_type, paths in self.orig_schemas.items():
            rmr.SCHEMAS[model_type]["csv_file"] = paths["csv_file"]
            rmr.SCHEMAS[model_type]["md_file"] = paths["md_file"]
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_text_add_and_sync(self):
        sample_text = {
            "Model": "TestOrg/TestModel-27B",
            "Quant": "oQ4e",
            "Params": "dense 27.8B",
            "Download Size": "15.8 GiB",
            "Resident Size": "16.6 GiB",
            "Baseline TTFT (ms)": 230.5,
            "Baseline Decode (tps)": 75.2,
            "Final TTFT (ms)": 245.0,
            "Final Decode (tps)": 62.1,
            "Final Settings": "ctx 32768, MTP depth 6, thinking off",
            "Quality Pass Rate": "3/3 pass",
            "Notes": "Baseline on quiet machine | Final with load"
        }
        rmr.add_result("generative-text", sample_text)

        # Verify CSV
        csv_path = rmr.SCHEMAS["generative-text"]["csv_file"]
        headers, rows = rmr.read_csv_data(csv_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Model"], "TestOrg/TestModel-27B")
        self.assertEqual(rows[0]["Baseline TTFT (ms)"], "230.5")

        # Verify Markdown
        md_path = rmr.SCHEMAS["generative-text"]["md_file"]
        self.assertTrue(md_path.exists())
        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()
        self.assertIn("TestOrg/TestModel-27B", md_text)
        # Verify pipe in Notes was escaped
        self.assertIn("quiet machine \\| Final with load", md_text)

        # Verify full sync
        self.assertTrue(rmr.validate_all_results())

    def test_add_duplicate_rejected(self):
        sample = {
            "Model": "TestOrg/TestModel-27B",
            "Quant": "oQ4e",
            "Params": "dense 27.8B",
            "Download Size": "15.8 GiB",
            "Resident Size": "16.6 GiB",
            "Baseline TTFT (ms)": 200,
            "Baseline Decode (tps)": 50,
            "Final TTFT (ms)": 210,
            "Final Decode (tps)": 55,
            "Final Settings": "thinking off",
            "Quality Pass Rate": "3/3 pass",
            "Notes": ""
        }
        rmr.add_result("generative-text", sample)
        with self.assertRaises(ValueError) as ctx:
            rmr.add_result("generative-text", sample)
        self.assertIn("already exists", str(ctx.exception))

    def test_update_existing_result(self):
        sample = {
            "Model": "TestOrg/TestModel-27B",
            "Quant": "oQ4e",
            "Params": "dense 27.8B",
            "Download Size": "15.8 GiB",
            "Resident Size": "16.6 GiB",
            "Baseline TTFT (ms)": 200,
            "Baseline Decode (tps)": 50,
            "Final TTFT (ms)": 210,
            "Final Decode (tps)": 55,
            "Final Settings": "thinking off",
            "Quality Pass Rate": "3/3 pass",
            "Notes": "Initial"
        }
        rmr.add_result("generative-text", sample)

        rmr.update_result("generative-text", "TestOrg/TestModel-27B", {
            "Final Decode (tps)": 65.5,
            "Notes": "Updated notes"
        })

        headers, rows = rmr.read_csv_data(rmr.SCHEMAS["generative-text"]["csv_file"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Final Decode (tps)"], "65.5")
        self.assertEqual(rows[0]["Notes"], "Updated notes")

    def test_ocr_validation_and_add(self):
        sample_ocr = {
            "Model": "mlx-community/Unlimited-OCR-2-8bit",
            "Quant": "8bit",
            "Checkpoint/Package": "mlx-vlm 0.7.11 DASH",
            "Resident Size": "4.8 GB",
            "CER (Character Error Rate)": 0.0012,
            "WER (Word Error Rate)": "N/A",
            "Avg Page Latency (s)": 1.13,
            "Max Tokens": 8192,
            "Quality/Status": "PASS - fixed, scored",
            "Notes": "12-page synthetic corpus"
        }
        rmr.add_result("ocr", sample_ocr)
        self.assertTrue(rmr.validate_all_results())

    def test_ocr_invalid_cer(self):
        bad_ocr = {
            "Model": "bad-ocr",
            "Quant": "8bit",
            "Checkpoint/Package": "v1",
            "Resident Size": "2 GB",
            "CER (Character Error Rate)": 1.5,  # Invalid: > 1.0
            "WER (Word Error Rate)": 0.2,
            "Avg Page Latency (s)": 1.0,
            "Max Tokens": 1024,
            "Quality/Status": "PASS",
            "Notes": ""
        }
        with self.assertRaises(ValueError):
            rmr.add_result("ocr", bad_ocr)

    def test_decision_validation_and_add(self):
        sample_decision = {
            "Model": "vllm-sr/d3-flash",
            "Quant": "native",
            "Params": "16.8 GB",
            "Resident Size": "16.8 GB",
            "Gate 1 (Accuracy)": 0.943,
            "Gate 2 (ECE / Calibration)": 0.0802,
            "Gate 3 (Log Loss)": 0.120,
            "Gate 4 (Media Score)": "0.955 (Image)",
            "Mean TTFT": "153.4 ms",
            "Samples": 39,
            "Notes": "PASS - best quality"
        }
        rmr.add_result("decision", sample_decision)
        self.assertTrue(rmr.validate_all_results())

    def test_image_generation_validation_and_add(self):
        sample_img = {
            "Model": "FLUX.1-schnell-4bit",
            "Quant": "4bit",
            "Steps": 4,
            "Resolution": "1024x1024",
            "TTFT/Step Latency": "45.0 ms/step",
            "Total Latency": "1.80 s",
            "VRAM/Resident": "9.4 GB",
            "Quality/CLIP": "0.324",
            "Notes": "Euler scheduler"
        }
        rmr.add_result("image-generation", sample_img)
        self.assertTrue(rmr.validate_all_results())

    def test_missing_mandatory_field(self):
        incomplete = {
            "Model": "TestModel",
            "Quant": "4bit"
            # Missing other mandatory columns
        }
        with self.assertRaises(ValueError) as ctx:
            rmr.add_result("generative-text", incomplete)
        self.assertIn("Missing mandatory", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
