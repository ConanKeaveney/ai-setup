---
name: databricks
description: >-
  Reference for Databricks on AWS: glossary, when to use it (vs Snowflake, EMR), system design
  rules (medallion, environments, pipelines vs jobs, CDC, CI/CD, self-serve platform), Unity
  Catalog, Delta and Iceberg, ingestion and CDC, Lakeflow pipelines and jobs, compute, cost
  governance, Feature Store / Feature Views and serving, and migrating from OSS Spark + Iceberg,
  Glue or Feast. Load whenever work touches Databricks. Triggers: "databricks", "unity catalog",
  "delta lake", "DLT", "lakeflow", "streaming table", "AUTO CDC", "auto loader", "change data
  feed", "feature store", "feature views", "model serving", "mlflow", "photon", "SQL warehouse",
  "asset bundles", "liquid clustering", "OPTIMIZE", "DBU", "system tables", "usage policy",
  "databricks cost", "lakebase", "data quality monitoring", "medallion", "design on databricks",
  "glue federation", "feast migration".
---

# Databricks (AWS) — platform reference

State as of 28 October 2026. Product names churn fast; the rename table below is load-bearing.
Before asserting a status (GA / Public Preview), check the linked doc — previews graduate often.

Deeper material:
- [references/system-design.md](references/system-design.md) — design rules with reasons, best resources to read
- [references/feature-store.md](references/feature-store.md) — feature tables, point-in-time, Feature Views, online store, serving, MLflow, Feast mapping
- [references/pipelines-cdc.md](references/pipelines-cdc.md) — Lakeflow pipelines, expectations, AUTO CDC, Auto Loader, Lakeflow Connect, CDF, MERGE patterns
- [references/unity-catalog-iceberg.md](references/unity-catalog-iceberg.md) — UC object model, grants, volumes, lineage, managed Iceberg, UniForm, Iceberg REST catalog, Glue federation
- [references/compute-jobs-cost.md](references/compute-jobs-cost.md) — compute types, Photon, Lakeflow Jobs, bundles, system-table cost queries, cost controls
- [references/migration-oss.md](references/migration-oss.md) — OSS Spark + Iceberg on AWS → Databricks, step by step
- [references/concepts.md](references/concepts.md) — plain-English glossary (~75 terms, old names in brackets), use cases, when to use / not, Databricks vs Snowflake vs EMR

## Renames (use the new name, recognise the old)

| Old name | Current name | Notes |
|---|---|---|
| Delta Live Tables (DLT) | Lakeflow Spark Declarative Pipelines (SDP); docs also say "Lakeflow pipelines" / "Lakeflow Declarative Pipelines" | `import dlt` → `from pyspark import pipelines as dp`. Core open-sourced as Apache Spark Declarative Pipelines |
| `APPLY CHANGES INTO` / `dlt.apply_changes` | `AUTO CDC INTO` / `dp.create_auto_cdc_flow` | Old syntax still parses; write the new one |
| `CREATE LIVE TABLE`, `LIVE.` prefix | `CREATE OR REFRESH MATERIALIZED VIEW` / `STREAMING TABLE`, bare names | |
| Databricks Workflows | Lakeflow Jobs | |
| Databricks Asset Bundles | Declarative Automation Bundles (still "DABs", still `databricks bundle ...`) | CLI ≥1.3 uses the direct deploy engine by default, not Terraform |
| Workspace Feature Store, `FeatureStoreClient` | Feature Engineering in Unity Catalog, `FeatureEngineeringClient` | Any UC Delta table with a PK is a feature table |
| Online Tables (legacy) | Online Feature Store (Lakebase-backed) | Legacy online tables are inaccessible |
| Feature Views beta (`ContinuousWindow`, `create_kafka_config`, `create_pipeline`) | Feature Views, **GA** (`RollingWindow`, `create_stream`, `materialize_features`) | Beta features must be migrated |
| Lakehouse Monitoring | Data quality monitoring: data profiling + anomaly detection | Billed `DATA_QUALITY_MONITORING` |
| Budget policies | Serverless usage policies | `usage_metadata.usage_policy_id`; `budget_policy_id` deprecated |
| UniForm | "External Iceberg Reads" in newer docs (same `delta.universalFormat` property) | |
| Workspace model registry, stages | Models in Unity Catalog, aliases (`@prod`) | `mlflow.set_registry_uri("databricks-uc")` |
| Access modes "shared" / "single user" | "standard" / "dedicated" | |

