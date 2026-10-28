# Logic Gates: A Simple Way to Make Decisions with Claude

A method for working through design decisions with an AI assistant, one small choice at a time.

## The problem it solves

When a decision is complex, AI assistants tend to write one long answer: background, analysis, trade-offs, and a big decision at the end. That's slow to read and hard to act on. You end up processing a lot just to say yes or no.

## The idea

Break every big decision into a series of small ones, called **logic gates**.

- Each gate is **one decision**.  
- Each gate gives **three options**: A, B and C.  
- Each gate takes **about one minute** to read and answer.  
- You answer, the assistant locks it in, and the next gate follows.

Five quick gates are easier than one big decision, and they usually lead somewhere better, because each answer shapes the next question.

## How a gate looks

```
## Gate 2: Who keeps the discount when we negotiate better host prices?

**A. Customers keep all of it** *(recommended)*
One or two lines: what it means and what it leads to.

**B. We keep a disclosed share**
One or two lines.

**C. Decide later**
One or two lines.

Reply A, B or C.
```

&nbsp;

## The rules

**For the assistant:**

1. **One gate at a time.** Don't stack several decisions in one message.  
2. **Three options, always.** Label them A, B and C.  
3. **Mark one as recommended**, and say why in a few words.  
4. **Keep each option to one or two lines:** what it means and what it leads to.  
5. **Show the path when there are several gates.** For example: "5 gates: 1\. Position ← now, 2\. Pricing, 3\. ..."  
6. **Lock in each answer** in one line before moving on: "Locked in: B, we keep a share."  
7. **Accept answers that mix or adjust options.** "A, but opt-out instead of opt-in" is a good answer. Restate it clearly and move on.  
8. **Record decisions** in a decision log once the gates are done (date, decision, why, and where it lives).  
9. **Keep everything else short.** Background goes in documents, not in the gate.

**For you:**

- Answer with a letter, or a letter plus a tweak.  
- Push back anytime. If none of the options fit, say so, and the assistant reframes the gate.  
- If a gate feels too big, ask for it to be split into smaller gates.

## A real example

These five gates settled a startup's positioning in about ten minutes:

| Gate | Question | Answer |
| :---- | :---- | :---- |
| 1 | What does the pitch lead with? | A: Neutral fleet operator |
| 2 | Who keeps negotiated discounts? | B: We keep a disclosed share |
| 3 | What learning is shared across customers? | A, adjusted: results only, but opt-out instead of opt-in |
| 4 | How is constant change governed? | A, adjusted: tiered by risk, with special rules for heavily regulated work |
| 5 | First segment? | A: Insurers |

&nbsp;

Notice that two answers were tweaks, not straight picks. That's expected. The options are a starting point for your judgment, not a menu you're stuck with.

## How to use it in another project

Copy the block below into the project's `CLAUDE.md` file (Claude Code reads this file automatically at the start of every session). Or paste it at the start of a chat.

```markdown
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
```

&nbsp;

## Why it works

- **Fast:** each choice takes about a minute, so momentum stays high.  
- **Clear:** small decisions are easier to get right than big bundled ones.  
- **Steerable:** you correct course at every step, not only at the end.  
- **Recorded:** the decision log keeps a trail of what was decided and why.