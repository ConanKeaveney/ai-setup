# Snowflake concepts — plain-English glossary, use cases, and when not to use it

State as of October 2026. Short definitions only; the cost and performance detail lives in SKILL.md and the other reference files (cost SQL, performance, ingestion, Iceberg interop). Edition requirements are noted where they commonly bite.

## Architecture and storage

- **Three-layer architecture** — Storage (compressed columnar files in Snowflake-managed S3, Azure Blob or GCS, billed per TB-month), compute (virtual warehouses plus serverless features, usually most of the bill) and cloud services are separate and billed separately. Many warehouses can read the same data at once without copying it, so a heavy ELT job doesn't slow the BI dashboards if they run on different warehouses.
- **Cloud services layer** — The "brain": parsing, optimising, metadata, security, the result cache, transactions. It is only billed for the part above 10% of the day's warehouse credits, so it's free for most accounts until something hammers metadata (thousands of tiny queries, very short dynamic-table lags).
- **Micro-partition** — The unit of storage: an immutable file of 50–500 MB uncompressed data, stored by column, with min/max and distinct-count metadata per column. Updating one row rewrites the whole micro-partition it lives in.
- **Pruning** — Skipping micro-partitions whose min/max range can't match the filter. It is the single biggest performance lever: a query that scans 20 of 50,000 partitions is fast and cheap whatever the warehouse size. Wrapping the filter column in a function (`WHERE TO_CHAR(ts, 'YYYY-MM') = …`) can defeat it. Data stays in load order, so a table loaded in time order already prunes well on time filters for free.
- **Clustering key** — A declared column or expression (e.g. `CLUSTER BY (TO_DATE(event_ts), tenant_id)`) that tells Snowflake how to keep the table physically ordered. Worth it only on multi-TB tables with a stable, selective filter pattern and far more reads than writes.
- **Automatic Clustering** — The serverless background service that re-sorts micro-partitions to honour a clustering key as new data arrives. Billed as serverless compute (2× multiplier in the classic version); on a high-churn table it can cost more than it saves.
- **Clustering depth** — The average number of micro-partitions whose value ranges overlap at a point for a given column set. 1 is perfect (no overlap), higher is worse, an empty table is 0. Check it with `SYSTEM$CLUSTERING_INFORMATION`.
- **Semi-structured data (VARIANT)** — A column type that holds JSON, Avro, Parquet or XML values; Snowflake columnarises common paths internally so `payload:customer.id` can still prune. Mixed types in one path block that.

## Compute: warehouses, credits and caches

- **Virtual warehouse** — A named compute cluster that runs queries and DML. It bills per second while running with a 60-second minimum on every start or resume, whether or not it is doing useful work.
- **Credit** — Snowflake's unit of compute. Dollars per credit depend on edition, cloud and region (on demand in AWS US East: $2 Standard, $3 Enterprise, $4 Business Critical).
- **Warehouse size** — XS to 6XL; each step doubles both credits per hour (XS = 1, S = 2, M = 4 …) and roughly the resources. A query that scales linearly costs the same on a bigger size and finishes faster; one that doesn't just costs double.
- **Auto-suspend / auto-resume** — The warehouse stops after N idle seconds and wakes on the next query. Short for batch (60 s), longer for BI (10 min or more) to keep the local cache warm.
- **Multi-cluster warehouse** (Enterprise+) — One warehouse that adds identical clusters when queries queue and removes them when the queue drains. Fixes concurrency, not single-query slowness. Scaling policy STANDARD favours latency, ECONOMY favours cost.
- **Gen2 warehouse** — Newer hardware and software for standard warehouses, faster on scans and DML, billed at 1.35× Gen1 on AWS and GCP and 1.25× on Azure. Only cheaper if the workload finishes more than about 26% faster on AWS.
- **Adaptive warehouse** (Enterprise+) — A warehouse where you set a performance ceiling and a throughput multiplier instead of size, cluster count and auto-suspend; Snowflake sizes each query and bills per query.
- **Snowpark-optimized warehouse** — A warehouse with much more memory per node, for memory-hungry Python UDFs and in-warehouse ML. Costs more per hour at the larger memory settings.
- **Interactive warehouse and interactive table** (GA December 2025) — A warehouse type and table type built for sub-second, high-concurrency queries such as live dashboards and data APIs. Queries are capped at 5 seconds, the minimum billable period is an hour and the minimum auto-suspend is 24 hours, so in practice it is an always-on cost.
- **Serverless compute** — Compute Snowflake manages for features like Snowpipe, Automatic Clustering, search optimization, MV maintenance and serverless tasks. Billed as compute-hours times a feature multiplier, and invisible to resource monitors.
- **Result cache** — Stores each query's result for 24 hours (extended on reuse up to 31 days). An identical query text against unchanged data, by a role with the same access, returns instantly with no warehouse running, so it is free.
- **Warehouse (local disk) cache** — Table data the warehouse has already read, kept on its SSDs. Lost when the warehouse suspends, which is why BI warehouses use longer auto-suspend.
- **Metadata cache** — Partition statistics in cloud services; `COUNT(*)` or `MAX(col)` on a table can be answered from it with no scan.
- **Queuing** — Queries waiting because the warehouse is full (`queued_overload_time`). Add clusters for this; a bigger size won't help much.
- **Spilling** — A query ran out of memory and wrote intermediate data to local disk (slower) or remote storage (much slower). Size up or reduce rows earlier.

