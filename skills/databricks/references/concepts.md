# Databricks concepts — plain-English glossary

What each Databricks term means, why it matters, and when the platform is (and is not) the right
tool. State as of October 2026. Old names are given in brackets because 2025–2026 brought a wave
of renames; the main rename table lives in SKILL.md. Release status (Beta, Public Preview, GA)
changes monthly, so check the docs before promising a feature in a design.

## Contents
1. Platform basics
2. Compute and cost
3. Unity Catalog (governance)
4. Tables: Delta Lake and Iceberg
5. Ingestion
6. Pipelines and jobs
7. Machine learning and AI
8. SQL, BI and AI assistants
9. Apps, operational data and operations
10. Use cases
11. When to use / when not to use
12. Databricks vs Snowflake vs self-managed Spark (EMR)
13. Sources

---

## 1. Platform basics

**Lakehouse.** The idea behind Databricks: keep one copy of data in open file formats on cheap
object storage (S3), and run warehouse-style SQL, data engineering and ML on that same copy.
It matters because it removes the "copy from the lake into a warehouse" step and the drift that
comes with it.

**Account.** The top level you buy: it owns identities (users, groups, service principals),
billing, workspaces and Unity Catalog metastores. One company usually has one account per cloud.

**Workspace.** The environment people log into to run notebooks, jobs, pipelines and SQL. An
account has many workspaces (typically dev / staging / prod, or per business unit); several
workspaces in one region can share one metastore, so they see the same governed data.

**Control plane.** The part Databricks runs in its own cloud account: the web UI, the job
scheduler, Unity Catalog's metadata service, the APIs. Your data does not live here; it holds
notebooks, job definitions and metadata.

**Compute plane.** Where your data is actually processed. **Classic** compute is EC2 machines
launched in *your* AWS account and VPC; **serverless** compute runs in Databricks' AWS account,
isolated per customer, and reads your S3 data. The choice drives cost model, start-up time and
how much you can tune.

**Workspace storage bucket / default storage.** Classic workspaces need an S3 bucket for system
data, the workspace catalog and legacy DBFS. Newer serverless workspaces can instead use
Databricks-managed *default storage*; some features (credential vending to outside engines,
streaming Feature Views) need your own bucket, so platform teams usually bring their own S3.

**Databricks Runtime (DBR).** The versioned software image on classic clusters: Apache Spark plus
Delta Lake, Photon and Databricks extras. LTS versions (for example 17.3 LTS, 18 LTS) are the
ones to pin for production; `-ml` runtimes add ML libraries.

**Free Edition (formerly Community Edition).** A no-cost, serverless-only, quota-limited
Databricks for learning and experiments. Good for trying things, not for company workloads.

## 2. Compute and cost

**DBU (Databricks Unit).** Databricks' billing unit: "a normalised unit of processing power".
Each compute type burns DBUs per hour at its own rate and each SKU has its own $/DBU. On classic
compute you pay DBUs *plus* the EC2 bill; serverless DBU prices include the machines. Example:
the same job costs more DBUs on an all-purpose cluster than on jobs compute.

**All-purpose compute (all-purpose cluster).** A classic cluster for interactive work, shared by
people and notebooks. Highest DBU rate; never schedule production jobs on it.

**Jobs compute (job cluster).** A classic cluster created for one job run and torn down after.
Cheaper DBU rate than all-purpose; use it when a job needs custom Spark settings, init scripts,
JARs, GPUs or specific instance types.

**Serverless compute.** Databricks-managed compute for notebooks, jobs and pipelines that starts
in seconds and scales itself. You give up most Spark config knobs, RDDs, init scripts and
instance choice. Serverless jobs come in "standard" (cheaper) and "performance-optimized"
(faster start) modes.

**Access mode: standard / dedicated (formerly shared / single user).** How a classic cluster
enforces Unity Catalog. Standard lets many users share a cluster safely but blocks some APIs
(RDDs); dedicated gives one user or group the full API.

