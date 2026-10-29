"""Stage 3: Structural filter. No model involved, only Form D fields.

Reads runs/<run_id>/02_parsed.jsonl and writes runs/<run_id>/03_filtered.jsonl.
Every row is kept in the output: survivors get passed_structural=True, the
rest get passed_structural=False plus a drop_reason, so any drop can be checked.

Usage:
    python -m pipeline.filter                    # today's run folder
    python -m pipeline.filter --run-id 2026-10-28
"""

import argparse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timezone

import requests

from pipeline.models import Filing
from pipeline.parse import RUNS_DIR, fetch_xml, parse_xml

# Decision 15: "Other" is kept because some AI startups tick the catch-all box.
# Decision 17: "Computers" added as cheap insurance.
KEEP_INDUSTRY_GROUPS = {"Other Technology", "Business Services", "Other", "Computers"}
# Decision 11: band on amount actually sold.
MIN_AMOUNT_SOLD = 1_000_000
MAX_AMOUNT_SOLD = 50_000_000


def previous_amount_sold(filing: Filing) -> int | None:
    """Amount sold on the filing this amendment amends (decision 16)."""
    data, _ = fetch_xml(filing.cik, filing.previous_accession_no)
    return parse_xml(data)["amount_sold_usd"]


def drop_reason(filing: Filing) -> str | None:
    """Return why a filing fails the filter, or None if it passes.

    Cheap checks come first so the amendment download only happens for
    filings that pass everything else.
    """
    if filing.parse_error:
        return f"parse error: {filing.parse_error}"
    if filing.industry_group not in KEEP_INDUSTRY_GROUPS:
        return f"industry group: {filing.industry_group}"
    sold = filing.amount_sold_usd
    if sold is None or not MIN_AMOUNT_SOLD <= sold <= MAX_AMOUNT_SOLD:
        return f"amount sold ${sold:,} outside $1M-$50M" if sold is not None else "amount sold missing"
    if filing.is_amendment:
        if not filing.previous_accession_no:
            return "amendment: no previous filing named"
        try:
            previous = previous_amount_sold(filing)
        except (requests.RequestException, ET.ParseError, ValueError) as e:
            # Precision over recall: if we can't confirm the rise, drop it.
            return f"amendment: previous filing unavailable ({type(e).__name__})"
        if previous is not None and sold <= previous:
            return f"amendment: amount sold did not rise (${previous:,} -> ${sold:,})"
    return None


def filter_run(run_id: str) -> None:
    in_path = RUNS_DIR / run_id / "02_parsed.jsonl"
    out_path = RUNS_DIR / run_id / "03_filtered.jsonl"
    filings = [Filing.model_validate_json(line) for line in in_path.read_text().splitlines()]
    processed_at = datetime.now(timezone.utc)

    reasons = Counter()
    with out_path.open("w") as out:
        for filing in filings:
            reason = drop_reason(filing)
            # Group reasons like "amount sold $500,000 outside ..." for the summary
            reasons[reason.split(" $")[0].split(" (")[0] if reason else "passed"] += 1
            filtered = filing.model_copy(update={
                "passed_structural": reason is None,
                "drop_reason": reason,
                "processed_at": processed_at,
            })
            out.write(filtered.model_dump_json() + "\n")

    print(f"Wrote {len(filings)} rows to {out_path}")
    for reason, count in reasons.most_common():
        print(f"  {count:5}  {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default=date.today().isoformat(), help="run folder name (default: today)")
    args = parser.parse_args()
    filter_run(args.run_id)


if __name__ == "__main__":
    main()
