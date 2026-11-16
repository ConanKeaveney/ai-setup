# Iceberg from the Spark side (open-source Spark on AWS)

This file covers what a Spark engineer needs to make Iceberg jobs fast. For table-format design (spec v2/v3,
catalogs, MoR internals, branching, interop) load the `iceberg` skill.

Source: Iceberg docs (spark-configuration, spark-writes, configuration, spark-procedures,
spark-structured-streaming, aws). SPJ, procedures and table properties were run locally with
`iceberg-spark-runtime-4.0_2.13:1.10.0`.

## 1. Session setup (AWS, Glue catalog, S3FileIO)

```bash
spark-submit \
  --packages org.apache.iceberg:iceberg-spark-runtime-<spark-major.minor>_<scala>:<iceberg-ver>,org.apache.iceberg:iceberg-aws-bundle:<iceberg-ver> \
  --conf spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions \
  --conf spark.sql.catalog.lake=org.apache.iceberg.spark.SparkCatalog \
  --conf spark.sql.catalog.lake.type=glue \
  --conf spark.sql.catalog.lake.warehouse=s3://bucket/prefix \
  --conf spark.sql.catalog.lake.io-impl=org.apache.iceberg.aws.s3.S3FileIO \
  job.py
```

- The runtime jar must match the Spark minor version and Scala version. Spark 4.x is Scala 2.13 only.
- The `IcebergSparkSessionExtensions` are needed for `CALL` procedures, `MERGE`/`UPDATE`/`DELETE`
  row-level plans, and the DDL extensions (`ALTER TABLE … WRITE ORDERED BY`, partition-field DDL).
- `type=rest` (REST catalog, S3 Tables, Polaris) works the same way. Only the catalog properties change.

## 2. Reads

- **Split sizing:** `read.split.target-size` (128 MB) is the table property. You can override it per
  read with `.option("split-size", …)` or per session with `spark.sql.iceberg.read.split-size`.
  Adaptive split sizing is available (`spark.sql.iceberg.read.adaptive-split-size.enabled`).
- **Vectorized Parquet reads:** on by default (`read.parquet.vectorization.enabled`=true, batch-size 5000).
- **Pruning:** Iceberg prunes on partition values (hidden partitioning: filter on `ts`, not on a derived
  `ts_day` column) and on column min/max stats in manifests. Filters on transformed or cast columns may not
  prune. Check "number of files read" in the SQL tab.
- **Aggregate pushdown:** MIN/MAX/COUNT from metadata (`spark.sql.iceberg.aggregate-push-down.enabled`=true).
- **Planning cost:** huge tables with many small manifests make driver-side planning slow, which shows up as a
  gap before the first job. `rewrite_manifests` fixes it. `spark.sql.iceberg.data-planning-mode` (AUTO, LOCAL
  or DISTRIBUTED) can push planning to executors.
- **Delete files (MoR):** many position or equality deletes slow reads. An executor cache for delete files
  exists (`spark.sql.iceberg.executor-cache.*`). The real fix is compaction.

## 3. Writes: distribution and file size

**`write.distribution-mode`** decides how Spark shuffles rows before writing:
- `none`: no shuffle. Each task writes to every partition it sees. That gives many small files unless the
  data is already clustered. To avoid needing a sort, use `fanout-enabled` (more open files and memory).
- `hash`: **default since Iceberg 1.2.0.** Hash-shuffle by partition value. Spark does not respect it for
  CTAS/RTAS before 3.5.0.
- `range`: sample, then range-shuffle by partition and sort key. Global ordering helps reads. It is costlier
  to write. It is the default when the table has a sort order.

**File size control.** A file cannot be larger than the Spark task that writes it, nor span partitions.
Iceberg rolls files at `write.target-file-size-bytes` (default **512 MB**), but only if the task has that
much data. With a distribution mode other than `none`, AQE sizes the write tasks to
`spark.sql.adaptive.advisoryPartitionSizeInBytes`. That is **shuffle bytes (row format)**, and it compresses
to much smaller Parquet. So:
- Set `spark.sql.iceberg.advisory-partition-size` (Iceberg-specific, wins for the write) or the AQE advisory
  size to **several times** the target file size. Measure the ratio on your data: look at the written file sizes
  in `<table>.files`.
- `spark.sql.adaptive.coalescePartitions.parallelismFirst=false`, or AQE may ignore the advisory size.

Other write properties:

| Property | Default | Notes |
|---|---|---|
| `write.parquet.compression-codec` | zstd | |
| `write.target-file-size-bytes` | 536870912 (512 MB) | |
| `write.spark.fanout.enabled` | false | Session or write option `fanout-enabled` |
| `write.object-storage.enabled` | false | Hash prefix in paths. Avoids S3 prefix throttling on hot partitions. |
| `write.delete.mode` / `write.update.mode` / `write.merge.mode` | copy-on-write | `merge-on-read` for frequent small changes, then compact |
| `write.metadata.delete-after-commit.enabled` | false | Turn on for frequent committers (with `write.metadata.previous-versions-max`) |
| `commit.manifest-merge.enabled` / `commit.manifest.min-count-to-merge` / `commit.manifest.target-size-bytes` | true / 100 / 8 MB | |

