# OCR Model Benchmark Results

| Model | Quant | Checkpoint/Package | Resident Size | CER (Character Error Rate) | WER (Word Error Rate) | Avg Page Latency (s) | Max Tokens | Quality/Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mlx-community/Unlimited-OCR-2-8bit | 8bit | mlx-vlm 0.7.11 DASH | 4.8 GB | 0.0012 | N/A | 1.21 | 8192 | PASS - fixed, scored | 12-page synthetic corpus; mean IoU 0.880; reading order perfect. Re-scored on oMLX 0.7.4.dev1: CER 0.0012 and IoU 0.880 unchanged; page latency 1.13 -> 1.21 s warm (a cold first page adds ~6 s to the mean). |
| jinaai/jina-reranker-v3.5-mlx | BF16 | MLX conversion | 1.2 GB | 0.0 | N/A | 0.05 | 512 | PASS - fixed (reranker) | Non-LLM reranker smoke test passed (rank 1 score 0.4715) |
