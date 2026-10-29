"""Score candidate models, and every A/B pair of them, against the golden set.

For each labeled company with a homepage, the Form D facts are re-read from
EDGAR and the homepage text is fetched; every candidate model then answers
as classifier (A) and as skeptic (B). Pairs from different model families
are scored with the same agreement logic the pipeline uses.

Writes runs/golden-eval/verdicts.jsonl (one line per answer, written as it
arrives, so a re-run only asks what is missing) and runs/golden-eval/report.md.
Needs EDGAR_CONTACT_EMAIL and OPENROUTER_API_KEY.

Usage:
    python -m pipeline.evaluate
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from itertools import product

from pipeline.classify import CONFIDENCE_FLOOR, call_model, decide, evidence_message
from pipeline.enrich import cap_words, page_text
from pipeline.labels import LABELS_PATH
from pipeline.models import Verdict, jsonl_lines
from pipeline.parse import RUNS_DIR, fetch_xml, parse_xml

CANDIDATES = [
    "deepseek/deepseek-v4-flash",
    "z-ai/glm-5.3",
    "openai/gpt-oss-120b",
]
OUT_DIR = RUNS_DIR / "golden-eval"


def family(model: str) -> str:
    return model.split("/")[0]


def load_cases() -> list[dict]:
    """Labeled companies with a homepage, plus their Form D facts and page text."""
    cases = []
    for line in jsonl_lines(LABELS_PATH):
        label = json.loads(line)
        if not label["homepage_url"]:
            continue  # the pipeline drops these as "no homepage found"
        parsed = parse_xml(fetch_xml(label["cik"], label["accession_no"])[0])
        homepage = label["homepage_url"]
        facts = {
            "company_name": label["company_name"], "city": parsed["city"], "state": parsed["state"],
            "homepage_url": homepage,
            "related_persons": [p.model_dump() for p in parsed["related_persons"]],
        }
        cases.append({**label, "message": evidence_message(facts, cap_words(page_text(homepage)), None)})
    return cases


def confident_yes(v: Verdict) -> bool:
    return v.label == "yes" and v.confidence >= CONFIDENCE_FLOOR


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    index = {c["accession_no"]: i for i, c in enumerate(cases)}
    jobs = list(product(range(len(cases)), CANDIDATES, (False, True)))

    # Reuse answers from an earlier, interrupted run (failed calls are asked again)
    answers = {}
    verdicts_path = OUT_DIR / "verdicts.jsonl"
    if verdicts_path.exists():
        for line in jsonl_lines(verdicts_path):
            row = json.loads(line)
            v = Verdict(**{k: row[k] for k in Verdict.model_fields})
            if row["accession_no"] in index and "call failed" not in v.reason:
                answers[(index[row["accession_no"]], row["model"], row["role"] == "B")] = v
    todo = [j for j in jobs if j not in answers]
    print(f"{len(cases)} labeled companies with a homepage; {len(jobs)} answers needed, {len(todo)} to ask", flush=True)

    lock = threading.Lock()
    done = 0

    def ask(job):
        nonlocal done
        i, model, skeptic = job
        v = call_model(model, skeptic, cases[i]["message"])
        with lock:
            answers[job] = v
            with verdicts_path.open("a") as f:
                f.write(json.dumps({"accession_no": cases[i]["accession_no"], "company": cases[i]["company_name"],
                                    "truth": cases[i]["label"], "category": cases[i]["category"],
                                    "role": "B" if skeptic else "A", **v.model_dump()}) + "\n")
            done += 1
            print(f"  {done}/{len(todo)} {model} {'B' if skeptic else 'A'} {cases[i]['company_name']}: "
                  f"{v.label} {v.confidence:.2f}", flush=True)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(ask, todo))
    verdicts = [answers[j] for j in jobs]

    truth_yes = sum(c["label"] == "yes" for c in cases)
    lines = [f"# Golden-set evaluation\n\n{len(cases)} companies with a homepage, {truth_yes} labeled AI.\n",
             "## Single models (confident yes = label yes and confidence >= 0.8)\n",
             "| Model | Role | Confident yes | Correct | Wrong (false positives) | Uncertain | Failed calls |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for model, skeptic in product(CANDIDATES, (False, True)):
        vs = [(cases[i], answers[(i, model, skeptic)]) for i in range(len(cases))]
        yes = [(c, v) for c, v in vs if confident_yes(v)]
        lines.append(f"| {model} | {'B' if skeptic else 'A'} | {len(yes)} | {sum(c['label'] == 'yes' for c, _ in yes)} "
                     f"| {', '.join(c['company_name'] for c, _ in yes if c['label'] == 'no') or '-'} "
                     f"| {sum(v.label == 'uncertain' for _, v in vs)} | {sum('call failed' in v.reason for _, v in vs)} |")

    lines += ["\n## Pairs (A classifies, B verifies; different families only)\n",
              "| A | B | Shipped | Precision | Recall | Review queue | Clear cases in review | False positives |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    rows = []
    for a_model, b_model in product(CANDIDATES, CANDIDATES):
        if family(a_model) == family(b_model):
            continue
        outcomes = [(c, decide(answers[(i, a_model, False)], answers[(i, b_model, True)], weak_match=False)[0])
                    for i, c in enumerate(cases)]
        shipped = [c for c, o in outcomes if o == "ship"]
        correct = sum(c["label"] == "yes" for c in shipped)
        review = [c for c, o in outcomes if o == "review"]
        precision = correct / len(shipped) if shipped else 0.0
        rows.append((precision, correct / truth_yes, -len(review), a_model, b_model, len(shipped), len(review),
                     sum(c["category"] == "clear" for c in review),
                     ", ".join(c["company_name"] for c in shipped if c["label"] == "no") or "-"))
    for p, r, _, a_model, b_model, n_ship, n_review, clear_review, fps in sorted(rows, reverse=True):
        lines.append(f"| {a_model} | {b_model} | {n_ship} | {p:.0%} | {r:.0%} | {n_review} | {clear_review} | {fps} |")

    cost = sum(v.cost_usd or 0 for v in verdicts)
    lines.append(f"\nTotal model cost for this evaluation: ${cost:.4f}")
    report = "\n".join(lines)
    (OUT_DIR / "report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
