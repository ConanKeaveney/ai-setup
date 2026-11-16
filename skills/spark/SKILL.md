---
name: spark
description: Reference for Apache Spark 3.5 / 4.x (PySpark, Scala, Java; OSS Spark on AWS and Databricks), weighted towards performance tuning of batch and streaming jobs on an Iceberg lakehouse. Load whenever the work touches a Spark job, its config, its plan or its Spark UI. Triggers: "spark", "pyspark", "straggler", "skew", "salting", "shuffle", "memoryOverhead", "exit code 137", "AQE", "broadcast join", "storage partitioned join", "spark UI", "structured streaming", "watermark", "RocksDB", "foreachBatch", "spark connect", "celeborn", "write-audit-publish", "sparkmeasure".
---

# Apache Spark (3.5 / 4.x) - tuning-first reference

Use this when writing, reviewing, or (above all) speeding up a Spark job. Defaults below were read from the
official config tables for 3.5, 4.0, 4.1 and 4.2 (latest docs are 4.2.0; 4.2.1 shipped 27 Oct 2026), and the
snippets were run on local PySpark 4.0.1 with Iceberg 1.10.0. If a value differs between versions, the version is given.

Deeper material:
- [references/config-reference.md](references/config-reference.md) covers every tuning key with its verified default and version, plus executor sizing.
- [references/debugging-oom.md](references/debugging-oom.md) walks through the Spark UI field by field, the memory model, and OOM / lost-executor triage by error message.
- [references/skew-and-joins.md](references/skew-and-joins.md) covers join selection, AQE skew handling, salting, and Storage Partitioned Join.
- [references/streaming.md](references/streaming.md) covers Structured Streaming triggers, state, RocksDB, watermarks, Kafka, monitoring, and what changed in 4.x.
- [references/iceberg-on-spark.md](references/iceberg-on-spark.md) covers the Spark side of Iceberg: catalogs, write distribution, file sizing, SPJ, streaming writes, and maintenance procedures. For table-format design, load the `iceberg` skill.
- [references/concepts.md](references/concepts.md) is a plain-English glossary of about 70 Spark terms, typical use cases with examples, and the full when-to-use table with alternatives.
- [references/spark-4x-changes.md](references/spark-4x-changes.md) lists what changed in 4.0, 4.1 and 4.2 (defaults, upgrade breakers, Connect, VARIANT, real-time mode, Declarative Pipelines).
- [references/cluster-sizing-aws.md](references/cluster-sizing-aws.md) covers executor sizing on EMR/EKS/K8s, Spot and decommissioning, Graviton, remote shuffle (Celeborn), and S3 committers.
- [references/field-results.md](references/field-results.md) lists measured production tuning results (ByteDance, Slack, Uber, Netflix, Pinterest, Zhihu) and the rule each supports.
- [references/testing.md](references/testing.md) covers `pyspark.testing`, chispa, session fixtures, and plan/metric regression tests.
- [references/job-design.md](references/job-design.md) covers designing jobs: layers, idempotent writes, incremental vs full, data quality, code layout, backfills, observability, and what to read.
- [references/benchmarking.md](references/benchmarking.md) covers fair engine/platform and table-format benchmarks, job regression harnesses, proving a migrated job's output is identical, and data-quality frameworks, with tool status.

## When to use it / when not to

Spark pays off when data is too big, or the work too parallel, for one machine. The full table with reasons is
in [references/concepts.md](references/concepts.md).

| Situation | Verdict | Use instead |
|---|---|---|
| Batch ETL over hundreds of GB to PB; big-big joins | Use | |
| Streaming ETL where seconds to minutes of latency is fine | Use | |
| Feature engineering, batch scoring, classic ML on large tabular data | Use | |
| Data fits on one machine | Avoid | DuckDB, Polars, pandas |
| Millisecond point lookups or serving an app | Avoid | Postgres / DynamoDB / Redis, or OpenSearch for search |
| Many small transactional writes | Avoid | An OLTP database |
| Sub-second, event-at-a-time streaming | Usually avoid | Flink, Kafka Streams (real-time mode, 4.1+, covers stateless Kafka queries only) |
| BI dashboards with many concurrent users | Avoid on a plain cluster | Snowflake, Databricks SQL, Trino, ClickHouse |
| Deep-learning training | Usually avoid | PyTorch / Ray; keep Spark for data prep and batch inference |
| Small SQL transforms already in a warehouse | Avoid | dbt or native warehouse SQL |

## 1. Mental model (60 seconds)

- **Driver** plans the query, schedules tasks, and holds anything you `collect()`, broadcast, or keep in Python
  driver memory. **Executors** are JVMs (plus Python workers for PySpark UDFs) that run tasks and hold cached
  blocks and shuffle files.
- **Action → job → stages → tasks.** Each action (`count`, `write`, `collect`) is one or more jobs. A job splits
  into stages at **shuffle boundaries**. A stage runs one task per partition, and one task uses one core
  (`spark.task.cpus`=1).
