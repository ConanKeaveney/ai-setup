# Spark 4.0 / 4.1 / 4.2: what changed in practice

Release dates (spark.apache.org news): 4.0.0 on 23 May 2025, 4.1.0 on 16 Dec 2025, 4.2.0 on 14 Jul 2026.
Current patch releases (27 Oct 2026): 4.2.1, 4.1.4, 4.0.5; 3.5.9 (16 Jul 2026) is the latest 3.5.
Every default below was read from the config tables or migration guides for that version. Anything
read only on unreleased `master` docs is marked as such.

## 1. Upgrade checklist (what breaks or changes behaviour)

| Version | Change | What to do |
|---|---|---|
| 4.0 | ANSI mode on (`spark.sql.ansi.enabled`=true) | Bad casts, overflow, divide-by-zero throw. Use `try_cast` / `try_divide`; diff outputs before switching. |
| 4.0 | JDK 17+, Scala 2.13 only, Python 3.8 dropped, Mesos removed | Rebuild jars for 2.13; Iceberg runtime jar must match (`iceberg-spark-runtime-4.x_2.13`). |
| 4.0 | Speculation less aggressive: `spark.speculation.multiplier` 1.5 → 3, `.quantile` 0.75 → 0.9 | Only matters if you enabled speculation. |
| 4.0 | `spark.shuffle.service.removeShuffle`, `spark.stage.ignoreDecommissionFetchFailure` → true; event logs rolled and compressed by default | Nothing; better defaults for dynamic allocation and spot. |
| 4.0 | ORC default codec snappy → zstd; `spark.sql.maxSinglePartitionBytes` unlimited → 128m | Parquet default codec is still snappy. |
| 4.1 | Python 3.10+, PyArrow 15+, pandas 2.2+ | Pin these in images. |
| 4.1 | `spark.sql.sources.v2.bucketing.enabled` → true (SPJ on by default for V2 sources such as Iceberg) | Check plans of Iceberg joins: shuffles may disappear, and so may parallelism if buckets are few. |
| 4.1 | SQL scripting GA and on (`spark.sql.scripting.enabled`=true; false in 4.0) | |
| 4.1 | `spark.checkpoint.compress` → true; native Netty IO (`spark.io.mode.default`=AUTO, epoll on Linux) | |
| 4.1 | Hadoop S3A **magic committer used for all S3 buckets by default** (`spark.hadoop.fs.s3a.committer.magic.enabled=false` restores) | Affects plain Parquet/ORC writes to `s3a://`, not Iceberg tables. |
| 4.1 | PySpark `BinaryType` → Python `bytes` everywhere (`spark.sql.execution.pyspark.binaryAsBytes`); `spark.sql.execution.pandas.convertToArrowArraySafely` on (overflow/truncation now raises) | Re-run UDF tests. |
| 4.2 | **Arrow on by default for PySpark**: `spark.sql.execution.arrow.pyspark.enabled`, `spark.sql.execution.pythonUDF.arrow.enabled`, `spark.sql.execution.pythonUDTF.arrow.enabled` all true | Plain `@udf` now runs Arrow-batched; nullable ints arrive in pandas UDFs as `Int64` etc., not `float64`. PyArrow 18+ required; PyPy dropped. |
| 4.2 | Order-independent shuffle checksums on (`spark.sql.shuffle.orderIndependentChecksum.enabled`, since 4.1.0); a mismatch on an indeterminate stage retry rolls back and re-runs dependent stages, or fails the job | Fixes silent wrong results after retries of non-deterministic stages; a job may now fail where it used to succeed wrongly. |
| 4.2 | K8s: executor pod allocation batch 10 → 20; a NetworkPolicy is created by default so executors accept traffic only from the driver and peers | If you run a sidecar or external shuffle path that talks to executors, exclude `NetworkPolicyFeatureStep`. |
| 4.2 | Java 25 supported; GEOMETRY/GEOGRAPHY types on; Web UI modernised | |

## 2. Features worth knowing

### Spark Connect (4.0 first-class)
- Thin client sends unresolved plans over gRPC; results come back as Arrow. `spark.api.mode` (4.0+, default
  `classic`) switches an application to Connect (`connect`) by starting a local Connect server.
- 4.0: lightweight `pyspark-client` package (about 1.5 MB), Scala/Java client API parity.
  4.1: Spark ML on Connect GA for Python, zstd-compressed plans, chunked Arrow results.
  4.2: Connect tab in the History Server, server-side `GetStatus`, `head()/take()` no longer scan everything.
- **Practical rule:** Connect removes RDD and `SparkContext` access, so code using `df.rdd`,
  `sparkContext.setJobDescription`, accumulators or `_jdf` needs changes. Databricks serverless and shared
  clusters are Connect-based, so writing Connect-compatible code eases the Databricks move.

### VARIANT (4.0 added, 4.1 GA)
- Binary semi-structured type: `parse_json(col)`, then `variant_get(v, '$.a.b', 'int')` or `v:a.b`
  (colon syntax, 4.1). 4.1 adds **shredding** in the Parquet writer (frequently used paths stored as typed
  columns, so reads skip parsing) and reads the Parquet Variant logical type.
- **Rule:** prefer VARIANT over JSON strings for semi-structured columns you query by path; it avoids
  re-parsing on every read. Check your Iceberg version supports VARIANT (Iceberg v3) before writing it to
  tables. Load the `iceberg` skill for v3 details.