More renames (Vector Search → AI Search, Delta Sharing → OpenSharing, Genie spaces → Genie
Agents, Assistant → Genie Code, AI Gateway → Unity Gateway) are in the glossary.

## When to use it / when not to

| Situation | Verdict | Instead |
|---|---|---|
| Large data with mixed ETL, streaming and ML on the same tables | Use | — |
| Features, training, registry and real-time serving on governed data | Use | — |
| Open-format lakehouse read by several engines (EMR, Trino, Snowflake) | Use | — |
| Small or simple workloads (a few GB, a few daily SQL transforms) | Avoid | Postgres + dbt, DuckDB, Athena |
| Pure BI on a warehouse that already works | Avoid | Keep Snowflake / BigQuery / Redshift |
| Low-latency OLTP system of record | Avoid the lakehouse | Aurora / RDS, DynamoDB (Lakebase only for app state next to lakehouse data) |
| Steady, well-understood, cost-sensitive batch Spark | Often avoid | EMR on EC2 with spot, EMR on EKS |
| Team without platform skills to own UC, IAM, networking, cost policies | Avoid or buy help | Snowflake / BigQuery + managed ELT + dbt |
| Sub-second stateful event processing | Avoid | Flink |

Rule of thumb: Snowflake for SQL analytics with least effort, Databricks when data engineering
and ML at scale are the main event, EMR when the job is stable and the compute bill decides.
Reasons, use cases and the full Databricks vs Snowflake vs EMR table:
[references/concepts.md](references/concepts.md).

## Designing on Databricks

Rules with reasons, sources and the reading list: [references/system-design.md](references/system-design.md).

| Decision | Rule of thumb | Why |
|---|---|---|
| Layers | Bronze append-only raw (+provenance) → silver one validated row per record (CDC applied here) → gold per consumer. Drop gold when consumers read silver facts | Medallion is "recommended, not required"; every layer costs storage and compute |
| Workspaces | Dev + prod, add staging as the team grows; never one per team; >50–100 needs strong justification | Isolation belongs in catalogs, not workspaces |
| Catalogs | One metastore per region; catalogs `<env>_<domain>`; managed storage per catalog on a UC-only bucket; prod catalog bound `ISOLATED` to prod workspace; personal dev schemas | Default binding is `OPEN`; catalog is the isolation unit |
| Pipelines vs jobs | Declarative pipelines for ingestion, CDC, medallion SQL; jobs + wheels for procedural logic and ML; jobs as the outer DAG | Pipelines bring retries, state, expectations; jobs bring control |
| ST vs MV vs MERGE | ST for append/ingest; MV for joins/aggregates over changing inputs (incremental only on serverless with row tracking + CDF on sources); MERGE in a job only when AUTO CDC can't express it | An MV over a read-once source (Kafka) breaks on full refresh |
| Re-runs | `REPLACE WHERE`/`REPLACE USING` over dynamic partition overwrite; idempotent `foreachBatch` MERGE; one checkpoint per stream; backfill pipelines with `append once` flows; protect bronze with `pipelines.reset.allowed=false` | `foreachBatch` is at-least-once; full refresh loses expired sources |
| CDC/SCD | SCD1 unless audit/point-in-time needs SCD2; `AUTO CDC` for logs, `FROM SNAPSHOT` for dumps; never-null sequencing STRUCT | Log-based captures deletes; query-based misses them |
| Quality | Fail only on invariants, drop+quarantine bad records, anomaly detection for freshness; gate downstream with a separate validation task | Expectations don't block downstream tables |
| CI/CD | Bundles for workspace resources, Terraform for account/network; deploy SP ≠ run-as SP, OIDC; unit → deploy non-prod → staging integration | `mode: production` enforces branch, `run_as`, no dev-mode pipelines |
| Self-serve | Groups own, SPs run prod; compute policies + required tags on classic; usage policies on serverless; budgets alert (never cap); bundle templates as golden paths | Attribution and guardrails must exist before onboarding teams |
| Features | Freshness tier decides trigger (cron → table trigger → streaming ~200 ms p99); one online store per env; promote code, not tables or models | Cost climbs steeply with freshness; online stores bill 24/7 |
| Observability | `system.billing.usage`, `system.lakeflow.*` (regional, ~1 h lag, SCD2 definitions), `system.query.history`, lineage, `system.data_quality_monitoring.table_results`; SQL alerts on SLA | System tables are free to read (pay query compute); free retention varies per table (audit 365 days) |