**Compute policy (cluster policy).** Admin rules on what clusters people may create: maximum
size, forced auto-termination, allowed instance types, required cost tags. The main cost
guardrail on classic compute.

**Serverless usage policy (formerly budget policy) and budgets.** A usage policy attaches tags
to serverless usage by a user, job or pipeline, the only way to charge serverless spend back to
a team. Budgets are account-level spend thresholds on tags or workspaces; they alert but do not
stop compute.

**Photon.** Databricks' vectorised C++ query engine that replaces parts of Spark's execution.
Big speed-ups for SQL and DataFrame scans, joins, aggregations and Delta writes; little or none
for Python UDFs, RDD code, stateful streaming or queries that already finish in under two
seconds. Always on for serverless and SQL warehouses; on classic it is a checkbox in the UI or
`runtime_engine: PHOTON` in the API, and Photon instances burn DBUs at a different (higher) rate,
so judge it by cost per run, not runtime.

## 3. Unity Catalog (governance)

**Unity Catalog (UC).** The single governance layer for everything in Databricks: tables,
views, files, functions, models, features. It handles permissions, audit, lineage, discovery
and data sharing across all workspaces. Nearly every newer feature requires it. Under the hood
there is one *metastore* per region per account, attached to workspaces; most people never touch
it directly.

**Catalog.** The first level of the three-part name `catalog.schema.table`. Usually one per
environment or domain, e.g. `prod_sales`, `dev_ml`. Catalogs can be bound to specific
workspaces so a dev workspace cannot see prod.

**Schema (database).** The second level; groups related tables, views, volumes and functions,
e.g. `prod_ml.features`.

**Managed table.** A table whose files Unity Catalog owns and places in your S3 bucket. Gets
automatic maintenance (predictive optimization), `UNDROP` for 7 days, and the newest features.
The default choice.

**External table.** A table over an S3 path that something else owns; UC governs access but
dropping the table leaves the files. Use only when another system must control the location.

**View / materialized view / metric view.** A view is a saved query; a materialized view stores
the result and refreshes it; a metric view defines business measures (revenue, active users)
once so dashboards and Genie compute them the same way.

**Volume.** Governed storage for non-tabular files (CSVs landing from a vendor, images, model
artefacts, checkpoints) at paths like `/Volumes/raw/crm/landing/`. Replaces DBFS mounts.

**Storage credential and external location.** A storage credential wraps an AWS IAM role; an
external location pairs it with an S3 prefix. Together they are how UC reaches your buckets,
instead of instance profiles or access keys.

**Privileges / grants.** SQL `GRANT` statements on catalogs, schemas and objects, inherited
downwards. A reader needs `USE CATALOG`, `USE SCHEMA` and `SELECT`. Grant to groups, not people,
and run production jobs as a *service principal* (a non-human identity) so they do not break
when someone leaves.

**Row filters, column masks and ABAC.** Row filters hide rows (EU analysts see EU rows only);
column masks redact values (hash an email). ABAC (attribute-based access control) applies such
rules automatically to every column carrying a governed tag like `pii`, instead of per table.
Governed tags are controlled labels (owner, PII, domain) that also drive search and cost
reports; data classification can detect sensitive columns and suggest them.

**Lineage.** Automatic record of which tables and columns feed which, captured from every UC
query. Answers "what breaks if I drop this column?" Queryable in system tables.

**Lakehouse Federation (foreign catalog).** Query data where it already lives (Glue, Hive
metastore, Postgres, MySQL, Snowflake, Redshift) through a *foreign catalog*, with UC
permissions, without copying it. A common first step in a migration.

**OpenSharing (formerly Delta Sharing).** Open protocol for sharing live tables, views, volumes
and models with other organisations, whether or not they use Databricks, without copying data.
Also powers Databricks Marketplace and **Clean Rooms**, where two companies run approved
analysis on each other's data without seeing the raw rows (e.g. a retailer and an advertiser
measuring campaign overlap).

