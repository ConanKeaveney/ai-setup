# Benchmarking and verification: platforms, regressions, migrated outputs

Covers three jobs: comparing engines, platforms or table formats fairly; catching performance regressions in
your own jobs; and proving a migrated job (Spark 3.5 → 4.x, OSS/EMR → Databricks) writes the same output.
Tool status (latest release, last commit) was read from GitHub, PyPI, Maven and vendor docs on 28 Oct 2026.
"UNVERIFIED" marks anything not confirmed from a primary source. Snippets in section 5 were run on local
PySpark 4.0.1 (ANSI on) against authored fake data.

## 1. Pick the method from the question

| Question | Method | Section |
|---|---|---|
| Is engine/platform X faster or cheaper than Y? | TPC-DS/TPC-H-derived suite **plus** your own top jobs, same data and layout, cost per run | 2 |
| Which table format, or which write mode, for our update pattern? | Incremental-merge and longevity benchmarks with your own change ratios | 3 |
| Did this code/config/version change make job J slower? | Fixed input snapshot, fixed cluster, stage metrics compared to the job's own history | 4 |
| Does the migrated job write the same data? | Schema → per-partition count + checksum → keyed diff → tolerance on floats | 5 |
| Is today's output sane? | In-job data-quality checks that gate publish | 6 |

## 2. Engine and platform benchmarks

