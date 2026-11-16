# Spark procedures, table properties and metadata tables

Verified against the Apache Iceberg **1.11.0** docs (`apache-iceberg-1.11.0` tag), with version arrivals found by diffing the 1.9.0, 1.10.0 and 1.11.0 tags. Items marked **unreleased** are on `main` after 1.11.0 and must not be assumed available.

## Calling procedures

```sql
CALL <catalog>.system.<procedure>(arg_name => value, ...);   -- named args (recommended), any order
CALL <catalog>.system.<procedure>(v1, v2);                    -- positional; only trailing optionals may be omitted
```

- Mixing named and positional is not allowed.
- Spark 3.x: requires `spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`.
- Spark 4.0+: procedures work natively without the extensions, and names are **case-sensitive**.
- Before Spark 4.2, catalog-scoped functions (`system.bucket`, `system.days`, `system.iceberg_version`) are not available through `spark_catalog` when it is a `SparkSessionCatalog`; call them through a `SparkCatalog`.
- Java/Scala equivalents: `SparkActions.get().rewriteDataFiles(table)...execute()`, `.expireSnapshots(table)`, `.deleteOrphanFiles(table)`, `.rewriteManifests(table)`, `.rewritePositionDeletes(table)`.

## Snapshot management

| Procedure | Arguments (required in bold) | Output | Notes |
|---|---|---|---|
| `rollback_to_snapshot` | **`table`**, **`snapshot_id`** long | `previous_snapshot_id`, `current_snapshot_id` | Target must be an ancestor |
| `rollback_to_timestamp` | **`table`**, **`timestamp`** | same | Snapshot current at that time |
| `set_current_snapshot` | **`table`**, `snapshot_id` or `ref` (exactly one) | same | Need not be an ancestor; `ref` = branch/tag |
| `cherrypick_snapshot` | **`table`**, **`snapshot_id`** | `source_snapshot_id`, `current_snapshot_id` | Only append and dynamic-overwrite snapshots |
| `publish_changes` | **`table`**, **`wap_id`** string | `source_snapshot_id`, `current_snapshot_id` | WAP staged snapshot; fails if several snapshots share the id (doc note 1.10+) |
| `fast_forward` | **`table`**, **`branch`**, **`to`** | `branch_updated`, `previous_ref`, `updated_ref` | e.g. `fast_forward('db.t','main','audit')` |

All of these invalidate cached Spark plans that reference the table.

## Metadata management

### `expire_snapshots`

| Arg | Type | Default | Notes |
|---|---|---|---|
| **`table`** | string | | |
| `older_than` | timestamp | 5 days ago (or `history.expire.max-snapshot-age-ms`) | |
| `retain_last` | int | 1 (or `history.expire.min-snapshots-to-keep`) | Ancestors kept regardless of age |
| `max_concurrent_deletes` | int | no pool | Thread pool for deletes |
| `stream_results` | boolean | false | Set `true` on big tables to avoid driver OOM |
| `snapshot_ids` | array<long> | | Expire specific ids (not the current one) |
| `clean_expired_metadata` | boolean | false | **1.10+**. Removes unused partition specs and schemas |

Output: `deleted_data_files_count`, `deleted_position_delete_files_count`, `deleted_equality_delete_files_count`, `deleted_manifest_files_count`, `deleted_manifest_lists_count`, `deleted_statistics_files_count`.

If both `older_than` and `retain_last` are omitted, the table properties apply. Snapshots referenced by a branch or tag are kept; ref expiry is governed by `history.expire.max-ref-age-ms` (default forever); `main` never expires. Never removes files a retained snapshot needs. Does **not** delete old metadata.json files (use `write.metadata.delete-after-commit.enabled`).

### `remove_orphan_files`

| Arg | Type | Default | Notes |
|---|---|---|---|
| **`table`** | string | | |
| `older_than` | timestamp | 3 days ago | Never shorter than the longest write + commit |
| `location` | string | table location | Restrict to a sub-directory, e.g. `.../data` |
| `dry_run` | boolean | false | Run first; returns candidates only |
| `max_concurrent_deletes` | int | no pool | |
| `stream_results` | boolean | false | **1.11+**. Output becomes a sample of up to 20,000 paths |
| `file_list_view` | string | | Temp view of `file_path`, `last_modified` to skip listing (e.g. from S3 Inventory) |
| `equal_schemes` | map | `map('s3a,s3n','s3')` | Schemes treated as equal |
| `equal_authorities` | map | | Authorities treated as equal |
| `prefix_mismatch_mode` | string | `ERROR` | `ERROR`, `IGNORE`, `DELETE` |
| `prefix_listing` | boolean | false | **1.10+**. Uses FileIO prefix listing (S3FileIO supports it) instead of Hadoop listing |

