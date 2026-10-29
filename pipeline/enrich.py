"""Stage 4 (build step 5): Enrich each survivor with its homepage text.

One Tavily web search per company finds the homepage; the page is fetched
and stripped to plain text, capped at ~1,500 words. A homepage is only
accepted when its domain looks like the company name; it is a "strong" match
when the page also names a related person or the city (or the domain is a
long, distinctive name), otherwise "weak". With no match, homepage_url stays
None, which later forces an "uncertain" verdict (evidence or nothing).

Reads runs/<run_id>/03_filtered.jsonl and writes runs/<run_id>/04_enriched.jsonl.
Needs TAVILY_API_KEY in the environment.

Usage:
    python -m pipeline.enrich                    # today's run folder
    python -m pipeline.enrich --run-id 2026-10-28
"""

import argparse
import os
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from pipeline.models import Filing
from pipeline.parse import RUNS_DIR

TAVILY_URL = "https://api.tavily.com/search"
MAX_EVIDENCE_WORDS = 1500
MIN_USEFUL_WORDS = 50  # fewer than this and the page is probably rendered by JavaScript
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AIFundingScanner/1.0)"}

# Sites that mention companies but are never their homepage.
DIRECTORY_DOMAINS = [
    "sec.gov", "linkedin.com", "crunchbase.com", "pitchbook.com", "bloomberg.com",
    "zoominfo.com", "dnb.com", "opencorporates.com", "bizapedia.com", "cbinsights.com",
    "tracxn.com", "wellfound.com", "ycombinator.com", "facebook.com", "x.com",
    "twitter.com", "instagram.com", "youtube.com", "wikipedia.org", "glassdoor.com",
    "indeed.com", "rocketreach.co", "apollo.io", "signalhire.com", "craft.co",
    "owler.com", "builtin.com", "techcrunch.com", "prnewswire.com", "businesswire.com",
    "globenewswire.com", "medium.com", "github.com", "reddit.com", "formds.com",
    "startengine.com", "wefunder.com", "republic.com", "angel.co", "f6s.com",
    "streetinsider.com", "govtribe.com", "g2.com", "equilar.com", "bizjournals.com",
    "digitaljournal.com", "equityzen.com", "employbl.com", "applytojob.com",
]

# Words that appear in many company names and say nothing about which company it is.
LEGAL_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "llc", "ltd", "lp",
                  "pbc", "plc", "company", "the", "holdings", "holding", "group"}
GENERIC_WORDS = {"data", "health", "software", "network", "networks", "capital", "partners",
                 "solutions", "systems", "analytics", "labs", "global", "energy", "intelligence",
                 "technologies", "technology", "ventures", "fund", "investment", "smart",
                 "digital", "cloud", "media", "services", "international", "america", "usa"}


def name_tokens(company_name: str) -> list[str]:
    """Lowercase words of the name, without "(CIK ...)", tickers and legal suffixes."""
    name = re.sub(r"\(.*?\)", " ", company_name.lower())
    return [w for w in re.findall(r"[a-z0-9]+", name) if w not in LEGAL_SUFFIXES]


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def is_directory(url: str) -> bool:
    domain = domain_of(url)
    if domain.endswith(".gov") or ".gov." in domain:  # government sites are never a startup's homepage
        return True
    return any(domain == d or domain.endswith("." + d) for d in DIRECTORY_DOMAINS)


def domain_label(url: str) -> str:
    """"www.agent-smyth.co.uk" -> "agentsmyth"."""
    return domain_of(url).split(".")[0].replace("-", "")


def joined_name(company_name: str) -> str:
    """"FuriosaAI, Inc." -> "furiosa"; "AgentSmyth Inc." -> "agentsmyth"."""
    return "".join(name_tokens(company_name)).removesuffix("ai")


def distinctive_words(company_name: str) -> list[str]:
    return [t for t in name_tokens(company_name) if len(t) >= 4 and t not in GENERIC_WORDS and t != "ai"]


def domain_matches_name(url: str, company_name: str) -> bool:
    """True when the domain looks like the company's name (weak on its own)."""
    label, joined = domain_label(url), joined_name(company_name)
    if joined and (joined in label or (len(label) >= 5 and joined.startswith(label))):
        return True
    return any(t in label for t in distinctive_words(company_name))


def domain_is_distinctive_name(url: str, company_name: str) -> bool:
    """True when the domain contains the full name and it is long enough to be
    unlikely to belong to another company ("agentsmyth", not "relay")."""
    joined = joined_name(company_name)
    return len(joined) >= 8 and joined in domain_label(url)


