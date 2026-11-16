# Iceberg concepts, use cases, and when to use it

Plain-English glossary of Apache Iceberg's main ideas, then typical workloads, a when-to-use / when-not-to table, and a comparison with Delta Lake and Apache Hudi. For commands, properties and runbooks, use SKILL.md and the other references; this file explains what things are. Facts checked 1 Oct 2026.

## Glossary

### Table format basics

- **Table format** - A layer of metadata over plain files in object storage that makes a pile of Parquet files behave like one database table, with atomic commits, a schema and history. Without one, "the table" is whatever files happen to sit under `s3://lake/events/`; with Iceberg, it is exactly the files the current snapshot lists, and nothing else.
- **Open table format** - A table format whose specification is public, so any engine can implement it and no single vendor owns your data. Iceberg, Delta Lake and Apache Hudi are the three main ones, and they are what make a **lakehouse** possible: warehouse-style transactions, updates and time travel on open files in cheap object storage.
- **Iceberg is a spec plus libraries, not a server** - There is no "Iceberg database" to run. Engines (Spark, Flink, Trino, Athena, Snowflake, Databricks, DuckDB, PyIceberg) read and write the files using the spec; a catalog holds the pointer to each table's current state.
- **Data file** - An immutable Parquet (default), ORC or Avro file holding rows. Iceberg never edits a data file in place; changes write new files and a new snapshot.
- **Format version (v1, v2, v3, v4)** - The spec level a table is written at. v1 is append-and-overwrite analytic tables; v2 adds row-level deletes; v3 adds new types, deletion vectors, row lineage, default values and encryption keys; v4 is still in development and not adopted. New tables default to v2, and upgrades are one-way.
- **Field ID** - Every column carries a permanent numeric ID, and data files store values by ID rather than by name. That is why renaming a column is instant and why dropping `email` and later adding a new `email` never brings the old values back.
- **Schema evolution** - Changing columns (add, drop, rename, reorder, widen `int` to `long`) as a metadata-only commit, with no data rewrite. Old files are read through the new schema using field IDs.
- **ACID and serializable isolation** - Readers always see one complete committed snapshot and never a half-finished write, and they take no locks. Two writers that clash are detected at commit time and one retries.

### The metadata tree

- **Table metadata file (`metadata.json`)** - The root document of a table's state: schemas, partition specs, sort orders, properties, the list of snapshots, and branches and tags. Every commit writes a new one (`v42.metadata.json` replaces `v41`).
- **Catalog pointer** - The catalog stores one thing per table that matters for correctness: the location of the current `metadata.json`. Committing means swapping that pointer atomically, which is why S3 alone cannot be the catalog for concurrent writers.
- **Manifest list** - One Avro file per snapshot listing that snapshot's manifests, with a partition value range summary for each. Planning reads it first to skip whole manifests, for example every manifest whose `day(ts)` range is before the query's filter.
- **Manifest** - An Avro file listing data files (or delete files), one row per file with its partition values, row count, and per-column min/max and null counts. Manifests are reused across snapshots, so a small append adds a new manifest rather than rewriting old ones.
- **Column statistics** - The per-file min/max, null and value counts kept in manifests. They let a query for `id = 42` skip every file whose `id` range does not contain 42, without opening it.
- **Scan planning and pruning** - Working out which files a query must read by walking manifest list, then manifests, then file stats, then Parquet row-group stats. There is no directory listing, which is what keeps planning fast on tables with millions of files.
- **Commit and optimistic concurrency** - A writer prepares new files and metadata assuming nobody else commits first, then tries to swap the catalog pointer. If someone did, it re-checks for conflicts and retries; if the conflict is real (both rewrote the same file), the commit fails with `CommitFailedException`.
- **Isolation level** - What a writer checks before retrying. `serializable` (default) also fails if a concurrent commit added rows that would have matched the write's filter; `snapshot` only fails if files it read were removed, which lets more concurrent writes succeed.
- **Sequence number** - A counter that increases on every commit and stamps every file added in it. It decides which deletes apply to which data: a delete only affects rows written before it.
- **Puffin file** - A small file format for extra blobs that do not fit in manifests: column statistics sketches (for example distinct-count estimates for the optimiser) and, in v3, deletion vectors. Statistics blobs, and the separate per-partition statistics files, are optional hints for cost-based optimisers; readers may ignore them.
- **Metadata tables** - Built-in read-only views over the metadata, queried like tables: `db.t.snapshots`, `db.t.files`, `db.t.manifests`, `db.t.partitions`, `db.t.history`, `db.t.refs` and more. They are the first place to look when diagnosing small files or slow planning.