## 4. Tables: Delta Lake and Iceberg

**Delta Lake.** The default table format: Parquet files plus a transaction log (`_delta_log`)
that gives ACID transactions, versioning and safe concurrent writes on S3. Open source, but the
newest features arrive in Databricks first.

**Apache Iceberg (managed Iceberg tables).** The other major open table format. Unity Catalog
can manage Iceberg tables natively (`USING ICEBERG`), and outside engines (EMR, Trino, Flink,
Snowflake) can read and write them through UC's **Iceberg REST catalog**, which hands them
short-lived S3 credentials ("credential vending") under UC permissions. Choose it when
non-Databricks engines must *write* the table.

**UniForm (now "External Iceberg Reads").** A Delta table setting that also writes Iceberg
metadata, so Iceberg readers can read a Delta table. Databricks stays the only writer.

**Time travel.** Query a table as it was at an earlier version or time
(`SELECT ... VERSION AS OF 120`), or `RESTORE` it. Lasts only as long as old files survive
VACUUM (7 days by default).

**Schema enforcement and evolution.** Writes with the wrong columns or types are rejected by
default; evolution (`mergeSchema`, Auto Loader's `addNewColumns`) adds new columns deliberately.
**Type widening** (GA 2026) lets a column grow, e.g. `INT` to `BIGINT`, without a rewrite.
The **Variant** type (GA 2026) stores semi-structured JSON in a form that stays fast to query.

**MERGE.** SQL upsert: insert new rows, update changed ones, delete removed ones in one atomic
statement. The workhorse of CDC and SCD logic outside pipelines.

**OPTIMIZE.** Compacts many small files into fewer large ones and applies clustering. Small
files are the most common cause of slow lakehouse queries.

**VACUUM.** Deletes data files no longer referenced by recent table versions, after a retention
period (7 days default). Saves storage; also ends time travel beyond that window.

**Liquid clustering.** The modern way to lay out data so queries skip irrelevant files:
`CLUSTER BY (customer_id, event_date)`, keys changeable later without rewriting, or
`CLUSTER BY AUTO` to let Databricks choose. Replaces partitioning (folders per column value) and
Z-order (co-locating values inside files), which remain only for very large tables with one
obvious filter column.

**Predictive optimization.** Databricks runs OPTIMIZE, VACUUM and statistics collection on
managed tables for you, when it judges them worthwhile. Billed as serverless; removes the need
for hand-written maintenance jobs.

**Deletion vectors.** Instead of rewriting a whole file to delete or update a few rows, Delta
marks those rows as deleted in a small side file. Makes DELETE / UPDATE / MERGE much faster, but
older external readers may not understand them.

**Change data feed (CDF).** A table-level record of row-level inserts, updates and deletes
between versions, so downstream jobs process only what changed instead of rescanning. Automatic
CDF (GA September 2026) derives it at read time for tables with **row tracking** enabled.

**Medallion architecture (bronze / silver / gold).** A naming convention for layers: bronze =
raw as landed, silver = cleaned and conformed, gold = business-ready aggregates. Not a product,
but almost every Databricks codebase is organised this way.

## 5. Ingestion

**Auto Loader.** Incrementally ingests new files as they land in S3 or a volume, remembers what
it has already loaded, handles schema changes, and scales to millions of files. In SQL it is
`STREAM read_files(...)`. Example: vendor drops hourly JSON files; Auto Loader appends only the
new ones to a bronze table. Turn on *file events* on the external location so it learns about
new files from S3 notifications instead of listing directories. For small, occasional loads,
SQL `COPY INTO` (load once, skip files already loaded) is simpler.

**Lakeflow Connect.** Managed connectors that ingest from SaaS apps (Salesforce, Workday,
ServiceNow, NetSuite, SharePoint and more) and databases (SQL Server, PostgreSQL, MySQL) into
UC tables, with incremental change capture. Database connectors use an *ingestion gateway*
that reads the source's change log; MySQL also has a gateway-less *integrated* CDC pipeline (GA
15 October 2026). Statuses vary per connector (PostgreSQL CDC still Public Preview in October
2026), so check before committing. *Query-based* connectors poll a
cursor column such as `updated_at` instead: no gateway or replication setup, but hard deletes
are missed.

