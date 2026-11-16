# Snowflake ingestion and pipelines

## Choosing an ingestion path

| Path | Typical latency | Compute | Billing | Pick when |
|---|---|---|---|---|
| `COPY INTO` (batch) | minutes–hours | Your warehouse | Warehouse seconds (60 s min per resume) | Scheduled bulk loads, backfills, one-offs |
| Snowpipe (auto-ingest) | ~1 min | Serverless | 0.0037 credits per GB (text: uncompressed; Parquet/Avro/ORC: observed size) — flat since Aug 2025 (Business Critical/VPS) and 8 Dec 2025 (Standard/Enterprise); no per-file fee any more | Continuous file drops to S3/GCS/Azure |
| Snowpipe Streaming, high-performance architecture | as low as ~5 s; up to 20 GB/s per table | Serverless | 0.0037 credits per uncompressed GB of input values | Rows from Kafka/CDC/apps without landing files |
| Snowpipe Streaming Classic | seconds | Serverless | compute ×1 + 0.01 credits per client instance-hour | Legacy `snowflake-ingest-java` ≤ 4.x — migrate |
| Kafka connector | seconds–minutes | Uses Snowpipe or Snowpipe Streaming underneath | As above | Existing Kafka Connect estate |

Rule of thumb: if data already lands as files in object storage, Snowpipe is cheaper and simpler than keeping a warehouse warm for micro-batches. If the files are Iceberg/Parquet already in the lakehouse, consider **not loading at all** — query them as Iceberg tables (see iceberg-interop.md).

## COPY INTO

```sql
CREATE STORAGE INTEGRATION s3_int
  TYPE = EXTERNAL_STAGE STORAGE_PROVIDER = 'S3' ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::123456789012:role/snowflake-load'
  STORAGE_ALLOWED_LOCATIONS = ('s3://raw-bucket/events/');

CREATE STAGE raw_events_stage URL = 's3://raw-bucket/events/' STORAGE_INTEGRATION = s3_int
  FILE_FORMAT = (TYPE = PARQUET);

COPY INTO raw.events
  FROM @raw_events_stage
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
  ON_ERROR = ABORT_STATEMENT;
```
- **File size 100–250 MB compressed**: load parallelism is per file; thousands of tiny files waste time on overhead, a single 50 GB file uses one thread. Avoid files > 100 GB.
- **Load metadata lasts 64 days**: COPY skips files it already loaded (per table). Files with LAST_MODIFIED older than that are "uncertain" — use `LOAD_UNCERTAIN_FILES = TRUE`; `FORCE = TRUE` reloads everything (duplicates).
- `FILES = (...)` (≤ 1,000 names) is fastest, prefix paths next, `PATTERN` regex slowest.
- `ON_ERROR = CONTINUE`/`SKIP_FILE` lets bad rows through silently; check `VALIDATE()` or `COPY_HISTORY`.
- JSON: `STRIP_NULL_VALUES = TRUE`; flatten hot fields to typed columns.
- Dedicated small loading warehouse, `AUTO_SUSPEND = 60`.

## Snowpipe

