"""Step 10: Make this week's audit checklist.

Picks up to 20 companies from the dashboard (all of them for the first
four weekly runs, as the spec asks, then a random 20) and writes
audits/<date>.md: one checkbox line per company with its homepage, plus a
place for postmortem lines and the measured error rate.

Usage:
    python -m pipeline.audit                 # companies added in the last 7 days
    python -m pipeline.audit --all           # every company on the dashboard
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "dashboard" / "data.json"
AUDITS_DIR = ROOT / "audits"
SAMPLE_SIZE = 20
FULL_AUDIT_WEEKS = 4  # hand-check every row for the first four weekly runs

TEMPLATE = """# Audit {today}

{n} of {total} companies {scope}. For each one, open the homepage and ask:
**is this an AI company under rubric v2?** (`pipeline/rubric_v2.md`)

Tick the box if yes. If not, leave it unticked and add a postmortem line below.

{rows}

## Postmortems (one line per false positive)

Format: `company | stage that let it through | what fixes the whole class of error | golden-set row added? (y/n)`

Example: `Acme Data Inc | 6 Verify | rubric: analytics dashboards with an "AI assistant" are bolted-on AI | y`

-

## Result

False positives: __ of {n} checked. Error rate: __% (with {n} checked, 0 found means "under ~{bound}%", not "perfect").
Time taken: __ minutes.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="audit every company, not just the last week's")
    args = parser.parse_args()

    companies = json.loads(DATA_PATH.read_text())["companies"]
    today = date.today()
    if args.all:
        pool, scope = companies, "on the dashboard"
    else:
        since = (today - timedelta(days=7)).isoformat()
        pool, scope = [c for c in companies if c["first_seen"] >= since], "added in the last 7 days"

    past_audits = len(list(AUDITS_DIR.glob("*.md"))) if AUDITS_DIR.exists() else 0
    if past_audits >= FULL_AUDIT_WEEKS and len(pool) > SAMPLE_SIZE:
        pool = random.sample(pool, SAMPLE_SIZE)
        scope += f", random sample of {SAMPLE_SIZE}"

    rows = "\n".join(
        f"- [ ] **{c['company_name']}** ({c['state']}, ${c['amount_sold_usd']:,}): "
        f"{c.get('homepage_url') or 'no homepage'} | {c['description']}"
        for c in sorted(pool, key=lambda c: c["company_name"].lower())
    ) or "- (no companies to audit this week)"
    n = len(pool)
    bound = round(100 * 3 / n) if n else 100  # "rule of three": 0 of n seen -> under ~3/n

    AUDITS_DIR.mkdir(exist_ok=True)
    path = AUDITS_DIR / f"{today.isoformat()}.md"
    path.write_text(TEMPLATE.format(today=today, n=n, total=len(companies), scope=scope, rows=rows, bound=bound))
    print(f"Wrote {path} with {n} companies to check")


if __name__ == "__main__":
    main()
