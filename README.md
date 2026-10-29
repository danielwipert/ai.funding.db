# AI Funding Scanner

A weekly pipeline that answers one question: **which AI companies closed a new
funding round in the last N days, and who runs them?**

It reads SEC EDGAR Form D filings, filters them, checks each company's homepage
with two independent AI classifiers, and publishes the results to a small
dashboard on GitHub Pages.

The full design is in [`planning_docs/AI_Funding_Scanner_Pipeline_Spec_v1.md`](planning_docs/AI_Funding_Scanner_Pipeline_Spec_v1.md).

## Folder layout

| Path | What lives there |
| --- | --- |
| `planning_docs/` | The spec, the logic-gates decision method, and other planning notes |
| `CLAUDE.md` | Instructions Claude Code reads at the start of every session |
| `pipeline/` | Python code, one file per stage (`pull.py`, `parse.py`, `filter.py`, ...) |
| `dashboard/` | The web page (`index.html`) and the data it shows (`data.json`) |
| `runs/` | One dated folder per run, e.g. `runs/2026-11-01/`. Only `summary.json` files are committed |
| `tracking.yml` | Your outreach notes, one entry per company (CIK). The pipeline never edits this |
| `requirements.txt` | Python packages the pipeline needs |
| `.github/workflows/` | GitHub Actions: deploys the dashboard to Pages |

## Getting started (local)

1. Create a virtual environment:

   ```bash
   python3 -m venv .venv
   ```

2. Activate it:

   ```bash
   source .venv/bin/activate
   ```

3. Install the packages:

   ```bash
   pip install -r requirements.txt
   ```

4. Tell EDGAR who you are (the SEC requires contact details on every request):

   ```bash
   export EDGAR_CONTACT_EMAIL=you@example.com
   ```

## Running the pipeline

Pull the last 7 days of Form D filings (writes `runs/<today>/01_filings.jsonl`):

```bash
python -m pipeline.pull
```

Or pick the dates yourself:

```bash
python -m pipeline.pull --since 2026-10-21 --until 2026-10-27
```

Then fetch and read each filing's details (writes `02_parsed.jsonl` in the same run folder; downloaded XML is kept in `cache/`):

```bash
python -m pipeline.parse
```

If you used `--run-id` on the pull, pass the same one here.

Then apply the structural filter (writes `03_filtered.jsonl`; every row is kept, dropped ones carry a `drop_reason`):

```bash
python -m pipeline.filter
```

Then find each survivor's homepage (writes `04_enriched.jsonl`; needs a free Tavily key from https://app.tavily.com):

```bash
export TAVILY_API_KEY=tvly-...
```

```bash
python -m pipeline.enrich
```

Then classify and verify with two AI models (writes `05_classified.jsonl` with a final `ship` / `review` / `drop` per company; needs an OpenRouter key):

```bash
export OPENROUTER_API_KEY=sk-or-...
```

```bash
python -m pipeline.classify
```

To re-test models or prompts against the golden set (writes `runs/golden-eval/report.md`):

```bash
python -m pipeline.evaluate
```

On GitHub, the **Pipeline test run** workflow (Actions tab) runs all of the above with the repository secrets and lets you download the results.

## Golden set (step 4)

`labels/golden_set.csv` holds 60 labeled companies (pre-labeled, then reviewed; hard cases at the top). To add more labels later, add rows with `label` = yes or no and re-run the import; rows already in `labels.jsonl` are skipped:

```bash
python -m pipeline.labels labels/golden_set.csv
```

## Build progress

- [x] Step 0 — Repo skeleton
- [x] Step 1 — Pull (`pipeline/pull.py`)
- [x] Step 2 — Parse (`pipeline/parse.py`)
- [x] Step 3 — Structural filter (`pipeline/filter.py`)
- [x] Step 4 — Golden set (`labels.jsonl`)
- [x] Step 5 — Enrich (`pipeline/enrich.py`)
- [x] Step 6 — Classify + Verify (`pipeline/classify.py`)
- [ ] Step 7 — Merge + data.json (`pipeline/output.py`)
- [ ] Step 8 — Dashboard (`dashboard/index.html`)
- [ ] Step 9 — Weekly Actions workflow
- [ ] Step 10 — Audit routine
