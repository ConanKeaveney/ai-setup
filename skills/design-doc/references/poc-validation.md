# POCs and validation for data-platform decisions

The purpose of a POC in a design doc is to find out, cheaply and before commitment, whether the
decision the doc rests on is wrong. It is not a demo and not the first sprint of the build. The
code is throwaway; the numbers and the method are what the doc keeps.

## 1. Find the decisions worth testing

List every decision in the proposal, then score each one from 1 (low) to 3 (high):

| Decision | Uncertainty (how sure are we?) | Cost of being wrong ($, time, trust) | Irreversibility (one-way door = 3) | Score (product) |
|---|---|---|---|---|
| <e.g. merge-on-read over copy-on-write> | 3 | 2 | 1 | 6 |
| <e.g. Kafka Connect over custom Spark CDC> | 2 | 3 | 3 | 18 |

Validate everything scoring 12 or more, and any one-way door with uncertainty of 2 or more. Two to
four decisions usually qualify. If none do, either the doc doesn't need writing or the risk hasn't
been looked for: ask "what would we be embarrassed to discover three months in?"

Typical riskiest assumptions on a data platform:

- The candidate is cheaper *on our workload*, not on a benchmark suite.
- Performance holds *after weeks of churn* (updates, deletes, small files), not on a fresh table.
- Freshness holds *at peak*, and the pipeline *catches up* after an outage.
- Every engine that must read or write the table can do so, including the maintenance jobs.
- Migration produces identical results (row counts, keys, values).
- The team can operate it: on-call load, upgrades, failure modes.

## 2. The experiment card (write before running)

One card per decision, copied into the doc's Validation plan table:

- **Decision and assumption under test:** <D1: reads on merge-on-read stay fast between compactions>
- **Hypothesis:** <read p95 on the top 20 dashboard queries stays within 2× copy-on-write>
- **Method:** <what is run, on which data, compute, versions, how many repetitions>
- **Baseline:** <today's system, or the alternative, measured with the same harness>
- **Metric and how it is measured:** <p95 wall time from the query history, cold cache, n=5>
- **Pass threshold:** <≤ 2×>
- **Result that changes the decision:** <> 2× → choose copy-on-write; > 3× → also revisit the compaction design>
- **What this test will not reproduce:** <peak season volume>
- **Timebox and owner:** <3 days, name>

Rules:

- Thresholds come from the doc's goals or from a cost the business cares about, not from what
  seems achievable.
- The decision rule must name an action. "We'll investigate further" is not a decision rule.
- If a threshold changes after the run, keep the original in the doc, record the new one and the
  reason in the Validation section's threshold-changes line.
- Stop at the timebox. A partial result with a clear caveat beats an unbounded POC.

## 3. Benchmark hygiene

- **Our data, at realistic scale.** Within 10× of production volume, real key distribution and
  skew. Synthetic data only when real data can't be used, and then match the distributions you
  measured.
- **Simulate time.** Run the update, delete and compaction pattern for a realistic number of days
  before measuring reads. A fresh table flatters every layout.
- **Same conditions for every option:** same data snapshot, same compute size (or the same
  dollars per hour when comparing engines), same harness, same concurrency.
- **Control caches.** Snowflake: `ALTER SESSION SET USE_CACHED_RESULT = FALSE`, and suspend and
  resume the warehouse to drop its local disk cache when testing cold reads. Databricks: disable the
  disk cache (`spark.databricks.io.cache.enabled = false`) for cold runs. Decide which state users
  actually hit and test that one, or both.
- **Repeat.** At least five runs per configuration; report median, p95 and the range. Discard the
  first warm-up run only if the doc says so.
- **Cost from billing, not list price.** Snowflake: `ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY` and
  `QUERY_ATTRIBUTION_HISTORY`. Databricks: `system.billing.usage`. AWS: Cost Explorer with tags.
  Use contract rates.
- **Record the set-up:** engine and version, table format version, compute size, data size and how
  sampled, dates, commit hash of the harness. Without this nobody can rerun it.
- **Measure what users feel.** End-to-end freshness and dashboard latency, not just job runtime.

## 4. Worked examples

