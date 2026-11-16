# Examples

One realistic data-platform decision, shown done well and done badly. The company, names and
numbers are illustrative; the shape is what to copy.

**Scenario.** Orders data reaches the lakehouse through a nightly Spark job that exports a full
snapshot of the 1.2B-row orders database. Finance dashboards are up to 26 hours stale, the job costs
$14k/month, and it failed 6 times last quarter. The proposal: stream database changes (CDC, change
data capture) through Kafka Connect into an Apache Iceberg table using merge-on-read writes, with
hourly compaction.

## Good: header and TL;DR

| | |
|---|---|
| **Author** | Alex Morgan |
| **Reviewers** | Priya (data eng: compaction schedule) · Marcus (SRE: Kafka Connect on-call) · Lena (finance analytics: cut-over timing) |
| **Approver** | Dana, Director of Data Platform |
| **Status** | In review |
| **Created / updated** | 2026-09-18 / 2026-10-01 |
| **Comments due** | 2026-10-09 |
| **Links** | Epic DP-412 · POC repo @ 7f3c2e1 · Freshness dashboard |

**TL;DR**

- **Problem:** Finance dashboards read orders data up to 26 hours old. The nightly snapshot job that
  feeds them costs $14k/month and failed 6 times last quarter, each time leaving dashboards two days
  stale.
- **Proposal:** Replace the nightly snapshot with streaming CDC: Debezium on Kafka Connect writes
  every database change into an Iceberg table within minutes, and an hourly job compacts it.
- **Key decisions:** (1) streaming CDC over a faster batch job; (2) merge-on-read writes over
  copy-on-write, trading slightly slower reads for much cheaper writes.
- **Validated:** A 3-day replay of production changes (410M rows) at twice peak load gave
  freshness of 6 minutes p95 (target under 15) and recovered from a 1-hour outage in 22 minutes
  (target under 30). Reads were 1.4× slower than copy-on-write (limit 2×). A 7-day shadow run
  matched production on 100% of keys.
- **Cost and effort:** +$3.1k, −$9.4k, **net −$6.3k/month**. Two engineers for six weeks.
- **Ask:** Dana to approve by 14 Oct. Lena to confirm by 9 Oct that the 3 Nov cut-over avoids month-end close.

*Why it works:* recommendation in the first two bullets; every claim has a number; each result
sits next to its threshold; the ask names people and dates; a director can approve without
reading further. CDC is glossed in the scenario sentence, and merge-on-read is explained by its
trade-off rather than by its definition.

## Bad: header and TL;DR

> **Status:** Draft
>
> **TL;DR:** This document proposes modernising our ingestion architecture by leveraging CDC and a
> lakehouse table format to deliver near-real-time, scalable and cost-effective data to downstream
> consumers. We evaluated several options and believe the streaming approach is the best fit. A POC
> showed promising results (see the Validation section for details). Feedback welcome!

*What's wrong:*

- No problem stated, and no number for it. "Modernising" is a solution looking for a problem.
- Adjectives instead of numbers: "near-real-time", "scalable", "cost-effective", "promising".
- Jargon without a gloss: CDC, lakehouse table format.
- Key decisions not named, so reviewers can't tell what they are approving.
- Validation result missing from the TL;DR, and the cross-reference forces the reader to dig.
- No cost or effort.
- No ask, no approver, no date: "Feedback welcome" will get none.
- Header missing reviewers, decider and deadline.

## Good: Validation results excerpt

| ID | Decision | Result (n=5 unless noted) | Threshold (set 2026-09-21) | Pass? | Evidence |
|---|---|---|---|---|---|
| V1 | Streaming CDC | Freshness p95 6 min, p99 11 min at 2× peak | ≤ 15 / ≤ 30 min | Pass | notebook `freshness.ipynb` @ 7f3c2e1 |
| V1b | Streaming CDC | Catch-up after 1-hour pause: 22 min | ≤ 30 min | Pass | same |
| V2 | Merge-on-read | Read p95, 60 min after compaction: 1.4× copy-on-write (range 1.3–1.6×) | ≤ 2× | Pass | `read_bench.py` @ 7f3c2e1 |
| V3 | Cost | Measured compaction 0.31 core-hours per GB changed → $2.2k/month at forecast volume | Net cost ≤ today's $14k | Pass | cost model sheet |
| V4 | Correctness | 7-day shadow: 100% key parity; 0.004% value mismatches, all from one timezone bug (fixed) | 100% keys; ≤ 0.01% values, all explained | Pass | parity report |

**Set-up:** production change log for 15–17 Sep replayed at 2× the measured peak (3,100 changes per
second); Iceberg format v2; Spark 3.5 on EMR 7.x for compaction; cold reads from Athena and
Snowflake; harness at commit 7f3c2e1.

**What surprised us:** Snowflake reads were 1.8× slower than copy-on-write, against 1.4× for
Athena. Still under the limit, but it is why compaction runs hourly rather than every four hours.

**What this does not prove:** Black Friday volume (about 4× normal) was not replayed. A load test at
4× is the exit criterion for phase 2, before the nightly job is retired.

## Bad: Validation excerpt (validation theatre)

> We built a POC with Kafka Connect and Iceberg on a sample of 1M orders. Queries ran in under a
> second and the pipeline kept up easily. Merge-on-read performed well. We're confident this will
> scale to production.

*What's wrong:* 1M rows against 1.2B in production; no churn, so merge-on-read had no delete files to
read; no thresholds set beforehand; no baseline; no repetitions; no peak load; no outage test; no
correctness check; no link to code; "confident this will scale" stands in for evidence.

## Good: Alternatives excerpt

| Criterion | Do nothing | Faster batch (hourly incremental Spark) | **Streaming CDC (proposal)** | Managed connector (vendor) |
|---|---|---|---|---|
| Freshness p95 | 26 h | ~75 min (estimated from job runtime) | 6 min (measured) | ~10 min (vendor trial) |
| Net cost / month | $14k, rising 9%/month | ~$8k | $7.7k | $12.5k at quoted rate |
| Effort | 0 | 3 eng-weeks | 12 eng-weeks | 4 eng-weeks |
| Operational load | 6 failures/quarter | Same job, more runs | New Kafka Connect on-call | Vendor-run; we own the table |
| Reversibility | n/a | Easy | Moderate: Kafka skills and on-call | Contract: 12 months |

**Faster batch** was attractive because it reuses the job everyone knows and costs a quarter of the
effort. It loses because 75 minutes misses finance's 15-minute goal. *We would choose it if* finance
relaxed the freshness goal to two hours.

**Managed connector** was attractive for low effort and no new on-call. It loses on cost: $4.8k a
month more than the proposal at the quoted rate. *We would choose it if* the quote fell below $8k a
month or we could not staff Kafka on-call.

**Abandoned:** Dual-writing from the application (rejected: the orders team owns that code and
won't take on the risk); full nightly snapshot on bigger hardware (rejected: fixes failures, not
freshness).

## Bad: Alternatives excerpt

> **Alternatives considered:** We looked at batch, but it's old-fashioned and doesn't scale. Vendors
> are expensive. Streaming is the industry standard.

*What's wrong:* no do-nothing; strawmen ("old-fashioned"); no shared criteria; no numbers; no reason
anyone would have chosen the alternatives; no condition under which the decision would flip.

## Not ready: what Claude tells the user

When a draft fails the gate, the hand-back is one line:

> Draft is at `docs/design/<doc-name>.md`; not ready for review: the merge-on-read read penalty
> (key decision 2) has a plan but no result yet, so status is Validating.