**Overwrite semantics:**
- `df.writeTo(t).overwritePartitions()` gives dynamic partition overwrite.
- `INSERT OVERWRITE` with `spark.sql.sources.partitionOverwriteMode=dynamic` behaves the same.
- Static-mode `INSERT OVERWRITE` without a `PARTITION` clause replaces the **whole table**.
- Prefer `MERGE INTO` for upserts.

## 4. MERGE / row-level operations: performance

- **Copy-on-write:** every touched file is rewritten. Writes are slow, reads are fast. This is the right choice
  for infrequent bulk changes.
- **Merge-on-read:** writes delete files, so writes are fast and reads pay for applying deletes. This is the
  right choice for frequent small upserts (CDC), **as long as** you compact regularly.
- **Make MERGE prune:** put a partition-bounded predicate in the `ON` clause (e.g.
  `t.event_date >= date_sub(current_date(), 3)`) so only the relevant files are scanned. A MERGE with only a
  key join scans the whole target.
- **Deduplicate the source first.** Multiple source rows matching one target row is an error.
- SPJ can remove the shuffle in MERGE when source and target share a bucket spec (see skew-and-joins.md).
- **Isolation level** defaults to serializable for MERGE/UPDATE/DELETE. Concurrent writers to the same
  partitions retry or fail on commit conflicts. Separate writers by partition, or serialise them.

## 5. Storage Partitioned Join

Settings, requirements and verification are in skew-and-joins.md, section 5. In short:
- bucket both tables on the join key with the same N;
- set `spark.sql.sources.v2.bucketing.enabled=true` (false by default before 4.1);
- set `spark.sql.iceberg.planning.preserve-data-grouping=true`;
- usually also set `spark.sql.requireAllClusterKeysForCoPartition=false`.

## 6. Streaming into Iceberg

- **Trigger:** Iceberg recommends ≥ 1 minute. Every micro-batch is a commit, which means a snapshot, a
  manifest, and small files.
- **`fanout-enabled=true`** avoids the per-batch shuffle or sort that the hash distribution would add. It
  keeps one open file per partition per task. Iceberg advises against it for batch writes.
- **Maintenance is mandatory:**
  - `expire_snapshots`: the default age is 5 days (`history.expire.max-snapshot-age-ms`), keeping 1
    snapshot minimum.
  - `rewrite_data_files`: compaction.
  - `rewrite_manifests`: fast appends do not merge manifests.
  - Optionally `write.metadata.delete-after-commit.enabled=true`.
- **Reading a stream from Iceberg:**
  - Only append snapshots are processed. Overwrites and deletes throw unless you set
    `streaming-skip-overwrite-snapshots` / `streaming-skip-delete-snapshots`.
  - Rate-limit with `streaming-max-files-per-micro-batch` / `streaming-max-rows-per-micro-batch`.
- **CDC upserts:** use `foreachBatch` with `MERGE INTO`, and dedupe each batch on key plus latest
  sequence first.

## 7. Maintenance procedures (Spark `CALL`)

```sql
-- Every statement in this block, and every query in section 8, ran successfully on Spark 4.0.1 with
-- Iceberg 1.10.0, against a merge-on-read v2 table that already had DELETE and MERGE commits.
-- Compaction strategy is binpack (default), sort or zorder.
CALL lake.system.rewrite_data_files(
  table => 'db.events',
  where => 'event_date >= current_date() - INTERVAL 7 DAYS',
  options => map('partial-progress.enabled','true', 'max-concurrent-file-group-rewrites','10'));

CALL lake.system.rewrite_data_files(table => 'db.events', strategy => 'sort', sort_order => 'zorder(user_id, ts)');

CALL lake.system.expire_snapshots(table => 'db.events', older_than => TIMESTAMP '2026-09-24 00:00:00', retain_last => 10);
CALL lake.system.remove_orphan_files(table => 'db.events', dry_run => true);
CALL lake.system.rewrite_manifests('db.events');
CALL lake.system.rewrite_position_delete_files('db.events');
```

`rewrite_data_files` options:

| Option | Default |
|---|---|
| `target-file-size-bytes` | table's 512 MB |
| `min-file-size-bytes` | 75% of target |
| `max-file-size-bytes` | 180% of target |
| `min-input-files` | 5 |
| `max-concurrent-file-group-rewrites` | 5 |
| `max-file-group-size-bytes` | 100 GB |
| `partial-progress.enabled` | false |
| `partial-progress.max-commits` | 10 |
| `delete-file-threshold` | max int |
| `delete-ratio-threshold` | 0.3 |
| `remove-dangling-deletes` | false |
| `rewrite-all` | false |

Compaction is itself a Spark job. Tune it like one:
- Raise `max-concurrent-file-group-rewrites` to use the cluster.
- Use a `where` filter to compact only recent partitions.
- Use partial progress so a failure does not waste hours.
- Run it in its own job so it does not contend with writers.

## 8. Useful metadata tables (great for diagnosing small files)

```sql
SELECT count(*), avg(file_size_in_bytes)/1048576 AS avg_mb FROM lake.db.events.files;
SELECT partition, file_count, record_count FROM lake.db.events.partitions ORDER BY file_count DESC LIMIT 20;
SELECT committed_at, operation, summary['added-data-files'], summary['added-records'] FROM lake.db.events.snapshots ORDER BY committed_at DESC LIMIT 20;
SELECT * FROM lake.db.events.manifests;
```
