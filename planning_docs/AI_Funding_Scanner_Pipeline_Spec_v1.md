# AI Funding Scanner — Pipeline Spec v1

Oct 28, 2026 · @Dan

## Purpose

The pipeline answers one question each week: **which AI companies closed a new funding round in the last N days, and who runs them?** Every design choice below serves that question and nothing else.

The output feeds created-role outreach. A round that closed 2–8 weeks ago is the window when a founder has cash, a hiring plan with holes, and no job descriptions written. The pipeline exists to surface that window before the aggregators do.

Two things it is deliberately **not**: it is not a general startup database, and it does not score fit. Fit is a human judgment applied to a short list; the pipeline's job is to make the short list trustworthy.

## Definition of done

"Pristine signal" means **precision over recall**: a company in the output is an AI company that raised money in the window, or the pipeline failed. Missing some real AI rounds is acceptable; including a non-AI company is not, because every false positive costs an hour of research.

| Target | Number | How measured |
| --- | --- | --- |
| Precision (output rows that are true AI companies) | ≥ 95% | Hand-label every row for the first 4 weekly runs; then sample 20 rows/week |
| Recall (true AI rounds in EDGAR that reach the output) | ≥ 70% | Compare against a newsletter's weekly deal list, once a month |
| Freshness (days from Form D filing to output row) | ≤ 7 | Timestamp on every row |
| Runtime | ≤ 30 min/week, unattended | Logged per run |
| Cost | ≤ $5/week in API calls | Logged per run |

The pipeline is done for v1 when four consecutive weekly runs hit the precision target and the review step takes under 20 minutes.

## What counts as an AI company

An **AI company** is one whose primary product would not exist without machine learning or LLMs — the model is the product or the core of it, not a feature bolted onto something else. The rubric below is the exact text the classifier receives; changing it changes the signal, so it is versioned.

**Rubric v2** (2026-10-29; v1 was the original text, changed by decisions 18–19 after the golden-set review).

**Include (any one is sufficient):**

- Builds or trains models, or sells model access or infrastructure (inference, evals, observability, data labeling, guardrails)
- Sells a product whose core function is performed by a model: agents, copilots, document intelligence, decisioning, generation, detection, forecasting
- Describes itself with "AI" or "ML" as the lead noun of the product, and the homepage describes what the model does, not just that it exists
- Sells a tool where named AI agents perform a core job and the homepage says what work they do, even if the underlying tool would work without them

**Exclude (any one is disqualifying):**

- AI appears only as a feature list item ("AI-powered insights") on a product that would work without it, with no named agent doing a core job — a CRM, a marketplace, a logistics network, a bank
- Services firms, agencies, consultancies, even "AI consultancies"
- Hardware, chips, robotics, biotech, drug discovery (real AI, wrong lane for this search)
- Crypto, Web3, or anything whose homepage mentions tokens
- Companies whose homepage leads with Public Sector, Federal, Defense, or National Security as a main focus (a government or defense customer listed among many industries is fine)

**Uncertain:** if the classifier cannot decide from the evidence, the row goes to a review queue, never to the output. Uncertain is a valid answer; a confident guess is not.

The rubric is deliberately strict on "bolted-on AI." In 2026 nearly every SaaS homepage says AI; the test is whether the homepage explains what the model does.

## Sources

EDGAR Form D is the only primary source; everything else enriches a name EDGAR already gave us. Form D is filed within 15 days of first sale under Regulation D, so it is the earliest public record of a round and catches seed rounds that never get press.

