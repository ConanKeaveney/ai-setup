# Snowflake cost SQL — ACCOUNT_USAGE cookbook

All views are in `SNOWFLAKE.ACCOUNT_USAGE`. Access: `GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE …`
or the narrower database role `GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE …`.
Retention is 1 year. Column names below were checked against each view's doc page in October 2026.

## Views and their traps

| View | Grain | Latency | Use for | Trap |
|---|---|---|---|---|
| `METERING_DAILY_HISTORY` | day × service_type | ~3 h | The bill: `credits_billed` includes the cloud-services 10% adjustment | Only view where the adjustment (`credits_adjustment_cloud_services`, negative) appears |
| `METERING_HISTORY` | hour × service/entity | ~3 h | Hourly by service type and object (e.g. `SNOWPIPE_STREAMING`) | Cloud services shown unadjusted |
| `WAREHOUSE_METERING_HISTORY` | hour × warehouse | 3 h (cloud services 6 h) | Warehouse spend; idle = `credits_used_compute - credits_attributed_compute_queries` | `credits_used` includes unadjusted cloud services |
| `QUERY_ATTRIBUTION_HISTORY` | query | up to 8 h | Per-query compute credits (`credits_attributed_compute`), QAS credits | Excludes idle, ≤ ~100 ms queries, cloud services, serverless; data from mid-Aug 2024; adaptive warehouses use `QUERY_METERING_HISTORY` |
| `QUERY_HISTORY` | query | 45 min | Timings (ms), spill, pruning, queueing, bytes, cache % | No credits column except `credits_used_cloud_services` |
| `QUERY_INSIGHTS` | query × insight | 90 min | Snowflake's own diagnoses (exploding join, remote spill, unselective filter…) | — |
| `TABLE_QUERY_PRUNING_HISTORY` | interval × table × query hash | 4 h | Pruning effectiveness per table | — |
| `QUERY_ACCELERATION_ELIGIBLE` | query | 3 h | Which queries QAS would help | Only shows queries not already accelerated |
| `AUTOMATIC_CLUSTERING_HISTORY` | window × table | 3 h | Reclustering credits, bytes reclustered, `version` (CLASSIC/OPTIMA) | — |
| `SEARCH_OPTIMIZATION_HISTORY` | window × index | 3 h | SOS maintenance credits | Uses `index_name`, `base_table_name` (the old `table_name` is gone) |
| `MATERIALIZED_VIEW_REFRESH_HISTORY` | window × MV | 3 h | MV maintenance credits | `table_name` is the MV |
| `SERVERLESS_TASK_HISTORY` | window × task | 3 h | Serverless task credits | User-managed tasks show up as warehouse usage instead |
| `PIPE_USAGE_HISTORY` | window × pipe | 3 h | Snowpipe credits, `bytes_billed`, files; Iceberg auto-refresh appears here with the table as `pipe_name` | — |
| `DYNAMIC_TABLE_REFRESH_HISTORY` | refresh | 3 h | Refresh action (NO_DATA/INCREMENTAL/FULL/REINITIALIZE), `query_id` | No credits column — join `query_id` to attribution |
| `TABLE_STORAGE_METRICS` | table | ~hours | Active / Time Travel / Fail-safe / clone-retained bytes, including dropped tables | — |

Credits → dollars: multiply by your contract rate (on demand e.g. $3 Enterprise in AWS US East, $3.90 in EU Dublin). Storage is separate ($/TB-month).

## 1. The bill by service

```sql
SELECT usage_date,
       service_type,
       SUM(credits_used_compute)              AS compute,
       SUM(credits_used_cloud_services)       AS cloud_services,
       SUM(credits_adjustment_cloud_services) AS cs_adjustment,
       SUM(credits_billed)                    AS billed
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY 1 DESC, billed DESC;
```

Cloud services above the free 10%:
```sql
SELECT usage_date,
       SUM(IFF(service_type = 'WAREHOUSE_METERING', credits_used_compute, 0)) AS wh_compute,
       SUM(credits_used_cloud_services)       AS cloud_services,
       SUM(credits_adjustment_cloud_services) AS adjustment,
       ROUND(DIV0(SUM(credits_used_cloud_services),
                  SUM(IFF(service_type = 'WAREHOUSE_METERING', credits_used_compute, 0))) * 100, 1) AS cs_pct
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1 ORDER BY 1 DESC;
```
cs_pct persistently > 10% usually means: very frequent tiny queries, dynamic tables with short lag, heavy `SHOW`/metadata calls, or COPY over huge file lists.