## Databases, schemas and table types

- **Account / organization** — An account is one Snowflake deployment in one cloud region; an organization groups a company's accounts for billing, replication and sharing.
- **Database and schema** — Logical containers: `database.schema.object`. They hold no data themselves and cost nothing beyond the objects inside. A **managed-access schema** centralises grant decisions with the schema owner rather than each object owner.
- **Permanent table** — The default. Time Travel of 1 day (up to 90 on Enterprise+) plus 7 days of Fail-safe.
- **Transient table** — Persists until dropped, but has at most 1 day of Time Travel and no Fail-safe. Use for staging and other data you can rebuild, to avoid paying for Fail-safe storage. Transient databases and schemas make everything inside them transient.
- **Temporary table** — Lives only for the session that created it, invisible to other sessions, no Fail-safe. Good for scratch work inside a procedure.
- **External table** — A read-only table over files sitting in a stage (e.g. Parquet in S3); Snowflake keeps only file-level metadata. Slower than native tables; Snowflake now points people to Iceberg tables instead.
- **Iceberg table** — A table stored as Apache Iceberg metadata plus Parquet files in your own cloud storage (via an external volume). Snowflake-managed Iceberg tables get full DML and automatic maintenance; externally managed ones (Glue, Unity, Polaris) are owned by another catalog and maintained by you.
- **Hybrid table** — A row-store table with an enforced primary key, row-level locking and indexes, for fast single-row reads and writes (app state, lightweight transactional apps, serving precomputed aggregates). AWS and Azure commercial regions only; larger storage footprint than standard tables.
- **Dynamic table** — A table defined by a SELECT that Snowflake keeps refreshed to within a target lag (60 seconds or more), incrementally where it can. Replaces most hand-written stream, task and MERGE pipelines for joins and aggregates.
- **Sequence / constraints** — Sequences give unique numbers (not gap-free). Primary, foreign and unique keys on standard tables are informational only and not enforced (only NOT NULL is); hybrid tables are the exception.

## Views

- **View** — A saved query. No storage; runs every time it's queried.
- **Materialized view** (Enterprise+) — A view whose result is stored and kept current by a serverless background process (2× multiplier). Single table only, no joins, limited aggregates; the optimizer can automatically rewrite queries on the base table to use it.
- **Secure view** — A view whose definition is hidden from non-owners and which skips optimizations that could leak underlying data. Required for views in a data share; can be slower, so don't use it for mere convenience.
- **Semantic view** — Business definitions (metrics, dimensions, relationships) stored as a schema object so BI tools and AI features like Cortex Analyst interpret the data the same way.

## Loading and pipelines

