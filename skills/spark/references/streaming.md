# Structured Streaming reference (Spark 3.5 / 4.x)

Sources: Spark 4.2 streaming guide pages (apis-on-dataframes-and-datasets, performance-tips,
additional-information, state data source, transformWithState, Kafka integration). The snippets were run on
local PySpark 4.0.1 with the RocksDB provider and changelog checkpointing on.

## 1. Execution model

- The default engine is **micro-batch**: each trigger plans and runs a small batch job over new offsets, then
  commits offsets and state to the checkpoint. The guide quotes about 100 ms latency at best, with
  exactly-once guarantees when the source is replayable and the sink is idempotent.
- **Continuous processing** (experimental, since 2.3) gives about 1 ms latency with **at-least-once**
  guarantees. It supports only map-like operations, Kafka/rate sources and Kafka/memory/console sinks, and has
  no automatic task retry.
- **Real-time mode** (4.1+) is a new trigger. It runs long-lived tasks, one per input partition, for
  sub-second latency. `Trigger.RealTime("5 minutes")` in Scala/Java (4.1); `.trigger(realTime="5 minutes")`
  in PySpark (4.2, SPARK-54660). The duration is a checkpoint interval, not a latency target
  (min `spark.sql.streaming.realTimeMode.minBatchDuration` = 5000ms).
  - Released (4.1/4.2): stateless queries only, Kafka source, Kafka/foreach/console sinks, `update` mode,
    no `foreachBatch`, no AQE. Kafka sink is at-least-once.
  - Needs one core per Kafka partition held for the whole batch (`minPartitions` unsupported); run one RTM
    query per cluster.
  - Stateful RTM (dedup, aggregations, JVM transformWithState) is documented on `master` for 4.3.0, which is
    unreleased as of Oct 2026. Detail: spark-4x-changes.md.
- **Asynchronous progress tracking** (`asyncProgressTrackingEnabled`, default false) checkpoints offsets in
  parallel with processing. It is stateless-only and Kafka-sink-only, and gives no exactly-once.

## 2. Triggers

| Trigger | PySpark | Use |
|---|---|---|
| Default (none) | n/a | Next batch starts as soon as the previous one finishes |
| Processing time | `.trigger(processingTime="1 minute")` | Steady cadence. Use ≥ 1 min for Iceberg sinks (commit rate) |
| Available-now (3.3+) | `.trigger(availableNow=True)` | Process everything available, **in multiple rate-limited batches**, then stop. This is "incremental batch" for scheduled jobs. |
| Once | `.trigger(once=True)` | **Deprecated**. It ignores rate limits (a single huge batch). Use availableNow. |
| Continuous | `.trigger(continuous="1 second")` | See above |

If a source does not support `AvailableNow`, that trigger is deactivated. Rate limits (`maxFilesPerTrigger`,
`maxOffsetsPerTrigger`, Iceberg `streaming-max-files-per-micro-batch`) still apply under availableNow.

## 3. Output modes and sinks

- `append` (default): only finalised rows. Aggregations need a watermark.
- `update`: changed rows.
- `complete`: whole result table, for aggregations only.
- **`foreachBatch(fn(df, batch_id))`** is the workhorse for MERGE/upsert into Iceberg, multi-sink fan-out, and
  calling batch-only APIs. It is **at-least-once** by default. For exactly-once, make the write idempotent
  keyed on `batch_id`, or MERGE on a natural key. If writing to multiple sinks, `persist()` the batch DataFrame
  and `unpersist()` it at the end.
- Kafka sink: at-least-once. File / Iceberg sinks: exactly-once via the checkpoint and atomic commits.

## 4. Checkpoints

- One unique, durable checkpoint per query (S3 is fine for Iceberg/Kafka pipelines). It holds offsets,
  commits, state, and metadata.
