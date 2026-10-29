# Weekly audit routine (about 20 minutes, Sunday or Monday)

The spec's precision target is 95%: a company on the dashboard must be a real AI company. This routine checks that, and turns every mistake into a fix.

## Steps

1. **Pull the latest results** (the Monday run commits them):

   ```bash
   git pull
   ```

2. **Decide the "Needs review" companies.** Open the dashboard, look at each company in the "Needs review" table, and add one line per company to `review.yml`, e.g. `"0002054765": yes` or `"0002054765": no`.

3. **Make this week's audit checklist:**

   ```bash
   python -m pipeline.audit
   ```

   This writes `audits/<date>.md`. For the first four weeks it lists every company added that week; after that, a random 20.

4. **Check each company.** Open its homepage and ask: is this an AI company under the rubric (`pipeline/rubric_v2.md`)? Tick the box if yes.

5. **Write a postmortem line for every false positive**, in the file:

   `company | stage that let it through | what fixes the whole class of error | golden-set row added? (y/n)`

   The fix is a new golden-set example (add the company to `review.yml` as `no`, or a row in `labels/golden_set.csv`), and, if needed, a rubric or filter change that is re-tested with `python -m pipeline.evaluate` before it ships. Never a one-off patch.

6. **Fill in the result line** (false positives / checked, and the time it took), then commit:

   ```bash
   git add audits review.yml tracking.yml
   ```

   ```bash
   git commit -m "Weekly audit"
   ```

   ```bash
   git push
   ```

## Reading the error rate

Report it as `false positives / companies checked`, with the count beside it. Zero mistakes in 20 checked means "under about 15%", not "perfect"; the estimate only tightens as audits add up.

## When v1 is done

Four weekly runs in a row at 95%+ precision, with this review taking under 20 minutes.