def page_mentions(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    return any(len(w) >= 4 and re.search(rf"\b{re.escape(w.lower())}\b", lowered) for w in words)


def confirms_identity(text: str, filing: Filing) -> bool:
    """True when the page names a related person (last name) or the filing's city."""
    last_names = [p.name.split()[-1] for p in filing.related_persons or [] if p.name]
    return page_mentions(text, last_names) or bool(filing.city and filing.city.lower() in text.lower())


def match_strength(url: str, text: str, filing: Filing) -> str | None:
    """"strong", "weak", or None when the site isn't this company's own.

    The domain must look like the company name: news and filing-aggregator
    pages also mention the name, city and people, so page text alone proves
    nothing. Renamed companies (domain unlike the legal name) get None and
    go to review.
    """
    if not domain_matches_name(url, filing.company_name):
        return None
    if confirms_identity(text, filing) or domain_is_distinctive_name(url, filing.company_name):
        return "strong"
    return "weak"


def search(filing: Filing) -> list[dict]:
    """One Tavily search for the company; returns the ranked results."""
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise SystemExit("Set TAVILY_API_KEY first (free key at https://app.tavily.com).")
    name = re.sub(r"\(.*?\)", "", filing.company_name).strip()
    response = requests.post(
        TAVILY_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "query": f'"{name}" {filing.city or ""} {filing.state or ""} company website',
            "search_depth": "basic",  # 1 credit
            "max_results": 8,
            "include_raw_content": "text",  # fallback when we can't fetch the page ourselves
            "exclude_domains": DIRECTORY_DOMAINS,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["results"]


def page_text(url: str) -> str:
    """Fetch a page and return its visible text, or "" if it can't be fetched."""
    try:
        response = requests.get(url, headers=BROWSER_HEADERS, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return ""
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def cap_words(text: str) -> str:
    return " ".join(text.split()[:MAX_EVIDENCE_WORDS])


def enrich_one(filing: Filing) -> dict:
    """Return the stage 4 fields for one filing."""
    try:
        results = search(filing)
    except requests.RequestException as e:
        return {"enrich_note": f"search failed: {type(e).__name__}"}
    results = [r for r in results if not is_directory(r["url"])]
    if not results:
        return {"enrich_note": "no search results outside directory sites"}
    candidates = {"candidate_urls": [r["url"] for r in results]}

    weak = None
    for result in results:
        homepage = f"https://{domain_of(result['url'])}"
        text = page_text(homepage)
        if len(text.split()) < MIN_USEFUL_WORDS:
            text = result.get("raw_content") or result.get("content") or ""
        strength = match_strength(homepage, text, filing)
        if strength is None:
            continue
        fields = {
            "homepage_url": homepage,
            "search_snippet": result.get("content"),
            "evidence_text": cap_words(text) or None,
            "homepage_match": strength,
            "enrich_note": f"{strength} match",
        }
        if strength == "strong":
            return {**fields, **candidates}
        weak = weak or fields  # keep the best weak match in case nothing strong turns up
    if weak:
        return {**weak, **candidates}

    return {
        "search_snippet": results[0].get("content"),
        "enrich_note": "no result's domain matched the company name; left for review",
        **candidates,
    }


def enrich(run_id: str) -> None:
    in_path = RUNS_DIR / run_id / "03_filtered.jsonl"
    out_path = RUNS_DIR / run_id / "04_enriched.jsonl"
    filings = [Filing.model_validate_json(line) for line in in_path.read_text().splitlines()]
    survivors = [f for f in filings if f.passed_structural]
    processed_at = datetime.now(timezone.utc)

    with_evidence = 0
    with out_path.open("w") as out:
        for i, filing in enumerate(survivors, start=1):
            fields = enrich_one(filing)
            with_evidence += bool(fields.get("evidence_text"))
            enriched = filing.model_copy(update={**fields, "processed_at": processed_at})
            out.write(enriched.model_dump_json() + "\n")
            print(f"  {i}/{len(survivors)} {filing.company_name}: {fields.get('homepage_url') or '-'} ({fields['enrich_note']})")

    share = with_evidence / len(survivors) if survivors else 0
    print(f"Wrote {len(survivors)} survivors to {out_path}; {with_evidence} ({share:.0%}) have evidence text")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default=date.today().isoformat(), help="run folder name (default: today)")
    args = parser.parse_args()
    enrich(args.run_id)


if __name__ == "__main__":
    main()
