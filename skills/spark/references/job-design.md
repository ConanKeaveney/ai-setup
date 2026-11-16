# Designing a Spark job (batch and streaming, on Iceberg)

How to shape a job so it is correct on re-run, cheap to change, and debuggable, before any tuning. Iceberg
rules are from the 1.12.0 docs; Spark from 4.2.0. Rules with no official source are marked "practice".

## 1. Layers and job boundaries

| Layer (Databricks / AWS name) | Does | Does not |
|---|---|---|
| Bronze / Raw | Append-only copy of the source with load metadata (source file, ingest time, batch id). Minimal parsing; keep awkward fields as string or VARIANT. | Dedupe, filter, or serve analysts |
| Silver / Stage | Clean, type, dedupe, conform keys, enrich. Keep at least one validated, non-aggregated copy of every record. Read bronze incrementally. | Get written straight from ingestion (Databricks advises against it) |
| Gold / Analytics | Business-level aggregates and dimensional models, several per domain if needed | Hold long raw history (that stays in silver) |

- AWS prescriptive guidance: at least three layers (Raw / Stage / Analytics), each in its own S3 bucket;
  Raw keeps the original format with bucket versioning on; a masked landing zone in front of Raw for PII.
- **One output table per job (or per flow), with dependencies in the orchestrator** (practice). It makes a
  failure re-runnable on its own, gives one place to look for each table's lineage and metrics, and maps
  onto Spark Declarative Pipelines (one flow per target) and Databricks jobs/pipelines when you migrate.
  Group several outputs in one job only when they share an expensive read that would otherwise repeat.
- Keep heavy shared intermediates as Iceberg tables, not cached DataFrames passed between steps: they
  survive failure, are inspectable, and decouple jobs.

## 2. Idempotent, re-runnable writes

A job is idempotent when running it twice for the same logical date leaves the table as running it once.

| Write | Idempotent? | Use for |
|---|---|---|
| `append()` / `INSERT INTO` | **No**: a re-run duplicates rows | Bronze, only with a dedupe key downstream or a guard on batch id |
| `overwrite(<filter>)` (`writeTo(t).overwrite(col("d") == run_date)`) | Yes | Recomputing a known slice (one day, one hour). Iceberg's preferred partition-bounded rerun, independent of partition layout. |
| `overwritePartitions()` / dynamic `INSERT OVERWRITE` | Yes, for the partitions the output touches | Daily partition rebuilds. Set `spark.sql.sources.partitionOverwriteMode=dynamic`; Spark's default STATIC with no `PARTITION` clause replaces the whole table. |
| `MERGE INTO` | Yes, if the source is deduplicated and keys are stable | Upserts, CDC, late corrections. Iceberg recommends MERGE over `INSERT OVERWRITE` because it replaces only affected files and does not depend on the partition spec. |

Rules:
- **Pass the logical run date (and any "now") in as a parameter**; never derive keys or filters from
  `current_timestamp()` / `current_date()`, which change between runs.
- **Deduplicate MERGE sources first**: more than one source row matching a target row is an error.
  Spark 3.5+ has `WHEN NOT MATCHED BY SOURCE` for deletes; 4.0+ has `df.mergeInto(target, cond)`.
- **Tag every commit with the run id**: write option `snapshot-property.run_id=<id>` (or
  `CommitMetadata.withCommitProperties` in SQL), so a snapshot can be traced to an orchestrator run.
- Prefer the v2 writer (`df.writeTo(...)`): it matches columns by name and makes overwrite semantics explicit.
- Deleting whole partitions (`DELETE FROM t WHERE d = …` matching full partitions) is metadata-only.
- Plain Parquet on S3 cannot do dynamic partition overwrite with the S3A committers; use Iceberg.

### Write-audit-publish (WAP) on Iceberg
Use when a bad publish is expensive (gold tables, external consumers).
```sql
ALTER TABLE db.t SET TBLPROPERTIES ('write.wap.enabled'='true');
ALTER TABLE db.t CREATE BRANCH `audit_20261028` RETAIN 7 DAYS;   -- branch must exist before the write
SET spark.wap.branch = audit_20261028;
-- run the job's write(s) as normal; they land on the branch, main is untouched
-- run data-quality checks against db.t.branch_audit_20261028
CALL lake.system.fast_forward('db.t', 'main', 'audit_20261028');  -- publish atomically
```
- Branch WAP works for MERGE and every write type. The older staged mode (`spark.wap.id`, then
  `publish_changes` / `cherrypick_snapshot`) **only publishes append and dynamic-overwrite snapshots**, and
  needs a unique wap id per run.
- Writes to a branch are validated against the table's current schema.
- Cost: an extra step and orchestration, and readers see new data only after publish.

