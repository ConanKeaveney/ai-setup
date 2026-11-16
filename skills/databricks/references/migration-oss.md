# Migrating from open-source Spark + Iceberg on AWS

For a team running Spark (EMR / EKS / self-managed) on Iceberg tables in S3 with a Glue (or Hive)
catalog, partly moving to Databricks. For Iceberg format internals (snapshots, manifests,
MoR vs CoW, maintenance procedures) load the separate `iceberg` skill if present.

## Contents
1. Decide the end state per table
2. Phased plan
3. Concept mapping
4. Code porting checklist
5. Coexistence: two engines, one table
6. Proof-of-concept scorecard
7. Evidence from real migrations
8. Risks

## 1. Decide the end state per table

| Table profile | End state |
|---|---|
| Written and read only by Databricks after migration | UC managed **Delta** (CDF, pipelines, deletion vectors, feature store all native) |
| Written by Databricks, read by EMR/Trino/Snowflake | Managed Delta + UniForm, or managed Iceberg |
| Written by external engines (EMR, Flink, Kafka Connect) long term | UC managed **Iceberg** via the Iceberg REST catalog, or keep in Glue and federate (read-only in Databricks) |
| Pipeline outputs (STs/MVs) needed by external engines | Compatibility mode |
| Not worth moving yet | Leave in Glue, read through a federated foreign catalog |

## 2. Phased plan

1. **Foundation**: account + workspaces (dev/prod), UC metastore, storage credentials and
   external locations on existing buckets, catalogs per env with managed locations on your S3,
   groups from your IdP via SCIM, service principals for CI.
2. **Federate**: Glue → UC foreign catalog. Analysts and new Databricks jobs read existing
   Iceberg tables with UC governance, no data copy.