## 2. Warehouse spend

Daily per warehouse:
```sql
SELECT DATE_TRUNC('day', start_time) AS day, warehouse_name,
       ROUND(SUM(credits_used_compute), 2) AS compute_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

Hour-of-day heatmap (find warehouses that run all night for nothing):
```sql
SELECT warehouse_name, HOUR(start_time) AS hour_of_day,
       ROUND(AVG(credits_used_compute), 2) AS avg_credits,
       ROUND(AVG(credits_used_compute - credits_attributed_compute_queries), 2) AS avg_idle
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD(day, -14, CURRENT_DATE())
GROUP BY 1, 2
ORDER BY 1, 2;
```

Idle credits and idle % per warehouse: see SKILL.md section 3. Snowflake-Labs WAF thresholds: idle < 25% on track, 25–40% needs improvement, > 40% needs attention.

Warehouse configuration audit:
```sql
SHOW WAREHOUSES
->> SELECT "name", "state", "type", "size", "auto_suspend", "auto_resume",
           "min_cluster_count", "max_cluster_count", "scaling_policy",
           "enable_query_acceleration", "resource_monitor"
    FROM $1
    ORDER BY "size";
```
(If a column name errors on your client version, run `SHOW WAREHOUSES` alone and read the header.)

## 3. Per-query cost

Most expensive individual queries:
```sql
SELECT a.query_id, a.warehouse_name, a.user_name, a.query_tag,
       ROUND(a.credits_attributed_compute, 3) AS credits,
       q.warehouse_size,
       ROUND(q.execution_time / 1000, 1)     AS exec_s,
       q.partitions_scanned, q.partitions_total,
       q.bytes_spilled_to_remote_storage,
       LEFT(q.query_text, 200)               AS query_text
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY a
JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
  ON q.query_id = a.query_id
 AND q.start_time >= DATEADD(day, -8, CURRENT_TIMESTAMP())
WHERE a.start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY a.credits_attributed_compute DESC
LIMIT 50;
```

Repeated query shapes (parameterized hash) — SKILL.md section 3. For hierarchical jobs (stored procedure calling many statements) roll up by `root_query_id`:
```sql
SELECT COALESCE(root_query_id, query_id) AS root, SUM(credits_attributed_compute) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY 2 DESC LIMIT 25;
```

Cost by user, role-free (QUERY_ATTRIBUTION_HISTORY carries `user_name` and `query_tag`):
```sql
SELECT user_name, COALESCE(NULLIF(query_tag, ''), '(untagged)') AS tag,
       ROUND(SUM(credits_attributed_compute), 2) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP())
GROUP BY 1, 2 ORDER BY 3 DESC;
```
Set tags at source: `ALTER SESSION SET QUERY_TAG = 'team=reporting;job=daily_rollup';` (dbt, Airflow and most drivers can set this per job). For idle cost per team, allocate each warehouse's idle credits proportionally to that team's attributed credits.

## 4. Performance signals that cost money

Spill and queueing per warehouse:
```sql
SELECT warehouse_name, warehouse_size,
       COUNT(*)                                             AS queries,
       COUNT_IF(bytes_spilled_to_local_storage > 0)         AS local_spill_q,
       COUNT_IF(bytes_spilled_to_remote_storage > 0)        AS remote_spill_q,
       ROUND(SUM(bytes_spilled_to_remote_storage) / POWER(1024, 3), 1) AS remote_spill_gb,
       ROUND(DIV0(SUM(queued_overload_time), SUM(total_elapsed_time)) * 100, 1) AS queued_pct,
       ROUND(AVG(percentage_scanned_from_cache) * 100, 1)   AS avg_cache_pct
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
  AND warehouse_name IS NOT NULL