Output: `orphan_file_location`. Path comparison is by string - an authority/scheme change (bucket alias, `s3a` vs `s3`) can make live files look orphaned. On huge buckets prefer `file_list_view` fed from S3 Inventory.

### `rewrite_data_files`

| Arg | Type | Notes |
|---|---|---|
| **`table`** | string | |
| `strategy` | string | `binpack` (default) or `sort` |
| `sort_order` | string | `'id DESC NULLS LAST, name ASC NULLS FIRST'`, or `'zorder(c1,c2)'`; default table sort order. `hilbert(c1,c2)` is **unreleased** |
| `options` | map<string,string> | see below |
| `where` | string | Predicate selecting files that *may* contain matching rows. Keep it a simple literal predicate |

Options (general):

| Option | Default | Notes |
|---|---|---|
| `target-file-size-bytes` | `write.target-file-size-bytes` (512 MB) | |
| `min-file-size-bytes` | 75% of target | Smaller files always candidates |
| `max-file-size-bytes` | 180% of target | Larger files split |
| `min-input-files` | 5 | A group with at least this many files is rewritten (group must have 2+) |
| `rewrite-all` | false | Force everything |
| `max-file-group-size-bytes` | 100 GB | Unit of parallel work / commit |
| `max-concurrent-file-group-rewrites` | 5 | Raise on big clusters |
| `partial-progress.enabled` | false | Commit groups as they finish - use on large tables |
| `partial-progress.max-commits` | 10 | |
| `partial-progress.max-failed-commits` | = max-commits | |
| `use-starting-sequence-number` | true | Avoids conflicts with concurrent deletes |
| `rewrite-job-order` | none | `bytes-asc`, `bytes-desc`, `files-asc`, `files-desc` |
| `delete-file-threshold` | 2147483647 | Rewrite a data file once it has this many deletes |
| `delete-ratio-threshold` | 0.3 | Rewrite once 30% of rows are deleted (1.8+) |
| `output-spec-id` | current spec | Re-layout old data into a new partition spec |
| `remove-dangling-deletes` | false | Extra commit dropping delete files that apply to no live data |
| `max-files-to-rewrite` | null | **1.11+**. Cap eligible files per run |
| `max-file-group-input-files`, `cache-delete-files` | | **unreleased** |

Sort strategy: `compression-factor` (1.0), `shuffle-partitions-per-file` (1). Z-order: `var-length-contribution` (8), `max-output-size` (2147483647).

Output: `rewritten_data_files_count`, `added_data_files_count`, `rewritten_bytes_count`, `failed_data_files_count`, `removed_delete_files_count` (1.10+).

Rewrites preserve v3 row lineage (1.10+). Compaction commits are `replace` snapshots - they show up in history and are ignored by streaming readers.

### `rewrite_manifests`

| Arg | Type | Default | Notes |
|---|---|---|---|
| **`table`** | string | | |
| `use_caching` | boolean | **false since 1.10** (was true) | Caching raises executor memory |
| `spec_id` | int | current spec | Rewrite manifests of one spec |
| `sort_by` | array<string> | all partition transforms in spec order | **1.11+**. Cluster manifests by the partition fields queries filter on |

Output: `rewritten_manifests_count`, `added_manifests_count`.

### `rewrite_position_delete_files` (v2 merge-on-read)

Args: **`table`**, `options` map, `where` string (**1.10+**). Options mirror rewrite_data_files (`rewrite-all`, `min-input-files` 5, `target-file-size-bytes` = `write.delete.target-file-size-bytes` 64 MB, `partial-progress.*`, `max-files-to-rewrite` **1.10+**). Drops records pointing at files that are no longer live. Output: `rewritten_delete_files_count`, `added_delete_files_count`, `rewritten_bytes_count`, `added_bytes_count`. On v3 tables deletes are DVs; there are no position delete files to compact after rewriting.

## Table migration

| Procedure | Arguments | Output | Notes |
|---|---|---|---|
| `snapshot` | **`source_table`**, **`table`**, `location`, `properties`, `parallelism` (1) | `imported_files_count` | Test copy over the same files; cannot expire (does not own files) |
| `migrate` | **`table`**, `properties`, `drop_backup` (false), `backup_table_name` (`<t>_BACKUP_`), `parallelism` | `migrated_files_count` | Replaces a Hive/Spark table in place; fails for bucketed tables or non Parquet/ORC/Avro partitions |
| `add_files` | **`table`**, **`source_table`** (or `` `parquet`.`s3://path` ``), `partition_filter` map, `check_duplicate_files` (true), `parallelism` | `added_files_count`, `changed_partition_count` | No schema validation; Iceberg will later delete these files on expiry |
| `register_table` | **`table`**, **`metadata_file`** | `current_snapshot_id`, `total_records_count`, `total_data_files_count` | Only when the table is not live in another catalog |

