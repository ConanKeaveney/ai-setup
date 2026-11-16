---
name: iceberg
description: Reference for Apache Iceberg (v2/v3) on AWS S3, used from Spark, Databricks and Snowflake: concepts glossary, when-to-use (Iceberg vs Delta vs Hudi), design, DDL, MERGE/upserts, CDC, maintenance, performance, catalogs, v3 upgrade, interop with Glue, S3 Tables, Unity Catalog and Snowflake. Load whenever the work touches an Iceberg table, catalog or table-format decision. Triggers: "iceberg", "what is iceberg", "iceberg vs delta", "open table format", "snapshot", "time travel", "rollback", "manifest", "compaction", "small files", "rewrite_data_files", "expire_snapshots", "orphan files", "hidden partitioning", "partition evolution", "schema evolution", "merge into", "upsert", "copy-on-write", "merge-on-read", "delete files", "equality deletes", "deletion vectors", "row lineage", "v3 upgrade", "glue catalog", "S3 Tables", "REST catalog", "Polaris", "UniForm", "managed iceberg", "Snowflake iceberg", "WAP", "CDC into iceberg", "commit conflict".
---

# Apache Iceberg

Reference for a Staff Data Platform engineer running an Iceberg lakehouse on AWS (S3 + Glue / S3 Tables)
with Spark, partly moving to Databricks, with Snowflake as a reader/writer. Deeper material:

- [references/procedures-and-properties.md](references/procedures-and-properties.md) - every Spark procedure with arguments, options, outputs and the version each arrived in; table properties with defaults; metadata tables; health-check SQL.
- [references/catalogs-and-interop.md](references/catalogs-and-interop.md) - Glue, S3 Tables, REST, Hive, Nessie, Polaris, Unity Catalog, Snowflake; Spark configs for each; Databricks and Snowflake interop; engine v3 support on AWS.
- [references/cdc-streaming-and-v3.md](references/cdc-streaming-and-v3.md) - CDC/upsert patterns with SQL, streaming ingestion, WAP, the v2-to-v3 upgrade runbook.
- [references/concepts.md](references/concepts.md) - plain-English glossary of about 70 terms, typical use cases, the full when-to-use table, and an Iceberg vs Delta vs Hudi comparison. Use it for "what is", "explain" or "should we use Iceberg" questions.

If the task is Databricks-specific (Delta, UC grants, Lakeflow, liquid clustering), also load the `databricks` skill; for Snowflake cost, warehouses or catalog integrations, also load the `snowflake` skill.

## When to use it / when not to

| Situation | Verdict |
|---|---|
| Several engines share large tables on S3 (Spark, Athena, Trino, Snowflake, Databricks) | **Iceberg** - widest engine support, open REST catalog |
| Large append-mostly event or fact tables, filtered by time | **Iceberg** - hidden partitioning, file-level pruning, partition evolution |
| CDC mirror with minutes of latency | **Iceberg** with MoR and owned, scheduled compaction |
| All-Databricks stack, no outside engines | **Delta Lake** - CDF, generated columns, constraints are Delta-only there; UniForm adds Iceberg reads later |
| Very high-rate, skewed-key upserts on a huge table | **Consider Hudi** - record-level index avoids joining against the table |
| Write-once archive, one reader, never updated | **Plain Parquet** is often enough |
| Millisecond point lookups or high-rate single-row updates | **OLTP database or key-value store** (Postgres, Aurora, DynamoDB) |
| Small BI mart used only in one warehouse | **Warehouse native tables** - fewer moving parts, full features |
| Sub-second, high-concurrency dashboards or seconds-level freshness | **Real-time store or streaming system** (ClickHouse, Pinot, OpenSearch, Flink), sinking to Iceberg |
| Athena reads the table and v3 is tempting | **Iceberg, but stay on v2** - Athena cannot read v3 |

Reasons, more rows and the format comparison are in [references/concepts.md](references/concepts.md).

## Current facts (re-check before quoting versions)

