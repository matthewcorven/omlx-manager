#!/usr/bin/env python3
"""Generate a synthetic OCR ground-truth corpus.

OCR models cannot be tuned on decode throughput the way a text model can: the
target is *accuracy against ground truth*, and there is no way to eyeball that.
oMLX's accuracy suite has no OCR benchmark, so this script manufactures one.

It renders known text at known positions with PIL, which makes ground truth
exact and free. Real scanned documents have no ground truth without manual
labelling, and hand-labelling is not reproducible across sessions.

Pages are 1024x1024 to match the model's `candidate_resolutions`. Bounding boxes
are recorded in the model's own 0-1000 normalised space, which is what
`<BLOCK>label[x0, y0, x1, y1]` emits.

Output: <out>/manifest.json (committed) and <out>/<page>.png (derived, ignored).

    python3 scripts/ocr_corpus.py --out results/non-llm/Unlimited-OCR-2-8bit/corpus
"""

from __future__ import annotations

import argparse
import json
import pathlib

from PIL import Image, ImageDraw, ImageFont

PAGE = 1024
FONT_DIR = pathlib.Path("/System/Library/Fonts/Supplemental")
REGULAR = FONT_DIR / "Arial.ttf"
BOLD = FONT_DIR / "Arial Bold.ttf"

INK = (17, 17, 17)
PAPER = (255, 255, 255)


def font(path: pathlib.Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def norm(box: tuple[float, float, float, float]) -> list[int]:
    """Pixel bbox -> the model's 0-1000 normalised space."""
    x0, y0, x1, y1 = box
    return [
        max(0, min(1000, round(x0 / PAGE * 1000))),
        max(0, min(1000, round(y0 / PAGE * 1000))),
        max(0, min(1000, round(x1 / PAGE * 1000))),
        max(0, min(1000, round(y1 / PAGE * 1000))),
    ]


class Page:
    def __init__(self, name: str, bg=PAPER, ink=INK):
        self.name = name
        self.image = Image.new("RGB", (PAGE, PAGE), bg)
        self.draw = ImageDraw.Draw(self.image)
        self.ink = ink
        self.blocks: list[dict] = []

    def text(
        self,
        label: str,
        body: str,
        xy: tuple[int, int],
        fnt: ImageFont.FreeTypeFont,
        width: int | None = None,
        leading: int = 6,
    ) -> None:
        """Draw `body`, wrapping to `width` px. One block per drawn line group."""
        lines = wrap(self.draw, body, fnt, width) if width else [body]
        x, y = xy
        top = y
        for line in lines:
            self.draw.text((x, y), line, font=fnt, fill=self.ink)
            y += fnt.size + leading
        right = max(x + self.draw.textlength(line, font=fnt) for line in lines)
        self.blocks.append(
            {
                "label": label,
                "bbox": norm((x, top, right, y - leading)),
                "text": " ".join(lines),
            }
        )

    def rotate(self, degrees: float) -> None:
        """Rotate the page and carry the recorded boxes with it.

        PIL rotates about the image centre, so each box corner is mapped
        through the same transform. The axis-aligned hull of the rotated
        corners is the new box.
        """
        import math

        self.image = self.image.rotate(degrees, resample=Image.BICUBIC, fillcolor=PAPER)
        self.draw = ImageDraw.Draw(self.image)
        rad = math.radians(degrees)
        cos, sin = math.cos(rad), math.sin(rad)
        c = PAGE / 2.0
        for b in self.blocks:
            x0, y0, x1, y1 = (v / 1000.0 * PAGE for v in b["bbox"])
            pts = []
            for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                dx, dy = px - c, py - c
                pts.append((c + dx * cos + dy * sin, c - dx * sin + dy * cos))
            b["bbox"] = norm(
                (
                    min(p[0] for p in pts),
                    min(p[1] for p in pts),
                    max(p[0] for p in pts),
                    max(p[1] for p in pts),
                )
            )

    def rule(self, y: int, x0: int = 60, x1: int = PAGE - 60, w: int = 2) -> None:
        self.draw.line([(x0, y), (x1, y)], fill=self.ink, width=w)

    def save(self, out: pathlib.Path) -> dict:
        self.image.save(out / f"{self.name}.png")
        return {
            "name": self.name,
            "image": f"{self.name}.png",
            "size": [PAGE, PAGE],
            "blocks": self.blocks,
        }


def wrap(draw, body: str, fnt, width: int) -> list[str]:
    words, lines, cur = body.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=fnt) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


