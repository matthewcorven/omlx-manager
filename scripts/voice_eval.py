#!/usr/bin/env python3
"""Score an oMLX conversational voice model over `/v1/realtime`.

Realtime voice models have no decode-throughput tuning target. The axes that
matter are how quickly a spoken turn comes back, how fast the reply audio
streams once it starts, and whether the reply is intelligible. This harness
opens one WebSocket conversation per run, sends a spoken prompt, and measures:

  turn_ttft_ms            commit -> `response.created` (the model accepted the
                          turn and started responding)
  first_audio_latency_ms  commit -> first `response.output_audio.delta`
  reply_audio_ms          duration of the returned 24 kHz PCM16 reply
  realtime_factor         reply_audio_ms / wall-clock stream time; > 1.0 means
                          the model speaks faster than playback
  transcript              the assistant transcript, transcribed back with the
                          model's own `/v1/audio/transcriptions` call
  roundtrip_wer           word error rate of that re-transcription against the
                          transcript text; the intelligibility gate
  output_tokens           audio slots reported in `response.done` usage

The prompt audio is synthesized with the model's own `/v1/audio/speech` call, so
no external corpus or TTS binary is needed. `/v1/realtime` rejects server turn
detection: every turn must be explicitly committed, which this harness does.

Usage:

    python3 scripts/voice_eval.py --model LFM3-Omni-2B-MLX-4bit --runs 3 \
        --out results/voice/LFM3-Omni-2B-MLX-4bit/baseline.json

The HTTP side uses only the standard library. The WebSocket client needs the
`websockets` package, which ships with the oMLX interpreter but not with the
stock `python3`; point `--python` at one that has it, or install it yourself.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import wave

import omlx_config

# Resolved from OMLX_BASE_URL; --base-url overrides it per run.
OMLX = omlx_config.BASE_URL

# One spoken turn, long enough to be a real request but short enough to keep the
# reply bounded. Kept identical across models so numbers stay comparable.
PROMPT_TEXT = (
    "In one short sentence, explain what a real-time speech model is."
)
SPEECH_RATE = 24000
RESPONSE_TIMEOUT_S = 600.0


# ---------------------------------------------------------------- transport


def post(path: str, body: dict, timeout: float = 900.0) -> bytes:
    req = urllib.request.Request(
        OMLX + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_json(path: str, timeout: float = 120.0) -> dict:
    with urllib.request.urlopen(OMLX + path, timeout=timeout) as r:
        return json.load(r)


def probe(model: str) -> dict:
    """Static capability read; no model load, so this also works when cold."""
    realtime = get_json(f"/v1/audio/voices?model={model}&realtime=true")
    try:
        tts = get_json(f"/v1/audio/voices?model={model}")
    except (urllib.error.URLError, ValueError):
        tts = {"voices": []}
    return {
        "realtime_voices": realtime.get("voices") or [],
        "tts_voices": tts.get("voices") or [],
        "capabilities": realtime.get("capabilities") or {},
    }


def synthesize(model: str, text: str, voice: str | None) -> bytes:
    """Render the prompt turn with the model's own TTS, as 24 kHz PCM16."""
    body = {"model": model, "input": text, "response_format": "pcm"}
    if voice:
        body["voice"] = voice
    pcm = post("/v1/audio/speech", body)
    if not pcm:
        raise SystemExit("speech endpoint returned no audio")
    return pcm


