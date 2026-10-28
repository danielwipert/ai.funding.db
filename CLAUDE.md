# AI Funding Scanner — notes for Claude

The design lives in `planning_docs/AI_Funding_Scanner_Pipeline_Spec_v1.md`.
Read it before starting a build step. Build steps run in order (see the
spec's "Build plan" and the checklist in `README.md`).

## Working style

- The owner codes mostly in Python and likes to go step by step.
- Don't assume they know how to do everything. Keep things simple and break
  tasks into small, numbered steps.

## Logic gates (how to ask for decisions)

When a path forward needs my decision, don't write one long answer with a big decision at the end.

- Break the decision into small **gates**, one at a time.
- Each gate gives **three clear options**, labeled A, B and C, readable in about one minute.
- Mark the recommended option.
- Keep each option to one or two lines: what it means and what it leads to.
- When there are several gates, show the path first (numbered list, current gate marked).
- After I pick, lock it in with one line, then move to the next gate.
- I may tweak an option ("A, but ..."); restate it and move on.
- When the gates are done, record the decisions in the project's decision log.

The decision log is the "Decision log" table at the end of the spec
(date, decision, chosen, why, where it lives). Update the spec section the
decision affects as well. The full method is in `planning_docs/logic_gates.md`.