- Latest documented Apache Iceberg release: **1.11.0 (19 May 2026)**. 1.12.0 was tagged on GitHub on 30 Sep 2026 but isn't on the docs site yet; check its release notes before relying on 1.11 behaviour.
- 1.11.0 requires **Java 17+**, deprecates Spark 3.4, adds Spark 4.1. Runtime jars ship for Spark 3.5 (Scala 2.12/2.13), 4.0 and 4.1.
- Spec: v1, v2, v3 are adopted. **v4 is under active development, not adopted** (relative paths in metadata; no new equality deletes).
- `format-version` default for new tables is **2** (since 1.4.0). Parquet default codec is **zstd** (since 1.4.0).
- v3 engine support is uneven. Spark-on-AWS (EMR 7.12+, Glue 5.1+, S3 Tables) does deletion vectors and row lineage; **Athena cannot read v3 at all**; Snowflake v3 GA 7 May 2026; Databricks v3 needs DBR 18 LTS+. Details in the interop reference.
- Spark 3.x needs `IcebergSparkSessionExtensions` for `CALL`, `MERGE`, `UPDATE`, `DELETE` and partition DDL. Spark 4.0+ supports procedures natively, and they are **case-sensitive** there.

## Inspect first

Before recommending or changing anything, establish:

1. Engine and version, Iceberg library version, and catalog type (Glue / S3 Tables / REST / Unity / Snowflake).
2. `format-version` and the row-level modes: `SHOW TBLPROPERTIES db.t`.
3. Every engine and job that **writes** to the table (streaming writers, Glue optimizers, S3 Tables maintenance, Databricks, Snowflake).
4. The actual file and snapshot shape, from metadata tables, not assumptions:

```sql
SELECT content, count(*) AS files, round(avg(file_size_in_bytes)/1048576,1) AS avg_mb,
       sum(CASE WHEN file_size_in_bytes < 32*1048576 THEN 1 ELSE 0 END) AS under_32mb
FROM db.t.files GROUP BY content;          -- content: 0=data, 1=position deletes/DVs, 2=equality deletes
SELECT count(*), min(committed_at), max(committed_at) FROM db.t.snapshots;
SELECT count(*), sum(added_data_files_count) FROM db.t.manifests;
SELECT partition, file_count, record_count, position_delete_file_count, equality_delete_file_count
FROM db.t.partitions ORDER BY file_count DESC LIMIT 20;
```

## The metadata tree

```
catalog  ── pointer ──>  vN.metadata.json   (schemas, partition specs, sort orders, properties,
                              │               snapshot list, refs = branches/tags, snapshot-log, metadata-log)
                              └─ snapshot S ─> manifest list  snap-*.avro  (one row per manifest + partition
                                                    │                       range summary per manifest)
                                                    ├─ data manifest  *.avro ─> data files (Parquet)
                                                    │      one row per file: path, partition tuple, record
                                                    │      count, per-column lower/upper bounds, null counts
                                                    └─ delete manifest *.avro ─> delete files
                                                           v2: position deletes, equality deletes
                                                           v3: deletion vectors (Roaring bitmaps in Puffin)
```

- **Commit = atomic swap of the catalog pointer** from one metadata.json to the next (optimistic concurrency). A loser re-reads, re-validates against its isolation level, and retries (`commit.retry.num-retries`, default 4). The catalog is what makes it atomic; S3 alone cannot.
- **Planning prunes top-down**: manifest-list partition summaries skip whole manifests; manifest column stats skip files; Parquet row-group stats skip row groups. No directory listing, ever. Partition values live in metadata, not paths.
- **Sequence numbers** order changes. An equality delete applies to data files with a strictly *lower* data sequence number; a position delete or DV to files with lower-or-equal. Compaction keeps the starting sequence number (`use-starting-sequence-number`, default true) so it does not "un-delete" rows deleted concurrently.
- **v3 deletion vectors**: at most one DV per data file per snapshot; writers merge new deletes into it. Position delete files must not be added to v3 tables (existing ones stay valid). Spark writes DVs for v3 since 1.8.0.
- Each commit writes a new metadata.json, manifest list and at least one manifest. High-frequency commits mean metadata bloat - that is the cause of slow planning more often than data size.

## Snapshots and time travel