- **Stage** — A named location for files: internal (Snowflake storage, including per-user and per-table stages) or external (your S3/GCS/Azure bucket, usually through a storage integration, an account object that lets Snowflake assume an IAM role so no keys are stored).
- **File format** — A named description of how to parse files (CSV delimiter, JSON options, Parquet). Reused across stages and COPY statements.
- **COPY INTO** — The bulk load (or unload) command, run on a warehouse. It remembers loaded files for 64 days and skips them on re-run, so re-running a load is safe. Aim for files of 100–250 MB compressed.
- **Snowpipe** — Serverless auto-ingest: an S3/GCS/Azure event notification triggers a COPY of each new file, typically within about a minute. Billed per GB ingested, no warehouse needed.
- **Snowpipe Streaming** — Row-level ingestion through an SDK or REST API, no files involved; latency as low as about 5 seconds. Used behind the Kafka connector and for CDC.
- **Openflow** — Snowflake's managed data-integration service built on Apache NiFi, with connectors for databases, SaaS apps, queues and unstructured sources.
- **Stream** — A change-tracking cursor on a table: reading it inside a committed DML statement returns rows changed since the last read (inserts, updates as delete+insert pairs, deletes) and advances the cursor. Goes stale if not consumed within the retention window.
- **Task** — A scheduled or triggered unit of SQL or a procedure call, on a warehouse or serverless. Tasks chain into graphs (DAGs); triggered tasks run when a stream has data. Created suspended — they do nothing until resumed.

## Data protection, sharing and replication

- **Time Travel** — Query, clone or restore data as it was at an earlier point, up to the retention period (1 day by default, up to 90 on Enterprise+). Example: `SELECT * FROM orders AT(OFFSET => -3600)` or `UNDROP TABLE orders`.
- **Fail-safe** — A further 7 days after Time Travel ends during which only Snowflake support can recover permanent-table data. Not user-accessible, but still billed as storage.
- **Zero-copy cloning** — `CREATE TABLE dev_orders CLONE orders` makes an instant copy that shares the original's storage; new storage is only used for data that later changes. Works for databases and schemas too, and combines with Time Travel (`CLONE … AT(…)`). Grants aren't copied unless you say `COPY GRANTS`.
- **Secure Data Sharing** — Giving another Snowflake account read-only live access to your tables and secure views without copying data. The provider pays storage; the consumer pays for the warehouse that queries it.
- **Share / listing** — A share is the object that bundles what's shared and with whom. A listing wraps a share with a description and terms so it can be offered privately or publicly, including across regions and clouds (Cross-Cloud Auto-Fulfillment replicates it for you).
- **Reader account** — A Snowflake account the provider creates and pays for, so a partner without Snowflake can query shared data.
- **Snowflake Marketplace** — The public catalogue of listings: third-party datasets (weather, financial, demographic), apps and models you can get into your account in minutes.
- **Data clean room** — A sharing setup where two parties can run approved queries over combined data (e.g. ad-audience overlap) without either seeing the other's raw rows.
- **Replication and failover** — Copying databases and shares to an account in another region or cloud is available on every edition; replicating account objects (users, roles, warehouses) and failing over or back with failover groups requires Business Critical or higher.

## Security and governance

- **RBAC (role-based access control)** — Privileges are granted to roles and roles to users; a user acts through the active role (plus any secondary roles). Every object also has an owner role that can grant access to it.
- **Role hierarchy** — Granting role A to role B gives B all of A's privileges. Grant custom roles up to SYSADMIN so administrators can still manage the objects they create. `GRANT … ON FUTURE TABLES IN SCHEMA` covers tables not yet created.
- **System roles** — ACCOUNTADMIN (top of the account, use rarely, with MFA), SECURITYADMIN (manages grants, users and roles), USERADMIN (creates users and roles), SYSADMIN (owns warehouses and databases), PUBLIC (everyone has it), and the organization-level GLOBALORGADMIN (replacing ORGADMIN, which is being phased out).
- **Database role** — A role that lives inside one database, used to bundle access to that database's objects; it can be granted to account roles or to shares.
- **Masking policy** (Enterprise+) — A rule attached to a column that decides at query time what each role sees, e.g. analysts see `***@example.com`, the support role sees the full email. Policies can be attached directly or via tags.
- **Row access policy** (Enterprise+) — A rule attached to a table that filters which rows each role or user can see, e.g. each tenant's users see only their tenant's rows. The usual tool for multi-tenant isolation in a shared table.
- **Object tag** — A key-value label on any object (e.g. `pii = 'email'`, `cost_center = 'marketing'`), used for discovery, cost attribution and tag-based masking. Tags are on every edition; tag-based masking needs Enterprise because masking does.
- **Data classification** (Enterprise+) — Automatic detection of sensitive columns (names, emails, national IDs) that can then be tagged and masked.
- **Access history** (Enterprise+) — An ACCOUNT_USAGE view recording which user and query read or wrote which columns; the basis for audits and lineage.
- **Horizon Catalog** — Snowflake's umbrella for governance and discovery: access control, policies, classification, lineage, data quality monitoring, the Trust Center, and an Iceberg REST endpoint so external engines like Spark can read Snowflake-managed Iceberg tables under the same policies.