| Source | Role | What it gives | What it lacks | Cost |
| --- | --- | --- | --- | --- |
| [EDGAR full-text search](https://efts.sec.gov/LATEST/search-index) | Primary feed | Every Form D in a date window: company name, CIK, accession number | Any description of the business | Free, rate-limited (\~10 req/s, User-Agent header required) |
| Form D XML (`primary_doc.xml` per filing) | Primary detail | Offering amount, amount sold, industry group, state, related persons (officers, directors), first-sale date | Sector beyond coarse buckets | Free |
| Company homepage (fetched) | Enrichment, evidence | What the product is, in the company's own words | Exists only if we find the URL | Free |
| Web search (one query per candidate) | Enrichment | Homepage URL, press coverage, a snippet | Noisy for common names | Low |
| LinkedIn company page | Enrichment, optional | Headcount band, HQ | Blocks scraping; manual lookup only | Manual |
| Crunchbase / newsletter deal lists | Validation only | A weekly list of announced rounds to measure recall against | Lags EDGAR by days to weeks | Free tier |

Two Form D fields do most of the pre-filtering. **Industry Group** keeps `Other Technology`, `Business Services`, `Other` and `Computers` (decisions 15, 17) and drops `Real Estate`, `Oil and Gas`, `Banking`, `Pooled Investment Fund` and the rest (funds file Form D constantly and are the largest source of noise). **Amount Sold** keeps $1M–$50M (`offering_total` can be a placeholder, so it is not used). Both are structural fields, so they never need a model.

Geography is US only for v1 (decision 10). Form D only covers US issuers; adding UK/EU means Companies House or Dealroom, a different build.

## Pipeline stages

Seven stages, each a separate Python function with its own input and output file, so any stage can be re-run alone. Stages 1–3 touch no model and cut a few hundred weekly filings to roughly 30–80. Stages 5 and 6 are the CASDAM pattern: a generator and a structurally different verifier, and only agreement ships.

&#91;embedded content: pipeline · 7 stages, 1 review queue\]

A filing moves down the column; anything the two models cannot agree on, or either calls uncertain, goes right to the review queue instead of the sheet. Every review decision becomes a labeled example, so the test set grows for free.

## Data model

One Pydantic record per filing carries through every stage; each stage adds fields and never overwrites earlier ones. That makes a bad output row traceable to the stage that produced it.

| Field | Set by stage | Type | Notes |
| --- | --- | --- | --- |
| `accession_no` | 1 Pull | str | Primary key; one Form D = one row |
| `cik`, `company_name` | 1 Pull | str | As EDGAR prints them |
| `filing_date`, `first_sale_date` | 2 Parse | date | Freshness is measured from `filing_date` |
| `offering_total_usd`, `amount_sold_usd` | 2 Parse | int | `amount_sold` is the real signal; `offering_total` can be a placeholder |
| `industry_group` | 2 Parse | str | EDGAR's enum, verbatim |
| `state`, `city` | 2 Parse | str | Issuer address |
| `related_persons` | 2 Parse | list\[Person\] | Name + relationship (Executive Officer, Director, Promoter); these are the outreach targets |
| `is_amendment` | 2 Parse | bool | `D/A` filings are dropped unless `amount_sold` rose |
| `previous_accession_no` | 2 Parse | str | The filing a `D/A` amends; its `amount_sold` is the comparison for the amendment rule |
| `parse_error` | 2 Parse | str | Null unless the XML could not be fetched or read |
| `passed_structural` | 3 Filter | bool | Plus `drop_reason` when false |
| `homepage_url`, `search_snippet` | 4 Enrich | str | Null allowed; a null homepage after two searches drops the row as "no homepage found" (decision 23) |
| `evidence_text` | 4 Enrich | str | Homepage text, capped at \~1,500 words |
| `homepage_match`, `enrich_note` | 4 Enrich | str | `strong` (name and identity confirmed) or `weak` (name only, or identity only); note says why a homepage is missing |
| `classify_a` | 5 Classify | Verdict | `{label: yes/no/uncertain, confidence: 0-1, reason: str, rubric_version: str}` |
| `classify_b` | 6 Verify | Verdict | Same shape, different model and prompt |
| `final` | 6 Verify | enum | `ship`, `review`, `drop` |
| `human_label` | Review | Verdict | Filled by Dan; becomes a test-set example |
| `run_id`, `processed_at` | every stage | str, datetime | One run = one dated folder of JSONL files |

Storage is JSONL per stage per run (`runs/2026-11-01/03_filtered.jsonl`), plus one append-only `labels.jsonl` for the test set. No database until the files stop being enough.

Two fields come from outside the pipeline and are merged at build time from `tracking.yml`, keyed on `cik`: `contacted` (bool, default false) and `note` (str, default empty). Dedupe is on `cik`, so `accession_no` stays the key for filings and `cik` becomes the key for dashboard rows.

## Precision controls

Five mechanisms keep false positives near zero. They are the same ones in the AI Operations Specification, applied to a one-person pipeline.

1. **Evidence or nothing.** The classifier sees only `evidence_text` from the company's own homepage plus the search snippet. No homepage found (after a second search with the founders' names) means the row is dropped as "no homepage found" and listed in the run summary, never a guess from the company name. A name like "Foo AI Inc" is not evidence.
2. **Generator/verifier separation.** Model A classifies with the rubric. Model B, an open-weight model from a different model family, sees the same evidence and a differently worded prompt that asks it to argue the company is *not* an AI company, then give a verdict. Only two `yes` verdicts ship. Disagreement goes to review. When the homepage match is `weak`, both models also get the Form D facts (name, city, related persons) and must each confirm the homepage is the same company, or the row goes to review (decision 22).
3. **Confidence floor.** Either model under 0.8 confidence routes to review regardless of label.
4. **Golden set.** Before the first real run, hand-label 60 filings: 20 clear AI, 20 clear non-AI, 20 hard cases (bolted-on AI, consultancies, robotics). Every rubric or prompt change is re-run against this set and must hold precision ≥ 95% before it ships. The set grows from review decisions.
5. **Weekly audit.** After each run, 20 output rows are sampled and checked by hand against the homepage. Any false positive gets a postmortem line: which stage let it through, and what rubric or filter change prevents the class of error. The fix is a new golden-set example, not a one-off patch.

