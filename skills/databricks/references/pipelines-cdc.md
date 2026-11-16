# Pipelines, ingestion and CDC

Lakeflow Spark Declarative Pipelines (formerly DLT), Auto Loader, Lakeflow Connect, change data
feed, and MERGE-based CDC outside pipelines. Pipeline decision tree, legacy-syntax table and
Auto CDC clause rules adapted from the official `databricks-pipelines` and
`databricks-lakeflow-connect` skills (https://github.com/databricks/databricks-agent-skills).

## Contents
1. Names
2. Dataset types and when to use each
3. Python and SQL skeletons
4. Expectations (data quality)
5. AUTO CDC (SCD 1 / 2) and snapshot CDC
6. Auto Loader
7. Lakeflow Connect
8. Kafka / MSK / Kinesis
9. Change data feed and MERGE outside pipelines
10. Running, refresh modes, operations
11. Legacy DLT → current syntax

## 1. Names

DLT → Lakeflow Declarative Pipelines (2025) → Lakeflow Spark Declarative Pipelines ("SDP"; docs
also say "Lakeflow pipelines"). The open-source core is Apache Spark Declarative Pipelines;
Lakeflow adds Auto Loader, AUTO CDC, expectations UI, serverless, UC integration. All the same
product when someone says any of these names.

## 2. Dataset types

| Type | Semantics | Use for |
|---|---|---|
| Streaming table (ST) | Append-only incremental processing, exactly-once per input row | Ingestion (Auto Loader, Kafka), CDC targets, bronze/silver |
| Materialized view (MV) | Stored query result, refreshed (incrementally on serverless when possible) | Aggregations, joins, gold, anything whose inputs change/delete |
| Temporary view | Pipeline-private, not persisted | Intermediate logic; pre-filtering before AUTO CDC |
| Persistent view | UC view, SQL only | Publishing logic without storage |
| Flow / Append flow | Writes into an ST; multiple flows fan in | Several sources → one table (instead of UNION); one-time backfill (`ONCE`) |
| Sink (Python) | Write to external Delta / Kafka / custom | Pushing out of the pipeline; `foreach_batch_sink` for custom merges |

Rules: aggregate over a streaming source with an **MV** reading it as batch; STs do not recompute
when upstream rows change. Cannot switch a dataset ST↔MV in place. Incremental MV refresh needs
serverless + row tracking on sources, otherwise full recompute.

## 3. Skeletons

SQL (default choice for simple pipelines):

```sql
CREATE OR REFRESH STREAMING TABLE bronze_orders
  CLUSTER BY AUTO
AS SELECT *, _metadata.file_path AS src_file
FROM STREAM read_files('/Volumes/raw/shop/landing/orders/', format => 'json',
                       schemaHints => 'amount DECIMAL(18,2)');

CREATE OR REFRESH STREAMING TABLE silver_orders (
  CONSTRAINT valid_id     EXPECT (order_id IS NOT NULL) ON VIOLATION DROP ROW,
  CONSTRAINT positive_amt EXPECT (amount > 0)
) AS SELECT * FROM STREAM(bronze_orders);

CREATE OR REFRESH MATERIALIZED VIEW gold_daily_revenue
  CLUSTER BY (order_date)
AS SELECT date(order_ts) AS order_date, country, sum(amount) AS revenue
FROM silver_orders GROUP BY ALL;
```

Python:

```python
from pyspark import pipelines as dp
from pyspark.sql import functions as F

@dp.table(cluster_by=["order_id"])
def bronze_orders():
    return (spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "json")
            .load("/Volumes/raw/shop/landing/orders/"))

@dp.table
@dp.expect_or_drop("valid_id", "order_id IS NOT NULL")
def silver_orders():
    return spark.readStream.table("bronze_orders")

@dp.materialized_view
def gold_daily_revenue():
    return (spark.read.table("silver_orders")
            .groupBy(F.to_date("order_ts").alias("order_date"), "country")
            .agg(F.sum("amount").alias("revenue")))
```

Pipeline settings: default catalog + schema; fully qualified names publish elsewhere; serverless
on; `channel` CURRENT vs PREVIEW; triggered vs continuous. In SQL use `CREATE OR REFRESH`, never
`CREATE OR REPLACE`.

## 4. Expectations

| Action | SQL | Python |
|---|---|---|
| Warn (keep row, record metric) | `CONSTRAINT c EXPECT (cond)` | `@dp.expect("c", "cond")` |
| Drop row | `... ON VIOLATION DROP ROW` | `@dp.expect_or_drop` |
| Fail update | `... ON VIOLATION FAIL UPDATE` | `@dp.expect_or_fail` |
| Many at once | multiple constraints | `@dp.expect_all{,_or_drop,_or_fail}({name: cond})` |

Metrics land in the pipeline event log (`event_log(TABLE(...))` / the pipeline's event log
table). Quarantine pattern: write violators to a separate table by inverting the condition in a
second flow rather than silently dropping.

## 5. AUTO CDC

```sql
CREATE OR REFRESH STREAMING TABLE dim_customer;

CREATE FLOW dim_customer_cdc AS AUTO CDC INTO dim_customer
FROM STREAM(customer_changes)              -- identifier only, not a subquery; pre-filter in a temp view
KEYS (customer_id)
IGNORE NULL UPDATES
APPLY AS DELETE WHEN op = 'DELETE'         -- DELETE/TRUNCATE clauses must come before SEQUENCE BY
SEQUENCE BY STRUCT(commit_ts, lsn)         -- total order; ties are non-deterministic
COLUMNS * EXCEPT (op, lsn)
STORED AS SCD TYPE 2                       -- default TYPE 1
TRACK HISTORY ON * EXCEPT (last_login);    -- SCD2: only these columns open new versions
```

```python
dp.create_streaming_table("dim_customer")
dp.create_auto_cdc_flow(
    target="dim_customer", source="customer_changes",
    keys=["customer_id"], sequence_by=F.struct("commit_ts", "lsn"),
    apply_as_deletes=F.expr("op = 'DELETE'"),
    except_column_list=["op", "lsn"],
    stored_as_scd_type=2)
```

- SCD2 adds `__START_AT` / `__END_AT` (double underscore); current rows: `WHERE __END_AT IS NULL`.
- Out-of-order events are handled by `SEQUENCE BY`; late events update history correctly.
- `APPLY AS TRUNCATE WHEN` is SCD1 only.
- Snapshot sources (full dumps, no change log): Python
  `dp.create_auto_cdc_from_snapshot_flow(target=..., source=..., keys=..., stored_as_scd_type=...)`.
- Debezium envelope: flatten `payload.after` / `payload.before`, map `op` (`c`,`u`,`d`,`r`), sequence
  by `ts_ms` + LSN/binlog position, in a temp view before the CDC flow.
- Reading an AUTO CDC target downstream as a stream needs `skipChangeCommits` (it gets updates/deletes).

## 6. Auto Loader

```python
(spark.readStream.format("cloudFiles")
   .option("cloudFiles.format", "parquet")
   .option("cloudFiles.schemaLocation", "/Volumes/raw/_meta/schemas/orders")  # automatic inside pipelines
   .option("cloudFiles.schemaEvolutionMode", "addNewColumns")  # or rescue | failOnNewColumns | none
   .option("cloudFiles.schemaHints", "amount DECIMAL(18,2)")
   .option("cloudFiles.useManagedFileEvents", "true")          # file events on the external location
   .option("cloudFiles.maxFilesPerTrigger", 1000)
   .load("s3://bucket/landing/orders/")
 .writeStream.option("checkpointLocation", "/Volumes/raw/_meta/ckpt/orders")
   .trigger(availableNow=True).toTable("raw.shop.bronze_orders"))
```

- Detection modes: directory listing (default, simple), file notification (SQS/SNS), and
  **file events** on a UC external location (recommended; DBR 14.3+; no per-stream queue setup).
- `_rescued_data` captures fields that do not fit the schema; `addNewColumns` stops the stream
  once on a new column, then restarts with it (expect one failure in jobs; set retries).
- `cloudFiles.includeExistingFiles` default true; `availableNow` trigger for batch-style runs.
- SQL / pipelines: `STREAM read_files(path, format => ...)` is Auto Loader.
- File metadata: `_metadata.file_path`, `_metadata.file_modification_time` (not `input_file_name()`).

## 7. Lakeflow Connect

Managed ingestion into UC streaming tables on serverless pipelines.

- **SaaS**: Salesforce, Workday, ServiceNow, GA4, HubSpot, Jira, SharePoint, Google Drive, etc.
- **Databases (CDC)**: SQL Server (GA per the official skill; not re-checked). **PostgreSQL:
  Public Preview** (reference page, last updated 11 Sep 2026; enrol via account team). **MySQL:
  integrated CDC pipeline GA 15 Oct 2026** (Beta 1 Jul). Two architectures:
  - *Gateway*: UC connection → **ingestion gateway** (continuously running job on classic compute
    in your network reading the change log) → staging in a UC volume → serverless **ingestion
    pipeline** applying changes to streaming tables, SCD1 or SCD2.
  - *Integrated* (MySQL GA; page also lists SQL Server and Oracle): one pipeline extracts binlog →
    staging volume → merges, per update. Triggered by default (continuous mode Beta), so no
    always-on gateway. **Defaults to classic compute** (`serverless: false`; ≥8 cores
    recommended). Needs `binlog_format=ROW`, `binlog_row_image=FULL`; binlog purged before
    processing → full refresh of those tables. Tables without a PK use all non-LOB columns as key
    (duplicates collapse). Feature flag via account team.
- **Query-based** connectors (GA 29 May 2026; PostgreSQL, MySQL, SQL Server and Federation
  sources): cursor column, no gateway or replication setup, but hard deletes are missed.
- Free tier (Summit 2026 blog, vendor claim, terms not in docs): 100 DBUs/day, ~100 M records/day
  on popular managed connectors. Billed as `LAKEFLOW_CONNECT`.
- SaaS GA in 2026 (release notes): Dynamics 365 (26 Jun), NetSuite, Google Drive, SharePoint
  (4 Aug); Confluence and HubSpot GA per the Summit blog. Dozens of others are Beta; row filtering
  for SaaS and query-based connectors GA 2 Jul.
- Choose Connect over Debezium/Kafka when: a supported source, no need for the events on a bus,
  and you want no infra. Choose Debezium → MSK → AUTO CDC when other consumers need the event
  stream, or the source/version is not supported.
- Postgres CDC needs logical replication (`wal_level=logical`, a publication and a replication
  slot); RDS/Aurora parameter groups must allow it. Watch slot lag — a stalled gateway retains WAL
  and can fill the source disk.

## 8. Kafka / MSK / Kinesis

```sql
CREATE OR REFRESH STREAMING TABLE bronze_events AS
SELECT CAST(value AS STRING) AS json, topic, partition, offset, timestamp
FROM STREAM read_kafka(bootstrapServers => '...:9098', subscribe => 'events',
                       startingOffsets => 'earliest');
```

MSK IAM auth: UC service credential (`databricks.serviceCredential` option) rather than keys in
code. Kinesis: `read_kinesis(...)`. Kafka retention bounds how far a full refresh can replay —
land raw to bronze before transforming.

## 9. Change data feed and MERGE outside pipelines

```sql
ALTER TABLE silver.orders SET TBLPROPERTIES (delta.enableChangeDataFeed = true);  -- legacy CDF
SELECT * FROM table_changes('silver.orders', 120);         -- from version 120
-- _change_type: insert | update_preimage | update_postimage | delete ; _commit_version ; _commit_timestamp
```

```python
changes = (spark.readStream.option("readChangeFeed", "true")
           .option("startingVersion", 120).table("silver.orders"))
```

- **Automatic CDF** (DBR 19+; GA 1 Sep 2026 for Delta and Iceberg v3): computed at read time for tables with row tracking (UC managed
  Delta, Iceberg v3, external Delta with row tracking); cheaper writes than legacy CDF. Not on
  tables with row filters/masks.
- CDF cannot span non-additive schema changes (rename/drop/type change); VACUUM removes old
  change files.

Hand-written CDC with MERGE (jobs, not pipelines):

```python
def upsert(batch_df, batch_id):
    latest = (batch_df.withColumn("rn", F.row_number().over(
                 Window.partitionBy("id").orderBy(F.col("seq").desc()))).filter("rn = 1"))
    latest.createOrReplaceTempView("src")
    batch_df.sparkSession.sql("""
      MERGE INTO silver.customers t USING src s ON t.id = s.id
      WHEN MATCHED AND s.op = 'd' THEN DELETE
      WHEN MATCHED AND s.seq > t.seq THEN UPDATE SET *
      WHEN NOT MATCHED AND s.op != 'd' THEN INSERT *""")

stream.writeStream.foreachBatch(upsert).option("checkpointLocation", ckpt).trigger(availableNow=True).start()
```

Dedupe within the micro-batch first (MERGE fails on multiple source matches). Prefer AUTO CDC
unless you need logic it cannot express. Deletion vectors make these MERGEs much cheaper.

## 10. Running and operations

- Triggered (batch-like, cheapest) vs continuous (always-on, lowest latency). Development mode
  keeps compute warm and disables retries; production mode retries and terminates.
- **Selective refresh** of named tables is the normal tool. **Full refresh** resets checkpoints and
  re-reads sources from scratch — data that has aged out of Kafka or been deleted from S3 is gone.
  Protect tables with `pipelines.reset.allowed = false`.
- Poll the *update*, not pipeline state. Real error text: `error.exceptions[0].message` in events.
- Pipelines are deployed as bundle resources (`resources/<name>.pipeline.yml`); `databricks bundle
  deploy` then `databricks bundle run <pipeline>`.
- Liquid clustering on pipeline tables: `CLUSTER BY` / `cluster_by=`; key types numeric, string,
  date, timestamp only.
- Iceberg readers of STs/MVs: enable compatibility mode (see unity-catalog-iceberg.md); or managed
  Iceberg MVs (Public Preview 7 Jul 2026); or external Delta/Iceberg reads of pipeline tables via
  REST (Public Preview 5 Jun 2026).

Changes Jun–Oct 2026 (release notes):

| Date | Change | Status |
|---|---|---|
| 15 Jun | AUTO CDC flows for standalone streaming tables in Databricks SQL | GA |
| 7 Jul | `REPLACE WHERE` flows (single-refresh predicate override 22 Jul) | GA |
| 26 Jul | Unit testing for pipelines (Python) | Beta |
| 5/11 Aug | `REPLACE USING` flows (partial snapshot replace keyed by columns) | Beta |
| 7 Aug | Change data feed on materialized views (DBR 18 LTS+) | Beta |
| 26 Aug | Zerobus Ingest into streaming tables | GA |
| 31 Aug | Pipeline events system table | Beta |
| 10 Sep | Managed tables written by append flows in pipelines | Beta |
| 10 Sep | Maintenance windows for continuous pipelines | — |
| 25 Sep | **Deleting a UC pipeline keeps its tables** unless `cascade=true` | behaviour change |
| 5 Oct | Pipeline run-as an account group | — |
| 12 Oct | Pipeline parameters (one codebase, many catalogs) | GA |
| 13 Oct | On-demand state repartitioning | GA |
| 21 Oct | `system.lakeflow.pipelines`, `pipeline_update_timeline` | GA |

Real-Time Mode (Structured Streaming and pipelines): Public Preview since 27 May 2026; dedicated
compute with task slots ≥ all stages' tasks; long batches (5 min default) so replay after failure
is longer. Use only where sub-second latency pays for it.

## 11. Legacy DLT → current syntax

| Legacy | Current |
|---|---|
| `import dlt` | `from pyspark import pipelines as dp` |
| `@dlt.table`, `@dlt.expect*` | `@dp.table` / `@dp.materialized_view`, `@dp.expect*` |
| `@dlt.view` | `@dp.temporary_view` |
| `dlt.read("x")` / `dlt.read_stream("x")` | `spark.read.table("x")` / `spark.readStream.table("x")` |
| `dlt.apply_changes(...)` | `dp.create_auto_cdc_flow(...)` |
| `dlt.apply_changes_from_snapshot(...)` | `dp.create_auto_cdc_from_snapshot_flow(...)` |
| `APPLY CHANGES INTO` | `AUTO CDC INTO` (inside `CREATE FLOW`) |
| `CREATE LIVE TABLE` / `CREATE STREAMING LIVE TABLE` | `CREATE OR REFRESH MATERIALIZED VIEW` / `STREAMING TABLE` |
| `LIVE.x` | `x` (batch) or `STREAM(x)` |
| `partition_cols` + ZORDER | `cluster_by` / `CLUSTER BY` |
| `input_file_name()` | `_metadata.file_path` |
| `target=` | `schema=` |

## Sources
- https://github.com/databricks/databricks-agent-skills — `skills/databricks-pipelines` (SKILL.md, references/auto-cdc-sql.md), `skills/databricks-lakeflow-connect` (adapted)
- https://docs.databricks.com/aws/en/ldp/
- https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/file-detection-modes
- https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/options
- https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/
- https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/postgresql-reference
- https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/mysql-integrated-pipeline
- https://docs.databricks.com/aws/en/structured-streaming/real-time
- Release notes: https://docs.databricks.com/aws/en/release-notes/product/2026/may , .../june , .../july , .../august , .../september , .../october
- Summit 2026 Lakeflow announcements (vendor): https://www.databricks.com/blog/lakeflow-new-era-agentic-data-engineering
- https://docs.databricks.com/aws/en/delta/delta-change-data-feed
- https://docs.databricks.com/aws/en/delta/deletion-vectors