GROUP BY 1, 2
ORDER BY remote_spill_gb DESC;
```
WAF thresholds: queued < 5% of elapsed on track, > 30% needs attention; remote spill < 0.5% of bytes scanned on track, > 2% needs attention.

Worst-pruning tables:
```sql
SELECT database_name, schema_name, table_name,
       SUM(num_queries)                         AS queries,
       SUM(partitions_scanned)                  AS scanned,
       SUM(partitions_pruned)                   AS pruned,
       ROUND(DIV0(SUM(partitions_pruned), SUM(partitions_scanned) + SUM(partitions_pruned)) * 100, 1) AS prune_pct,
       ROUND(SUM(aggregate_query_execution_time) / 1000 / 3600, 1) AS exec_hours
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_QUERY_PRUNING_HISTORY
WHERE interval_start_time >= DATEADD(day, -14, CURRENT_TIMESTAMP())
GROUP BY 1, 2, 3
HAVING SUM(partitions_scanned) > 10000
ORDER BY exec_hours DESC
LIMIT 25;
```
High exec_hours with low prune_pct = clustering or search-optimization candidate.

What Snowflake itself flagged:
```sql
SELECT insight_type_id, COUNT(DISTINCT query_id) AS queries,
       ROUND(SUM(total_elapsed_time) / 1000 / 3600, 1) AS elapsed_hours
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_INSIGHTS
WHERE start_time >= DATEADD(day, -14, CURRENT_TIMESTAMP())
  AND is_opportunity
GROUP BY 1 ORDER BY 3 DESC;
```
(`total_elapsed_time` repeats per insight row; the sum overcounts queries with several insights — fine for ranking.)

QAS candidates:
```sql
SELECT warehouse_name, COUNT(*) AS eligible_queries,
       ROUND(SUM(eligible_query_acceleration_time) / 3600, 1) AS eligible_hours,
       MEDIAN(upper_limit_scale_factor) AS median_scale_factor
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ACCELERATION_ELIGIBLE
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1 ORDER BY eligible_hours DESC;
```
Then per query: `SELECT PARSE_JSON(SYSTEM$ESTIMATE_QUERY_ACCELERATION('<query_id>'));`

## 5. Serverless spend

```sql
SELECT 'clustering' AS feature, database_name || '.' || schema_name || '.' || table_name AS object, SUM(credits_used) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP()) GROUP BY 1, 2
UNION ALL
SELECT 'search_opt', database_name || '.' || schema_name || '.' || base_table_name, SUM(credits_used)
FROM SNOWFLAKE.ACCOUNT_USAGE.SEARCH_OPTIMIZATION_HISTORY WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP()) GROUP BY 1, 2
UNION ALL
SELECT 'mv', database_name || '.' || schema_name || '.' || table_name, SUM(credits_used)
FROM SNOWFLAKE.ACCOUNT_USAGE.MATERIALIZED_VIEW_REFRESH_HISTORY WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP()) GROUP BY 1, 2
UNION ALL
SELECT 'serverless_task', database_name || '.' || schema_name || '.' || task_name, SUM(credits_used)
FROM SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP()) GROUP BY 1, 2
UNION ALL
SELECT 'pipe', pipe_name, SUM(credits_used)
FROM SNOWFLAKE.ACCOUNT_USAGE.PIPE_USAGE_HISTORY WHERE start_time >= DATEADD(day, -30, CURRENT_TIMESTAMP()) GROUP BY 1, 2
ORDER BY credits DESC
LIMIT 50;
```
Clustering worth it? Compare a table's clustering credits with the drop in scan time on queries against it (TABLE_QUERY_PRUNING_HISTORY before/after). Suspend with `ALTER TABLE t SUSPEND RECLUSTER;`.

Multipliers to keep in mind (credits per compute-hour; Service Consumption Table, 30 Sep 2026): Clustering Classic 2 (+1 cloud services), MV maintenance 2 (+1), Search Optimization 2 (+1), Serverless Tasks 0.9 (+1), Serverless Tasks Flex 0.5, QAS 1, Iceberg automated refresh 1.25, Optima Clustering 0.007 credits per uncompressed GB, Snowpipe and Snowpipe Streaming 0.0037 credits per GB, Snowpipe Streaming Classic 1 + 0.01 credits per client-hour.

## 6. Dynamic table refresh cost

```sql
SELECT r.qualified_name, r.refresh_action,
       COUNT(*)                                       AS refreshes,
       ROUND(SUM(a.credits_attributed_compute), 2)    AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.DYNAMIC_TABLE_REFRESH_HISTORY r
LEFT JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY a
  ON a.query_id = r.query_id
 AND a.start_time >= DATEADD(day, -8, CURRENT_TIMESTAMP())