## Orientation map

```
            ┌──────────────────── Unity Catalog (account-level metastore) ───────────────────┐
            │ catalog.schema.{table | view | volume | function | model | feature | stream}   │
            │ grants · lineage · audit · tags · row filters/masks · system tables            │
            └───────────────────────────────────────────────────────────────────────────────┘
 Ingest                         Transform                    Serve / consume
 ─────                          ─────────                    ───────────────
 Auto Loader (S3 files)   ─┐    Lakeflow pipelines (SDP):    SQL warehouses (BI, dbt, ad hoc)
 Lakeflow Connect (SaaS,   ├──▶ streaming tables, MVs,  ──▶  Feature Engineering → training sets
   Postgres/MySQL/SQL Svr) │    expectations, AUTO CDC       Online Feature Store (Lakebase)
 Kafka/Kinesis/MSK        ─┤    or notebooks/wheels in        Model Serving / Feature Serving
 Zerobus (push), Federation┘    Lakeflow Jobs                Iceberg REST catalog → EMR/Trino/Snowflake
 Storage: Delta or Iceberg on your S3 (managed by UC)  ·  Compute: serverless or classic (EC2 in your VPC)
 Deploy: Declarative Automation Bundles (YAML) + CLI  ·  Cost: system.billing.* + tags + budgets
```