3. **PoCs** (the team's current phase): one ingestion path (Auto Loader or Lakeflow Connect), one
   CDC path (AUTO CDC from Debezium/MSK or Lakeflow Connect for Postgres/MySQL), one feature table
   end to end (training set → model → online store → serving endpoint). Score with the scorecard
   below.
4. **Move writers**: per table, move the writer job to Databricks (bundle-deployed Lakeflow Job
   or pipeline), then bring the table under UC. For Glue **Iceberg** tables the only route to
   managed Iceberg is `DEEP CLONE` (full copy, history and time travel reset — no zero-copy, no
   `SET MANAGED`); Delta tables can `SET MANAGED MOVE|COPY` in place (DBR 17.3+). Cut over in a
   freeze window: stop the EMR writer, clone, repoint readers to the Iceberg REST catalog, keep the
   Glue copy read-only until parity checks pass. If EMR keeps writing a managed Iceberg table it
   must use copy-on-write or v3 deletion vectors (v2 MoR position/equality deletes unsupported).
5. **Decommission**: Glue entries, EMR clusters, custom compaction/expiry jobs, Feast infra.

## 3. Concept mapping

| OSS on AWS | Databricks |
|---|---|
| Glue Data Catalog / HMS | Unity Catalog (foreign catalog during migration) |
| Lake Formation / bucket policies / IAM per job | UC grants, row filters, column masks; storage credentials + external locations |
| EMR cluster per job / spark-submit | Serverless jobs or classic jobs compute; Lakeflow Jobs |
| Airflow / Step Functions DAG | Lakeflow Jobs (task graph, triggers, repair); Airflow can trigger jobs |
| Iceberg `rewrite_data_files` / `rewrite_manifests` | `OPTIMIZE` / predictive optimization |
| Iceberg `expire_snapshots`, `remove_orphan_files` | `VACUUM` / predictive optimization |
| Iceberg hidden partitioning, partition evolution | Liquid clustering (`CLUSTER BY`, changeable without rewrite) |
| Iceberg merge-on-read delete files | Delta deletion vectors (Iceberg v3 also has DVs) |
| Iceberg snapshots, time travel, tags/branches | Delta versions / `TIMESTAMP AS OF`, `RESTORE`; no branches (use clones for WAP-style flows) |
| Iceberg incremental read / changelog view | Delta change data feed |
| Spark Structured Streaming file source | Auto Loader |
| Debezium → Kafka → custom MERGE | AUTO CDC in a pipeline, or Lakeflow Connect |
| Great Expectations / Deequ checks | Pipeline expectations (plus your existing tests) |
| Terraform for EMR + Airflow DAG code | Declarative Automation Bundles (+ Terraform provider for account/workspace infra) |
| Feast | Feature Engineering in UC + Online Feature Store (see feature-store.md) |
| MLflow OSS | Managed MLflow, Models in UC |

## 4. Code porting checklist

- Replace two-part `db.table` names with `catalog.schema.table`; S3 paths with tables or
  `/Volumes/...` paths.
- Remove Iceberg runtime JARs and `spark.sql.catalog.*` configs from Databricks jobs (built in).
- Search for `sparkContext`, `.rdd`, `spark.conf.set`, Hadoop `FileSystem`, custom JARs,
  `input_file_name()` — these block serverless or standard access mode.
- `PARTITIONED BY (days(ts))` / `bucket(n, col)` → `CLUSTER BY (ts_date, col)` or `CLUSTER BY AUTO`.
- Structured Streaming checkpoints: new locations in volumes; do not reuse OSS checkpoints across
  engines/versions.
- Iceberg-specific SQL (`CALL system.rewrite_data_files`, `.snapshots` metadata tables) has no
  Delta equivalent — use `DESCRIBE HISTORY`, `OPTIMIZE`, predictive optimization.
- Credentials: replace access keys / instance profiles with UC service credentials and
  connections.
- Tests: run PySpark unit tests locally against OSS Spark or Databricks Connect; integration tests
  in a dev target via `databricks bundle run`.

## 5. Coexistence: two engines, one table

- One writer per table at a time. Pick the catalog that owns commits (UC for managed Iceberg;
  Glue for tables not yet migrated) — never let two catalogs commit to the same Iceberg table.
- External engines read UC tables through the Iceberg REST catalog with `EXTERNAL USE SCHEMA`
  and credential vending; Databricks reads Glue tables through federation.
- Watch reader compatibility: deletion vectors, Iceberg v3, zstd compression, column mapping.
- UniForm metadata is asynchronous — consumers that need read-after-write should read via
  Databricks or tolerate lag.

## 6. PoC scorecard

| Dimension | Measure |
|---|---|
| Cost | $/run and $/month vs EMR equivalent (DBU + EC2 vs EMR + EC2), from `system.billing.usage` |
| Latency / freshness | End-to-end lag source → silver → online feature |
| Developer time | Lines of pipeline code and on-call toil vs today |
| Correctness | Row-count and value parity with the OSS pipeline; SCD2 history parity |
| Governance | Can a data scientist self-serve a feature without a platform ticket? Are grants/lineage visible? |
| Interop | Can EMR/Trino/Snowflake still read (and if required, write) the tables? |
| Lock-in | What would it take to move back (formats, APIs used: Preview-only features flagged) |

## 7. Evidence from real migrations

Public write-ups with measured before/after results are scarce (searched Oct 2026); most "EMR →
Databricks saved X%" pages are consultancy marketing without method. What exists:

| Source | Measured | Rule it supports |
|---|---|---|
| Capital One TPC-DS SF1000, Jan 2026 | Classic jobs 27–78% cheaper than serverless jobs; serverless SQL warehouse cheapest of all for SQL batch | Port steady Spark batch to classic jobs compute first; move SQL-shaped transforms to a warehouse; don't assume serverless is cheaper |
| Community PoC, Feb 2024 (CSV in/out, untuned) | EMR 2–6× cheaper than Databricks + Photon on the same code | Run the cost PoC on real jobs, writing Delta, equally tuned; Photon does little for CSV-write-bound jobs |
| Coinbase (Databricks customer story) | Real-Time Mode: freshness ~800 ms → 100–250 ms; est. 51% compute cut | Gains came from retiring over-provisioned streaming clusters, not from the engine alone [vendor-published] |
| HMS/Glue→UC posts (Databricks community 2024; OneUptime Aug 2026, secondary) | (qualitative) | Phase by team or data product; SYNC/clone succeeds but jobs break on hard-coded two-part names and paths — grep code first |

No public Feast → Databricks migration with measured outcomes was found.

Transferable lessons (rules, each backed above or in the docs):
- Migrate jobs in waves starting with non-critical ones; keep Glue/HMS and UC in parallel via
  federation rather than a big-bang cutover.
- Compare **total cost per run** (DBU + EC2 + S3) per job class from `system.billing.usage`, not
  DBU rates. Classic jobs on spot + Photon only where the speed-up exceeds its DBU premium.
- The productivity case (managed maintenance, pipelines, feature lineage) is usually the real win;
  the raw-compute case often favours EMR. State both in the business case.

## 8. Risks

- Preview features (Feature View sub-features such as `SawtoothWindow`/`CustomUDF`, PostgreSQL
  CDC, many SaaS connectors) in a production design — keep a GA fallback (Feature Views core,
  feature tables + `FeatureLookup`, Debezium + AUTO CDC).
- Glue Lake Formation permission lapses on the federation service credential dropping and
  recreating schemas (and their grants) in the foreign catalog.
- One full copy per Iceberg table to reach managed Iceberg — budget S3 and the freeze window.
- Dual-catalog commits corrupting Iceberg tables.
- Serverless restrictions discovered late — audit code first.
- Cost surprise from all-purpose clusters, always-on pipelines, idle endpoints and online stores.
- Predictive optimization VACUUM removing files an external reader still references (long
  queries / stale snapshots) — set retention to cover the slowest consumer.

## Sources
- https://docs.databricks.com/aws/en/query-federation/hms-federation-glue
- https://docs.databricks.com/aws/en/query-federation/hms-federation-concepts
- https://docs.databricks.com/aws/en/iceberg/
- https://docs.databricks.com/aws/en/delta/clustering
- https://docs.databricks.com/aws/en/optimizations/predictive-optimization
- https://github.com/databricks/databricks-agent-skills — `databricks-iceberg`, `databricks-serverless-migration`
- https://docs.databricks.com/aws/en/tables/convert-to-managed
- https://docs.databricks.com/aws/en/iceberg/clone
- https://capitalonesoftware.com/blog/databricks-benchmarks-classic-jobs-serverless-jobs-dbsql-comparison
- https://community.databricks.com/t5/get-started-discussions/poc/m-p/60433
- https://www.databricks.com/customers/coinbase/lakeflow
- https://community.databricks.com/t5/technical-blog/prepare-your-journey-to-migrate-from-aws-glue-data-catalog-to/ba-p/66643
- https://oneuptime.com/blog/post/2026-08-05-migrate-hive-metastore-unity-catalog/view (hard-coded names pitfall; unverified secondary source)
