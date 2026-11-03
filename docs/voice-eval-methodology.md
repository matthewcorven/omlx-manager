# Conversational Voice Model Evaluation Methodology

How oMLX conversational voice models are benchmarked, and why the numbers in
`results/voice.csv` are the ones that matter.

## What "conversational voice" means in oMLX 0.7.3

oMLX classifies a model as realtime-voice-capable when its `config_model_type`
is one of `lfm3_audio`, `lfm3_omni`, or `qwen3_omni_moe` **and** the model does
not set `enable_audio_output: false`
(`model_discovery.py:404`, `is_realtime_voice_model()`). Those three types map
to `LFM3VoiceBackend` and `Qwen3OmniVoiceBackend` in `engine/vlm.py`.

This is a different surface from text generation and from plain TTS:

| Surface | Endpoint | What it does |
|---|---|---|
| Conversational voice | `WS /v1/realtime` | Audio in, audio out, multi-turn, tools, images |
| Text-to-speech | `POST /v1/audio/speech` | Text in, audio out, selectable voices |
| Speech-to-text | `POST /v1/audio/transcriptions` | Audio in, text out |

A model can support all three. `LiquidAI/LFM3-Omni-2B-MLX-4bit`, for example,
exposes **one** built-in realtime voice but **two** TTS voices (`female`,
`male`) across 18 languages. Do not conflate the two voice counts.

## The realtime protocol

`/v1/realtime` is a WebSocket that speaks a subset of the OpenAI Realtime API.
The client drives every turn explicitly:

1. `session.update` — set `instructions`, `tools`, `voice`, `modalities`.
   oMLX **rejects** `turn_detection`; server-side VAD is not available, so the
   client must decide when a turn ends.
2. `input_audio_buffer.append` — base64 PCM16 at **24 kHz**, in ~40 ms frames
   (`STEP_SECONDS = 0.04`). Other sample rates are rejected.
3. `input_audio_buffer.commit` — close the input turn. Minimum 0.1 s of audio
   (`MIN_COMMIT_SECONDS`), maximum 120 s (`MAX_INPUT_SECONDS`).
4. `response.create` — ask for a reply.

The server then emits, in order: `response.created` →
`response.output_item.added` → `response.output_audio_transcript.delta` and
`response.output_audio.delta` (interleaved) → `response.output_audio.done` →
`response.output_audio_transcript.done` → `response.output_item.done` →
`response.done`.

`session.update` is only honoured before the first turn. After that the session
is locked (`session_locked` error) — instructions, tools, and voice cannot be
changed mid-conversation. A sweep over those knobs therefore requires a fresh
WebSocket per variant.

## Metrics

`scripts/voice_eval.py` measures five things per run:

| Metric | Definition | Why it matters |
|---|---|---|
| `turn_ttft_ms` | Send → `response.created` | Server-side turn acceptance; should be single-digit ms |
| `first_audio_latency_ms` | Send → first `response.output_audio.delta` | The number a user actually feels as "responsiveness" |
| `reply_audio_ms` | Sum of emitted audio duration | How long the spoken answer is |
| `realtime_factor` | `reply_audio_ms / stream_wall_ms` | Generation speed relative to playback. `> 1` means the model outruns the speaker |
| `transcript_wer` | WER of TTS → realtime → ASR round trip | Whether the audio is intelligible, not just fast |

`realtime_factor` replaces decode tokens/second for this modality. A model at
RTF 9.2 produces one second of speech in 109 ms, so playback — not inference —
is the bottleneck. Anything below RTF 1.0 cannot hold a live conversation: the
listener hears gaps.

`transcript_wer` is the quality gate. A fast model that produces unintelligible
audio is worthless, and WER is the only objective, automatable proxy available
without human listening tests. It is measured by synthesizing the prompt with
`/v1/audio/speech`, feeding that audio through the realtime session, and
transcribing the reply with `/v1/audio/transcriptions`.

## Procedure

```sh
# 1. Load the model
curl -s -X POST $OMLX/admin/api/models/<model_id>/load

# 2. Confirm it is realtime-voice capable before spending time on it
curl -s "$OMLX/v1/audio/voices?model=<model_id>&realtime=true" | jq .

# 3. Smoke test the harness once
/Applications/oMLX.app/Contents/MacOS/omlx-cluster-python \
  scripts/voice_eval.py --model <model_id> --runs 1 --out results/voice/<model>/smoke.json

# 4. Baseline
/Applications/oMLX.app/Contents/MacOS/omlx-cluster-python \
  scripts/voice_eval.py --model <model_id> --runs 3 --out results/voice/<model>/baseline.json

# 5. Record through the canonical writer
python3 scripts/record_model_result.py --type voice --add --data '<json_data>'
python3 scripts/record_model_result.py --validate-all
```

The harness needs `websockets`, which ships with the oMLX cluster interpreter
(`/Applications/oMLX.app/Contents/MacOS/omlx-cluster-python`), not the stock
`python3`. `scripts/omlx_config.py` exposes that path as `PYTHON`.

## Rules

- **Same prompt audio, same `--runs 3`, same `max_tokens`** for every
  comparison. Medians are reported.
- **One benchmark at a time.** oMLX returns 409 on concurrent runs and the
  measurements are corrupted.
- **Never compare a realtime number to a TTS number.** They are different
  endpoints with different bottlenecks.
- **Record only through `scripts/record_model_result.py`.** Hand-edited tables
  are prohibited and `--validate-all` will reject them.
- **Keep `Notes` single-line.** The dashboard's CSV parser splits on newlines
  before applying quote handling.

## Known limits

- The corpus is a single English prompt. It cannot measure multilingual
  quality, accent robustness, or long-context conversation.
- WER is measured against the model's own transcript, so a model that
  consistently mispronounces a word in the same way can still score well.
- `realtime_factor` depends on the reply length; a model that answers in one
  short sentence and one that rambles are not directly comparable on RTF alone.
  Compare `first_audio_latency_ms` for responsiveness and RTF for throughput.
- LFM3 realtime voice has no voice selection. Voice variety is a TTS property,
  not a realtime one, and is recorded in `Voices/Languages` for context only.
