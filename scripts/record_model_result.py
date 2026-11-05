#!/usr/bin/env python3
"""
scripts/record_model_result.py

Unified CLI for validating, adding, updating, and synchronizing benchmark results
across CSV and sibling Markdown files for Generative Text, OCR, Decision, Image
Generation, and Voice models.

Project Invariant: All model benchmark results must be recorded ONLY EVER by this script.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Root of repo (where results/ and docs/ live)
REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results"
DASHBOARD = REPO_ROOT / "dashboard" / "index.html"

SCHEMAS: Dict[str, Dict[str, Any]] = {
    "generative-text": {
        "aliases": ["text", "generative-text", "llm"],
        "csv_file": RESULTS_DIR / "generative-text.csv",
        "md_file": RESULTS_DIR / "generative-text.md",
        "title": "Generative Text Model Benchmark Results",
        "columns": [
            "Model", "Quant", "Params", "Download Size", "Resident Size",
            "oMLX Version",
            "Baseline TTFT (ms)", "Baseline Decode (tps)",
            "Final TTFT (ms)", "Final Decode (tps)",
            "Final Settings", "Quality Pass Rate", "Notes"
        ],
        "numeric_validators": {
            "Baseline TTFT (ms)": lambda v: float(v) >= 0,
            "Baseline Decode (tps)": lambda v: float(v) > 0,
            "Final TTFT (ms)": lambda v: float(v) >= 0,
            "Final Decode (tps)": lambda v: float(v) > 0,
        }
    },
    "ocr": {
        "aliases": ["ocr"],
        "csv_file": RESULTS_DIR / "ocr.csv",
        "md_file": RESULTS_DIR / "ocr.md",
        "title": "OCR Model Benchmark Results",
        "columns": [
            "Model", "Quant", "Checkpoint/Package", "Resident Size",
            "oMLX Version",
            "CER (Character Error Rate)", "WER (Word Error Rate)",
            "Avg Page Latency (s)", "Max Tokens", "Quality/Status", "Notes"
        ],
        "numeric_validators": {
            "CER (Character Error Rate)": lambda v: 0.0 <= float(v) <= 1.0,
            "WER (Word Error Rate)": lambda v: v.strip().upper() == "N/A" or (0.0 <= float(v) <= 1.0),
            "Avg Page Latency (s)": lambda v: float(v) > 0,
            "Max Tokens": lambda v: int(v) > 0,
        }
    },
    "decision": {
        "aliases": ["decision"],
        "csv_file": RESULTS_DIR / "decision.csv",
        "md_file": RESULTS_DIR / "decision.md",
        "title": "Decision Model Benchmark Results",
        "columns": [
            "Model", "Quant", "Params", "Resident Size",
            "oMLX Version",
            "Gate 1 (Accuracy)", "Gate 2 (ECE / Calibration)",
            "Gate 3 (Log Loss)", "Gate 4 (Media Score)",
            "Mean TTFT", "Samples", "Notes"
        ],
        "numeric_validators": {
            "Gate 1 (Accuracy)": lambda v: 0.0 <= float(v) <= 1.0,
            "Gate 2 (ECE / Calibration)": lambda v: 0.0 <= float(v) <= 1.0,
            "Gate 3 (Log Loss)": lambda v: float(v) >= 0.0,
            "Samples": lambda v: int(v) > 0,
        }
    },
    "image-generation": {
        "aliases": ["image", "image-generation"],
        "csv_file": RESULTS_DIR / "image-generation.csv",
        "md_file": RESULTS_DIR / "image-generation.md",
        "title": "Image Generation Model Benchmark Results",
        "columns": [
            "Model", "Quant", "Steps", "Resolution", "oMLX Version",
            "TTFT/Step Latency", "Total Latency",
            "VRAM/Resident", "Quality/CLIP", "Notes"
        ],
        "numeric_validators": {
            "Steps": lambda v: int(v) > 0,
        }
    },
    "voice": {
        "aliases": ["voice", "realtime", "speech", "audio"],
        "csv_file": RESULTS_DIR / "voice.csv",
        "md_file": RESULTS_DIR / "voice.md",
        "title": "Conversational Voice Model Benchmark Results",
        "columns": [
            "Model", "Quant", "Params", "Resident Size",
            "oMLX Version",
            "Turn TTFT (ms)", "First Audio Latency (ms)",
            "Reply Audio (ms)", "Speech Real-Time Factor",
            "Transcript WER", "Voices/Languages", "Quality/Status", "Notes"
        ],
        "numeric_validators": {
            "Turn TTFT (ms)": lambda v: float(v) >= 0.0,
            "First Audio Latency (ms)": lambda v: float(v) >= 0.0,
            "Reply Audio (ms)": lambda v: float(v) > 0.0,
            "Speech Real-Time Factor": lambda v: float(v) > 0.0,
            "Transcript WER": lambda v: v.strip().upper() == "N/A" or (0.0 <= float(v) <= 1.0),
        }
    }
}


def resolve_type(type_input: str) -> str:
    """Normalize user input to canonical schema key."""
    norm = type_input.strip().lower()
    for key, spec in SCHEMAS.items():
        if norm == key or norm in spec["aliases"]:
            return key
    raise ValueError(f"Unknown model type '{type_input}'. Supported types: {list(SCHEMAS.keys())}")


def validate_row(canonical_type: str, row: Dict[str, Any]) -> Dict[str, str]:
    """Strictly validate that a row complies with the schema for canonical_type."""
    spec = SCHEMAS[canonical_type]
    expected_cols = spec["columns"]
    validated_row: Dict[str, str] = {}

    missing = [col for col in expected_cols if col not in row or str(row[col]).strip() == ""]
    # Notes can be empty or omitted
    missing_mandatory = [c for c in missing if c != "Notes"]
    if missing_mandatory:
        raise ValueError(f"Missing mandatory column(s) for {canonical_type}: {missing_mandatory}")

    for col in expected_cols:
        val = str(row.get(col, "")).strip()
        if col in spec.get("numeric_validators", {}):
            validator = spec["numeric_validators"][col]
            try:
                if not validator(val):
                    raise ValueError(f"Value '{val}' for column '{col}' failed numeric range constraint.")
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid numeric format for column '{col}': '{val}'. Error: {e}")
        validated_row[col] = val

    return validated_row


def read_csv_data(csv_path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read existing CSV file and return (headers, rows)."""
    if not csv_path.exists():
        return [], []
    with open(csv_path, mode="r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return [], []
        headers = [h.strip() for h in headers]
        rows: List[Dict[str, str]] = []
        for r in reader:
            if not r or all(c.strip() == "" for c in r):
                continue
            row_dict = {headers[i]: r[i].strip() if i < len(r) else "" for i in range(len(headers))}
            rows.append(row_dict)
        return headers, rows


def escape_markdown_cell(val: str) -> str:
    """Escape vertical bars for markdown table."""
    return str(val).replace("|", "\\|")


def parse_markdown_cells(md_line: str) -> List[str]:
    """Split a markdown table row into cells, respecting escaped pipes (\\|)."""
    # Split on '|' that is not preceded by an unescaped backslash
    raw_cells = re.split(r'(?<!\\)\|', md_line.strip())
    # Drop first and last empty elements caused by leading/trailing '|'
    if raw_cells and raw_cells[0].strip() == "":
        raw_cells = raw_cells[1:]
    if raw_cells and raw_cells[-1].strip() == "":
        raw_cells = raw_cells[:-1]
    return [c.strip().replace(r"\|", "|") for c in raw_cells]


def generate_markdown_content(title: str, columns: List[str], rows: List[Dict[str, str]]) -> str:
    """Generate canonical markdown document from rows."""
    lines = [f"# {title}", ""]
    header_line = "| " + " | ".join(columns) + " |"
    divider_line = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines.append(header_line)
    lines.append(divider_line)

    for r in rows:
        row_cells = [escape_markdown_cell(r.get(col, "")) for col in columns]
        lines.append("| " + " | ".join(row_cells) + " |")

    lines.append("")  # trailing newline
    return "\n".join(lines)


def write_csv_and_markdown(canonical_type: str, rows: List[Dict[str, str]],
                           sync_embed: bool = True) -> None:
    """Atomically write both CSV and sibling Markdown table.

    Also refreshes the dashboard's baked-in copy of the tables. Every recorded
    change must reach the UI's offline fallback, or the fallback starts serving
    numbers the tables no longer contain.
    """
    spec = SCHEMAS[canonical_type]
    csv_path: Path = spec["csv_file"]
    md_path: Path = spec["md_file"]
    columns: List[str] = spec["columns"]
    title: str = spec["title"]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temp_csv = csv_path.with_suffix(".csv.tmp")
    with open(temp_csv, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for r in rows:
            writer.writerow([r.get(c, "") for c in columns])
    temp_csv.replace(csv_path)

    temp_md = md_path.with_suffix(".md.tmp")
    md_content = generate_markdown_content(title, columns, rows)
    with open(temp_md, mode="w", encoding="utf-8") as f:
        f.write(md_content)
    temp_md.replace(md_path)

    if sync_embed:
        try:
            regenerate_dashboard_embed(quiet=True)
        except SystemExit:
            # A missing dashboard must not block recording a benchmark.
            pass


def add_result(canonical_type: str, data: Dict[str, Any]) -> None:
    """Add a new model result row, enforcing uniqueness by Model name."""
    spec = SCHEMAS[canonical_type]
    validated = validate_row(canonical_type, data)
    model_name = validated["Model"]

    headers, existing_rows = read_csv_data(spec["csv_file"])
    for r in existing_rows:
        if r.get("Model") == model_name:
            raise ValueError(f"Model '{model_name}' already exists in {spec['csv_file']}. Use --update to modify it.")

    existing_rows.append(validated)
    write_csv_and_markdown(canonical_type, existing_rows)
    print(f"Successfully recorded new result for '{model_name}' in {canonical_type}.")


def update_result(canonical_type: str, model_name: str, data: Dict[str, Any]) -> None:
    """Update an existing model result row by Model name."""
    spec = SCHEMAS[canonical_type]
    headers, existing_rows = read_csv_data(spec["csv_file"])

    idx = -1
    for i, r in enumerate(existing_rows):
        if r.get("Model") == model_name:
            idx = i
            break

    if idx == -1:
        raise ValueError(f"Model '{model_name}' not found in {spec['csv_file']} for update.")

    updated_data = dict(existing_rows[idx])
    updated_data.update(data)
    updated_data["Model"] = model_name
    validated = validate_row(canonical_type, updated_data)

    existing_rows[idx] = validated
    write_csv_and_markdown(canonical_type, existing_rows)
    print(f"Successfully updated result for '{model_name}' in {canonical_type}.")


def validate_all_results() -> bool:
    """Validate all CSV and sibling Markdown files across all schemas."""
    all_ok = True
    print("Validating all benchmark result tables...")

    for canonical_type, spec in SCHEMAS.items():
        csv_path: Path = spec["csv_file"]
        md_path: Path = spec["md_file"]
        columns: List[str] = spec["columns"]

        if not csv_path.exists():
            print(f"[FAIL] Missing CSV file: {csv_path}")
            all_ok = False
            continue

        if not md_path.exists():
            print(f"[FAIL] Missing sibling Markdown file: {md_path}")
            all_ok = False
            continue

        headers, rows = read_csv_data(csv_path)
        if headers != columns:
            print(f"[FAIL] {csv_path.name} header mismatch.\nExpected: {columns}\nActual:   {headers}")
            all_ok = False

        for i, row in enumerate(rows):
            try:
                validate_row(canonical_type, row)
            except Exception as e:
                print(f"[FAIL] {csv_path.name} row {i+1} ('{row.get('Model')}') validation error: {e}")
                all_ok = False

        # Read markdown table rows and check 1:1 synchronization
        with open(md_path, mode="r", encoding="utf-8") as f:
            md_lines = [l.strip() for l in f if l.strip().startswith("|")]

        # MD must have at least header + separator
        if len(md_lines) < 2:
            print(f"[FAIL] {md_path.name} has malformed markdown table structure.")
            all_ok = False
        else:
            md_data_rows = md_lines[2:]
            if len(md_data_rows) != len(rows):
                print(f"[FAIL] {canonical_type}: Row count mismatch between CSV ({len(rows)}) and Markdown ({len(md_data_rows)}).")
                all_ok = False
            else:
                for idx, (csv_r, md_line) in enumerate(zip(rows, md_data_rows)):
                    cells = parse_markdown_cells(md_line)
                    for c_idx, col in enumerate(columns):
                        expected_val = csv_r.get(col, "")
                        actual_val = cells[c_idx] if c_idx < len(cells) else ""
                        if expected_val != actual_val:
                            print(f"[FAIL] {canonical_type} row {idx+1} cell mismatch on '{col}': CSV='{expected_val}' vs MD='{actual_val}'")
                            all_ok = False

    if all_ok:
        print("[PASS] All CSV and Markdown results are valid and 100% synchronized.")
    return all_ok


def regenerate_markdown(canonical_type: Optional[str] = None) -> None:
    """Regenerate Markdown tables directly from CSV data."""
    types = [canonical_type] if canonical_type else list(SCHEMAS.keys())
    for t in types:
        spec = SCHEMAS[t]
        headers, rows = read_csv_data(spec["csv_file"])
        write_csv_and_markdown(t, rows)
        print(f"Regenerated {spec['md_file'].name} from {spec['csv_file'].name}.")


EMBED_START = "const EMBEDDED_DATA = "
EMBED_END = ";\n"


def regenerate_dashboard_embed(quiet: bool = False) -> None:
    """Rewrite the dashboard's EMBEDDED_DATA block from the committed CSVs.

    The dashboard keeps a baked-in copy of every table so it still renders when
    opened straight from `file://` or when a `fetch` fails. That copy used to be
    maintained by hand, so it silently went stale — it was still serving
    pre-0.7.4 numbers and did not know about models added after it was written.
    Generating it from the CSVs makes the fallback correct by construction.
    """
    if not DASHBOARD.is_file():
        raise SystemExit(f"dashboard not found: {DASHBOARD}")

    html = DASHBOARD.read_text(encoding="utf-8")
    start = html.find(EMBED_START)
    if start == -1:
        raise SystemExit(f"no {EMBED_START!r} block in {DASHBOARD}")
    end = html.find(EMBED_END, start)
    if end == -1:
        raise SystemExit("unterminated EMBEDDED_DATA block")
    end += len(EMBED_END)
    # Consume a duplicated `};` left behind by an older generator bug, so
    # running this twice cannot leave the page syntactically broken.
    while html[end:].lstrip("\n").startswith("};"):
        skipped = len(html[end:]) - len(html[end:].lstrip("\n"))
        end += skipped + 2
        while html[end:end + 1] == "\n":
            end += 1

    payload = {
        t: (SCHEMAS[t]["csv_file"]).read_text(encoding="utf-8")
        for t in SCHEMAS
        if SCHEMAS[t]["csv_file"].is_file()
    }
    # json.dumps produces a valid JS object literal for this data (only
    # strings), and it escapes the newlines the dashboard's parser splits on.
    block = EMBED_START + json.dumps(payload, indent=2, ensure_ascii=False) + EMBED_END

    DASHBOARD.write_text(html[:start] + block + html[end:], encoding="utf-8")
    if not quiet:
        total = sum(len(v.splitlines()) for v in payload.values())
        print(f"Regenerated dashboard EMBEDDED_DATA from {len(payload)} CSV(s) "
              f"({total} data lines).")


def migrate_add_version(version: str) -> None:
    """Insert the `oMLX Version` column into every table and backfill it.

    Rows are stamped with `version` because that is the only honest value: the
    tables were re-measured on it. Printing the change is deliberate — a
    migration that silently stamps a version onto numbers taken on a different
    release would defeat the whole point of the column.
    """
    for canonical_type, spec in SCHEMAS.items():
        csv_path: Path = spec["csv_file"]
        headers, rows = read_csv_data(csv_path)
        if not headers:
            continue
        if "oMLX Version" in headers:
            print(f"{csv_path.name}: already has oMLX Version, leaving rows alone")
            continue
        # Place it right after Resident Size where the schema declares it,
        # falling back to the end for tables without that column.
        anchor = "Resident Size" if "Resident Size" in headers else None
        if anchor:
            pos = headers.index(anchor) + 1
        else:
            pos = len(headers) - 1  # before Notes

        out_rows = []
        for row in rows:
            new_row = {}
            for i, h in enumerate(headers):
                if i == pos:
                    new_row["oMLX Version"] = version
                new_row[h] = row.get(h, "")
            if pos >= len(headers):
                new_row["oMLX Version"] = version
            out_rows.append(new_row)

        new_headers = headers[:pos] + ["oMLX Version"] + headers[pos:]
        spec["columns"] = new_headers
        write_csv_and_markdown(canonical_type, out_rows)
        print(f"{csv_path.name}: added oMLX Version={version} to {len(out_rows)} row(s)")


def main():
    parser = argparse.ArgumentParser(
        description="Unified model benchmark results recording and validation CLI."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", action="store_true", help="Add a new model result.")
    group.add_argument("--update", action="store_true", help="Update an existing model result.")
    group.add_argument("--validate-all", action="store_true", help="Validate all CSV and MD files.")
    group.add_argument("--generate-markdown", action="store_true", help="Regenerate Markdown files from CSV.")
    group.add_argument("--generate-embed", action="store_true",
                       help="Regenerate dashboard/index.html EMBEDDED_DATA from the CSVs.")
    group.add_argument("--migrate-add-version", metavar="VERSION", type=str,
                       help="Add the oMLX Version column and backfill it with VERSION.")

    parser.add_argument("--type", type=str, help="Model type: text, ocr, decision, or image.")
    parser.add_argument("--model", type=str, help="Model name (required for --update if not in data).")
    parser.add_argument("--data", type=str, help="JSON string containing row fields.")
    parser.add_argument("--file", type=str, help="JSON file containing row fields.")

    args = parser.parse_args()

    if args.validate_all:
        ok = validate_all_results()
        sys.exit(0 if ok else 1)

    if args.generate_markdown:
        canonical = resolve_type(args.type) if args.type else None
        regenerate_markdown(canonical)
        sys.exit(0)

    if args.generate_embed:
        regenerate_dashboard_embed()
        sys.exit(0)

    if args.migrate_add_version:
        migrate_add_version(args.migrate_add_version)
        regenerate_dashboard_embed()
        sys.exit(0)

    if not args.type:
        parser.error("--type is required when using --add or --update.")

    canonical_type = resolve_type(args.type)

    row_data: Dict[str, Any] = {}
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            row_data = json.load(f)
    elif args.data:
        row_data = json.loads(args.data)
    else:
        parser.error("Either --data or --file is required for --add or --update.")

    if args.add:
        add_result(canonical_type, row_data)
    elif args.update:
        model_name = args.model or row_data.get("Model")
        if not model_name:
            parser.error("--model is required for --update if 'Model' key is not present in data.")
        update_result(canonical_type, model_name, row_data)


if __name__ == "__main__":
    main()
