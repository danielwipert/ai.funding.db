"""Mark a company as contacted from a dashboard request (decision 30).

The dashboard's "Mark contacted" button opens a pre-filled GitHub issue
titled "[contacted] <cik> <company>" with an optional "note:" line. When
the repo owner submits it, the contacted.yml workflow runs this script,
which sets contacted: true (and the note) for that CIK in tracking.yml and
refreshes contacted/note in dashboard/data.json.

The issue title and body arrive in the ISSUE_TITLE and ISSUE_BODY
environment variables (never pasted into a shell command).

Usage (normally run by the workflow):
    ISSUE_TITLE="[contacted] 0002054765 Overwatch Data" ISSUE_BODY="note: emailed CEO" python -m pipeline.tracking
"""

import json
import os
import re
from datetime import datetime, timezone

from pipeline.output import DATA_PATH, TRACKING_PATH, apply_tracking, load_data, read_yaml

HEADER = """# Outreach tracking. One entry per company, keyed on CIK. Edit by hand, or
# use the dashboard's "Mark contacted" button (it opens a GitHub issue; the
# contacted.yml workflow then updates this file). The weekly pipeline only
# reads this file and never writes it.
#
# Example:
#
# "0001234567":
#   contacted: true
#   note: "Sent LinkedIn message 11/3, referenced Refund Gate"

"""


def parse_request(title: str, body: str) -> tuple[str, str]:
    """Return (cik, note) from the issue text."""
    match = re.search(r"\b(\d{10})\b", title) or re.search(r"cik:\s*(\d+)", body)
    if not match:
        raise SystemExit(f"No CIK found in issue title {title!r}")
    note = re.search(r"^note:[ \t]*(.*)$", body, flags=re.MULTILINE)
    return match.group(1).zfill(10), (note.group(1).strip() if note else "")


def to_yaml(tracking: dict) -> str:
    """Write entries in the hand-edited style: every CIK quoted, values on
    their own lines (JSON strings are valid YAML double-quoted strings)."""
    lines = []
    for cik in sorted(tracking):
        entry = tracking[cik] or {}
        lines.append(f'"{cik}":')
        lines.append(f"  contacted: {'true' if entry.get('contacted') else 'false'}")
        if entry.get("note"):
            lines.append(f"  note: {json.dumps(str(entry['note']), ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def mark_contacted(cik: str, note: str) -> None:
    tracking = read_yaml(TRACKING_PATH)
    entry = tracking.get(cik) or {}
    entry["contacted"] = True
    if note:
        entry["note"] = note
    tracking[cik] = entry
    TRACKING_PATH.write_text(HEADER + to_yaml(tracking))

    data = load_data()
    apply_tracking(data, tracking)
    data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    DATA_PATH.write_text(json.dumps(data, indent=1) + "\n")
    name = next((c["company_name"] for c in data["companies"] if c["cik"] == cik), "(not on the dashboard)")
    print(f"Marked {cik} {name} as contacted" + (f" with note: {note}" if note else ""))


def main() -> None:
    cik, note = parse_request(os.environ.get("ISSUE_TITLE", ""), os.environ.get("ISSUE_BODY", ""))
    mark_contacted(cik, note)


if __name__ == "__main__":
    main()