- These settings are **frozen at first run**. Changing them needs a new checkpoint (guide, "Additional
  Information"):
  - `spark.sql.shuffle.partitions`. This is the number of state partitions. To run fewer tasks, `coalesce`
    rather than re-partition.
  - `spark.sql.streaming.stateStore.providerClass`, so you **cannot switch HDFS→RocksDB on an existing
    checkpoint**.
  - `spark.sql.streaming.multipleWatermarkPolicy`.
- Query changes that are allowed or forbidden on restart are listed under "Recovery Semantics after Changes in
  a Streaming Query". Roughly:
  - Changing filters or projections, and adding sinks via foreachBatch, are allowed.
  - Changing the grouping keys, stateful operator, or join type is not.

## 5. Stateful processing

### Watermarks

```python
(events.withWatermark("event_ts", "10 minutes")
       .groupBy(F.window("event_ts", "5 minutes"), "k").count())
```

- `withWatermark` must be applied to the same column used in the aggregation, and **before** the aggregation.
- A watermark of "2 hours" guarantees that data less than 2 hours late is not dropped. Later data *may* be
  dropped.
- With multiple input watermarks, the global watermark = min by default
  (`spark.sql.streaming.multipleWatermarkPolicy=min`; `max` is the other option).
- `dropDuplicatesWithinWatermark(["guid"])` (3.5+) dedupes with state bounded by the watermark. Plain
  `dropDuplicates` on a stream keeps state forever unless the watermark column is among the keys.

### Stream-stream joins
- Both sides need watermarks plus an event-time range condition (or a time-window equality) so state can be
  dropped. Inner joins can work without them, but state grows unbounded.
- Outer joins **require** watermarks and the time constraint, and emit unmatched rows only once the watermark
  passes.

### Stream-static joins
- The static side is re-read each micro-batch (a fresh scan unless cached). Keep it small or broadcast it.
- Prefer a left join from the stream to the static side, because inner joins silently drop late-arriving
  dimension rows.

### transformWithState (4.0+)
- The next-generation arbitrary stateful API. It replaces `mapGroupsWithState` / `flatMapGroupsWithState`
  (Scala) and `applyInPandasWithState` (Python).
- It offers ValueState, ListState and MapState, TTL-based eviction, and timers. State schema evolution is
  value-side only and needs `spark.sql.streaming.stateStore.encodingFormat=avro`.
- In Python it comes in two forms: `transformWithStateInPandas` (pandas interface) and `transformWithState`
  (Row interface). The Row interface is better for very high key cardinality.

## 6. State store: HDFS-backed vs RocksDB

- **HDFS-backed (default):**
  - State lives in executor **JVM heap**, so millions of keys cause GC pauses and erratic batch times.
  - Watch `loadedMapCacheHitCount` / `loadedMapCacheMissCount` for locality.
- **RocksDB (since 3.2):**
  - State lives in native memory plus local disk, and checkpoints to durable storage.
  - Use it with transformWithState. The OSS guide page does not say whether RocksDB is required there, so
    this was not verified.
  - Enable it with:

```
spark.sql.streaming.stateStore.providerClass=org.apache.spark.sql.execution.streaming.state.RocksDBStateStoreProvider
spark.sql.streaming.stateStore.rocksdb.changelogCheckpointing.enabled=true   # default false
```

| RocksDB key (`spark.sql.streaming.stateStore.rocksdb.*`) | Default | Notes |
|---|---|---|
| `changelogCheckpointing.enabled` | false | Uploads only the change log each batch, with snapshots in the background. Lower latency. Can be toggled either way on restart. |
| `compactOnCommit` | false | |
| `blockSizeKB` | 4 | |
| `blockCacheSizeMB` | 8 | |
| `lockAcquireTimeoutMs` | 60000 | |
| `maxOpenFiles` | -1 | |
| `resetStatsOnLoad` | true | |
| `trackTotalNumberOfRows` | true | Costs an extra lookup per write. Turn it off for heavy state (numTotalStateRows then reports 0). |
| `writeBufferSizeMB` / `maxWriteBufferNumber` | -1 / -1 | Per-instance memtable limits |
| `boundedMemoryUsage` | false | Soft cap across all instances on a node |
| `maxMemoryUsageMB` | 500 | Used when bounded |
| `writeBufferCacheRatio` / `highPriorityPoolRatio` | 0.5 / 0.1 | |
| `allowFAllocate` | true | |
| `compression` | lz4 | |

- **Memory:** RocksDB memory is outside the JVM heap, so it counts against `spark.executor.memoryOverhead`.
  Either bound it (`boundedMemoryUsage=true` + `maxMemoryUsageMB`) or size overhead for it, or pods get
  OOMKilled. 4.1 integrates RocksDB memory usage with the unified memory manager (SPARK-53001); the release
  notes do not say it moved into the heap, so keep budgeting overhead (unverified beyond the JIRA title).
- **Changelog checkpointing is still off by default in 4.2** (streaming guide). 4.1/4.2 add automatic
  snapshot repair, row checksums and snapshot-on-upload-lag (`forceSnapshotUploadOnLag`, on by default in 4.2).
- **Locality:** state stores are reused when a task lands on the same executor. If batches keep reloading
  state, raise `spark.locality.wait`. Avoid dynamic allocation and autoscaling on stateful streams, because
  moving executors forces state reloads.

### Inspecting state (4.0+)

```python
spark.read.format("state-metadata").load(checkpoint).show()   # operators, partitions, batch range
spark.read.format("statestore").load(checkpoint).show()       # key/value rows (read-only, experimental)
```

Both were verified on 4.0.1. The metadata only exists for checkpoints written by Spark 4.0+ (run once on 4.x
first).

## 7. Sources

### Kafka
- Options: `subscribe` / `subscribePattern` / `assign`, `startingOffsets` (`earliest`/`latest`/JSON; it only
  applies when a new query starts), `startingTimestamp` (takes precedence), `failOnDataLoss`, and
  `maxOffsetsPerTrigger` (rate limit).
- `minPartitions`: Spark splits Kafka partitions to get about this many tasks. Use it when topic partitions
  are fewer than cores.
- Kafka `auto.offset.reset` and `group.id` semantics are managed by Spark. Use `startingOffsets`, not
  consumer configs.

### Files
- `maxFilesPerTrigger` or `maxBytesPerTrigger` (not both), `latestFirst`, `maxFileAge` (default 1 week, ignored
  for the first batch), and `cleanSource` (archive or delete).
- Listing large S3 prefixes is slow. Prefer Kafka or Iceberg as the source.

### Iceberg
- Reads **append snapshots only**. Overwrite and delete snapshots throw unless
  `streaming-skip-overwrite-snapshots` / `streaming-skip-delete-snapshots` are set.
- Use `stream-from-timestamp` to start from a point in time, and `streaming-max-files-per-micro-batch` /
  `streaming-max-rows-per-micro-batch` for rate limits.
- `async-micro-batch-planning-enabled` overlaps planning with processing.

## 8. Monitoring and tuning

- **`query.lastProgress` / `recentProgress`** (JSON): `batchId`, `numInputRows`, `inputRowsPerSecond`,
  `processedRowsPerSecond`, `durationMs` (addBatch, getBatch, latestOffset, queryPlanning, triggerExecution,
  walCommit), `eventTime.watermark`, `stateOperators[]` (numRowsTotal, numRowsUpdated, memoryUsedBytes, and
  `customMetrics` with rocksdb* timings), `sources[]` (offsets, Kafka lag metrics), and `sink`.
- **Healthy query:** processed rate ≥ input rate on average, batch duration < trigger interval, and state
  rows flat (bounded by the watermark).
- **Falling behind:**
  - Check whether `addBatch` dominates: that means compute, so tune it like a batch job (skew, partitions).
  - Check whether `walCommit` / `commit` or the sink commit dominates (often Iceberg metadata): lengthen the
    trigger, compact, and expire snapshots.
  - Check whether `queryPlanning` / `latestOffset` dominates: that means source listing.
- Use `StreamingQueryListener` (Scala/Java, and Python since 3.4) to push progress to metrics, or set
  `spark.sql.streaming.metricsEnabled=true` for Dropwizard metrics.
- The Structured Streaming UI tab shows input/process rates, batch duration, operation duration, and state
  rows over time.
- Keep `spark.sql.shuffle.partitions` sane **before first start** for stateful queries. 200 state partitions
  with RocksDB means 200 RocksDB instances per batch.

## 9. Production checklist (idea borrowed from Databricks' streaming skill, made engine-neutral)

- [ ] Unique durable checkpoint per query, and never reused across code that changes stateful shape
- [ ] RocksDB provider plus changelog checkpointing chosen **before** first run, with memory bounded or budgeted in overhead
- [ ] Watermark on every stateful operation, with a lateness bound agreed with the data owners
- [ ] Rate limit set (`maxOffsetsPerTrigger` / `maxFilesPerTrigger`) so a backlog cannot create one giant batch
- [ ] availableNow (not once) for scheduled incremental jobs
- [ ] foreachBatch writes idempotent on `batch_id` or natural key
- [ ] Fixed-size executors for stateful streams (no aggressive dynamic allocation)
- [ ] Progress metrics exported, with alerts on input rate > processed rate and batch duration > trigger
- [ ] Iceberg sink: trigger ≥ 1 min, `fanout-enabled` considered, compaction / expire-snapshots / rewrite-manifests scheduled
