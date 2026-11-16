---
name: snowflake
description: >-
  Snowflake reference, cost and performance first: credits, warehouse sizing, caches,
  pruning, clustering, Query Profile, search optimization, QAS, MVs vs dynamic tables vs
  streams and tasks, Snowpipe, Iceberg tables and catalogs, ACCOUNT_USAGE cost SQL, Snowpark,
  RBAC, Time Travel. Load whenever the work touches Snowflake. Triggers: "snowflake",
  "warehouse size", "credits", "snowflake cost", "query profile", "slow query", "spilling",
  "clustering key", "micro-partition", "pruning", "search optimization", "materialized view",
  "dynamic table", "target lag", "streams and tasks", "snowpipe", "COPY INTO",
  "snowflake iceberg", "external volume", "catalog integration", "catalog-linked database",
  "horizon catalog", "open catalog", "ACCOUNT_USAGE", "QUERY_ATTRIBUTION_HISTORY",
  "resource monitor", "query acceleration", "Gen2", "multi-cluster", "auto-suspend",
  "result cache", "snowpark", "time travel", "when to use snowflake", "snowflake vs".
---

# Snowflake — platform reference (cost and performance first)

State as of October 2026. Prices and multipliers come from the Service Consumption Table dated
30 Sep 2026; feature status churns, so check the linked doc before asserting GA vs preview.

Deeper material:
- [references/cost-sql.md](references/cost-sql.md) — ready ACCOUNT_USAGE queries: per-query cost, warehouse spend, idle, serverless spend, storage, attribution, guardrails
- [references/performance.md](references/performance.md) — Query Profile field guide, clustering, search optimization, QAS, warehouse sizing detail
- [references/ingestion-pipelines.md](references/ingestion-pipelines.md) — COPY, Snowpipe, Snowpipe Streaming, streams, tasks, dynamic tables, MVs, worked SQL
- [references/iceberg-interop.md](references/iceberg-interop.md) — managed vs external Iceberg, catalog integrations, catalog-linked DBs, Horizon REST for Spark, lakehouse patterns
- [references/concepts.md](references/concepts.md) — plain-English glossary of ~80 Snowflake terms, typical use cases, and the full when-to-use table

## When to use it / when not to

| Situation | Verdict | Instead, and why |
|---|---|---|
| SQL analytics and ELT over many sources, bursty load | Use | Pay only while warehouses run; no capacity planning |
| Internal BI, tens to hundreds of users | Use | Multi-cluster warehouse + result cache; keep it off the ELT warehouse |
| Sharing live data with partners or customers | Use | Secure Data Sharing: no copies, consumer pays compute |
| Near-real-time reporting (minutes of lag) | Use | Snowpipe Streaming + dynamic tables |
| Customer-facing, high-QPS, sub-second queries | Avoid on standard warehouses | Warehouse sized for peak runs all day; precompute here, serve from ClickHouse / Druid / Pinot, OpenSearch, or a precomputed key-value/Postgres table. Interactive warehouses exist but are effectively always-on (24 h minimum auto-suspend, 5 s query cap) |
| OLTP system of record | Avoid | Immutable micro-partitions make single-row writes expensive; use Postgres (or Snowflake Postgres) and replicate in |
| Large-scale ML training, images/audio/video | Usually avoid | Databricks / Spark have the mature distributed-training and GPU ecosystem |
| Petabytes of raw or rarely read data | Don't load it | Iceberg on S3 at object-storage prices; query slices via a catalog-linked database |
| Full-text relevance search | Avoid | OpenSearch / Elasticsearch |
| Per-event, millisecond stream processing | Avoid | Flink / Kafka Streams |
| Under ~100 GB, tiny team | Often overkill | Postgres or DuckDB |

Reasons and examples for each row: [references/concepts.md](references/concepts.md).

## 1. Mental model

Three layers, billed separately:

