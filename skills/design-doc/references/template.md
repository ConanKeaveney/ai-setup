# Design doc template

Copy everything below the line. Replace every `<…>`. Delete the guidance in *italics* once a
section is written. Sections 1–8 are mandatory, including in a 1–3 page mini doc; later sections
may be a single line when they don't apply, saying why. Write the TL;DR last.

House rules for the finished doc: plain English, the answer first, numbers kept, no § symbol, no
inline "see other-doc" references (paraphrase instead; links go in the Links section), every
acronym glossed on first use.

---

# <Decision as a short noun phrase, e.g. "CDC ingestion for the orders database via Kafka Connect into Iceberg">

| | |
|---|---|
| **Author** | <name> |
| **Reviewers** | <name — what they are asked to check>; <name — …> |
| **Approver / decider** | <one name> |
| **Status** | <Draft · Draft: reviewing problem · Validating · In review · Approved · Implemented · Superseded by … · Abandoned> |
| **Created / last updated** | <YYYY-MM-DD> / <YYYY-MM-DD> |
| **Comments due** | <YYYY-MM-DD> |
| **Links** | <epic or ticket> · <POC repo or notebook> · <dashboard> · <parent doc / child ADRs> |

## TL;DR

*150–250 words. Written last, read first. A director stops here, so everything needed to say yes
or no is in this block. Lead with the recommendation. Numbers, not adjectives. No "see below".*

- **Problem:** <one sentence with the current number, e.g. "Finance dashboards read data that is 26 hours old, and the nightly job costs $14k/month and failed 6 times last quarter.">
- **Proposal:** <one or two sentences: what we will build or change.>
- **Key decision(s):** <the 1–3 choices that matter, each with the chosen option, e.g. "Iceberg merge-on-read over copy-on-write; Kafka Connect over a custom Spark job".>
- **Validated:** <what was tested and the headline result against its threshold, e.g. "A 3-day replay of production CDC (410M changes) held end-to-end lag at p95 6 min (target < 15) and read p95 at 1.4× copy-on-write (limit 2×).">
- **Cost and effort:** <run-rate change as net $/month with increase and decrease, plus people-weeks, e.g. "+$3.1k, −$9.4k, net −$6.3k/month; 2 engineers × 6 weeks".>
- **Ask:** <who must do what by when, e.g. "Approve by 14 Oct (Dana); data-eng leads comment on the compaction schedule by 9 Oct.">

## Context and problem

*Facts, not opinion. Today's state with numbers: volume, latency or freshness, cost per month,
failure rate, on-call load. Who feels the pain and how. Why now (a deadline, a growth curve, an
incident, a contract). End with the do-nothing projection.*

<…>

**If we do nothing:** <projection with numbers and a date, e.g. "At 9% monthly growth the nightly job passes its 6-hour window in March 2027; cost reaches $21k/month.">

## Goals and non-goals

**Goals** *(measurable; each one should be testable after launch)*

1. <e.g. Data available to dashboards within 15 minutes of the source commit, p95.>
2. <e.g. Run-rate cost no higher than today's $14k/month.>
3. <…>

**Non-goals** *(things a reader could reasonably expect that we are deliberately not doing)*

- <e.g. Real-time (sub-minute) freshness.>
- <e.g. Migrating the other 40 source databases; this doc covers orders only.>

## Proposal

*Start with one paragraph a newcomer understands, then a diagram, then detail. Sketch interfaces
and data shapes; don't paste full code or config. Cover the failure path for each key flow.*

<Overview paragraph.>

```
<ASCII or Mermaid diagram: sources → components → stores → consumers>
```
*Caption: <what the reader should notice in this diagram>.*

### Data model

<Tables, keys, partitioning or clustering, retention. Show the schema shape in full where it matters.>

### Interfaces and contracts

<Who writes, who reads, the contract (schema, freshness SLA, ownership), how schema changes are handled.>

### Key flows

| Flow | Normal path | Failure and recovery |
|---|---|---|
| <e.g. CDC change arrives> | <…> | <e.g. connector restarts from last committed offset; duplicates removed by MERGE on primary key> |
| <e.g. Backfill> | <…> | <…> |

## Key decisions

*The 2–4 choices that carry the doc. Each must link to a validation result below.*

| # | Decision | Choice | Why (one line) | Reversible? | Validated by |
|---|---|---|---|---|---|
| D1 | <e.g. Table write mode> | <merge-on-read> | <write cost 6× lower at our update rate> | <Two-way door: switchable per table> | <V1> |
| D2 | <e.g. Ingestion tool> | <Kafka Connect + Debezium> | <…> | <One-way door for 12 months: ops investment> | <V2> |

## Validation

*Every key decision has an entry. Criteria were written before the test ran. A doc with a key
decision lacking a result is not ready for review.*

### Plan (written <YYYY-MM-DD>, before any test ran)

| ID | Decision | Riskiest assumption | Test (smallest that could prove us wrong) | Metric and method | Pass threshold | Result that changes the decision | Timebox / owner |
|---|---|---|---|---|---|---|---|
| V1 | D1 | <Reads on merge-on-read stay fast enough between compactions> | <Replay 3 days of production CDC into a copy of the table; run the 20 most expensive dashboard queries hourly> | <Read p95 over 5 runs, cold cache, same compute> | <≤ 2× copy-on-write p95> | <> 2× → choose copy-on-write and accept write cost> | <3 days / name> |
| V2 | D2 | <…> | <…> | <…> | <…> | <…> | <…> |