**Zerobus Ingest.** Push-based ingestion: applications send events over gRPC or REST straight
into a UC Delta table, with no Kafka in between. Example: IoT devices or app servers writing
telemetry directly to bronze.

**Lakeflow Designer.** A visual, no-code canvas (with natural-language prompts) for analysts to
build data prep pipelines that compile to governed Lakeflow pipelines. GA June 2026.

## 6. Pipelines and jobs

**Lakeflow.** Umbrella brand for Databricks data engineering: Lakeflow Connect (ingest),
Lakeflow Spark Declarative Pipelines (transform), Lakeflow Jobs (orchestrate), Lakeflow
Designer (no-code).

**Lakeflow Spark Declarative Pipelines (formerly Delta Live Tables / DLT).** You declare the
tables you want and the queries that define them; Databricks works out order, incremental
processing, retries, data-quality checks and infrastructure. The open-source core is Apache
Spark Declarative Pipelines.

**Streaming table.** A pipeline table that processes each new input row exactly once and
appends. Use for ingestion and CDC targets. A *full refresh* discards its streaming state and
re-reads sources; data that has aged out of Kafka or been deleted from S3 is lost, so treat it
as destructive.

**Materialized view.** A pipeline (or SQL) table that stores a query's result and refreshes it,
incrementally where possible. Use for joins and aggregations whose inputs change.

**Expectations.** Data-quality rules on pipeline tables (`amount > 0`) that warn, drop the bad
row, or fail the update, with metrics recorded per run.

**AUTO CDC (formerly APPLY CHANGES).** Pipeline statement that turns a stream of inserts,
updates and deletes into an up-to-date table, handling out-of-order events. Supports SCD
Type 1 and 2.

**SCD Type 1 / Type 2.** Slowly changing dimensions. Type 1 overwrites a row with its latest
value; Type 2 keeps history with start and end timestamps. Example: a customer's address
history for "where did they live when they ordered?".

**Structured Streaming.** Spark's streaming engine, underneath Auto Loader and streaming tables.
Can run continuously or as "available now" batches that process the backlog and stop.

**Lakeflow Jobs (formerly Databricks Workflows).** The built-in orchestrator: a DAG of tasks
(notebooks, Python, SQL, pipelines, dbt, JARs, other jobs) with schedules, file-arrival and
table-update triggers, retries, and "repair run" to rerun only failed tasks. Often replaces
Airflow for Databricks-only flows.

**Declarative Automation Bundles (formerly Databricks Asset Bundles, still "DABs").** YAML plus
code in Git that defines jobs, pipelines, dashboards, models and more, deployed per environment
with `databricks bundle deploy`. The way to get infrastructure-as-code and CI/CD for workspace
resources; the Terraform provider remains the usual tool for account-level setup (workspaces,
metastores, networking).

## 7. Machine learning and AI

**MLflow.** Open-source ML lifecycle tool, hosted and managed in Databricks: experiments and
runs (parameters, metrics, artefacts), model packaging, evaluation, and tracing for GenAI apps.

**Models in Unity Catalog (formerly Workspace Model Registry).** Registered models live in UC as
`catalog.schema.model` with versions and aliases (`@prod`, `@challenger`) instead of the old
"Staging/Production" stages. Gets UC permissions and lineage.

**Feature Engineering in Unity Catalog (formerly Workspace Feature Store).** Databricks' feature
store: any UC Delta table with a primary key is a *feature table*. Builds point-in-time-correct
training sets and records which features a model used, so serving can look them up
automatically.