## 3. Incremental vs full recompute

| Situation | Choose |
|---|---|
| Output is small or logic changes often | Full recompute (overwrite the table or its recent partitions); simplest and self-healing |
| Upstream is append-only, output is big | Incremental: Iceberg `start-snapshot-id` / `end-snapshot-id` read (start exclusive, end inclusive), or a stream with `availableNow` |
| Upstream has MERGE / UPDATE / DELETE | `CALL system.create_changelog_view(...)` over a snapshot range: rows with `_change_type` (INSERT, DELETE, UPDATE_BEFORE, UPDATE_AFTER); `compute_updates` needs `identifier_columns` and cannot be combined with `net_changes` |
| Late data can change already-written aggregates | Recompute a trailing window of partitions each run (e.g. last 3 days) with `overwrite(<filter>)`, or MERGE corrections |
| On Databricks / Delta | Change data feed (`readChangeFeed`, `table_changes()`), with `_change_type` insert / update_preimage / update_postimage / delete |

- Iceberg incremental batch reads and streaming reads see **append snapshots only**; overwrite and delete
  snapshots throw unless skipped (`streaming-skip-overwrite-snapshots`, `streaming-skip-delete-snapshots`).
  Use the changelog view when the upstream rewrites rows.
- Store the last processed snapshot id (or let a streaming checkpoint do it); never "the last N hours by
  wall clock", which double-counts or misses on retries.

**Batch vs streaming vs availableNow:**
- **Scheduled batch** when the source is a table you recompute slices of, or freshness is hours.
- **`trigger(availableNow=True)`** for incremental batch on a schedule: processes everything new in
  rate-limited micro-batches, then stops, with exactly-once bookkeeping from the checkpoint. Replaces
  `Trigger.Once` (deprecated). If a source lacks support it falls back to one batch.
- **Continuous micro-batch streaming** when freshness must be minutes or less and the cost of an always-on
  cluster is justified. Iceberg sinks: trigger ≥ 1 minute, append or complete mode.
- Exactly-once needs a replayable source, a checkpoint, and an idempotent sink; `foreachBatch` is
  at-least-once unless the write is idempotent on `batchId` or a natural key.
- Know what a checkpoint survives before shipping: changing the number or type of sources, stateful
  operators or grouping keys needs a new checkpoint; adding filters does not (streaming.md section 4).

## 4. Schema contracts and data quality in the job
- **Declare the input schema** for JSON/CSV. Use `mode=PERMISSIVE` with `columnNameOfCorruptRecord` (that
  string column must be in your schema) to route bad records to a quarantine table; `FAILFAST` to stop the
  job; never silently `DROPMALFORMED` without counting.
- **Schema changes are deliberate**: Iceberg evolution (add, drop, rename, widen, reorder) is metadata-only and
  safe because columns are tracked by id. Write-time schema merge needs both
  `write.spark.accept-any-schema=true` on the table and `mergeSchema=true` on the write: allow it in bronze
  at most, never in silver/gold. Iceberg checks nullability and column order on write by default
  (`check-nullability`, `check-ordering` = true).
- **Quarantine, don't drop**: compute an `is_valid` flag from the rules, write invalid rows with the failing
  rule names to a quarantine table, and fail the job when the invalid share crosses a threshold
  (Databricks expectation-patterns page shows the pattern; it works on plain Spark).
- **Gate publishing on checks**: run checks on the WAP branch (section 2) or as a separate orchestrator task
  that downstream tasks depend on. A check whose result nothing waits on gates nothing.
- Cheap checks worth having on every output: row count vs previous run, primary-key uniqueness, null rate of
  key columns, freshness of the max event time. Capture them with `df.observe` (section 7) to avoid extra jobs.
- **Libraries:**
  - Deequ / PyDeequ: constraint checks, suggestion, anomaly detection. README lists Spark 3.1–3.5, but Maven
    has Spark 4 builds on the 2.0.x line (`2.0.18-spark-4.1`, Jun 2026); PyDeequ 1.7.0 supports 3.5 and 4.1.
  - Great Expectations (GX Core 1.x): Spark DataFrame data source (`context.data_sources.add_spark()`);
    Spark 4 since 1.19.0.
  - Soda Core v4: YAML contracts on a Spark DataFrame (`soda-sparkdf`); Elastic License 2.0.
  - Versions, fit and the Databricks-only options (DQX): benchmarking.md section 6.
  - Databricks Lakeflow expectations (`@dp.expect`, `expect_or_drop`, `expect_or_fail`; SQL
    `CONSTRAINT … EXPECT … ON VIOLATION`) are **Databricks-only**: OSS Spark Declarative Pipelines (4.1/4.2)
    has no expectations.

