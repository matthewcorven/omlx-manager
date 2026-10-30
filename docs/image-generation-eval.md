# Evaluation Architecture & Metrics Specification: Image Generation Models

## 1. Executive Summary & Objective

This document defines the formal evaluation architecture, standard prompt suite, deterministic seed contract, performance metrics, and benchmark harness for multi-modal image generation models running on Apple Silicon via MLX / oMLX.

As diffusion architectures transition from traditional UNet backbones (e.g., Stable Diffusion 1.5, SDXL) toward Diffusion Transformers (DiTs) (e.g., FLUX.1 [schnell], FLUX.1 [dev], Stable Diffusion 3.5), hardware resource requirements shift dramatically. On Apple Silicon unified memory architectures, image generation performance is constrained by:
1. **Unified Memory Bandwidth**: Peak transfer rates between CPU/GPU during transformer block self-attention and cross-attention.
2. **Metal Compute Shader Compilation**: Substantial cold-start compilation overhead (up to 30–60 seconds on initial graph capture) that must be strictly separated from steady-state inference.
3. **VRAM Residency & Quantization Trade-offs**: 16-bit float DiT weights exceed the residency budgets of standard M-series configurations (16GB–36GB unified memory), necessitating 4-bit and 8-bit weight quantization without degrading text alignment or high-frequency details.

All benchmarks and evaluations conducted under this specification record canonical results directly into `results/image-generation.csv` and `results/image-generation.md` via the central `scripts/record_model_result.py` CLI.

---

## 2. Target Architectures & Quantization Matrix

The evaluation suite benchmarks three distinct classes of image generation models on Apple Silicon:

| Architecture Class | Representative Models | Parameter Count | Target Quantization | Primary Target Resolution |
|---|---|---|---|---|
| **Diffusion Transformers (DiT)** | `FLUX.1-schnell`<br>`FLUX.1-dev`<br>`SD3.5-Large` | 12B – 24B | 4-bit (MXFP4, Q4_K_M)<br>8-bit (Q8_0)<br>BF16/FP16 | 1024x1024<br>768x1344 (9:16)<br>1344x768 (16:9) |
| **Distilled / Turbo UNets** | `SDXL-Turbo`<br>`SDXL-Lightning` | 2.6B – 3.5B | 8-bit, FP16 | 512x512<br>1024x1024 |
| **Legacy Latent Diffusion** | `Stable-Diffusion-v1.5`<br>`SDXL-Base-1.0` | 860M – 3.5B | 8-bit, FP16 | 512x512<br>1024x1024 |

### Hardware & Environment Constraints
- **Apple Silicon Unified Memory**: Models must execute within unified memory without triggering system swap paging. Paging into NVMe causes immediate 10x–50x step latency degradation.
- **Metal Shader Caching**: Metal compiles compute pipelines during initial model instantiation and first inference pass. Benchmarks must discard the cold compilation run when reporting steady-state step latency and total generation time, while recording cold compilation time as a distinct operational KPI.
- **Quiet Machine Rule**: Image generation benchmarks require zero competing GPU/Metal workloads and no concurrent background disk I/O.

---

## 3. Standard Benchmark Prompt Suite

Evaluation requires a fixed, deterministic set of 5 standardized prompts probing five orthogonal generative capabilities:

```
[Prompt Suite]
  ├── P1: Photographic & Human Anatomy (Micro-detail, hands, facial features)
  ├── P2: In-Image Typography & Text Rendering (Spelling, font fidelity, kerning)
  ├── P3: Spatial Reasoning & Compositional Binding (Color binding, relative positions)
  ├── P4: Vector & Stylized Graphic Design (Clean line-art, flat shading, icon style)
  └── P5: Complex Architectural Perspective (High-frequency geometric textures)
```

### Prompt Definitions

#### Prompt 1: Photographic & Human Anatomy (Micro-detail)
- **Prompt**: `"A close-up studio portrait photograph of an elderly Japanese watchmaker inspecting the intricate mechanical gears of an antique pocket watch. Macro lens, soft natural window lighting, 85mm f/1.4, detailed skin pores, realistic wrinkles, sharp focus on accurate fingers and watchmaker tweezers."`
- **Evaluation Focus**: Skin micro-textures, specular reflections, anatomical accuracy of hands and fingernails, optical depth-of-field realism.

#### Prompt 2: In-Image Typography & Text Rendering
- **Prompt**: `"A futuristic cyberpunk alleyway bathed in rain and neon glow, featuring a large glowing neon sign that clearly reads 'OMLX FAST INFERENCE' in bright cyan letters, with a smaller yellow sign below reading 'LOW LATENCY'. Professional architectural photography, wet reflective pavement."`
- **Evaluation Focus**: In-image character rendering, correct spelling without hallucinated or duplicated glyphs, kerning, contrast against background lighting.

#### Prompt 3: Spatial Reasoning & Compositional Binding
- **Prompt**: `"A minimalist still life photograph on a clean matte table: a bright yellow ceramic cube positioned strictly to the left of a dark blue glass sphere, with a small red apple resting on top of the yellow cube. Neutral grey studio background, crisp directional shadows."`
- **Evaluation Focus**: Attribute binding (yellow $\rightarrow$ cube, blue $\rightarrow$ sphere, red $\rightarrow$ apple) and spatial relation adherence (left of, on top of).