**Point-in-time join.** Joining each training label only to feature values known *before* that
label's timestamp, so the model never sees the future (label leakage). Example: a fraud label at
10:00 gets spend totals as of 09:59, not the end of day.

**Feature Views (declarative feature engineering).** Declare an aggregation ("sum of amount per
user over 7 days") over a table, a Kafka or Kinesis stream, or request-time data; Databricks
computes it, backfills it, and keeps it fresh offline and online. GA 12 October 2026 (Public
Preview before); a few parts (e.g. `SawtoothWindow`, `CustomUDF`) are still Preview.

**Online Feature Store (formerly Online Tables).** Low-latency copy of feature tables, backed by
Lakebase, that serving endpoints read during real-time inference. A *Feature Serving* endpoint
returns feature values over REST to apps or models running outside Databricks.

**Model Serving (formerly Mosaic AI Model Serving).** Serverless REST endpoints for custom MLflow
models, Databricks-hosted foundation models (pay-per-token or provisioned throughput) and
external models such as OpenAI. Scales to zero for non-production; bills while warm.
*Inference tables* log every request and response to a UC table for monitoring and retraining.

**Unity Gateway (formerly Mosaic AI Gateway / AI Gateway).** Governance layer in front of model
endpoints, external LLM providers and MCP servers: permissions, rate and spend limits,
guardrails, usage tracking. GA August 2026.

**AI Search (formerly Vector Search / Mosaic AI Vector Search).** Managed similarity search over
embeddings, kept in sync with a Delta table, plus keyword (BM25) and hybrid search. The
retrieval half of a RAG chatbot. Renamed June 2026; the `databricks-vectorsearch` package is a
compatibility shim for `databricks-ai-search`.

**Agent Bricks.** Databricks' family of tools for building and deploying AI agents (with
managed memory, sessions, tools and tracing). Several parts were Beta in late 2026.

**AI Functions.** SQL functions that call models inside a query: `ai_query`, `ai_classify`,
`ai_extract`, `ai_parse_document`. Example: classify 10 million support tickets by topic with one
SQL statement.

**Data quality monitoring (formerly Lakehouse Monitoring).** Two parts: *anomaly detection*
(Public Preview) learns each table's commit cadence and daily row volume across a schema and flags
stale or incomplete tables; *data profiling* (the old Lakehouse Monitoring) computes summary and
drift metrics for a table or a model inference table. Billed as serverless under
`DATA_QUALITY_MONITORING`.

## 8. SQL, BI and AI assistants

**Databricks SQL (DBSQL).** The data-warehouse face of Databricks: SQL editor, query history,
SQL warehouses, dashboards, alerts. In the 2026 UI this section is labelled "Lakehouse".

**SQL warehouse.** Compute dedicated to SQL queries from BI tools, dbt and the SQL editor.
**Serverless** starts in 2–6 seconds and autoscales (the default); **Pro** and **Classic** run in
your VPC and take about 4 minutes to start, kept for custom networking needs.

**AI/BI dashboards (formerly Lakeview dashboards).** Built-in dashboards on SQL warehouses with
AI-assisted authoring. Legacy dashboards were retired and deleted in early 2026.

**Genie Agents (formerly Genie spaces / AI/BI Genie).** A natural-language "ask your data"
experience that data teams configure with curated tables, metrics and instructions. Example: a
sales manager types "top 10 accounts by churn risk this quarter" and gets SQL plus a chart.

**Genie One and Genie Code (Genie Code formerly Databricks Assistant).** Genie One is the chat
front door for business users; Genie Code is the in-product AI coding agent for notebooks, SQL,
pipelines and dashboards.

## 9. Apps, operational data and operations