| Layer | What it is | How it bills |
|---|---|---|
| **Storage** | Immutable columnar **micro-partitions** (50–500 MB uncompressed) in cloud object storage, plus per-partition metadata (min/max per column, distinct counts) | $/TB-month on compressed bytes, including Time Travel, Fail-safe and clone-retained bytes |
| **Compute** | **Virtual warehouses** you size and start; **serverless** features run on Snowflake-managed compute | Credits per second while running, **60-second minimum on every start/resume**; serverless = compute-hours × a feature multiplier |
| **Cloud services** | Parsing, optimising, metadata, auth, result cache, change detection | 4.4 credits/hour of use, but only the part above **10% of that day's warehouse credits** is billed (daily, UTC; serverless doesn't count toward the 10%) |

Consequences that drive almost every decision:
- **You pay for time a warehouse is running, not for work done.** An idle warehouse waiting for auto-suspend costs the same as a busy one. Per-query cost is an attribution, not a meter.
- **Speed comes from not reading data.** Pruning uses partition min/max metadata to skip micro-partitions; it only works if the data is physically ordered the way queries filter. Natural load order (usually time) is free clustering.
- **DML rewrites whole micro-partitions.** An UPDATE touching one row per partition rewrites every partition — cost, Time Travel storage, and re-clustering churn all follow.
- **Each size up doubles credits/hour and roughly doubles resources.** If a query scales linearly, a bigger warehouse costs the same and finishes faster; if it doesn't (small scans, single-threaded steps), you pay double for nothing.

Credits/hour, standard Gen1: XS 1, S 2, M 4, L 8, XL 16, 2XL 32, 3XL 64, 4XL 128, 5XL 256, 6XL 512.
**Gen2** (default for new standard warehouses where available; no 5XL/6XL): **1.35×** Gen1 on AWS and GCP, **1.25×** on Azure. Faster hardware plus DML/scan improvements; only cheaper if queries finish more than ~26% (AWS) faster. Gen2 is also required for Optima indexing/planning. Benchmark the real workload before switching.
Credit price on demand is region/edition-dependent (e.g. AWS US East: $2 Standard, $3 Enterprise, $4 Business Critical; EU Dublin $2.60/$3.90/$5.20).

**The three caches**
| Cache | Where | Lifetime | Note |
|---|---|---|---|
| Result cache | Cloud services | 24 h, reset on reuse up to 31 days | Exact query text match, data unchanged, same role privileges, no non-deterministic functions; **no warehouse needed** — free. `USE_CACHED_RESULT` toggles it |
| Warehouse (local disk) cache | Warehouse SSD | **Dropped on suspend** | Why BI warehouses want ≥10 min auto-suspend; `percentage_scanned_from_cache` in QUERY_HISTORY |
| Metadata | Cloud services | Always | `COUNT(*)`, `MIN/MAX` on columns can be answered with no scan ("Metadata-based Result" in the profile) |

