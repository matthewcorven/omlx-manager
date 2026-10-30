# Image Generation Model Benchmark Results

| Model | Quant | Steps | Resolution | TTFT/Step Latency | Total Latency | VRAM/Resident | Quality/CLIP | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FLUX.1-schnell | 4bit | 4 | 1024x1024 | 418.6 ms/step | 2.02 s | 8.4 GB | 0.3180 CLIP | Reference FLUX.1 schnell 4-bit benchmark on Apple Silicon |
| FLUX.1-dev | 8bit | 20 | 1024x1024 | 510.7 ms/step | 10.63 s | 14.2 GB | 0.3320 CLIP | Diffusion Transformer (DiT); 8-bit quantized on Apple Silicon M4 Max |
| SD3.5-Large | 8bit | 24 | 1024x1024 | 317.4 ms/step | 7.9 s | 10.4 GB | 0.3195 CLIP | Stable Diffusion 3.5 Large MMDiT; 8-bit Q8_0 weights on M4 Max |
| SDXL-Turbo | 8bit | 1 | 512x512 | 112.0 ms/step | 0.29 s | 4.1 GB | 0.2855 CLIP | Single-step adversarial distilled UNet; guidance=0.0; EulerAncestral |
| Tongyi-MAI/Z-Image-Turbo | 8bit | 8 | 1024x1024 | 162.3 ms/step | 1.51 s | 6.8 GB | 0.3100 CLIP | OpenAI-compatible mlx-vlm turbo pipeline; 8 Euler steps at 1024x1024 |
| baidu/ERNIE-Image-Turbo | 8bit | 8 | 1024x1024 | 173.9 ms/step | 1.61 s | 7.2 GB | 0.3070 CLIP | Baidu ERNIE turbo image pipeline via oMLX v0.7.3 image engine |
| mage-flow-community/Mage-Flow-Turbo | 8bit | 8 | 1024x1024 | 151.5 ms/step | 1.41 s | 6.4 GB | 0.3125 CLIP | Mage-Flow rectified flow turbo pipeline; 8 steps at 1024x1024 |
