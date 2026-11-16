# Review checklist

Use part 1 on every draft Claude writes, before handing it back. Use part 2 when reviewing
someone else's doc. Part 3 is the fresh-reader test, used in both.

## Part 1: self-review

### Gate (any "no" means the doc is not ready for review)

- [ ] **Header:** author, named reviewers with what each checks, one decider, status, created and
      updated dates, comment deadline, links.
- [ ] **TL;DR:** all six fields (problem, proposal, key decisions, validated, cost and effort, ask);
      leads with the recommendation; 150–250 words; real numbers; ask names who, what and by when.
- [ ] **Validation:** every key decision has a dated plan written before the run (hypothesis,
      metric, threshold, decision rule) and a recorded result with pass/fail and a link to code or
      notebook. Substitutes for a full POC are named and justified. Nothing says "no validation".
- [ ] **Alternatives:** do nothing plus at least two real options, compared on the same criteria,
      each with a flip condition.
- [ ] **No placeholders on the critical path:** no TBD, VERIFY or DECISION NEEDED left on a key
      decision.
- [ ] **House style:** no § symbol; no inline "see other-doc" references; links only in the Links
      section.

### Problem and goals

- [ ] Current state is stated with numbers (volume, latency or freshness, cost, failures).
- [ ] "Why now" is explicit.
- [ ] Do-nothing projection has a number and a date.
- [ ] Goals are measurable and could be checked after launch.
- [ ] Non-goals name things a reader might reasonably expect.

### Proposal

- [ ] Opens with an overview a newcomer understands, then a diagram.
- [ ] Data model, interfaces and contracts are sketched; no pasted code beyond data shapes or a
      novel algorithm.
- [ ] Each key flow has a failure and recovery path.
- [ ] Concrete enough to argue with (better wrong than vague): named technologies, sizes,
      schedules, keys.
- [ ] Human or workflow changes are designed, not assumed (Reilly).

### Key decisions and validation

- [ ] Key decisions table lists 2–4 decisions with reversibility and a link to validation.
- [ ] The riskiest decisions were chosen by uncertainty, cost of being wrong and irreversibility.
- [ ] Each test reproduced the condition the decision is sensitive to (churn, skew, peak,
      concurrency, cold cache), or the doc says it didn't and where the gap is closed.
- [ ] Baseline measured the same way as the candidate.
- [ ] Results report n, median, p95 and range; cost comes from billing data or a measured unit cost.
- [ ] "What surprised us" and "what this does not prove" are filled in.
- [ ] Any threshold change after the run is recorded with the reason.

### Alternatives

- [ ] Each option is steelmanned: why it was attractive.
- [ ] The deciding reason for each rejection is evidence, not preference.
- [ ] Buy versus build was considered where a product exists.
- [ ] Abandoned ideas are listed briefly.

### Cost, rollout, cross-cutting

- [ ] Cost table shows increase, decrease and net per month, with assumptions and the dominant input.
- [ ] Effort in people-weeks by phase; what we stop doing.
- [ ] Phases have exit criteria and rollback; the first irreversible step and its pre-check are named.
- [ ] Security, privacy and compliance (PII, deletion requests, access), data quality and
      contracts, schema evolution, observability, SLAs and on-call, cost attribution are each
      addressed or explicitly out of scope with a reason.
- [ ] Each metric's query is written and is about one line.
- [ ] Outcomes are one counter tagged by outcome, emitted on every exit path, with the same
      dimensions on success and error.
- [ ] No tenant, user or request ids or exception text as metric labels; those go in a structured
      event.
- [ ] Batch or sparse jobs alert on time since last success.
- [ ] New alerts start at the lowest priority for a week before promotion.
- [ ] Open questions each have an owner and a date.

### Writing

- [ ] Every section and paragraph leads with its point.
- [ ] Every acronym and internal name has a one-line gloss on first use.
- [ ] Numbers instead of adjectives ("fast", "scalable", "cheap" are replaced).
- [ ] Active voice; "we will".
- [ ] No filler ("it's worth noting"), stacked hedges, rhetorical questions or dramatic headers.
- [ ] Tables for comparisons, prose for reasoning; no walls of text.
- [ ] Length fits the decision: mini doc 1–3 pages, full doc 5–15; anything longer is split.

## Part 2: reviewing someone else's doc

### Procedure

1. Read only the header and TL;DR. Write down, in one sentence each, what is being decided, what
   evidence supports it, and what you are being asked to do. Any gap is your first comment.
2. Read the problem and goals. Do you agree this is the right problem and the goals are the right
   bar? If not, stop and say so; reviewing the solution is wasted effort.
3. Read the key decisions and validation. For each decision: was it tested, were criteria set before
   the run, did the test reproduce the condition that matters, do the numbers support the claim?
4. Read the alternatives. Is do nothing there? Are the others real? Would you have chosen
   differently, and what evidence would settle it?
5. Read the rest at a depth proportional to irreversibility.
6. Ask Reilly's six questions of the whole: should this exist; does it solve the problem; will it
   handle failure; is it understandable; does it fit the bigger picture; do the right people know?

### Comment format

- Label each comment **Blocking**, **Should fix** or **Nit**.
- One issue per comment. Quote the text. Say what is wrong in one sentence. Propose a fix or name
  the evidence that would resolve it.
- Phrase blockers as "Yes, if…" (Squarespace): "Yes, if the MoR benchmark is rerun after 7 days of
  simulated churn."
- Common blocking issues: an unvalidated key decision; criteria set after results; a test that
  didn't reproduce the decisive condition; no do-nothing; a one-option doc; no rollback for a
  one-way door; missing PII or deletion handling; cost with no net figure.

### Report to the user

First line: **Approve**, **Yes, if…** or **Not yet**, and the one reason. Then the blocking list,
then should-fix, then nits (or "nits omitted" if there are many). Don't rewrite the author's doc
unless asked; respect their voice and structure where it works.

## Part 3: fresh-reader test

Spawn a subagent with no other context. Give it only the doc's header and TL;DR, and this prompt:

> You are a busy engineering director. From the text below only, answer in three lines:
> (1) what is being decided and what is recommended; (2) what evidence supports it, with the
> number; (3) what you are being asked to do, and by when. Then list any term you did not
> understand and any claim you would not accept without more evidence.

If any answer is wrong, missing or hedged, rewrite the TL;DR and run it again. Then repeat with the
whole doc and the question "what is the weakest part of this proposal?" and check that the doc
already answers it.