def transcribe(model: str, pcm: bytes) -> str:
    """Transcribe 24 kHz PCM16 back to text through the model's ASR path."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SPEECH_RATE)
        w.writeframes(pcm)
    wav = buf.getvalue()

    boundary = "----omlxvoiceeval"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="model"\r\n\r\n',
            model.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="reply.wav"\r\n',
            b"Content-Type: audio/wav\r\n\r\n",
            wav,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        OMLX + "/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=900.0) as r:
        return (json.load(r).get("text") or "").strip()


# ---------------------------------------------------------------- scoring


def words(text: str) -> list[str]:
    return [w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if w]


def wer(truth: str, hyp: str) -> float:
    """Levenshtein word error rate; 0.0 is perfect."""
    t, h = words(truth), words(hyp)
    if not t:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, tw in enumerate(t, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (tw != hw)))
        prev = cur
    return prev[-1] / len(t)


async def run_turn(model: str, pcm: bytes) -> dict:
    """One committed turn over `/v1/realtime`; returns timings for the reply."""
    import websockets  # imported here so --help works without the extra

    ws_url = OMLX.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/v1/realtime?model={model}"
    # 24 kHz mono PCM16 -> 40 ms frames, the step the backend emits on.
    frame = int(SPEECH_RATE * 0.04) * 2

    created = first_audio = done = None
    audio = bytearray()
    transcript: list[str] = []
    usage: dict = {}
    status = "unknown"

    async with websockets.connect(ws_url, subprotocols=["realtime"], max_size=None) as ws:
        await ws.send(json.dumps({"type": "session.update", "session": {}}))
        t0 = time.perf_counter()
        for i in range(0, len(pcm), frame):
            chunk = pcm[i : i + frame]
            await ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode(),
                    }
                )
            )
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await ws.send(json.dumps({"type": "response.create"}))

        deadline = time.perf_counter() + RESPONSE_TIMEOUT_S
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise SystemExit("timed out waiting for response.done")
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            event = json.loads(raw)
            kind = event.get("type")
            now = time.perf_counter()
            if kind == "error":
                raise SystemExit(f"realtime error: {event.get('error')}")
            if kind == "response.created" and created is None:
                created = now - t0
            elif kind == "response.output_audio_transcript.delta":
                transcript.append(event.get("delta") or "")
            elif kind == "response.output_audio.delta":
                if first_audio is None:
                    first_audio = now - t0
                audio += base64.b64decode(event.get("delta") or "")
            elif kind == "response.done":
                done = now - t0
                response = event.get("response") or {}
                status = response.get("status") or "unknown"
                usage = response.get("usage") or {}
                break

    if first_audio is None or not audio:
        raise SystemExit("the model returned no reply audio")

    return {
        "turn_ttft_ms": round((created or first_audio) * 1000, 1),
        "first_audio_latency_ms": round(first_audio * 1000, 1),
        "reply_audio_ms": round(len(audio) / 2 / SPEECH_RATE * 1000, 1),
        "stream_wall_ms": round((done - first_audio) * 1000, 1),
        "realtime_factor": round(len(audio) / 2 / SPEECH_RATE / max(done - first_audio, 1e-6), 3),
        "output_tokens": usage.get("output_tokens"),
        "input_tokens": usage.get("input_tokens"),
        "status": status,
        "transcript": "".join(transcript).strip(),
        "audio_pcm": bytes(audio),
    }


def summarise(runs: list[dict]) -> dict:
    def med(key: str) -> float:
        return round(statistics.median([r[key] for r in runs]), 3)

    return {
        "turn_ttft_ms": med("turn_ttft_ms"),
        "first_audio_latency_ms": med("first_audio_latency_ms"),
        "reply_audio_ms": med("reply_audio_ms"),
        "realtime_factor": med("realtime_factor"),
        "output_tokens": med("output_tokens") if runs[0]["output_tokens"] else None,
        "runs": len(runs),
    }


def main() -> int:
    global OMLX  # noqa: PLW0603 - --base-url is a per-run override

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", help="write the JSON report here")
    ap.add_argument("--base-url", default=OMLX, help="oMLX base URL")
    ap.add_argument("--voice", help="TTS voice for the prompt turn")
    ap.add_argument("--prompt-text", default=PROMPT_TEXT)
    ap.add_argument("--skip-transcript", action="store_true",
                    help="skip the ASR round trip (no WER gate)")
    args = ap.parse_args()

    OMLX = args.base_url.rstrip("/")

    caps = probe(args.model)
    print(f"model            {args.model}")
    print(f"realtime voices  {caps['realtime_voices'] or '(single built-in voice)'}")
    print(f"tts voices       {caps['tts_voices'] or '(none)'}")
    print(f"capabilities     {caps['capabilities']}")

    pcm_prompt = synthesize(args.model, args.prompt_text, args.voice)
    print(f"prompt audio     {len(pcm_prompt) / 2 / SPEECH_RATE:.2f} s")

    runs: list[dict] = []
    for i in range(args.runs):
        result = asyncio.run(run_turn(args.model, pcm_prompt))
        runs.append(result)
        print(
            f"run {i + 1}/{args.runs}        "
            f"ttft={result['turn_ttft_ms']:.0f} ms  "
            f"first_audio={result['first_audio_latency_ms']:.0f} ms  "
            f"reply={result['reply_audio_ms']:.0f} ms  "
            f"rtf={result['realtime_factor']:.2f}  status={result['status']}"
        )

    summary = summarise(runs)
    summary["transcript"] = runs[-1]["transcript"]

    transcript_wer = None
    if not args.skip_transcript:
        heard = transcribe(args.model, runs[-1]["audio_pcm"])
        transcript_wer = round(wer(summary["transcript"], heard), 4)
        summary["retranscribed"] = heard
        summary["transcript_wer"] = transcript_wer
        print(f"transcript       {summary['transcript']!r}")
        print(f"re-transcribed   {heard!r}")
        print(f"roundtrip wer    {transcript_wer:.4f}")

    report = {
        "model": args.model,
        "capabilities": caps,
        "prompt_text": args.prompt_text,
        "summary": summary,
        "runs": [{k: v for k, v in r.items() if k != "audio_pcm"} for r in runs],
    }
    if args.out:
        import pathlib

        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote            {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