## 5. Code organisation
- **Pure transforms**: functions `DataFrame -> DataFrame` with plain parameters, chained with
  `df.transform(f, *args, **kwargs)` (args since 3.3). No reads, writes, actions or session creation inside.
- **Thin entrypoint** (practice): parse arguments and config, build the session, read inputs, call the
  transforms, write, emit metrics. Config (paths, table names, dates, thresholds) lives in arguments or a
  config file, not in the transform code, so the same code runs in tests, backfills and production.
- In SDP dataset functions, never write, `collect()`, `count()` or cause side effects: the guide says the
  code may be evaluated several times.
- **Packaging**: `--py-files` ships `.py`/`.zip`/`.egg` but not wheels with native code; for dependencies ship
  a packed environment (conda-pack, venv-pack, PEX) via `--archives` / `spark.archives`, or bake a
  container image (K8s, EMR on EKS). On Databricks, use Declarative Automation Bundles (formerly Databricks
  Asset Bundles, `databricks.yml`) with a wheel.
- Tests: testing.md.

## 6. Backfills and late data
- **Backfill partition by partition** with the same code path as the daily run and `overwrite(<filter>)` or a
  partition-scoped MERGE; size each run to what the cluster handles (for example one month), and make
  each slice independently re-runnable.
- **Isolate risky backfills on a branch**: write to a branch, compare with `main` via time travel
  (`VERSION AS OF '<branch|tag|snapshot>'`), then `fast_forward`. Tag the pre-backfill snapshot
  (`ALTER TABLE t CREATE TAG pre_backfill_x RETAIN 14 DAYS`; prefix tag names, since a numeric name is read as a
  snapshot id) and keep `rollback_to_snapshot` as the undo.
- Backfills compete with production: run them on their own cluster or queue, and avoid concurrent writers
  on the same partitions (commit conflicts under serializable isolation).
- **Streaming late data**: `withWatermark("ts", "2 hours")` guarantees data under 2 hours late is kept; later
  data may or may not be dropped. Decide the bound with the data owners, then handle stragglers with a
  periodic batch correction (MERGE) rather than an ever-larger watermark. For dedup use
  `dropDuplicatesWithinWatermark` with a delay longer than the gap between duplicates.

## 7. Observability by design
- **Event logs always on**: `spark.eventLog.enabled=true`, `spark.eventLog.dir=s3a://…`; History Server
  reads `spark.history.fs.logDirectory`. Rolling and compression are on by default from 4.0.
- **Name the work**: `spark.sparkContext.setJobDescription("silver.orders: merge")`, `setJobGroup(id, desc)`;
  `spark.addTag()` / `interruptTag()` (3.5+; classic since 4.0) to find and cancel. With Python threads use
  `pyspark.InheritableThread`. (Not available on Spark Connect for `sparkContext` calls.)
- **Metrics without extra jobs**: `obs = Observation("orders"); df = df.observe(obs, F.count(F.lit(1)).alias("rows"),
  F.sum(F.col("bad").cast("int")).alias("bad"))`, then `obs.get` after the write (3.3+, batch only). For
  streaming use `df.observe("name", …)` and read it in a `StreamingQueryListener` (`onQueryProgress`).
- **Assert on Iceberg commit summaries** after a write: MERGE commits carry
  `spark.merge-into.num-target-rows-{inserted,updated,deleted,copied}` (Spark 4.1+), INSERTs
  `spark.insert.num-inserted-rows` (Spark 4.2+). Read them from `<table>.snapshots`.
- Iceberg `MetricsReporter` (since 1.1.0, catalog property `metrics-reporter-impl`) emits scan and commit
  reports (attempts, files added/removed, duration); the REST catalog posts them to `/metrics` by default.
- **Lineage**: OpenLineage Spark listener, `spark.extraListeners=io.openlineage.spark.agent.OpenLineageSparkListener`,
  `spark.openlineage.transport.type=http` + `.transport.url`, `spark.openlineage.namespace`, and
  `spark.openlineage.parentJobName` / `parentRunId` to link to the orchestrator run. Package
  `io.openlineage:openlineage-spark_2.13:<ver>` (1.54.0 current). Iceberg dataset support not verified on its docs.

## 8. Best resources to read

