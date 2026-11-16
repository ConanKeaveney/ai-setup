# ADR template

An ADR (architecture decision record) captures one decision, its context and its consequences, in
one or two pages (Nygard). Use it for a decision that is already scoped, usually a child of a design
doc, or for a blocked decision where the right move is to make a guess and record it (Reilly).

Rules:

- **Numbered in sequence, never reused.** Store with the code that owns the decision, e.g.
  `docs/adr/<NNNN>-<decision-title>.md`, or wherever the team keeps them.
- **Immutable once accepted.** To change a decision, write a new ADR that supersedes it and mark the
  old one "Superseded by ADR-NNNN". Never delete; the old record explains why things are the way
  they are.
- **Full sentences**, written as a conversation with a future engineer (Nygard). Bullets only for
  lists of consequences.
- **The validation rule still applies.** The ADR states how the decision was validated, with the
  headline number and a link. If the decision was a deliberate guess, say so, and name the check
  and date at which it will be revisited (the "Confirmation" idea from MADR).
- House style: plain English, the decision first, numbers kept, no § symbol, no inline "see
  other-doc" references; links go in the Links line.

A good ADR has issue, decision, status and consequences, with measured outcomes and an increase,
decrease and net cost table.

---

# ADR-<NNNN>: <Decision as a short noun phrase>

| | |
|---|---|
| **Status** | <Proposed · Accepted · Deprecated · Superseded by ADR-NNNN> |
| **Date** | <YYYY-MM-DD> |
| **Deciders** | <names> |
| **Parent design doc** | <title and link> |
| **Links** | <POC code or notebook, ticket, related ADRs> |

## Decision

<One or two sentences in active voice, starting "We will…". This is the first thing a reader sees.>

## Context

<The forces at play: technical, cost, organisational, deadline. Current numbers. What problem this
decision answers and why it must be made now. Neutral and factual; two or three short paragraphs.>

## Options considered

<Brief: each option in a sentence or two with the deciding reason it lost. Include do nothing. For a
fuller comparison, paraphrase the parent doc's conclusion here rather than pointing at it.>

## Validation

<How we know this is right, or how we will find out.>

- **Test:** <what was run, on what data>
- **Threshold set before the run:** <…>
- **Result:** <number, n, range> — <pass/fail> — <link>
- **Revisit if:** <the signal or date that would reopen the decision, e.g. "table passes 6B rows" or "2027-04-01">

## Consequences

*Positive, negative and neutral. Numbers where they exist.*

- <Good: …>
- <Bad: …, and how we live with it>
- <Neutral: … e.g. "We now maintain three tables to resolve properties instead of two.">

| Cost item | Increase ($/month) | Decrease ($/month) | Notes |
|---|---|---|---|
| <…> | <…> | <…> | <…> |
| **Total** | <…> | <…> | **Net: <…>** |

*(Cost table optional; include it when the decision changes run-rate cost.)*
