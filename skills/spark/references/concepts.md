# Spark concepts: glossary, use cases, and when to use it

Plain-English definitions of the terms that come up when working with Apache Spark 3.5 / 4.x. Each entry says
what the thing is and why it matters. Defaults and version notes were checked against the 4.2.0 docs; sources
are at the end. For tuning detail, follow the links back to the other reference files.

## Core architecture

- **Driver.** The process that runs your `main()` / notebook code, builds the query plan, and schedules tasks.
  Anything you `collect()`, `toPandas()` or broadcast passes through it, which is why driver OOM is a classic
  failure.
- **SparkSession.** The entry point for DataFrame and SQL work since Spark 2.0 (`spark` in shells and notebooks).
  It wraps the older **SparkContext**, which is still the entry point for RDDs, broadcast variables and
  accumulators.
- **Executor.** A JVM process on a worker node (any machine in the cluster) that runs tasks and holds cached
  data and shuffle files. Each application (one driver plus its executors) gets its own executors, so two jobs
  submitted separately cannot see each other's cached data. In PySpark it also starts Python worker processes
  for Python UDFs.
- **Cluster manager.** The external service that hands out machines and containers: Spark standalone, Hadoop
  YARN, or Kubernetes. Spark asks it for executors; it does not schedule Spark tasks itself.
- **Deploy mode.** Where the driver runs. In *cluster* mode the driver runs inside the cluster (normal for
  scheduled jobs); in *client* mode it runs where you submitted from (normal for notebooks and shells).
- **Spark Connect.** A client-server mode (3.4+, first-class in 4.0) where a thin client sends unresolved query
  plans over gRPC and gets results back as Arrow batches. It isolates client crashes and versions from the
  cluster, but has no RDD API and no direct SparkContext access.
- **Dynamic allocation.** Lets an application add and remove executors as load changes
  (`spark.dynamicAllocation.enabled`, default false). Shuffle tracking (default true since 3.0) means it works
  without an external shuffle service. Graceful decommissioning (`spark.decommission.enabled`) moves shuffle and
  cache blocks off an executor before it goes away, which matters on spot instances.

## Execution model

- **Transformation.** An operation that defines a new dataset from an existing one, such as `filter`, `select`,
  `join` or `groupBy`. Nothing runs yet.
- **Action.** An operation that needs a result, such as `count`, `collect`, `show` or `write`. Actions trigger
  execution of all the transformations behind them.
- **Lazy evaluation.** Spark records transformations and only runs them when an action needs a result. This lets
  the optimiser see the whole query first, for example pushing a filter written last down into the file scan.
- **Lineage.** The recorded chain of transformations that produced a dataset. If a partition is lost, Spark
  recomputes it from lineage rather than relying on replicas, which is the "resilient" in RDD. Spark turns
  lineage into a DAG (directed acyclic graph) of steps and cuts it into stages at shuffle boundaries.
- **Job.** The work triggered by one action. One action can produce several jobs (for example, a schema
  inference pass plus the real read).
- **Stage.** A set of tasks that can run without moving data between machines. Stages are separated by
  shuffles, so a query with two `groupBy`s typically has at least three stages.
- **Task.** The smallest unit of work: one stage applied to one partition, run on one executor core. A stage
  over 800 partitions runs 800 tasks. A failed task is retried (`spark.task.maxFailures`, default 4); if an
  executor dies with shuffle output on it, Spark reruns the stage that produced it, which shows up as
  `FetchFailedException` and repeated stages.
- **Partition.** One chunk of a distributed dataset, processed by one task. Partition count sets parallelism:
  too few leaves cores idle, too many adds scheduling overhead.
- **Narrow vs wide dependency.** Narrow transformations (`select`, `filter`, `map`) need only one input
  partition per output partition and stay in a stage. Wide ones (`groupBy`, non-broadcast `join`, `distinct`,
  `orderBy`, `repartition`) need data from many partitions and force a shuffle.