### A. Engine or vendor choice

*Decision:* move the BI workload from Snowflake to Databricks SQL serverless (or keep it).

*Riskiest assumptions:* price-performance on our query mix; concurrency at the 9am peak; SQL
translation effort; gaps in features we rely on (row access policies, UDFs, data sharing).

*Smallest decisive test:* take the 50 queries that consumed the most credits over the last 30
days (from `QUERY_ATTRIBUTION_HISTORY`; check they cover a majority of BI spend), translate them,
and replay them against the same data on both engines (an Iceberg copy both can read keeps the data
identical) at the measured peak concurrency.

*Criteria written up front:*

| Metric | Threshold | Decision rule |
|---|---|---|
| Daily cost of the replayed workload, from each billing source | ≥ 25% cheaper | < 15% cheaper → stay; 15–25% → only if migration pays back within 12 months |
| p95 latency at peak concurrency | No worse than +10% | Worse → stay, regardless of cost |
| Queries needing manual rewrite | ≤ 10% | More → re-estimate migration effort before deciding |

*Vendor trial rules:* our data, our queries, our engineers at the keyboard, exit criteria agreed
with the vendor before it starts, pricing at the rate we would actually sign. Vendor-run demos and
published benchmarks (TPC-DS and similar) are context, not validation.

### B. Table format or write mode

*Decision:* Iceberg merge-on-read (MoR) instead of copy-on-write (CoW) for a CDC table receiving
upserts every 5 minutes.

*Riskiest assumptions:* MoR reads stay acceptable between compactions; compaction keeps up and its
cost is acceptable; every reader engine handles delete files; concurrent writers don't hit commit
conflicts.

*Smallest decisive test:* replay 3 days of production CDC (real change rate and key distribution)
into two copies of the table, one per mode, with compaction running on the proposed schedule. Run
the 20 most expensive read queries every hour, and at 0, 30 and 60 minutes after a compaction.
Have every engine that must read the table (for example Snowflake and Athena) run one query.
Run the maintenance job concurrently with the writer to provoke conflicts.

*Criteria:*

| Metric | Threshold |
|---|---|
| Write commit p95 | MoR ≤ 1/3 of CoW |
| Read p95, 60 min after compaction | MoR ≤ 2× CoW |
| Compaction cost per day | ≤ 30% of the write savings |
| Commit conflicts over 3 days | 0 unrecovered failures |
| Every reader engine returns identical row counts | Yes |

*Change the decision if:* read penalty > 2× → CoW, or MoR with more frequent compaction if that
still beats CoW on total cost. Any reader engine can't read the table → CoW or a different format
version.

### C. Storage layout (partitioning, clustering, wide vs long)

*Decision:* replace a long name/value (EAV) property table with a wide one-row-per-object table
for reporting queries.

*Riskiest assumption:* the read win survives production churn. A typical failure: the benchmark
compared several layouts across small, medium and large tenants, but assumed the table was fully
compacted at each snapshot. Under production update churn the wide table scanned far more
partitions than the long one, and a hybrid (hot properties wide, the rest long) was needed.

*Smallest decisive test:* build each layout from the same 10–20 tenants spanning small to large,
apply 14 simulated days of updates at the real per-object update rate, run maintenance
(reclustering, cleanup, compaction) on its *real* schedule and budget, then run the top reporting
queries.

*Criteria:* bytes and partitions scanned for the top 20 queries down ≥ 40% versus the long layout
after 14 days of churn; p95 latency down ≥ 30%; maintenance cost included in the net. Record
pruning ratio (partitions scanned ÷ total) per query.

*Change the decision if:* the win disappears after churn → hybrid layout or a different
maintenance schedule, with its cost in the doc.

### D. Latency and freshness (streaming versus micro-batch)

*Decision:* streaming CDC with 1-minute commits versus 15-minute micro-batches.

*Riskiest assumptions:* freshness at peak; catch-up after an outage; no lost or duplicated changes.

*Smallest decisive test:* insert heartbeat rows at the source every 10 seconds carrying their
commit time; measure freshness as (time the row is visible to a reader query) minus (source commit
time). Run at 2× the measured peak rate for an hour. Kill a worker mid-run, then pause the pipeline
for one hour and restart it. Reconcile primary keys and counts between source and target at the end.

