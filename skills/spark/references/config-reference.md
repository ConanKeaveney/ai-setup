# Spark configuration reference (tuning keys)

These defaults were extracted from the official config tables for **3.5.6, 4.0.0, 4.1.0 and 4.2.0**
(spark.apache.org/docs/<ver>/configuration.html and sql-performance-tuning.html), and spot-checked with
`spark.conf.get` on local PySpark 4.0.1. "Since" is the version the key was added. Where defaults differ
across versions, every version is listed.

How to set them:
- Use `spark-submit --conf k=v` or `SparkSession.builder.config(k, v)`.
- SQL keys (`spark.sql.*`) can also be changed at runtime with `spark.conf.set` / `SET k=v`.
- Core keys (`spark.executor.*`, `spark.driver.*`, `spark.memory.*`) must be set before the
  SparkContext starts. In client mode, set `spark.driver.memory` with `--driver-memory`, not in code.

## Executor and driver resources

| Key | Default | Since | Notes |
|---|---|---|---|
| `spark.executor.memory` | 1g | 0.7.0 | JVM heap per executor |
| `spark.executor.cores` | 1 on YARN; all worker cores in standalone | 1.0.0 | Concurrent tasks per executor |
| `spark.executor.instances` | (not in table; set by cluster manager / dynamic allocation) | | |
| `spark.executor.memoryOverhead` | executorMemory × `memoryOverheadFactor`, min `minMemoryOverhead` | 2.3.0 | Non-heap: JVM overhead, netty, **Python workers** (unless `pyspark.memory` set), native libs (RocksDB, Arrow) |
| `spark.executor.memoryOverheadFactor` | 0.10 (**0.40 for Kubernetes non-JVM jobs**) | 3.3.0 | |
| `spark.executor.minMemoryOverhead` | 384m | 4.0.0 | Before 4.0 the 384 MB floor was hard-coded |
| `spark.executor.pyspark.memory` | not set | 2.4.0 | If set, it caps Python memory and is **added** to the container request |
| `spark.python.worker.memory` | 512m | 1.1.0 | Python-side aggregation spill threshold, not a container limit |
| `spark.memory.offHeap.enabled` / `.size` | false / 0 | 1.6.0 | Off-heap Tungsten memory, also added to the container size |
| `spark.driver.memory` | 1g | 1.1.1 | |
| `spark.driver.cores` | 1 | 1.3.0 | Cluster mode only |
| `spark.driver.maxResultSize` | 1g | 1.2.0 | Total serialized results of one action; 0 = unlimited (risks driver OOM) |
| `spark.task.cpus` | 1 | 0.5.0 | |

**Container size on YARN/K8s** = `executor.memory` + `memoryOverhead` + `offHeap.size` +
`pyspark.memory` (per the config doc).

**Sizing rule of thumb** (community practice, not an official default):
- Use 4–5 cores per executor, and leave about 1 core and a few GB per node for the OS and node daemons.
- Keep heap ≤ about 32–40 GB per executor to keep GC sane.
- Aim for about 4–8 GB heap per core for shuffle-heavy SQL.
- For PySpark with pandas UDFs, raise overhead (or set `pyspark.memory`) well above 10%.
- EMR on EC2 already defaults the YARN overhead factor to 0.1875, not 0.10 (AWS EMR best-practices guide).
  Full method, Kubernetes and Spot detail: [cluster-sizing-aws.md](cluster-sizing-aws.md).

Worked example for a 16 vCPU / 128 GiB node:
- 3 executors × 5 cores (15 cores used).
- Per executor, about 128 GiB × 0.9 / 3 ≈ 38 GiB of container space.
- Split each container as 32g heap + 6g overhead.

## Unified memory model

| Key | Default | Since | Meaning |
|---|---|---|---|
| `spark.memory.fraction` | 0.6 | 1.6.0 | M = (heap − 300 MiB reserved) × 0.6 is shared by execution and storage |
| `spark.memory.storageFraction` | 0.5 | 1.6.0 | R = M × 0.5 is the part of storage that execution cannot evict |
| `spark.storage.memoryMapThreshold` | 2m | 0.9.2 | |
| `spark.cleaner.periodicGC.interval` | 30min | 1.6.0 | |

Execution can evict cached blocks down to R. Storage can never evict execution. The remaining
40% of (heap − 300 MiB) is "user memory": UDF objects, metadata, and data structures.

## Shuffle, network, serialization