- **Narrow** transformations (`select`, `filter`, `withColumn`, `mapPartitions`) stay inside a stage. **Wide**
  ones (`groupBy`, `join` without broadcast, `distinct`, `repartition`, `orderBy`, windows with `partitionBy`)
  add an `Exchange`, which means shuffle write, network, and shuffle read.
- **Catalyst** goes from the analysed logical plan, through rule-based optimisation (predicate and projection
  pushdown, constant folding), to a physical plan, choosing joins from statistics. **AQE** (on by default
  since 3.2.0) re-plans at each shuffle boundary using real sizes. **Tungsten** gives off-heap-capable binary row
  format and whole-stage codegen (the `*(n)` prefix in plans).
- DataFrame/SQL code goes through Catalyst. RDD code, Python UDFs and `Dataset.map` lambdas are opaque to
  it: no pushdown, and Python UDFs pay serialisation to a Python worker.
- **4.x changes that bite** (full list in [references/spark-4x-changes.md](references/spark-4x-changes.md)):
  - 4.0: ANSI mode on (`spark.sql.ansi.enabled`=true, false in 3.5), so bad casts and overflow **throw**
    instead of returning NULL. JDK 17+ and Scala 2.13 required. Spark Connect first-class (`spark.api.mode`).
  - 4.1: SPJ on by default (`spark.sql.sources.v2.bucketing.enabled`=true); S3A magic committer for plain
    files on S3; Python 3.10+.
  - 4.2: Arrow on by default for `toPandas`, plain Python UDFs and UDTFs; shuffle checksums re-run (or fail)
    stages whose retried non-deterministic output changed.

## 2. Diagnose a slow job (do this before touching any config)

Follow these steps in order, and stop when you find the dominant cost. The order follows Databricks' Spark UI
guide (jobs timeline, then longest stage, then skew/spill, then I/O, then everything else). Field meanings
are in [references/debugging-oom.md](references/debugging-oom.md).

1. **Jobs tab, event timeline.** Look for:
   - red failed jobs or removed executors (go to the OOM section);
   - **gaps of a minute or more** between jobs, which means driver-side work: Python code, `collect`, planning
     over huge file listings, or Iceberg/Glue metadata;
   - many tiny jobs, which usually means a loop of actions or `count()` used for debugging.
2. **SQL / DataFrame tab.** Open the slow query and read the plan graph: the operator with the largest time
   or rows; row counts that **explode** after a join or `explode`; `Exchange` sizes; whether the scan pruned
   files ("number of files read" vs table size).

   In the final plan, `AQEShuffleRead coalesced` / `coalesced and skewed` and `SortMergeJoin(skew=true)`
   confirm AQE acted (verified on 4.0.1).
3. **Stages tab, sorted by duration.** Pick the longest stage, then check:
   - **Task count vs cores.** Fewer tasks than total executor cores means idle cores. Thousands of
     sub-second tasks means scheduling overhead.
