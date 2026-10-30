#!/usr/bin/env python3
"""Generate the labelled decision-model corpus.

Decision models answer typed questions with probabilities instead of generating
text, so there is no decode throughput to measure and no sampling to tune. The
only thing worth scoring is whether the probabilities are *right* and *honest*.
That needs ground truth, and ground truth has to be reproducible across
sessions, so the corpus is generated here rather than hand-labelled.

Every item is a `(state, question, expected)` triple. `expected` is the correct
answer in the question's own space:

- `noul`  -> `true` / `false`
- `choice` -> the correct option key
- `score` -> the correct level index

Items are grouped into *families* so a failure can be attributed. Each family
isolates one thing a decision model can get wrong:

| Family | Isolates |
|---|---|
| `sentiment` | the floor: trivially separable text |
| `arithmetic` | a verifiable answer with no lexical shortcut |
| `negation` | polarity flips that bag-of-words models miss |
| `ordering` | comparison against a threshold |
| `multilabel` | choice among 4+ options, not just yes/no |
| `graded` | score questions on an ordered scale |
| `longstate` | the same question with a padded state, to expose truncation |
| `ambiguous` | genuinely 50/50 items; a confident answer here is miscalibration |

The `ambiguous` family is the important one and the least obvious. A model that
scores 1.0 on every item looks perfect on accuracy and is useless, because it
carries no information. Accuracy alone cannot see that; the calibration metrics
in `decision_eval.py` can.

Usage:
    python3 scripts/decision_corpus.py --out results/decision/corpus.json
    python3 scripts/decision_corpus.py --list
"""
from __future__ import annotations

import argparse
import json
import random
import sys

# Fixed seed: the corpus must regenerate byte-identically on any machine.
SEED = 20261029

# --------------------------------------------------------------------------
# noul items: (state, instructions, expected_bool, family)
# --------------------------------------------------------------------------
NOUL_ITEMS = [
    # sentiment -- the floor
    ("I love this product, it works perfectly and arrived early.",
     "Is the sentiment of this text positive?", True, "sentiment"),
    ("This is the worst purchase I have ever made. Nothing works.",
     "Is the sentiment of this text positive?", False, "sentiment"),
    ("The support team resolved my issue in minutes. Excellent service.",
     "Is the sentiment of this text positive?", True, "sentiment"),
    ("Delivery was late, the box was crushed, and the item was missing.",
     "Is the sentiment of this text positive?", False, "sentiment"),

    # arithmetic -- verifiable, no lexical shortcut
    ("17 + 26 = 43", "Is this arithmetic statement correct?", True, "arithmetic"),
    ("17 + 26 = 41", "Is this arithmetic statement correct?", False, "arithmetic"),
    ("9 * 8 = 72", "Is this arithmetic statement correct?", True, "arithmetic"),
    ("9 * 8 = 74", "Is this arithmetic statement correct?", False, "arithmetic"),
    ("144 / 12 = 12", "Is this arithmetic statement correct?", True, "arithmetic"),
    ("144 / 12 = 14", "Is this arithmetic statement correct?", False, "arithmetic"),

    # negation -- polarity flips
    ("The build did not fail.", "Does this text report a build failure?", False, "negation"),
    ("The build failed.", "Does this text report a build failure?", True, "negation"),
    ("It is not true that the server is down.",
     "Does this text report that the server is down?", False, "negation"),
    ("It is not true that the server is up.",
     "Does this text report that the server is down?", True, "negation"),

    # ordering -- comparison against a threshold
    ("The package weighs 2.4 kg.", "Does the package weigh more than 2 kg?", True, "ordering"),
    ("The package weighs 1.4 kg.", "Does the package weigh more than 2 kg?", False, "ordering"),
    ("The job took 45 minutes.", "Did the job take longer than an hour?", False, "ordering"),
    ("The job took 95 minutes.", "Did the job take longer than an hour?", True, "ordering"),

    # ambiguous -- genuinely undecidable; confidence here is the signal
    ("The film was released in the spring.", "Was the film good?", None, "ambiguous"),
    ("The meeting is scheduled for Tuesday.", "Is the meeting important?", None, "ambiguous"),
    ("The report has twelve pages.", "Is the report well written?", None, "ambiguous"),
    ("The car is blue.", "Is the car fast?", None, "ambiguous"),
]