*Criteria:*

| Metric | Threshold |
|---|---|
| Freshness p95 / p99 at 2× peak | ≤ 15 min / ≤ 30 min |
| Catch-up after a 1-hour pause | ≤ 30 min |
| Lost changes (source keys missing from target) | 0 |
| Duplicates after dedupe | 0 |
| Small files produced per hour (feeds the compaction cost) | recorded, and costed in the doc |

*Change the decision if:* micro-batch meets the freshness goal at lower cost → micro-batch. The goal
is the user's freshness target, not the lowest possible latency.

### E. Cost: back-of-envelope plus micro-benchmark

When a full cost trial is impractical, build a model and measure the term that dominates it.

*Decision:* run an hourly MERGE of CDC changes into a 4B-row Snowflake table on a Medium warehouse
(4 credits per hour).

*Model:* monthly credits = runs per month × hours per run × credits per hour.
The unknown that dominates is hours per run; nobody's docs know it for our table.

*Micro-benchmark:* merge one real hour of changes (2.1M rows) into a clone of the table, five times.
Median 7.5 minutes. Repeat on a 2B-row clone: 4.1 minutes. Runtime roughly doubles with table size,
so pruning is not helping (**INFERENCE** from two points; a third size would confirm).

*Arithmetic:*

- Today: 720 runs × 0.125 h × 4 credits = 360 credits ≈ **$1,080/month** at $3 per credit (contract
  rate, **VERIFY** with finance).
- In 12 months, at the forecast 8B rows: ~15 minutes per run → 720 credits ≈ **$2,160/month**.

*Decision rule written up front:* if the 12-month projection exceeds $2,500/month, switch to
append-only plus a daily dedupe. At $2,160 it passes, with a re-check when the table reaches 6B rows.

*Sensitivity:* name the input that moves the answer most (here, runtime growth with table size) and
show the cost at its plausible low and high values.

### F. Migration correctness

*Decision:* cut a pipeline over from the old system to the new one.

*Smallest decisive test:* run both in parallel (shadow) for at least one full business cycle (a
week, or a month-end for finance data). Compare daily: row counts per partition, the primary-key set
difference in both directions, and a per-column hash aggregate per partition. Investigate every
mismatch.

*Criteria:* 100% key parity; value mismatches ≤ 0.01% of rows, each one explained; downstream
dashboard totals match to the cent for finance metrics.

## 5. When a full POC is impractical

Use the strongest option available and say in the doc why the stronger ones were not possible.
"No validation" is never an option.

| Option | Use when | How to make it count |
|---|---|---|
| Narrower spike | The full system is too big to build | Test only the mechanism the decision depends on: one table, one query shape, one hour of traffic |
| Back-of-envelope plus micro-benchmark | The question is cost or capacity | Write the model, find its dominant term, measure that term on our data (example E) |
| Replay | Production data can be copied or sampled | Real queries or events through the candidate, offline |
| Shadow or dark launch | Building is cheap, but switching is risky | Run alongside the old path on real traffic; compare outputs and metrics; serve nothing from it |
| Vendor trial | Buying, not building | Our data, our queries, our engineers, exit criteria agreed up front |
| Staged rollout as validation | Nothing earlier is possible | Name the criteria, guardrail metrics and canary size, and the check that must pass before the first irreversible step |

Reference calls and published benchmarks support a case; they never stand in for validation.

## 6. Writing up results

In the doc's Validation section:

1. The plan table, dated, showing it was written before the run.
2. A results table: test, result (with n and range), threshold, pass or fail, link to code at a
   commit hash and to raw results.
3. The set-up in one paragraph.
4. **What surprised us**, and whether it changed the design.
5. **What this does not prove**, and where in the rollout that gap gets closed.
6. Any threshold changes with the reason.

Then carry the headline into the TL;DR: the one result, against its threshold, that a director
needs.

After launch, check the goals against production numbers and add them to the Decision log. A good record
reports the measured change in the goal metrics, plus an increase, decrease and net cost table.