#### Prompt 4: Vector & Stylized Graphic Design
- **Prompt**: `"A clean modern vector illustration of an astronaut tending to an indoor hydroponic greenhouse on Mars. Flat design, bold outlines, vibrant limited color palette of orange, teal, and off-white, minimalist aesthetic, SVG icon art style."`
- **Evaluation Focus**: Ability to suppress photorealism in favor of clean 2D vector aesthetics, sharp lines without diffuse rendering artifacts.

#### Prompt 5: Complex Architectural Perspective & Geometry
- **Prompt**: `"A wide-angle interior photograph of a grand Gothic cathedral library, featuring vaulted ribbed ceilings, soaring arched stone columns, spiral staircases, and endless wooden bookshelves receding into geometric one-point perspective. Rays of morning sun filtering through stained glass."`
- **Evaluation Focus**: Structural symmetry, perspective convergence, high-frequency repetitive geometry without warping or structural drift.

---

## 4. Deterministic Seed Contract & Sampling Protocol

To eliminate stochastic variance across model comparisons:
1. **Evaluation Seeds**: Every prompt is evaluated across three canonical fixed seeds:
   - Primary Seed: `42`
   - Secondary Seed: `1337`
   - Tertiary Seed: `2026`
2. **Warm-up Protocol**:
   - **Step 0 (Cold Compilation)**: A single unmeasured 1-step or 4-step generation with seed `0` is executed to trigger Metal graph capture and compute shader compilation.
   - **Steps 1..N (Benchmark)**: Subsequent runs measure steady-state inference latency.
3. **Step Count Standard**:
   - Schnell / Distilled / Turbo models: `4` steps (guidance scale: `0.0` or `1.0`).
   - Standard DiT / Base models: `20` and `30` steps (Euler / DPMSolverMultistepScheduler, guidance scale: `3.5` – `7.5`).

---

## 5. Metrics Specification

The evaluation harness extracts seven canonical metrics for each benchmarked configuration:

### 1. Step Latency (`ms/step` or `s/step`)
- **Definition**: The arithmetic mean time required to execute one denoising diffusion step through the transformer/UNet backbone during steady-state sampling.
- **Formula**:
  $$\text{Step Latency} = \frac{\sum_{i=1}^{S} \Delta t_i}{S}$$
  where $S$ is the number of denoising steps and $\Delta t_i$ is the duration of step $i$.

### 2. Total Generation Latency (`Total Latency`)
- **Definition**: End-to-end wall-clock time from text prompt input to final decoded RGB pixel tensor on host memory. Includes text encoding (e.g., T5-XXL / CLIP), full diffusion loop, and VAE decoding.
- **Unit**: Seconds (`s`) or milliseconds (`ms`).

### 3. VRAM / Resident Memory (`VRAM/Resident`)
- **Definition**: Maximum resident set size (RSS) in gigabytes during sampling, captured via system memory telemetry.
- **Invariant**: Must distinguish model weights from temporary KV and activation allocations.

### 4. Cold Compilation Latency (`TTFI_cold`)
- **Definition**: Latency of the very first inference invocation from process cold start, capturing Metal shader compilation and weight memory mapping.

### 5. Effective Throughput (`images/min`)
- **Definition**: Sustained image generation rate under continuous back-to-back inference:
  $$\text{Throughput} = \frac{60.0}{\text{Total Latency (s)}}$$

### 6. Perceptual Quality & Text Alignment (`Quality/CLIP`)
- **Metric**: Zero-shot cosine similarity between image embedding and target prompt using standard `CLIP-ViT-L/14` or `CLIP-ViT-B/32`:
  $$\text{CLIP Score} = 100 \times \max\left(\cos(\mathbf{e}_{\text{img}}, \mathbf{e}_{\text{text}}), 0\right)$$
- **Complementary Measure**: Optional human-preference alignment score (ImageReward or PickScore).

### 7. Degeneracy Gate (Pass / Fail)
A model run is flagged **Degenerate** if:
- VAE output NaN / Inf / black image tensor.
- Severe mode collapse or repetitive noise pattern.
- Memory swap exceeds 500 MB during generation.

---

## 6. Centralized Results Integration & Schema

Results generated by `scripts/image_eval.py` map 1:1 to `results/image-generation.csv` and `results/image-generation.md`:

```csv
Model,Quant,Steps,Resolution,TTFT/Step Latency,Total Latency,VRAM/Resident,Quality/CLIP,Notes
FLUX.1-schnell,4bit,4,1024x1024,485.2 ms/step,2.45 s,9.8 GB,0.318 CLIP,Metal FP16 VAE; guidance=0.0; Euler
SDXL-Turbo,8bit,1,512x512,185.0 ms/step,0.42 s,4.2 GB,0.285 CLIP,EulerAncestral; guidance=0.0
```

All updates are executed exclusively via:
```bash
python3 scripts/record_model_result.py --type image-generation --data "..."
```

---

## 7. Harness Stub Architecture (`scripts/image_eval.py`)

The companion evaluation harness `scripts/image_eval.py` provides:
1. **CLI Interface**: Accepts `--model`, `--quant`, `--steps`, `--resolution`, `--seeds`, `--prompt-suite`, `--output-dir`, `--record`, and `--dry-run`.
2. **Benchmark Execution Flow**:
   - Warms up pipeline and Metal shaders.
   - Iterates through the standard 5-prompt suite across all configured seeds.
   - Measures steady-state step latency, end-to-end latency, and peak resident memory.
   - Computes average metrics and formats output JSON report.
3. **Automatic Recording**: When invoked with `--record`, invokes `scripts/record_model_result.py` to atomically update the central repository results.