WHERE r.refresh_start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1, 2
ORDER BY credits DESC NULLS LAST;
```
Lots of `NO_DATA` refreshes = lag too short (cloud services cost). Any `FULL` or `REINITIALIZE` you didn't expect = check the DT's refresh mode. The warehouse's 60-second minimum applies per resume, so many small DTs on one warehouse with aligned lags is cheaper than staggered ones.

## 7. Storage

```sql
SELECT table_catalog || '.' || table_schema || '.' || table_name AS tbl,
       is_transient,
       ROUND(active_bytes / POWER(1024, 4), 3)               AS active_tb,
       ROUND(time_travel_bytes / POWER(1024, 4), 3)          AS time_travel_tb,
       ROUND(failsafe_bytes / POWER(1024, 4), 3)             AS failsafe_tb,
       ROUND(retained_for_clone_bytes / POWER(1024, 4), 3)   AS clone_retained_tb,
       table_dropped
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
WHERE active_bytes + time_travel_bytes + failsafe_bytes + retained_for_clone_bytes > 0
ORDER BY time_travel_bytes + failsafe_bytes DESC
LIMIT 50;
```
WAF threshold: Time Travel + Fail-safe < 20% of total storage on track, > 50% needs attention. Fixes: shorter `DATA_RETENTION_TIME_IN_DAYS` on churny tables, TRANSIENT for rebuildable staging, avoid `INSERT OVERWRITE`/full rebuilds of large permanent tables (each rebuild lands the old copy in TT then Fail-safe).

Unused tables (no reads in 90 days) — Snowflake-Labs WAF pattern, uses `ACCESS_HISTORY` (Enterprise+):
```sql
WITH read_tables AS (
  SELECT DISTINCT UPPER(REPLACE(f.value:objectName::STRING, '"', '')) AS full_name
  FROM SNOWFLAKE.ACCOUNT_USAGE.ACCESS_HISTORY,
       LATERAL FLATTEN(input => base_objects_accessed) f
  WHERE query_start_time > DATEADD(day, -90, CURRENT_TIMESTAMP())
)
SELECT t.table_catalog, t.table_schema, t.table_name,
       ROUND(t.active_bytes / POWER(1024, 3), 1) AS active_gb
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS t
LEFT JOIN read_tables r
  ON UPPER(t.table_catalog || '.' || t.table_schema || '.' || t.table_name) = r.full_name
WHERE t.table_dropped IS NULL AND r.full_name IS NULL
  AND t.active_bytes > 0 AND t.table_created < DATEADD(day, -90, CURRENT_TIMESTAMP())
ORDER BY t.active_bytes DESC
LIMIT 50;
```

## 8. Guardrails

```sql
-- Warehouse-level hard stop (warehouses only; ACCOUNTADMIN)
CREATE OR REPLACE RESOURCE MONITOR rm_etl
  WITH CREDIT_QUOTA = 2000 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  NOTIFY_USERS = (alice)
  TRIGGERS ON 80 PERCENT DO NOTIFY
           ON 100 PERCENT DO SUSPEND
           ON 120 PERCENT DO SUSPEND_IMMEDIATE;
ALTER WAREHOUSE etl_wh SET RESOURCE_MONITOR = rm_etl;

-- Runaway query cap (default is 172800 s = 48 h)
ALTER WAREHOUSE bi_wh SET STATEMENT_TIMEOUT_IN_SECONDS = 600 STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 120;

-- Idle policy
ALTER WAREHOUSE etl_wh SET AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;
```
Resource monitors: frequencies DAILY/WEEKLY/MONTHLY/YEARLY/NEVER, reset at 00:00 UTC; `SUSPEND` waits for running queries, `SUSPEND_IMMEDIATE` cancels them. They don't cover serverless features — use **Budgets** (account budget plus custom budgets over tagged objects) for those.

Sources: per-view pages under https://docs.snowflake.com/en/sql-reference/account-usage/ — `query_attribution_history`, `warehouse_metering_history`, `query_history`, `metering_daily_history`, `query_insights`, `table_query_pruning_history`, `query_acceleration_eligible`, `automatic_clustering_history`, `search_optimization_history`, `materialized_view_refresh_history`, `serverless_task_history`, `pipe_usage_history`, `dynamic_table_refresh_history`, `table_storage_metrics`; resource monitors https://docs.snowflake.com/en/user-guide/resource-monitors; dynamic table costs https://docs.snowflake.com/en/user-guide/dynamic-tables/cost; Service Consumption Table https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf; Snowflake-Labs/coco-skills WAF control YAMLs (thresholds, idle/unused/TT-FS queries).
