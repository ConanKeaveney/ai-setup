---
name: design-doc
description: >-
  Write, draft, review or improve a technical design doc the way a strong staff engineer would:
  RFCs, tech specs, architecture proposals, one-pagers, and the ADRs (decision records) that go
  with them. Enforces a metadata header + TL;DR and evidence-backed key decisions.
  Covers doc vs ADR vs nothing, the section skeleton, alternatives considered, a self-review
  gate, and reviewing someone else's doc. Triggers: "design doc", "write a design doc", "RFC",
  "tech spec", "architecture proposal", "ADR", "decision record", "review my design doc",
  "proposal", "one-pager", "POC", "prototype", "spike", "benchmark plan", "alternatives
  considered", "TL;DR".
---

# Design Docs

A design doc exists to get the right decision made early, while changing it is cheap, and to
leave a record of why. It is judged by two things: whether a busy reader can act on the top of
it, and whether its key decisions are backed by evidence rather than confidence.

Reference files (load when needed):

- [references/template.md](references/template.md) — the full fill-in-the-blanks doc, metadata to links.
- [references/poc-validation.md](references/poc-validation.md) — designing POCs and benchmarks for
  data-platform decisions (engine/vendor, table format, layout, freshness, cost), with worked examples.
- [references/review-checklist.md](references/review-checklist.md) — the self-review gate and the
  procedure for reviewing someone else's doc.
- [references/adr-template.md](references/adr-template.md) — short Nygard-style ADR for one decision.
- [references/threat-model.md](references/threat-model.md) — STRIDE-per-data-flow threat model,
  method and template, for the Security cross-cutting concern.
- [references/examples.md](references/examples.md) — a good and a bad TL;DR, validation and
  alternatives section for a realistic data-platform decision.

For the technical substance, also load the domain skill that applies (`iceberg`, `databricks`,
`snowflake`, `spark`, `opensearch`, `graphql`). For "is this doc worth my time" or strategy
questions, load `staff-engineer`: after about five design docs, synthesise the recurring
decisions into a strategy (Larson, *Write five then synthesize*).

## Two non-negotiable rules

1. **Every key decision is validated.** Each one has a POC, spike, benchmark, prototype or a
   narrower substitute, with the hypothesis and pass threshold written down *before* it ran, and
   the result recorded in the Validation section with numbers and a link to the code. A doc whose
   key decision has no validation is **not ready for review**, whatever else is good about it.
2. **The top is a metadata header plus a TL;DR** that states the problem, the proposal, the key
   decision(s), what was validated and the headline result, cost and effort, and the ask with a
   date. A director should be able to stop reading after it and still approve or decline.

## Which document, if any