4. **Summary metrics for that stage.** Compare the 75th percentile with the max:
   - **Skew:** max duration more than 50% above the 75th percentile (Databricks' heuristic), or one task's
     shuffle-read size far above the median. See section 5.
   - **Spill:** any non-zero *Spill (Memory)* / *Spill (Disk)*. Partitions are too big for execution memory.
     Use more and smaller partitions, or more memory per core.
   - **GC time** above about 10% of task time, which means memory pressure or too many objects (often Python UDFs
     or a big cache). This 10% is a common rule of thumb, not an official threshold.
   - **Shuffle read fetch wait / blocked time** high, which points at network or remote shuffle, or lost
     executors.
   - **Scheduler delay / deserialization** high, which means tasks are too small or the closures are too large.
5. **I/O bound?** Input size per task far above about 128 MB, or millions of tiny files (Databricks flags reads
   of "tens of thousands of files or more" and files under about 8 MB). If so, fix file layout (section 6) and
   compaction, not compute.
6. **Not I/O and no skew?** Check for Python UDFs (swap for built-ins or `pandas_udf`), Cartesian or
   nested-loop joins (`BroadcastNestedLoopJoin`, `CartesianProduct`), `explode` blowups, and an uncached
   DataFrame recomputed by several actions.
7. **Executors tab.** Look at per-executor GC, failed tasks, storage memory used, and whether the executor
   count matches what you asked for (dynamic allocation or capacity).
8. Change **one** thing, re-run, and compare the same stage's metrics.

## 3. Tuning cheat-sheet: symptom → cause → fix

| Symptom (where you see it) | Likely cause | Fix (real keys, sensible values) |
|---|---|---|
| One or a few tasks run 10x longer; max ≫ p75 (stage summary) | Key skew in join/agg | AQE skew join is on by default (`spark.sql.adaptive.skewJoin.enabled`=true; split threshold = `skewedPartitionFactor` 5.0 × median **and** > `skewedPartitionThresholdInBytes` 256MB). Lower the threshold (e.g. 128MB) to catch more. Broadcast the small side. Salt the hot key. Filter null/sentinel keys first. |
| Obvious skew but no `skew=true` in the final plan, with > 2000 shuffle partitions | Map status records block sizes as an average above 2000 partitions, so AQE cannot see the hot partition | `spark.shuffle.accurateBlockSkewedFactor` (3.3+, default -1 = off) = `skewedPartitionFactor` (5.0). See [references/skew-and-joins.md](references/skew-and-joins.md). |
| Spill (Memory/Disk) > 0 | Shuffle partitions too large for execution memory | Raise `spark.sql.shuffle.partitions` (200 default) or `spark.sql.adaptive.coalescePartitions.initialPartitionNum`, and lower `spark.sql.adaptive.advisoryPartitionSizeInBytes` (64MB default). Or give more memory per core (fewer `spark.executor.cores`, bigger `spark.executor.memory`). |
| Thousands of tiny tasks after shuffle | Too many shuffle partitions, or AQE favouring parallelism | `spark.sql.adaptive.coalescePartitions.parallelismFirst=false`, which makes AQE honour the 64MB advisory size. The docs recommend this on busy clusters. |
| Few huge tasks reading files | Big unsplittable files (gzip CSV/JSON) or `maxPartitionBytes` too high | Splittable formats (Parquet, ORC). `spark.sql.files.maxPartitionBytes` (128MB). Repartition after read. |
| Slow scan of many small files | Small files; per-file open cost | Compact (Iceberg `rewrite_data_files`). Raise `spark.sql.files.openCostInBytes` (4MB) to pack more per task. |
| SortMergeJoin where one side is small | Stats missing or above 10MB | `broadcast(df)` hint. Raise `spark.sql.autoBroadcastJoinThreshold` (10MB) to 50–200MB if driver/executor memory allows. `ANALYZE TABLE … COMPUTE STATISTICS`. |
| `Cannot broadcast the table that is larger than 8GB` / driver OOM on broadcast | Broadcast of a big or misestimated relation | Remove the hint. Set `spark.sql.autoBroadcastJoinThreshold=-1` for that query. Check stats. |
| `Container killed … exceeding memory limits` / K8s `OOMKilled` (137) | Off-heap use beyond overhead: Python workers, Arrow, netty, RocksDB | Raise `spark.executor.memoryOverhead` (default max(384m, 0.10×heap); 0.40 for K8s non-JVM jobs). Set `spark.executor.pyspark.memory` for PySpark. |
| `java.lang.OutOfMemoryError` on executor | Partition too big, wide rows, big `collect_list`, explode | More and smaller partitions. Avoid giant arrays per key. Fewer cores per executor. See [references/debugging-oom.md](references/debugging-oom.md). |
| Driver OOM / `maxResultSize` exceeded | `collect()`/`toPandas()` of large data; huge plans; too many tasks or files | Write to storage instead. `spark.driver.maxResultSize` (1g). Raise `spark.driver.memory`. Avoid loops that grow plans (checkpoint). |
| High GC time | Too many objects in heap; cached deserialized data; UDF objects | Use built-ins, not UDFs. Cache less or use `MEMORY_AND_DISK`. G1GC; consider smaller executors (about 4–5 cores, ≤ about 32–40 GB heap; rule of thumb). |
| `FetchFailedException` / executor lost mid-shuffle | Executor died (OOM, spot loss) or shuffle service missing | Fix the OOM first. On spot/K8s: `spark.decommission.enabled` + `spark.storage.decommission.enabled` + `…shuffleBlocks.enabled`. External shuffle service on YARN. |
| Python UDF stage slow | Row-at-a-time pickling | Built-in functions. Else `pandas_udf` / `mapInPandas` (Arrow). 4.2: `spark.sql.execution.pythonUDF.arrow.enabled` defaults to true (false in 3.5 to 4.1). |
| `toPandas()` / `createDataFrame(pandas)` slow | Arrow off: `spark.sql.execution.arrow.pyspark.enabled` is false before 4.2 | Set it to `true` (true by default in 4.2). Keep the result small regardless. |
| Same input recomputed per action | Lineage reused without cache | `df.persist()` before the reuse, `unpersist()` after. Or write an intermediate table. |
| Job never uses all executors | Too few input partitions or dynamic allocation ramp-up | `repartition(n)` early. `spark.sql.files.minPartitionNum`. Check `spark.dynamicAllocation.*`. |

## 4. Join strategies

Selection order for equi-joins: hints first. Without hints, Spark picks **BroadcastHash** if one side's
estimated size is ≤ `spark.sql.autoBroadcastJoinThreshold` (10MB), then **ShuffledHash** or **SortMerge**
depending on stats and `spark.sql.join.preferSortMergeJoin`. Non-equi joins fall back to
**BroadcastNestedLoop** or **Cartesian**, both of which are expensive.

- **Broadcast hash join:** no shuffle of the big side. The small side is built on the driver and shipped to
  every executor, so it costs driver memory and network. There is a hard 8 GB cap. AQE can convert SMJ to
  broadcast at runtime when a side turns out small (`spark.sql.adaptive.autoBroadcastJoinThreshold`, which
  defaults to the static threshold).
- **Shuffle hash join:** both sides are shuffled and the smaller per partition is hashed. There is no sort,
  but the build side must fit in memory. AQE converts SMJ to SHJ when every post-shuffle partition is
  ≤ `spark.sql.adaptive.maxShuffledHashJoinLocalMapThreshold` (0 by default, so off).
- **Sort-merge join:** both sides are shuffled and sorted. It is the most robust for big-big joins and can
  spill. AQE skew splitting applies here.
- **Storage Partitioned Join (SPJ):** if both sides are V2 tables (Iceberg) partitioned compatibly on the join
  key, Spark skips the shuffle entirely. Verified locally: 2 → 0 `Exchange`s. Configs and requirements are in
  [references/skew-and-joins.md](references/skew-and-joins.md).
- **Hints:** `BROADCAST` > `MERGE` > `SHUFFLE_HASH` > `SHUFFLE_REPLICATE_NL` (priority when both sides
  are hinted). Hints are not guaranteed, since some join types cannot support them.

## 5. Skew playbook (in order of effort)

1. **Confirm it:** run `df.groupBy(key).count().orderBy(desc("count"))`, and check per-partition rows with
   `groupBy(spark_partition_id())`.
2. **Filter junk keys** (NULL, `''`, `-1`, "unknown") before the join or aggregation, and union them back if
   needed.
3. **Broadcast** the other side if it is small enough. Skew does not matter for broadcast joins.
4. **Let AQE split it.** It is on by default for SMJ. Lower `skewedPartitionThresholdInBytes` and
   `advisoryPartitionSizeInBytes` if the hot partition sits under 256MB but is still dominant. Check the plan
   for `skew=true`; with more than 2000 shuffle partitions also set `spark.shuffle.accurateBlockSkewedFactor`
   (section 3). AQE only splits a side it can safely split: for a LEFT OUTER join, skew on the left is split but skew
   on the right is not, and a FULL OUTER join is not split at all (verified on 4.0.1).
5. **Salt.** For aggregations, run a two-phase aggregate on `(key, salt)` and then `key`. For joins, add a random
   salt on the big side and explode the small side over all salts. Both are in [references/skew-and-joins.md](references/skew-and-joins.md) section 4, verified.
6. **Isolate hot keys.** Join the top-N keys separately via broadcast, the rest normally, then union.
7. For writes skewed by partition value, use `REBALANCE` (AQE splits skewed rebalance partitions:
   `spark.sql.adaptive.optimizeSkewsInRebalancePartitions.enabled`=true).

## 6. Partitioning and file sizing

- **Three different "partitions":** input splits (`spark.sql.files.maxPartitionBytes`=128MB,
  `openCostInBytes`=4MB), shuffle partitions (`spark.sql.shuffle.partitions`=200, then AQE coalesces), and
  output/table partitions (directory or Iceberg partition spec). Tune each separately.
- **Targets:** about 100–200 MB of shuffle data per task. Set a total task count of at least 2–3× total cores
  (official tuning guide: 2–3 tasks per core). With AQE, set a high initial partition number and let it
  coalesce.
- `repartition(n[, cols])` is a full shuffle and gives even sizes. `coalesce(n)` has no shuffle and merges
  partitions, but it **reduces upstream parallelism** too. Never `coalesce(1)` a large result.
- **`REBALANCE` hint / `df.hint("rebalance")`** is AQE-aware: it evens out output partition sizes and splits
  skew. Prefer it to `repartition` before writes.
- **Output files:** aim for about 128 MB to 1 GB Parquet files. Iceberg's default `write.target-file-size-bytes` is 512 MB.
  `maxRecordsPerFile` (`spark.sql.files.maxRecordsPerFile`, 0 = unlimited) caps rows per file.
- **Dynamic partition overwrite:** `spark.sql.sources.partitionOverwriteMode=dynamic` (default STATIC
  replaces the whole table on `insertInto … overwrite`). For Iceberg, prefer `overwritePartitions()` or
  `MERGE`.
- Partition tables on low-cardinality columns that are actually filtered on. High-cardinality partitioning
  causes the small-file problem.

## 7. AQE essentials (default on since 3.2.0)

AQE does three things, and all three are on by default:
- coalesces post-shuffle partitions toward `advisoryPartitionSizeInBytes` (64MB);
- converts joins to broadcast or shuffle-hash using runtime sizes;
- splits skewed SMJ partitions.

What to tune:
- **`parallelismFirst`=true (default)** ignores the 64MB target and only respects `minPartitionSize`
  (1MB), so you often get many small tasks. Set it to `false` for batch ETL on shared clusters.
- Raise `advisoryPartitionSizeInBytes` (128–256MB) when tasks are too short. Lower it when tasks spill.
- AQE cannot fix the **first** stage (scan) or a skewed **aggregation**. It only acts at shuffle boundaries
  and skew-splits joins and rebalances.
- Look at the **final** plan (SQL tab, or `explain` after the action). The `isFinalPlan=false` plan shown by
  `explain()` before execution is not what ran.

## 8. Caching

- `df.cache()` = `persist()` with **MEMORY_AND_DISK_DESER** in PySpark (since 3.0) and MEMORY_AND_DISK in Scala.
  It is lazy, so the first action materialises it. Check the Storage tab for the fraction cached.
- Cache only when a DataFrame is reused by two or more actions **and** recomputing it is expensive. Always
  `unpersist()`.
- Unified memory: (heap − 300 MB) × `spark.memory.fraction` (0.6). Storage keeps an eviction-immune
  `spark.memory.storageFraction` (0.5) of that. A big cache squeezes execution memory and causes spill.
- `localCheckpoint()` / `checkpoint()` truncate lineage in iterative loops, because huge plans slow the driver.
  Writing an intermediate Iceberg table is often better and debuggable.
- Do not cache just before a single write. Do not cache the raw scan when only a filtered subset is reused.

## 9. Structured Streaming essentials

Full detail is in [references/streaming.md](references/streaming.md).
- **Micro-batch engine.** Each trigger is a small batch job. Triggers are `processingTime`, `availableNow`
  (3.3+; replaces deprecated `once`), and continuous (experimental, at-least-once). 4.1 adds real-time mode.
- **Checkpoint per query, durable storage.** Never share a checkpoint between queries. Changing the query shape
  (adding stateful ops, or changing keys) can make an old checkpoint unusable.
- **Watermark** (`withWatermark(col, "10 minutes")`) bounds state for aggregations, dedup and stream-stream
  joins. Without it, state grows forever.
- **State store:** use RocksDB for anything non-trivial:
  `spark.sql.streaming.stateStore.providerClass=org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider`,
  plus `…rocksdb.changelogCheckpointing.enabled=true` (default false). RocksDB memory is native, so budget it in
  memoryOverhead, or bound it with `…rocksdb.boundedMemoryUsage`.
- `spark.sql.shuffle.partitions`, the state store provider class and `multipleWatermarkPolicy` are **frozen
  in the checkpoint at first run**. Changing them later means starting from a new checkpoint, so set them
  before the first start.
- **`foreachBatch`** for MERGE/upserts and multi-sink writes. It is at-least-once unless you dedupe on
  `batchId`.
- Rate-limit: Kafka `maxOffsetsPerTrigger`; file `maxFilesPerTrigger`/`maxBytesPerTrigger`; Iceberg
  `streaming-max-files-per-micro-batch`.
- Monitor `query.lastProgress`: `inputRowsPerSecond` vs `processedRowsPerSecond`, `durationMs`,
  `stateOperators[].numRowsTotal`, and watermark lag.

## 10. Verified snippets (PySpark 4.0.1, local)

```python
from pyspark.sql import functions as F
from pyspark.sql.functions import broadcast

# Skew check: rows per key and rows per partition after a hash repartition
df.groupBy("key").count().orderBy(F.desc("count")).show(10)
df.repartition(200, "key").groupBy(F.spark_partition_id().alias("pid")).count() \
  .orderBy(F.desc("count")).show(5)

# Broadcast join + read the plan (formatted mode exists since 3.0)
j = facts.join(broadcast(dims), "key")
j.explain(mode="formatted")            # expect BroadcastHashJoin / BroadcastExchange

# SQL hints
spark.sql("SELECT /*+ SHUFFLE_HASH(d) */ * FROM facts f JOIN dims d ON f.key = d.key")
spark.sql("SELECT /*+ REBALANCE(key) */ * FROM facts")   # AQE-aware even output

# Salted aggregation and salted join: references/skew-and-joins.md section 4 (verified)

# Vectorised UDF instead of a row-at-a-time Python UDF
import pandas as pd
@F.pandas_udf("double")
def plus_one(s: pd.Series) -> pd.Series:
    return s + 1.0
```

```python
# Session settings for a batch ETL job on a shared cluster (all keys verified)
spark.conf.set("spark.sql.adaptive.coalescePartitions.parallelismFirst", "false")
spark.conf.set("spark.sql.adaptive.advisoryPartitionSizeInBytes", "128m")
spark.conf.set("spark.sql.shuffle.partitions", "800")      # AQE coalesces down from here
spark.conf.set("spark.sql.autoBroadcastJoinThreshold", str(64 * 1024 * 1024))
```

## 11. Spark + Iceberg (the team's stack)

Detail is in [references/iceberg-on-spark.md](references/iceberg-on-spark.md); load the `iceberg` skill for format design.
- **Session setup:** set `spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`
  (needed for `CALL`, `MERGE` and the DDL extensions). Then configure the catalog with
  `spark.sql.catalog.<name>=org.apache.iceberg.spark.SparkCatalog` and `….type=glue` (or `rest`), with
  `….io-impl=org.apache.iceberg.aws.s3.S3FileIO` on AWS.
- **Write distribution** (`write.distribution-mode`): `hash` is the default since Iceberg 1.2.0 (shuffle by
  partition), and `range` applies if the table has a sort order. AQE then sizes the write tasks using
  `advisoryPartitionSizeInBytes`. That size is **in-memory shuffle bytes, not file bytes**. Parquet compresses
  far smaller, so set the advisory size (or `spark.sql.iceberg.advisory-partition-size`) **above** the file
  target to get files near `write.target-file-size-bytes` (512 MB).
- **SPJ for big-big joins on the same bucketed key.** It needs `spark.sql.sources.v2.bucketing.enabled=true`
  (default **false** in 3.5 and 4.0, true from 4.1), `spark.sql.iceberg.planning.preserve-data-grouping=true`,
  `spark.sql.sources.v2.bucketing.pushPartValues.enabled=true`, and often
  `spark.sql.requireAllClusterKeysForCoPartition=false`.
- **Row-level ops:** `write.delete.mode` / `write.update.mode` / `write.merge.mode` all default to
  `copy-on-write`. Use `merge-on-read` for frequent small MERGEs, then compact.
- **Streaming into Iceberg:** a trigger of 1 minute or more (Iceberg's guidance). Use `fanout-enabled=true` to
  avoid a sort in streaming writes. Schedule `rewrite_data_files`, `expire_snapshots` (default 5 days) and
  `rewrite_manifests`.

## 12. AI-assisted diagnosis

An agent is only as good as the runtime evidence it sees. The measured wins (Expedia, Datadog) all give it the
physical plan, stage/task metrics and the source code together, plus a checklist of patterns to look for, and
keep an engineer approving every change.

- **Feed it History Server data, never just code.** The open-source Spark History Server MCP
  (`kubeflow/mcp-apache-spark-history-server`) exposes applications, stages, executors, SQL plans and
  run-to-run comparison to Claude Code against any History Server (OSS, EMR, EKS). Keep event logs on
  (`spark.eventLog.enabled=true`, durable `spark.eventLog.dir`) or there is nothing to read.
- **Give it a checklist.** Section 3's symptom table and section 5's skew playbook. An agent finds the
  patterns it is told to look for and misses the rest.
- **Validate every suggestion against this file** before applying: agents propose fixes AQE already does
  (skew splitting, coalescing), extra salting where broadcast suffices, and config keys with wrong defaults.
  A misspelt key passed to `spark.conf.set` is silently ignored.
- **Measure one job at a time**: same input, before/after stage time, runtime and cost. Change one thing
  (section 2, step 8).
- **Too many metrics hurt.** Full traces overflow context and raise false positives; send the slowest
  stage's summary and the plan for the slow query, not everything.
- **Config autotuning is not an LLM job.** Production autotuners are ML/optimisation over a few knobs
  (Microsoft's Rockhopper / Fabric Autotune: shuffle partitions, broadcast threshold, max partition bytes;
  ByteDance's Rover). On Databricks serverless most configs are locked, so tune code and table layout.
- **Vendor agents**: AWS Spark Troubleshooting and Upgrade agents (MCP; EMR, Glue, SageMaker only;
  advice not changes); Databricks Genie Code (writes and fixes code, optimises SQL from the query
  profile; no evidence it tunes Spark jobs); Google Gemini Cloud Assist for Dataproc.
- **Migrations** (Spark upgrade, EMR/OSS to Databricks): inventory jobs, rewrite, then diff outputs
  against the old job on the same input before switching (section 16).

## 13. Designing a job

Decide these before tuning. Detail and reading list: [references/job-design.md](references/job-design.md).
- **Layers:** bronze append-only raw copy with load metadata; silver cleaned, deduped, one validated record
  per entity; gold business aggregates. One output table per job or flow, ordered by the orchestrator.
- **Every run is idempotent.** Pass the run date in; never key on `current_timestamp()`. Use
  `writeTo(t).overwrite(<partition filter>)` or `overwritePartitions()` for slice rebuilds and `MERGE` (deduped
  source) for upserts; plain `append` duplicates on re-run. Tag commits: `snapshot-property.run_id=<id>`.
- **Write-audit-publish** for tables others consume: `write.wap.enabled=true`, write to a branch via
  `spark.wap.branch`, check it, then `CALL …fast_forward('db.t','main','<branch>')`. The older `spark.wap.id`
  mode publishes appends and dynamic overwrites only, not MERGE.
- **Incremental only when recompute is too slow.** Append-only upstream: Iceberg `start-snapshot-id` reads or a
  stream with `availableNow`. Upstream with MERGE/DELETE: `create_changelog_view`. Late data: recompute a
  trailing window of partitions each run.
- **Batch vs streaming:** hours of freshness means scheduled batch or `availableNow`; minutes means
  micro-batch streaming (Iceberg trigger ≥ 1 min); sub-second means real-time mode or Flink.
- **Quality gates in the job:** declared input schemas; bad rows to a quarantine table, not dropped; row count,
  key uniqueness and null-rate checks via `df.observe`; fail before publish. Deequ has Spark 4.1 builds (2.0.x
  line); OSS Declarative Pipelines has no expectations (Databricks only).
- **Observable by default:** event logs to S3, `setJobDescription` per step, assert on Iceberg commit summaries
  (`spark.merge-into.num-target-rows-*`, Spark 4.1+), OpenLineage listener for lineage.

## 14. Cluster shape on AWS

Detail and measured results are in [references/cluster-sizing-aws.md](references/cluster-sizing-aws.md).
- **4–5 cores per executor** (AWS EMR guide). Check per-task execution memory ≈ (heap − 300 MiB) × 0.6 /
  cores; that, not the heap, decides spill.
- **Overhead is platform-specific:** 0.10 on OSS YARN/K8s JVM jobs, **0.40 for PySpark on K8s**, 0.1875 on
  EMR on EC2. PySpark with pandas/Arrow UDFs: budget 0.2–0.4 or set `spark.executor.pyspark.memory`.
- **Driver On-Demand, executors on Spot**, with `spark.decommission.enabled` +
  `spark.storage.decommission.enabled` and an S3 `…fallbackStorage.path` with a lifecycle rule. Spot's
  2-minute notice often beats migration, so pick the Spot share per job by SLA.
- **Graviton:** expect about 20–30% lower cost, mostly from price; some jobs run up to 6% slower, so benchmark
  heavy jobs, and rebuild native `.so` and Python wheels for aarch64.
- **Remote shuffle (Celeborn)** pays off for big shuffles on Spot/K8s autoscaling, where lost shuffle files
  force recomputes (Uber, Pinterest run it at 8–25 PB/day). Not worth it for short jobs or small shuffles,
  and it changes AQE's size statistics. Push-based shuffle is YARN-only.
- On K8s, mount NVMe instance store as `spark-local-dir-1`; the default `emptyDir` uses node ephemeral storage.

## 15. Testing

Detail in [references/testing.md](references/testing.md).
- Keep transforms pure (`DataFrame -> DataFrame`), I/O in a thin entrypoint, and compare with
  `pyspark.testing.assertDataFrameEqual` / `assertSchemaEqual` (3.5+; ignore-order/type options 4.0+).
- One session-scoped `local[2]` fixture with `spark.sql.shuffle.partitions=2` and ANSI on, same versions as production.
- **Guard performance by pinning the plan:** assert join strategy and `Exchange` count for key queries; diff
  `explain("formatted")` golden files in review (Spark's own `PlanStabilitySuite` does this for TPC-DS).
- Track stage metrics (shuffle bytes, spill, executor time) on a fixed Iceberg snapshot with sparkMeasure
  or the History Server REST API; alert on relative change, not wall-clock.

## 16. Benchmarking and verification

Detail, tool status and sources in [references/benchmarking.md](references/benchmarking.md).
- **Platforms and engines:** generate TPC-DS/TPC-H-derived data once (NVIDIA NDS runs on CPU Spark with
  Iceberg; `databricks/spark-sql-perf` is gone from GitHub, HiBench is archived) and read the same files,
  layout, table-format version and stats state from both sides. Then run your own top jobs by cost.
- Report cold and warm separately, 3+ runs, median and spread, total **and** geomean, and **cost per run** at
  list prices (instance-hours + EBS + EMR fee or DBUs). Check each query's result matches across engines.
- Publishing outside the company: call it "derived from TPC-DS", never quote QphDS, add the TPC disclaimer.
- **Table formats:** model your own change ratio and run 50–100 commits before measuring reads (LST-Bench
  longevity, lake-loader); count compaction in the cost. LHBench's numbers (Iceberg 1.1, 2022) are stale.
- **Regressions in your jobs:** frozen input (Iceberg tag), dedicated fixed-size cluster, 3–5 runs per side;
  gate on median executor CPU time or executor-seconds, a new spill or a new `Exchange`, not wall-clock.
  Match stages by job description (AQE renumbers them). Nightly: change-point detection (Apache Otava)
  over each job's history, not fixed thresholds.
- Two-run diffs: History Server MCP `compare_job_performance` / `compare_stages`; on Databricks,
  `system.lakeflow.job_run_timeline` and `system.billing.usage` by `job_run_id` give duration and cost per run.
- **Migrated output:** shadow-run to an Iceberg branch from the same input snapshot, then schema →
  per-partition count + decimal sum of `xxhash64` → keyed diff → column diff with float tolerance
  (datacompy `SparkSQLCompare`, spark-extension `diff`). Lakebridge reconcile has no OSS Spark/Iceberg source.
- Hash traps (verified 4.0.1): NULLs are skipped, so hash `isNull()` flags too; a bigint `sum` of hashes
  overflows under ANSI; `bit_xor` cancels duplicate rows; `subtract` hides duplicates, so `exceptAll` both ways.
- Diff with the new engine at its defaults (ANSI, CORRECTED time parsing; DBR 17+ is ANSI too) and use legacy
  flags only to bridge cut-over.
- **Data quality:** keep checks portable (`df.observe` + WAP, Deequ, GX 1.19+); DQX and Lakeflow expectations
  are Databricks-only, and Soda Core v4 is Elastic-licensed.

## 17. Anti-patterns

- `collect()` / `toPandas()` on anything unbounded. Use `limit`, write out, or Arrow-enabled `toPandas` on small results.
- Python UDFs for things built-ins do (`F.when`, `F.regexp_extract`, `F.transform`, higher-order functions).
- `withColumn` in a loop over hundreds of columns, which builds a huge plan. Use a single `select([...])` or `withColumns({...})`.
- `count()` "just to check" between steps. Each one is a full job.
- `repartition` before every write regardless of size. Use `REBALANCE` or Iceberg's hash distribution.
- `coalesce(1)` for "one output file" on big data, which serialises the whole upstream stage.
- `orderBy` on the full dataset when only a per-group order is needed (use windows), or before a write that does not need it.
- `inferSchema` on large CSV/JSON in production. Declare the schema.
- Caching everything. Or caching and never unpersisting.
- Turning AQE off to "make it deterministic".
- Relying on a hint without checking the plan.
- Tuning executor memory before checking for skew or small files.
- Joining on columns with mismatched types, which causes implicit casts and kills pushdown and SPJ.
- Using `spark.sql.shuffle.partitions=200` for a 5 TB shuffle, or for a 50 MB one.
- In 4.x, wrapping casts in `try`/`except` to dodge ANSI errors. Use `try_cast` / `try_*` functions deliberately.

## Sources

Official Spark docs (read Oct 2026, latest = 4.2.0; config tables also read for 3.5.6, 4.0.0, 4.1.0):
- https://spark.apache.org/docs/latest/sql-performance-tuning.html
- https://spark.apache.org/docs/latest/tuning.html
- https://spark.apache.org/docs/latest/configuration.html (and /docs/3.5.6/, /docs/4.0.0/, /docs/4.1.0/)
- https://spark.apache.org/docs/latest/web-ui.html
- https://spark.apache.org/docs/latest/streaming/apis-on-dataframes-and-datasets.html
- https://spark.apache.org/docs/latest/streaming/performance-tips.html
- https://spark.apache.org/docs/latest/streaming/structured-streaming-state-data-source.html
- https://spark.apache.org/docs/latest/streaming/structured-streaming-transform-with-state.html
- https://spark.apache.org/docs/latest/streaming/structured-streaming-kafka-integration.html
- https://spark.apache.org/releases/spark-release-4-0-0.html
- https://spark.apache.org/releases/spark-release-4.1.0.html

Databricks:
- https://docs.databricks.com/aws/en/optimizations/spark-ui-guide/ (jobs-timeline, long-spark-stage-page, slow-spark-stage-low-io)

AI-assisted diagnosis (read Oct 2026):
- https://github.com/kubeflow/mcp-apache-spark-history-server
- https://aws.amazon.com/blogs/big-data/introducing-mcp-server-for-apache-spark-history-server-for-ai-powered-debugging-and-optimization
- https://medium.com/expedia-group-tech/using-llms-to-analyze-spark-sql-plans-a-practical-approach-to-debugging-long-running-jobs-35eace7eeec4
- https://www.datadoghq.com/blog/using-agentic-ai-with-jobs-monitoring/
- https://docs.aws.amazon.com/emr/latest/ReleaseGuide/spark-troubleshoot.html
- https://docs.databricks.com/aws/en/genie-code/features-capabilities
- https://learn.microsoft.com/fabric/data-engineering/autotune
- https://www.microsoft.com/en-us/research/?p=1144154 (Rockhopper, SIGMOD 2025)
- https://arxiv.org/abs/2302.04046 (Rover)

Iceberg (docs source, main branch):
- https://iceberg.apache.org/docs/latest/spark-writes/
- https://iceberg.apache.org/docs/latest/spark-configuration/
- https://iceberg.apache.org/docs/latest/configuration/
- https://iceberg.apache.org/docs/latest/spark-procedures/
- https://iceberg.apache.org/docs/latest/spark-structured-streaming/
- https://iceberg.apache.org/docs/latest/aws/

Sections 1, 3 and 13–16 summarise reference files; their URLs are in each file's Sources:
spark-4x-changes.md, cluster-sizing-aws.md, field-results.md, testing.md, job-design.md, benchmarking.md.

Write-ups:
- https://medium.com/expedia-group-tech/turbocharge-efficiency-slash-costs-mastering-spark-iceberg-joins-with-storage-partitioned-join-03fdc1ff75c0
- https://issues.apache.org/jira/browse/SPARK-37442 (8 GB broadcast limit)

Existing agent skills checked (structure borrowed, numbers re-verified; jeffallan's "broadcast < 200 MB" rejected):
- https://github.com/jeffallan/claude-skills/tree/main/skills/spark-engineer
- https://github.com/wshobson/agents/tree/main/plugins/data-engineering/skills/spark-optimization
- https://github.com/databricks/databricks-agent-skills (`databricks-spark-structured-streaming`)