**Warehouse controls**: `AUTO_SUSPEND` (seconds), `AUTO_RESUME`, multi-cluster (`MIN/MAX_CLUSTER_COUNT`, Enterprise+) with `SCALING_POLICY = STANDARD` (start a cluster as soon as queries queue) or `ECONOMY` (only when there's ~6 minutes of work for it). Multi-cluster fixes **concurrency/queuing**, a bigger size fixes **single-query slowness and spilling** — don't confuse the two. **Adaptive warehouses** (GA, Enterprise+) replace size/cluster/QAS/suspend knobs with `MAX_QUERY_PERFORMANCE_LEVEL` and `QUERY_THROUGHPUT_MULTIPLIER`, billed per query (tracked in `QUERY_METERING_HISTORY`, not QUERY_ATTRIBUTION_HISTORY).

Auto-suspend guidance from the docs: loading/tasks → suspend immediately (60 s); ad-hoc/data-science → ~5 min; BI/dashboards → ≥10 min to keep the disk cache. If queries arrive every 30 min, a 10-min suspend just buys 10 idle minutes per query.

## 2. Slow-query diagnosis (Query Profile)

**Pick the query before profiling it.**
- Flag a query only if it is both **important** (≥5% of total warehouse time, or on a user-facing path) and **bad**.
- Triage flagged queries by the time you could win back, not raw time share: a heavy query that is already doing inherent work has little to recover.
- Confirm a flagged query still runs (current QUERY_HISTORY) before debugging it; review windows go stale.
- A sharp drop in duration with flat call counts marks a deployed fix.

Open the query in Snowsight → Query History → Query Profile (or `SELECT * FROM TABLE(GET_QUERY_OPERATOR_STATS('<query_id>'))` for the same data as rows, last 14 days).

1. **Was it even running?** Compare `total_elapsed_time` with `execution_time` in QUERY_HISTORY. Large `queued_overload_time` = warehouse saturated (concurrency). Large `queued_provisioning_time` = resume/cold start. Large `compilation_time` = huge SQL, many views, or metadata-heavy (thousands of tiny files/partitions). None of these are fixed by rewriting the query.
2. **Profile Overview → percentage of time.** Processing (CPU), Local Disk IO / Remote Disk IO (spill or cold scan), Network Communication (data shuffled between nodes), Synchronization, Initialization.
3. **Most Expensive Nodes** (≥1% of time) — start at the top one.
4. **Statistics pane**: Pruning (partitions scanned vs total), Spilling (bytes to local / remote storage), IO (bytes scanned, % from cache), Network.
5. **Query Insights pane** (and `ACCOUNT_USAGE.QUERY_INSIGHTS`): Snowflake already flags exploding joins, joins without conditions, unselective filters, leading-wildcard LIKE, unnecessary UNION DISTINCT, remote spillage, queued overload.
6. Change one thing, re-run with `ALTER SESSION SET USE_CACHED_RESULT = FALSE`, compare.

| Symptom in profile | Likely cause | Fix |
|---|---|---|
| TableScan dominant, partitions scanned ≈ total | No pruning: filter column not correlated with storage order, or filter wrapped in a function/cast | Filter on the raw column; cluster on the filter column(s) (multi-TB tables only); for point lookups use search optimization |
| Bytes spilled to **local** storage | Intermediate state > memory | Tolerable; reduce rows earlier (filter/aggregate before join), or size up |
| Bytes spilled to **remote** storage | Badly out of memory — usually 10×+ slower | Size up one step at a time, or split the work; check for an exploding join first |
| Join output rows ≫ input rows | Exploding join (missing/duplicated key, many-to-many) | Fix join keys; dedupe the dimension; check `QUALIFY ROW_NUMBER()` |
| Aggregate on UNION, heavy Sort | `UNION` instead of `UNION ALL`, unnecessary DISTINCT/ORDER BY | Use `UNION ALL`; remove sorts not needed by the consumer |
| Network Communication dominant | Large shuffle (big × big join, high-cardinality GROUP BY) | Pre-aggregate; join on clustered keys; avoid `SELECT *` on wide tables |
| `queued_overload_time` high, execution fast | Too many concurrent queries for one cluster | Multi-cluster (STANDARD policy for user-facing, ECONOMY for batch) or separate warehouses per workload |
| `compilation_time` high | Deep view stacks, huge IN lists, many tiny partitions | Flatten views; stage IN lists in a table; compact small-file tables |
| Fast but repeated thousands of times | Dashboard or app polling | Result cache (keep text identical), MV / dynamic table pre-aggregate, or serve from a cheaper store |
| Large scan, selective filter, ad-hoc and bursty | Outlier queries on an undersized warehouse | Query Acceleration Service (`ENABLE_QUERY_ACCELERATION`), check `QUERY_ACCELERATION_ELIGIBLE` first |
| Remote Disk IO with 0% from cache | Cold cache after resume | Longer auto-suspend for BI warehouses, or accept |

Detail per operator, clustering depth, SOS and QAS sizing: [references/performance.md](references/performance.md).

## 3. Cost-control playbook

Views live in `SNOWFLAKE.ACCOUNT_USAGE` (1-year history, 45 min–8 h latency; needs `IMPORTED PRIVILEGES` on SNOWFLAKE or the `USAGE_VIEWER` database role). Full set in [references/cost-sql.md](references/cost-sql.md).

**Where is the money going? (by service, last 30 days)**
```sql
SELECT service_type, SUM(credits_billed) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date >= DATEADD(day, -30, CURRENT_DATE())
GROUP BY 1 ORDER BY 2 DESC;
```

**Top query shapes by cost (last 7 days)** — groups re-runs of the same query with different literals:
```sql
SELECT a.query_parameterized_hash,
       ANY_VALUE(q.query_text)                         AS sample_text,
       ANY_VALUE(a.warehouse_name)                     AS warehouse,
       COUNT(*)                                        AS runs,
       ROUND(SUM(a.credits_attributed_compute), 2)     AS compute_credits,
       ROUND(SUM(COALESCE(a.credits_used_query_acceleration, 0)), 2) AS qas_credits,
       ROUND(AVG(q.total_elapsed_time) / 1000, 1)      AS avg_elapsed_s
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_ATTRIBUTION_HISTORY a
JOIN SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY q
  ON q.query_id = a.query_id
 AND q.start_time >= DATEADD(day, -8, CURRENT_TIMESTAMP())
WHERE a.start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY compute_credits DESC
LIMIT 25;
```
QUERY_ATTRIBUTION_HISTORY excludes idle time, queries ≤ ~100 ms, cloud services and serverless; latency up to 8 h.

**Warehouse spend and idle share (last 30 days)**
```sql
SELECT warehouse_name,
       ROUND(SUM(credits_used), 1)                       AS total_credits,
       ROUND(SUM(credits_used_compute), 1)               AS compute_credits,
       ROUND(SUM(credits_attributed_compute_queries), 1) AS query_credits,
       ROUND(SUM(credits_used_compute) - SUM(credits_attributed_compute_queries), 1) AS idle_credits,
       ROUND(DIV0(SUM(credits_used_compute) - SUM(credits_attributed_compute_queries),
                  SUM(credits_used_compute)) * 100, 1)   AS idle_pct
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE start_time >= DATEADD(day, -30, CURRENT_DATE())
  AND end_time < CURRENT_DATE()
GROUP BY 1
ORDER BY total_credits DESC;
```
Snowflake-Labs' WAF assessment treats >25% idle as "needs improvement" and >40% as "needs attention".

**Warehouses configured to burn idle time**
```sql
SHOW WAREHOUSES
->> SELECT "name", "size", "auto_suspend", "auto_resume",
           "min_cluster_count", "max_cluster_count", "scaling_policy", "resource_monitor"
    FROM $1
    WHERE "auto_suspend" IS NULL OR "auto_suspend" = 0 OR "auto_suspend" > 600
    ORDER BY "auto_suspend" DESC NULLS FIRST;
```
(`->>` is the pipe operator; use `TABLE(RESULT_SCAN(LAST_QUERY_ID()))` on older clients.)

**Levers, in the order they usually pay off**
1. **Kill idle**: auto-suspend 60 s for batch/ELT, consolidate low-utilisation warehouses, drop min-cluster > 1 unless latency SLAs need it.
2. **Right-size**: drop a size where spill is zero and queries don't get slower in proportion; size up where remote spill dominates (it may get *cheaper*).
3. **Isolate workloads** (ELT, BI, data science, customer-facing) on separate warehouses so each gets its own suspend/size/policy and its own line on the bill. Tag warehouses and set `QUERY_TAG` for attribution.
4. **Stop repeat work**: duplicated dashboards hitting raw tables → result cache, MVs or dynamic tables; high-QPS customer-facing reads → move to the lakehouse/serving store rather than a permanently-on multi-cluster warehouse.
5. **Watch serverless** — invisible to resource monitors: Automatic Clustering (2× multiplier), Search Optimization (2×), MV maintenance (2×), serverless tasks (0.9×), QAS (1×), Snowpipe (0.0037 credits/GB). Check `METERING_DAILY_HISTORY` by service_type weekly.
6. **Storage**: long Time Travel on churny tables, Fail-safe on rebuildable staging (use TRANSIENT), forgotten clones and dropped-but-retained tables (`TABLE_STORAGE_METRICS`).
7. **Guardrails**: `STATEMENT_TIMEOUT_IN_SECONDS` per warehouse (default is 172,800 s = 2 days), resource monitors with `SUSPEND` on warehouses, **Budgets** for serverless and per-tag spend.

```sql
CREATE RESOURCE MONITOR rm_bi WITH CREDIT_QUOTA = 500 FREQUENCY = MONTHLY START_TIMESTAMP = IMMEDIATELY
  TRIGGERS ON 75 PERCENT DO NOTIFY ON 100 PERCENT DO SUSPEND ON 110 PERCENT DO SUSPEND_IMMEDIATE;
ALTER WAREHOUSE bi_wh SET RESOURCE_MONITOR = rm_bi;          -- ACCOUNTADMIN only
ALTER WAREHOUSE bi_wh SET STATEMENT_TIMEOUT_IN_SECONDS = 900;
```

## 4. Precompute: MV vs dynamic table vs streams + tasks

| Need | Use | Why / limits |
|---|---|---|
| Speed up repeated filters/aggregates on **one** table; want queries against the base table rewritten automatically | **Materialized view** (Enterprise+) | No joins, no window functions, no UDFs, no HAVING/ORDER BY/LIMIT; limited aggregates. Serverless maintenance at 2×, always current. Optimizer can rewrite base-table queries to use it |
| Declarative multi-table SQL pipeline (joins, aggregates, layers) with freshness measured in minutes | **Dynamic table** | `TARGET_LAG` ≥ 60 s or `DOWNSTREAM`; runs on *your* warehouse (60 s minimum per refresh); check refresh mode resolved to INCREMENTAL, not FULL. No stored procs/external functions, no direct DML into it |
| Procedural logic, MERGE/upserts, SCD2, calling procedures or external APIs, custom retries, exactly-once CDC consumption | **Streams + tasks** | Stream gives the delta since last consumption; task runs on a schedule or is triggered by the stream. Most control, most code |
| Point lookups / substring search on a huge table, not precomputation | **Search optimization** | Index-like access paths, serverless 2× maintenance plus storage |
| Same answer over and over within 24 h, data unchanged | **Result cache** | Free; exact text match required |

Rules of thumb: dynamic tables replace most stream+task+MERGE chains; set intermediate DTs to `DOWNSTREAM`; never set lag shorter than the consumer needs (each DT does a change check every cycle — 200 DTs at 1-minute lag ≈ 288k checks/day in cloud services). Worked examples: [references/ingestion-pipelines.md](references/ingestion-pipelines.md).

## 5. Ingestion in one table

| Path | Latency | Billing | Use when |
|---|---|---|---|
| `COPY INTO` on a warehouse | Batch | Warehouse time | Scheduled bulk loads; files 100–250 MB compressed; 64-day load metadata dedupes re-runs |
| Snowpipe (`AUTO_INGEST`) | ~1 min | **0.0037 credits/GB** (uncompressed for text, observed size for Parquet/Avro/ORC) | Continuous file drops; stage ~1 file/min, not hundreds of tiny files |
| Snowpipe Streaming (high-performance) | as low as ~5 s | 0.0037 credits per uncompressed GB | Kafka/CDC/app rows without files; writes to native or Snowflake-managed Iceberg tables |
| Snowpipe Streaming Classic | seconds | Serverless compute + 0.01 credits per client-hour | Legacy ingest-java SDK ≤ 4.x; plan migration |

## 6. Iceberg interop (summary)

| | Snowflake-managed (`CATALOG = 'SNOWFLAKE'`) | Externally managed (Glue, Iceberg REST: Polaris/Open Catalog/Unity, or metadata files) |
|---|---|---|
| Writes from Snowflake | Full DML | Supported via REST catalogs / catalog-linked DBs, with limits (no multi-statement transactions) |
| Writes from Spark | Yes, through the **Horizon Iceberg REST endpoint** (`https://<account>.snowflakecomputing.com/polaris/api/catalog`, vended credentials) | Yes — the external catalog owns commits |
| Maintenance | Snowflake compacts, expires snapshots, can cluster | **You** compact/expire; Snowflake won't; no clustering |
| Freshness in Snowflake | Immediate | `AUTO_REFRESH` polling (default 30 s) or `ALTER ICEBERG TABLE … REFRESH`; auto-refresh billed on the Snowpipe line at 1.25× |
| Protection | Time Travel; Fail-safe only on Snowflake storage | No Fail-safe |
| Storage bill | Your cloud account (external volume) or Snowflake (`SNOWFLAKE_MANAGED`) | Your cloud account |

Key facts for a Spark/Iceberg + Databricks estate:
- **Catalog-linked database** (`CREATE DATABASE … LINKED_CATALOG = (CATALOG = '<integration>')`) mirrors a whole REST catalog (Glue, Unity Catalog, Open Catalog/Polaris) and auto-discovers namespaces and tables every 30 s by default — the low-effort way to let Snowflake query lakehouse tables without copies.
- **Equality deletes are not supported** (position deletes for v2, deletion vectors for v3 only). Flink/streaming upsert writers that emit equality deletes produce tables Snowflake can't read correctly — compact or switch to merge-on-read with position deletes.
- Parquet only. For tables Spark must also read, set `STORAGE_SERIALIZATION_POLICY = COMPATIBLE`.
- **Open Catalog** (managed Polaris) is closed to new customers; Snowflake points new users to **Horizon Catalog**. Horizon REST API calls are billed 0.5 credits per million.
- One owner per table: don't let both Snowflake and Spark/Databricks run compaction or snapshot expiry on the same table.

Setup SQL, decision guide and failure modes: [references/iceberg-interop.md](references/iceberg-interop.md). For Iceberg format internals (delete files, maintenance, v3) load the `iceberg` skill.

## 7. Platform basics worth having to hand

- **RBAC**: privileges go to roles, roles to users (and roles to roles). System roles: ORGADMIN, ACCOUNTADMIN (top, use sparingly, MFA), SECURITYADMIN (manage grants), USERADMIN (users/roles), SYSADMIN (owns warehouses/databases), PUBLIC. Grant custom roles up to SYSADMIN so objects stay manageable. Use **database roles** for object-level access bundles, `GRANT … ON FUTURE TABLES IN SCHEMA` for new objects, managed-access schemas to centralise grants. Row access policies and masking policies for multi-tenant/PII.
- **Time Travel**: `DATA_RETENTION_TIME_IN_DAYS` default 1, up to 90 on Enterprise+ for permanent objects; transient/temporary 0–1. `AT(TIMESTAMP => …)`, `AT(OFFSET => -300)`, `BEFORE(STATEMENT => '<query_id>')`, `UNDROP`, zero-copy `CLONE … AT(…)`.
- **Fail-safe**: 7 further days, permanent tables only, recoverable only by Snowflake support, still billed as storage. Transient tables skip it — use them for rebuildable staging.
- **Snowpark** (Python/Java/Scala): lazy DataFrames compiled to SQL and run on a warehouse; UDFs/UDTFs/stored procedures run server-side. Snowpark-optimized warehouses give more memory per node for ML/large UDF state. **Snowpark Connect for Apache Spark** runs PySpark DataFrame code against Snowflake compute — relevant when comparing "move Spark jobs into Snowflake" vs keeping them in the lakehouse.
- **Snowflake ML Feature Store**: entities plus feature views backed by dynamic tables (or external pipelines), with a Model Registry. The **Online Feature Store** (served from Snowflake Postgres, AWS and Azure) is GA. Weaker than Databricks for distributed or GPU custom training.

## 8. Pitfalls

- **60-second minimum per resume**: a warehouse woken every 30 s by a poller bills ~continuous. Batch tiny tasks; prefer serverless tasks for short frequent jobs.
- **Per-query cost hides idle.** Sum of QUERY_ATTRIBUTION_HISTORY ≠ the bill; idle, cloud services and serverless sit outside it.
- **Multi-cluster `MIN_CLUSTER_COUNT > 1`** pays for N clusters all day. Maximized mode is rarely right.
- **Resource monitors don't see serverless or (fully) cloud services** — use Budgets.
- **Clustering keys on small or high-churn tables** burn Automatic Clustering credits (2×) forever. Only for multi-TB tables with a stable filter pattern and a high read:write ratio; ≤ 3–4 keys, low→high cardinality, use `TO_DATE(ts)` not `ts`.
- **Functions on filter columns** (`WHERE DATE(ts) = …`, implicit casts) can defeat pruning; compare raw columns to constants.
- **Search optimization on everything**: storage + 2× maintenance per table; estimate first with `SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS`.
- **Dynamic table AUTO resolving to FULL** silently reprocesses the whole table each refresh; check `refresh_mode` in `SHOW DYNAMIC TABLES` and REINITIALIZE in refresh history.
- **Tasks are created suspended**; streams go **stale** if not consumed within retention (extended up to 14 days by `MAX_DATA_EXTENSION_TIME_IN_DAYS`).
- **Result cache misses** on whitespace/case differences, `CURRENT_TIMESTAMP()`, changed role, or any DML to the table.
- **Long Time Travel on high-churn tables** multiplies storage; set retention per table.
- **ACCOUNT_USAGE latency** (45 min–8 h): don't conclude "no spend" from today's rows. INFORMATION_SCHEMA table functions are real-time but short-retention.
- **Gen2 default**: new standard warehouses default to Gen2 at 1.25–1.35× the rate; check `RESOURCE_CONSTRAINT`/generation before comparing costs month-on-month.
- **SEARCH_OPTIMIZATION_HISTORY renamed columns**: `TABLE_NAME` → `INDEX_NAME`/`BASE_TABLE_NAME`; older blog SQL breaks.

## Sources

Official docs (fetched October 2026):
- Compute cost: https://docs.snowflake.com/en/user-guide/cost-understanding-compute
- Online Feature Store GA: https://docs.snowflake.com/en/release-notes/2026/other/2026-10-20-online-feature-store-ga
- Service Consumption Table (30 Sep 2026): https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf
- Gen2: https://docs.snowflake.com/en/user-guide/warehouses-gen2 · Multi-cluster: https://docs.snowflake.com/en/user-guide/warehouses-multicluster · Adaptive: https://docs.snowflake.com/en/user-guide/warehouses-adaptive
- Micro-partitions: https://docs.snowflake.com/en/user-guide/tables-clustering-micropartitions · Clustering keys: https://docs.snowflake.com/en/user-guide/tables-clustering-keys
- Result cache: https://docs.snowflake.com/en/user-guide/querying-persisted-results · Warehouse cache: https://docs.snowflake.com/en/user-guide/performance-query-warehouse-cache
- Query Profile: https://docs.snowflake.com/en/user-guide/ui-snowsight-activity · GET_QUERY_OPERATOR_STATS: https://docs.snowflake.com/en/sql-reference/functions/get_query_operator_stats
- ACCOUNT_USAGE: https://docs.snowflake.com/en/sql-reference/account-usage (+ per-view pages listed in references/cost-sql.md)
- Resource monitors: https://docs.snowflake.com/en/user-guide/resource-monitors · QAS: https://docs.snowflake.com/en/user-guide/query-acceleration-service
- Dynamic tables: https://docs.snowflake.com/en/user-guide/dynamic-tables-about · comparison: https://docs.snowflake.com/en/user-guide/dynamic-tables-comparison · cost: https://docs.snowflake.com/en/user-guide/dynamic-tables/cost
- MVs: https://docs.snowflake.com/en/user-guide/views-materialized · SOS: https://docs.snowflake.com/en/user-guide/search-optimization-service
- Streams: https://docs.snowflake.com/en/user-guide/streams-intro · Tasks: https://docs.snowflake.com/en/user-guide/tasks-intro
- Snowpipe pricing: https://docs.snowflake.com/en/release-notes/2025/other/2025-12-08-snowpipe-simplified-pricing
- Iceberg: https://docs.snowflake.com/en/user-guide/tables-iceberg · Horizon REST for external engines: https://docs.snowflake.com/en/user-guide/tables-iceberg-query-using-external-query-engine-snowflake-horizon · Open Catalog: https://docs.snowflake.com/en/user-guide/opencatalog/overview
- Time Travel: https://docs.snowflake.com/en/user-guide/data-time-travel · Snowpark: https://docs.snowflake.com/en/developer-guide/snowpark/index
- Optima: https://docs.snowflake.com/en/user-guide/snowflake-optima

Existing skills/rules borrowed from (credit):
- Snowflake-Labs/coco-skills `well-architected-framework-assessment` (cost and performance control YAMLs): idle-rate SQL, thresholds for idle/queueing/spill/pruning, QUERY_INSIGHTS and TABLE_QUERY_PRUNING_HISTORY checks, storage TT/FS check — https://github.com/Snowflake-Labs/coco-skills
- PatrickJS/awesome-cursorrules `snowflake-data-engineering` rule: pipeline choice framing and anti-patterns (lag shorter than needed, forgetting to RESUME tasks) — https://github.com/PatrickJS/awesome-cursorrules/blob/main/rules/snowflake-data-engineering-cursorrules-prompt-file.mdc