| Situation | Write |
|---|---|
| New system or major change; more than ~1 month of engineering; crosses teams; hard to reverse; sets a precedent; or changes run-rate cost materially | **Design doc** (5–15 pages; Google's sweet spot for large projects is 10–20) |
| Ambiguous but small: one team, a few weeks, still has real trade-offs | **Mini design doc** (1–3 pages): same skeleton, every section short. Validation still required. |
| One decision, already scoped, often a child of a design doc; or a blocked decision you need to "make a guess and record" (Reilly) | **ADR** — use [references/adr-template.md](references/adr-template.md) and link it to its parent doc |
| Obvious solution, no real trade-offs, easily reversed, and the user is the decider | **Nothing.** State the approach in a sentence, get agreement, build it (Ubl; Sourcegraph) |

Google's quick test: write a doc if three or more are true — the design is ambiguous, senior
input would help, it is contentious, cross-cutting concerns tend to get forgotten, or the system
needs high-level documentation. If a doc would read as an implementation manual with no
trade-offs, skip it.

## Drafting procedure

Usual order; skip or merge a step when it clearly doesn't apply, but never skip validation (steps 6–7) or the self-review (step 9).

1. **Frame the job.** Who decides, who reviews, who is affected, and by when a decision is needed.
   Ask the user only what the evidence cannot answer, one question at a time. Calibrate background to
   the audience: own team gets little, other teams get their missing context.
2. **Gather evidence before writing.** Read existing design docs, ADRs, incident reports, the code,
   dashboards and query history. Pull the current numbers: volume, latency, freshness, cost per
   month, error rates, on-call load. A problem without a number is not yet a problem statement.
3. **Write the problem, goals and non-goals first.** Goals are measurable ("p95 dashboard load
   under 3 s at 200 concurrent users"), not adjectives. Non-goals are things a reader could
   reasonably expect that are deliberately out (Ubl). If the problem is contested, circulate just
   this part as *Draft: reviewing problem* before designing (Sourcegraph).
4. **List the options and the criteria.** At least two real alternatives plus *do nothing*. Score
   every option against the same criteria.
5. **Name the riskiest decisions.** For each candidate decision ask: how unsure are we, how bad is
   being wrong, and how hard is it to reverse? One-way doors with high uncertainty go first.
   Usually two to four decisions carry the doc; name them in a Key decisions table.
6. **Plan the validation** for each risky decision: hypothesis, method, dataset, metric, pass
   threshold, the result that would change the decision, timebox and owner. Write this down and
   show it to the user before anything runs. Details and worked examples are in
   [references/poc-validation.md](references/poc-validation.md).
7. **Run or help run the POCs.** Claude can write the benchmark harness, the notebook, the cost
   model and the replay script. Record environment, versions, data size and commit hash. Code is
   throwaway; results are not.
8. **Write the rest of the doc** from [references/template.md](references/template.md): proposal,
   alternatives, cost, risks and rollout, cross-cutting concerns, open questions. Write the TL;DR
   **last** and place it first.
9. **Self-review** against the gate below and the full list in
   [references/review-checklist.md](references/review-checklist.md). Then run a fresh-reader test:
   give a subagent with no context only the header and TL;DR and ask it to state the decision, the
   evidence and the ask. If it can't, rewrite the TL;DR (borrowed from Anthropic's doc-coauthoring
   skill).
10. **Circulate.** Named reviewers, each with a specific question ("Priya: is the compaction
    schedule safe for the finance jobs?"), and a comment deadline. Ask for "yes, if…" rather than
    yes or no (Squarespace). Fold answers into the doc, record decisions in the Decision log,
    spin off ADRs for decisions that will outlive the doc, and keep the doc updated as
    implementation diverges (Google's design-doc lifecycle).

When handing a draft back to the user, say in one line where it is, whether it passes the gate, and
what is missing. They read the doc; the chat message is a status.

## Required skeleton, in order

1. **Title and metadata header** — author, reviewers (with what each reviews), approver/decider,
   status, created, last updated, comment deadline, links (ticket or epic, POC code, dashboards,
   parent or child ADRs). Status values: Draft, Draft: reviewing problem, Validating, In review,
   Approved, Implemented, Superseded by …, Abandoned.
2. **TL;DR** — rules below.
3. **Context and problem** — current state with numbers, who feels the pain, why now, and what
   happens if we do nothing for six months. Facts, not opinion.
4. **Goals and non-goals** — measurable goals; explicit non-goals.
5. **Proposal** — overview paragraph and a diagram first, then data model, interfaces (sketched,
   not pasted), key flows including failure and recovery. No code except novel algorithms or
   data shapes.
6. **Key decisions** — table: decision, choice, why, reversibility (one-way or two-way door),
   validated by (link into the Validation section).
7. **Validation** — the POC plan and the results; rules below.
8. **Alternatives considered** — rules below.
9. **Cost and effort** — run-rate cost delta as increase, decrease and net ,
   people-weeks by phase, and what we stop doing.
10. **Risks, rollout and rollback** — phases with exit criteria, the first irreversible step, the
    kill switch, guardrail metrics, migration and backfill plan.
11. **Cross-cutting concerns** — security, privacy and compliance (PII, deletion requests),
    data quality and contracts, schema evolution, observability, SLAs and freshness, on-call and
    operational load, cost attribution.
12. **Open questions** — each with an owner and a date. Nothing on the critical path is "TBD".
13. **Decision log** — dated entries of what changed after review and why.
14. **Links and appendix** — raw results, notebooks, prior docs. Links live here, not in prose.

Sections 1–8 are mandatory in every doc, including mini docs. Sections 9–14 may be one line each
when they genuinely don't apply; say why instead of writing "N/A".

## Validation rules

- **Pick by risk, not by convenience.** Validate the decisions that are uncertain, expensive to
  get wrong and hard to reverse. Don't benchmark what nobody doubts.
- **Smallest test that could prove the decision wrong.** A two-day spike that reproduces the one
  condition the decision is sensitive to beats a two-week end-to-end build.
- **Criteria before results.** For each test write: the hypothesis, the metric and how it is
  measured, the pass threshold, the baseline it is compared with, and the result that would change
  the decision ("if MoR read p95 exceeds 2× CoW, we choose CoW and accept the write cost"). If a
  threshold changes after results come in, keep the original, record the change and the reason.
- **Production-like on the axis that matters.** Real data shape, volume within 10× of production,
  real skew, real update or churn rate, real concurrency, cold caches where users hit cold caches.
  Name what the test did *not* reproduce. Example: a benchmark that assumes a table fully cleaned
  between snapshots misses the partition scans that daily churn causes. Simulate the churn, not a
  fresh table.
- **Measure against a baseline** run the same way: same data, same compute size, same harness.
- **Report numbers that survive scrutiny:** p50/p95/p99 over repeated runs, cost from billing
  tables rather than list-price guesses, and the variance.
- **Record results in the doc**: a table of test, threshold, result, pass/fail, link; then what
  surprised us and what the test does not prove. Link to the code, notebook and raw results.
- **Status gate.** The doc moves to *In review* only when every key decision shows a result. It
  may circulate earlier as *Draft* or *Validating* for feedback on the problem and options, never
  for approval.

### When a full POC is impractical

Never write "no validation". Pick the strongest option that fits, and say in the doc why the
stronger ones were not possible:

1. **Narrower spike** — test only the riskiest mechanism (one table, one query shape, one hour of
   traffic).
2. **Back-of-envelope plus micro-benchmark** — build the model, then measure the one or two unit
   costs that dominate it (credits per TB scanned, MB/s per core, cost per million upserts) instead
   of trusting docs or list prices.
3. **Replay** — run a sample of real production queries or events through the candidate offline.
4. **Shadow or dark launch** — run the new path alongside the old on real traffic, compare outputs
   and metrics, serve nothing from it.
5. **Vendor trial** — on our data, our queries, run by our engineers, with exit criteria agreed
   before it starts; vendor-run demos on their data don't count.
6. **Staged rollout as the validation** — only when nothing earlier is possible: name the
   criteria, the guardrail metrics, the canary size, and the check that must pass *before* the
   first irreversible step.

Reference calls with other companies and published benchmarks are supporting evidence, never the
validation on their own.

## TL;DR rules

- **Fixed fields, in this order:** Problem (with a number) · Proposal (one or two sentences) · Key
  decision(s) · Validated (what was tested and the headline result against its threshold) · Cost and
  effort · Ask (approve, comment, or pick an option, with a date and from whom).
- **150–250 words, or 6–8 bullets.** It is a decision summary, not an introduction. GitLab's
  template notes the summary is "very often the only section that will be read".
- **The answer first.** Lead with the recommendation, not the background.
- **Numbers, not adjectives.** "p95 from 14 s to 2.1 s, $9k/month cheaper" rather than "faster and
  cheaper".
- **Plain English.** No acronym or internal name without a short gloss; a director outside the team
  must follow it.
- **Stands alone.** No "see below", no cross-references.
- **Honest.** If a key result is marginal or failed and the proposal changed because of it, say so.

## Alternatives considered

- **Always include do nothing**, projected forward with numbers (cost growth, incident trend,
  date we hit a limit).
- **At least two real alternatives.** Usually: the minimum change to today's system, the proposal,
  and a bigger redesign or a buy option. A doc with one option is asking for permission, not doing
  design. "If you omit this section because you didn't consider any alternatives, that's a signal
  you may not have thought the problem through" (Reilly).
- **Steelman each one:** say why it was attractive and who would favour it.
- **Same criteria for all,** in a comparison table (cost, effort, latency or freshness, operational
  load, reversibility, team skills, lock-in), then a short paragraph per option giving the deciding
  reason.
- **State the flip condition:** what evidence would make us choose this option instead. Tie it to
  a validation result where one exists.
- **Record abandoned ideas** so reviewers don't relitigate them (HashiCorp).

## Writing rules for the doc

- Plain English, the answer first in every section and paragraph, numbers kept.
- Every acronym or internal name gets a one-line gloss on first use, or goes.
- **Better wrong than vague** (Reilly): make concrete claims and decisions so reviewers can argue
  with them. "We will partition by `event_date` and bucket by `account_id` into 64 buckets" beats
  "we will choose an appropriate partitioning strategy".
- Never use the § symbol. Never write inline "see other-doc.md" references; paraphrase the needed
  fact inline. All links go in the Links section at the end.
- Active voice, "we will…". Short paragraphs, one idea each. Tables for comparisons, prose for
  reasoning. A diagram near the top of the Proposal.
- No filler ("it's worth noting"), no stacked hedges, no rhetorical questions (lemieux/rfc-skills).
- Mark unverified claims inline as **VERIFY**, inferences as **INFERENCE**, and unresolved choices as
  **DECISION NEEDED**, and list each in Open questions with an owner (melbaldove/dotfiles RFC skill).
  None may remain on a key decision when the doc goes to review.

## Self-review gate (run before handing back any draft)

The doc is **not ready for review** if any answer is no. Full checklist in
[references/review-checklist.md](references/review-checklist.md).

1. Header complete: author, named reviewers, decider, status, dates, comment deadline, links.
2. TL;DR has all six fields, leads with the recommendation, carries real numbers, and states an ask
   with a date. A fresh reader can restate decision, evidence and ask from it alone.
3. Problem has a current-state number and a do-nothing projection.
4. Goals are measurable; non-goals exist.
5. Every key decision appears in the Key decisions table and links to a validation result.
6. Every validation shows criteria written before the run, the result, pass/fail, what it didn't
   test, and a link to code or notebook.
7. Alternatives include do nothing plus two real options, the same criteria for each, and flip
   conditions.
8. Cost shows increase, decrease and net; effort is given in people-weeks by phase.
9. Rollout names the first irreversible step and the rollback path.
10. No § symbols, no inline cross-doc references, no unglossed jargon, no TBD on the critical path.

## Reviewing someone else's doc

1. **Read the header and TL;DR only, then write down what you think is being decided and asked.**
   If you can't, that is the first comment.
2. **Ask Reilly's questions:** should this work exist; does it solve the stated problem; will it
   handle failure; is it understandable; does it fit the bigger picture; do the right people know?
3. **Check the evidence.** For each key decision: was it validated, were criteria set before the
   run, did the test reproduce the condition the decision is sensitive to, do the numbers support
   the claim? An unvalidated key decision is a blocking comment.
4. **Check the alternatives** for strawmen and a missing do-nothing.
5. **Spend effort in proportion to irreversibility.** One-way doors get scrutiny; two-way doors get
   a light touch.
6. **Write comments that can be acted on.** Label each **Blocking**, **Should fix** or **Nit**.
   One issue per comment, quote the text, and propose a fix or the evidence that would resolve it.
   Frame blockers as "yes, if…" (Squarespace).
7. **Report to the user in one line first:** Approve / Yes, if… / Not yet, and the one reason. Then the
   blocking list, then the rest. Don't rewrite the author's doc unless asked.

## Anti-patterns

- **Implementation manual** — pages of how with no trade-offs or alternatives (Ubl).
- **Decision already made** — doc written to justify a choice, with strawman alternatives.
- **Validation theatre** — benchmark on toy data, a fresh table, warm caches, the vendor's demo
  dataset, or only the happy path; thresholds chosen after seeing the numbers.
- **Vague to avoid argument** — "we'll choose a suitable engine" (Reilly: better wrong than vague).
- **TL;DR as introduction** — background instead of the decision; no ask; no date.
- **Adjectives instead of numbers** — "scalable", "fast", "cost-effective".
- **Buried ask** — reviewers don't know what they're approving or by when.
- **Template padding** — every optional section filled with "N/A"; overloaded templates discourage
  writing at all (Larson). Short and complete beats long and hollow.
- **Writing by committee** — gather input widely, write alone (Larson).
- **Doc rot** — not updated when implementation diverges, so the record lies (Ubl).
- **Reference chasing** — §, "see X.md", undefined internal names.

## Sources

- Malte Ubl, "Design Docs at Google" (2020): sections, non-goals, trade-offs, mini docs, lifecycle.
- Will Larson (staffeng.com, lethain.com): start from the problem, light templates, write alone,
  good over perfect, *Write five then synthesize*.
- Tanya Reilly, *The Staff Engineer's Path* (2022): RFC template, review questions, "better wrong
  than vague", "make a guess and document it with an ADR" (via secondary write-ups).
- Squarespace, "The Power of 'Yes, if'" (2019). Gergely Orosz, The Pragmatic Engineer, on Uber's RFCs.
- HashiCorp, Rust and React RFC templates; Python PEP 1 ("a prototype implementation be
  co-developed with the PEP"). Oxide RFD 1. Sourcegraph RFC handbook. GitLab design-doc template.
- Michael Nygard, "Documenting Architecture Decisions" (2011); MADR ("Confirmation").
- Amazon narrative memos and PR/FAQ (Bryar and Carr, *Working Backwards*). Rogers and Lasky-Fink,
  *Writing for Busy Readers*. mmapped.blog, "Effective design docs".
- Agent skills borrowed from: lemieux/rfc-skills (AI-tell patterns, PoC-before-RFC);
  melbaldove/dotfiles RFC skill (rejection criteria, VERIFY / INFERENCE / DECISION NEEDED);
  anthropics/skills doc-coauthoring (fresh-reader test).
