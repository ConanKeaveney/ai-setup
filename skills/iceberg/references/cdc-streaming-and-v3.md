# CDC, upserts, streaming ingestion, WAP, and the v3 upgrade

## CDC into Iceberg: the two-table pattern

Ryan Blue's "CDC MERGE pattern" (Tabular, 2023) is the reference design: a single MERGE-maintained mirror table loses change history (several changes to one key in a batch must be squashed) and cannot safely serve as a change stream. Keep both:

1. **Changelog (bronze) table** - append-only, every change event, long retention. Cheap appends, replayable, the true record.
2. **Mirror (silver) table** - current state per key, maintained by `MERGE` from the changelog, read-optimised.

```sql
CREATE TABLE cat.cdc.accounts_changelog (
  account_id bigint, op string,          -- 'I','U','D'
  seq bigint,                            -- source LSN / binlog position / Kafka offset: strictly ordered per key
  balance decimal(16,2), source_ts timestamp, ingest_ts timestamp)
USING iceberg PARTITIONED BY (day(ingest_ts));

CREATE TABLE cat.silver.accounts (
  account_id bigint NOT NULL, balance decimal(16,2), seq bigint, last_updated timestamp)
USING iceberg PARTITIONED BY (bucket(64, account_id))
TBLPROPERTIES ('format-version'='2',
  'write.merge.mode'='merge-on-read', 'write.update.mode'='merge-on-read', 'write.delete.mode'='merge-on-read',
  'write.metadata.delete-after-commit.enabled'='true');
ALTER TABLE cat.silver.accounts SET IDENTIFIER FIELDS account_id;
```

Incremental MERGE, one change per key, dropping events older than what the mirror already holds:

```sql
MERGE INTO cat.silver.accounts t
USING (
  SELECT s.* FROM (
    SELECT c.*, ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY seq DESC) AS rn
    FROM cat.cdc.accounts_changelog c
    WHERE ingest_ts >= TIMESTAMP '${last_watermark}' AND ingest_ts < TIMESTAMP '${this_watermark}'
  ) s
  LEFT JOIN cat.silver.accounts cur ON cur.account_id = s.account_id
  WHERE s.rn = 1 AND (cur.seq IS NULL OR s.seq > cur.seq)          -- stale/replayed events never reach MERGE
) s
ON t.account_id = s.account_id
WHEN MATCHED AND s.op = 'D' THEN DELETE
WHEN MATCHED THEN UPDATE SET t.balance = s.balance, t.seq = s.seq, t.last_updated = s.source_ts
WHEN NOT MATCHED AND s.op != 'D' THEN
  INSERT (account_id, balance, seq, last_updated) VALUES (s.account_id, s.balance, s.seq, s.source_ts);
```

Notes:

- Without the `rn = 1` dedup, MERGE fails with "target row matched more than one source row".
- The `s.seq > cur.seq` filter makes reruns idempotent. Filter stale rows in the source rather than with a no-op `WHEN MATCHED ... UPDATE`, because even a no-op update rewrites the file (CoW) or writes a delete + insert (MoR).
- Store the watermark in the snapshot summary (`snapshot-property.cdc.watermark` write option in DataFrame writes, or a control table) so a restart knows where it got to.
- Hard deletes arrive as `op='D'` with the last key; soft-delete instead (an `is_deleted` flag) if downstream consumers need tombstones.
- Instead of the ingest-time window you can read the changelog incrementally by snapshot: `spark.read.format("iceberg").option("start-snapshot-id", last).option("end-snapshot-id", cur).load("cat.cdc.accounts_changelog")` (append snapshots only).
- MERGE frequency trades latency against total work: each run rewrites (CoW) or adds deletes to (MoR) every touched file. Running twice as often roughly doubles cost. For minute-level latency on high-churn tables, use MoR, bucketed keys and frequent compaction - or a streaming engine with equality deletes (below).

### CDC stream as a dirty flag

When CDC arrives per cell (wide-column sources) or out of order, don't reassemble rows from the stream. Collect the changed keys per micro-batch, re-read the current rows from the source, and upsert them. Row-level consistency without cell ordering.