| Tool | What it does | Status (28 Oct 2026) |
|---|---|---|
| `databricks/spark-sql-perf` | The classic Scala TPC-DS/TPC-H data generator and runner | **GitHub repo returns 404**; artifacts still on Maven. Use the fork below. |
| [KubedAI/spark-sql-perf](https://github.com/KubedAI/spark-sql-perf) | Fork; branch `support-iceberg-tpcds-v4.0` adds Iceberg tables and TPC-DS v4.0 queries | Branch last commit 20 Apr 2026. Comet's guide uses it (3 iterations, SF100). |
| [databricks/tpcds-kit](https://github.com/databricks/tpcds-kit) | `dsdgen`/`dsqgen` (TPC-DS tools v2.4) with fixes, used by spark-sql-perf | Last commit 15 Aug 2023; dormant but works |
| [NVIDIA NDS](https://github.com/NVIDIA/cudf-spark-benchmarks) (renamed from `spark-rapids-benchmarks`) | NDS (TPC-DS-derived) and NDS-H (TPC-H-derived): power run (per-query CSV), throughput run (N parallel streams), data maintenance (INSERT/DELETE refresh) on Iceberg or Delta. **Runs on CPU Spark** (CPU, CPU+Iceberg, CPU+Delta templates) | Last commit 19 Oct 2026; no releases. Best-maintained open TPC-DS harness for Spark. |
| [aws-samples/emr-spark-benchmark](https://github.com/aws-samples/emr-spark-benchmark), [emr-on-eks-benchmark](https://github.com/aws-samples/emr-on-eks-benchmark) | AWS's EMR-vs-OSS method: TPC-DS v2.13 at 3 TB, 104 queries, Iceberg 1.10 on S3, OSS cluster via Flintrock | Last commits 26 Apr 2026 / 30 Jun 2026 |
| [Apache Gluten](https://github.com/apache/gluten) `tools/gluten-it` | Generates TPC-H/TPC-DS data, runs queries, and `queries-compare` checks Gluten results against vanilla Spark | Top-level Apache project since 18 Feb 2026; v1.7.0 (26 Aug 2026); Spark 3.4–4.1. Only published chart is old (Jun 2023, Spark 3.3.2). |
| [Apache DataFusion Comet](https://github.com/apache/datafusion-comet) | Benchmark guide and published TPC-DS/TPC-H results; data from `apache/datafusion-benchmarks` | 1.1.0 (6 Oct 2026). Dev docs list Spark 3.5–4.2; exact list for 1.1.0 UNVERIFIED. |
| [microsoft/LakeBench](https://github.com/microsoft/LakeBench) | pip-installable, multi-engine end-to-end: load, incremental merge, maintenance, queries | v2.2.0 (7 Oct 2026) |
| HiBench | Micro/ML workloads (WordCount, TeraSort, …) | **Archived** 15 Dec 2025; last release 2020. Do not use. |

**Running one honestly** (Raasveldt et al. DBTest 2018 checklist; AWS's EMR method; the Nov 2021
Databricks/Snowflake exchange):
1. **Same data, same layout.** Identical scale factor, file format, codec, file sizes, partitioning/sort,
   table-format version and catalog. Generate once, read from both platforms. A "pre-clustered" layout on one
   side is a cost you must count (Databricks' point).
2. **Same preprocessing.** Either collect stats (`ANALYZE TABLE … COMPUTE STATISTICS FOR ALL COLUMNS`) on both
   sides or on neither; AWS ran with "no precalculated statistics". Note automatic stats or optimisations the
   platform does for you (Databricks predictive optimisation, liquid clustering) and say whether they were on.
3. **Cold and warm separately.** Cold = fresh cluster, cleared disk/IO caches (Databricks disk cache, Photon,
   OS page cache); warm = discard the first run. Report which. AWS: 3 sequential rounds, per-query average.
4. **Repeat and report spread.** At least 3 runs; median with min/max or standard deviation. One run is an
   anecdote.
5. **Report total and geomean.** Total runtime is dominated by the few longest queries; geometric mean
   weights every query equally. AWS reports both (EMR 7.12 vs OSS 3.5.6: total 1,350 s vs 6,114 s, geomean
   7.5 s vs 22.3 s).
6. **Cost per run, not just runtime.** On-Demand list price × instance-hours + EBS + platform uplift (EMR fee,
   DBUs). Use list prices on both sides, not your discount on one. Include idle and start-up time.
7. **Check results are correct.** Compare row counts or result hashes per query between engines (gluten-it
   `queries-compare` does this); a fast wrong answer is not a win.
8. **Add your own jobs.** TPC-DS is a star-schema query mix; your top 10 jobs by cost (with their MERGEs, UDFs
   and skew) decide the migration. Zhihu saw about 40% of its top 200 jobs gain nothing on Gluten
   (field-results.md).
9. **Same table maintenance state.** Benchmark after the same compaction/manifest state on both sides, or the
   format with fewer small files wins by accident.

**TPC fair use** (Fair Use Quick Reference, 2019; Policies v6.20, Nov 2024). Results you run yourself are
not TPC results: call the workload "derived from TPC-DS", do not quote primary metrics (no `QphDS`, no
price/QphDS), and print the disclaimer that it "is derived from the TPC-DS … and as such is not comparable to
published TPC-DS results". Only audited results may use the TPC name. Current specs: TPC-DS v4.0.0 (Nov 2024;
QphDS combines power, two throughput and two data-maintenance tests plus load), TPC-H 3.0.1. Internal
comparisons are fine; this matters when publishing a blog or slide outside the company.

## 3. Table-format benchmarks

| Benchmark | Measures | Status / findings |
|---|---|---|
| [LHBench](https://github.com/lhbench/lhbench) (CIDR 2023, Jain et al.) | Four tests on Delta, Hudi, Iceberg: TPC-DS load + queries; TPC-DS Refresh (10 MERGEs of 3% each, then re-query); Merge micro-benchmark; Large File Count (up to 200k × 10 MB files) | Frozen since Feb 2023 (EMR 6.9, Spark 3.3, Iceberg 1.1, Delta 2.2, Hudi 0.12). Findings: merge-on-read merges faster but queries slower afterwards (Hudi MoR 1.3x faster merge, 3.2x slower query); MoR beats CoW from about 100k updated rows; Delta's queries 1.7x faster than Iceberg's, mostly scan time. Iceberg has changed a lot since 1.1: re-run, don't cite. |
| [LST-Bench](https://github.com/microsoft/lst-bench) (SIGMOD 2024) | Tasks → sessions (can run concurrently) → phases; workloads `wp1_longevity` (degradation over repeated data-maintenance rounds), `wp2_resilience`, `wp3_rw_concurrency`, `wp4_time_travel`; ships OPTIMIZE/compaction scripts for each format; telemetry to DuckDB | Last commit on main Jul 2025, no releases. Configs for Spark 3.3.1; Spark 3.4+ needs a schema tweak (SPARK-44025). Only open benchmark of read-after-many-commits degradation. |
| [onehouseinc/lake-loader](https://github.com/onehouseinc/lake-loader) | Generates rounds of change data (insert/update ratio, record size, partition spread, Zipfian skew); bulk-loads round 0, then incremental MERGEs; loaders for EMR, Databricks, Snowflake | Last commit Jun 2026; Spark 3.x |
| NVIDIA NDS data maintenance | TPC-DS refresh functions (INSERT/DELETE) on Iceberg or Delta | Section 2 |
| [Iceberg JMH](https://github.com/apache/iceberg/blob/main/jmh.gradle) | Micro-benchmarks in the Iceberg repo (core, data, Spark/Flink modules) | Active; for format developers, not platform choice |

Rules:
- **Model your own write pattern**: change ratio per run, partitions touched, update skew, run frequency.
  lake-loader parameterises exactly this; vendor benchmarks pick ratios that favour their format.
- **Measure over time, not once**: run 50–100 commits, then measure query time with and without compaction
  (LST-Bench longevity). Merge-on-read looks cheap at commit 1 and degrades as delete files pile up.
- Count maintenance (`rewrite_data_files`, `OPTIMIZE`) in the cost; a format that needs compaction every hour
  is not cheaper because its MERGE was faster.
- Pin versions in the write-up (format, engine, deletion vectors on/off, Iceberg v2 vs v3).

## 4. Regression harness for your own jobs

**Collect** (everything but sparkMeasure and system tables reads event logs, so keep `spark.eventLog.enabled=true`
with a durable directory):

| Tool | Gives | Status |
|---|---|---|
| [sparkMeasure](https://github.com/LucaCanali/sparkMeasure) | Per-stage/task metrics in code (`StageMetrics` begin/end), or **Flight Recorder** mode with no code change; sinks to files, Kafka, InfluxDB, Prometheus Pushgateway | 0.28 (19 May 2026), Spark 3.x and 4.x; PyPI `sparkmeasure` 0.28.0. API in testing.md section 4. |
| History Server REST API | `/api/v1/applications/<id>/stages`, `…/stages/<id>/<attempt>/taskSummary`, `/sql/<execution-id>`, `/allexecutors`; `/logs` downloads the event log | Spark built-in |
| [kubeflow/mcp-apache-spark-history-server](https://github.com/kubeflow/mcp-apache-spark-history-server) | MCP tools `compare_job_performance`, `compare_job_environments`, `compare_stages` (per-task quantiles), `compare_sql_executions` (optional plan diff); CLI `shs compare apps --app-a --app-b` | v1.0.2 (16 Oct 2026). Best ready-made two-run diff. |
| [NVIDIA cudf-spark-tools](https://github.com/NVIDIA/cudf-spark-tools) (renamed from `spark-rapids-tools`) | Profiling tool reads CPU or GPU event logs (config, executor and metric reports); Qualification only estimates GPU speed-up | v26.08.4 (23 Oct 2026). Not a purpose-built diff. |
| Databricks system tables | `system.lakeflow.job_run_timeline` / `job_task_run_timeline` (run durations), `system.billing.usage` joined to `system.billing.list_prices` on `usage_metadata.job_run_id` (cost per run), `system.compute.node_timeline` (per-node per-minute utilisation), `system.query.history` | GA (no preview label on the docs index). `query.history` covers SQL warehouses, serverless and pipelines, **not classic-compute jobs**. |
| Dead, do not adopt | qubole/sparklens (last commit 2021), linkedin/dr-elephant (2020), datamechanics/delight (archived 2024) | |

**What to compare** (practice; the CPU-time preference is a synthesis, not stated by any one source):
- Executor run time, executor CPU time and executor-seconds per stage, shuffle read/write bytes, spill, GC
  time, input bytes and files read, output files and bytes. Wall-clock last: it moves with cluster load.
- Match stages by their description (`setJobDescription`) or SQL operator, not stage id: AQE renumbers
  stages between runs (Onehouse, Jul 2026).
- Cost per run: executor-seconds × instance price on EMR/EKS; `system.billing.usage` per `job_run_id` on
  Databricks. That is the only metric comparable across the two platforms.

**Wiring it into CI and schedules:**
1. **Freeze the input**: an Iceberg tag (`CREATE TAG perf_baseline_2026q4 RETAIN 365 DAYS`) or a pinned
   snapshot id, so input never drifts. A scaled sample hides long-tail skew (Netflix, field-results.md);
   use full size for the jobs that matter.
2. **Freeze the cluster**: dedicated On-Demand nodes of one instance type, fixed executor count (dynamic
   allocation off), not a shared queue. MongoDB found EC2 noise is not per-instance and dropped with
   hyperthreading and power saving disabled (summarised from search results; posts not opened).
3. **Per pull request (cheap)**: plan-shape assertions and golden plans (testing.md section 4).
4. **Pre-merge for heavy changes**: run baseline and candidate 3–5 times each on the frozen input; gate on the
   median of executor CPU time or executor-seconds, e.g. fail above +10% (DBS: "within 10% of production run
   time"; UNVERIFIED, page returned 403) or on any new spill/`Exchange`.
5. **Nightly trend**: send per-job metrics to a table and run change-point detection instead of fixed
   thresholds: [Apache Otava](https://otava.apache.org/) (incubating, 0.8.0, May 2026; formerly
   DataStax Hunter; E-Divisive means as in MongoDB's ICPE 2020 paper), or flag runs outside the job's own
   P50/P95 envelope (Onehouse). Fixed thresholds on noisy metrics produce alert fatigue.

## 5. Proving a migrated job writes the same output

**Shadow run first**: run old and new jobs on the same input (same Iceberg snapshot) and have the new one
write to an Iceberg branch (`spark.wap.branch=shadow`) or a separate table, never over the production output.
Read the branch as `db.t.branch_shadow` or `VERSION AS OF 'shadow'` (a branch read uses the table's current
schema; a tag/snapshot read uses that snapshot's schema). Uber diffed outputs this way for its 2.4 → 3.3 move.

**Ladder (stop at the first step that fails, then drill down):**
1. **Schema**: `assertSchemaEqual` (testing.md). Types matter: a decimal precision change alters hashes.
2. **Per-partition row count and checksum** (cheap, one aggregate per side).
3. **Keyed diff** on the partitions that failed: classify each key as same / changed / only_old / only_new.
4. **Column-level diff with tolerances** for the changed rows (datacompy or spark-extension `diff`).
5. **Business aggregates** (sums per day/country) as the sign-off number for stakeholders.

```python
from pyspark.sql import functions as F

def row_hash(df, ignore=()):
    cols = sorted(c for c in df.columns if c not in ignore)
    # null flags: xxhash64 skips NULLs, so (1, NULL) and (NULL, 1) hash alike without them
    return F.xxhash64(*[F.col(c) for c in cols], *[F.col(c).isNull() for c in cols])

def checksum(df, by, ignore=()):
    h = row_hash(df, ignore).cast("decimal(38,0)")   # a bigint sum overflows and throws under ANSI
    return df.groupBy(by).agg(F.count(F.lit(1)).alias("rows"), F.sum(h).alias("hash"))

def bad_partitions(old, new, by, ignore=()):
    o, n = checksum(old, by, ignore).alias("o"), checksum(new, by, ignore).alias("n")
    return (o.join(n, by, "full_outer")
             .where(~F.col("o.rows").eqNullSafe(F.col("n.rows")) | ~F.col("o.hash").eqNullSafe(F.col("n.hash"))))

def keyed_diff(old, new, keys, ignore=()):
    o = old.select(*keys, row_hash(old, ignore).alias("h_old"), F.lit(True).alias("in_old"))
    n = new.select(*keys, row_hash(new, ignore).alias("h_new"), F.lit(True).alias("in_new"))
    return (o.join(n, keys, "full_outer")
             .withColumn("status", F.when(F.col("in_new").isNull(), "only_old")
                                    .when(F.col("in_old").isNull(), "only_new")
                                    .when(F.col("h_old") != F.col("h_new"), "changed")
                                    .otherwise("same")))

old = spark.read.option("snapshot-id", OLD_SNAPSHOT).table("lake.db.orders")
new = spark.read.table("lake.db.orders.branch_shadow")
ignore = ("loaded_at", "run_id")                     # run metadata differs by design
bad_partitions(old, new, "order_date", ignore).show()
keyed_diff(old, new, ["order_id"], ignore).groupBy("status").count().show()
```
Verified on 4.0.1: the checksum is identical after `repartition` + random reorder; without `ignore`, a
differing `loaded_at` flags every partition (the negative control); `sum(xxhash64(...))` as bigint threw
`ARITHMETIC_OVERFLOW` with ANSI on.

**Pitfalls (verified locally or in the Spark source/docs):**
- `xxhash64`/`hash` skip NULLs, and hashing a `struct` does not help: `(1, NULL)`, `(NULL, 1)` and `(1)` all
  hash the same. Add null flags as above.
- `-0.0` and `0.0` hash the same; NaN = NaN is true in Spark and NaNs group together.
- Decimals with precision ≤ 18 hash as a long, larger as bytes: same value, different type, different hash.
- **Floats**: sums depend on partitioning, so float/double aggregates differ in the last bits between runs
  and engines. Leave float columns out of the hash (`ignore`) and compare them with a
  tolerance in step 4.
- `bit_xor` of row hashes cancels duplicate rows (two identical rows XOR to 0). Use the decimal sum plus count.
- `subtract` is `EXCEPT DISTINCT` (drops duplicate differences); `exceptAll` is `EXCEPT ALL`. Run
  `exceptAll` in **both** directions. Both match columns by position, so `select` the same column order first.
- Set operations reject `MAP` columns (`SET_OPERATION_ON_MAP_TYPE`): convert with
  `array_sort(map_entries(m))` first.
- Joining on keys by name drops NULL keys to "only" on both sides; use `eqNullSafe` if keys can be NULL.
- Output file counts and sizes will differ (AQE, Celeborn, Photon); compare data, not files.

**Tools:**

| Tool | Use | Status |
|---|---|---|
| [datacompy](https://github.com/capitalone/datacompy) `SparkSQLCompare` | Column-level report on a keyed join (null-safe), `abs_tol`/`rel_tol` per column, unequal counts, max difference, sample mismatches; `matches()` for a boolean gate | v1.2.0 (27 Oct 2026); Spark 3.5 and 4.x, ANSI-tested, Spark Connect since 1.1.0. Pass `cache_intermediates=False` on Databricks serverless. |
| [G-Research spark-extension](https://github.com/G-Research/spark-extension) `diff` | Adds a diff column N/I/D/C (unchanged/inserted/deleted/changed) plus changed-column list; comparators per type/column: epsilon, whitespace, time window, maps; sparse mode; `pyspark-extension` for Python | 2.15.1 (10 Sep 2026), Spark up to 4.2. Best Spark-native row diff. |
| [Lakebridge](https://github.com/databrickslabs/lakebridge) reconcile (formerly Remorph) | Source → Databricks reconciliation: `schema`, `row` (sha2-256 row hash, no key), `data` (keyed), `all`; aggregate checks (MIN/MAX/SUM/…, with group by); column and table thresholds | v0.15.4 (23 Oct 2026). Sources: Oracle, Snowflake, SQL Server, Redshift, Teradata, BigQuery, Databricks. **No OSS Spark/Iceberg-on-S3 source**; registering the old Iceberg tables in Unity Catalog and reconciling as a Databricks source should work (UNVERIFIED). |
| `pyspark.testing.assertDataFrameEqual` | Small samples and unit tests (testing.md) | Spark 3.5+ |
| datafold/data-diff | Cross-database diff | **Archived May 2024**; fork `reladiff` (v0.6.0, Mar 2025) lists no Spark support. Skip. |

**Differences that change output values, not just errors** (Spark SQL migration guide, 4.2 docs):

| Move | Change | Setting to match the old behaviour while diffing |
|---|---|---|
| 3.5 → 4.0 | ANSI on: bad casts/overflow throw instead of NULL | `spark.sql.ansi.enabled` |
| 3.5 → 4.0 | Unparseable dates/timestamps: NULL (non-ANSI) or error, not legacy parsing | `spark.sql.legacy.timeParserPolicy` (now CORRECTED) |
| 3.5 → 4.0 | `-0.0` map keys normalised to `0.0` | `spark.sql.legacy.disableMapKeyNormalization` |
| 3.5 → 4.0 | Non-ANSI timestamp → integral cast returns NULL on overflow instead of wrapping | |
| 3.5 → 4.0 | `encode`/`decode` raise on bad characters instead of mojibake | `spark.sql.legacy.codingErrorAction`, `…javaCharsets` |
| 3.5 → 4.0 | CTE name precedence now CORRECTED; views add casts when column types change | `spark.sql.legacy.ctePrecedencePolicy`, `…viewSchemaCompensation` |
| 3.5 → 4.0 | Parquet rebase keys renamed (`spark.sql.parquet.datetimeRebaseModeInWrite`, `…int96RebaseModeInWrite`) | Check old dates (< 1582) survive |
| 4.0 → 4.1 | Parquet struct with all requested fields missing no longer read as NULL | `spark.sql.legacy.parquet.returnNullStructIfAllFieldsMissing` |
| 4.1 → 4.2 | `GROUPING SETS (())` over empty input returns one grand-total row; `NATURAL JOIN` honours `caseSensitive`; built-in functions win over same-named SQL function parameters | |
| OSS → Databricks | ANSI on in DBR 17.0+, serverless, and Databricks SQL (accounts since Oct 2022); session time zone, `spark.sql.timestampType` (TIMESTAMP_LTZ default in both) | Set the same session TZ on both sides before diffing |
| Spark → Photon | Docs say Photon falls back to Spark and "still produces correct results"; no documented value differences (float/regex differences UNVERIFIED) | Photon cannot be switched off on serverless or SQL warehouses |

Diff once with the new engine at its defaults: a mismatch then tells you which row breaks under the new
semantics. Legacy flags are a bridge for cut-over, not a permanent setting.

## 6. Data-quality frameworks in the job

| Framework | Latest (date) | Spark 4 | Runs on OSS Spark? | Fit |
|---|---|---|---|---|
| [Deequ](https://github.com/awslabs/deequ) / [PyDeequ](https://github.com/awslabs/python-deequ) | Deequ 2.1.0 (16 Sep 2026, `-spark-3.5` only); Maven has `2.0.18-spark-4.1` (Jun 2026); PyDeequ 1.7.0 (14 Sep 2026) | Yes, 4.1 via the 2.0.x line (README table still says 3.1–3.5) | Yes | Constraint checks, metrics repository, anomaly detection; best fit on 3.5, works on 4.1 a release behind. PyDeequ needs `SPARK_VERSION=3.5` or `4.1`. |
| [Great Expectations](https://pypi.org/project/great-expectations/) (GX Core) | 1.24.1 (22 Oct 2026) | Yes since 1.19.0 (Jul 2026), pyspark `<4.2` | Yes (`add_spark()`) | Python suites and data docs; heavier |
| [Soda Core v4](https://github.com/sodadata/soda-core) | 4.29.0 (27 Oct 2026), weekly | `soda-sparkdf` needs pyspark ≥ 3.5 | Yes | YAML data contracts; **licence is Elastic 2.0 / proprietary** (date of change UNVERIFIED): legal review first |
| [Databricks Labs DQX](https://github.com/databrickslabs/dqx) | 0.17.0 (22 Oct 2026) | n/a | **No**: needs a workspace, no local mode, Databricks licence | Checks, quarantine, profiling on the Databricks side only |
| Lakeflow expectations | `@dp.expect`, `expect_or_drop`, `expect_or_fail`; SQL `CONSTRAINT … EXPECT … ON VIOLATION` | n/a | **No**: OSS Declarative Pipelines (4.2 guide) has none | Native on Databricks pipelines |
| [EMR Data Quality](https://docs.aws.amazon.com/emr/latest/ManagementGuide/emr-data-quality.html) | `emr-spark-8.1.0` (launched about 12 Oct 2026, secondary source) | Spark version UNVERIFIED | EMR only (EC2, EKS, Serverless) | DQDL rules on the Deequ engine, results in Glue Data Quality |
| [Pandera](https://pandera.readthedocs.io/en/stable/pyspark_sql.html) | 0.35.0 (25 Oct 2026) | UNVERIFIED (no upper pin) | Yes | Schema and type validation; weak on aggregate metrics |
| [cuallee](https://pypi.org/project/cuallee/) | 0.15.4 (7 Oct 2025) | Yes (pyspark 4.0.1) | Yes | Light, `Observation`-based; stale for a year |

For a stack moving between OSS Spark and Databricks, keep the checks portable: plain `df.observe` metrics
plus a WAP gate (job-design.md section 4), or GX/Deequ on both sides, rather than DQX or Lakeflow
expectations that stop at the platform boundary.

## 7. Best resources

| Resource | Why |
|---|---|
| [Raasveldt et al., "Fair Benchmarking Considered Difficult" (DBTest 2018)](https://ir.cwi.nl/pub/27862/27862.pdf) | Short paper; Appendix A is the checklist to hold any benchmark to |
| [AWS: EMR vs OSS Spark + Iceberg (Nov 2025)](https://aws.amazon.com/blogs/big-data/run-apache-spark-and-iceberg-4-5x-faster-than-open-source-spark-with-amazon-emr) + [emr-spark-benchmark](https://github.com/aws-samples/emr-spark-benchmark) | A complete, reproducible platform comparison with method, cluster and cost |
| [NVIDIA NDS README](https://github.com/NVIDIA/cudf-spark-benchmarks) | Power / throughput / maintenance runs on Iceberg, CPU or GPU |
| [LHBench paper (CIDR 2023)](https://www.cidrdb.org/cidr2023/papers/p92-jain.pdf) and [LST-Bench paper](https://arxiv.org/abs/2305.01120) | How to benchmark table formats, including degradation over many commits |
| [TPC Fair Use Quick Reference](https://www.tpc.org/TPC_Documents_Current_Versions/pdf/Fair_Use_Quick_Reference_v1.0.0.pdf) | Two pages on what you may say when publishing derived results |
| [Onehouse: catching Spark regressions across runs (Jul 2026)](https://www.onehouse.ai/blog/spark-performance-regressions) | History envelopes, stage matching under AQE, which metrics to watch |
| [Daly et al., change point detection at MongoDB (ICPE 2020)](https://arxiv.org/abs/2003.00584) | Why fixed thresholds fail for performance CI; the method behind Apache Otava |
| [Uber: upgrading 2M Spark jobs](https://www.uber.com/blog/ubers-strategy-to-upgrading-2m-spark-jobs/) | Shadow-run-and-diff at fleet scale |
| [Spark SQL migration guide](https://spark.apache.org/docs/latest/sql-migration-guide.html) | Every behaviour change between versions, with the legacy flag for each |

## Sources
Benchmarks (read 28 Oct 2026):
- https://github.com/databricks/spark-sql-perf (404) and https://mvnrepository.com/artifact/com.databricks/spark-sql-perf
- https://github.com/KubedAI/spark-sql-perf
- https://github.com/databricks/tpcds-kit
- https://github.com/NVIDIA/cudf-spark-benchmarks
- https://github.com/aws-samples/emr-spark-benchmark
- https://github.com/aws-samples/emr-on-eks-benchmark
- https://aws.amazon.com/blogs/big-data/run-apache-spark-and-iceberg-4-5x-faster-than-open-source-spark-with-amazon-emr
- https://github.com/apache/gluten and https://incubator.apache.org/projects/gluten.html
- https://github.com/apache/datafusion-comet
- https://datafusion.apache.org/comet/contributor-guide/benchmark-results/tpc-ds.html
- https://datafusion.apache.org/comet/contributor-guide/benchmarking_spark_sql_perf.html
- https://github.com/apache/datafusion-benchmarks
- https://github.com/microsoft/LakeBench
- https://github.com/Intel-bigdata/HiBench
- https://www.tpc.org/TPC_Documents_Current_Versions/pdf/Fair_Use_Quick_Reference_v1.0.0.pdf
- https://www.tpc.org/TPC_Documents_Current_Versions/pdf/Policies_v6.20.pdf
- https://www.tpc.org/tpc_documents_current_versions/current_specifications5.asp
- https://www.tpc.org/tpcds/results/tpcds_results5.asp?version=3
- https://ir.cwi.nl/pub/27862
- https://www.snowflake.com/en/blog/industry-benchmarks-and-competing-with-integrity
- https://www.databricks.com/blog/2021/11/15/snowflake-claims-similar-price-performance-to-databricks-but-not-so-fast.html

Table formats:
- https://www.cidrdb.org/cidr2023/papers/p92-jain.pdf
- https://github.com/lhbench/lhbench
- https://github.com/microsoft/lst-bench
- https://arxiv.org/abs/2305.01120
- https://github.com/onehouseinc/lake-loader
- https://github.com/apache/iceberg/blob/main/jmh.gradle

Regression harnesses:
- https://github.com/LucaCanali/sparkMeasure
- https://spark.apache.org/docs/latest/monitoring.html
- https://github.com/kubeflow/mcp-apache-spark-history-server
- https://github.com/NVIDIA/cudf-spark-tools
- https://github.com/qubole/sparklens
- https://github.com/linkedin/dr-elephant
- https://github.com/datamechanics/delight
- https://docs.databricks.com/aws/en/admin/system-tables/
- https://docs.databricks.com/aws/en/admin/system-tables/jobs-cost
- https://docs.databricks.com/aws/en/admin/system-tables/compute
- https://docs.databricks.com/aws/en/admin/system-tables/query-history
- https://arxiv.org/abs/2003.00584
- https://otava.apache.org/ and https://github.com/apache/otava
- https://mongodb.com/blog/post/reducing-variability-performance-tests-ec2-setup-key-results (search summary only)
- https://www.onehouse.ai/blog/spark-performance-regressions
- https://medium.com/dbs-tech-blog/adopt-these-3-key-practices-to-drive-better-long-term-application-performance-on-spark-7b89820f7651 (403; search snippet only)

Output verification:
- https://github.com/capitalone/datacompy and https://capitalone.github.io/datacompy/spark_usage.html
- https://github.com/databrickslabs/lakebridge and https://databrickslabs.github.io/lakebridge/docs/reconcile/
- https://github.com/G-Research/spark-extension/blob/master/DIFF.md
- https://github.com/datafold/data-diff
- https://github.com/erezsh/reladiff
- https://spark.apache.org/docs/latest/sql-ref-syntax-qry-select-setops.html
- https://spark.apache.org/docs/latest/api/sql/hash-functions/
- https://spark.apache.org/docs/latest/sql-ref-datatypes.html
- https://github.com/apache/spark/blob/master/sql/catalyst/src/main/scala/org/apache/spark/sql/catalyst/expressions/hash.scala
- https://iceberg.apache.org/docs/latest/branching/
- https://iceberg.apache.org/docs/latest/spark-queries/
- https://spark.apache.org/docs/latest/sql-migration-guide.html
- https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-ansi-compliance
- https://docs.databricks.com/aws/en/sql/language-manual/parameters/ansi_mode
- https://docs.databricks.com/aws/en/compute/serverless/limitations
- https://docs.databricks.com/aws/en/compute/photon

Data quality:
- https://github.com/awslabs/deequ and https://repo1.maven.org/maven2/com/amazon/deequ/deequ/
- https://github.com/awslabs/python-deequ
- https://pypi.org/project/great-expectations/
- https://docs.greatexpectations.io/docs/core/connect_to_data/dataframes/
- https://github.com/sodadata/soda-core and https://pypi.org/project/soda-sparkdf/
- https://github.com/databrickslabs/dqx and https://databrickslabs.github.io/dqx/docs/installation/
- https://docs.databricks.com/aws/en/ldp/expectations
- https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html
- https://docs.aws.amazon.com/emr/latest/ManagementGuide/emr-data-quality.html
- https://pandera.readthedocs.io/en/stable/pyspark_sql.html
- https://pypi.org/project/cuallee/