```sql
SELECT * FROM db.t TIMESTAMP AS OF '2026-09-30 00:00:00';  -- uses that snapshot's schema
SELECT * FROM db.t VERSION AS OF 10963874102873;            -- snapshot id; snapshot's schema
SELECT * FROM db.t VERSION AS OF 'audit-branch';             -- branch: uses the TABLE's current schema
SELECT * FROM db.t VERSION AS OF 'eoy-2025';                 -- tag: snapshot's schema
SELECT * FROM db.t.`branch_audit-branch`;                    -- identifier form (backquote names with '-')
CALL cat.system.rollback_to_snapshot('db.t', 10963874102873);
CALL cat.system.rollback_to_timestamp('db.t', TIMESTAMP '2026-09-30 00:00:00');
CALL cat.system.set_current_snapshot(table => 'db.t', ref => 'eoy-2025');  -- need not be an ancestor
```

DataFrame: `.option("snapshot-id", ...)`, `"as-of-timestamp"` (ms), `"branch"`, `"tag"`; incremental append reads with `"start-snapshot-id"` (exclusive) / `"end-snapshot-id"` (inclusive). Time travel only reaches snapshots not yet expired - retention is a product decision, not a default.

### Partial recovery

When good writes landed after the bad one, `rollback_to_snapshot` discards them too. Instead `MERGE` from `VERSION AS OF <id>` into the live table, bounded to the affected keys or time range; dry-run first (report would-recover counts), then check counts after. Pick one strategy:

| Strategy | When | On match |
|---|---|---|
| **Append-only** (default when unsure) | Rows were deleted; live rows are correct | Do nothing; insert only the missing rows |
| **Live wins** | Both have data; live is newer where present | `SET col = COALESCE(live.col, snap.col)` |
| **Snapshot is truth** | A bad UPDATE corrupted live rows | Overwrite from the snapshot |

Recovery only ever adds back. Never overwrite the table wholesale.

## Hidden partitioning and partition evolution

Transforms: `identity`, `bucket(N, col)`, `truncate(W, col)`, `year`, `month`, `day`, `hour` (Spark also accepts `years/months/days/hours`), plus `void` for dropped fields. Users filter on the **source column** (`WHERE ts >= ...`); Iceberg derives the partition predicate. Do not add a derived `event_date` column just to partition on it.

```sql
CREATE TABLE cat.db.events (id bigint, ts timestamp, tenant string, payload string)
USING iceberg PARTITIONED BY (day(ts), bucket(16, tenant))
TBLPROPERTIES ('format-version'='2', 'write.merge.mode'='merge-on-read');

ALTER TABLE cat.db.events REPLACE PARTITION FIELD ts_day WITH hour(ts);  -- metadata-only
ALTER TABLE cat.db.events ADD PARTITION FIELD bucket(32, id) AS id_bucket;
ALTER TABLE cat.db.events DROP PARTITION FIELD id_bucket;
ALTER TABLE cat.db.events WRITE ORDERED BY tenant, ts;                    -- sort order for writes/compaction
```

- Evolution is **metadata-only**: old files keep their old spec, planning runs per spec. To physically re-layout old data use `rewrite_data_files` with option `output-spec-id`.
- Size partitions to the data: aim for hundreds of MB to a few GB per partition per write window. Over-partitioning (e.g. `hour` on a low-volume table, `identity` on a high-cardinality key) is the most common cause of small files and slow planning. `bucket` is for join/MERGE keys and spreading high-cardinality keys.
- After evolving, dynamic `INSERT OVERWRITE` replaces partitions of the *new* spec - another reason to prefer `MERGE INTO`.

## Schema evolution

By field ID, so no data rewrite and no "zombie" columns: add, drop, rename, reorder, widen (`int->long`, `float->double`, decimal precision up), required->optional. v3 also allows `date -> timestamp/timestamp_ns` and column defaults (`initial-default`, `write-default`), but **engine support for defaults is partial** - check before relying on it. Drop or replace a partition field / identifier field before dropping its source column. Through a Hive Metastore catalog, position-shifting changes (`FIRST`/`AFTER`, dropping a non-last column) fail unless HMS's `hive.metastore.disallow.incompatible.col.type.changes` is disabled. Writers can auto-add columns with table property `write.spark.accept-any-schema=true` plus the DataFrame write option `mergeSchema=true` (or session `spark.sql.iceberg.merge-schema`); Iceberg 1.11 adds initial MERGE INTO schema evolution for Spark 4.1 only.

