"""Save a "Needs review" decision from a dashboard request (decision 31).

The dashboard's "✓ AI" / "✗ Not AI" buttons open a pre-filled GitHub issue
titled "[review] <cik> yes|no <company>" with an optional "note:" line.
When the repo owner submits it, the review.yml workflow runs this script,
which:

1. writes the line "<cik>": yes|no into review.yml (keeping its comments),
2. applies the decision to dashboard/data.json right away, the same way the
   weekly run does: "yes" moves the company to the main table, "no" removes
   it from review, and either one is added to labels.jsonl (the note becomes
   the label's your_note).

The issue title and body arrive in the ISSUE_TITLE and ISSUE_BODY
environment variables (never pasted into a shell command).

Usage (normally run by the workflow):
    ISSUE_TITLE="[review] 0002054765 yes Overwatch Data" ISSUE_BODY="note: real AI product" python -m pipeline.review
"""

import json
import os
import re
from datetime import date, datetime, timezone

from pipeline.output import DATA_PATH, REVIEW_PATH, TRACKING_PATH, apply_tracking, load_data, merge, read_yaml


def parse_request(title: str) -> tuple[str, str]:
    """Return (cik, decision) from the issue title."""
    match = re.search(r"\b(\d{10})\s+(yes|no)\b", title, flags=re.IGNORECASE)
    if not match:
        raise SystemExit(f"Expected '[review] <10-digit cik> yes|no' in issue title {title!r}")
    return match.group(1), match.group(2).lower()


def parse_note(body: str) -> str:
    note = re.search(r"^note:[ \t]*(.*)$", body, flags=re.MULTILINE)
    return note.group(1).strip() if note else ""


def write_decision(cik: str, decision: str, note: str) -> None:
    """Replace (or add) this CIK's line in review.yml; other lines and comments stay as they are."""
    lines = REVIEW_PATH.read_text().splitlines() if REVIEW_PATH.exists() else []
    lines = [l for l in lines if not re.match(rf'\s*"?0*{int(cik)}"?\s*:', l)]
    comment = f"  # {note.replace(chr(10), ' ')}" if note else ""
    lines.append(f'"{cik}": {decision}{comment}')
    REVIEW_PATH.write_text("\n".join(lines) + "\n")


def decide(cik: str, decision: str, note: str) -> None:
    write_decision(cik, decision, note)

    data = load_data()
    name = next((c["company_name"] for c in data["review"] if c["cik"] == cik), None)
    changes = merge([], data, {cik: decision}, date.today().isoformat(), notes={cik: note})
    apply_tracking(data, read_yaml(TRACKING_PATH))
    if changes:
        data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        DATA_PATH.write_text(json.dumps(data, indent=1) + "\n")
        print(f"Decided {cik} {name}: {decision}" + (f" (note: {note})" if note else ""))
    else:
        print(f"Saved {cik}: {decision} in review.yml; it is not in the review list, so the dashboard is unchanged")


def main() -> None:
    cik, decision = parse_request(os.environ.get("ISSUE_TITLE", ""))
    decide(cik, decision, parse_note(os.environ.get("ISSUE_BODY", "")))


if __name__ == "__main__":
    main()