*If a full POC is impractical for a decision, say which substitute was used (narrower spike,
back-of-envelope plus micro-benchmark, replay, shadow launch, vendor trial, staged rollout with a
pre-irreversible check) and why the stronger options were not possible. Never "no validation".*

### Results

| ID | Result | Threshold | Pass? | Evidence |
|---|---|---|---|---|
| V1 | <p95 1.4× copy-on-write (n=5, range 1.3–1.6×)> | <≤ 2×> | <Pass> | <link to notebook @ commit abc123> |
| V2 | <…> | <…> | <…> | <…> |

**Set-up:** <data size and how sampled, engine and version, compute size, cache state, dates run, commit hash>.

**What surprised us:** <anything unexpected, and whether it changed the design>.

**What this does not prove:** <conditions not reproduced, e.g. "Peak Black Friday volume (4× normal) not tested; covered by the load test in phase 2 before cut-over.">

**Threshold changes:** <none, or the original threshold, the new one, and why>.

## Alternatives considered

*Do nothing plus at least two real options. Same criteria for each. Steelman each: why it was
attractive. Give the flip condition: what evidence would make us choose it instead.*

| Criterion | Do nothing | <Option A: minimum change> | **<Proposal>** | <Option C: bigger change or buy> |
|---|---|---|---|---|
| Cost (net $/month) | <…> | <…> | <…> | <…> |
| Effort (people-weeks) | 0 | <…> | <…> | <…> |
| Freshness / latency | <…> | <…> | <…> | <…> |
| Operational load | <…> | <…> | <…> | <…> |
| Reversibility | <…> | <…> | <…> | <…> |
| Lock-in / team skills | <…> | <…> | <…> | <…> |

**Do nothing.** <What happens, with the projection.>

**<Option A>.** <Why it was attractive. Why we didn't choose it, with evidence. Flip condition: "We would choose this if …".>

**<Option C>.** <Same.>

**Abandoned ideas.** <Ideas ruled out early, one line each with the reason, so reviewers don't reopen them.>

## Cost and effort

| Item | Increase ($/month) | Decrease ($/month) | Notes and assumptions |
|---|---|---|---|
| <Compute for ingestion> | <…> | | <…> |
| <Compaction / maintenance> | <…> | | <…> |
| <Storage> | <…> | | <…> |
| <Retired nightly job> | | <…> | <…> |
| **Total** | **<…>** | **<…>** | **Net: <…>** |

*Unit costs come from billing data or a measured micro-benchmark, not list prices. Give a range
when an input is uncertain, and name the input that drives most of the total.*

**Effort:** <phase — people × weeks>, <…>. **What we stop doing:** <…>.

## Risks, rollout and rollback

**Phases**

| Phase | What ships | Exit criteria | Rollback |
|---|---|---|---|
| 1 | <e.g. Shadow pipeline writes to a parallel table> | <row-count and checksum parity ≥ 99.99% for 7 days> | <drop parallel table> |
| 2 | <e.g. Dashboards switch to new table behind a flag> | <…> | <flip flag back> |
| 3 | <e.g. Retire nightly job> | <…> | <**first irreversible step**; re-enable job from saved config within 1 day> |

**First irreversible step:** <what it is and the check that must pass before it>.

**Risks**

| Risk | Likelihood / impact | Mitigation or reason to accept |
|---|---|---|
| <…> | <…> | <…> |

## Cross-cutting concerns

- **Security, privacy, compliance:** <PII columns, access control, deletion-request handling, retention.>
  *For a new trust boundary or data flow, summarise the threat model (method and template:
  [threat-model.md](threat-model.md)).*
- **Data quality and contracts:** <checks, owners, what happens on a contract break.>
- **Schema evolution:** <how upstream changes propagate; what breaks.>
- **Observability:** <freshness, volume and error metrics; alerts; dashboards.>
  - *Write each query before naming the metric. If it isn't about one line, the metric isn't useful.*
  - *One counter tagged by outcome, emitted on every exit path, with the same dimensions on success
    and error. A drop in success volume is a signal error counters miss.*
  - *No tenant, user or request ids or exception text as metric labels; put them in a structured event.*
  - *Batch or sparse jobs alert on time since last success.*
  - *New alerts ship at the lowest priority for a week before promotion.*
- **SLAs and on-call:** <freshness SLA, who is paged, runbook owner, expected added toil.>
- **Cost attribution:** <tags, warehouses or budgets that make this cost visible.>

## Open questions

| Question | Owner | Needed by | Blocks |
|---|---|---|---|
| <…> | <…> | <YYYY-MM-DD> | <decision or phase it blocks, or "nothing"> |

*Inline markers used in the draft (VERIFY, INFERENCE, DECISION NEEDED) each appear here once.
None may remain on a key decision at review.*

## Decision log

| Date | Change | Why | Who |
|---|---|---|---|
| <YYYY-MM-DD> | <e.g. Compaction moved from hourly to every 15 min> | <reviewer found finance queries at :50 past the hour> | <…> |

## Links and appendix

- <Epic / ticket>
- <POC code and notebooks, with commit hashes>
- <Raw benchmark results>
- <Related design docs and ADRs>
- <Dashboards>