## Copy-on-write vs merge-on-read

Set per operation: `write.delete.mode`, `write.update.mode`, `write.merge.mode` (default `copy-on-write` for all three; MoR needs v2+). Isolation: `write.{delete,update,merge}.isolation-level` = `serializable` (default) or `snapshot`.

| Situation | Choose | Why |
|---|---|---|
| Few, large batch rewrites of whole partitions; read-heavy BI | **CoW** | Readers never merge deletes; cost paid once at write |
| Frequent small MERGE/UPDATE/DELETE scattered across many files (CDC, GDPR deletes, late-arriving corrections) | **MoR** | Rewriting a 512 MB file to change one row is the write-amplification trap |
| Streaming/micro-batch upserts every few minutes | **MoR + scheduled compaction** | Keeps commits small; compaction folds deletes back in |
| v3 table with MoR | **MoR (DVs)** | One bitmap per data file; much cheaper reads than v2 position-delete files |
| Readers that cannot apply delete files (old engines, some external readers) | **CoW** | Guarantees plain data files only |
| Commit conflicts between a MERGE and compaction | MoR + `snapshot` isolation on the writer, or partition-scoped compaction | Narrows the validation window |

MoR cost is proportional to delete-file count, so MoR without compaction degrades steadily. Spark writes **file-scoped** position deletes by default since 1.8.0 (table property `write.delete.granularity` defaults to `partition`, but Spark's write default is `file`).

## Maintenance runbook (Spark SQL)

Order matters: compact first so the files it replaces become unreferenced, then expire so they are deleted, then clean orphans. Arguments verified against the 1.11.0 docs.

```sql
-- 1. Compact data files (bin-pack by default; also applies deletes and can drop dangling ones).
CALL cat.system.rewrite_data_files(
  table => 'db.t',
  where => 'ts >= "2026-09-29 00:00:00"',                  -- scope to recently written partitions (literal predicate)
  options => map('min-input-files','5', 'partial-progress.enabled','true',
                 'max-concurrent-file-group-rewrites','10', 'remove-dangling-deletes','true'));
-- sort or z-order instead of bin-pack:
CALL cat.system.rewrite_data_files(table => 'db.t', strategy => 'sort', sort_order => 'zorder(tenant, id)');

-- 2. (v2 MoR only) compact position delete files and drop dangling records.
CALL cat.system.rewrite_position_delete_files(table => 'db.t', options => map('rewrite-all','true'));

-- 3. Re-cluster manifests when planning is slow or manifests are many and small.
CALL cat.system.rewrite_manifests(table => 'db.t');           -- use_caching defaults to false since 1.10

-- 4. Expire snapshots: removes snapshots AND files only they reference (irreversible).
CALL cat.system.expire_snapshots(table => 'db.t', older_than => TIMESTAMP '2026-09-24 00:00:00',
                                  retain_last => 50, stream_results => true,
                                  clean_expired_metadata => true);   -- clean_expired_metadata: 1.10+

-- 5. Orphan files from failed writes. Dry-run first; never older_than < longest writer runtime.
CALL cat.system.remove_orphan_files(table => 'db.t', dry_run => true);
CALL cat.system.remove_orphan_files(table => 'db.t', older_than => TIMESTAMP '2026-09-28 00:00:00');
```

Also set `write.metadata.delete-after-commit.enabled=true` (keeps `write.metadata.previous-versions-max`, default 100) so old metadata.json files do not pile up - expire_snapshots does not remove them.

Cadence that works for most tables: compaction hourly-to-daily on hot partitions; expire daily; rewrite_manifests weekly or when `manifests` count climbs; orphans weekly. Defaults when arguments are omitted: expire uses `history.expire.max-snapshot-age-ms` (5 days) and `min-snapshots-to-keep` (1); orphan removal uses 3 days. Snapshots held by branches/tags are never expired; `main` never expires.

**Do not double-run maintenance.** If Glue table optimizers or S3 Tables managed maintenance are on, your own Spark jobs compete with them (commit conflicts, duplicated cost). Pick one owner per table. S3 Tables snapshot management **fails for the whole table** if any branch/tag exists or `history.expire.*` properties are set.

## Catalogs compared

| Catalog | Spark `type` / impl | Strengths | Watch out |
|---|---|---|---|
| **AWS Glue Data Catalog** (`GlueCatalog`) | `glue` | Native on AWS; optimistic locking; IAM/Lake Formation; Athena/EMR/Redshift read it; managed optimizers | `glue.skip-archive` default true (keep it - streaming creates a version per commit); single-level namespaces |
| **Glue Iceberg REST endpoint** | `rest`, `uri=https://glue.<region>.amazonaws.com/iceberg`, SigV4 `glue` | Standard REST clients; reaches S3 Tables via `catalogs/s3tablescatalog/<bucket>` | No views; check v3 support per op |
| **Amazon S3 Tables** | `rest` (S3 Tables endpoint, SigV4 `s3tables`) or `S3TablesCatalog` | Managed compaction / snapshot expiry / unreferenced-file removal on by default | No CTAS via REST (`stage-create`), purge-only drops, 50 MB metadata.json cap, conflicts with your own maintenance |
| **Iceberg REST (generic)** | `rest` | Engine-neutral; server-side commit; credential vending; remote scan planning (1.11) | Capabilities vary by server - check `/v1/config` |
| **Hive Metastore** | `hive` | Legacy compatibility | Lock-based commits, HMS schema checks; avoid for new estates |
| **Nessie** | `nessie` | Git-like multi-table branches and commits | Extra service to run; ecosystem narrower than REST |
| **Apache Polaris** (TLP Feb 2026) / Snowflake Open Catalog / Horizon | `rest` | Vendor-neutral REST, RBAC, credential vending, federation | Horizon serves Snowflake-managed tables only |
| **Databricks Unity Catalog** | `rest`, `uri=https://<ws>/api/2.1/unity-catalog/iceberg-rest` | Governance across Delta + Iceberg; external read/write for managed Iceberg | Needs `EXTERNAL USE SCHEMA`; UniForm/foreign tables are read-only externally |
| JDBC / Hadoop | `jdbc` / `hadoop` | Tests, local dev | Hadoop catalog on S3 is unsafe for concurrent writers |

**Rule: one catalog owns writes for a table.** Registering the same metadata.json in two catalogs (via `register_table`) and writing from both corrupts history. Others should read through federation or REST. Configs for each are in the interop reference.

## CDC and upserts (summary)

- Land raw changes append-only in a **changelog table** (op, key, source sequence/LSN, payload); derive the **mirror table** with `MERGE INTO`, deduplicated to one change per key per batch (`ROW_NUMBER() OVER (PARTITION BY key ORDER BY seq DESC) = 1`), with a guard so older events never overwrite newer ones. MERGE without dedup fails with "matched more than one source row".
- Mirror table: MoR, `bucket(N, key)` partitioning plus a time transform if queries need it, `SET IDENTIFIER FIELDS key`, compaction scheduled.
- Spark Structured Streaming's Iceberg sink is **append/complete only**; upserts go through `foreachBatch` + MERGE. Flink's sink can upsert using **equality deletes** - cheap to write, expensive to read; it needs aggressive compaction.
- Read changes out with incremental reads or `create_changelog_view` (net changes, pre/post images via identifier columns). v3 row lineage (`_row_id`, `_last_updated_sequence_number`) gives row-level change tracking without a CDC column.

Full SQL and the streaming settings are in [references/cdc-streaming-and-v3.md](references/cdc-streaming-and-v3.md).

## Branching, tagging and WAP

```sql
ALTER TABLE db.t CREATE BRANCH `audit` RETAIN 7 DAYS WITH SNAPSHOT RETENTION 3 SNAPSHOTS;
ALTER TABLE db.t CREATE TAG `eoy-2025` AS OF VERSION 1234 RETAIN 365 DAYS;   -- default retention: forever
INSERT INTO db.t.branch_audit SELECT ...;                                    -- branch must already exist
CALL cat.system.fast_forward('db.t', 'main', 'audit');                       -- publish after checks
ALTER TABLE db.t DROP BRANCH `audit`;
```

WAP, two styles: (a) branch - `write.wap.enabled=true`, `SET spark.wap.branch = audit`, write, validate, `fast_forward`; (b) staged snapshot - `SET spark.wap.id = <id>`, write (snapshot is staged, not current), validate, `CALL cat.system.publish_changes('db.t', '<id>')` (cherry-picks; fails if two snapshots share the id). Branch writes validate against the table's current schema. Databricks does not support Iceberg branches/tags (main only), and S3 Tables' managed expiry stops if any exist.

## Key table properties

| Property | Default | Set it when |
|---|---|---|
| `format-version` | 2 | `3` only after every reader/writer supports v3 (one-way) |
| `write.{delete,update,merge}.mode` | copy-on-write | MoR for frequent small row-level changes |
| `write.target-file-size-bytes` | 512 MB | Lower (128-256 MB) for small tables or point-lookup heavy reads |
| `write.distribution-mode` | engine default (Spark: `hash`; `range` if a sort order exists) | `none` only with pre-clustered input; `range` for global sort |
| `write.parquet.compression-codec` | zstd | `snappy` only for old readers |
| `write.metadata.delete-after-commit.enabled` / `previous-versions-max` | false / 100 | Turn on for any frequently committed table (not on Databricks-managed tables) |
| `history.expire.max-snapshot-age-ms` / `min-snapshots-to-keep` / `max-ref-age-ms` | 5 days / 1 / forever | Encode time-travel SLA; unset on S3 Tables |
| `commit.retry.num-retries` | 4 | Raise for many concurrent writers |
| `commit.manifest-merge.enabled` | true | Leave on |
| `write.object-storage.enabled` | false | High-throughput writes to one S3 prefix (throttling, 503 SlowDown) |
| `write.wap.enabled` | false | WAP workflows |
| `gc.enabled` | true | `false` for tables created by `snapshot`/`add_files` over files you do not own |
| `write.spark.accept-any-schema` | (unset) | Allow writer-driven schema evolution |

Full table with read, Parquet, commit and Spark write options: [references/procedures-and-properties.md](references/procedures-and-properties.md).

## Common pitfalls

1. **Streaming without maintenance**: thousands of snapshots, manifests and tiny files; planning time explodes before scan time does.
2. **Orphan cleanup with a short `older_than`** deletes files of in-flight writes - corrupts the table. Never under the longest write/commit duration; 3 days default exists for a reason.
3. **S3 lifecycle expiration rules on table prefixes** delete live data or manifests. Exclude Iceberg paths; let Iceberg delete.
4. **Two tables sharing one S3 location** (or overlapping paths): orphan cleanup on one deletes the other's files.
5. **`DROP TABLE` semantics differ** by catalog/engine (Spark keeps files unless `PURGE`; S3 Tables only allows purge). Confirm before running.
6. **Static `INSERT OVERWRITE`** without a `PARTITION` clause replaces the whole table; use dynamic mode (`spark.sql.sources.partitionOverwriteMode=dynamic`) or, better, MERGE.
7. **Over-partitioning** and partitioning on high-cardinality identity columns.
8. **Upgrading to v3 while any reader is v2-only** (Athena, older Trino/Iceberg < 1.9 clients) breaks those readers. No downgrade in the spec.
9. **MoR with no compaction**, and equality deletes from Flink/CDC left uncompacted.
10. **Commit storms**: many writers or very frequent micro-batches against one table produce `CommitFailedException` retries; batch larger, serialise writers, or partition-scope compaction.
11. **Using `snapshot`/`migrate`/`add_files` then `expire_snapshots`**: Iceberg now owns and may delete the original files (`snapshot` tables block this; `add_files` does not).
12. **Running maintenance from two places** (your Spark job + Glue optimizer/S3 Tables/Databricks predictive optimization).
13. **Assuming every engine sees branches, v3 types or defaults** - check each engine.
14. **Logical delete ≠ physical delete.** A `DELETE` writes delete files; bytes leave S3 only after compaction + snapshot expiry + orphan cleanup. Size the maintenance cadence to the deletion SLA.

## Verify after changes

- After compaction: file count and avg size before/after from `files`, plus identical `count(*)` on the current snapshot.
- After expiry: snapshot count and oldest retained `committed_at` still meet the time-travel requirement.
- After partition evolution: `SELECT spec_id, count(*) FROM db.t.files GROUP BY spec_id` shows new writes on the new spec.
- After a v3 upgrade: run a read from **every** engine that touches the table; name any you could not test.

## Sources

Official Apache Iceberg (1.11.0 docs and `main` spec): [Spec](https://iceberg.apache.org/spec/), [Spark procedures](https://iceberg.apache.org/docs/latest/spark-procedures/), [Configuration](https://iceberg.apache.org/docs/latest/configuration/), [Spark DDL](https://iceberg.apache.org/docs/latest/spark-ddl/), [Spark writes](https://iceberg.apache.org/docs/latest/spark-writes/), [Spark queries](https://iceberg.apache.org/docs/latest/spark-queries/), [Spark configuration](https://iceberg.apache.org/docs/latest/spark-configuration/), [Maintenance](https://iceberg.apache.org/docs/latest/maintenance/), [Partitioning](https://iceberg.apache.org/docs/latest/partitioning/), [Evolution](https://iceberg.apache.org/docs/latest/evolution/), [Branching](https://iceberg.apache.org/docs/latest/branching/), [AWS](https://iceberg.apache.org/docs/latest/aws/), [Releases](https://iceberg.apache.org/releases/). Version diffs were taken from the `apache-iceberg-1.9.0`, `1.10.0` and `1.11.0` tags on [GitHub](https://github.com/apache/iceberg).

AWS: [S3 Tables maintenance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-maintenance.html), [S3 Tables REST endpoint](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html), [Glue Iceberg REST endpoint](https://docs.aws.amazon.com/glue/latest/dg/connect-glu-iceberg-rest.html), [Glue table optimizers](https://docs.aws.amazon.com/glue/latest/dg/table-optimizers.html) and [their limitations](https://docs.aws.amazon.com/glue/latest/dg/optimizer-notes.html), [AWS v3 DV/row lineage announcement](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-apache-iceberg-v3-deletion-vectors-row-lineage), [S3 Tables v3 data types](https://aws.amazon.com/blogs/aws/amazon-s3-tables-now-support-all-apache-iceberg-v3-data-types/).

Databricks: [Iceberg overview](https://docs.databricks.com/aws/en/iceberg/), [Iceberg v3](https://docs.databricks.com/aws/en/iceberg/iceberg-v3), [Iceberg reads / UniForm](https://docs.databricks.com/aws/en/delta/uniform), [Iceberg REST access](https://docs.databricks.com/aws/en/external-access/iceberg). Snowflake: [Iceberg tables](https://docs.snowflake.com/en/user-guide/tables-iceberg), [Glue REST catalog integration](https://docs.snowflake.com/en/user-guide/tables-iceberg-configure-catalog-integration-rest-glue), [Horizon for external engines](https://docs.snowflake.com/en/user-guide/tables-iceberg-access-using-external-query-engine-snowflake-horizon), [v3 GA note](https://docs.snowflake.com/en/release-notes/2026/other/2026-05-07-iceberg-v3-ga).

Write-ups: Ryan Blue, [The CDC MERGE Pattern](https://tabular.medium.com/the-cdc-merge-pattern-b6f8b564177a); [Dremio, CoW vs MoR](https://www.dremio.com/blog/row-level-changes-on-the-lakehouse-copy-on-write-vs-merge-on-read-in-apache-iceberg/); [AWS Prescriptive Guidance, Iceberg on AWS](https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/best-practices-read.html); [Iceberg v3 on AWS support matrix (H. Konishi)](https://hidekazu-konishi.com/entry/apache_iceberg_v3_on_aws.html); [Polaris graduation](https://polaris.apache.org/blog/2026/02/19/apache-polaris-graduates-to-top-level-project/).

Existing skills borrowed from (credit): Gordon Murray's [data-engineering-skills `iceberg`](https://github.com/gordonmurray/data-engineering-skills/blob/main/iceberg/SKILL.md) (MIT) - the inspect-first / safety / verify structure; Databricks' [databricks-agent-skills `databricks-iceberg`](https://github.com/databricks/databricks-agent-skills/tree/main/skills/databricks-iceberg) - Databricks and Snowflake interop specifics, re-checked against current vendor docs.