| Key | Default | Since | Notes |
|---|---|---|---|
| `spark.sql.shuffle.partitions` | 200 | 1.1.0 | Initial shuffle partitions for SQL/DataFrame. AQE coalesces from here. |
| `spark.default.parallelism` | max(total cores, 2) on clusters | 0.5.0 | RDD ops only |
| `spark.shuffle.file.buffer` | 32k | 1.4.0 | Raise to 1m to cut disk syscalls on big shuffles |
| `spark.reducer.maxSizeInFlight` | 48m | 1.4.0 | |
| `spark.shuffle.compress` | true | 0.6.0 | |
| `spark.io.compression.codec` | lz4 | 0.8.0 | zstd is smaller on the wire; 4.0 added parallel zstd |
| `spark.shuffle.sort.bypassMergeThreshold` | 200 | 1.1.1 | |
| `spark.shuffle.service.enabled` | false | 1.2.0 | External shuffle service (YARN) |
| `spark.shuffle.push.enabled` | false | 3.2.0 | Push-based shuffle (YARN only) |
| `spark.serializer` | JavaSerializer | 0.5.0 | Kryo helps RDD/closure-heavy code. DataFrames use Tungsten encoders regardless. |
| `spark.kryoserializer.buffer.max` | 64m | 1.4.0 | |
| `spark.network.timeout` | 120s | 1.3.0 | |
| `spark.executor.heartbeatInterval` | 10s | 1.1.0 | Must be ≪ network.timeout |
| `spark.locality.wait` | 3s | 0.5.0 | Raise for streaming state-store locality |
| `spark.task.maxFailures` | 4 | 0.8.0 | |
| `spark.speculation` | false | 0.6.0 | `.multiplier` 3, `.quantile` 0.9 from 4.0 (1.5 / 0.75 in 3.5). Speculation helps with bad nodes, **not** skew. |
| `spark.shuffle.accurateBlockThreshold` | 100 * 1024 * 1024 | 2.2.1 | Blocks above this size are recorded exactly in map status |
| `spark.shuffle.accurateBlockSkewedFactor` | -1.0 (off) | 3.3.0 | Set equal to `skewJoin.skewedPartitionFactor` so AQE sees skew when shuffle partitions > 2000 |
| `spark.sql.shuffle.orderIndependentChecksum.enabled` | true (4.2 migration guide) | 4.1.0 | A checksum mismatch on an indeterminate stage retry re-runs dependent stages or fails the job |
| `spark.io.mode.default` | AUTO (native epoll on Linux) | 4.1.0 | |
| `spark.checkpoint.compress` | false → **true** in 4.1 | 2.2.0 | |
| `spark.eventLog.rolling.enabled` / `spark.eventLog.compress` | true / true from 4.0 (false in 3.5) | 3.0.0 / 1.0.0 | 4.0 release notes and migration guide; the 4.0.0 config table still printed false |

## AQE (sql-performance-tuning.html)

| Key | Default | Since |
|---|---|---|
| `spark.sql.adaptive.enabled` | true (default-on since 3.2.0) | 1.6.0 |
| `spark.sql.adaptive.coalescePartitions.enabled` | true | 3.0.0 |
| `spark.sql.adaptive.coalescePartitions.parallelismFirst` | true. When true, it ignores the advisory size and only respects `minPartitionSize`. The docs recommend `false` on busy clusters. | 3.2.0 |
| `spark.sql.adaptive.coalescePartitions.minPartitionSize` | 1MB | 3.2.0 |
| `spark.sql.adaptive.coalescePartitions.initialPartitionNum` | (none, so `spark.sql.shuffle.partitions`) | 3.0.0 |
| `spark.sql.adaptive.advisoryPartitionSizeInBytes` | 64MB | 3.0.0 |
| `spark.sql.adaptive.autoBroadcastJoinThreshold` | (none, so same as `spark.sql.autoBroadcastJoinThreshold`) | 3.2.0 |
| `spark.sql.adaptive.localShuffleReader.enabled` | true | 3.0.0 |
| `spark.sql.adaptive.maxShuffledHashJoinLocalMapThreshold` | 0 (SMJ→SHJ conversion off) | 3.2.0 |
| `spark.sql.adaptive.skewJoin.enabled` | true | 3.0.0 |
| `spark.sql.adaptive.skewJoin.skewedPartitionFactor` | 5.0 | 3.0.0 |
| `spark.sql.adaptive.skewJoin.skewedPartitionThresholdInBytes` | 256MB (should be > advisory size) | 3.0.0 |
| `spark.sql.adaptive.forceOptimizeSkewedJoin` | false (true allows an extra shuffle to fix skew) | 3.3.0 |
| `spark.sql.adaptive.optimizeSkewsInRebalancePartitions.enabled` | true | 3.2.0 |
| `spark.sql.adaptive.rebalancePartitionsSmallPartitionFactor` | 0.2 | 3.3.0 |
| `spark.sql.adaptive.optimizer.excludedRules` | (none) | 3.1.0 |

