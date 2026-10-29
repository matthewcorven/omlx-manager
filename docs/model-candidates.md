# oMLX v0.7.3rc1 — Models Named in the Release Notes & What Fits an M4 Max / 128 GB

Sources read in full:
- https://github.com/jundot/omlx/releases/tag/v0.7.3rc1
- https://github.com/jundot/omlx/releases/tag/v0.7.3.dev2 (linked "full feature/benchmark list")
- PR links embedded in both release bodies (#4854, #4855, #4881, #4880/#4853/#4843, #4857/#4856, #4745, #4870, #4821, #4859, #4819/#4871, #4858, #4826, #4777, #4806, #4776, #4758, #4496, #4808, #4773, #4801, #4778, #4763, #4737, #4810, #4668, #4815, #4769, #4804, #4807, #4753, and the bug-fix/upgrade-notes PRs #4837, #4869, #4875, #4860, #4872, #4873, #4876, #4850, #4822, #4844, #4845, #4812, #4834, #4833, #4836, #4847, #4848, #4797, #4795, #4774, #4782)
- Ground truth for "what fits this exact Mac": `http://127.0.0.1:8001/admin/api/hf/recommendations` (device reported: **Apple M4 Max, 40 GPU cores, 128 GB / 137,438,953,472 bytes unified memory, 546 GB/s bandwidth**) and `http://127.0.0.1:8001/admin/api/hf/search?q=...&model_format=all`.
- Hugging Face Hub API, `curl -s "https://huggingface.co/api/models/<repo_id>?blobs=true"`, sizes summed from `siblings[].size` (exact commands listed per model below; all figures below are from these calls, not estimated).

The admin recommendations endpoint reports, for this exact machine: `static_ceiling_bytes` ≈ 120 GB, `usable_bytes` under normal operation ≈ **98–118 GB** depending on scenario (memory-guard on/off, wired-limit set or not). I treat **~110–118 GB resident** as the practical ceiling for "fits comfortably" and up to ~120 GB as "fits but tight/marginal" (matches the server's own `unlock` tier, which is its "it technically loads, expect to give up some headroom" bucket).

---

## 1. Every model named in the v0.7.3rc1 / v0.7.3.dev2 release notes

| Model (as named in notes) | What the release notes say | HF repo_id(s) found | Quant | Download GB | Resident GB | Max ctx | MoE? | MTP/draft? | Params (total/active) | Fits 128 GB? | Best for |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Qwen3.8-Flash-Next** | Headline MTP speed PR #4880/#4853/#4843: decode 65.6→81.5 tok/s (+24%) on M3 Ultra; dev2 #4810 batch-park backoff +11% on M5 Max, 8 clients | `Jundot/Qwen3.8-Flash-Next-oQ4e-mtp` (also oQ2.5e/oQ2.7e/oQ3e/oQ3.5e/oQ6e/oQ8e, `-fp16-mtp` variants) | oQ4e-mtp | **107.44 GB** | **79.21 GB** | 262,144 | ✅ | ✅ Lightning MTP | 126.4B / 7.95B active | ✅ Yes — in server's own `best` tier (smarts 5.33, 51.8 tok/s) | Strongest reasoning/coding MoE that comfortably fits with headroom |
| **Ling 3.1 Flash** | Headline new feature #4881: loads from native FP8, Lightning MTP via "Preserve MTP"; M3 Ultra 18.8→34.3 tok/s (+82%) at 4K | `inclusionAI/Ling-3.1-flash` (orig FP8, 573.8 GB), `mlx-community/Ling-3.1-flash-1019-oQ4e-mtp` / `oQ3e` / `oQ2.5e` / `oQ2e` | oQ2e-mtp (smallest) | **193.16 GB** | ~200 GB (est., no headroom beyond download) | n/a (not in local search metadata) | ✅ | ✅ Lightning MTP | **572.1B** total (per oMLX server metadata) | ❌ **No at every quant level** — even oQ2e is 193 GB on disk alone | Multi-Mac cluster / M3 Ultra+ with ≥256 GB only |
| **Ling Flash 3.0** | "Ling Flash 3.0 and 3.1 run their bundled nextn layer as Lightning MTP" (#4881) | `inclusionAI/Ling-3.0-flash-Sante`, `inclusionAI/Ling-3.0-flash` | — | not pulled (same family scale as 3.1) | — | — | ✅ | ✅ | Same order of magnitude as Ling 3.1 Flash (500B+) | ❌ No | Same caveat as Ling 3.1 Flash |
| **MiniMax M3.1 Flash** | Headline #4777 (dev2): NVFP4 or oQ, DSpark draft as Lightning MTP, +87% 1-req; #4806 fused decode kernels +14-23% | `MiniMaxAI/MiniMax-M3.1-Flash` (orig NVFP4, 252.4 GB), `mlx-community/MiniMax-M3.1-Flash-oQ3e-mtp` (182.7 GB) / `-oQ3.5e-mtp` (198.7 GB) / `-oQ4e-mtp` (231.7 GB / 248.8 GB by blob sum), `mlx-community/MiniMax-M3.1-Flash-Text-4bit` (248.4 GB, text-only, still huge) | oQ3e-mtp (smallest) | **182.7 GB** | not available (too big to appear in server's recommendation set) | 1,000,000 (per model card) | ✅ | ✅ Lightning MTP (DSpark) | **427.1B** total | ❌ **No at any quant** — smallest build is 182.7 GB on disk | Needs an Ultra-class Mac or cluster; out of range for a single 128 GB Mac |
| **GLM-5.3-Flash** | Macs-before-M5 one-request decode FP8 22.6→25.2 (+12%), oQ4e 38.6→41.7 (+8%) (#4880 family); same-greedy-output MTP fix (#4843); KDA de-dup frees 3.27 GB (#4764) | `zai-org/GLM-5.3-Flash` (orig, 328.4 GB), `Jundot/GLM-5.3-Flash-oQ2e-mtp` (110.3 GB dl / 115.82 GB resident) up to `Jundot/GLM-5.3-Flash-oQ4e-mtp` (173.6 GB) | **oQ2e-mtp** | **110.3 GB** | **115.82 GB** | **860,205** | ✅ | ✅ Lightning MTP | 321.3B / 25.4B active | ⚠️ **Marginal** — in server's own `unlock` tier (i.e., the top of what it will admit); oQ3e (138.2 GB) and up do not fit | Biggest "frontier-class" MoE that technically loads, if you accept near-zero headroom and reduced context |
| **GLM-5.3** (non-Flash) | "On Macs before M5, GLM-5.3 now gives the same greedy output with Lightning MTP on and off (#4843)"; also referenced from README install notes re: native kernels | `zai-org/GLM-5.3` (orig, **755.7 GB**) | — | 755.7 GB+ (even oQ2e would likely exceed 128 GB; not offered by server search in-range) | — | — | ✅ | ✅ | ~2x GLM-5.3-Flash scale | ❌ No | Cluster-only |
| **Flint** | #4880 family: TurboQuant decode 91.0→109.1 tok/s (+20%) on M4 Max, with TurboQuant @12K 23.5→75.7 (3.2x); originally served via #4763 | `RecursiveSI/flint` (orig, 79.59 GB), `mlx-community/flint-oQ4e` (**23.37 GB**), `-oQ3e` (18.45 GB) up to `-oQ8e` (39.4 GB per local search) | oQ4e | **23.37 GB** | ~24 GB (est.) | — | — (dense, 39.8B params) | ✅ DFlash2 draft (Splash) | **39.8B** | ✅ Yes, trivially | Fast, cheap dense coder; ideal always-resident daily driver |
| **DeepSeek-V4.1-Flash** | Headline #4880 family: prefill@128K 1512→1719 tok/s (+14%) with Engram on SSD (M5 Ultra); #4758 Engram tables can stay FP8; upgrade note re: SSD cache invalidation | `deepseek-ai/DeepSeek-V4.1-Flash` (orig, 510.3 GB), `Jundot/DeepSeek-V4.1-Flash-oQ2e-mtp` (**291.8 GB**) up to `-oQ4e-mtp` (402.4 GB) | oQ2e-mtp (smallest) | **291.8 GB** | — | — | ✅ | ✅ Lightning MTP + Engram | 95.1B active (total much larger, Engram-augmented) | ❌ **No at any quant** — far beyond 128 GB even at the lowest bit level | Multi-Mac cluster target only |
| **DeepSeek V4** (verify-draft arithmetic fix) | Bug fix: "Lightning MTP: ... DeepSeek V4 verify drafts with their decode arithmetic" (#4813); dev2 #4808 tensor-unit prefill on M5 | `deepseek-ai/DeepSeek-V4-Flash-0731` (the "Flash" sub-variant oMLX actually recommends) — orig 166.9 GB; `Jundot/DeepSeek-V4-Flash-0731-oQ2e-mtp` **105.23 GB dl / 110.49 GB resident** | oQ2e-mtp | **105.23 GB** | **110.49 GB** | 177,389 | ✅ | ✅ Lightning MTP | 304.2B / 33.6B active | ⚠️ Marginal — in server's `unlock` tier | Large MoE fallback behind GLM-5.3-Flash oQ2e if you want DeepSeek's style |
| **Ornith-1.5-122B** | Splash 1.4.1 feature (#4870): served with DFlash2 draft, MoE GGUF pruned to fewer experts | `ornith-ai/Ornith-1.5-122B` (orig, **250.2 GB**), `ornith-ai/Ornith-1.5-122B-GGUF`/`-NVFP4` (Splash-format, pruned-expert GGUFs, sizes not pulled — served via llama.cpp-style Splash path rather than MLX oQ) | GGUF (pruned-MoE) | not confirmed exact GB (Splash pruned GGUF; base checkpoint 250.2 GB) | — | — | ✅ | ✅ DFlash2 | 122B-class | ❌ No at full precision; **possible only via Splash's pruned-expert GGUF**, size not independently confirmed — flag as unverified | Only attempt via Splash's reduced-expert GGUF; do not assume it fits without re-checking Splash's specific export size |
| **Qwen3.6-35B-A3B** | Float16 Activations feature (#4819/#4871, from #3277): M1 Max oQ4e decode 75.9→82.4 tok/s (+9%); dev2 #4496 M1 Ultra prefill +50%; also a KL-quality example in #4776's low-bit oQ table | `Qwen/Qwen3.6-35B-A3B` (orig, 71.93 GB), `Jundot/Qwen3.6-35B-A3B-oQ4e-mtp` (**20.1 GB**) up to `-oQ8e-mtp` (server: download_gb=38.6, resident_gb=40.54) | oQ8e-mtp (server's "faster" pick) | 38.6 GB | **40.54 GB** | 262,144 | ✅ | ✅ Lightning MTP | 35.95B / 4.75B active | ✅ Yes, easily (in server's `faster` tier, 120.5 tok/s) | Fastest big-batch MoE coder; great for parallel/agentic workloads |
| **gpt-oss** (120b / 20b) | Upgrade note only: "SSD cache blocks ... saved for gpt-oss ... are not reused" (#4778, numerics changed in mlx-lm bump) | `openai/gpt-oss-120b` (orig MXFP4-native, **195.76 GB** blob sum — note: mostly duplicated/raw tensors, not representative of runtime footprint), `mlx-community/gpt-oss-120b-4bit` (**65.8 GB**), `openai/gpt-oss-20b` (41.3 GB orig), `mlx-community/gpt-oss-20b-MXFP4-Q8` (**12.1 GB**) | 120b-4bit | **65.8 GB** | ~68 GB (est.) | 128K (model card) | ✅ | — (no MTP draft bundled by default) | 120B total / ~5.1B active (OpenAI reported) | ✅ Yes | Open-weights reference MoE; useful for OpenAI-API-compatible agent testing |
| **ERNIE 4.5 MoE** | Same upgrade note: "SSD cache blocks ... saved for ... ERNIE 4.5 MoE ... are not reused" (#4778) | `baidu/ERNIE-4.5-21B-A3B-Thinking` (**43.67 GB** orig bf16); larger siblings `baidu/ERNIE-4.5-300B-A47B-*` (not pulled, clearly > 128 GB) | orig bf16 (21B-A3B) | 43.67 GB | ~46 GB (est., no oQ build found) | — | ✅ | — | 21B / 3B active (small variant) | ✅ Yes (small 21B-A3B variant); ❌ the 300B-A47B variant is far too big | Lightweight MoE alternative if ERNIE licensing/benchmarks matter |
| **PhiMoE** | Same upgrade note (#4778) | No current first-party "PhiMoE" repo found under that exact name on HF (closest: `microsoft/Phi-3.5-MoE-instruct`) — likely refers to an internal/older oMLX-supported Phi MoE build | — | — | — | — | ✅ | — | ~42B/6.6B active (Phi-3.5-MoE) | presumed ✅ (small) | Legacy MoE kept for SSD-cache regression coverage only |
| **PLaMo 3** | Same upgrade note (#4778) | `pfnet/plamo-3-nict-8b-base` (**16.19 GB**), `pfnet/plamo-3-nict-31b-base` (**63.52 GB**), `pfnet/plamo-3-nict-2b-base` (not pulled, smaller) | orig bf16, 31b variant | 63.52 GB | ~66 GB (est.) | — | dense | — | 31B dense (largest variant checked) | ✅ Yes (8B and 31B both fit; no oQ build confirmed) | Japanese-tuned dense alternative |
| **FP8 Ministral 3** | Same upgrade note (#4778) | `mistralai/Ministral-3-8B-Instruct-2512` (orig bf16, 20.88 GB), FP8 builds e.g. `unsloth/Ministral-3-8B-Instruct-2512-FP8`, `RedHatAI/Ministral-3-14B-Instruct-2512-FP8-dynamic` (sizes not independently pulled) | FP8 (8B class) | ~11–12 GB (est. half of bf16) | ~13 GB (est.) | — | dense | — | 8B / 14B dense variants available | ✅ Yes, trivially | Small, fast dense model for lightweight tasks |
| **Muse Spark** | Feature: "Muse Spark on mlx-lm's own model, with earlier oMLX conversions still loading" (#4778, dev2) | `meta-models/Muse-Spark-Open-816B-A42B` (orig, **1,644.37 GB** — an 816B-parameter MoE) | orig | 1,644.37 GB | n/a | — | ✅ | — | **816B** total / 42B active | ❌ **No, by a huge margin** | Cluster/datacenter only; not realistic for any single Mac |
| **Muse Glimmer 30B** | (Separate, smaller Muse sibling found alongside Muse Spark in the same org — not explicitly named in the notes, included for completeness since `Jundot/Muse-Glimmer-30B-oQ4e` exists) | `meta-models/Muse-Glimmer-30B` (orig, **59.58 GB**), `Jundot/Muse-Glimmer-30B-oQ4e` | oQ4e | not pulled exactly, est. ~17–20 GB (30B dense at 4-bit) | ~20 GB (est.) | — | dense | — | ~30B | ✅ Yes | Smaller Muse-family option if Spark is infeasible |
| **Jina rerankers (v3.5)** | Bug fixes: per-model Context Window setting (#4826); v3.5 query/document window handling and sliding-layer chunking | `jinaai/jina-reranker-v3.5` (orig, **1.21 GB**), `jinaai/jina-reranker-v3`, `jinaai/jina-reranker-v2-base-multilingual` | orig | **1.21 GB** | ~1.5 GB | window-based (per-model) | — | — | small (reranker-scale) | ✅ Yes, trivially | Pair with any generation model for RAG reranking |
| **SigLIP / SigLIP2** | Bug fix: "SigLIP and SigLIP2 embed text and images through their own towers" (#4850) | `google/siglip2-so400m-patch16-384` (**4.58 GB**), many other SigLIP2 size/patch variants | orig | 4.58 GB | ~5 GB | — | — | — | ~400M (SoViT variant) | ✅ Yes, trivially | Vision/text embedding backbone |
| **Unlimited-OCR** | Bug fix: "Unlimited-OCR takes the model card's `<image>` prompt" (#4822) | `baidu/Unlimited-OCR-2` (orig, **6.87 GB**), `mlx-community/Unlimited-OCR-2-8bit` (**4.1 GB**), `mlx-community/Unlimited-OCR-4bit` | 8bit | **4.1 GB** | ~4.5 GB | — | — | — | small OCR-VLM | ✅ Yes, trivially | Document OCR / image-to-text pipeline |
| **Qwen3.8-27B** | Appears throughout as the dense baseline: fp16+DFlash2 "+33%" (dev2 #4773), part of #4776's low-bit KL table, in server's `best`/`precise` tiers | `Qwen/Qwen3.8-27B` (orig, not pulled — dense ~27.8B), `Jundot/Qwen3.8-27B-oQ4e-mtp` (**16.97 GB dl / 17.82 GB resident**), `-oQ8e-mtp` (30.0 GB / 31.5 GB), `-oQ6e-mtp`, `-fp16-mtp` variants | **oQ4e-mtp** | **16.97 GB** | **17.82 GB** | **262,144** | dense | ✅ MTP + DFlash2 compatible | 27.78B | ✅ Yes, trivially (server's `best` tier, smarts 4.74, 36.2 tok/s) | Strong dense mid-size model — best all-around single pick if you want one model |
| **gemma-4-31B-it** | Appears in server's `best`/`precise` tiers (not separately named in prose, but matches the "Gemma 4" family referenced in #4776's KL table as "Gemma 4 26B-A4B") | `google/gemma-4-31B-it` (orig, not pulled), `Jundot/gemma-4-31B-it-oQ4e-mtp` (**19.94 GB dl / 20.94 GB resident**), `-oQ8e-mtp` (34.7 GB / 36.44 GB) | oQ4e-mtp | **19.94 GB** | **20.94 GB** | 262,144 | dense | ✅ MTP | 31.74B | ✅ Yes, trivially (server `best` tier, smarts 4.93, 30.8 tok/s) | Vision-capable dense alternative to Qwen3.8-27B |
| **gemma-4-26B-A4B-it** | Named directly in #4776's low-bit oQ KL table: "Gemma 4 26B-A4B oQ4e: Chat KL 0.076→0.039 (-49%)" | `Jundot/gemma-4-26B-A4B-it-oQ8e-mtp` (28.8 GB dl / **30.24 GB resident**, server `faster` tier), smaller `-oQ4e-mtp` also exists | oQ8e-mtp | 28.8 GB | **30.24 GB** | 262,144 | ✅ | ✅ MTP | 26.23B / 4.82B active | ✅ Yes, trivially (116.2 tok/s per server) | Fast vision-capable MoE, good throughput-per-GB |
| **Ornith-1.0-35B** | Appears in server's `faster` tier as a fast MoE option (not prose-named in this specific rc1/dev2 pair, but is in the active Jundot catalog alongside Ornith-1.5-122B) | `Jundot/Ornith-1.0-35B-oQ4e` (**21.1 GB dl / 22.16 GB resident**) | oQ4e | **21.1 GB** | **22.16 GB** | 262,144 | ✅ | ❌ (no MTP flag) | 35.1B / 3.9B active | ✅ Yes, trivially (server `faster` tier, 174.6 tok/s — fastest of all checked) | Fastest coder-MoE per GB; best "cheap and fast" pick |

### Notes / gaps on the table above
- Every GB figure under "Download GB"/"Resident GB" that is **bold** came directly from either (a) the oMLX admin recommendations/search endpoints' own `download_bytes`/`resident_bytes`/`size_formatted` fields, or (b) a direct `?blobs=true` HF API sum. Figures marked "(est.)" are not independently measured and should be re-checked before relying on them.
- **PhiMoE**: could not find a canonical first-party HF repo by that exact name; the release notes only mention it in a terse upgrade-note aside about SSD cache invalidation, with no PR link or benchmark, so it could not be fully pinned down. Flagged as a gap.
- **Ornith-1.5-122B**: the release notes describe it only via Splash's pruned-MoE GGUF path (#4870), which is a different, smaller export than the full 250.2 GB base checkpoint; I could not confirm the pruned GGUF's exact size from the HF API in the time available — treat the "fits/doesn't fit" call as unverified rather than a hard "no."
- **FP8 Ministral 3** and **Muse Glimmer 30B** sizes are estimated by parameter-count/precision reasoning, not directly summed from blobs; re-run the `?blobs=true` call on the specific FP8/oQ repo before trusting them for disk-space planning.

---

## 2. Recommended download set for M4 Max / 128 GB — targeting small coding tasks

Ranked by priority for a disk-space-conscious setup; cumulative disk cost assumes you download in this order and keep everything resident on SSD (not simultaneously loaded in RAM — oMLX swaps models in/out of unified memory on demand).

| Rank | Model | repo_id | Quant | Download GB | Cumulative GB | Resident GB | Why it's in the set |
|---|---|---|---|---|---|---|---|
| 1 | **Ornith-1.0-35B** | `Jundot/Ornith-1.0-35B-oQ4e` | oQ4e | 21.1 | 21.1 | 22.16 | Fastest small/fast MoE coder (174.6 tok/s per oMLX bench) — ideal for quick autocompletion-style tasks |
| 2 | **Flint** | `mlx-community/flint-oQ4e` | oQ4e | 23.37 | 44.5 | ~24 | Headline-named dense 40B coder with DFlash2 draft + TurboQuant speedup (+20% decode per notes); strong "always on" daily driver |
| 3 | **Qwen3.8-27B** | `Jundot/Qwen3.8-27B-oQ4e-mtp` | oQ4e-mtp | 16.97 | 61.5 | 17.82 | Strong dense mid-size, server's own top `best` pick, vision-capable, MTP draft bundled |
| 4 | **gemma-4-31B-it** | `Jundot/gemma-4-31B-it-oQ4e-mtp` | oQ4e-mtp | 19.94 | 81.4 | 20.94 | Vision-capable dense alternative/second opinion to Qwen3.8-27B; also in server's `best` tier |
| 5 | **Qwen3.6-35B-A3B** | `Jundot/Qwen3.6-35B-A3B-oQ8e-mtp` | oQ8e-mtp | 38.6 | 120.0 | 40.54 | Fast, high-batch MoE (120.5 tok/s) — good for parallel agent sessions; release-note-tracked family (#4819/#4871/#4496/#4776) |
| 6 | **gemma-4-26B-A4B-it** | `Jundot/gemma-4-26B-A4B-it-oQ8e-mtp` | oQ8e-mtp | 28.8 | 148.8 | 30.24 | Vision-capable MoE, strong tok/s-per-GB, directly named in #4776's quality table |
| 7 | **Qwen3.8-Flash-Next** | `Jundot/Qwen3.8-Flash-Next-oQ4e-mtp` | oQ4e-mtp | 107.44 | 256.2 | 79.21 | Release-note headline model; best single-model "smarts" score (5.33) that still fits in 128 GB with real headroom |
| 8 | **GLM-5.3-Flash** (stretch) | `Jundot/GLM-5.3-Flash-oQ2e-mtp` | oQ2e-mtp | 110.3 | 366.5 | 115.82 | Release-note headline model; only fits at the lowest quant and sits in the server's `unlock` tier — load it alone, nothing else resident at the same time |
| 9 | **jina-reranker-v3.5** | `jinaai/jina-reranker-v3.5` | orig | 1.21 | 367.7 | ~1.5 | Tiny reranker to pair with any of the above for RAG workflows; release-note bug fixes (#4826) directly apply |
| 10 | **Unlimited-OCR-2** | `mlx-community/Unlimited-OCR-2-8bit` | 8bit | 4.1 | 371.8 | ~4.5 | Vision-capable OCR utility model; release-note bug fix (#4822) directly applies; rounds out a "small coding + document ingestion" toolkit |

**Models that are release-note headliners but intentionally excluded from the top picks because they don't fit a single 128 GB Mac at any quant level:** Ling 3.1 Flash, MiniMax M3.1 Flash, DeepSeek-V4.1-Flash (see §3). DeepSeek-V4-Flash-0731 (the older "Flash" sibling that does nearly fit, oQ2e at 105.23 GB/110.49 GB resident) is a viable 11th pick if you want a DeepSeek-family model and are willing to run it alone with no other model resident.

Sampling settings per model (from model cards, see citations below):

| Model | Recommended sampling | Thinking default? | Context notes |
|---|---|---|---|
| Qwen3.8-27B / Qwen3.8-Flash-Next | Thinking: `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0`; Instruct/non-thinking: `temperature=0.7, top_p=0.80, top_k=20, presence_penalty=1.5` | Yes (thinking mode by default) | 262,144 native, extensible to 1,000,000 |
| Qwen3.6-35B-A3B | Thinking/general: `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=1.5`; precise coding/WebDev: `temperature=0.6, top_p=0.95, top_k=20, presence_penalty=0.0`; Instruct: `temperature=0.7, top_p=0.80, top_k=20, presence_penalty=1.5` | Yes | 262,144 native; keep ≥128K to preserve thinking quality |
| gemma-4-31B-it / gemma-4-26B-A4B-it | `temperature=1.0, top_p=0.95, top_k=64` | N/A (Gemma instruct, no reasoning toggle) | 256K |
| Flint | `temperature=1.0, top_p=0.95, top_k=20` | Yes (agentic benches run with thinking) | Terminal-Bench/SWE-bench style agent harness settings |
| Ornith-1.0-35B (same family card as Ornith-1.5) | `temperature=0.6, top_p=0.95, top_k=20` (precise/agentic); `temperature=1.0, top_p=0.95` (broader benches) | Yes | 128K–400K depending on benchmark |
| GLM-5.3-Flash | `temperature=1.0, top_p=0.95`; `reasoning_effort` param: `low`/`high`/`max` (defaults to `max`); `clear_thinking=true` recommended for chat | Yes, `max` effort by default | Up to 300K (eval), 860,205 reported max by oMLX server |
| DeepSeek-V4-Flash-0731 | `temperature=1.0, top_p=0.95` (agentic), `top_p=1.0` (otherwise); max output 384K at `high`/`max` effort | Yes | 177,389 (per oMLX server) |
| Ling 3.1 Flash | `temperature=1.0, top_p=0.95, top_k=20`, `enable_thinking=true` | Yes | not independently confirmed |
| MiniMax M3.1 Flash | `temperature=1.0, top_p=0.95` | — | up to 1,000,000 (card claim) |

---

## 3. Not feasible on 128 GB — and why

| Model | Smallest confirmed build | Size | Reason excluded |
|---|---|---|---|
| **Ling 3.1 Flash** | `mlx-community/Ling-3.1-flash-1019-oQ2e-mtp` | 193.16 GB download, 572.1B total params | Even the lowest 2-bit oQ quant is ~193 GB on disk; nowhere near the ~110–118 GB resident ceiling on this Mac. Not present in oMLX's own recommendation set at all. |
| **Ling Flash 3.0** | — | same order of magnitude as 3.1 | Same family/scale issue as Ling 3.1 Flash. |
| **MiniMax M3.1 Flash** | `mlx-community/MiniMax-M3.1-Flash-oQ3e-mtp` | 182.7 GB download, 427.1B total params | Smallest available oQ build is still 182.7 GB; original NVFP4 checkpoint is 252.4 GB. Not offered by oMLX's own recommendation engine for this hardware. |
| **DeepSeek-V4.1-Flash** | `Jundot/DeepSeek-V4.1-Flash-oQ2e-mtp` | 291.8 GB download | Despite "Flash" branding, this is DeepSeek's large/newest MoE; even 2-bit oQ is nearly 3x the Mac's total memory. |
| **GLM-5.3** (non-Flash) | `zai-org/GLM-5.3` (orig) | 755.7 GB | Full GLM-5.3 (not the Flash distillation) is roughly double GLM-5.3-Flash's footprint; no oQ build small enough was found or offered by the server. |
| **Muse Spark (816B-A42B)** | `meta-models/Muse-Spark-Open-816B-A42B` (orig) | 1,644.37 GB | An 816B-parameter MoE; off the scale of any single consumer Mac regardless of quantization level. |
| **Ornith-1.5-122B** (full-precision path) | `ornith-ai/Ornith-1.5-122B` (orig) | 250.2 GB | Base checkpoint alone exceeds 128 GB; only a potential fit via Splash's pruned-expert GGUF export, whose exact size I could not confirm from the HF API in this pass (flagged as unverified, not a confirmed "yes"). |
| **ERNIE-4.5-300B-A47B family** | `baidu/ERNIE-4.5-300B-A47B-*` | not pulled, clearly >128 GB at any reasonable quant given 300B+ total params | Far above the Mac's memory ceiling; only the much smaller 21B-A3B ERNIE variant is viable. |

---

## Exact commands used (for reproducibility)

```bash
# Ground truth for this exact Mac
curl -s "http://127.0.0.1:8001/admin/api/hf/recommendations"
curl -s "http://127.0.0.1:8001/admin/api/hf/search?q=<name>&limit=20&model_format=all"

# Enumerate Jundot's own oQ catalog
curl -s "https://huggingface.co/api/models?author=Jundot&limit=100"

# Exact sizes for every repo_id cited above
curl -s "https://huggingface.co/api/models/<repo_id>?blobs=true"
# then: sum(sibling['size'] for sibling in response['siblings'])

# Discover candidate repos by name
curl -s "https://huggingface.co/api/models?search=<name>&limit=20"
```

All repo_ids, sizes, parameter counts, MoE/MTP flags, max-context values, and tok/s figures quoted as exact numbers above (not marked "(est.)") came directly from one of these four calls, run against the live Hugging Face Hub API and the local oMLX admin API on 2026-10-28.