LOREM = (
    "The quarterly review found that throughput improved across every region "
    "while operating cost stayed flat. Field engineers reported fewer "
    "interruptions and a shorter mean time to recovery."
)
LOREM2 = (
    "A second pass confirmed the result. The committee asked for a written "
    "summary before the next planning cycle so that the assumptions could be "
    "checked against the original forecast."
)
LOREM3 = (
    "Nothing in the data suggested a regression. Two outliers were traced to a "
    "misconfigured sensor and excluded from the final tally."
)


def page_clean() -> Page:
    p = Page("clean")
    p.text("title", "Annual Operations Review", (60, 60), font(BOLD, 40))
    p.rule(120)
    p.text("text", LOREM, (60, 150), font(REGULAR, 24), width=PAGE - 120, leading=10)
    p.text("text", LOREM2, (60, 300), font(REGULAR, 24), width=PAGE - 120, leading=10)
    p.text("footer", "Page 1 of 1", (60, 960), font(REGULAR, 18))
    return p


def page_dense() -> Page:
    p = Page("dense")
    p.text("title", "Appendix B — Detailed Findings", (50, 40), font(BOLD, 28))
    y = 100
    for body in (LOREM, LOREM2, LOREM3, LOREM, LOREM2):
        p.text("text", body, (50, y), font(REGULAR, 15), width=PAGE - 100, leading=3)
        y += 150
    return p


def page_table() -> Page:
    p = Page("table")
    p.text("title", "Regional Summary", (60, 50), font(BOLD, 32))
    rows = [
        ("Region", "Units", "Revenue", "Delta"),
        ("North", "1,204", "48,120", "+3.1%"),
        ("South", "988", "39,004", "-0.4%"),
        ("East", "1,551", "61,772", "+7.8%"),
        ("West", "742", "29,318", "+1.2%"),
    ]
    x0, y0, cw, rh = 60, 140, 220, 70
    fnt = font(REGULAR, 22)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            p.draw.rectangle(
                [x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh],
                outline=p.ink,
                width=2,
            )
            p.draw.text((x0 + c * cw + 12, y0 + r * rh + 20), cell, font=fnt, fill=p.ink)
            p.blocks.append(
                {
                    "label": "table",
                    "bbox": norm((x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)),
                    "text": cell,
                }
            )
    p.text("footer", "Source: internal ledger, Q3", (60, 960), font(REGULAR, 18))
    return p


def page_twocol() -> Page:
    p = Page("twocol")
    p.text("title", "Two Column Layout", (60, 50), font(BOLD, 34))
    p.rule(110)
    colw = (PAGE - 180) // 2
    p.text("text", LOREM, (60, 150), font(REGULAR, 20), width=colw, leading=8)
    p.text("text", LOREM2, (60 + colw + 60, 150), font(REGULAR, 20), width=colw, leading=8)
    p.text("text", LOREM3, (60, 500), font(REGULAR, 20), width=colw, leading=8)
    p.text("text", LOREM, (60 + colw + 60, 500), font(REGULAR, 20), width=colw, leading=8)
    return p


def page_small() -> Page:
    p = Page("small")
    p.text("title", "Fine Print", (60, 50), font(BOLD, 26))
    y = 120
    for body in (LOREM, LOREM2, LOREM3, LOREM, LOREM2, LOREM3):
        p.text("text", body, (60, y), font(REGULAR, 11), width=PAGE - 120, leading=2)
        y += 120
    return p


def page_lowcontrast() -> Page:
    p = Page("lowcontrast", bg=(246, 246, 244), ink=(150, 150, 148))
    p.text("title", "Faded Scan", (60, 60), font(BOLD, 36))
    p.text("text", LOREM, (60, 160), font(REGULAR, 22), width=PAGE - 120, leading=9)
    p.text("text", LOREM2, (60, 320), font(REGULAR, 22), width=PAGE - 120, leading=9)
    return p


def page_rotated() -> Page:
    p = Page("rotated")
    p.text("title", "Skewed Capture", (60, 60), font(BOLD, 36))
    p.text("text", LOREM, (60, 160), font(REGULAR, 22), width=PAGE - 160, leading=9)
    p.text("text", LOREM2, (60, 320), font(REGULAR, 22), width=PAGE - 160, leading=9)
    p.rotate(3.0)
    return p