### Snapshots and time travel

- **Snapshot** - The complete state of a table at one commit: an ID, a timestamp, a parent, and the manifest list that names every live file. Each write produces a new snapshot; the old ones stay until expired.
- **Snapshot operation** - Each snapshot's summary records what kind of change it was: `append` (only added files), `replace` (rewrote files without changing data, such as compaction), `overwrite` (logical replace of some rows) or `delete`. Streaming readers and expiry use this to decide what to process.
- **Time travel** - Querying an earlier snapshot by ID or timestamp, for example "yesterday's numbers as they were at 09:00 yesterday". It only reaches snapshots that have not been expired.
- **Rollback** - Making an older snapshot current again, for example after a bad job overwrote a partition. It is a metadata change; no data is copied.
- **Incremental read** - Reading only the rows appended between two snapshots, so a downstream job processes new data without rescanning. Works for append snapshots; overwrites and deletes need a changelog view instead.
- **Changelog view** - A Spark procedure that compares snapshots and returns inserted, deleted and (with identifier columns) before/after-update rows. It is how you get CDC out of an Iceberg table that has no change column.

### Partitioning and data layout

- **Partition spec** - The table's rule for grouping rows into partitions, built from transforms on columns. A table can have several specs over its life; each data file records which one it was written with.
- **Hidden partitioning** - Partition values are derived from real columns by the spec, and queries filter on the real column. You partition by `day(ts)` and query `WHERE ts >= '2026-09-30'`; nobody has to know or set an `event_date` column.
- **Partition transform** - The functions a spec may use: `identity`, `bucket(N, col)` (hash into N groups, good for join keys and high-cardinality IDs), `truncate(W, col)`, `year`, `month`, `day`, `hour`, and `void` for a dropped field.
- **Partition evolution** - Changing the partition spec (say `day` to `hour` as volume grows) as a metadata-only commit. Old files keep their old layout, new files use the new one, and queries plan across both without rewriting anything.
- **Sort order** - A table-level declaration of how rows should be sorted inside files, used by writers and compaction. Sorting on commonly filtered columns makes min/max stats tighter, so more files and row groups get skipped.
- **Z-order** - A sort that interleaves several columns so filters on any of them prune well, used through compaction (`zorder(tenant, id)`). Useful when queries filter on two or three columns with no single dominant one.
- **Write distribution mode** - How an engine shuffles rows to writer tasks before writing: `none`, `hash` (by partition) or `range` (by sort order). It controls how many files each write produces per partition.
- **Small files problem** - Many tiny data files (from streaming, over-partitioning or many small commits) make planning and reads slow because every file is a separate request and manifest entry. Fixed by compaction and by partitioning to the data volume; writers and compaction aim for a **target file size** of 512 MB by default.

### Deletes and row-level changes