## Joins, statistics, optimizer

| Key | Default | Since | Notes |
|---|---|---|---|
| `spark.sql.autoBroadcastJoinThreshold` | 10MB | 1.1.0 | -1 disables auto-broadcast (not BroadcastNestedLoopJoin for non-equi joins) |
| `spark.sql.broadcastTimeout` | 300 (s) | 1.3.0 | |
| `spark.sql.shuffledHashJoinFactor` | 3 | 3.3.0 | |
| `spark.sql.cbo.enabled` | false | 2.2.0 | Needs `ANALYZE TABLE … COMPUTE STATISTICS [FOR COLUMNS …]` |
| `spark.sql.statistics.histogram.enabled` | false | 2.3.0 | |
| `spark.sql.optimizer.dynamicPartitionPruning.enabled` | true | 3.0.0 | |
| `spark.sql.optimizer.runtime.bloomFilter.enabled` | true | 3.3.0 | Creation side ≤ 10MB, application side ≥ 10GB |
| `spark.sql.optimizer.runtimeFilter.number.threshold` | 10 | 3.3.0 | |
| `spark.sql.sources.bucketing.enabled` | true | 2.0.0 | Hive-style bucketing (V1) |
| `spark.sql.bucketing.coalesceBucketsInJoin.enabled` | false | 3.1.0 | |

Hard limit: a broadcast relation larger than 8 GB fails with `Cannot broadcast the table that is larger than 8GB`
(see SPARK-37442).

## Storage Partition Join (V2 sources such as Iceberg)

| Key | 3.5 | 4.0 | 4.1 / 4.2 | Since |
|---|---|---|---|---|
| `spark.sql.sources.v2.bucketing.enabled` | **false** | **false** | **true** | 3.3.0 |
| `spark.sql.sources.v2.bucketing.pushPartValues.enabled` | true | true | true | 3.4.0 |
| `spark.sql.requireAllClusterKeysForCoPartition` | true | true | true | 3.4.0 |
| `spark.sql.sources.v2.bucketing.partiallyClusteredDistribution.enabled` | false | false | false | 3.4.0 |
| `spark.sql.sources.v2.bucketing.allowJoinKeysSubsetOfPartitionKeys.enabled` | n/a | false | false | 4.0.0 |
| `spark.sql.sources.v2.bucketing.allowCompatibleTransforms.enabled` | n/a | false | false | 4.0.0 |
| `spark.sql.sources.v2.bucketing.shuffle.enabled` | n/a | false | false | 4.0.0 |

Iceberg-side switch: `spark.sql.iceberg.planning.preserve-data-grouping` (default false).

## File sources and writes

| Key | Default | Since | Notes |
|---|---|---|---|
| `spark.sql.files.maxPartitionBytes` | 128MB | 2.0.0 | Max bytes per read split |
| `spark.sql.files.openCostInBytes` | 4MB | 2.0.0 | Raise to pack more small files per task |
| `spark.sql.files.minPartitionNum` | (none, so default parallelism) | 3.1.0 | |
| `spark.sql.files.maxPartitionNum` | (none) | 3.5.0 | Caps split count by rescaling |
| `spark.sql.files.maxRecordsPerFile` | 0 (unlimited) | 2.2.0 | |
| `spark.sql.files.ignoreCorruptFiles` / `ignoreMissingFiles` | false / false | 2.1.1 / 2.3.0 | |
| `spark.sql.sources.partitionOverwriteMode` | STATIC | 2.3.0 | `dynamic` = only overwrite touched partitions (file tables) |
| `spark.sql.sources.parallelPartitionDiscovery.threshold` | 32 | 1.5.0 | |
| `spark.sql.parquet.compression.codec` | snappy | 1.1.1 | Iceberg tables use their own `write.parquet.compression-codec` (zstd) |
| `spark.sql.parquet.filterPushdown` | true | 1.2.0 | |
| `spark.sql.parquet.enableVectorizedReader` | true | 2.0.0 | |
| `spark.sql.parquet.aggregatePushdown` | false | 3.3.0 | |
| `spark.sql.inMemoryColumnarStorage.compressed` / `.batchSize` | true / 10000 | 1.0.1 / 1.1.1 | Cache format |

## Dynamic allocation and decommissioning