def page_mixed() -> Page:
    p = Page("mixed")
    p.text("title", "Field Report", (60, 50), font(BOLD, 34))
    p.text("text", LOREM3, (60, 120), font(REGULAR, 20), width=PAGE - 120, leading=8)
    x0, y0, cw, rh = 60, 260, 300, 60
    fnt = font(REGULAR, 20)
    for r, row in enumerate([("Item", "Count"), ("Sensors", "42"), ("Relays", "17")]):
        for c, cell in enumerate(row):
            p.draw.rectangle(
                [x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh],
                outline=p.ink,
                width=2,
            )
            p.draw.text((x0 + c * cw + 10, y0 + r * rh + 16), cell, font=fnt, fill=p.ink)
            p.blocks.append(
                {
                    "label": "table",
                    "bbox": norm((x0 + c * cw, y0 + r * rh, x0 + (c + 1) * cw, y0 + (r + 1) * rh)),
                    "text": cell,
                }
            )
    p.text("text", LOREM2, (60, 520), font(REGULAR, 20), width=PAGE - 120, leading=8)
    p.text("footer", "Report 2024-11", (60, 960), font(REGULAR, 18))
    return p


def page_mixedcase() -> Page:
    """Identifiers, punctuation and digits that a language prior will "fix"."""
    p = Page("mixedcase")
    p.text("title", "Serial Numbers", (60, 50), font(BOLD, 32))
    p.text(
        "text",
        "Unit A7X-0042 shipped on 2024-11-03. Reference O0Il1|S5B8 must be "
        "transcribed exactly: 0O 1l I| 5S 8B. Cost was 1,204.50 not 1204.5.",
        (60, 130),
        font(REGULAR, 20),
        width=PAGE - 120,
        leading=8,
    )
    p.text(
        "text",
        "Hash 9f2c4e7a1b, port 8443, ratio 0.00042, code ZQ-77/xx. "
        "Do not normalise: e-mail ops@example.org, tel +1 (555) 010-4477.",
        (60, 300),
        font(REGULAR, 20),
        width=PAGE - 120,
        leading=8,
    )
    return p


def page_handwriting() -> Page:
    """Italic serif at low weight — the closest synthetic stand-in for a scan."""
    p = Page("handwriting")
    italic = FONT_DIR / "Times New Roman Italic.ttf"
    p.text("title", "Field Notes", (60, 50), font(italic, 34))
    p.text("text", LOREM, (60, 140), font(italic, 19), width=PAGE - 140, leading=7)
    p.text("text", LOREM2, (60, 300), font(italic, 19), width=PAGE - 140, leading=7)
    p.text("text", LOREM3, (60, 460), font(italic, 19), width=PAGE - 140, leading=7)
    return p


def page_noise() -> Page:
    """Salt-and-pepper speckle over normal text — a fax or a bad photocopy."""
    import random

    p = Page("noise")
    p.text("title", "Degraded Copy", (60, 50), font(BOLD, 34))
    p.text("text", LOREM, (60, 140), font(REGULAR, 20), width=PAGE - 120, leading=8)
    p.text("text", LOREM2, (60, 300), font(REGULAR, 20), width=PAGE - 120, leading=8)
    rng = random.Random(20241103)
    px = p.image.load()
    for _ in range(24000):
        x, y = rng.randrange(PAGE), rng.randrange(PAGE)
        v = rng.randrange(0, 90) if rng.random() < 0.5 else rng.randrange(170, 256)
        px[x, y] = (v, v, v)
    return p


def page_multipage() -> Page:
    """A page whose text continues past the bottom, to exercise cross_* labels."""
    p = Page("multipage")
    p.text("title", "Continued Report", (60, 50), font(BOLD, 32))
    y = 130
    for body in (LOREM, LOREM2, LOREM3, LOREM, LOREM2):
        p.text("text", body, (60, y), font(REGULAR, 18), width=PAGE - 120, leading=6)
        y += 150
    return p


PAGES = [
    page_clean,
    page_dense,
    page_table,
    page_twocol,
    page_small,
    page_lowcontrast,
    page_rotated,
    page_mixed,
    page_mixedcase,
    page_handwriting,
    page_noise,
    page_multipage,
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {"page_size": PAGE, "coord_space": "0-1000", "pages": []}
    for build in PAGES:
        page = build()
        manifest["pages"].append(page.save(out))

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    total = sum(len(p["blocks"]) for p in manifest["pages"])
    print(f"wrote {len(manifest['pages'])} pages, {total} ground-truth blocks -> {out}")


if __name__ == "__main__":
    main()