- **Row-level operation** - `MERGE INTO`, `UPDATE` and `DELETE` that change individual rows rather than whole partitions. Because data files are immutable, each one is implemented by rewriting files or by writing delete files.
- **Copy-on-write (CoW)** - Row changes rewrite every affected data file in full. Reads stay simple and fast, but changing one row in a 512 MB file rewrites 512 MB; the default mode.
- **Merge-on-read (MoR)** - Row changes write small delete files (and new rows) instead of rewriting, and readers apply the deletes at query time. Cheap writes and slower reads until compaction folds the deletes back in; needs v2 or later.
- **Delete file** - A file that marks rows as deleted without touching the data file. Three kinds exist: position deletes, equality deletes and deletion vectors.
- **Position delete** - Marks a row deleted by data file path and row number ("row 1,234 of file A is gone"). Cheap for readers to apply; v2 stores them in delete files, v3 in deletion vectors.
- **Equality delete** - Marks rows deleted by value ("every row with `id = 5` written before this commit is gone"). Very cheap to write because the writer never reads the table, which is why Flink upserts use it, but expensive for readers, and v4 stops allowing new ones.
- **Deletion vector (DV)** - v3's replacement for position delete files: one compact bitmap of deleted row positions per data file, stored in a Puffin file. At most one per data file per snapshot, so readers apply one bitmap rather than merging many delete files. The bitmap layout is compatible with Delta Lake's deletion vectors.
- **Identifier fields** - Columns declared as the row's logical key (like a primary key, but Iceberg does not enforce uniqueness). Flink upserts and changelog before/after images use them.
- **Upsert** - Insert a row if its key is new, update it if it exists, usually through `MERGE INTO`. Source rows must be deduplicated to one per key per batch, or MERGE fails.
- **Change data capture (CDC)** - Copying inserts, updates and deletes from an operational database into the lake. The standard Iceberg pattern lands raw change events in an append-only changelog table, then MERGEs them into a mirror table holding current state.

### Catalogs

- **Catalog** - The service that maps table names to their current `metadata.json` and performs the atomic pointer swap on commit. Tables are grouped into **namespaces** (like databases or schemas), for example `analytics.events`.
- **Iceberg REST catalog** - An open HTTP API for catalogs, so any engine with a REST client can use any compliant catalog. It moves commit validation to the server and enables credential vending; most new catalogs speak it.
- **Credential vending** - The catalog hands the engine short-lived storage credentials scoped to the one table it is reading, instead of every engine holding broad S3 keys. Access control then lives in the catalog.
- **AWS Glue Data Catalog** - AWS's managed catalog, usable natively or through its Iceberg REST endpoint. Athena, EMR, Redshift and Glue jobs all read tables registered in it, and Glue can run managed compaction.
- **Amazon S3 Tables** - S3 buckets built for Iceberg tables, with the catalog and maintenance (compaction, snapshot expiry, unreferenced file removal) managed by AWS. Less to run, but its maintenance competes with your own jobs if you also run them.
- **Apache Polaris, Snowflake Open Catalog and Horizon** - Polaris is a vendor-neutral REST catalog (an Apache top-level project since Feb 2026); Snowflake Open Catalog is Snowflake's hosted Polaris; Horizon is Snowflake's own catalog, exposing Snowflake-managed Iceberg tables to outside engines.
- **Databricks Unity Catalog** - Databricks' governance catalog, which manages Delta and Iceberg tables and exposes an Iceberg REST endpoint so outside engines can read, and for managed Iceberg tables write.
- **Project Nessie** - A catalog with Git-style branches and commits spanning many tables at once, for example a branch where ten tables are updated together and merged atomically.
- **Iceberg view** - A spec for storing SQL view definitions in the same metadata style as tables, so a view created in one engine can be read by another. Support varies by catalog and engine.
- **Table migration** - Bringing existing Parquet or Hive tables into Iceberg without copying data: `migrate` (convert in place), `snapshot` (a test copy that shares files), `add_files` (register existing files), `register_table` (adopt an existing `metadata.json`).

### Maintenance

- **Compaction (`rewrite_data_files`)** - Rewrites many small files into fewer large ones, optionally re-sorting and applying pending deletes. It is a `replace` snapshot: the data is unchanged, only its layout.
- **Rewrite manifests** - Regroups many small manifests into fewer, better-clustered ones so planning reads less metadata. Matters most for streaming tables, whose fast appends add a manifest per commit.
- **Expire snapshots** - Removes old snapshots from metadata and physically deletes files that only those snapshots referenced. This is what frees storage after compaction or deletes, and it is the hard limit on how far back time travel can go.
- **Orphan files** - Files in the table's location that no snapshot references, usually left by failed or killed writes. `remove_orphan_files` deletes them, but only older than a safety window, since in-flight writes also look like orphans.
- **Old metadata files** - Each commit leaves the previous `metadata.json` behind. A table property keeps only the last N (100 by default when enabled); snapshot expiry does not remove them.
- **Managed maintenance** - Platforms that run the jobs above for you: Glue table optimizers, S3 Tables maintenance, Databricks predictive optimization, Snowflake for its managed tables. Pick one owner per table; two maintainers cause commit conflicts and double cost.