Measured error rate is reported per run as `false_positives / shipped_rows` with the sample size beside it, so a 0% on 20 samples is read as "under \~15%", not "perfect."

## Output and cadence

The output is a dashboard on GitHub Pages: one newest-first table, sortable and filterable, one row per company keyed on CIK. The pipeline writes `dashboard/data.json` and commits it; Pages rebuilds. Outreach tracking lives in `tracking.yml` in the same repo (one entry per CIK: `contacted: true/false`, `note: "..."`), edited by Dan and merged into `data.json` at build time, so the pipeline never overwrites a note.

| Column | Source | Example |
| --- | --- | --- |
| Company (links to homepage) | pipeline | Pinch AI |
| Filing date | pipeline | 2026-01-12 |
| Amount sold (USD) | pipeline; updated if a later filing is higher | 5,000,000 |
| State | pipeline | CA |
| One-line description (model A, ≤ 20 words) | pipeline | Post-purchase risk platform deciding returns and refunds for retailers |
| Related persons | pipeline | Arthi Rajan Makhija (Executive Officer); … |
| EDGAR filing | pipeline | link to the Form D |
| Contacted + note | `tracking.yml` | ✓ · "Sent LinkedIn message 11/3, referenced Refund Gate" |

**Merge rule:** a company already in `data.json` keeps its row; a later Form D for the same CIK updates `amount_sold` and sets `last_updated` only when the amount rose. Contacted and note are never touched by the pipeline. Polish level is clean and functional: good type, sortable columns, filters on state, amount, contacted; no summary header, no detail panel in v1.

**Cadence:** a GitHub Actions workflow runs the pipeline every Monday 6am CT on the prior 7 days and commits `data.json`; Pages redeploys on the commit. A `workflow_dispatch` input `since` allows a one-off backfill (the last 90 days, run once to seed the dashboard). Secrets (the model-hosting API key) live in repository secrets, never in the repo.

## Build plan

Ten steps, in order, each ending with something that runs. No step opens until the one before it produces a file you can look at. Estimated 13–17 hours total; steps 1–4 are the first day. The repo is created in step 0 so every later step commits into it.