| Resource | Why |
|---|---|
| Iceberg Spark docs: [writes](https://iceberg.apache.org/docs/latest/spark-writes/), [procedures](https://iceberg.apache.org/docs/latest/spark-procedures/), [branching](https://iceberg.apache.org/docs/latest/branching/) | The authority on every idempotency, WAP, CDC and maintenance rule here |
| [Structured Streaming guide](https://spark.apache.org/docs/latest/streaming/apis-on-dataframes-and-datasets.html) | Triggers, watermarks, and the exact list of checkpoint-compatible query changes |
| [Spark Declarative Pipelines guide](https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html) | The OSS version of the Databricks pipeline model; shows how to structure flows before migrating |
| [PySpark testing guide](https://spark.apache.org/docs/latest/api/python/getting_started/testing_pyspark.html) | The official pattern for unit-testing transforms |
| [Databricks medallion architecture](https://docs.databricks.com/aws/en/lakehouse/medallion) | Clearest do/don't list per layer |
| [Databricks expectation patterns](https://docs.databricks.com/aws/en/ldp/expectation-patterns) | Quarantine, uniqueness and gating recipes that port to plain Spark |
| [AWS: Using Apache Iceberg on AWS](https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/introduction.html) | Glue, EMR and Athena specifics for this stack |
| [AWS blog: WAP with Iceberg branches and Glue Data Quality](https://aws.amazon.com/blogs/big-data/build-write-audit-publish-pattern-with-apache-iceberg-branching-and-aws-glue-data-quality/) | End-to-end WAP on AWS, with its trade-offs |
| [Netflix: Scaling Data Quality (Ufford, 2017)](https://www.slideshare.net/MichelleFUfford/scaling-data-quality-netflix-76917740) | Where write-audit-publish comes from |
| [Uber: operational excellence in data quality](https://www.uber.com/blog/operational-excellence-data-quality/) | Quality dimensions, tiered SLAs, lineage-generated tests |
| [Beauchemin: Functional Data Engineering (talk)](https://www.aicouncil.com/functional-data-engineering-a-set-of-best-practices) | The case for pure, idempotent, partition-overwrite pipelines (essay on Medium not fetched) |
| [Data Engineering Design Patterns: code repo](https://github.com/bartosz25/data-engineering-design-patterns-book) | Runnable idempotency and data-quality patterns (author/publisher not verified from the repo page) |
| [Spark: The Definitive Guide excerpts](https://pages.databricks.com/definitive-guide-spark.html) | Free chapters on the DataFrame and execution model |

## Sources
Spark (4.2.0):
- https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html
- https://spark.apache.org/docs/latest/streaming/apis-on-dataframes-and-datasets.html
- https://spark.apache.org/docs/latest/streaming/getting-started.html
- https://spark.apache.org/docs/latest/sql-data-sources-json.html
- https://spark.apache.org/docs/latest/monitoring.html
- https://spark.apache.org/docs/latest/api/python/tutorial/python_packaging.html
- https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.transform.html
- https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.Observation.html
- https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.DataFrame.observe.html
- https://spark.apache.org/docs/latest/api/python/reference/pyspark.sql/api/pyspark.sql.functions.current_timestamp.html
- https://spark.apache.org/docs/latest/api/python/reference/api/pyspark.SparkContext.setJobGroup.html
- https://spark.apache.org/docs/latest/api/python/reference/pyspark.ss/api/pyspark.sql.streaming.StreamingQueryListener.html

Iceberg (1.12.0):
- https://iceberg.apache.org/docs/latest/spark-writes/
- https://iceberg.apache.org/docs/latest/spark-configuration/
- https://iceberg.apache.org/docs/latest/spark-procedures/
- https://iceberg.apache.org/docs/latest/spark-queries/
- https://iceberg.apache.org/docs/latest/spark-structured-streaming/
- https://iceberg.apache.org/docs/latest/branching/
- https://iceberg.apache.org/docs/latest/evolution/
- https://iceberg.apache.org/docs/latest/metrics-reporting/

Databricks and AWS:
- https://docs.databricks.com/aws/en/lakehouse/medallion
- https://docs.databricks.com/aws/en/ldp/expectations
- https://docs.databricks.com/aws/en/ldp/expectation-patterns
- https://docs.databricks.com/aws/en/delta/delta-change-data-feed
- https://docs.databricks.com/aws/en/dev-tools/bundles/
- https://docs.aws.amazon.com/prescriptive-guidance/latest/defining-bucket-names-data-lakes/data-layer-definitions.html
- https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/introduction.html
- https://aws.amazon.com/blogs/big-data/build-write-audit-publish-pattern-with-apache-iceberg-branching-and-aws-glue-data-quality/

Data quality and lineage:
- https://github.com/awslabs/deequ
- https://docs.greatexpectations.io/docs/core/connect_to_data/dataframes/
- https://docs.soda.io/soda-documentation/reference/data-source-reference-for-soda-core/spark-dataframe.md
- https://openlineage.io/docs/integrations/spark/configuration/usage
- https://openlineage.io/docs/integrations/spark/installation