- **Shuffle.** Redistributing data across the cluster so that rows with the same key end up in the same
  partition. It costs disk writes, serialisation and network, and is usually the most expensive thing in a job.
  The number of output partitions is `spark.sql.shuffle.partitions` (default 200), which AQE then coalesces.
- **Spill.** When a task's in-memory data for sorting, aggregating or joining does not fit in execution memory,
  Spark writes it to local disk and reads it back. Some spill is survivable; lots of it means partitions are too
  big.
- **Data skew.** A few keys own most of the rows, so a few tasks take far longer than the rest and the stage
  waits for them. Example: 40% of orders have `customer_id = NULL`. Fixes are in skew-and-joins.md.
- **Speculative execution.** Launching a second copy of a slow task on another executor and keeping whichever
  finishes first (`spark.speculation`, default false). It helps with a bad machine, not with skew, because the
  copy has the same amount of data.

## Data abstractions and APIs

- **RDD (Resilient Distributed Dataset).** Spark's original low-level API: a partitioned collection of
  arbitrary objects with functional operations. The optimiser cannot see inside RDD lambdas, so prefer
  DataFrames unless you need full control.
- **DataFrame.** A distributed table with named, typed columns, like a SQL table or a pandas DataFrame. All
  DataFrame code goes through the Catalyst optimiser, so the Python, Scala, Java and SQL versions of a query run
  the same plan.
- **Dataset.** A typed DataFrame for Scala and Java (`Dataset[Order]`), giving compile-time types and lambdas
  over objects. Python and R have no Dataset API; in Scala a DataFrame is just `Dataset[Row]`.
- **UDF (user-defined function).** Your own function applied to columns. Python UDFs ship rows to a Python
  process one at a time and block optimisation, so use built-in functions when one exists. A **pandas UDF**
  receives whole batches via Apache Arrow and is usually many times faster than a plain Python UDF.
- **Pandas API on Spark.** A pandas-compatible API that runs on Spark (formerly the Koalas project, merged in
  3.2). Handy for porting pandas code, but not every pandas operation scales well.
- **Broadcast variable.** A read-only value copied once to every executor instead of shipped with each task.
  Example: a 50 MB lookup dictionary used inside a UDF. Broadcast joins use the same idea for a small table.
- **Accumulator.** A counter or sum that tasks add to and only the driver reads. Updates inside actions are
  applied exactly once; updates inside transformations can be double-counted when tasks retry.
- **Cache / persist.** Keeping a computed dataset in executor memory (and optionally disk) so later actions
  reuse it. It is lazy, costs memory that joins and sorts also need, and should be released with `unpersist()`.
  The storage level sets where it lives (`MEMORY_ONLY`, `MEMORY_AND_DISK`, `DISK_ONLY`, `_2` for two copies);
  DataFrame `cache()` uses a memory-and-disk level, RDD `cache()` uses `MEMORY_ONLY`.
- **Checkpoint.** Writing a dataset to reliable storage and cutting its lineage. Useful in long iterative loops
  where the plan keeps growing. (Streaming has a separate "checkpoint location", described below.)

## SQL engine internals

- **Spark SQL and the Catalyst optimiser.** Spark SQL is the engine under all DataFrame, SQL and streaming
  code. Catalyst turns a query into a plan in steps: parsed, analysed (names and types resolved against the
  catalog), optimised logical plan (*what* to compute), then physical plan (*how*: join algorithms, where the
  `Exchange` shuffles go). `df.explain(mode="formatted")` shows it.
- **Predicate pushdown.** Moving filters into the data source so less data is read. Example:
  `WHERE event_date = '2026-09-30'` is checked against Parquet row-group statistics so whole blocks are skipped.
- **Column pruning.** Reading only the columns a query uses. With columnar formats like Parquet, selecting 5 of
  200 columns reads roughly 5 columns' worth of bytes.
- **Partition pruning.** Skipping whole table partitions (directories, or Iceberg partitions) that a filter rules
  out. Example: a table partitioned by day and filtered to one day reads one day.