- [x] **Step 0 — Repo (30 min).** Create the GitHub repo with `pipeline/`, `dashboard/`, `tracking.yml`, `runs/` (gitignored except summaries), `requirements.txt`. Make the repo public and publish `dashboard/` to Pages through a deploy workflow (Pages cannot serve a `dashboard/` folder directly). Done when a placeholder `index.html` is live at the Pages URL.
- [x] **Step 1 — Pull (1 hr).** `pull.py`: hit the EDGAR full-text search for `forms=D` over a date range, page through results, write `01_filings.jsonl` with accession, CIK, name, filing date. Done when a 7-day pull returns a few hundred rows and a re-run is idempotent. (First test, 2026-10-21 to 10-27: 1,266 filings including D/A, ~5 seconds; re-run identical.)
- [x] **Step 2 — Parse (2 hrs).** `parse.py`: fetch each filing's `primary_doc.xml`, map the fields in the data model, respect the rate limit, cache every XML locally. Done when every row has amount, industry group, state, and related persons, and a second run fetches nothing new. (First test, same week: 1,266 parsed, 0 errors, ~3 min; re-run downloaded 0.)
- [x] **Step 3 — Structural filter (30 min).** `filter.py`: apply industry group, amount band, amendment rule. Write `drop_reason` on every dropped row. Done when the survivor count is 30–80 for a 7-day window and spot-checking 10 drops shows no AI company among them. (First test, same week: 66 survivors; AI-named drops were all outside the amount band, by design.)
- [x] **Step 4 — Golden set (1.5 hrs).** Hand-label 60 survivors from a backfill pull into `labels.jsonl`. Done before any prompt is written, so the prompt is tested against labels it did not see.
- [ ] **Step 5 — Enrich (2 hrs).** `enrich.py`: one web search per survivor, pick the homepage, fetch and strip it to text, cap length. Done when ≥ 80% of survivors have `evidence_text` and the rest are marked null.
- [ ] **Step 6 — Classify + Verify (2 hrs).** `classify.py`: rubric v1 as a prompt, Pydantic-validated JSON verdict, model A then model B, agreement logic, review routing. Done when precision on the golden set is ≥ 95% and the review queue holds the hard cases, not the easy ones.
- [ ] **Step 7 — Merge + data.json (1 hr).** `output.py`: dedupe on CIK against the existing `data.json`, apply the amount-update rule, merge `tracking.yml`, write `dashboard/data.json` and a run summary (counts per stage, cost, runtime). Done when a second run changes nothing it shouldn't.
- [ ] **Step 8 — Dashboard (2–3 hrs).** `dashboard/index.html`: one self-contained page that loads `data.json`, renders the eight columns newest-first, sorts on any column, filters on state, amount, and contacted. Done when the ten companies from the target list render cleanly from a hand-made `data.json`.
- [ ] **Step 9 — Actions (1 hr).** Workflow: cron Monday 6am CT plus `workflow_dispatch` with a `since` input; installs requirements, runs the pipeline, commits `data.json` and the run summary. API keys in repository secrets. Done when the first scheduled run lands rows on the live page without you touching it.
- [ ] **Step 10 — Audit routine (30 min).** A 20-row audit checklist for Sunday review and a one-line postmortem format for any false positive. Done when it has been used once.

Order matters at one point: the golden set (step 4) comes before the classifier (step 6). Writing the prompt first and then labeling what it got right is how a pipeline grades its own homework.

## Open decisions

All resolved by logic gate on 2026-10-28 (decisions 9–13 in the decision log). The table keeps the original options for reference.

| Decision | Options | Chosen | Why |
| --- | --- | --- | --- |
| Time window | 7 / 14 / 30 days per run | 7 days, weekly, plus a one-time 90-day backfill | Matches the Sunday/Monday cadence; backfill seeds the dashboard on day one |
| Geography | US only (Form D) vs. add UK/EU | US only for v1 | Form D is free and structural; EU sources are a second build |
| Amount band | $1–50M vs. wider | $1–50M on `amount_sold` | Under $1M is friends-and-family; over $50M is past the created-role window |
| Models A and B | Which two providers | Two open-weight models from different families, through one hosting service (e.g. OpenRouter); exact models picked in step 6 | Good results at a low price; different families keep the verifier independent; one key, one code path |
| Repo visibility | Public (free Pages) vs. private (GitHub Pro, \~$4/mo) | Public, notes included | Free Pages and Actions; Pages is public even on a private repo, so private bought little. Accepted: `tracking.yml` notes and their git history are public |

One more decision is not the pipeline's: **what happens to the output.** The dashboard produces candidates; the three-company outreach already scoped is still the first thing to send. The pipeline is the weekly feed behind it, not a reason to wait.

## Decision log

Decisions made by logic gate on 2026-10-28. Each line: what was decided, why, and where it lives in this spec.