# --------------------------------------------------------------------------
# choice items: (state, instructions, {key: description}, expected_key, family)
# --------------------------------------------------------------------------
CHOICE_ITEMS = [
    ("I was charged twice for the same order and nobody has replied to my emails.",
     "What is the primary intent of this message?",
     {"billing": "a payment, charge or invoice problem",
      "shipping": "a delivery or tracking problem",
      "technical": "a bug or malfunction",
      "account": "a login or profile problem"},
     "billing", "multilabel"),

    ("The app crashes every time I open the settings screen.",
     "What is the primary intent of this message?",
     {"billing": "a payment, charge or invoice problem",
      "shipping": "a delivery or tracking problem",
      "technical": "a bug or malfunction",
      "account": "a login or profile problem"},
     "technical", "multilabel"),

    ("My parcel has said 'in transit' for eleven days and the tracking has not moved.",
     "What is the primary intent of this message?",
     {"billing": "a payment, charge or invoice problem",
      "shipping": "a delivery or tracking problem",
      "technical": "a bug or malfunction",
      "account": "a login or profile problem"},
     "shipping", "multilabel"),

    ("I cannot reset my password because the reset email never arrives.",
     "What is the primary intent of this message?",
     {"billing": "a payment, charge or invoice problem",
      "shipping": "a delivery or tracking problem",
      "technical": "a bug or malfunction",
      "account": "a login or profile problem"},
     "account", "multilabel"),

    ("def add(a, b):\n    return a - b",
     "What does this function do?",
     {"adds": "returns the sum of the arguments",
      "subtracts": "returns the difference of the arguments",
      "multiplies": "returns the product of the arguments",
      "compares": "returns a boolean comparison"},
     "subtracts", "multilabel"),

    ("SELECT * FROM orders WHERE total > 100;",
     "What does this query return?",
     {"all_rows": "every row in the table",
      "expensive_orders": "rows whose total exceeds 100",
      "cheap_orders": "rows whose total is below 100",
      "count": "a single count of rows"},
     "expensive_orders", "multilabel"),
]

# --------------------------------------------------------------------------
# score items: (state, instructions, [level labels], expected_index, family)
# --------------------------------------------------------------------------
SCORE_ITEMS = [
    ("The site has been completely down for six hours and we have lost all traffic.",
     "How severe is this incident?",
     ["no impact", "minor", "moderate", "major", "total outage"], 4, "graded"),
    ("One user reports a typo in the help centre.",
     "How severe is this incident?",
     ["no impact", "minor", "moderate", "major", "total outage"], 1, "graded"),
    ("Checkout is slow for about 5% of users but still completes.",
     "How severe is this incident?",
     ["no impact", "minor", "moderate", "major", "total outage"], 2, "graded"),
    ("The primary database is unreachable; all writes are failing.",
     "How severe is this incident?",
     ["no impact", "minor", "moderate", "major", "total outage"], 4, "graded"),
    ("A background report is two minutes late.",
     "How severe is this incident?",
     ["no impact", "minor", "moderate", "major", "total outage"], 0, "graded"),
]

# Padding used by the longstate family. Deliberately low-information so the
# answer stays determined by the final sentence.
PAD_SENTENCE = (
    "The archive contains routine maintenance notes from the previous quarter "
    "and no action is required. "
)


def build() -> dict:
    """Assemble the corpus as a list of items with stable ids."""
    rng = random.Random(SEED)
    items: list[dict] = []

    for i, (state, instructions, expected, family) in enumerate(NOUL_ITEMS):
        items.append({
            "id": f"noul-{family}-{i:02d}",
            "family": family,
            "type": "noul",
            "state": state,
            "instructions": instructions,
            "criteria": None,
            "expected": expected,
        })

    for i, (state, instructions, criteria, expected, family) in enumerate(CHOICE_ITEMS):
        items.append({
            "id": f"choice-{family}-{i:02d}",
            "family": family,
            "type": "choice",
            "state": state,
            "instructions": instructions,
            "criteria": criteria,
            "expected": expected,
        })

    for i, (state, instructions, criteria, expected, family) in enumerate(SCORE_ITEMS):
        items.append({
            "id": f"score-{family}-{i:02d}",
            "family": family,
            "type": "score",
            "state": state,
            "instructions": instructions,
            "criteria": criteria,
            "expected": expected,
        })

    # longstate: the arithmetic items again, buried in padding. Same expected
    # answer, so a drop here is a context-handling fault, not a reasoning one.
    for i, (state, instructions, expected, _family) in enumerate(NOUL_ITEMS[4:10]):
        pad = PAD_SENTENCE * rng.choice([40, 120, 300])
        items.append({
            "id": f"noul-longstate-{i:02d}",
            "family": "longstate",
            "type": "noul",
            "state": pad + state,
            "instructions": instructions,
            "criteria": None,
            "expected": expected,
        })

    return {
        "version": 1,
        "seed": SEED,
        "note": (
            "Generated by scripts/decision_corpus.py. Do not hand-edit; "
            "regenerate instead so ground truth stays reproducible."
        ),
        "items": items,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", help="write the corpus JSON here")
    ap.add_argument("--list", action="store_true", help="print a family summary")
    args = ap.parse_args()

    corpus = build()

    if args.list:
        counts: dict[str, int] = {}
        for item in corpus["items"]:
            counts[item["family"]] = counts.get(item["family"], 0) + 1
        for family, n in sorted(counts.items()):
            print(f"{family:12s} {n:3d}")
        print(f"{'total':12s} {len(corpus['items']):3d}")
        return 0

    if not args.out:
        json.dump(corpus, sys.stdout, indent=1)
        print()
        return 0

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, indent=1)
        fh.write("\n")
    print(f"wrote {len(corpus['items'])} items to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