## Developer features and AI

- **Snowpark** — Python, Java and Scala DataFrame APIs that compile to SQL and run on a warehouse, so code runs next to the data instead of pulling it out. Snowpark Connect lets existing PySpark code run on Snowflake compute.
- **UDF / UDTF** — User-defined scalar or table functions in SQL, Python, Java, Scala or JavaScript, called from SQL like built-ins. Python UDFs can use packages from the built-in Anaconda channel.
- **Stored procedure** — Procedural code (Snowflake Scripting SQL, Python, Java, Scala, JavaScript) that can run multiple statements, loops and DDL; called with `CALL`. Use for admin automation and logic that can't be one SELECT.
- **Snowpark Container Services** — Run your own container images (APIs, ML training and serving, including on GPUs) on Snowflake-managed compute pools inside the account.
- **Native App Framework and Streamlit in Snowflake** — Package code and data as an app other accounts install from the Marketplace; Streamlit apps run inside Snowflake for internal data tools.
- **Cortex AI functions** — SQL functions that call large language models on your data, e.g. `AI_COMPLETE`, `AI_CLASSIFY`, `AI_EXTRACT`, `AI_SENTIMENT`, `AI_SUMMARIZE_AGG`, `AI_EMBED`, `AI_PARSE_DOCUMENT`. Billed per token (or per page for documents) on top of the warehouse; Snowflake recommends a warehouse no larger than Medium.
- **Cortex Search, Cortex Analyst, Cortex Agents** — Managed hybrid (vector plus keyword) search over text for retrieval-augmented generation; natural-language-to-SQL over semantic views; and agents that orchestrate both plus tools.
- **CoCo and CoWork** — Snowflake's 2026 names for its AI coding assistant (Cortex Code) and its business-user conversational agent (CoWork, formerly Snowflake Intelligence).
- **Snowflake Postgres** (GA February 2026) — Managed PostgreSQL instances run by Snowflake on dedicated VMs, for transactional app workloads, with the tables visible to Snowflake as read-only Iceberg tables. Selected AWS and Azure regions.

## Performance and cost controls

- **Query Profile** — The per-query execution graph in Snowsight showing operators, time, rows, pruning and spill; the first place to look for a slow query.
- **Search optimization** (Enterprise+) — A maintained index-like structure that makes needle-in-haystack lookups fast (equality on high-cardinality columns, substring, full-text, geospatial). Costs extra storage plus serverless maintenance at 2×; enable it on specific columns, not whole tables.
- **Query Acceleration Service** (Enterprise+) — Lets a warehouse borrow extra serverless compute for the large-scan part of an outlier query, so one ugly query doesn't force a bigger warehouse for everyone.
- **Resource monitor** — A credit quota on one or more warehouses that can notify or suspend them at thresholds. Doesn't see serverless features; use **Budgets** for those and for per-tag spend. Pair it with `STATEMENT_TIMEOUT_IN_SECONDS` (default 2 days) and a `QUERY_TAG` per app or tenant for attribution.
- **ACCOUNT_USAGE** — Views in the shared `SNOWFLAKE` database covering the whole account: 1 year of history, includes dropped objects, but 45 minutes to 3 hours behind (some up to 8 hours). Use for cost analysis and audits.
- **INFORMATION_SCHEMA** — Per-database views and table functions with no lag but short retention (7 days to 6 months) and no dropped objects. Use for "what's happening right now".
- **Editions** — Standard (core platform, 1-day Time Travel), Enterprise (90-day Time Travel, multi-cluster, materialized views, search optimization, query acceleration, masking and row access policies), Business Critical (HIPAA and PCI support, private connectivity, failover and failback), Virtual Private Snowflake (fully isolated deployment). Edition also sets the price per credit.

