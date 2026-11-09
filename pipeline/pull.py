"""Stage 1: Pull every Form D filed in a date window from EDGAR full-text search.

Writes runs/<run_id>/01_filings.jsonl with one row per filing.

Usage:
    python -m pipeline.pull                                   # the prior 7 days
    python -m pipeline.pull --since 2026-10-20 --until 2026-10-26
"""

import argparse
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pipeline.edgar import get_json
from pipeline.models import Filing

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
PAGE_SIZE = 100  # EDGAR returns at most 100 hits per page
SEARCH_TRIES = 3  # tries per page when EDGAR's reply has no "hits"
RUNS_DIR = Path(__file__).resolve().parent.parent / "runs"


def search_page(params: dict, tries: int = SEARCH_TRIES) -> dict:
    """Return one page of search results (the "hits" part of EDGAR's reply).

    EDGAR sometimes answers 200 OK with a body that has no "hits" (the
    2026-11-02 weekly run died on one). Status-code retries in edgar.py
    don't catch that, so wait and ask again here.
    """
    for attempt in range(1, tries + 1):
        reply = get_json(SEARCH_URL, params)
        if "hits" in reply:
            return reply["hits"]
        if attempt < tries:
            wait = 5 * 2 ** (attempt - 1)  # 5s, then 10s
            print(f"EDGAR reply had no results for {params['startdt']} (try {attempt}); retrying in {wait}s")
            time.sleep(wait)
    raise SystemExit(
        f"EDGAR search for {params['startdt']} gave no results after {tries} tries. "
        f"Last reply: {str(reply)[:300]}"
    )


def pull_day(day: date) -> list[dict]:
    """Return the raw search hits for every Form D (and D/A) filed on one day.

    Searching one day at a time keeps each query far below EDGAR's
    10,000-result cap, so a 90-day backfill works the same way as a week.
    """
    hits = []
    while True:
        params = {
            "forms": "D",  # also returns D/A amendments
            "dateRange": "custom",
            "startdt": day.isoformat(),
            "enddt": day.isoformat(),
            "from": len(hits),
        }
        page = search_page(params)
        hits.extend(page["hits"])
        if not page["hits"] or len(hits) >= page["total"]["value"]:
            return hits


def hit_to_filing(hit: dict, run_id: str, processed_at: datetime) -> Filing:
    source = hit["_source"]
    # display_names look like "Acme AI, Inc.  (CIK 0001234567)"; co-issuer
    # filings list several companies, and the first is the lead issuer.
    company_name = re.sub(r"\s*\(CIK \d+\)\s*$", "", source["display_names"][0])
    return Filing(
        accession_no=source["adsh"],
        cik=source["ciks"][0],
        company_name=company_name,
        filing_date=source["file_date"],
        run_id=run_id,
        processed_at=processed_at,
    )


def pull(since: date, until: date, run_id: str) -> Path:
    processed_at = datetime.now(timezone.utc)
    filings: dict[str, Filing] = {}
    day = since
    while day <= until:
        hits = pull_day(day)
        for hit in hits:
            filing = hit_to_filing(hit, run_id, processed_at)
            filings[filing.accession_no] = filing  # dedupe on accession number
        print(f"{day}: {len(hits)} filings")
        day += timedelta(days=1)

    out_path = RUNS_DIR / run_id / "01_filings.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Sorted, and the file is rewritten each time, so a re-run gives the same rows.
    rows = sorted(filings.values(), key=lambda f: (f.filing_date, f.accession_no))
    with out_path.open("w") as f:
        for filing in rows:
            f.write(filing.model_dump_json() + "\n")
    print(f"Wrote {len(rows)} filings to {out_path}")
    return out_path


def main() -> None:
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=date.fromisoformat, help="first filing date (default: 7 days ago)")
    parser.add_argument("--until", type=date.fromisoformat, default=yesterday, help="last filing date (default: yesterday)")
    parser.add_argument("--run-id", default=date.today().isoformat(), help="run folder name (default: today)")
    args = parser.parse_args()
    since = args.since or args.until - timedelta(days=6)
    pull(since, args.until, args.run_id)


if __name__ == "__main__":
    main()