- **Dynamic partition pruning (DPP).** Partition pruning decided at runtime from the other side of a join
  (default on since 3.0). Example: joining a huge fact table to a dimension filtered to "UK stores" only reads
  fact partitions for those stores.
- **Runtime bloom filter.** For a shuffle join where one side has a selective filter, Spark builds a compact
  bloom filter of its keys and applies it to the other side before the shuffle, so less data moves (key
  `spark.sql.optimizer.runtime.bloomFilter.enabled`, on by default in current versions).
- **Statistics and CBO.** Table and column statistics (row counts, sizes, distinct values) from
  `ANALYZE TABLE` help Spark pick join types and order. The cost-based optimiser that uses column stats for join
  reordering is off by default (`spark.sql.cbo.enabled`=false).
- **AQE (Adaptive Query Execution).** Re-plans the query at each shuffle using real data sizes (default on since
  3.2). It merges tiny partitions, switches joins to broadcast when a side turns out small, and splits skewed
  join partitions.
- **Broadcast hash join.** Copies the small side of a join to every executor so the big side never shuffles.
  Used automatically when a side is estimated at 10 MB or less, and the fastest join when it fits.
- **Sort-merge join.** Shuffles and sorts both sides by the join key, then merges them. The robust default for
  two large tables, because it can spill to disk.
- **Shuffle hash join.** Shuffles both sides and builds an in-memory hash table from the smaller side of each
  partition. Skips the sort, but needs that side to fit in memory per partition.
- **Storage Partitioned Join (SPJ).** A join with no shuffle at all, because both tables are already stored
  partitioned (for example bucketed) on the join key. Works with V2 sources such as Iceberg; settings are in
  iceberg-on-spark.md.
- **Join hints.** Comments in SQL or `df.hint(...)` that ask for a strategy: `BROADCAST`, `MERGE`,
  `SHUFFLE_HASH`, `SHUFFLE_REPLICATE_NL`. Spark may ignore a hint the join type cannot support, so check the plan.
- **Tungsten and whole-stage codegen.** Tungsten is Spark's compact binary row format and memory management.
  Whole-stage codegen compiles a chain of operators into one Java function per stage; the `*(n)` prefix in a plan
  marks operators that were fused this way.
- **ANSI mode.** SQL-standard behaviour for errors: invalid casts, overflow and divide-by-zero throw instead of
  returning NULL. On by default since 4.0 (off in 3.5), so upgrades can surface data bugs; use `try_cast` and
  other `try_*` functions where NULL is wanted.
- **Photon.** Databricks' native vectorised engine that replaces parts of Spark's execution on Databricks
  clusters and SQL warehouses. It is proprietary, not part of open-source Spark.

## Storage and IO

- **Data source API (V1 and V2).** How Spark reads and writes external systems. V2 sources (Iceberg, newer
  connectors) can report partitioning and accept pushed-down filters, which enables features like SPJ and
  row-level `MERGE`.
- **Parquet and ORC.** Columnar file formats with per-column compression and min/max statistics. They are the
  default choice for analytics because they enable column pruning and predicate pushdown.
- **Splittable vs unsplittable files.** Parquet, ORC and uncompressed CSV can be split across many tasks. A
  gzip-compressed CSV or JSON file cannot, so a 10 GB `.csv.gz` is read by one task. Splittable files are cut
  into read tasks of up to `spark.sql.files.maxPartitionBytes` (128 MB), which sets first-stage parallelism.
- **Small files problem.** Thousands of tiny files make reads slow (per-file open cost and metadata listing)
  and stress the catalog. Usually caused by over-partitioned tables or frequent streaming commits; fixed by
  compaction.
- **Table partitioning.** Laying out a table by column values, such as one folder per day, so filters skip data.
  Partition on low-cardinality columns you actually filter on; partitioning by `user_id` creates millions of tiny
  files.
- **Bucketing.** Pre-hashing a table into a fixed number of buckets by a key so joins and aggregations on that
  key can skip the shuffle. Hive-style bucketing in Spark is fragile; Iceberg's `bucket(n, col)` partition
  transform is the modern equivalent.