## Use cases

What Snowflake is genuinely good at, with a concrete example of each:

| Workload | Example |
|---|---|
| Central analytics warehouse with ELT | Fivetran or Openflow lands Salesforce, Stripe and Postgres data in raw schemas; dbt or dynamic tables build cleaned and modelled marts; analysts query with SQL. |
| Internal BI and dashboards | Tableau or Looker dashboards for 300 employees on a dedicated multi-cluster warehouse with 10-minute auto-suspend; repeated tiles hit the result cache for free. |
| Mixed workloads that must not collide | Nightly ELT on a Large warehouse, finance's ad-hoc queries on a Small one, data science on a Snowpark-optimized one, all reading the same tables with no copies. |
| Semi-structured event analytics | Load raw JSON clickstream into a VARIANT column with Snowpipe, then query `payload:page.url` directly and flatten hot fields later. |
| Sharing data with partners or customers | A retailer shares daily sell-through numbers with 40 suppliers via secure views and a private listing; each supplier sees only its rows through a row access policy, and pays its own compute. |
| Buying external data | Join your store table to a Marketplace weather dataset to model demand without building an ingest pipeline. |
| Near-real-time operational reporting (minutes) | Snowpipe Streaming from Kafka into a table, dynamic tables with a 5-minute lag building an orders-by-region mart, an internal ops dashboard on top. |
| Governed self-service with PII | One customer table, masking policies by role on email and phone, classification and tags to find new PII columns, access history for auditors. |
| Querying a lakehouse without copying | Spark writes Iceberg tables to S3 with Glue as the catalog; a catalog-linked database lets analysts query them from Snowflake. |
| Dev and test environments | Clone the production database every morning in seconds for testing a migration, then drop it; you only pay for what the test changes. |
| SQL-native AI over text | `AI_CLASSIFY` support tickets into categories and `AI_SENTIMENT` on reviews in a nightly job, without exporting data to an ML service. |
| Feature engineering for ML | Build training features with SQL or Snowpark DataFrames where the data lives, then train small-to-medium models in a Snowpark-optimized warehouse or Container Services. |

## When to use / when not to use

| Situation | Verdict | Better alternative and why |
|---|---|---|
| Analytics over many sources, SQL-first team, variable or bursty load | **Use** | Pay only while warehouses run; separation of storage and compute means no capacity planning. |
| Internal BI with tens to hundreds of users | **Use** | Multi-cluster warehouse plus result cache handles it; isolate it from ELT. |
| Sharing live data with other organisations | **Use** | Secure Data Sharing has no copies or pipelines and the consumer pays compute; few competitors match it. |
| Near-real-time analytics where minutes of lag are fine | **Use** | Snowpipe Streaming plus dynamic tables. |
| Customer-facing, high-QPS, low-latency queries (e.g. a per-tenant analytics page in a SaaS product hit thousands of times a minute) | **Usually avoid on standard warehouses** | Per-second warehouse billing sized for peak concurrency runs all day whether or not tenants are querying, and cost grows with traffic. Precompute in Snowflake, then serve from **ClickHouse, Apache Druid or Pinot** (built for sub-second, high-concurrency aggregation on a fixed-cost cluster), **OpenSearch** (when the access pattern is search plus aggregations), or a key-value or Postgres serving table for precomputed results. Snowflake's own answers are interactive warehouses (sub-second, but a 24-hour minimum auto-suspend makes them always-on, and queries are capped at 5 seconds) and hybrid tables for point reads; price them against the alternatives with real QPS. |
| OLTP: an application's system of record with many small concurrent writes and transactions | **Avoid** | Micro-partitions are immutable, so single-row updates rewrite whole partitions and locking is coarse. Use **Postgres** (or Aurora, or Snowflake Postgres if you want it inside the Snowflake estate); replicate changes into Snowflake for analytics. Hybrid tables cover only lightweight transactional cases. |
| Large-scale ML training, deep learning, heavy work on images, audio or video | **Usually avoid** | **Databricks or Spark** (on EMR or Kubernetes) have the mature distributed-training, GPU and notebook ecosystem and work directly on files. Snowflake can run GPU containers via Container Services, but it's younger and you pay Snowflake rates for the compute. |
| Very large raw or rarely queried data (petabytes of logs, landing-zone history) | **Don't load it** | Keep it as **Iceberg on S3** (or another object store) at object-storage prices, maintained by Spark; query the slices you need from Snowflake as external Iceberg tables. Loading it all into native tables pays for storage you rarely read. |
| Full-text relevance search, autocomplete, fuzzy matching | **Avoid** | **OpenSearch or Elasticsearch** do ranking and analyzers; Snowflake's search optimization and Cortex Search are for filtering and retrieval-augmented generation, not product search. |
| Sub-second event processing (fraud scoring on each event, alerting in milliseconds) | **Avoid** | **Flink or Kafka Streams** process each event as it arrives; Snowflake's best case is seconds to minutes. |
| Small data (under about 100 GB) and a tiny team | **Often overkill** | **Postgres or DuckDB** are cheaper and simpler; Snowflake earns its keep when data, users or sources grow. |
| Must run on-premises or in a fully air-gapped environment | **Not possible** | Snowflake is cloud-only SaaS. Consider self-hosted ClickHouse, Trino plus Iceberg, or a commercial on-prem warehouse. |
| Spark-heavy estate where most tables are already Iceberg or Delta | **Use for SQL and BI, not as the system of record** | Keep the lakehouse as source of truth with one catalog owner; give Snowflake read access via a catalog-linked database, rather than two copies of every table. |

