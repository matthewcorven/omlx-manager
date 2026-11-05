#!/usr/bin/env python3
"""
scripts/tests/test_release_reprofile.py

Tests for .github/skills/omlx-release-reprofile/scripts/release_reprofile.py.

The script talks to a live oMLX server, so these tests pin the pure logic that
has actually been wrong before: version extraction, candidate filtering, and the
verdict thresholds. A regression in any of these silently produces a wrong plan.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".github/skills/omlx-release-reprofile/scripts"))

import release_reprofile as rr  # noqa: E402


class TestVersionExtraction(unittest.TestCase):
    def test_finds_plain_and_rc_versions(self):
        self.assertEqual(rr._extract_versions("Re-profiled on oMLX 0.7.4.dev1."),
                         ["0.7.4.dev1"])
        self.assertEqual(rr._extract_versions("0.7.3rc1 baseline"), ["0.7.3rc1"])
        self.assertEqual(rr._extract_versions("shipped 0.7.3 stable"), ["0.7.3"])

    def test_ignores_unrelated_dependency_versions(self):
        # A real false positive: the OCR row names `mlx-vlm 0.7.11`, which is
        # not an oMLX version. Reporting it as one made every OCR row look
        # stamped against an unknown release.
        text = "mlx-vlm 0.7.11 DASH"
        self.assertEqual(rr._extract_versions(text), [])

    def test_still_finds_omlx_version_next_to_a_dependency(self):
        text = "mlx-vlm 0.7.11 DASH; re-scored on oMLX 0.7.4.dev1"
        self.assertEqual(rr._extract_versions(text), ["0.7.4.dev1"])


class TestCandidateFilter(unittest.TestCase):
    """The filter exists because a naive smallest-size pick chose a 1 GB
    'overlay' repo as the DeepSeek V4.1 build that 'fits' a 128 GB Mac."""

    def test_trusted_whole_model_is_accepted(self):
        self.assertTrue(rr._candidate_ok(
            "Jundot/GLM-5.3-Flash-oQ2e-mtp", {"download_all_size": 110 * 1024**3}))

    def test_overlay_and_adapters_are_rejected(self):
        for rid in ("lued/DeepSeek-V4.1-Flash-overlay",
                    "someone/model-lora",
                    "x/model-gguf"):
            self.assertFalse(rr._candidate_ok(rid, {"download_all_size": 50 * 1024**3}),
                             rid)

    def test_uncensored_and_reap_recuts_are_rejected(self):
        for rid in ("butterf1ying/Qwen3.8-Flash-Next-Uncensored-REAP288-MTP-MLX-4bit",
                    "x/model-abliterated"):
            self.assertFalse(rr._candidate_ok(rid, {"download_all_size": 50 * 1024**3}),
                             rid)

    def test_distrusted_publisher_is_rejected(self):
        # mlx-community is trusted, an unknown uploader is not.
        self.assertTrue(rr._candidate_ok(
            "mlx-community/MiniMax-M3.1-Flash-Text-3bit",
            {"download_all_size": 170 * 1024**3}))
        self.assertFalse(rr._candidate_ok(
            "OsaurusAI/MiniMax-M3.1-Flash-JANGHT1.9",
            {"download_all_size": 95 * 1024**3}))

    def test_implausibly_small_is_rejected(self):
        self.assertFalse(rr._candidate_ok(
            "Jundot/tiny", {"download_all_size": 600 * 1024**2}))

    def test_unsupported_repo_is_rejected(self):
        self.assertFalse(rr._candidate_ok(
            "Jundot/model",
            {"download_all_size": 50 * 1024**3, "unsupported_reason": "nope"}))


class TestVerdict(unittest.TestCase):
    def test_fit_threshold(self):
        self.assertEqual(rr._verdict(78.5, None), "fits")
        self.assertEqual(rr._verdict(rr.RESIDENT_CEILING_GB, None), "fits")
        self.assertEqual(rr._verdict(291.8, None), "too-large")

    def test_missing_size_or_unsupported(self):
        self.assertEqual(rr._verdict(None, None), "absent")
        self.assertEqual(rr._verdict(10.0, "cannot run"), "unsupported")


class TestNorm(unittest.TestCase):
    def test_strips_publisher_and_baseline_suffix(self):
        self.assertEqual(rr._norm("Jundot/Qwen3.8-27B-oQ4e-mtp"),
                         "Qwen3.8-27B-oQ4e-mtp")
        self.assertEqual(rr._norm("Jundot/Qwen3.8-27B-oQ4e-mtp (baseline)"),
                         "Qwen3.8-27B-oQ4e-mtp")
        self.assertEqual(rr._norm("d3-edge"), "d3-edge")


if __name__ == "__main__":
    unittest.main()
