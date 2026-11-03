# Conversational Voice Model Benchmark Results

| Model | Quant | Params | Resident Size | Turn TTFT (ms) | First Audio Latency (ms) | Reply Audio (ms) | Speech Real-Time Factor | Transcript WER | Voices/Languages | Quality/Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LiquidAI/LFM3-Omni-2B-MLX-4bit | 4bit | dense 2.2B omni | 1.92 GB | 12.9 | 96.5 | 7200 | 9.20 | 0.0476 | 1 built-in realtime voice; TTS female/male; 18 languages | PASS - 3/3 turns completed | Realtime WS baseline, 3 runs, 4.8 s spoken prompt; RTF 9.2x means 1 s of speech is generated in 109 ms. |