| Key | Default | Since |
|---|---|---|
| `spark.dynamicAllocation.enabled` | false | 1.2.0 |
| `spark.dynamicAllocation.shuffleTracking.enabled` | true | 3.0.0 |
| `spark.dynamicAllocation.executorIdleTimeout` | 60s | 1.2.0 |
| `spark.dynamicAllocation.cachedExecutorIdleTimeout` | infinity (executors holding cache never released) | 1.4.0 |
| `spark.decommission.enabled` | false | 3.1.0 |
| `spark.storage.decommission.enabled` | false | 3.1.0 |
| `spark.storage.decommission.shuffleBlocks.enabled` | true | 3.1.0 |

On Kubernetes there is no external shuffle service. Dynamic allocation relies on shuffle tracking, and
decommissioning migrates shuffle/cache blocks off spot nodes that are going away. 4.0 enabled
`spark.shuffle.service.removeShuffle` and `spark.stage.ignoreDecommissionFetchFailure` by default (4.0.0
release notes).

## SQL semantics, Python and Arrow

| Key | 3.5 | 4.0 | 4.1 | 4.2 | Since |
|---|---|---|---|---|---|
| `spark.sql.ansi.enabled` | false | **true** | true | true | 3.0.0 |
| `spark.sql.execution.pythonUDF.arrow.enabled` | false | false | false | **true** | 3.4.0 |
| `spark.sql.execution.pythonUDTF.arrow.enabled` | false | false | false | true | 3.5.0 |
| `spark.sql.execution.arrow.enabled` | false | false | false | **true** | 2.3.0 |
| `spark.sql.execution.arrow.pyspark.enabled` | follows `spark.sql.execution.arrow.enabled` | (false) | (false) | (true) | 3.0.0 |
| `spark.sql.execution.arrow.maxRecordsPerBatch` | 10000 | 10000 | 10000 | 10000 | 2.3.0 |
| `spark.sql.execution.arrow.pyspark.selfDestruct.enabled` | false | false | false | false | 3.2.0 |
| `spark.sql.pyspark.jvmStacktrace.enabled` | false | false | false | false | 3.0.0 |
| `spark.sql.execution.pyspark.udf.faulthandler.enabled` | n/a | from `spark.python.worker.faulthandler.enabled` | | | 4.0.0 |
| `spark.sql.pyspark.udf.profiler` | n/a | (none): `perf` or `memory` | | | 4.0.0 |
| `spark.api.mode` | n/a | classic (or `connect`) | | | 4.0.0 |
| `spark.sql.scripting.enabled` | n/a | false | **true** | true | 4.0.0 |
| `spark.sql.execution.pyspark.binaryAsBytes` | n/a | n/a | true | true | 4.1.0 |
| `spark.sql.pyspark.worker.logging.enabled` | n/a | n/a | false | false | 4.1.0 |
| `spark.sql.execution.arrow.compression.codec` | n/a | n/a | none | none | 4.1.0 |
| `spark.sql.execution.arrow.pythonUDF.columnarInput.enabled` | n/a | n/a | n/a | true | 4.2.0 |

The 4.2 Arrow defaults are confirmed by the PySpark 4.1 → 4.2 migration guide. So before 4.2, `toPandas()` / `createDataFrame(pandas_df)` do **not** use Arrow unless you set
`spark.sql.execution.arrow.pyspark.enabled=true`, which is a big speedup worth setting explicitly. Lower
`maxRecordsPerBatch` if pandas UDF batches blow Python memory.

## Streaming (selected; more in streaming.md)

| Key | Default | Since |
|---|---|---|
| `spark.sql.streaming.stateStore.providerClass` | HDFS-backed provider (state in executor JVM heap) | RocksDB provider added in 3.2 |
| `spark.sql.streaming.stateStore.rocksdb.changelogCheckpointing.enabled` | false | |
| `spark.sql.streaming.stateStore.rocksdb.boundedMemoryUsage` / `maxMemoryUsageMB` | false / 500 | |
| `spark.sql.streaming.stateStore.rocksdb.trackTotalNumberOfRows` | true (turn off for write-heavy state) | |
| `spark.sql.streaming.stateStore.stateSchemaCheck` | true | 3.1.0 |
| `spark.sql.streaming.stateStore.encodingFormat` | unsaferow (`avro` option) | 4.0.0 |
| `spark.sql.streaming.noDataMicroBatches.enabled` | true | 2.4.1 |
| `spark.sql.streaming.metricsEnabled` | false (true exposes Dropwizard metrics) | 2.0.2 |
| `spark.sql.streaming.multipleWatermarkPolicy` | min | 2.4.0 |
| `spark.sql.streaming.numRecentProgressUpdates` | 100 | 2.1.1 |

The RocksDB rows come from the streaming guide's RocksDB table, which gives defaults but no since-version.
