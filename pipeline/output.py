"""Stage 7: Merge a run into dashboard/data.json and write the run summary.

- Shipped companies go into the main table, one row per company (CIK). A
  company already there keeps its row; a later filing only updates
  amount_sold_usd (and last_updated) when the amount rose.
- Review companies go into a separate "Needs review" list until you decide
  them in review.yml ("<cik>": yes / no). "yes" moves the company into the
  main table; every decision is also added to labels.jsonl (the golden set).
- contacted / note come from tracking.yml at build time; the pipeline never
  writes tracking.yml or review.yml.
- runs/<run_id>/summary.json records counts per stage, cost and runtime.

Usage:
    python -m pipeline.output                    # today's run folder
    python -m pipeline.output --run-id 2026-10-28
"""

import argparse
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from pipeline.labels import LABELS_PATH, RUBRIC_VERSION
from pipeline.models import Filing
from pipeline.parse import RUNS_DIR

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "dashboard" / "data.json"
TRACKING_PATH = ROOT / "tracking.yml"
REVIEW_PATH = ROOT / "review.yml"


def read_yaml(path: Path) -> dict:
    """A {cik: value} mapping; CIKs are zero-padded so 1234 and "0000001234" match."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return {str(cik).zfill(10): value for cik, value in data.items()}


def edgar_url(filing: Filing) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(filing.cik)}/"
            f"{filing.accession_no.replace('-', '')}/")


def company_row(filing: Filing, today: str) -> dict:
    """The dashboard columns for one company, from the filing that put it there."""
    a, b = filing.classify_a, filing.classify_b
    return {
        "cik": filing.cik,
        "company_name": filing.company_name,
        "homepage_url": filing.homepage_url,
        "filing_date": filing.filing_date.isoformat(),
        "amount_sold_usd": filing.amount_sold_usd,
        "state": filing.state,
        "description": a.description if a else "",
        "related_persons": [{"name": p.name, "relationships": p.relationships}
                            for p in filing.related_persons or []],
        "edgar_url": edgar_url(filing),
        "accession_no": filing.accession_no,
        "first_seen": today,
        "last_updated": today,
        # review rows only: why it needs a human
        "review_reason": filing.final_reason if filing.final == "review" else None,
        "homepage_match": filing.homepage_match,
        "verdicts": [{"model": v.model, "label": v.label, "confidence": v.confidence, "reason": v.reason}
                     for v in (a, b) if v],
    }


def load_data() -> dict:
    if DATA_PATH.exists():
        data = json.loads(DATA_PATH.read_text())
        if isinstance(data, dict):
            return data
    return {"companies": [], "review": []}


def add_label(row: dict, decision: str, existing: set[str]) -> bool:
    """Append a review decision to the golden set (once per filing)."""
    if row["accession_no"] in existing:
        return False
    with LABELS_PATH.open("a") as f:
        f.write(json.dumps({
            "accession_no": row["accession_no"], "cik": row["cik"], "company_name": row["company_name"],
            "label": decision, "category": "hard",
            "reason": f"Weekly review decision; pipeline said review: {row['review_reason']}",
            "your_note": None, "homepage_url": row["homepage_url"],
            "rubric_version": RUBRIC_VERSION, "labeled_at": datetime.now(timezone.utc).isoformat(),
        }) + "\n")
    existing.add(row["accession_no"])
    return True


def merge(filings: list[Filing], data: dict, decisions: dict, today: str) -> Counter:
    """Fold this run's ship/review rows and the review decisions into data."""
    companies = {c["cik"]: c for c in data["companies"]}
    review = {c["cik"]: c for c in data["review"]}
    changes = Counter()

    def upsert(row: dict) -> None:
        old = companies.get(row["cik"])
        if old is None:
            companies[row["cik"]] = {**row, "review_reason": None}
            changes["companies added"] += 1
        elif (row["amount_sold_usd"] or 0) > (old["amount_sold_usd"] or 0):
            old.update(amount_sold_usd=row["amount_sold_usd"], last_updated=today,
                       accession_no=row["accession_no"], edgar_url=row["edgar_url"])
            changes["amounts raised"] += 1

    for filing in sorted(filings, key=lambda f: f.filing_date):
        if filing.final not in ("ship", "review"):
            continue
        row = company_row(filing, today)
        if filing.final == "ship" or filing.cik in companies:
            upsert(row)  # already on the dashboard: only the amount can change
            review.pop(filing.cik, None)
        elif decisions.get(filing.cik) is None and filing.cik not in review:
            review[filing.cik] = row
            changes["sent to review"] += 1

    existing_labels = {json.loads(line)["accession_no"] for line in LABELS_PATH.read_text().splitlines()}
    for cik, decision in decisions.items():
        if isinstance(decision, bool):  # YAML reads a bare yes / no as true / false
            decision = "yes" if decision else "no"
        decision = str(decision).strip().lower()
        if cik not in review or decision not in ("yes", "no"):
            continue
        row = review.pop(cik)
        changes[f"review decided {decision}"] += 1
        changes["labels added"] += add_label(row, decision, existing_labels)
        if decision == "yes":
            upsert(row)

    data["companies"] = sorted(companies.values(), key=lambda c: c["filing_date"], reverse=True)
    data["review"] = sorted(review.values(), key=lambda c: c["filing_date"], reverse=True)
    return changes


