# Snowflake performance — Query Profile, clustering, SOS, QAS, sizing

## Query Profile field guide

Where: Snowsight → Monitoring → Query History → a query → Query Profile. Programmatic:
```sql
SELECT operator_id, operator_type, parent_operators,
       operator_statistics:input_rows::NUMBER  AS in_rows,
       operator_statistics:output_rows::NUMBER AS out_rows,
       execution_time_breakdown:overall_percentage::FLOAT AS pct_time,
       operator_statistics:spilling AS spilling,
       operator_statistics:pruning  AS pruning
FROM TABLE(GET_QUERY_OPERATOR_STATS('<query_id>'))   -- completed queries, last 14 days
ORDER BY pct_time DESC;
```
`execution_time_breakdown` keys: overall_percentage, initialization, processing, synchronization, local_disk_io, remote_disk_io, network_communication.

Operator families: TableScan, IndexScan (search optimization), ExternalScan, Filter, JoinFilter (runtime bloom filter pruning the probe side), Join, Aggregate, GroupingSets, WindowFunction, Sort, SortWithLimit, Flatten, UnionAll, Insert/Update/Delete/Merge/Unload, Result, and the cheap ones: **Query Result Reuse** (result cache hit) and **Metadata-based Result** (answered from partition metadata).

Reading it:
- **Ratio of output_rows to input_rows on a Join** is the fastest exploding-join check. A Join whose output is many times larger than both inputs is almost always a key problem, not a sizing one.
- **TableScan "Partitions scanned / Partitions total"**: near 1.0 on a big table means no pruning. Check whether the filter is pushed into the scan (it shows as a filter on the TableScan) or applied later in a Filter node (often a function on the column, or a filter from a join that couldn't become a JoinFilter).
- **"Partitions pruned by Snowflake Optima"** in Statistics appears on Gen2/adaptive warehouses when Optima indexing helped.
- **Bytes spilled**: local is a warning, remote is the problem. Spill is per operator — find the one (usually a Join build side, Aggregate or Sort / WindowFunction).
- **Bytes scanned % from cache** low on a frequently repeated query = the warehouse suspended between runs.
- **Initialization dominant** on a short query = overhead; batching statements helps more than sizing.
- **Synchronization dominant** = skew; one worker has most of the data (skewed join key or GROUP BY key, e.g. a NULL or "unknown" bucket).

Common query problems Snowflake calls out: exploding joins, `UNION` without `ALL`, queries too large to fit in memory, inefficient pruning. `ACCOUNT_USAGE.QUERY_INSIGHTS` exposes the same diagnosis at scale; insight types include `QUERY_INSIGHT_EXPLODING_JOIN`, `…_NESTED_EXPLODING_JOIN`, `…_JOIN_WITH_NO_JOIN_CONDITION`, `…_INEFFICIENT_JOIN_CONDITION`, `…_UNSELECTIVE_FILTER`, `…_NO_FILTER_ON_TOP_OF_TABLE_SCAN`, `…_INAPPLICABLE_FILTER_ON_TABLE_SCAN`, `…_LIKE_WITH_LEADING_WILDCARD`, `…_FILTER_WITH_CLUSTERING_KEY`, `…_INEFFICIENT_AGGREGATE`, `…_UNNECESSARY_UNION_DISTINCT`, `…_REMOTE_SPILLAGE`, `…_QUEUED_OVERLOAD`, plus search-optimization and Optima usage notes.

## Pruning and clustering

How pruning works: each micro-partition stores min/max (and distinct count) per column. A predicate `col BETWEEN a AND b` skips any partition whose range doesn't overlap. Pruning quality depends on **overlap** — the clustering depth is the average number of partitions overlapping at a point. Lower is better.

Check a table:
```sql
SELECT SYSTEM$CLUSTERING_INFORMATION('db.sch.events', '(TO_DATE(event_ts), tenant_id)');
SELECT SYSTEM$CLUSTERING_DEPTH('db.sch.events', '(TO_DATE(event_ts))');
```
`average_depth` near 1 and a histogram concentrated in low buckets = well clustered for that expression.

When to add a clustering key (all should be true):
- Multi-TB table with many micro-partitions.
- Most expensive queries filter (or join) on the same column(s), selectively.
- Queries greatly outnumber writes, and writes don't touch partitions all over the table.
- Natural load order doesn't already give you the order you need (time-series loaded in time order usually is already clustered by time).

How:
```sql
ALTER TABLE events CLUSTER BY (TO_DATE(event_ts), tenant_id);   -- low → high cardinality, ≤ 3–4 expressions
SELECT SYSTEM$ESTIMATE_AUTOMATIC_CLUSTERING_COSTS('events', '(TO_DATE(event_ts), tenant_id)');
ALTER TABLE events SUSPEND RECLUSTER;   -- pause spend
ALTER TABLE events RESUME RECLUSTER;
```
Cardinality: too low (boolean) prunes little; too high (raw timestamp, UUID) makes reclustering expensive — reduce with `TO_DATE`, `DATE_TRUNC`, `SUBSTRING`, or bucketing. Automatic Clustering is serverless at a 2× multiplier (Classic); **Optima Clustering** bills 0.007 credits per uncompressed GB (see `AUTOMATIC_CLUSTERING_HISTORY.version`). A one-off alternative for append-only tables: rebuild once with `INSERT OVERWRITE … SELECT … ORDER BY key` and rely on load order thereafter.

Multi-tenant customer reporting (SaaS-style): clustering by `(tenant_id, date)` makes per-tenant queries prune well, but large tenants still scan many partitions and small tenants share partitions. Point lookups per tenant/object id are better served by search optimization; very high QPS per-tenant reads are cheaper outside Snowflake.

## Search Optimization Service (SOS)

Enterprise+. Builds a persistent search access path (shown as IndexScan) so selective lookups skip partitions that min/max can't.
```sql
ALTER TABLE events ADD SEARCH OPTIMIZATION ON EQUALITY(user_id, order_id), SUBSTRING(url), FULL_TEXT(message);
-- also GEO(col) for GEOGRAPHY; EQUALITY on VARIANT paths e.g. EQUALITY(payload:customer.id)
DESCRIBE SEARCH OPTIMIZATION ON events;
SELECT SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS('db.sch.events', 'EQUALITY(user_id)');
ALTER TABLE events DROP SEARCH OPTIMIZATION ON SUBSTRING(url);
```
Helps: equality/IN on high-cardinality columns returning few rows, LIKE/ILIKE/RLIKE substrings, `SEARCH()`/`SEARCH_IP()`, ARRAY_CONTAINS/ARRAYS_OVERLAP on semi-structured, geospatial predicates. Doesn't help: queries returning large fractions of the table, analytic scans, low-cardinality filters. Costs: extra storage plus serverless build/maintenance at 2× (+1× cloud services); high-churn tables pay continuously. Always enable `ON` specific columns rather than the whole table.

## Query Acceleration Service (QAS)

Enterprise+. Offloads parts of eligible queries (large scans with selective filters or aggregation; large INSERT/CTAS/COPY) to serverless compute so an outlier doesn't force a bigger warehouse for everyone.
```sql
ALTER WAREHOUSE bi_wh SET ENABLE_QUERY_ACCELERATION = TRUE QUERY_ACCELERATION_MAX_SCALE_FACTOR = 4;
SELECT PARSE_JSON(SYSTEM$ESTIMATE_QUERY_ACCELERATION('<query_id>'));
```
Scale factor caps QAS compute as a multiple of the warehouse size; default 8 (2 for Gen2 or multi-cluster warehouses), 0 = unbounded. Billed per second at multiplier 1; per-query QAS credits are in `QUERY_ATTRIBUTION_HISTORY.credits_used_query_acceleration`, totals in `QUERY_ACCELERATION_HISTORY`. Ineligible: not enough partitions, unselective filters, very high-cardinality GROUP BY, LIMIT clauses, non-deterministic functions (SEQ, RANDOM).

## Warehouse sizing procedure

1. Separate workloads first (ELT vs BI vs ad-hoc vs customer-facing); you can't size a mixed warehouse.
2. For a batch job, run it at size N and N+1 with the result cache off. If time halves, cost is flat — take the faster one. If time drops < ~30%, stay small.
3. Size up only for remote spill or a too-long single query. Add clusters (multi-cluster, `STANDARD` policy) only for `queued_overload_time`.
4. Gen2 vs Gen1: run the same benchmark; Gen2 costs 1.35× (AWS/GCP) / 1.25× (Azure) per hour, so it must be > ~26% / 20% faster. DML-heavy (MERGE/UPDATE/DELETE) and scan-heavy workloads gain most.
5. Snowpark-optimized warehouses (`RESOURCE_CONSTRAINT = MEMORY_16X` etc.) only for memory-heavy UDFs/ML; same 1× rate at MEMORY_1X, 1.5× at MEMORY_16X (M and up).
6. Consider an **adaptive warehouse** where workloads are too mixed to tune and per-query billing is acceptable.
7. Re-check monthly with the spill/queue query in cost-sql.md section 4.

## SQL habits that keep scans small

- Select only needed columns (columnar storage; `SELECT *` on wide VARIANT-heavy tables reads everything).
- Filter on raw columns compared to constants; push date filters into the scan; avoid `WHERE TO_CHAR(ts,'YYYY-MM') = …`.
- `UNION ALL` unless de-duplication is truly needed; drop ORDER BY in subqueries and CTEs.
- Aggregate or filter before joining large tables; `QUALIFY` for top-N per group instead of self-joins.
- Flatten frequently-queried VARIANT paths into typed columns at load; mixed types in a VARIANT path block sub-columnarisation.
- Keep repeated dashboard SQL byte-identical so the result cache hits.

Sources: https://docs.snowflake.com/en/user-guide/ui-snowsight-activity · https://docs.snowflake.com/en/sql-reference/functions/get_query_operator_stats · https://docs.snowflake.com/en/sql-reference/account-usage/query_insights · https://docs.snowflake.com/en/user-guide/tables-clustering-micropartitions · https://docs.snowflake.com/en/user-guide/tables-clustering-keys · https://docs.snowflake.com/en/user-guide/search-optimization-service · https://docs.snowflake.com/en/user-guide/search-optimization/enabling · https://docs.snowflake.com/en/user-guide/query-acceleration-service · https://docs.snowflake.com/en/user-guide/warehouses-gen2 · https://docs.snowflake.com/en/user-guide/snowflake-optima · Service Consumption Table https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf
