#!/usr/bin/env python3
"""Score an oMLX OCR model against a ground-truth corpus.

OCR models have no decode-throughput tuning target. The axes that matter are
accuracy, latency, and memory, and accuracy is the only one that cannot be
eyeballed. This harness turns the model's `<PAGE><BLOCK>label[x0, y0, x1, y1]
<FORK>text` output into numbers against `scripts/ocr_corpus.py` ground truth.

Metrics, per page and aggregated:

  cer            character error rate over the concatenated page text
                 (Levenshtein / len(truth)); lower is better
  block_recall   fraction of ground-truth blocks matched by an emitted block
  block_precision fraction of emitted blocks that matched a ground-truth block
  iou            mean IoU of matched block boxes, in 0-1000 space
  order          Kendall tau of matched blocks' reading order; 1.0 = perfect
  finish         `stop` or `length`; `length` means the score is a max_tokens
                 artifact and the page must be re-run with a larger budget

Two gates run before any score is trusted:

  determinism    the same page twice at temperature 0 must be byte-identical
  truncation     finish_reason must be `stop`

Usage:

    python3 scripts/ocr_eval.py --model Unlimited-OCR-2-8bit \
        --corpus results/non-llm/Unlimited-OCR-2-8bit/corpus \
        --out results/non-llm/Unlimited-OCR-2-8bit/eval/baseline.json
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import statistics
import sys
import time
import urllib.request

OMLX = "http://127.0.0.1:8001"
PROMPT = "Multi page parsing."

# The model emits an optional hierarchy tag between the label and the box,
# e.g. `<BLOCK>title<LEVEL1>[58, 60, 550, 103]<FORK>...`. The tag is not part
# of the label vocabulary and must not break parsing.
BLOCK_RE = re.compile(
    r"<BLOCK>(?P<label>[a-z_]+)(?:<[A-Z0-9_]+>)*"
    r"\[(?P<x0>\d+),\s*(?P<y0>\d+),\s*(?P<x1>\d+),\s*(?P<y1>\d+)\]"
    r"<FORK>(?P<text>[^\n]*)"
)


# ---------------------------------------------------------------- transport


def post(path: str, body: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(
        OMLX + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ocr(model: str, image: pathlib.Path, max_tokens: int, temperature: float = 0.0) -> dict:
    b64 = base64.b64encode(image.read_bytes()).decode()
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        OMLX + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    chunks: list[str] = []
    usage = None
    finish = None
    error = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                error = obj["error"].get("message", str(obj["error"]))
                continue
            if obj.get("usage"):
                usage = obj["usage"]
            for choice in obj.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    chunks.append(delta["content"])
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
    text = "".join(chunks)
    return {
        "text": text,
        "error": error,
        "finish_reason": finish,
        "wall_ms": round((time.time() - started) * 1000, 1),
        "usage": usage,
    }


# ------------------------------------------------------------------ parsing


def degenerate(text: str) -> str | None:
    """Detect output that is structurally not OCR, whatever the score says.

    A page that emits no blocks, or that collapses into a repeated token, is a
    failure even when `finish_reason` is `stop`. This is the gate that catches
    a processor misconfiguration: at `max_crops: 4` the model answers a dense
    real page with `11. 11. 11. ...` and stops cleanly.
    """
    if not text.strip():
        return "empty output"
    if "<BLOCK>" not in text:
        return "no <BLOCK> markup"
    tokens = text.split()
    if len(tokens) >= 40:
        head = tokens[:40]
        if len(set(head)) <= 3:
            return f"repeated-token collapse ({head[0]!r} x{len(head)})"
    return None


def parse_blocks(text: str) -> list[dict]:
    out = []
    for m in BLOCK_RE.finditer(text):
        out.append(
            {
                "label": m.group("label"),
                "bbox": [int(m.group(k)) for k in ("x0", "y0", "x1", "y1")],
                "text": m.group("text").strip(),
            }
        )
    return out


# ------------------------------------------------------------------ scoring


def normalise(s: str) -> str:
    s = s.replace("\u2014", "-").replace("\u2013", "-").replace("\u2019", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def flatten_table(s: str) -> str:
    """The model emits a whole table as one block of HTML. Compare cell text."""
    if "<table" not in s:
        return s
    cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", s, re.S)
    return " ".join(cells) if cells else re.sub(r"<[^>]+>", " ", s)


def merge_table_blocks(blocks: list[dict]) -> list[dict]:
    """Ground truth records one block per cell; the model records one per table.

    Collapse runs of adjacent `table` blocks into a single region so the two
    representations are comparable.
    """
    out: list[dict] = []
    for b in blocks:
        if b["label"] == "table" and out and out[-1]["label"] == "table":
            prev = out[-1]
            prev["bbox"] = [
                min(prev["bbox"][0], b["bbox"][0]),
                min(prev["bbox"][1], b["bbox"][1]),
                max(prev["bbox"][2], b["bbox"][2]),
                max(prev["bbox"][3], b["bbox"][3]),
            ]
            prev["text"] = prev["text"] + " " + b["text"]
        else:
            out.append(dict(b))
    return out


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def iou(a: list[int], b: list[int]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / (area_a + area_b - inter)


def kendall_tau(pairs: list[tuple[int, int]]) -> float | None:
    """pairs = (truth_index, pred_index) for matched blocks."""
    n = len(pairs)
    if n < 2:
        return None
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = pairs[i][0] - pairs[j][0]
            b = pairs[i][1] - pairs[j][1]
            if a * b > 0:
                conc += 1
            elif a * b < 0:
                disc += 1
    total = conc + disc
    return round((conc - disc) / total, 4) if total else None


def score_page(truth: dict, pred_blocks: list[dict]) -> dict:
    truth_blocks = merge_table_blocks(truth["blocks"])
    for b in pred_blocks:
        b["text"] = flatten_table(b["text"])
    truth_text = " ".join(b["text"] for b in truth_blocks)
    # CER is over recognised text only. Scoring the raw stream would count the
    # markup itself as errors.
    pred_text = " ".join(b["text"] for b in pred_blocks)

    t_norm, p_norm = normalise(truth_text), normalise(pred_text)
    cer = round(levenshtein(t_norm, p_norm) / max(1, len(t_norm)), 4)

    # Greedy match on text similarity, then on IoU, so a block that is found
    # but mis-boxed still counts as found.
    used: set[int] = set()
    pairs: list[tuple[int, int]] = []
    ious: list[float] = []
    for ti, tb in enumerate(truth_blocks):
        best, best_j = 0.0, None
        for pi, pb in enumerate(pred_blocks):
            if pi in used:
                continue
            t_sim = 1.0 - levenshtein(normalise(tb["text"]), normalise(pb["text"])) / max(
                1, len(normalise(tb["text"]))
            )
            t_sim = max(0.0, t_sim)
            overlap = iou(tb["bbox"], pb["bbox"])
            combined = 0.6 * t_sim + 0.4 * overlap
            if combined > best:
                best, best_j = combined, pi
        if best_j is not None and best >= 0.5:
            used.add(best_j)
            pairs.append((ti, best_j))
            ious.append(iou(tb["bbox"], pred_blocks[best_j]["bbox"]))

    matched = len(pairs)
    return {
        "cer": cer,
        "block_recall": round(matched / max(1, len(truth_blocks)), 4),
        "block_precision": round(matched / max(1, len(pred_blocks)), 4),
        "iou": round(statistics.fmean(ious), 4) if ious else None,
        "order_tau": kendall_tau(pairs),
        "truth_blocks": len(truth_blocks),
        "pred_blocks": len(pred_blocks),
    }


# --------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--pages", nargs="*", help="subset of page names")
    ap.add_argument("--skip-determinism", action="store_true")
    args = ap.parse_args()

    corpus = pathlib.Path(args.corpus)
    manifest = json.loads((corpus / "manifest.json").read_text())
    pages = [p for p in manifest["pages"] if not args.pages or p["name"] in args.pages]

    results = []
    for page in pages:
        image = corpus / page["image"]
        run = ocr(args.model, image, args.max_tokens)
        blocks = parse_blocks(run["text"])
        row = {
            "page": page["name"],
            "error": run["error"],
            "finish_reason": run["finish_reason"],
            "wall_ms": run["wall_ms"],
            "usage": run["usage"],
            "raw": run["text"],
            **score_page(page, blocks),
        }

        row["degenerate"] = degenerate(run["text"])
        if run["error"]:
            row["status"] = "error"
        elif row["degenerate"]:
            row["status"] = "degenerate"
        elif run["finish_reason"] != "stop":
            row["status"] = "truncated"
        else:
            row["status"] = "ok"

        if not args.skip_determinism and not run["error"]:
            again = ocr(args.model, image, args.max_tokens)
            row["deterministic"] = again["text"] == run["text"]

        results.append(row)
        print(
            f"{page['name']:<12} cer={row['cer']:.4f} recall={row['block_recall']:.2f} "
            f"prec={row['block_precision']:.2f} iou={row['iou']} tau={row['order_tau']} "
            f"finish={row['finish_reason']} det={row.get('deterministic')} "
            f"{row['wall_ms']:.0f}ms"
            + (f" ERROR {row['error']}" if row["error"] else "")
            + (f" DEGENERATE {row['degenerate']}" if row["degenerate"] else ""),
            flush=True,
        )

    scored = [r for r in results if r["status"] == "ok"]
    summary = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "prompt": PROMPT,
        "pages": len(results),
        "pages_complete": len(scored),
        "errored": [r["page"] for r in results if r["status"] == "error"],
        "degenerate": [r["page"] for r in results if r["status"] == "degenerate"],
        "truncated": [r["page"] for r in results if r["status"] == "truncated"],
        "nondeterministic": [r["page"] for r in results if r.get("deterministic") is False],
        "mean_cer": round(statistics.fmean(r["cer"] for r in scored), 4) if scored else None,
        "mean_block_recall": round(statistics.fmean(r["block_recall"] for r in scored), 4)
        if scored
        else None,
        "mean_block_precision": round(statistics.fmean(r["block_precision"] for r in scored), 4)
        if scored
        else None,
        "mean_iou": round(statistics.fmean(r["iou"] for r in scored if r["iou"] is not None), 4)
        if any(r["iou"] is not None for r in scored)
        else None,
        "mean_order_tau": round(
            statistics.fmean(r["order_tau"] for r in scored if r["order_tau"] is not None), 4
        )
        if any(r["order_tau"] is not None for r in scored)
        else None,
        "mean_wall_ms": round(statistics.fmean(r["wall_ms"] for r in results), 1),
        "results": results,
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")

    print("\n--- summary ---")
    for k in (
        "pages",
        "pages_complete",
        "errored",
        "degenerate",
        "truncated",
        "nondeterministic",
        "mean_cer",
        "mean_block_recall",
        "mean_block_precision",
        "mean_iou",
        "mean_order_tau",
        "mean_wall_ms",
    ):
        print(f"{k:<22} {summary[k]}")
    print(f"-> {out}")

    if summary["errored"]:
        print("\nFAIL: request errors — the model produced no output on these pages")
        return 4
    if summary["degenerate"]:
        print("\nFAIL: degenerate output — the model did not produce OCR on these pages")
        return 5
    if summary["truncated"]:
        print("\nFAIL: truncated pages — raise --max-tokens before trusting any score")
        return 2
    if summary["nondeterministic"]:
        print("\nFAIL: non-deterministic output at temperature 0")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