**Lakebase.** Fully managed PostgreSQL inside Databricks (built on Neon's technology), GA since
January 2026, Postgres 16–18. Separates storage from compute, so it autoscales, scales to zero,
and can branch a database instantly for testing. Use it for application state and low-latency
lookups next to lakehouse data, not for analytics.

**Synced tables.** Keep a copy of a UC Delta table in Lakebase, updated automatically, so an app
can do millisecond key lookups on lakehouse results. Example: serve per-customer
recommendations computed nightly.

**Databricks Apps.** Host internal web apps (Streamlit, Dash, Gradio, React, Express) on
serverless Databricks compute, with UC permissions and SSO built in. Saves standing up separate
hosting for a data tool or chatbot UI.

**System tables.** Read-only Databricks-managed tables under the `system` catalog covering
billing (`system.billing.usage`), audit, lineage, jobs, compute, query history and more. The
source for cost dashboards, chargeback and governance reports. `system.access.audit` records
every action (who read, granted, dropped); `system.query.history` records every SQL query with
duration and bytes, the first stop for "why is this slow?" and "who is spending?".

## 10. Use cases

| Workload | Why Databricks fits | Concrete example |
|---|---|---|
| Large-scale batch ETL | Spark at any scale, Photon, managed Delta maintenance, declarative pipelines | Nightly: 2 TB of clickstream JSON → cleaned silver tables → daily gold aggregates, one pipeline with data-quality rules |
| Streaming and near-real-time | Auto Loader, Kafka/Kinesis readers, streaming tables, Zerobus | Card transactions from MSK into a streaming table, fraud features updated within seconds |
| Database replication / CDC | Lakeflow Connect or Debezium + AUTO CDC into SCD2 tables | Mirror 40 production Postgres tables into the lakehouse with full change history |
| SaaS data centralisation | Managed connectors land SaaS data next to product data | Salesforce + Workday + product events joined for revenue per employee |
| ML training and feature store | Data, features, experiments, registry and lineage in one governed place | Churn model trained on point-in-time features, logged with MLflow, scored nightly with `score_batch` |
| Real-time ML serving | Online Feature Store + Model Serving with automatic feature lookup | Checkout calls an endpoint with `user_id`; it fetches features and returns a fraud score in tens of milliseconds |
| GenAI / RAG / agents | AI Search over governed documents, Model Serving, Unity Gateway, MLflow tracing | Internal support assistant answering from policy PDFs, with access limited by UC permissions |
| SQL analytics and BI on lake data | Serverless SQL warehouses, AI/BI dashboards, Genie | Finance dashboards on gold tables without copying into a separate warehouse |
| Governed data sharing | OpenSharing, Clean Rooms, Marketplace | Share a live, filtered product-usage table with a partner who uses Snowflake |
| Migrating from Hadoop / EMR | Federation first, then move writers; managed maintenance replaces cron jobs | Glue catalog federated in week one; EMR jobs moved one domain at a time |
| Data apps on lakehouse data | Lakebase + Databricks Apps + synced tables | Ops team app showing live inventory risk, reading Lakebase, writing overrides back |

## 11. When to use / when not to use

| Situation | Verdict | Better alternative (if not Databricks) | Why |
|---|---|---|---|
| Large or growing data (hundreds of GB to PB) with mixed ETL, streaming and ML | **Use** | — | This is the design centre: one copy of data, one governance layer, Spark scale |
| ML team needs features, training, registry and serving on the same data | **Use** | — | Feature lineage and automatic lookup remove glue code and train/serve skew |
| Streaming + batch on the same tables | **Use** | — | Same tables and code for both; pipelines handle incremental state |
| Lakehouse on open formats with several engines (EMR, Trino, Snowflake reading) | **Use** | — | UC Iceberg REST catalog and UniForm keep tables open to other engines |
| Small or simple workloads (a few GB, a handful of daily SQL transforms) | **Avoid** | Postgres + dbt, DuckDB/MotherDuck, Athena, or a cron'd Python job | Platform overhead (workspaces, UC, IAM, networking, cost controls) outweighs the benefit; a distributed engine is unnecessary |
| Pure BI on a warehouse that already works (Snowflake, BigQuery, Redshift) | **Avoid** | Keep the existing warehouse | Adds a second platform, migration cost and duplicate governance for no new capability |
| Low-latency OLTP (orders, payments, user accounts) | **Avoid the lakehouse** | Aurora / RDS Postgres, DynamoDB | Delta tables are for analytics, not thousands of small transactions per second. Lakebase is reasonable for app state that sits next to lakehouse data, but core systems of record belong in a dedicated OLTP database |
| Cost-sensitive, steady, well-understood batch Spark job | **Often avoid** | EMR on EC2 with spot, EMR on EKS, or Spark on Kubernetes | Databricks' DBU charge sits on top of EC2; EMR's uplift is usually smaller, and a stable job gains little from Databricks' productivity features. Re-check: include engineering time and Photon speed-ups before deciding |
| Team without platform engineering skills or time | **Avoid, or buy help** | Snowflake / BigQuery + a managed ELT tool (Fivetran) + dbt | Databricks still needs someone to own UC design, IAM roles, networking, compute policies and cost attribution; SQL-first warehouses have fewer knobs |
| Sub-second event processing with complex per-event state | **Avoid** | Apache Flink (e.g. Amazon Managed Service for Apache Flink) or Kafka Streams | Spark streaming is micro-batch; seconds of latency are normal, sub-second with heavy state is not its strength |
| Full-text search or log analytics as the primary need | **Avoid** | OpenSearch / Elasticsearch | Purpose-built inverted indexes, sub-second search; AI Search covers RAG retrieval, not log search |
| Ad hoc SQL over S3 a few times a month | **Avoid** | Athena | Pay per query scanned, nothing to run or govern |
| Strong preference to stay vendor-neutral | **Use with care** | Self-managed Spark + Iceberg + an open catalog | Data stays in open formats, but pipelines, Feature Views, Genie and bundles are Databricks-specific; flag Preview-only features in any lock-in review |

## 12. Databricks vs Snowflake vs self-managed Spark (EMR)

| Dimension | Databricks | Snowflake | Self-managed Spark (EMR) |
|---|---|---|---|
| Core strength | Spark-native data engineering, streaming and ML on open tables | SQL warehousing with very little tuning | Full control and lowest raw compute price |
| Primary interface | Python, SQL, Scala notebooks and files | SQL first; Python via Snowpark | Whatever you build: spark-submit, Airflow, notebooks |
| Storage | Delta or Iceberg in *your* S3 | Snowflake-managed storage by default; Iceberg tables on your S3 optional | Your S3, usually Iceberg or Hudi or Delta |
| Governance | Unity Catalog (permissions, lineage, audit, ABAC) | Horizon (RBAC, masking, lineage) | Glue + Lake Formation + IAM, assembled yourself |
| ML / AI | Integrated: MLflow, feature store, Model Serving, AI Search, agents | Snowflake ML, Feature Store, Cortex AI; less suited to heavy custom training | Bring your own (SageMaker, Feast, MLflow OSS) |
| Streaming | Structured Streaming, streaming tables, Zerobus | Snowpipe Streaming, dynamic tables (minute-level freshness) | Spark Structured Streaming or Flink, self-run |
| Operational database | Lakebase (Postgres) | Snowflake Postgres | None; use RDS/Aurora |
| Billing | DBUs (+ EC2 on classic) | Credits per second with a 60-second minimum per warehouse start, plus storage | EC2 + EMR fee, or EMR Serverless vCPU/memory-seconds |
| Ops burden | Medium: workspaces, UC, IAM, policies | Low: warehouses and roles | High: clusters, versions, compaction, catalog, security |
| Pick it when | ETL + streaming + ML on large data, open formats matter | Analytics/BI teams, SQL-heavy work, minimal ops | Steady, well-understood jobs where cost dominates and you have Spark platform engineers |

Rule of thumb: Snowflake for SQL analytics with the least effort; Databricks when data
engineering and ML at scale are the main event; EMR when the job is stable, the team is strong
on Spark, and the compute bill is the deciding number. Many companies run two: Databricks for
engineering and ML, Snowflake for BI, joined through Iceberg tables and a shared catalog. The
`snowflake` and `spark` skills cover those platforms in depth.

## 13. Sources

Checked October 2026.
- Architecture, control and compute planes: https://docs.databricks.com/aws/en/getting-started/high-level-architecture
- DBU definition: https://www.databricks.com/product/pricing
- Photon (defaults, UI vs API, DBU rate): https://docs.databricks.com/aws/en/compute/photon
- SQL warehouse types and start times: https://docs.databricks.com/aws/en/compute/sql-warehouse/warehouse-types
- Free Edition: https://docs.databricks.com/aws/en/getting-started/free-edition
- Lakebase overview and GA (22 Jan 2026), Postgres versions: https://docs.databricks.com/aws/en/oltp/ , https://docs.databricks.com/aws/en/release-notes/lakebase/ , https://docs.databricks.com/aws/en/oltp/instances/
- AI Search (formerly Vector Search): https://docs.databricks.com/aws/en/ai-search/ai-search
- Model Serving: https://docs.databricks.com/aws/en/machine-learning/model-serving/
- Unity Gateway: https://docs.databricks.com/aws/en/unity-gateway/ ; rename and GA date: https://lakenaut.dev/news/ai-gateway-is-now-unity-gateway-and-it-is-generally-available-6582ad/
- Genie family: https://docs.databricks.com/aws/en/genie/
- AI/BI dashboards and legacy retirement: https://docs.databricks.com/aws/en/dashboards/ , https://docs.databricks.com/aws/en/archive/legacy/legacy-dashboards
- Databricks Apps: https://docs.databricks.com/aws/en/dev-tools/databricks-apps/
- OpenSharing (formerly Delta Sharing): https://docs.databricks.com/aws/en/opensharing/
- Lakeflow Connect: https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/ ; PostgreSQL connector status: https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/postgresql-reference
- Zerobus Ingest: https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/zerobus-overview , https://www.databricks.com/blog/announcing-general-availability-zerobus-ingest-part-lakeflow-connect
- Data quality monitoring: https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-quality-monitoring/
- Agent Bricks: https://docs.databricks.com/aws/en/generative-ai/agent-bricks/
- Release notes used for renames and GA dates: March 2026 (Assistant → Genie Code, Asset Bundles → Declarative Automation Bundles, type widening), June 2026 (Vector Search → AI Search, Delta Sharing → OpenSharing, Lakeflow Designer GA), July 2026 (Genie Spaces → Genie Agents, Variant GA), August 2026 (Unity Gateway GA, Zerobus GA), September 2026 (automatic CDF GA, `system.query.history` GA): https://docs.databricks.com/aws/en/release-notes/product/2026/march , .../june , .../july , .../august , .../september , .../may (SQL section renamed "Lakehouse")
- October 2026 release notes (Feature Views GA 12 Oct, MySQL integrated CDC GA 15 Oct): https://docs.databricks.com/aws/en/release-notes/product/2026/october
- Data quality monitoring parts: https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-quality-monitoring/anomaly-detection/ , .../data-profiling/
- Amazon EMR pricing model: https://aws.amazon.com/emr/pricing/
- Snowflake billing model: the local `snowflake` skill (Service Consumption Table, 30 Sep 2026)
- Snowflake Postgres (Crunchy Data acquisition): https://www.snowflake.com/en/blog/streamline-data-movement-snowflake-postgres/ , https://www.infoworld.com/article/4001149/snowflake-acquires-crunchy-data-for-enterprise-grade-postgresql-to-counter-databricks-neon-buy.html
- Everything else (UC objects, Delta maintenance, pipelines, feature store): the other files in this skill and their sources.