## Sources

Official docs (fetched October 2026):
- Editions: https://docs.snowflake.com/en/user-guide/intro-editions
- Micro-partitions and clustering depth: https://docs.snowflake.com/en/user-guide/tables-clustering-micropartitions
- Temporary and transient tables: https://docs.snowflake.com/en/user-guide/tables-temp-transient
- Hybrid tables: https://docs.snowflake.com/en/user-guide/tables-hybrid
- External tables: https://docs.snowflake.com/en/user-guide/tables-external-intro
- Interactive tables and warehouses: https://docs.snowflake.com/en/user-guide/interactive · GA note: https://docs.snowflake.com/en/release-notes/2025/other/2025-12-11-interactive-tables-ga
- Secure views: https://docs.snowflake.com/en/user-guide/views-secure
- Zero-copy cloning: https://docs.snowflake.com/en/user-guide/object-clone
- Secure Data Sharing: https://docs.snowflake.com/en/user-guide/data-sharing-intro
- Replication and failover: https://docs.snowflake.com/en/user-guide/account-replication-intro
- Access control and system roles: https://docs.snowflake.com/en/user-guide/security-access-control-overview
- Horizon Catalog: https://docs.snowflake.com/en/user-guide/snowflake-horizon
- ACCOUNT_USAGE vs INFORMATION_SCHEMA: https://docs.snowflake.com/en/sql-reference/account-usage
- Cortex AI functions: https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql · cost: https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-cost · AI features overview: https://docs.snowflake.com/en/guides-overview-ai-features
- Snowpark Container Services: https://docs.snowflake.com/en/developer-guide/snowpark-container-services/overview
- Snowflake Postgres GA: https://docs.snowflake.com/en/release-notes/2026/other/2026-02-24-snowflake-postgres-ga
- Plus the sources already listed in SKILL.md for warehouses, Gen2, adaptive warehouses, caches, MVs, dynamic tables, streams, tasks, Snowpipe, Iceberg, Time Travel and Snowpark.

Other:
- Openflow: https://www.snowflake.com/en/product/features/openflow/
- CoWork rename of Snowflake Intelligence (June 2026): https://siliconangle.com/2026/06/03/snowflake-cowork-powers-real-world-agentic-ai-snowflakesummit/
- The alternatives in the "when not to use" table (ClickHouse, Druid, Pinot, OpenSearch, Postgres, DuckDB, Flink, Databricks) reflect general engineering judgement about each tool's design, not Snowflake documentation.
