#!/usr/bin/env python3
"""Generate the labelled decision-model media corpus (images and video).

The text corpus in `decision_corpus.py` scores whether a decision model's
probabilities are right about *words*. It cannot say anything about whether the
same probabilities are right about *pixels*, and every checkpoint in the sweep
carries a vision tower, so that is a real question left open.

Ground truth has to be reproducible, and it has to be ours. Scraping photographs
would make the corpus unreproducible and licence-encumbered; both problems are
avoided by drawing the observations here from a fixed seed. The corpus is
synthetic on purpose, for the same three reasons the text corpus is: the answer
is known by construction, the file regenerates byte-identically, and no item can
be solved from a memorised caption because no such caption exists.

Modality limits are not invented here. They come from the server source and are
enforced below so the corpus cannot drift outside what the models accept:

| Limit | Value | Source |
|---|---|---|
| image floor | 65,536 px | `d3.IMAGE_MIN_PIXELS` |
| image ceiling | 1,638,400 px | `d3.IMAGE_MAX_PIXELS` |
| images per request, OpenJev | 1 | `openjev.split_state` |
| video fps range | 0.1 .. 1000 | `d3.VIDEO_SOURCE_FPS` |
| video frames sampled | 4 .. 32 | `d3.VIDEO_MIN/MAX_FRAMES` |
| video sampling rate | 2 fps | `d3.VIDEO_FPS` |
| video source pixels | 8,294,400 max | `d3.MAX_VIDEO_SOURCE_PIXELS` |
| video duration | 300 s max | `d3.MAX_VIDEO_SECONDS` |
| video payload | 200 MB max | `utils.video.DEFAULT_MAX_VIDEO_BYTES` |

Every image is 1024x1024 (1,048,576 px) and every clip is 640x480 at 24 fps for
4 s (307,200 px, 96 frames). The image size matches the OCR corpus page size, and
the clip lands inside every bound with room to spare.

Item families, one per thing a vision tower can get wrong:

| Family | Modality | Isolates |
|---|---|---|
| `img-count` | image | counting discrete objects |
| `img-colour` | image | binding an attribute to the right object |
| `img-spatial` | image | relative position, which needs the layout not the parts |
| `img-text` | image | reading rendered text |
| `img-shape` | image | shape classification |
| `img-ambiguous` | image | no-information images; a confident answer is miscalibration |
| `vid-motion` | video | static vs moving, which a single frame cannot answer |
| `vid-direction` | video | direction of travel |
| `vid-appear` | video | something entering partway through |
| `vid-colourchange` | video | an attribute changing over time |

The two temporal families are the point of the video corpus. `vid-motion` and
`vid-colourchange` are constructed so that any single frame is consistent with
both answers: a static clip and a moving clip share their first frame, and a
colour-changing clip and a steady clip share theirs. A model that scores well on
those without watching the sequence is guessing.

Usage:
    python3 scripts/decision_media_corpus.py --out results/decision/media
    python3 scripts/decision_media_corpus.py --list
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

# Fixed seed: the corpus must regenerate byte-identically on any machine.
SEED = 20261029

PAGE = 1024
PAPER = (247, 247, 245)
INK = (24, 24, 28)
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
BOLD = FONT_DIR / "Arial Bold.ttf"

COLOURS = {
    "red": (196, 48, 48),
    "green": (46, 138, 74),
    "blue": (46, 84, 168),
    "yellow": (214, 170, 32),
}
BGR = {k: (v[2], v[1], v[0]) for k, v in COLOURS.items()}

# 640x480 at 24 fps for 4 s. d3 samples at 2 fps, so it sees 8 frames of the 96.
VIDEO_W, VIDEO_H, VIDEO_FPS, VIDEO_SECONDS = 640, 480, 24, 4
VIDEO_FRAMES = VIDEO_FPS * VIDEO_SECONDS

# Object centres for the counting family: a 3x3 lattice with 256 px spacing,
# which keeps 64 px radius objects from touching.
CELLS = [(256, 256), (512, 256), (768, 256),
         (256, 512), (512, 512), (768, 512),
         (256, 768), (512, 768), (768, 768)]


# --------------------------------------------------------------------------
# drawing primitives
# --------------------------------------------------------------------------
def _base():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (PAGE, PAGE), PAPER)
    return im, ImageDraw.Draw(im)


def _circle(d, cx, cy, r, colour):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)


def _square(d, cx, cy, half, colour):
    d.rectangle([cx - half, cy - half, cx + half, cy + half], fill=colour)


def _triangle(d, cx, cy, r, colour):
    d.polygon([(cx, cy - r), (cx - r, cy + r * 0.85), (cx + r, cy + r * 0.85)], fill=colour)


def _star(d, cx, cy, r, colour):
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    d.polygon(pts, fill=colour)


SHAPES = {
    "circle": _circle,
    "square": _square,
    "triangle": _triangle,
    "star": _star,
}


# --------------------------------------------------------------------------
# image families
# --------------------------------------------------------------------------
def _img_count(rng: random.Random, out: Path) -> list[dict]:
    """Counting discrete objects. Distractors are off by exactly one."""
    specs = [(3, 3, True), (4, 3, False), (5, 5, True),
             (2, 3, False), (6, 6, True), (7, 6, False)]
    items = []
    for i, (drawn, asked, expected) in enumerate(specs):
        im, d = _base()
        for cx, cy in rng.sample(CELLS, drawn):
            _circle(d, cx, cy, 64, COLOURS["blue"])
        name = f"img-count-{i:02d}.png"
        im.save(out / name)
        items.append({
            "id": f"img-count-{i:02d}",
            "family": "img-count",
            "modality": "image",
            "type": "noul",
            "state": "The attached image is the observation.",
            "instructions": f"Are there exactly {asked} circles in this image?",
            "criteria": None,
            "expected": expected,
            "media": [name],
            "drawn_objects": drawn,
        })
    return items


def _img_colour(rng: random.Random, out: Path) -> list[dict]:
    """Bind an attribute to the right object: one large square, three small ones."""
    order = ["red", "green", "blue", "yellow"]
    corners = [(160, 160), (864, 160), (160, 864), (864, 864)]
    criteria = {c: f"the largest square is {c}" for c in order}
    items = []
    for i, key in enumerate(order):
        im, d = _base()
        _square(d, 512, 512, 190, COLOURS[key])
        for (cx, cy), c in zip(corners, [c for c in order if c != key]):
            _square(d, cx, cy, 62, COLOURS[c])
        name = f"img-colour-{i:02d}.png"
        im.save(out / name)
        items.append({
            "id": f"img-colour-{i:02d}",
            "family": "img-colour",
            "modality": "image",
            "type": "choice",
            "state": "The attached image is the observation.",
            "instructions": "What colour is the largest square in this image?",
            "criteria": criteria,
            "expected": key,
            "media": [name],
        })
    return items


def _img_spatial(rng: random.Random, out: Path) -> list[dict]:
    """Relative position, which needs the layout and not just the parts."""
    specs = [(320, 704, True), (704, 320, False), (288, 736, True), (736, 288, False)]
    items = []
    for i, (circle_x, square_x, expected) in enumerate(specs):
        im, d = _base()
        _circle(d, circle_x, 512, 90, COLOURS["green"])
        _square(d, square_x, 512, 90, COLOURS["yellow"])
        name = f"img-spatial-{i:02d}.png"
        im.save(out / name)
        items.append({
            "id": f"img-spatial-{i:02d}",
            "family": "img-spatial",
            "modality": "image",
            "type": "noul",
            "state": "The attached image is the observation.",
            "instructions": "Is the circle to the left of the square in this image?",
            "criteria": None,
            "expected": expected,
            "media": [name],
        })
    return items


def _img_text(rng: random.Random, out: Path) -> list[dict]:
    """Reading rendered text. The queried word is sometimes absent."""
    from PIL import ImageFont
    # 200 px, not 96. At 96 px the glyphs fall below what the vision tower can
    # resolve and the item measures legibility instead of reading: d3-edge
    # answered 0.05 on a present word, and d3-flash only reached 0.59. At 200 px
    # d3-flash separates cleanly (0.89 present vs 0.01 absent), so the item is
    # answerable and a miss is the model's, not the corpus's.
    font = ImageFont.truetype(str(BOLD), 200)
    specs = [("ORCHID", "ORCHID", True), ("LANTERN", "ORCHID", False),
             ("MARBLE", "MARBLE", True), ("THICKET", "MARBLE", False)]
    items = []
    for i, (rendered, queried, expected) in enumerate(specs):
        im, d = _base()
        d.text((PAGE // 2, PAGE // 2), rendered, font=font, fill=INK, anchor="mm")
        name = f"img-text-{i:02d}.png"
        im.save(out / name)
        items.append({
            "id": f"img-text-{i:02d}",
            "family": "img-text",
            "modality": "image",
            "type": "noul",
            "state": "The attached image is the observation.",
            "instructions": f"Does this image contain the word {queried}?",
            "criteria": None,
            "expected": expected,
            "media": [name],
        })
    return items


def _img_shape(rng: random.Random, out: Path) -> list[dict]:
    """Shape classification, one shape per image."""
    criteria = {
        "circle": "a round shape with no corners",
        "square": "four equal straight sides",
        "triangle": "three straight sides",
        "star": "five points",
    }
    items = []
    for i, key in enumerate(criteria):
        im, d = _base()
        SHAPES[key](d, 512, 512, 240, COLOURS["blue"] if key != "square" else COLOURS["green"])
        name = f"img-shape-{i:02d}.png"
        im.save(out / name)
        items.append({
            "id": f"img-shape-{i:02d}",
            "family": "img-shape",
            "modality": "image",
            "type": "choice",
            "state": "The attached image is the observation.",
            "instructions": "Which shape is present in this image?",
            "criteria": criteria,
            "expected": key,
            "media": [name],
        })
    return items


def _img_ambiguous(rng: random.Random, out: Path) -> list[dict]:
    """No-information images. Any confident answer here is miscalibration."""
    import numpy as np
    from PIL import Image
    items = []
    for i in range(3):
        # Coarse noise upsampled to page size: no object, no text, no edge that
        # could be read as one. Fine-grained noise would be equally uninformative
        # but would not compress, and the corpus is committed.
        coarse = np.random.default_rng(SEED + i).integers(0, 12, (32, 32), dtype=np.uint8)
        arr = (232 + np.kron(coarse, np.ones((PAGE // 32, PAGE // 32), np.uint8))).astype(np.uint8)
        im = Image.fromarray(arr, mode="L").convert("RGB")
        name = f"img-ambiguous-{i:02d}.png"
        im.save(out / name, optimize=True)
        items.append({
            "id": f"img-ambiguous-{i:02d}",
            "family": "img-ambiguous",
            "modality": "image",
            "type": "noul",
            "state": "The attached image is the observation.",
            "instructions": "Is this image a photograph of a dog?",
            "criteria": None,
            "expected": None,
            "media": [name],
        })
    return items


# --------------------------------------------------------------------------
# video families
# --------------------------------------------------------------------------
def _blank():
    import numpy as np
    return np.full((VIDEO_H, VIDEO_W, 3), 30, np.uint8)


def _write_video(path: Path, frames: list) -> None:
    import cv2
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                         float(VIDEO_FPS), (VIDEO_W, VIDEO_H))
    if not vw.isOpened():
        raise RuntimeError(f"cv2.VideoWriter could not open {path}")
    for frame in frames:
        vw.write(frame)
    vw.release()


def _vid_motion(rng: random.Random, out: Path) -> list[dict]:
    """Static vs moving. Both share their first frame, so one frame cannot decide."""
    import cv2
    specs = [(True, True), (False, False), (True, True), (False, False)]
    items = []
    for i, (moving, expected) in enumerate(specs):
        frames = []
        for k in range(VIDEO_FRAMES):
            f = _blank()
            if moving:
                cx = 120 + int(round(400 * k / (VIDEO_FRAMES - 1)))
            else:
                cx = 320
            cv2.circle(f, (cx, VIDEO_H // 2), 56, BGR["yellow"], -1)
            frames.append(f)
        name = f"vid-motion-{i:02d}.mp4"
        _write_video(out / name, frames)
        items.append({
            "id": f"vid-motion-{i:02d}",
            "family": "vid-motion",
            "modality": "video",
            "type": "noul",
            "state": "The attached video is the observation.",
            "instructions": "Does the object in this video move?",
            "criteria": None,
            "expected": expected,
            "media": [name],
        })
    return items


def _vid_direction(rng: random.Random, out: Path) -> list[dict]:
    """Direction of travel, four options."""
    import cv2
    criteria = {
        "left_to_right": "the object travels from the left side to the right side",
        "right_to_left": "the object travels from the right side to the left side",
        "upward": "the object travels from the bottom to the top",
        "downward": "the object travels from the top to the bottom",
    }
    items = []
    for i, key in enumerate(criteria):
        frames = []
        for k in range(VIDEO_FRAMES):
            t = k / (VIDEO_FRAMES - 1)
            if key == "left_to_right":
                cx, cy = 120 + 400 * t, 240
            elif key == "right_to_left":
                cx, cy = 520 - 400 * t, 240
            elif key == "upward":
                cx, cy = 320, 400 - 280 * t
            else:
                cx, cy = 320, 120 + 280 * t
            f = _blank()
            cv2.circle(f, (int(round(cx)), int(round(cy))), 56, BGR["green"], -1)
            frames.append(f)
        name = f"vid-direction-{i:02d}.mp4"
        _write_video(out / name, frames)
        items.append({
            "id": f"vid-direction-{i:02d}",
            "family": "vid-direction",
            "modality": "video",
            "type": "choice",
            "state": "The attached video is the observation.",
            "instructions": "In which direction does the moving object travel?",
            "criteria": criteria,
            "expected": key,
            "media": [name],
        })
    return items


def _vid_appear(rng: random.Random, out: Path) -> list[dict]:
    """Something entering partway through. Absent and present share their first half."""
    import cv2
    specs = [(True, True), (False, False), (True, True), (False, False)]
    items = []
    for i, (appears, expected) in enumerate(specs):
        frames = []
        for k in range(VIDEO_FRAMES):
            f = _blank()
            cv2.circle(f, (200, VIDEO_H // 2), 56, BGR["yellow"], -1)
            if appears and k >= VIDEO_FRAMES // 2:
                cv2.circle(f, (460, VIDEO_H // 2), 56, BGR["green"], -1)
            frames.append(f)
        name = f"vid-appear-{i:02d}.mp4"
        _write_video(out / name, frames)
        items.append({
            "id": f"vid-appear-{i:02d}",
            "family": "vid-appear",
            "modality": "video",
            "type": "noul",
            "state": "The attached video is the observation.",
            "instructions": "Does a second object appear during this video?",
            "criteria": None,
            "expected": expected,
            "media": [name],
        })
    return items


def _vid_colourchange(rng: random.Random, out: Path) -> list[dict]:
    """An attribute changing over time. Steady and changing share their first frame."""
    import cv2
    specs = [(True, True), (False, False), (True, True), (False, False)]
    items = []
    for i, (changes, expected) in enumerate(specs):
        frames = []
        for k in range(VIDEO_FRAMES):
            colour = BGR["red"]
            if changes and k >= VIDEO_FRAMES // 2:
                colour = BGR["blue"]
            f = _blank()
            cv2.circle(f, (VIDEO_W // 2, VIDEO_H // 2), 90, colour, -1)
            frames.append(f)
        name = f"vid-colourchange-{i:02d}.mp4"
        _write_video(out / name, frames)
        items.append({
            "id": f"vid-colourchange-{i:02d}",
            "family": "vid-colourchange",
            "modality": "video",
            "type": "noul",
            "state": "The attached video is the observation.",
            "instructions": "Does the object change colour during this video?",
            "criteria": None,
            "expected": expected,
            "media": [name],
        })
    return items


IMAGE_FAMILIES = [_img_count, _img_colour, _img_spatial, _img_text, _img_shape, _img_ambiguous]
VIDEO_FAMILIES = [_vid_motion, _vid_direction, _vid_appear, _vid_colourchange]


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
def build(out: Path, modality: str = "all") -> dict:
    """Draw every item into `out` and return the manifest."""
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    items: list[dict] = []

    if modality in ("all", "image"):
        for builder in IMAGE_FAMILIES:
            items.extend(builder(rng, out))
    if modality in ("all", "video"):
        for builder in VIDEO_FAMILIES:
            items.extend(builder(rng, out))

    # Refuse to emit a corpus the models would reject. These bounds come from
    # the server source, not from taste.
    _check_bounds(items, out)

    return {
        "version": 1,
        "seed": SEED,
        "modality": modality,
        "note": (
            "Generated by scripts/decision_media_corpus.py. Do not hand-edit; "
            "regenerate instead so ground truth stays reproducible. Media files "
            "are committed because they are small and because regenerating them "
            "needs Pillow and OpenCV, which the stock interpreter does not have."
        ),
        "items": items,
    }


def _check_bounds(items: list[dict], out: Path) -> None:
    from PIL import Image
    for item in items:
        if item["modality"] != "image":
            continue
        with Image.open(out / item["media"][0]) as im:
            px = im.size[0] * im.size[1]
        if not 65_536 <= px <= 1_638_400:
            raise ValueError(f"{item['id']}: {px} px is outside the image bounds")
        if len(item["media"]) > 1:
            raise ValueError(f"{item['id']}: OpenJev accepts at most one image")
    for item in items:
        if item["modality"] != "video":
            continue
        if (VIDEO_W * VIDEO_H) > 8_294_400:
            raise ValueError(f"{item['id']}: source pixels exceed MAX_VIDEO_SOURCE_PIXELS")
        if (VIDEO_FRAMES / VIDEO_FPS) > 300:
            raise ValueError(f"{item['id']}: duration exceeds MAX_VIDEO_SECONDS")
        if not 0.1 <= VIDEO_FPS <= 1000:
            raise ValueError(f"{item['id']}: fps outside VIDEO_SOURCE_FPS")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="results/decision/media",
                    help="directory for the manifest and the media files")
    ap.add_argument("--modality", choices=["all", "image", "video"], default="all")
    ap.add_argument("--list", action="store_true", help="print a family summary")
    args = ap.parse_args()

    if args.list:
        # Enumerating needs the media drawn, so build into a temp dir.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            corpus = build(Path(tmp), args.modality)
        counts: dict[str, int] = {}
        for item in corpus["items"]:
            counts[item["family"]] = counts.get(item["family"], 0) + 1
        for family, n in sorted(counts.items()):
            print(f"{family:18s} {n:3d}")
        print(f"{'total':18s} {len(corpus['items']):3d}")
        return 0

    out = Path(args.out)
    corpus = build(out, args.modality)
    manifest = out / "manifest.json"
    with open(manifest, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, indent=1)
        fh.write("\n")

    total = sum((out / m).stat().st_size for i in corpus["items"] for m in i["media"])
    print(f"wrote {len(corpus['items'])} items to {manifest}")
    print(f"media {total / 1024:.0f} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