`snapshot` and `migrate` gain `ignore_missing_files` on `main` (**unreleased**).

## Metadata, CDC, statistics, replication

| Procedure | Arguments | Output | Since |
|---|---|---|---|
| `ancestors_of` | **`table`**, `snapshot_id` | `snapshot_id`, `timestamp` | old |
| `create_changelog_view` | **`table`**, `changelog_view`, `options` (`start-snapshot-id` exclusive, `end-snapshot-id` inclusive, `start-timestamp`, `end-timestamp`), `net_changes` (false), `compute_updates`, `identifier_columns` | `changelog_view` | old |
| `compute_table_stats` | **`table`**, `snapshot_id`, `columns` array | `statistics_file` (Puffin, NDV theta sketches) | 1.8 |
| `compute_partition_stats` | **`table`**, `snapshot_id` | `partition_statistics_file` | 1.10 |
| `rewrite_table_path` | **`table`**, **`source_prefix`**, **`target_prefix`**, `start_version`, `end_version`, `staging_location`, `create_file_list` (true) | `latest_version`, `file_list_location`, `rewritten_manifest_file_paths_count`, `rewritten_delete_file_paths_count` | 1.8 |

Changelog view columns: `_change_type` (`INSERT`, `DELETE`, `UPDATE_BEFORE`, `UPDATE_AFTER`), `_change_ordinal`, `_commit_snapshot_id`. Carry-over rows from copy-on-write rewrites are removed by default; `SELECT * FROM db.t.changes` shows the raw form.

`rewrite_table_path` is for cross-region/account DR copies: it stages rewritten metadata and a CSV copy plan; you copy the files (DistCp, S3 Batch Replication) and then `register_table` at the target. Partition statistics files block it in 1.10; 1.11 adds support.

## Table properties (1.11.0 defaults)

### Write

| Property | Default | Notes |
|---|---|---|
| `write.format.default` | parquet | |
| `write.delete.format.default` | data file format | |
| `write.target-file-size-bytes` | 536870912 (512 MB) | |
| `write.delete.target-file-size-bytes` | 67108864 (64 MB) | |
| `write.distribution-mode` | not set; Spark uses `hash` (or `range` if a sort order exists) | `none`, `hash`, `range` |
| `write.{delete,update,merge}.distribution-mode` | not set | Per-operation override |
| `write.{delete,update,merge}.mode` | copy-on-write | `merge-on-read` needs v2+ |
| `write.{delete,update,merge}.isolation-level` | serializable | or `snapshot` |
| `write.delete.granularity` | partition | Spark write option `delete-granularity` defaults to `file` since 1.8 |
| `write.parquet.compression-codec` | zstd | zstd, brotli, lz4, gzip, snappy, uncompressed |
| `write.parquet.row-group-size-bytes` | 128 MB | |
| `write.parquet.page-size-bytes` | 1 MB | |
| `write.parquet.page-version` | v1 | **1.11+** |
| `write.parquet.bloom-filter-enabled.column.<col>` | not set | Point lookups on high-cardinality keys |
| `write.parquet.bloom-filter-fpp.column.<col>` | 0.01 | |
| `write.parquet.shred-variants` | false | **1.11+**. Shredded variant encoding |
| `write.metadata.metrics.default` | truncate(16) | `none`, `counts`, `truncate(n)`, `full` |
| `write.metadata.metrics.column.<col>` | not set | e.g. `full` on sort keys, `none` on blobs |
| `write.metadata.metrics.max-inferred-column-defaults` | 100 | Wide tables: only first 100 columns get stats |
| `write.metadata.delete-after-commit.enabled` | false | |
| `write.metadata.previous-versions-max` | 100 | |
| `write.metadata.compression-codec` | none | or gzip |
| `write.object-storage.enabled` | false | Hash prefixes to avoid S3 throttling |
| `write.object-storage.partitioned-paths` | true | false drops partition values from paths |
| `write.data.path` / `write.metadata.path` | table location + `/data` / `/metadata` | Do not set `write.metadata.path` on Databricks-managed tables |
| `write.wap.enabled` | false | |
| `write.spark.fanout.enabled` | false | Fanout writer: no clustering needed, more memory |
| `write.spark.accept-any-schema` | not set | Allow writer-driven schema change |
| `write.summary.partition-limit` | 0 | Per-partition stats in snapshot summaries |

### Read

`read.split.target-size` 128 MB; `read.split.metadata-target-size` 32 MB; `read.split.planning-lookback` 10; `read.split.open-file-cost` 4 MB; `read.parquet.vectorization.enabled` true; `read.parquet.vectorization.batch-size` 5000 (lower it, or disable vectorization, on `OversizedAllocationException`).

### Table behaviour