### SQL scripting (4.0 preview behind a flag, 4.1 GA and on, 4.2 cursors)
- `BEGIN … END` blocks with variables, `IF`, `WHILE`, `FOR`, handlers, `EXECUTE IMMEDIATE`. Useful for
  maintenance or control-flow SQL that used to need a Python driver loop.

### Python Data Source API (4.0 added)
- Write a reader/writer (batch and streaming) in pure Python: subclass `pyspark.sql.datasource.DataSource`,
  register with `spark.dataSource.register`. 4.1: filter pushdown API and Arrow writer for streaming
  sources. 4.2: admission control and `Trigger.AvailableNow` for streaming readers; a type mismatch
  against the declared schema now fails (`DATA_SOURCE_RETURN_SCHEMA_MISMATCH`).
- **Rule:** fine for APIs and small sources; for throughput, return Arrow batches and implement filter
  pushdown, or the source becomes the bottleneck. A JVM DSv2 connector is still faster for big data.

### Python UDF execution
- 4.1: `@arrow_udf` / Arrow UDTF decorators that take and return PyArrow arrays with no pandas conversion;
  Python worker logging (`spark.sql.pyspark.worker.logging.enabled`, default false); Arrow IPC compression
  (`spark.sql.execution.arrow.compression.codec`, default `none`).
- 4.2: Arrow-optimised plain UDFs by default (above); pandas UDFs can take Arrow-backed columnar input
  directly from DSv2 scans (`spark.sql.execution.arrow.pythonUDF.columnarInput.enabled`, default true).
- Order of preference is unchanged: built-in function > Arrow/pandas UDF > plain Python UDF.

### transformWithState (4.0 added)
- Replaces `flatMapGroupsWithState` / `applyInPandasWithState`: value, list and map state, TTL, timers,
  schema evolution (needs `spark.sql.streaming.stateStore.encodingFormat=avro`). 4.1 adds a Row-based Python
  API and Connect support; 4.2 speeds up initial-state handoff to Python. Detail in streaming.md.

### Real-time mode (4.1 added)
- `Trigger.RealTime("5 minutes")` (Scala/Java, 4.1) and `.trigger(realTime="5 minutes")` (PySpark, 4.2).
  One long-running task per Kafka partition removes the micro-batch latency floor; the duration is a
  **checkpoint interval**, not a latency target (minimum `spark.sql.streaming.realTimeMode.minBatchDuration`
  = 5000ms).
- Released scope (4.1/4.2): **stateless** queries only (projections, filters, `explode`, unions,
  stream-static broadcast joins), Kafka source, Kafka/foreach/console sinks, `update` output mode, no
  `foreachBatch`, no AQE. Needs at least one core per Kafka partition, all held for the whole batch, so run
  one RTM query per cluster. Kafka sink is at-least-once.
- Stateful RTM (dedup, aggregations, JVM transformWithState) is in the `master` docs for **4.3.0, which is
  unreleased** as of Oct 2026.

### Spark Declarative Pipelines (4.1 added)
- Define streaming tables, materialized views and temporary views in `.py` (`pyspark.pipelines`) or `.sql`
  files plus a `spark-pipeline.yml` spec; Spark resolves the dependency graph, runs flows in parallel,
  manages checkpoints (`storage:` in the spec) and retries (`spark.sql.pipelines.maxFlowRetryAttempts`,
  default 2).
- CLI: `spark-pipelines init | run | dry-run`; `run --full-refresh a,b` or `--full-refresh-all`; built on
  `spark-submit`, so every cluster manager works. Install with `pip install pyspark[pipelines]`.
- 4.2 adds **Auto CDC (SCD type 1)** flows, Python and Connect APIs.
- It is the OSS core of Databricks Lakeflow Declarative Pipelines (formerly DLT). Not verified on the OSS
  docs: data-quality expectations, SCD type 2, and incremental (non-full) refresh of materialized views.
  Treat those as Databricks-only until the OSS guide lists them.

## 3. Other changes worth a line
- 4.0: SQL pipe syntax (`FROM t |> WHERE … |> AGGREGATE …`), structured JSON logging, state data source
  reader, PySpark UDF profiler (`spark.sql.pyspark.udf.profiler`).
- 4.1: RocksDB state store memory integrated with the unified memory manager; automatic snapshot repair and
  row checksums for state.
- 4.2: stream-stream join state format V4; non-outer stream-stream joins in update mode; `CHANGES` clause
  for CDC queries on DSv2 tables; NEAREST BY top-K join; metric views; DSv2 transactions.

## Sources
- https://spark.apache.org/news/index.html (release dates)
- https://spark.apache.org/releases/spark-release-4-0-0.html
- https://spark.apache.org/releases/spark-release-4.1.0.html
- https://spark.apache.org/releases/spark-release-4-2-0.html
- https://spark.apache.org/docs/latest/core-migration-guide.html
- https://spark.apache.org/docs/latest/sql-migration-guide.html
- https://spark.apache.org/docs/latest/api/python/migration_guide/pyspark_upgrade.html
- https://spark.apache.org/docs/4.2.0/configuration.html (and /docs/3.5.6/, /4.0.0/, /4.1.0/: defaults diffed table to table)
- https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html
- https://apache.googlesource.com/spark/+show/master/docs/streaming/real-time-mode.md (master docs; stateful scope unreleased)
