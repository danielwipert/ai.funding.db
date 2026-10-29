"""Step 4: Turn a reviewed golden-set sheet into labels.jsonl (the answer key).

The sheet is a CSV with one company per row. The only columns you edit are
`label` (yes / no) and, if you like, `your_note`. Rows already in
labels.jsonl are skipped, so the file stays append-only.

Usage:
    python -m pipeline.labels labels/golden_set.csv
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.models import jsonl_lines

ROOT = Path(__file__).resolve().parent.parent
LABELS_PATH = ROOT / "labels.jsonl"
RUBRIC_VERSION = "v2"


def import_sheet(sheet_path: Path) -> None:
    existing = set()
    if LABELS_PATH.exists():
        existing = {json.loads(line)["accession_no"] for line in jsonl_lines(LABELS_PATH)}

    added, skipped, problems = 0, 0, []
    labeled_at = datetime.now(timezone.utc).isoformat()
    with sheet_path.open(newline="", encoding="utf-8-sig") as f, LABELS_PATH.open("a") as out:
        for row in csv.DictReader(f):
            label = row["label"].strip().lower()
            if label not in ("yes", "no"):
                problems.append(f"{row['company']}: label is {row['label']!r}, expected yes or no")
                continue
            if row["accession_no"] in existing:
                skipped += 1
                continue
            out.write(json.dumps({
                "accession_no": row["accession_no"],
                "cik": row["cik"].zfill(10),  # spreadsheets drop leading zeros
                "company_name": row["company"],
                "label": label,
                "category": row["category"],  # clear / hard
                "reason": row["reason"],
                "your_note": row.get("your_note", "").strip() or None,
                "homepage_url": row["homepage"] or None,
                "rubric_version": RUBRIC_VERSION,
                "labeled_at": labeled_at,
            }) + "\n")
            existing.add(row["accession_no"])
            added += 1

    print(f"Added {added} labels to {LABELS_PATH} ({skipped} already there)")
    for problem in problems:
        print(f"  skipped, fix and re-run: {problem}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sheet", type=Path, help="the reviewed CSV")
    import_sheet(parser.parse_args().sheet)


if __name__ == "__main__":
    main()