- **Catalog and metastore.** Where table names map to schemas and file locations: the Hive metastore, AWS Glue,
  Unity Catalog, or an Iceberg REST catalog. Extra catalogs are registered with `spark.sql.catalog.<name>`.
- **Open table formats (Iceberg, Delta Lake, Hudi).** A metadata layer over Parquet files that adds atomic
  commits, schema evolution, time travel and `MERGE`/`UPDATE`/`DELETE`. They matter on S3 because plain folders
  of files give no transactions and no safe concurrent writes.

## Streaming

- **Structured Streaming.** Spark's streaming engine, built on Spark SQL: you write a normal DataFrame query over
  an unbounded input and Spark runs it incrementally. The same code can often run as batch.
- **DStreams (Spark Streaming).** The older RDD-based streaming API. The docs call it a legacy project with no
  new updates; use Structured Streaming for new work.
- **Micro-batch.** The default execution mode: every trigger, Spark runs a small batch job over the new data.
  Latency is roughly 100 ms at best, usually seconds, with exactly-once guarantees.
- **Trigger.** When the next micro-batch runs: as soon as the last one finishes (default), on a fixed interval
  (`processingTime`), or `availableNow`, which processes all current data in rate-limited batches and then stops.
- **Continuous processing and real-time mode.** Lower-latency alternatives to micro-batch. Continuous
  processing (experimental, since 2.3) reaches about 1 ms but only at-least-once and only for map-like queries.
  Real-time mode (4.1+; Scala/Java in 4.1, PySpark from 4.2) targets sub-second latency and, for stateless
  queries on Kafka, single-digit milliseconds. Stateful support is not in a released version yet (as of 4.2.1).
- **Source and sink.** Where a stream reads from (Kafka, files, Iceberg tables, rate) and writes to (Kafka,
  files, tables, `foreachBatch`). Exactly-once needs a replayable source and an idempotent or transactional sink.
- **Checkpoint location.** A durable folder per streaming query that records offsets processed and operator
  state, so a restarted query resumes where it stopped. Never share one between queries.
- **Output mode.** What each trigger emits: `append` (only final rows), `update` (rows that changed), or
  `complete` (the whole result, aggregations only).
- **Event time and watermark.** Event time is when something happened, not when Spark saw it. A watermark
  (`withWatermark("ts", "10 minutes")`) says how late data may arrive; older state is dropped, which keeps state
  from growing forever.
- **Stateful operations and state store.** Aggregations, deduplication, stream-stream joins and
  `transformWithState` (4.0+) keep per-key state between batches. State lives in a state store; RocksDB is the
  usual choice for anything large.
- **foreachBatch.** Runs your own batch code on each micro-batch's DataFrame. It is the standard way to `MERGE`
  into a table or write to several sinks, and is at-least-once unless the write is idempotent.

## Deployment and operations

- **spark-submit.** The command-line launcher for packaged applications (a JAR or a Python file), with flags
  for master URL, deploy mode, resources and config.
- **Standalone, YARN, Kubernetes.** The three supported cluster managers. Standalone is Spark's own simple
  manager; YARN is Hadoop's resource manager (common on EMR); Kubernetes runs driver and executors as pods
  (generally available since 3.1). Mesos support was removed in 4.0.
- **Managed platforms.** Amazon EMR, AWS Glue, Google Dataproc, Azure HDInsight / Synapse and Databricks run
  Spark for you. They differ mainly in startup time, autoscaling, pricing, and extras such as Photon on
  Databricks.
- **Spark UI and History Server.** The web UI (port 4040 on the driver) shows jobs, stages, tasks, SQL plans,
  storage and executors while an app runs. The History Server shows the same views afterwards from event logs
  (`spark.eventLog.enabled`).