### SCD type 2 variant

Keep `valid_from`, `valid_to`, `is_current`. MERGE closes the current row (`UPDATE SET valid_to = s.source_ts, is_current = false`) and a second pass (or a `UNION ALL` source trick with a null merge key) inserts the new version. Partition by a time transform on `valid_from` only if queries filter on it; otherwise `bucket(key)`.

## Streaming ingestion

**Spark Structured Streaming**

```scala
df.writeStream.format("iceberg").outputMode("append")
  .trigger(Trigger.ProcessingTime(1, TimeUnit.MINUTES))     // docs: at least 1 minute
  .option("checkpointLocation", "s3://lake/chk/events")
  .option("fanout-enabled", "true")                          // skip per-batch sort for partitioned tables
  .toTable("cat.db.events")
```

- Sink supports `append` and `complete` only. Upserts: `foreachBatch { (batch, id) => batch.createOrReplaceTempView("s"); spark.sql("MERGE INTO ... USING (dedup of s) ...") }`. Make it idempotent (batch id or seq guard), because `foreachBatch` is at-least-once.
- Fast appends do not merge manifests, so streaming tables need `rewrite_manifests` as well as compaction and expiry.
- `Trigger.AvailableNow` suits scheduled catch-up jobs; Iceberg streaming reads honour the rate-limit options under it (1.11 release notes list AvailableNow support).
- Streaming **reads** only process append snapshots; overwrite/replace snapshots throw unless `streaming-skip-overwrite-snapshots` / `streaming-skip-delete-snapshots` are set. Read options: `stream-from-timestamp`, `streaming-max-files-per-micro-batch`, `streaming-max-rows-per-micro-batch`. A MERGE-maintained mirror table is therefore a poor streaming source - stream the changelog table instead.

**Flink / Kafka Connect**

- Flink sink with `upsert-enabled=true` and identifier fields writes **equality deletes** for every upsert: very cheap writes, expensive reads, and a v4 spec direction away from them. Requires frequent `rewrite_data_files` (with `delete-file-threshold` / `delete-ratio-threshold`) and, in Iceberg 1.11, Flink can run post-commit maintenance (compaction, manifest rewrite) inside the sink.
- The Iceberg Kafka Connect sink (in the Iceberg repo) does exactly-once appends with a coordinator; good for raw changelog landing.
- Debezium envelope -> changelog table via Kafka Connect, then Spark MERGE to the mirror, is the lowest-risk AWS pattern; Flink CDC direct-to-mirror is lower latency but higher maintenance.

## Reading changes out of Iceberg

```sql
CALL cat.system.create_changelog_view(
  table => 'silver.accounts',
  options => map('start-snapshot-id', '123', 'end-snapshot-id', '456'),
  identifier_columns => array('account_id'),     -- produces UPDATE_BEFORE / UPDATE_AFTER pairs
  changelog_view => 'accounts_changes');
SELECT * FROM accounts_changes WHERE _change_type IN ('UPDATE_AFTER','INSERT') ORDER BY _change_ordinal;
```

`net_changes => true` collapses intermediate changes (cannot combine with `compute_updates`). CoW carry-over rows are removed by default. Requires the snapshots in range still exist - align `expire_snapshots` retention with downstream consumers' worst-case lag.

**v3 row lineage**: every row gets `_row_id` (stable across rewrites and updates) and `_last_updated_sequence_number`. Incremental consumers can select rows with `_last_updated_sequence_number > :last_seen` and dedupe by `_row_id`, without a CDC column or snapshot diffing. Caveat: writers that update via equality deletes do not read the old row, so they cannot preserve its `_row_id` (Flink upserts); compaction preserves lineage (1.10+). Engines expose these as metadata columns (Spark 4 for lineage support; Flink 1.11 exposes them too).

## Write-audit-publish (WAP)

Branch style (preferred; needs `write.wap.enabled=true`):