| Property | Default |
|---|---|
| `commit.retry.num-retries` | 4 |
| `commit.retry.min-wait-ms` / `max-wait-ms` / `total-timeout-ms` | 100 / 60000 / 1800000 |
| `commit.status-check.num-retries` | 3 |
| `commit.manifest.target-size-bytes` | 8 MB |
| `commit.manifest.min-count-to-merge` | 100 |
| `commit.manifest-merge.enabled` | true |
| `history.expire.max-snapshot-age-ms` | 432000000 (5 days) |
| `history.expire.min-snapshots-to-keep` | 1 |
| `history.expire.max-ref-age-ms` | Long.MAX_VALUE (forever) |
| `gc.enabled` | true |
| `format-version` | 2 (since 1.4.0) |
| `encryption.key-id` / `encryption.data-key-length` | not set / 16 bytes |
| `comment` | not set |

### Spark write options (per write, override table props)

`write-format`, `target-file-size-bytes`, `check-nullability`, `snapshot-property.<key>` (custom summary metadata - useful to stamp a job id or CDC watermark), `fanout-enabled`, `check-ordering`, `isolation-level`, `validate-from-snapshot-id`, `compression-codec`, `distribution-mode`, `delete-granularity` (default `file`), `mergeSchema`, `shred-variants` (1.11+).

### Spark session settings worth knowing

`spark.sql.iceberg.distribution-mode`, `spark.wap.id`, `spark.wap.branch`, `spark.sql.iceberg.merge-schema` (false), `spark.sql.sources.partitionOverwriteMode=dynamic`, `spark.sql.adaptive.advisoryPartitionSizeInBytes` (governs output file size when distribution mode is not `none` - it is in-memory size, so set it larger than the target file size).

### Catalog-level defaults

`spark.sql.catalog.<cat>.table-default.<prop>` sets a default on tables created through that catalog; `spark.sql.catalog.<cat>.table-override.<prop>` enforces it. Good place to put `format-version`, MoR modes and `write.metadata.delete-after-commit.enabled` for a whole estate.

## Metadata tables

Query as `db.t.<name>`; time travel works on them (`db.t.files VERSION AS OF ...`).

| Table | Use |
|---|---|
| `history` | Snapshot lineage incl. rollbacks (`is_current_ancestor`) |
| `metadata_log_entries` | metadata.json history |
| `snapshots` | `committed_at`, `snapshot_id`, `operation`, `summary` map (added/deleted files, records) |
| `refs` | Branches and tags with retention |
| `files` / `data_files` / `delete_files` | Current snapshot's files: `content`, `file_path`, `partition`, `record_count`, `file_size_in_bytes`, column stats |
| `all_files` / `all_data_files` / `all_delete_files` | Across all retained snapshots |
| `manifests` / `all_manifests` | Manifest counts and sizes; added/existing/deleted counts |
| `entries` / `all_entries` | Manifest entries incl. status and sequence numbers |
| `partitions` | Per-partition record/file counts, delete counts, `last_updated_at` |
| `position_deletes` | Position delete rows (DVs surfaced since 1.8) |

Health-check SQL:

```sql
-- Small-file hot spots by partition
SELECT partition, count(*) AS files, round(avg(file_size_in_bytes)/1048576,1) AS avg_mb
FROM db.t.data_files GROUP BY partition HAVING count(*) > 50 ORDER BY files DESC LIMIT 20;

-- Commit rate per hour (streaming pressure) and operation mix
SELECT date_trunc('hour', committed_at) AS h, operation, count(*) FROM db.t.snapshots
GROUP BY 1, 2 ORDER BY 1 DESC LIMIT 48;

-- Delete debt (merge-on-read health)
SELECT sum(position_delete_file_count) pos_files, sum(equality_delete_file_count) eq_files,
       sum(position_delete_record_count) pos_rows FROM db.t.partitions;

-- Spec spread after partition evolution
SELECT spec_id, count(*) FROM db.t.files GROUP BY spec_id;
```

## Sources

[Spark procedures](https://iceberg.apache.org/docs/latest/spark-procedures/), [Configuration](https://iceberg.apache.org/docs/latest/configuration/), [Spark configuration](https://iceberg.apache.org/docs/latest/spark-configuration/), [Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/), [Spark queries](https://iceberg.apache.org/docs/latest/spark-queries/), [Maintenance](https://iceberg.apache.org/docs/latest/maintenance/), [Releases](https://iceberg.apache.org/releases/), and the docs at tags `apache-iceberg-1.9.0`, `1.10.0`, `1.11.0` in [apache/iceberg](https://github.com/apache/iceberg). Spark delete-granularity default checked in `SparkWriteConf.java` at tags 1.7.0 (table default) and 1.8.0+ (`FILE`). Glue optimizer vectorization tip: [AWS Glue optimizer notes](https://docs.aws.amazon.com/glue/latest/dg/optimizer-notes.html).