| # | Decision | Chosen | Why | Lives in |
| --- | --- | --- | --- | --- |
| 1 | Monday landing view | Newest-first table with filters | Simple, fast to build; Dan decides what matters | Output and cadence |
| 2 | Outreach status model | Binary contacted + free-text note | Lowest friction; staleness tracking not needed yet | Output and cadence; Data model |
| 3 | Polish level | Clean and functional | Laptop-only, nobody else sees it | Output and cadence |
| 4 | Where it lives | GitHub Actions runs the pipeline; GitHub Pages serves the dashboard (changed from a hosted artifact) | Dan's choice; keeps pipeline and dashboard in one repo with history | Output and cadence; Build plan |
| 5 | Where tracking lives | `tracking.yml` in the repo, merged at build | Durable, versioned, no tokens in the browser; cost is a commit per update | Output and cadence; Data model |
| 6 | Table fields | Core eight | Everything that drives a decision, nothing that doesn't | Output and cadence |
| 7 | Duplicate filings | One row per CIK; later filing updates amount only; tracking untouched | Keeps the dashboard one-row-per-company without losing a seed-to-A step-up | Output and cadence; Data model |
| 8 | Scope | One build; the dashboard is the v1 output | No throwaway CSV; one weekend | Build plan |
| 9 | Time window | 7 days, weekly, plus a one-time 90-day backfill | Matches the Monday run with no overlap; backfill seeds the dashboard | Output and cadence; Open decisions |
| 10 | Geography | US only (Form D) for v1 | Free and structural; UK/EU is a second build | Sources; Open decisions |
| 11 | Amount band | $1M–$50M on `amount_sold` | Money actually raised; `offering_total` can be a placeholder. Accepted: rounds filed with under $1M sold so far are dropped | Sources; Open decisions |
| 12 | Models A and B | Two open-weight models from different families via one host (e.g. OpenRouter); exact models chosen in step 6 against the golden set | Value: good results, low price; family difference keeps verification independent | Precision controls; Open decisions |
| 13 | Repo visibility | Public repo, GitHub Pages, notes included in `tracking.yml` | Free hosting and Actions; private repo would still have a public Pages site. Accepted: notes are public, including git history | Build plan; Open decisions |
| 14 | EDGAR contact | Personal email in the User-Agent, read from the `EDGAR_CONTACT_EMAIL` repository secret / env var | SEC requires contact details; owner is fine with SEC knowing; keeps it out of the public code | Build plan (step 1); `pipeline/edgar.py` |
| 15 | Industry groups kept | `Other Technology`, `Business Services`, `Other` | Some AI startups tick the catch-all `Other`; ~55/week stays inside the 30–80 target and the classifiers drop the rest for cents | Sources; `pipeline/filter.py` |
| 16 | Amendment comparison | Compare a `D/A`'s `amount_sold` to the filing it amends (`previous_accession_no`); keep only if it rose | Accurate, catches rounds that grow after first filing; ~10 extra cached downloads/week | Data model; `pipeline/filter.py` |
| 17 | Add `Computers` industry group | Keep `Computers` too | Near-free insurance: 3 filings in the test week, none in band; some AI companies may pick it | Sources; `pipeline/filter.py` |
| 18 | Golden-set labeling | Claude pre-labels 60 from homepages; owner reviews the 20 hard cases | Keeps owner time to ~20–30 min; classifiers are other model families, so less self-grading risk | Build plan (step 4); `labels/golden_set.csv` |
| 19 | Defense exclusion (rubric v2) | Exclude only when the homepage leads with defense / national security / public sector; a listed government customer is fine | Owner labeled CVAT.ai yes despite a Military & Defense industry listing | What counts as an AI company |
| 20 | Agents on a regular tool (rubric v2) | Include when named agents perform a core job and the homepage says what they do | Owner labeled CandorIQ, Allstacks, Lexful yes; plain "AI-powered" lines still excluded | What counts as an AI company |
| 21 | Search provider | Tavily (free 1,000 searches/month, no card; then $0.008/search) | Covers ~240/month weekly runs plus backfill; returns page text as a fallback | Sources; `pipeline/enrich.py` |
| 22 | Weak homepage matches | Both classifiers also confirm the homepage is the same company (given name, city, people); otherwise review | Keeps the review queue small (~1 in 3 real homepages match only weakly) while a wrong site still has to fool two models | Precision controls; `pipeline/classify.py` |
| 23 | No homepage found | Second search (name + executive officers); if still none, drop with reason "no homepage found", listed in the run summary | ~1/3 of survivors are vehicles with no website; sending them to review would break the 20-minute review goal; the second search recovers real companies the first missed | Precision controls; Data model; `pipeline/enrich.py` |