Two planes: the **control plane** (Databricks' account) runs UI, jobs scheduler, UC; the
**compute plane** is either *serverless* (Databricks' AWS account, your data stays in your S3) or
*classic* (EC2 in your VPC). Serverless removes cluster tuning but restricts Spark confs, RDDs,
init scripts and custom JVM libraries.

## Picking compute

| Workload | Use | Avoid / notes |
|---|---|---|
| Scheduled ETL (Python/Scala/notebook) | Serverless jobs compute ("standard" mode for cost, "performance-optimized" for latency) | All-purpose clusters — higher DBU rate, not built for automation |
| Scheduled ETL that needs custom Spark confs, init scripts, JARs, GPUs, RDD API, specific instance types | Classic **jobs** compute (spot with fallback, Photon if SQL-heavy) | |
| Declarative pipelines | Serverless pipelines (needed for incremental MV refresh) | Classic pipeline compute only for unsupported features |
| SQL: BI, dbt, analysts, ad hoc | Serverless SQL warehouse (starts in seconds, Photon always on) | Pro/Classic warehouse only if serverless unavailable or custom networking |
| Interactive notebook dev | Serverless notebooks; classic all-purpose only for R, RDDs, Scala, custom libs | Leaving all-purpose clusters up: set auto-termination |
| Local IDE dev against real data | Databricks Connect (`DatabricksSession...serverless(True)`) | |
| Model / feature serving | Model Serving endpoints (serverless; scale-to-zero for non-prod) | |
| Low-latency key lookups (features, app state) | Lakebase (managed Postgres) via Online Feature Store / synced tables | Querying Delta from an app request path |

**Photon**: vectorised C++ engine; on by default for serverless and SQL warehouses; opt-in on
classic at a higher DBU rate. Wins on SQL/DataFrame scans, joins, aggregations, MERGE, writes to
Delta; little gain on Python UDF-heavy or RDD code. Measure cost per run, not runtime alone.

## Unity Catalog model

- **Hierarchy**: metastore (one per region per account) → catalog → schema → table / view /
  volume / function / registered model / feature / stream. Three-level names everywhere:
  `catalog.schema.object`. Catalogs are usually per environment or domain (`dev_ml`, `prod_ml`).
- **Managed vs external tables**: managed = UC owns the files (in the catalog/schema managed
  storage location, on *your* S3), gets predictive optimization, auto liquid clustering,
  `UNDROP` (default 7-day recovery). External = you own the path; UC governs access only; `DROP`
  leaves files. Default to managed; use external only when another system must own the path.
- **Formats**: managed tables can be Delta or Iceberg (`USING ICEBERG`).
- **Volumes**: governed file storage `/Volumes/<cat>/<sch>/<vol>/...` for raw files, checkpoints,
  libraries, model artifacts. Replaces DBFS mounts. `READ VOLUME` / `WRITE VOLUME` privileges.
- **Access to S3**: storage credential (IAM role) → external location (S3 prefix) → external
  tables/volumes and managed storage. Not instance profiles.
- **Grants** cascade down; a reader needs `USE CATALOG` + `USE SCHEMA` + `SELECT`. Grant to
  groups, run jobs as service principals.
  ```sql
  GRANT USE CATALOG ON CATALOG prod_ml TO `data-scientists`;
  GRANT USE SCHEMA, SELECT ON SCHEMA prod_ml.features TO `data-scientists`;
  GRANT CREATE TABLE, MODIFY ON SCHEMA dev_ml.sandbox TO `data-scientists`;
  GRANT EXTERNAL USE SCHEMA ON SCHEMA prod_ml.features TO `emr-sp`;  -- external engines via IRC
  ```
- **Lineage** is automatic for UC workloads (table + column level): `system.access.table_lineage`,
  `system.access.column_lineage`; features → models lineage shows in Catalog Explorer.

Detail, Iceberg interop and federation: [references/unity-catalog-iceberg.md](references/unity-catalog-iceberg.md).

## Delta table maintenance

| Topic | Rule of thumb |
|---|---|
| Layout | **Liquid clustering** for all new tables (`CLUSTER BY (a, b)` up to 4 keys, or `CLUSTER BY AUTO` on UC managed tables, DBR 15.4+). Not combinable with partitioning or Z-order. Convert: `ALTER TABLE t REPLACE PARTITIONED BY WITH CLUSTER BY (...)` |
| Z-order | Legacy. Only on partitioned tables you are not migrating yet |
| Partitioning | Only for very large tables with a low-cardinality column used in nearly every filter, or hard retention deletes. Never small partitions |
| OPTIMIZE | Incremental compaction + clustering. `OPTIMIZE t FULL` reclusters everything (after changing keys) |
| VACUUM | Deletes unreferenced files older than retention (default 7 days, `delta.deletedFileRetentionDuration`). Kills time travel beyond that. `VACUUM t DRY RUN` first. Never lower retention below your longest-running stream/query |
| Predictive optimization | Runs OPTIMIZE, VACUUM, ANALYZE on UC **managed** tables automatically (default on for newer accounts; rolled out to all accounts). Billed as serverless jobs. Observe in `system.storage.predictive_optimization_operations_history`. `ALTER CATALOG c ENABLE PREDICTIVE OPTIMIZATION` |
| Deletion vectors | Soft-delete rows for fast DELETE/UPDATE/MERGE (merge-on-read). Purge with `REORG TABLE t APPLY (PURGE)`. Upgrades protocol — old external readers break; UniForm needs them off |
| Change data feed | `delta.enableChangeDataFeed = true` (legacy CDF) or automatic CDF (DBR 19+, row-tracking tables). Read with `table_changes('t', v)` or `readChangeFeed`. Required for TRIGGERED/CONTINUOUS online-store publish |
| Row tracking | `delta.enableRowTracking = true` — enables incremental MV refresh and automatic CDF |

## Ingestion and CDC patterns

| Source | Pattern |
|---|---|
| Files landing in S3 | Auto Loader (`cloudFiles`, or `STREAM read_files(...)` in SQL) into a streaming table; file events on the external location rather than directory listing |
| Postgres / MySQL / SQL Server | Lakeflow Connect database connector (gateway + staging + serverless pipeline, SCD1/2) — check connector status; or Debezium → Kafka/MSK → `AUTO CDC` |
| SaaS (Salesforce, Workday, ServiceNow, ...) | Lakeflow Connect |
| Kafka / MSK / Kinesis | Streaming table reading `read_kafka` / `read_kinesis`; for features, Feature Views `create_stream` |
| CDC feed already in a table | `AUTO CDC INTO target FROM STREAM(src) KEYS (...) SEQUENCE BY ...` (SCD 1 or 2) |
| Periodic full snapshots | Python `dp.create_auto_cdc_from_snapshot_flow()` |
| Query in place, no copy | Lakehouse Federation (foreign catalog) |
| Downstream incremental reads of a Delta table | Change data feed, not full rescans |

```sql
CREATE OR REFRESH STREAMING TABLE customers_cdc_raw
AS SELECT * FROM STREAM read_files('/Volumes/raw/crm/landing/customers/', format => 'json');

CREATE OR REFRESH STREAMING TABLE customers;            -- SCD2 target
CREATE FLOW customers_flow AS AUTO CDC INTO customers
FROM STREAM(customers_cdc_raw)
KEYS (customer_id)
APPLY AS DELETE WHEN op = 'd'
SEQUENCE BY STRUCT(ts_ms, lsn)
COLUMNS * EXCEPT (op, ts_ms, lsn, _rescued_data)
STORED AS SCD TYPE 2;                                   -- adds __START_AT / __END_AT
```

Expectations, MVs vs streaming tables, Auto Loader options, MERGE outside pipelines:
[references/pipelines-cdc.md](references/pipelines-cdc.md).

## Feature store essentials

Model: **Unity Catalog is the feature store.** A feature table is any UC Delta table with a
primary key (plus optional `TIMESERIES` key for point-in-time). Two authoring styles, one
train/score path (`create_training_set` → `fe.log_model` → `fe.score_batch` / serving):

1. **Feature tables + `FeatureLookup`** (GA): you compute features (pipelines/jobs), FE joins them.
2. **Feature Views** (declarative feature engineering, **GA**, `databricks-feature-engineering>=0.16.0`, Streams `>=0.18.0`, DBR 17.0 ML+ or serverless): declare aggregations over a Delta table, Kafka/Kinesis stream or request data; Databricks computes point-in-time and materializes offline (Delta) and online (Lakebase) via managed serverless pipelines (billed `FEATURE_STORE`). Databricks recommends them for new use cases.

```python
from databricks.feature_engineering import FeatureEngineeringClient, FeatureLookup
from datetime import timedelta
import mlflow
mlflow.set_registry_uri("databricks-uc")
fe = FeatureEngineeringClient()

fe.create_table(                                   # PK required; cannot be added later via this API
    name="prod_ml.features.user_txn_features",
    primary_keys=["user_id", "ts"], timeseries_column="ts",
    df=user_feats_df, description="7d/30d spend per user")
# later refreshes: fe.write_table(name=..., df=new_df)  (mode="merge" upserts on PK)

training_set = fe.create_training_set(
    df=labels_df,                                  # user_id, event_ts, label
    feature_lookups=[FeatureLookup(
        table_name="prod_ml.features.user_txn_features",
        lookup_key="user_id", timestamp_lookup_key="event_ts",   # AS OF join, no leakage
        lookback_window=timedelta(days=30))],
    label="label", exclude_columns=["user_id", "event_ts"])
train_pdf = training_set.load_df().toPandas()

with mlflow.start_run():
    model = train(train_pdf)
    fe.log_model(model=model, artifact_path="model", flavor=mlflow.sklearn,
                 training_set=training_set,        # stores feature lineage in the model
                 registered_model_name="prod_ml.models.fraud")

preds = fe.score_batch(model_uri="models:/prod_ml.models.fraud@prod", df=keys_df)  # keys (+ts) only
```

Online: `fe.create_online_store(name="fraud-online", capacity="CU_1")` (DNS-safe name), then
`fe.publish_table(online_store=..., source_table_name=..., online_table_name=..., publish_mode="TRIGGERED")`
(needs CDF + non-null PK for TRIGGERED/CONTINUOUS). Model Serving endpoints then look features up
automatically; Feature Serving endpoints expose raw features via a `FeatureSpec`.

Self-serve for data scientists: one `features_<domain>` schema per env catalog; prod features
created and materialized only by a CI service principal (only a materialized feature's creator can
delete it); scientists prototype with local `Feature(...)` objects and `CREATE FEATURE` in a
sandbox, then PR. One online store per environment (no scale-to-zero — it bills 24/7). Freshness via
anomaly detection on source schemas, drift via data profiling on tables feeding prod models.
Full API, naming, CI/CD, cost, monitoring, Feast mapping:
[references/feature-store.md](references/feature-store.md).

## Cost and governance checklist

- [ ] System tables enabled (`system.billing`, `system.access`, `system.lakeflow`, `system.compute`, `system.storage`) and a cost dashboard on `system.billing.usage` × `list_prices` ([queries](references/compute-jobs-cost.md)).
- [ ] Every workload attributable: `custom_tags` on classic clusters/pools, **serverless usage policies** for serverless (tags land in `custom_tags`), `run_as` service principals per team.
- [ ] Account budgets with alerts per tag/workspace.
- [ ] Compute policies: cap max workers, force auto-termination, restrict instance types, require tags; most users cannot create unrestricted clusters.
- [ ] Scheduled work on serverless jobs or classic **jobs** compute, never all-purpose.
- [ ] SQL warehouses serverless with short auto-stop; one per workload class, not per person.
- [ ] Model / feature serving: scale-to-zero outside prod; right-size online store capacity; delete unused endpoints and stores (they bill while idle).
- [ ] Weekly trend of background products (`PREDICTIVE_OPTIMIZATION`, `DATA_QUALITY_MONITORING`, `LAKEBASE`, `FEATURE_STORE`, `MODEL_SERVING`) and of serverless usage with no `usage_policy_id`.
- [ ] Compare **total cost per run** (DBU + EC2) before choosing serverless vs classic for steady batch: one TPC-DS benchmark (Jan 2026) had classic jobs 27–78% cheaper than serverless jobs, and a serverless SQL warehouse cheapest of all ([details](references/compute-jobs-cost.md)).
- [ ] UC: managed tables by default; catalog per environment; workspace-catalog bindings so dev cannot write prod; grants to groups only.
- [ ] Row filters / column masks (or ABAC tag policies) for PII; data classification tags.
- [ ] Audit: `system.access.audit`; lineage before any drop/rename.
- [ ] Everything deployed via bundles from Git; no hand-made prod jobs.

## Migration from OSS Spark + Iceberg on AWS (summary)

1. **Catalog first**: federate the existing Glue/Hive metastore into UC (foreign catalog) so
   Databricks reads current tables governed by UC without moving data. Glue Iceberg reads need a
   `storage_root` on the foreign catalog. Then convert incrementally: Delta in place
   (`SET MANAGED MOVE|COPY`), **Iceberg only by `DEEP CLONE`** — a full copy, history reset.
2. **Iceberg stays possible**: managed Iceberg tables in UC are read/write from Databricks and
   from EMR/Trino/Flink/PyIceberg via the UC Iceberg REST catalog (`/api/2.1/unity-catalog/iceberg-rest`).
   Choose Delta where you want CDF, SDP streaming tables/MVs, deletion vectors by default; choose
   managed Iceberg where external engines must *write*.
3. **Replace maintenance jobs** (`rewrite_data_files`, `expire_snapshots`, `remove_orphan_files`)
   with predictive optimization on managed tables.
4. **Hidden partition transforms** (`days(ts)`, `bucket(16, id)`) are not supported in
   `PARTITIONED BY` on managed Iceberg — use liquid clustering on plain columns.
5. **Security**: IAM instance profiles / bucket policies → storage credentials + external locations + UC grants.
6. **Jobs**: spark-submit / Airflow DAGs → Lakeflow Jobs defined in bundles (Airflow can still
   trigger them). Check serverless restrictions before porting code that sets Spark confs.
7. **Features**: Feast → Feature Engineering in UC; keep Feast online serving running until the
   Online Feature Store is backfilled and parity-tested.

Full plan and gotchas: [references/migration-oss.md](references/migration-oss.md).

## Pitfalls

- Writing `CREATE OR REPLACE STREAMING TABLE` — pipelines use `CREATE OR REFRESH`.
- Aggregating over a streaming table with another streaming table: STs are append-only; use an MV.
- Pipeline **full refresh** resets streaming state and can lose data whose source has expired (Kafka retention, deleted files). Treat as a destructive operation.
- Changing a dataset from ST to MV (or back) in place fails even with full refresh; rename or drop.
- `mlflow.log_model` instead of `fe.log_model(training_set=...)` → no feature lineage, `score_batch` and automatic lookup fail.
- Omitting `timestamp_lookup_key` on time-series features → label leakage; offline AUC looks great, prod collapses.
- `FeatureStoreClient` against UC tables — use `FeatureEngineeringClient`.
- Online store names must be DNS-compliant (hyphens, no underscores). `fe.get_online_store()` returns `None` when missing — it does not raise.
- Publishing to the online store without CDF and a NOT NULL PK (TRIGGERED/CONTINUOUS modes).
- Dropping a feature's source table leaves its materialization pipeline failing forever; tear down materialized features first.
- Lowering VACUUM retention below the lag of any stream or long query → `FileNotFound` and lost time travel.
- Treating `SHALLOW CLONE` as Snowflake's zero-copy clone: it copies metadata only and reads the source's files. On non-UC tables, VACUUM on the source breaks the clone; on UC managed tables it needs DBR 13.3+ and cannot be `CREATE OR REPLACE`d. Use `DEEP CLONE` for backups, DR, or anything that must outlive the source.
- Enabling deletion vectors on tables that external (non-Databricks) readers use, or with UniForm.
- Expecting CDF on managed Iceberg v2 tables — not supported; use Delta (+UniForm) if consumers need CDF.
- Installing an Iceberg library onto Databricks Runtime — it is built in; adding one causes conflicts.
- Running scheduled jobs on all-purpose clusters; forgetting auto-termination; Photon on UDF-heavy jobs.
- Joining `billing.usage` to `list_prices` on SKU only — must also bound by price start/end time.
- `usage_quantity` includes RETRACTION / RESTATEMENT records; always `SUM` rather than picking rows.
- Assuming Lakeflow Connect connectors are GA — PostgreSQL CDC and most SaaS connectors are Preview/Beta (Oct 2026); Feature Views core is GA but `SawtoothWindow`, `LastN`, `CustomUDF` are Preview.
- EMR/Flink writing merge-on-read v2 deletes into a UC managed Iceberg table — unsupported; switch writers to copy-on-write or v3 deletion vectors.
- Revoking then re-granting Lake Formation permissions on the Glue federation credential — a lapse can drop and recreate foreign schemas and lose their grants.
- Materializing Feature Views from a personal notebook — only the creator can ever delete them; tags/usage policy on an existing online table are silently ignored.
- Assuming deleting a UC pipeline drops its tables — tables are kept unless `cascade=true`.

## Existing official skills

[databricks/databricks-agent-skills](https://github.com/databricks/databricks-agent-skills)
(`databricks aitools install`) holds Databricks' maintained, CLI-oriented per-product skills; this
skill is the cross-product map and decision layer. `databricks-solutions/ai-dev-kit` is deprecated.

## Sources

- Official agent skills (paraphrased and credited throughout): https://github.com/databricks/databricks-agent-skills (commit 0420b1f, 1 Oct 2026) — `databricks-ml-training` (feature-store.md, feature-views.md), `databricks-pipelines`, `databricks-iceberg`, `databricks-unity-catalog`, `databricks-lakeflow-connect`, `databricks-execution-compute`, `databricks-dabs`
- https://github.com/databricks-solutions/ai-dev-kit (deprecation notice)
- Delta: https://docs.databricks.com/aws/en/delta/clustering , https://docs.databricks.com/aws/en/sql/language-manual/delta-vacuum , https://docs.databricks.com/aws/en/delta/clone , https://docs.databricks.com/aws/en/delta/delta-change-data-feed , https://docs.databricks.com/aws/en/delta/deletion-vectors , https://docs.databricks.com/aws/en/optimizations/predictive-optimization
- Tables and Iceberg: https://docs.databricks.com/aws/en/tables/managed , https://docs.databricks.com/aws/en/iceberg/ , https://docs.databricks.com/aws/en/tables/convert-to-managed , https://docs.databricks.com/aws/en/iceberg/clone , https://docs.databricks.com/aws/en/query-federation/hms-federation-glue
- Compute and cost: https://docs.databricks.com/aws/en/compute/choose-compute , https://docs.databricks.com/aws/en/admin/system-tables/billing , https://docs.databricks.com/aws/en/admin/system-tables/jobs-cost , https://docs.databricks.com/aws/en/admin/usage/budget-policies
- Pipelines and ingestion: https://docs.databricks.com/aws/en/ldp/ , https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/file-detection-modes , .../auto-loader/options , https://docs.databricks.com/aws/en/ingestion/lakeflow-connect/ , https://docs.databricks.com/aws/en/dev-tools/bundles/
- Feature store: https://docs.databricks.com/aws/en/machine-learning/feature-store/uc/feature-tables-uc , .../time-series , .../declarative-apis , .../online-feature-store , .../automatic-feature-lookup , https://docs.databricks.com/aws/machine-learning/feature-store/migrate-from-online-tables
- Release notes Jun–Oct 2026 (statuses quoted with dates): https://docs.databricks.com/aws/en/release-notes/product/2026/october , .../september , .../august , .../july , .../june
- Feature Views, materialization, cost: https://docs.databricks.com/aws/en/machine-learning/feature-store/feature-views , .../materialized-features , .../cost-management
- Data quality monitoring: https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-quality-monitoring/
- Design: https://docs.databricks.com/aws/en/developers/best-practices , https://docs.databricks.com/aws/en/data-governance/unity-catalog/best-practices , https://docs.databricks.com/aws/en/lakehouse-architecture/deployment-guide/workspace-strategy , https://docs.databricks.com/aws/en/lakehouse/medallion (full list in references/system-design.md)
- Serverless vs classic benchmark: https://capitalonesoftware.com/blog/databricks-benchmarks-classic-jobs-serverless-jobs-dbsql-comparison