```sql
ALTER TABLE db.t SET TBLPROPERTIES ('write.wap.enabled'='true');
ALTER TABLE db.t CREATE BRANCH IF NOT EXISTS `etl_20261001` RETAIN 3 DAYS;
SET spark.wap.branch = etl_20261001;
INSERT INTO db.t SELECT ...;                         -- lands on the branch, main untouched
-- audit: row counts, null checks, uniqueness, against db.t.`branch_etl_20261001`
RESET spark.wap.branch;
CALL cat.system.fast_forward('db.t', 'main', 'etl_20261001');   -- fails if main moved; then rebase or cherry-pick
ALTER TABLE db.t DROP BRANCH `etl_20261001`;
```

Staged-snapshot style: `SET spark.wap.id = run_42`, write (snapshot is staged, not current), audit with `VERSION AS OF <staged snapshot id>` (find it in `db.t.snapshots` where `summary['wap.id'] = 'run_42'`), then `CALL cat.system.publish_changes('db.t', 'run_42')`. Only append and dynamic-overwrite snapshots can be published/cherry-picked.

Caveats: S3 Tables managed snapshot expiry stops while any branch/tag exists - drop audit branches promptly. Databricks shows only `main`. Branches validate against the table's current schema.

## Upgrading v2 -> v3

What you gain: deletion vectors (cheaper MoR reads, one bitmap per data file), row lineage, default values, variant / geo / nanosecond types, multi-argument transforms, table encryption keys. What you lose: every reader below v3 support (Athena today; Iceberg Java < 1.8 cannot read DVs; Databricks external readers need 1.9.0+ per the Databricks skill; Trino/Presto/DuckDB versions vary). **One-way: the spec has no downgrade.**

Runbook:

1. Inventory every reader and writer of the table (query logs: Athena, Redshift Spectrum, Trino, Snowflake, Databricks, PyIceberg, BI extracts). Confirm each supports v3 *and the features you will use*.
2. Upgrade Iceberg libraries everywhere first (1.10+, ideally 1.11; Java 17).
3. Rehearse on a copy: `CALL cat.system.snapshot('db.t', 'db.t_v3_test')` (shares files, cannot expire) or a CTAS copy, then upgrade the copy and test every engine.
4. Optionally compact first so few v2 position delete files remain (`rewrite_data_files` with `delete-file-threshold` low, `rewrite_position_delete_files`).
5. `ALTER TABLE db.t SET TBLPROPERTIES ('format-version' = '3');` - metadata-only commit; data files stay. `next-row-id` starts at 0 and existing rows get IDs inherited lazily.
6. New MoR writes produce DVs; the first DV for a file absorbs that file's old position deletes.
7. Read from every engine; keep the previous metadata.json location noted (`metadata_log_entries`) for forensic purposes - it is not a rollback path for writers that have since written v3 features.

Do not upgrade tables that Athena or other v2-only engines read. Where Snowflake reads them, check that in-place upgrades of externally managed tables are recognised (reported unsupported for Snowflake-managed tables at v3 GA).

## Sources

Ryan Blue, [The CDC MERGE Pattern](https://tabular.medium.com/the-cdc-merge-pattern-b6f8b564177a) (read via browser; site blocks fetchers); [Iceberg Spark procedures - create_changelog_view](https://iceberg.apache.org/docs/latest/spark-procedures/#change-data-capture); [Spark Structured Streaming](https://iceberg.apache.org/docs/latest/spark-structured-streaming/); [Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/); [Branching and WAP](https://iceberg.apache.org/docs/latest/branching/); [Spec: row lineage, deletion vectors, format versioning](https://iceberg.apache.org/spec/); [Iceberg releases (1.8-1.11 notes)](https://iceberg.apache.org/releases/); [Dremio: MERGE INTO patterns and SCD2](https://www.dremio.com/blog/merge-into-patterns-for-apache-iceberg-upserts-and-scd-type-2/); [AWS iceberg-streaming-examples](https://github.com/aws-samples/iceberg-streaming-examples); [AWS S3 Tables v3 note](https://aws.amazon.com/blogs/aws/amazon-s3-tables-now-support-all-apache-iceberg-v3-data-types/).