def apply_tracking(data: dict, tracking: dict) -> None:
    for company in data["companies"]:
        entry = tracking.get(company["cik"]) or {}
        company["contacted"] = bool(entry.get("contacted", False))
        company["note"] = entry.get("note", "") or ""


def summarize(run_id: str, changes: Counter) -> dict:
    """Counts per stage, cost and runtime for one run."""
    run_dir = RUNS_DIR / run_id
    pulled = [Filing.model_validate_json(l) for l in (run_dir / "02_parsed.jsonl").read_text().splitlines()]
    filtered = [Filing.model_validate_json(l) for l in (run_dir / "03_filtered.jsonl").read_text().splitlines()]
    classified = [Filing.model_validate_json(l) for l in (run_dir / "05_classified.jsonl").read_text().splitlines()]
    model_cost = sum(v.cost_usd or 0 for f in classified for v in (f.classify_a, f.classify_b) if v)
    searches = sum(f.searches or 0 for f in classified)
    started = min(f.processed_at for f in pulled)
    return {
        "run_id": run_id,
        "filings_pulled": len(pulled),
        "parse_errors": sum(bool(f.parse_error) for f in pulled),
        "passed_filter": sum(bool(f.passed_structural) for f in filtered),
        "filter_drops": dict(Counter(f.drop_reason.split(":")[0].split(" $")[0]
                                     for f in filtered if f.drop_reason).most_common()),
        "with_homepage": sum(bool(f.homepage_url) for f in classified),
        "final": dict(Counter(f.final for f in classified)),
        "shipped": [f.company_name for f in classified if f.final == "ship"],
        "review": [f.company_name for f in classified if f.final == "review"],
        "no_homepage_found": [f.company_name for f in classified if f.final_reason == "no homepage found"],
        "dashboard_changes": dict(changes),
        "tavily_searches": searches,
        "tavily_cost_usd_if_paid": round(searches * 0.008, 4),
        "model_cost_usd": round(model_cost, 4),
        "runtime_minutes": round((datetime.now(timezone.utc) - started).total_seconds() / 60, 1),
    }


def output(run_id: str) -> None:
    classified_path = RUNS_DIR / run_id / "05_classified.jsonl"
    filings = [Filing.model_validate_json(l) for l in classified_path.read_text().splitlines()]
    today = date.today().isoformat()

    data = load_data()
    before = json.dumps({k: data.get(k) for k in ("companies", "review")}, sort_keys=True)
    changes = merge(filings, data, read_yaml(REVIEW_PATH), today)
    apply_tracking(data, read_yaml(TRACKING_PATH))
    after = json.dumps({k: data.get(k) for k in ("companies", "review")}, sort_keys=True)
    if after != before:  # a re-run that changes nothing leaves the file untouched
        data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        DATA_PATH.write_text(json.dumps(data, indent=1) + "\n")

    summary = summarize(run_id, changes)
    (RUNS_DIR / run_id / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default=date.today().isoformat(), help="run folder name (default: today)")
    output(parser.parse_args().run_id)


if __name__ == "__main__":
    main()
