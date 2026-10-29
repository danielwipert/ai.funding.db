"""Stage 5-6 (build step 6): Classify with model A, verify with model B.

Model A applies the rubric. Model B, from a different model family, gets
a differently worded prompt that first argues the company is NOT an AI
company, then gives its own verdict. Both also say whether the homepage
belongs to the company in the filing. Only agreement ships:

    ship    both say yes, both confident (>= 0.8), and for a weak homepage
            match both confirm the website is this company's
    drop    no homepage found, or both say no
    review  anything else (disagreement, uncertain, low confidence, identity doubt)

Reads runs/<run_id>/04_enriched.jsonl and writes runs/<run_id>/05_classified.jsonl.
Needs OPENROUTER_API_KEY in the environment.

Usage:
    python -m pipeline.classify                    # today's run folder
    python -m pipeline.classify --run-id 2026-10-28
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from pipeline.models import Filing, Verdict
from pipeline.parse import RUNS_DIR

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RUBRIC_VERSION = "v2"
RUBRIC = (Path(__file__).parent / f"rubric_{RUBRIC_VERSION}.md").read_text()

# Picked in step 6 by pipeline/evaluate.py against the golden set (decision 25).
MODEL_A = "deepseek/deepseek-v4-flash"
MODEL_B = "google/gemma-4-31b-it"
CONFIDENCE_FLOOR = 0.8

CLASSIFIER_PROMPT = f"""You classify companies for a scanner that finds newly funded AI companies.
Apply this rubric exactly:

{RUBRIC}

You get facts from the company's SEC Form D filing and text from a website we
believe is its homepage. Use only this evidence; never guess from the company
name. If the website might belong to a different company with a similar name,
say so in same_company."""

SKEPTIC_PROMPT = f"""You are a skeptical reviewer checking another analyst's work. A company is
claimed to be an AI company under the rubric below. First, write the strongest
honest case that it is NOT an AI company under the rubric (bolted-on AI, a
services firm, hardware, an excluded vertical, too little evidence, or a
website that may belong to a different company). Then weigh that case and give
your own verdict; if the case against fails, say yes.

{RUBRIC}

Use only the evidence given; never guess from the company name."""

FIELDS = {
    "same_company": {"type": "string", "enum": ["yes", "no", "uncertain"],
                     "description": "Does the website belong to the company in the filing?"},
    "label": {"type": "string", "enum": ["yes", "no", "uncertain"],
              "description": "Is it an AI company under the rubric?"},
    "confidence": {"type": "number", "description": "0 to 1"},
    "reason": {"type": "string", "description": "At most 30 words, naming the rubric rule applied"},
    "description": {"type": "string", "description": "At most 20 words: what the product does"},
}


def schema(skeptic: bool) -> dict:
    properties = dict(FIELDS)
    if skeptic:
        properties = {"case_against": {"type": "string", "description": "The strongest case it is not AI"}, **properties}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def evidence_message(facts: dict, evidence: str, snippet: str | None) -> str:
    people = "; ".join(f"{p['name']} ({', '.join(p['relationships'])})" for p in facts["related_persons"][:8])
    return (
        f"Form D facts:\n- Company: {facts['company_name']}\n- Location: {facts['city']}, {facts['state']}\n"
        f"- Related persons: {people or 'none listed'}\n\n"
        f"Search snippet:\n{snippet or '(none)'}\n\n"
        f"Website: {facts['homepage_url']}\nWebsite text:\n{evidence}"
    )


def call_model(model: str, skeptic: bool, message: str) -> Verdict:
    """Ask one model for a verdict; errors become an "uncertain" verdict so the row goes to review."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY first.")
    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SKEPTIC_PROMPT if skeptic else CLASSIFIER_PROMPT},
                    {"role": "user", "content": message},
                ],
                "temperature": 0,
                "reasoning": {"effort": "low"},  # a yes/no call needs little thinking; keeps it fast and cheap
                "max_tokens": 4000,
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "verdict", "strict": True, "schema": schema(skeptic)}},
                "provider": {"require_parameters": True},  # only hosts that enforce the schema
                "usage": {"include": True},
            },
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        data = json.loads(body["choices"][0]["message"]["content"])
        cost = (body.get("usage") or {}).get("cost")
        return Verdict(**{k: data[k] for k in FIELDS}, model=model, rubric_version=RUBRIC_VERSION, cost_usd=cost)
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        return Verdict(same_company="uncertain", label="uncertain", confidence=0, description="",
                       reason=f"model call failed: {type(e).__name__}", model=model, rubric_version=RUBRIC_VERSION)


def decide(a: Verdict, b: Verdict, weak_match: bool) -> tuple[str, str]:
    """Agreement logic: returns (final, reason). The identity check only
    applies to weak homepage matches (decision 22)."""
    if a.label == b.label == "no" and min(a.confidence, b.confidence) >= CONFIDENCE_FLOOR:
        return "drop", "both models: not an AI company"
    if "uncertain" in (a.label, b.label):
        return "review", "a model was uncertain"
    if min(a.confidence, b.confidence) < CONFIDENCE_FLOOR:
        return "review", "a model was under the confidence floor"
    if a.label != b.label:
        return "review", "models disagree"
    if weak_match and (a.same_company != "yes" or b.same_company != "yes"):
        return "review", "a model doubts the website is this company's"
    return "ship", "both models: AI company"


def facts_of(filing: Filing) -> dict:
    return {
        "company_name": filing.company_name, "city": filing.city, "state": filing.state,
        "homepage_url": filing.homepage_url,
        "related_persons": [p.model_dump() for p in filing.related_persons or []],
    }


def classify_one(filing: Filing) -> dict:
    if not filing.homepage_url:
        return {"final": "drop", "final_reason": filing.enrich_note or "no homepage found"}
    message = evidence_message(facts_of(filing), filing.evidence_text or "", filing.search_snippet)
    a = call_model(MODEL_A, skeptic=False, message=message)
    b = call_model(MODEL_B, skeptic=True, message=message)
    final, reason = decide(a, b, weak_match=filing.homepage_match == "weak")
    return {"classify_a": a, "classify_b": b, "final": final, "final_reason": reason}


def classify(run_id: str) -> None:
    in_path = RUNS_DIR / run_id / "04_enriched.jsonl"
    out_path = RUNS_DIR / run_id / "05_classified.jsonl"
    filings = [Filing.model_validate_json(line) for line in in_path.read_text().splitlines()]
    processed_at = datetime.now(timezone.utc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(classify_one, filings))

    counts, cost = {}, 0.0
    with out_path.open("w") as out:
        for filing, fields in zip(filings, results):
            row = filing.model_copy(update={**fields, "processed_at": processed_at})
            out.write(row.model_dump_json() + "\n")
            counts[row.final] = counts.get(row.final, 0) + 1
            cost += sum(v.cost_usd or 0 for v in (row.classify_a, row.classify_b) if v)
            print(f"  {row.final:6} {filing.company_name}: {row.final_reason}")
    print(f"Wrote {len(filings)} rows to {out_path}: {counts}; model cost ${cost:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", default=date.today().isoformat(), help="run folder name (default: today)")
    args = parser.parse_args()
    classify(args.run_id)


if __name__ == "__main__":
    main()