```sql
CREATE PIPE raw.events_pipe AUTO_INGEST = TRUE AS
  COPY INTO raw.events FROM @raw_events_stage FILE_FORMAT = (TYPE = PARQUET)
  MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE;

SHOW PIPES;                                   -- notification_channel = SQS ARN for S3 event notifications
SELECT SYSTEM$PIPE_STATUS('raw.events_pipe');
ALTER PIPE raw.events_pipe REFRESH;           -- backfill: only files staged in the last 7 days
```
- Stage roughly **one file per minute** per source; more frequent tiny files add queue overhead without lower latency.
- Pipe has its own load history (separate from COPY's 64-day metadata); a pipe paused longer than the event-message retention (14 days by default) goes stale.
- Monitor: `PIPE_USAGE_HISTORY` (credits, `bytes_billed`, files), `COPY_HISTORY` for per-file errors.

## Snowpipe Streaming

High-performance architecture (GA Sep 2025, GCP Nov 2025): SDKs in Java, Python and Node.js over a shared Rust core, plus a REST API. Writes go through a **PIPE** object. Channel types:
- **Elastic channels** — producers just write; at-least-once, no ordering guarantee.
- **Named channels** — offset tokens per channel give ordered, exactly-once ingestion; use for Kafka partitions or CDC streams.

Can target native tables and Snowflake-managed Iceberg tables (v2 and v3). Billing is on input bytes received, not table bytes. Monitor with `METERING_HISTORY` where `service_type = 'SNOWPIPE_STREAMING'`.

## Streams (CDC on a table)

```sql
CREATE STREAM raw.events_s ON TABLE raw.events;                    -- standard: inserts, updates, deletes
CREATE STREAM raw.events_ao ON TABLE raw.events APPEND_ONLY = TRUE; -- inserts only, cheaper
CREATE STREAM ext.files_s ON EXTERNAL TABLE ext.files INSERT_ONLY = TRUE; -- external tables; externally managed Iceberg tables also get insert-only streams
```
- Extra columns: `METADATA$ACTION` (INSERT/DELETE), `METADATA$ISUPDATE`, `METADATA$ROW_ID`. An UPDATE appears as a DELETE + INSERT pair with ISUPDATE = TRUE.
- The offset **advances only when the stream is read inside a DML statement that commits** (INSERT/MERGE/CTAS/COPY). A plain SELECT doesn't consume it. Read once per transaction and write all targets in that transaction.
- **Staleness**: if not consumed within the table's retention, Snowflake extends retention up to `MAX_DATA_EXTENSION_TIME_IN_DAYS` (default 14); beyond that the stream goes stale and must be recreated (with a gap). Alert on `SHOW STREAMS` → `stale_after`.
- Streams cost nothing by themselves; cost is the consuming query plus extra retained storage.

## Tasks

```sql
-- Serverless, scheduled (no WAREHOUSE): Snowflake sizes compute from history; 0.9× multiplier
CREATE TASK etl.rollup_hourly
  SCHEDULE = 'USING CRON 5 * * * * UTC'
  SERVERLESS_TASK_MAX_STATEMENT_SIZE = 'LARGE'
AS
  CALL etl.build_rollup();

-- Triggered (no SCHEDULE): runs when the stream has data; min interval 30 s by default (10 s minimum)
CREATE TASK etl.apply_orders
  TARGET_COMPLETION_INTERVAL = '15 MINUTES'
  WHEN SYSTEM$STREAM_HAS_DATA('raw.orders_s')
AS
  MERGE INTO core.orders t
  USING (SELECT * FROM raw.orders_s WHERE METADATA$ACTION = 'INSERT') s
    ON t.order_id = s.order_id
  WHEN MATCHED THEN UPDATE SET t.status = s.status, t.updated_at = s.updated_at
  WHEN NOT MATCHED THEN INSERT (order_id, status, updated_at) VALUES (s.order_id, s.status, s.updated_at);

-- Graph: child runs after parent; a FINALIZE task runs at the end regardless of outcome
CREATE TASK etl.publish AFTER etl.rollup_hourly AS CALL etl.publish();

ALTER TASK etl.publish RESUME;          -- children first, then the root
ALTER TASK etl.rollup_hourly RESUME;
EXECUTE TASK etl.rollup_hourly;         -- manual run for testing
```
- Tasks are created **suspended**.
- `WHEN SYSTEM$STREAM_HAS_DATA(...)`: the condition check itself doesn't consume warehouse credits; only runs that execute do.
- Serverless vs warehouse: serverless suits short, frequent jobs that would otherwise wake a warehouse (and pay its 60-second minimum) for a few seconds of work; billed at 0.9× ("Serverless Tasks Flex" is listed at 0.5×). A shared warehouse suits long jobs or many concurrent tasks that already keep it busy.
- Monitor: `TASK_HISTORY` (runs, errors), `SERVERLESS_TASK_HISTORY` (credits).

## Dynamic tables

```sql
CREATE OR REPLACE DYNAMIC TABLE mart.daily_revenue
  TARGET_LAG = '30 minutes'
  WAREHOUSE  = transform_wh
  REFRESH_MODE = INCREMENTAL          -- fail at create time instead of silently going FULL
  INITIALIZE = ON_CREATE
AS
SELECT o.tenant_id, DATE_TRUNC('day', o.created_at) AS day, SUM(o.amount) AS revenue, COUNT(*) AS orders
FROM core.orders o
JOIN core.tenants t ON t.tenant_id = o.tenant_id
GROUP BY 1, 2;

CREATE OR REPLACE DYNAMIC TABLE core.orders_clean
  TARGET_LAG = DOWNSTREAM WAREHOUSE = transform_wh
AS SELECT * FROM raw.orders WHERE order_id IS NOT NULL;

ALTER DYNAMIC TABLE mart.daily_revenue REFRESH;    -- manual
ALTER DYNAMIC TABLE mart.daily_revenue SUSPEND;    -- stop spend (e.g. off-hours)
SHOW DYNAMIC TABLES LIKE 'DAILY_REVENUE' IN SCHEMA mart;   -- check refresh_mode, target_lag, scheduling_state
```
- `TARGET_LAG` minimum 60 s; `DOWNSTREAM` means "refresh only when a consumer needs it" — use for intermediate layers.
- Refresh modes: `INCREMENTAL`, `FULL`, `AUTO` (resolved once at creation — check what it chose), plus newer `ADAPTIVE` and `CUSTOM_INCREMENTAL`. Non-deterministic functions, some window/outer-join shapes and unsupported constructs force FULL.
- Cost: refreshes run on your warehouse (60-second minimum per resume); change detection runs in cloud services every cycle even when nothing changed. If nothing upstream changed the warehouse is not started.
- Can't: stored procedures or external functions in the definition, DML into the DT, sequences for surrogate keys, SCD2 history — use streams + tasks for those.
- Use TRANSIENT dynamic tables for rebuildable layers to drop Fail-safe storage.
- Monitor: `DYNAMIC_TABLE_REFRESH_HISTORY` (`refresh_action` NO_DATA / INCREMENTAL / FULL / REINITIALIZE, `query_id`) joined to `QUERY_ATTRIBUTION_HISTORY` — see cost-sql.md section 6.

## Materialized views

```sql
CREATE MATERIALIZED VIEW mart.events_by_day CLUSTER BY (day) AS
SELECT tenant_id, TO_DATE(event_ts) AS day, COUNT(*) AS events, SUM(bytes) AS bytes
FROM raw.events
GROUP BY 1, 2;
```
Enterprise+. One base table, no joins, no window functions, UDFs, HAVING, ORDER BY, LIMIT or set operators; aggregates limited to COUNT, SUM, AVG, MIN, MAX, STDDEV/VARIANCE families. Always current (queries combine the MV with not-yet-maintained base rows). Maintenance is serverless at 2× (+1 cloud services) — on a high-churn base table that can exceed the query savings. The optimizer can rewrite queries on the base table to use the MV. Monitor `MATERIALIZED_VIEW_REFRESH_HISTORY`.

## Decision matrix (expanded)

| Question | MV | Dynamic table | Streams + tasks |
|---|---|---|---|
| Joins across tables | No | Yes | Yes |
| Freshness | Always current | ≥ 60 s target lag | As often as task runs (triggered ≥ 10–30 s) |
| Compute | Serverless 2× | Your warehouse | Your warehouse or serverless 0.9× |
| Logic | One SELECT, restricted | One SELECT, broad SQL | Anything: MERGE, procs, external calls |
| Upserts / SCD2 / deletes to target | No | No direct DML | Yes |
| Query rewrite to use it automatically | Yes | No | No |
| Operational burden | Lowest | Low | Highest (offsets, staleness, retries) |
| Typical use | Hot single-table aggregate under a dashboard | Medallion layers, reporting marts | CDC apply, idempotent upserts, orchestration |

Sources: https://docs.snowflake.com/en/user-guide/data-load-considerations-prepare · https://docs.snowflake.com/en/user-guide/data-load-considerations-load · https://docs.snowflake.com/en/user-guide/data-load-snowpipe-auto-s3 · https://docs.snowflake.com/en/sql-reference/sql/alter-pipe · https://docs.snowflake.com/en/user-guide/data-load-snowpipe-billing · https://docs.snowflake.com/en/release-notes/2025/other/2025-12-08-snowpipe-simplified-pricing · https://docs.snowflake.com/en/user-guide/snowpipe-streaming/data-load-snowpipe-streaming-overview · https://docs.snowflake.com/en/user-guide/snowpipe-streaming-high-performance-cost · https://docs.snowflake.com/en/user-guide/streams-intro · https://docs.snowflake.com/en/user-guide/tasks-intro · https://docs.snowflake.com/en/user-guide/tasks-triggered · https://docs.snowflake.com/en/user-guide/dynamic-tables-about · https://docs.snowflake.com/en/user-guide/dynamic-tables-comparison · https://docs.snowflake.com/en/user-guide/dynamic-tables/cost · https://docs.snowflake.com/en/user-guide/views-materialized · Service Consumption Table https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf · pipeline-choice framing adapted from PatrickJS/awesome-cursorrules `snowflake-data-engineering` rule.