### Branching and tagging

- **Ref** - A named pointer to a snapshot, stored in table metadata. `main` is the default branch and the table's current state.
- **Branch** - A movable ref with its own line of snapshots, so writes can go to `audit` without changing `main`. Each branch can have its own retention.
- **Tag** - A fixed label on one snapshot, kept until its retention expires, for example `eoy-2025` to keep the year-end state queryable for audits.
- **Write-audit-publish (WAP)** - Write a batch to a branch (or a staged snapshot), run data-quality checks against it, then publish to `main`. Publishing is a **fast-forward** (move `main` to the branch head, only if `main` has not moved since) or a **cherry-pick** (apply one snapshot's changes onto the current state). Readers of `main` never see data that failed the checks.

### Format v3 features

- **Row lineage** - Every row gets a stable `_row_id` and a `_last_updated_sequence_number`, kept across compaction and updates. Downstream jobs can ask "which rows changed since sequence 1,200?" without a CDC column; rows updated via equality deletes get new IDs instead.
- **Default values** - A column added later can have an `initial-default` for existing rows and a `write-default` for new rows that omit it, with no data rewrite. Engine support is still partial.
- **Variant** - A type for semi-structured data, like JSON but with richer types (dates, decimals, binary) and a compact binary encoding shared with Parquet. Good for event payloads whose shape varies by event.
- **Geometry and geography** - Spatial types with bounding-box stats, so map-style filters can prune files.
- **Nanosecond timestamps and the `unknown` type** - `timestamp_ns` for high-precision event times; `unknown` is a placeholder type for a column that has only ever held nulls. v3 also allows **multi-argument transforms** (partition and sort transforms over more than one column).
- **Table encryption keys** - Metadata for tracking the keys used to encrypt a table's files, as a basis for engine-level encryption.
- **Format v4 (in development)** - Relative file paths in metadata, so a table can be moved or copied without rewriting metadata, and no new equality deletes. Not adopted; do not plan around it yet.

## Use cases

| Workload | Why Iceberg fits | Concrete example |
|---|---|---|
| Shared lakehouse across engines | One copy of the data, any engine, one catalog owns commits | Spark on EMR writes `sales.orders`; Athena serves analysts, Snowflake joins it with CRM data, and a data science team reads it with PyIceberg, all from the same S3 files. |
| Large append-heavy event tables | Hidden partitioning on time, file-level pruning, no listing | 5 TB/day of clickstream partitioned by `day(event_ts)`; a dashboard query on the last two hours reads a few dozen files out of millions. |
| CDC mirrors of OLTP databases | MERGE with MoR, compaction, changelog for history | Debezium streams Postgres `accounts` changes to Kafka; Kafka Connect appends them to a changelog table; a Spark job MERGEs them into `silver.accounts` every 15 minutes. |
| Near-real-time streaming ingestion | Atomic commits per micro-batch, readers never see partial batches | Flink writes IoT readings every minute; analysts query data under five minutes old while hourly compaction keeps file counts down. |
| Privacy deletes (GDPR, CCPA) | Row-level deletes without rewriting partitions by hand | A nightly `DELETE FROM events WHERE user_id IN (erasure_requests)` with MoR, then expiry so deleted rows physically disappear from storage within the retention window. |
| Reproducible ML training and audits | Time travel and tags pin an exact table state | Tag `training-2026-09` on the feature table; a model can be retrained months later on exactly the same rows. |
| Data quality gates | WAP branches keep unchecked data out of `main` | The nightly load writes to branch `etl_20261001`; row-count and null checks run; only then is `main` fast-forwarded. |
| Slowly changing dimensions | MERGE with closing and inserting row versions | `dim_customer` keeps `valid_from`, `valid_to`, `is_current`; a daily MERGE closes changed rows and inserts their new versions. |
| Fixing legacy Hive tables | Migrate in place, then gain atomic commits and evolution | A Hive table with 200,000 partitions and slow listings is converted with `migrate`, then repartitioned from `hour` to `day` without a rewrite. |
| Avoiding warehouse lock-in | Storage stays in your account, in an open format | Raw and silver layers live as Iceberg on S3; Snowflake and Databricks both read them, so changing compute vendor does not mean moving data. |

## When to use / when not to use

| Situation | Verdict | Better alternative and reason |
|---|---|---|
| Several engines (Spark, Athena, Trino, Snowflake, Databricks) share large tables on S3 | **Use Iceberg** | This is its main strength: the widest engine support and an open REST catalog standard. |
| Large append-mostly fact or event tables queried by time range | **Use Iceberg** | Hidden partitioning and file-level stats make pruning cheap; partitioning can change as volume grows. |
| CDC mirror with minutes of latency and a moderate update rate | **Use Iceberg** (MoR plus scheduled compaction) | Works well when compaction is owned and scheduled; without it reads degrade steadily. |
| Everything runs on Databricks and no outside engine needs the tables | **Use Delta Lake** | Databricks builds on Delta first: change data feed, generated columns, constraints and collation are Delta-only there. UniForm can still expose Iceberg reads later. |
| Very high-rate upserts with skewed keys on a huge table, minute-level freshness | **Consider Apache Hudi** | Hudi's record-level index finds a key's file directly, while Iceberg's MERGE joins against the table; Hudi also runs compaction and cleaning as built-in services. Weigh this against Hudi's narrower engine support; the published benchmarks come from the Hudi project. |
| Write-once archive, never updated, read by one engine | **Plain Parquet** (date-partitioned folders) is often enough | No commits, catalog or maintenance to run. Switch to Iceberg once you need schema changes, atomic overwrites, deletes or multi-engine access. |
| Point lookups by key in milliseconds, or thousands of single-row updates per second | **Do not use Iceberg**; use an OLTP database (Postgres, Aurora) or key-value store (DynamoDB) | Each commit writes several files to S3 and commits are best kept to about one a minute per table; per-row latency and write rate are far outside its design. |
| Small BI mart (a few GB) used only inside Snowflake, BigQuery or Redshift | **Use the warehouse's native tables** | Fewer moving parts, full warehouse features (for example Snowflake Fail-safe, which Iceberg tables on your own storage do not get), and no lake maintenance. |
| Sub-second dashboards with high concurrency over very fresh data | **Use a real-time analytics store** (ClickHouse, Apache Pinot, Druid) or OpenSearch, with Iceberg as the long-term copy | Iceberg queries go through object storage and planning, so latency is seconds, not milliseconds. |
| Seconds-level end-to-end freshness | **Use a streaming system** (Kafka plus Flink state, or a real-time store) and sink to Iceberg | More frequent commits mean metadata bloat and commit conflicts. |
| Full-text search or relevance ranking | **Use OpenSearch or Elasticsearch** | Iceberg has no text indexes. |
| Data fits on one machine (tens of GB), single analyst | **DuckDB over Parquet, or Postgres** | A catalog and maintenance jobs are overhead with no payoff at that size. |
| Athena reads the table and you want v3 features | **Use Iceberg but stay on v2** | Athena cannot read v3 tables, and the upgrade is one-way. |

## Iceberg vs Delta Lake vs Apache Hudi

| | Apache Iceberg | Delta Lake | Apache Hudi |
|---|---|---|---|
| Origin and governance | Netflix; Apache Software Foundation | Databricks; Linux Foundation | Uber; Apache Software Foundation |
| Latest release (GitHub, checked 1 Oct 2026) | 1.12.0 tagged 30 Sep 2026 (docs site still shows 1.11.0) | 4.4.0, 20 Aug 2026 | 1.2.1, 24 Sep 2026 |
| How table state is stored | Tree of metadata.json, manifest list and manifests; catalog holds the pointer | `_delta_log` folder of JSON commit files plus periodic Parquet checkpoints | Timeline of actions in `.hoodie` (LSM timeline since 1.0) plus an internal metadata table |
| Partitioning | Hidden partitioning with transforms; partition evolution without rewrite | Explicit partition columns (generated columns for derived values) or liquid clustering (OSS 3.1+) | Explicit partition paths; clustering service for layout |
| Row-level changes | CoW or MoR; v2 delete files, v3 deletion vectors | CoW by default; deletion vectors (2.3+, MERGE from 3.1) | CoW or MoR table types; MoR writes updates to log files per file group |
| Finding rows to update | Join incoming keys against the table, pruned by stats | Join against the table, pruned by stats | Indexes map keys to file groups (record-level index since 0.14, secondary indexes in 1.x) |
| Maintenance | Separate procedures you schedule, or a managed service | `OPTIMIZE` / `VACUUM`; automatic on Databricks | Built-in table services (compaction, clustering, cleaning) run inline or async |
| Getting changes out | Incremental reads, changelog view, v3 row lineage | Change data feed | Incremental queries and CDC mode with before/after images |
| Engine breadth | Widest: Spark, Flink, Trino, Athena, EMR, Redshift, Snowflake, BigQuery, Databricks, DuckDB, PyIceberg | Best on Databricks; many readers via Delta Kernel and delta-rs | Strongest on Spark and Flink; others mainly read |
| Catalog standard | Iceberg REST catalog spec, implemented by Glue, S3 Tables, Polaris, Unity, Horizon | Unity Catalog | Hive Metastore sync and others |
| Best fit | Multi-engine lakehouse, open catalog, large analytic tables | Databricks-centred platforms | Upsert-heavy streaming ingestion with record-level indexing |

Bridges between formats: Delta **UniForm** writes Iceberg metadata alongside a Delta table so Iceberg readers can query it (read-only); **Apache XTable** (still incubating) translates metadata between all three. Both let one copy of data serve readers of another format, but writes still belong to the original format.

## Sources

Apache Iceberg: [Table spec (main branch: format versions, deletes, row lineage, snapshots, refs, statistics)](https://github.com/apache/iceberg/blob/main/format/spec.md), [Puffin spec](https://iceberg.apache.org/puffin-spec/), [View spec](https://iceberg.apache.org/view-spec/), [Maintenance](https://iceberg.apache.org/docs/latest/maintenance/), [Spark queries and metadata tables](https://iceberg.apache.org/docs/latest/spark-queries/), [Spark DDL](https://iceberg.apache.org/docs/latest/spark-ddl/), [Releases](https://iceberg.apache.org/releases/), [GitHub releases](https://github.com/apache/iceberg/releases).

Delta Lake: [Deletion vectors](https://docs.delta.io/delta-deletion-vectors/), [Liquid clustering](https://docs.delta.io/delta-clustering/), [GitHub releases](https://github.com/delta-io/delta/releases).

Apache Hudi: [Hudi vs Iceberg for CDC workloads (Hudi project blog, Aug 2026; vendor-side view)](https://hudi.apache.org/blog/2026/08/06/hudi-vs-iceberg-for-cdc-workloads/), [Hudi vs Iceberg for streaming ingestion](https://hudi.apache.org/blog/2026/08/11/hudi-vs-iceberg-for-streaming-ingestion/), [Hudi 1.0 announcement](https://hudi.apache.org/blog/2024/12/16/announcing-hudi-1-0-0/), [Indexing](https://hudi.apache.org/docs/metadata_indexing/), [LSM timeline](https://hudi.apache.org/blog/2025/05/29/lsm-timeline/), [GitHub releases](https://github.com/apache/hudi/releases).

Platforms: [Databricks Iceberg overview (managed Iceberg vs Delta features)](https://docs.databricks.com/aws/en/iceberg/), [Snowflake Iceberg tables (Fail-safe, billing, unsupported features)](https://docs.snowflake.com/en/user-guide/tables-iceberg), [Apache XTable (incubating)](https://xtable.apache.org/), [Polaris graduation](https://polaris.apache.org/blog/2026/02/19/apache-polaris-graduates-to-top-level-project/).