- **Spark Declarative Pipelines.** A 4.1 framework where you declare datasets and the queries that produce them,
  and Spark works out the dependency order, parallelism, checkpoints and retries. It is the open-source
  counterpart of Databricks' Lakeflow Declarative Pipelines (formerly DLT). Run with the `spark-pipelines`
  CLI; 4.2 adds Auto CDC (SCD type 1). Detail in spark-4x-changes.md.
- **SQL scripting.** Procedural SQL (`BEGIN … END`, variables, loops, handlers); GA and on by default from 4.1.
- **Python Data Source API.** Custom batch and streaming readers/writers written in Python (4.0+), with filter
  pushdown from 4.1.
- **MLlib.** Spark's machine-learning library: DataFrame-based pipelines for feature transforms and classic
  models (linear models, trees, clustering, ALS). Good for large tabular data; not a deep-learning framework.
- **GraphX and GraphFrames.** GraphX is Spark's RDD-based graph library (Scala only). GraphFrames is a separate
  package that offers graph algorithms on DataFrames and works from Python.

## Use cases

Spark earns its overhead when the data is too big or the work too parallel for one machine.

| Workload | Concrete example |
|---|---|
| Large batch ETL / ELT | Nightly job reads 2 TB of raw clickstream JSON from S3, cleans and deduplicates it, and writes partitioned Iceberg tables. |
| Incremental ingestion and CDC upserts | Every 5 minutes, read new Debezium change events from Kafka and `MERGE` them into an Iceberg `customers` table via `foreachBatch`. |
| Big joins and aggregations for reporting | Join 5 billion order lines to products and stores, then build daily revenue by region and category for the BI layer. |
| Streaming ETL at seconds-to-minutes latency | Parse IoT readings from Kafka, drop bad records, compute 1-minute windowed averages with a watermark, and write to a table and an alert topic. |
| Feature engineering for ML | Compute 90-day rolling purchase counts and recency features for 200 million users and write a feature table for training and batch scoring. |
| Batch model scoring | Score 500 million rows with a trained scikit-learn or XGBoost model inside a pandas UDF, spread across 100 cores. |
| Classic distributed ML on tabular data | Train an MLlib logistic regression or ALS recommender on data too large for one machine's memory. |
| Backfills and reprocessing | Recompute two years of a derived table after a logic fix, one month per run, without touching the serving system. |
| Lakehouse table maintenance | Run Iceberg `rewrite_data_files`, `expire_snapshots` and `rewrite_manifests` as scheduled Spark jobs. |
| Semi-structured data at scale | Parse nested JSON logs with `from_json` or the `VARIANT` type (4.0+), flatten them, and store as columnar tables. |
| Exploratory analysis on large data | Notebook queries over a 10 TB events table to size a new feature, where a single-node tool would run out of memory. |

## When to use / when not to use

| Situation | Verdict | Better alternative, and why |
|---|---|---|
| Data fits comfortably on one machine (up to roughly tens of GB, sometimes more) | Avoid | DuckDB, Polars or pandas. In-process engines skip cluster startup, shuffle and serialisation, and a laptop often finishes before a cluster has started. DuckDB and Polars' streaming engine also handle larger-than-memory data on one box. |
| Hundreds of GB to PB of batch transformation | Use | Spark is built for this: parallel reads, shuffles that spill, and recovery from failed tasks. |
| Joins of two very large tables | Use | Sort-merge joins, AQE skew handling and SPJ on Iceberg are Spark strengths. |
| Point lookups or serving rows to an app with millisecond latency | Avoid | An OLTP database (Postgres, MySQL, DynamoDB), a cache (Redis), or OpenSearch. Spark has no indexes for single-row access and every query plans and schedules tasks. Use Spark to build the data, then load it into the serving store. |
| Transactional writes (many small inserts or updates per second) | Avoid | Postgres, MySQL or DynamoDB. Spark writes in batches; table formats handle commits per job, not per row. |
| Event-at-a-time streaming, sub-second latency, complex event processing | Usually avoid | Apache Flink or Kafka Streams, which process one record at a time with millisecond latency and mature stateful APIs. Spark's real-time mode (4.1+) narrows the gap, but only for stateless Kafka-to-Kafka queries so far (Scala in 4.1, Python from 4.2). |
| Streaming ETL where seconds to minutes of latency is fine | Use | Micro-batch Structured Streaming with exactly-once sinks, sharing code with batch jobs. |
| Interactive BI dashboards with many concurrent users | Avoid on a plain Spark cluster | A warehouse: Snowflake, Databricks SQL (Spark plus Photon behind a warehouse front end with caching and concurrency handling), BigQuery, or Trino / ClickHouse. Plain Spark is tuned for throughput, not hundreds of small concurrent queries. |
| Ad-hoc SQL across several live systems without moving data | Usually avoid | Trino, which is built for federated interactive queries. Spark can read many sources but is slower to start and aimed at heavier jobs. |
| Full-text search, relevance ranking, faceted filtering | Avoid | OpenSearch / Elasticsearch, which have inverted indexes. Spark would scan everything. |
| Training deep-learning models | Usually avoid | PyTorch / TensorFlow with their own distributed training, or Ray. Spark is fine for preparing the data and for batch inference. |
| Classic ML on large tabular data | Use | MLlib, or pandas UDFs wrapping scikit-learn / XGBoost for scoring. |
| Graph traversal queries ("friends of friends within 3 hops", live) | Avoid | A graph database such as Neo4j. Use GraphFrames only for whole-graph batch algorithms like PageRank or connected components. |
| Small scheduled SQL transformations already in a warehouse | Avoid | dbt or native SQL in the warehouse. Adding Spark adds a second engine and data movement for no gain. |
| Simple file copies or format conversion of a few files | Avoid | A script, AWS Lambda, or DuckDB `COPY`. A cluster is overkill. |
| Mixed Python logic over large data (cleaning, parsing, enrichment) | Use, with care | Spark with built-in functions first and pandas UDFs second. Row-at-a-time Python UDFs throw away much of the speed. |

Rule of thumb: start with the simplest tool that fits on one machine, and move to Spark when data size, a
shared lakehouse, or a need for fault-tolerant parallelism forces it.

## Sources

Apache Spark docs (latest = 4.2.0, read Oct 2026):
- https://spark.apache.org/docs/latest/ (overview, list of components)
- https://spark.apache.org/docs/latest/cluster-overview.html (glossary, cluster managers, deploy modes)
- https://spark.apache.org/docs/latest/rdd-programming-guide.html (RDDs, laziness, shuffle, broadcast, accumulators, storage levels)
- https://spark.apache.org/docs/latest/sql-programming-guide.html (DataFrame and Dataset, language support)
- https://spark.apache.org/docs/latest/sql-performance-tuning.html (AQE, join hints, SPJ)
- https://spark.apache.org/docs/latest/configuration.html (defaults for dynamic allocation, shuffle tracking, speculation, DPP, CBO, runtime bloom filter)
- https://spark.apache.org/docs/latest/spark-connect-overview.html
- https://spark.apache.org/docs/latest/streaming-programming-guide.html (DStreams legacy note)
- https://spark.apache.org/docs/latest/streaming/apis-on-dataframes-and-datasets.html
- https://spark.apache.org/releases/spark-release-4-0-0.html (Mesos removed, ANSI default, VARIANT, transformWithState, Python data sources)
- https://spark.apache.org/releases/spark-release-4.1.0.html (Declarative Pipelines, real-time mode, VARIANT GA)
- https://spark.apache.org/releases/spark-release-4-2-0.html (real-time mode in PySpark, Auto CDC in SDP)

Alternatives:
- https://duckdb.org/why_duckdb (in-process analytical database)
- https://docs.pola.rs/user-guide/concepts/streaming/ (Polars streaming engine for larger-than-memory data)
- https://flink.apache.org/what-is-flink/flink-architecture/ (local state, low latency, exactly-once state)
- https://kafka.apache.org/43/streams/core-concepts/ (one-record-at-a-time processing, millisecond latency)
