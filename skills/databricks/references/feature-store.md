# Feature Store on Databricks — deep reference

Feature Engineering in Unity Catalog, Feature Views (declarative feature engineering), the
Online Feature Store, feature and model serving, MLflow basics, and a Feast → Databricks mapping.
Much of the API detail and the gotchas are adapted from the official
`databricks-ml-training` skill (references `feature-store.md`, `feature-views.md`) in
https://github.com/databricks/databricks-agent-skills, cross-checked against docs.databricks.com.

## Contents
1. Mental model and product history
2. Feature tables (`FeatureLookup` API)
3. Point-in-time correctness
4. Training, logging, batch scoring
5. On-demand features (`FeatureFunction`)
6. Feature Views (declarative feature engineering)
7. Online Feature Store and serving
8. MLflow and Model Serving basics
9. Operating it as a platform (self-serve design)
10. Feast → Databricks mapping and migration
11. Gotchas

---

## 1. Mental model and product history

- **Unity Catalog is the feature store.** Since DBR 13.3 LTS, any UC Delta table with a primary
  key constraint is a feature table. Discovery, ACLs, lineage (table → feature → model →
  endpoint) all come from UC.
- **Offline store** = Delta tables in UC. **Online store** = Databricks Online Feature Store,
  backed by Lakebase (managed Postgres; new stores are Lakebase Autoscaling projects). Requires
  DBR 16.4 LTS ML+ or serverless, `databricks-feature-engineering>=0.13.0`.
- **Legacy, do not build on**: Workspace Feature Store (`FeatureStoreClient`,
  `databricks-feature-store` package), legacy Online Tables (inaccessible after 15 Jan 2026),
  third-party online stores for new builds (DynamoDB is still supported for automatic lookup in
  existing setups).
- **Package**: `databricks-feature-engineering` (pre-installed on DBR ML 13.3+; Feature Views need
  `>=0.16.0` and DBR 17.0 ML+ or serverless; Streams need `>=0.18.0`; latest 0.18.2 as of Oct
  2026). Client: `FeatureEngineeringClient`. `databricks-feature-store` deprecated in 0.17.0.

Two authoring styles share one train → log → score path:

| | Feature tables + `FeatureLookup` | Feature Views (declarative) |
|---|---|---|
| Status | GA | **GA 12 Oct 2026** for batch, streaming and request-time (release note); compliance-security-profile workspaces mid-Nov 2026. Some sub-features still Preview (below) |
| Who computes | You (pipeline / job writes the table) | Databricks, from a declared spec |
| Good for | Already-computed columns, arbitrary transforms, existing pipelines | Many window aggregations over the same source; streaming (Kafka) features |
| Training set arg | `feature_lookups=[FeatureLookup(...)]` | `features=[Feature(...)]` |
| Materialization | You write; `publish_table` for online | `materialize_features` (offline Delta + online Lakebase) |

Default: use plain UC tables unless you need reuse across models, point-in-time joins, online
lookups, or feature lineage on the model. Add FE when a concrete need appears.

## 2. Feature tables (`FeatureLookup` API)

```python
%pip install "databricks-feature-engineering>=0.16.0" "mlflow>=2.22"
dbutils.library.restartPython()

from databricks.feature_engineering import FeatureEngineeringClient, FeatureLookup, FeatureFunction
import mlflow
mlflow.set_registry_uri("databricks-uc")
fe = FeatureEngineeringClient()
```

**Create from a DataFrame** (PK required, unique, set at creation):

```python
fe.create_table(
    name="prod_ml.features.user_txn_features",
    primary_keys=["user_id", "ts"],
    timeseries_column="ts",            # singular; pre-0.16 alias was timestamp_keys
    schema=user_feats_df.schema,       # or df=... to create and write in one call
    description="Rolling spend per user",
)
fe.write_table(name="prod_ml.features.user_txn_features", df=user_feats_df)  # mode="merge" default
```

`write_table(mode="merge")` upserts on PK; rows not in the DataFrame are untouched.
`mode="overwrite"` replaces everything.

**Promote an existing table** (typical when features come from a Lakeflow pipeline / SQL):

```sql
ALTER TABLE prod_ml.features.user_txn_features ALTER COLUMN user_id SET NOT NULL;
ALTER TABLE prod_ml.features.user_txn_features ALTER COLUMN ts SET NOT NULL;
ALTER TABLE prod_ml.features.user_txn_features
  ADD CONSTRAINT user_txn_pk PRIMARY KEY (user_id, ts TIMESERIES);
-- recommended for time-series lookups:
ALTER TABLE prod_ml.features.user_txn_features CLUSTER BY (user_id, ts);
```

Only the table owner can add a PK. A materialized view / streaming table produced by a pipeline
can also carry a PK constraint in its definition, which is how pipeline-owned feature tables are
usually built.

## 3. Point-in-time correctness

- Mark the event-time column with `TIMESERIES` in the PK (or `timeseries_column=`).
- In `FeatureLookup`, set `timestamp_lookup_key` to the label DataFrame's timestamp column. FE
  does an AS OF join: for each label row, the latest feature row with `feature.ts <= label.ts`
  for that key.
- `lookback_window=timedelta(days=7)` ignores feature rows older than that (Feast's `ttl`).
- Performance: liquid-cluster on (key, ts); enable Photon and pass
  `use_spark_native_join=True` to `create_training_set` / `score_batch`.
- Online, time-series tables serve the latest value per key (snapshot) or a TTL-bounded window.

## 4. Training, logging, batch scoring

```python
from datetime import timedelta

labels = spark.table("prod_ml.labels.fraud_labels").select("txn_id", "user_id", "merchant_id", "event_ts", "label")

training_set = fe.create_training_set(
    df=labels,
    feature_lookups=[
        FeatureLookup(table_name="prod_ml.features.user_txn_features",
                      lookup_key="user_id", timestamp_lookup_key="event_ts",
                      feature_names=["spend_7d", "spend_30d", "txn_count_7d"],
                      lookback_window=timedelta(days=30)),
        FeatureLookup(table_name="prod_ml.features.merchant_features",
                      lookup_key="merchant_id",
                      rename_outputs={"risk_score": "merchant_risk"}),
    ],
    label="label",
    exclude_columns=["txn_id", "user_id", "merchant_id", "event_ts"],
)
df = training_set.load_df()

with mlflow.start_run():
    model = fit(df.toPandas())
    fe.log_model(
        model=model, artifact_path="model", flavor=mlflow.sklearn,
        training_set=training_set,                       # binds feature lineage + lookup spec
        registered_model_name="prod_ml.models.fraud",
    )

from mlflow import MlflowClient
c = MlflowClient(registry_uri="databricks-uc")
latest = max(c.search_model_versions("name='prod_ml.models.fraud'"), key=lambda v: int(v.version))
c.set_registered_model_alias("prod_ml.models.fraud", "prod", latest.version)

# Batch scoring: pass keys (+ timestamp for PIT) only; FE joins features from lineage
scored = fe.score_batch(model_uri="models:/prod_ml.models.fraud@prod",
                        df=spark.table("prod_ml.staging.txns_to_score")
                               .select("txn_id", "user_id", "merchant_id", "event_ts"),
                        result_type="double")
```

## 5. On-demand features (`FeatureFunction`)

Compute at request time from request data + looked-up features, using a UC Python UDF, so the
same code runs in training and serving.

```sql
CREATE OR REPLACE FUNCTION prod_ml.features.amount_vs_avg(amount DOUBLE, avg_7d DOUBLE)
RETURNS DOUBLE LANGUAGE PYTHON AS $$
return None if not avg_7d else amount / avg_7d
$$;
```

```python
FeatureFunction(udf_name="prod_ml.features.amount_vs_avg",
                input_bindings={"amount": "amount", "avg_7d": "spend_7d_avg"},
                output_name="amount_vs_avg")
```

Add it to `feature_lookups=[...]` alongside `FeatureLookup`s. At serving time the request must
carry the raw inputs (`amount`).

## 6. Feature Views (declarative feature engineering)

GA since 12 Oct 2026 (it was Public Preview behind a Previews-page toggle); `>=0.16.0`; DBR 17.0
ML+ or serverless. Features persist in UC as `Feature` objects (no `FeatureView` class).
Materialized output is called a **Materialized Feature**. UC privileges: `CREATE FEATURE` (schema),
`READ FEATURE`, `MANAGE` (needed to materialize or delete a feature).

Three ways to define (feature-views page, Oct 2026):
- `Feature(...)` constructor — local only, nothing in UC; usable in `create_training_set` for
  experiments. `fe.register_feature(f)` persists it later.
- `fe.create_feature(...)` — validate + register in one call.
- Sources: `DeltaTableSource` (batch, incremental via CDF), `StreamSource` (a UC Stream),
  `RequestSource` (request-time; `ColumnSelection` only, no aggregations/windows; ARRAY/MAP/STRUCT
  fields from 0.18.2), `FeatureViewSource` (0.18.0; not materializable).
- Operators: `Sum Avg Count Min Max First Last FirstN LastN VarPop VarSamp StddevPop StddevSamp`
  (`LastN` Preview). `CustomUDF` (Preview, not materializable).
- Windows: `TumblingWindow`, `SlidingWindow` (batch only); `RollingWindow` (batch + streaming,
  `delay=` replaces the beta `offset`); `SawtoothWindow` (Preview; streaming; `window_duration`
  > 2 days, recommended for windows > 7 days).

```python
from databricks.feature_engineering.entities import (
    DeltaTableSource, Feature, AggregationFunction, ColumnSelection,
    Sum, Avg, Count, Max, SlidingWindow, TumblingWindow, RollingWindow,
    OfflineStoreConfig, OnlineStoreConfig, CronSchedule, TableTrigger, StreamingMode)
from datetime import timedelta

src = DeltaTableSource(catalog_name="prod_ml", schema_name="silver", table_name="transactions",
                       filter_condition="amount > 0")       # optional; transformation_sql is projection-only

spend_7d = fe.create_feature(
    source=src, entity=["user_id"], timeseries_column="ts",
    function=AggregationFunction(operator=Sum(input="amount"),
                                 time_window=SlidingWindow(window_duration=timedelta(days=7),
                                                           slide_duration=timedelta(days=1))),
    catalog_name="prod_ml", schema_name="features", name="user_spend_7d")

# Preview without persisting: fe.compute_features(features=[...]).display()

training_set = fe.create_training_set(df=labels, features=[spend_7d], label="label",
                                      exclude_columns=["user_id", "ts"])

fe.materialize_features(
    features=[spend_7d],
    offline_config=OfflineStoreConfig(catalog_name="prod_ml", schema_name="features",
                                      table_name_prefix="fv"),
    online_config=OnlineStoreConfig(catalog_name="prod_ml", schema_name="features",
                                    table_name_prefix="fv_online", online_store_name="fraud-online"),
    trigger=CronSchedule(quartz_cron_expression="0 0 2 * * ?", timezone_id="UTC"))
```

Rules that bite:
- **Materialization runs as Databricks-managed serverless Lakeflow pipelines plus an orchestration
  job**, billed under `billing_origin_product = 'FEATURE_STORE'` at the serverless jobs rate (1x,
  no premium). Group features that share destinations and trigger into **one**
  `materialize_features` call — each call is its own pipeline.
- Triggers: `CronSchedule` (aggregations; the first run backfills immediately), `TableTrigger()`
  (runs on source commits; for aggregations at most once per half the feature's granularity,
  between 5 min and 1 h), `StreamingMode()` (required for `StreamSource`; also works on a
  `DeltaTableSource` with CDF). One trigger type per call; streaming and batch never in one call.
  *Correction:* earlier text here said `TableTrigger` was `ColumnSelection`-only — not so per the
  Oct 2026 materialization page.
- Not materializable: `RequestSource`, `FeatureViewSource`, `CustomUDF`, batch `RollingWindow`
  (except online-only `Last`). `ColumnSelection` materializes **online only**.
- **Only the creator of a materialized feature can delete it** (UC `MANAGE` does not help), and
  only in the workspace that created it. Materialize from CI as a service principal, never from a
  person's notebook.
- Fix history with `fe.backfill_features(features=[...], ...)` (+ `get_backfill`,
  `wait_for_backfill`, `cancel_backfill`, 0.18.2); streaming features cannot be backfilled this way.
  `purge_feature_entities` (Beta) deletes an entity's rows. No in-place update of a materialization:
  delete and re-materialize.
- Streaming: `fe.create_stream(name=..., source_config=KafkaStreamConfig|KinesisStreamConfig,
  connection_config=..., schema_config=..., ingestion_config=IngestionConfig(...))` registers a UC
  `Stream`. Auth via UC connection (MSK IAM through a service credential, SASL, mTLS); Kinesis via a
  `KINESIS` connection. Confluent Schema Registry for Avro/Protobuf (Kafka only); JSON needs an
  inline schema; one value subject per stream. Kafka columns are referenced as `value.`/`key.`.
  Ingestion starts at the latest offset — history only via `StreamBackfillSource` (needs a UTC
  `stream_record_timestamp` column and ≥1 h overlap with the live stream). Online only, ~200 ms p99
  freshness (docs). Streaming pipelines restart twice a week (up to ~1 min delay). Deleting a
  stream deletes its ingestion pipeline and table. `update_stream` only changes schema and
  excluded columns. The Streams page carried no status label on 12 Oct 2026.
- Entity columns must be scalar (no ARRAY/MAP/STRUCT); `DATE` timeseries columns are rejected for
  aggregations (0.18.0); entity/timeseries/request column names must be globally unique across a
  training set or endpoint; the label column must not exist in any source.
- A `FeatureSpec` cannot mix Feature View features with `FeatureLookup`/`FeatureFunction`.
- `list_materialized_features()` returns 100 by default — pass `max_results` in platform tooling.
- Teardown (drops do not cascade): remove references in models/specs → `delete_materialized_feature`
  (offline copy for aggregations, which also removes online; online copy for `ColumnSelection`) →
  `delete_feature` → delete stream → delete online store. A background process then removes the
  tables, pipeline and job. Skipping steps leaves pipelines failing and billing.

## 7. Online Feature Store and serving

```python
store = fe.get_online_store(name="fraud-online")      # returns None if absent (does not raise)
if store is None:
    fe.create_online_store(name="fraud-online", capacity="CU_1")   # DNS-safe name; takes minutes
    store = fe.get_online_store(name="fraud-online")

fe.publish_table(
    online_store=store,
    source_table_name="prod_ml.features.user_txn_features",
    online_table_name="prod_ml.features.user_txn_features_online",
    publish_mode="TRIGGERED",        # default; CONTINUOUS = streaming; SNAPSHOT = one-off full copy
)
```

Prereqs for TRIGGERED / CONTINUOUS: CDF on the source (`delta.enableChangeDataFeed = true`, or
automatic CDF) and non-nullable PK columns. SNAPSHOT suits tables where most rows change between
syncs.

Online store facts (online-feature-store page, updated 15 Oct 2026):
- Stores created after 23 Mar 2026 are **Lakebase Autoscaling projects**. Capacity `CU_1`,
  `CU_2`, `CU_4`, `CU_8`; resize with `fe.update_online_store(capacity=...)`. Up to 3 read
  replicas (`read_replica_count`). **No scale-to-zero** — a store bills continuously.
- Turning high availability off breaks connected serving endpoints until restarted; change HA
  blue/green.
- The online table's catalog name must match its Lakebase database name or serving deploys fail.
- A feature table published to several online tables: endpoints read the **oldest** one.
- `publish_table` ignores `filter_condition`, `checkpoint_location`, `mode`, `trigger`, `features`.
- CMK applies only to stores whose project was created after CMK reached the region.
- Freshness check for streaming features: Lakebase CDF preview + `REPLICA IDENTITY FULL`, then
  `commit_time - event_time` in `lb_<online_table>_history`. Adds load: validate, don't run in prod.

**Serving patterns**

| Pattern | Use when | How |
|---|---|---|
| Model Serving with automatic feature lookup | Model runs in Databricks | Model logged with `fe.log_model`; publish its feature tables; create endpoint; caller sends keys (+ request-time inputs); can override feature values in the payload |
| Feature Serving endpoint | Model or app outside Databricks needs raw features | `fe.create_feature_spec(name="prod_ml.features.fraud_spec", features=[...])` then serve the spec |
| Lakebase synced table | App needs row lookups that are not ML features | Synced table from Delta to Lakebase |

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput
w = WorkspaceClient()
w.serving_endpoints.create(
    name="fraud-features",
    config=EndpointCoreConfigInput(served_entities=[ServedEntityInput(
        entity_name="prod_ml.features.fraud_spec", workload_size="Small", scale_to_zero_enabled=True)]))
```

(The FE client's own `fe.create_feature_serving_endpoint` takes a single `ServedEntity`, not a
list — a known trap.) Feature Serving endpoints have no in-place fix after `UPDATE_FAILED`; delete
and recreate, and create them only after the online backfill finishes.

Inference tables on endpoints can log the augmented DataFrame (looked-up features included) for
monitoring and skew analysis.

## 8. MLflow and Model Serving basics

- Always `mlflow.set_registry_uri("databricks-uc")`; models are `catalog.schema.model`.
- Stages are gone in UC — use aliases (`@prod`, `@challenger`) and `set_registered_model_alias`.
- `mlflow.autolog()` captures params, metrics, artifacts; experiment parent folder must exist.
- Batch scoring of non-FE models: `mlflow.pyfunc.spark_udf(spark, "models:/cat.sch.m@prod", env_manager="local")`.
- Serving endpoint: `served_entities=[ServedEntityInput(entity_name=..., entity_version=...)]`,
  traffic split across versions for canaries, scale-to-zero for non-prod. Pin exact
  `pip_requirements`; mismatches fail at container build.
- Pass `resources=[...]` to `log_model` when the model calls other UC resources (functions,
  vector indexes, endpoints) so the endpoint gets passthrough credentials.

## 9. Operating it as a platform (self-serve design)

For ~1,000 features and self-serving scientists. Databricks publishes no naming standard for
features; the conventions below are this skill's recommendation, built on documented mechanics.

**Layout and naming**
- Schemas: `<env>_ml.features_<domain>` (shared, platform/CI-owned), `<env>_ml.sandbox_<team>`
  (scientist-owned, `CREATE FEATURE`/`CREATE TABLE`), `<env>_ml.models`. Promote by code, never by
  copying tables.
- Feature name = `<entity>_<measure>_<agg>_<window>` (`user_spend_sum_7d`); it is the column name
  in training sets, and entity/timeseries names must be globally unique per training set, so fix
  entity column names (`user_id`, never `uid` in one source and `user_id` in another).
- Comment every feature (what, unit, null meaning); govern tags `owner`, `domain`, `freshness_sla`,
  `pii`, `tier` (prod/experimental). Tags drive search, ABAC and cost reports. Governed tag
  propagation is Beta (12 Oct 2026).

**Ownership and permissions**
- Prod features are created and materialized only by a CI service principal (bundle-deployed job
  running the definitions module). Reasons: only the creator can delete a materialized feature,
  and run-as identity owns the pipeline. Owners of schemas/features = groups.
- Scientists: `READ FEATURE`/`SELECT` in prod; `CREATE FEATURE`, `CREATE TABLE`, `CREATE FUNCTION`
  in sandbox; experiment with local `Feature(...)` objects (no UC writes) and `compute_features`,
  then open a PR to register.
- `fe.grant_feature_serving_access(...)` (0.16.0) for serving principals.

**CI/CD ("features as code")**
- No bundle resource type exists for features, Feature Views or online stores (bundle resources
  page, Oct 2026: jobs, pipelines, `quality_monitor`, `database_instance`, `synced_database_table`,
  `postgres_*` Lakebase resources, `model_serving_endpoint`, `registered_model`, `catalog`,
  `schema`, `volume`...). Pattern: definitions live in a Python package; a bundle-deployed job runs
  `create_feature` / `materialize_features` idempotently (catch AlreadyExists → `get_feature`).
  Lakebase projects and serving endpoints can be bundle resources.
- PR checks: build the training set on a fixed label sample with local `Feature` objects; diff row
  counts/null rates against main; lint names and required tags.
- `materialize_features(tags=..., budget_policy_id=...)` (0.18.0) only applies at creation;
  materializing into an **existing** online table applies neither, silently. Set them on day one.

**Cost of the online path** (cost-management page)
- Online store: Lakebase compute per CU and replica, continuous; one shared store per environment
  (docs suggest sharing dev/test/training stores), start at `CU_1` and scale on measured latency.
- Feature Serving endpoints: Model Serving SKU (`SERVERLESS_REAL_TIME_INFERENCE`); scale-to-zero
  outside prod.
- Materialization: `FEATURE_STORE` product, serverless jobs rate; `usage_metadata.data_source` and
  `.operation` split batch vs streaming. Cheapest lever: a less frequent trigger.

**Freshness and drift**
- Freshness of sources: **data quality monitoring → anomaly detection** (Public Preview), enabled per
  schema (needs `MANAGE`; up to 50 schemas at once from a catalog): learns each table's commit
  cadence and 24 h row volume, flags stale/incomplete, results in
  `system.data_quality_monitoring.table_results`. Not on views or foreign tables.
- Distribution drift: **data profiling** (formerly Lakehouse Monitoring) — time series profile on
  offline feature tables, inference profile on serving inference tables; writes
  `profile_metrics`/`drift_metrics` Delta tables + a dashboard. Time series/inference profiles
  only cover the last 30 days; snapshot profiles max 4 TB. Both bill as serverless
  `DATA_QUALITY_MONITORING` — profile the tables that feed prod models, not all 1,000 features.
- Materialization health: Explore Feature Views UI, the orchestration job's runs in
  `system.lakeflow.job_run_timeline`, pipeline updates in `system.lakeflow.pipeline_update_timeline`
  (GA 21 Oct 2026).
- Train/serve skew: log inference tables on endpoints (they include looked-up features) and
  compare with training distributions in a profile.

**Golden path**: a bundle template with feature definitions job + training job + serving endpoint
so a new model is a PR, not a ticket.

## 10. Feast → Databricks mapping and migration

| Feast | Databricks |
|---|---|
| `feature_store.yaml` + registry (file/SQL) | Unity Catalog (no separate registry) |
| `Entity(join_keys=[...])` | Primary key columns (`lookup_key` / `entity=`) |
| `FeatureView(source=..., ttl=...)` over precomputed data | Feature table + `FeatureLookup(lookback_window=...)` |
| Batch source (`SparkSource`, file, warehouse) | UC Delta (or Iceberg) table |
| `get_historical_features(entity_df, features)` | `fe.create_training_set(df, feature_lookups)` → `load_df()` |
| Point-in-time join using `event_timestamp` + `ttl` | `TIMESERIES` PK + `timestamp_lookup_key` + `lookback_window` |
| `feast materialize` / `materialize-incremental` | `fe.publish_table` (TRIGGERED/CONTINUOUS) or `materialize_features` |
| Online store (Redis, DynamoDB, Postgres) | Online Feature Store (Lakebase) |
| `get_online_features` / feature server | Feature Serving endpoint, or automatic lookup in Model Serving |
| `FeatureService` | `FeatureSpec` |
| `OnDemandFeatureView` | `FeatureFunction` (UC Python UDF), or Feature Views `RequestSource` + `ColumnSelection` (no aggregations) / `CustomUDF` (Preview) |
| `StreamFeatureView` / `PushSource` | Feature Views `create_stream` + `StreamSource` (Kafka or Kinesis), or Zerobus into a CDF-enabled Delta table + `StreamingMode()`, or a streaming pipeline writing a feature table + CONTINUOUS publish |
| Feast does not compute features (transformations live elsewhere) | Feature tables: same; Feature Views: Databricks computes aggregations |
| Definitions in Git | Definitions in Git via bundles + Python; Feature View definitions persist in UC |

Migration plan:
1. Inventory Feast feature views, entities, TTLs, online-serving consumers and SLAs.
2. Point the existing batch-source tables at UC (federation or rewrite to managed tables), add PK
   + `TIMESERIES` constraints — these become feature tables without recomputation.
3. Rebuild training with `create_training_set`; diff against `get_historical_features` output on
   the same entity DataFrame (row counts, null rates, value equality) — PIT semantics differ
   subtly at boundaries (`<=` vs `<`, TTL vs lookback window).
4. Stand up the online store, publish, shadow-read against Feast's online store; compare
   p50/p99 latency and value parity.
5. Re-log models with `fe.log_model` so serving does automatic lookup; cut endpoints over; then
   retire Feast materialization jobs and the Redis/DynamoDB store.
6. Re-implement on-demand views as UC Python UDFs; check type coercion.

Trade-offs to state to stakeholders: Databricks gives governance, lineage and no separate
registry/infra; Feast gives portability and engine neutrality. Lock-in is mitigated because
feature tables are ordinary Delta/Iceberg tables readable through the Iceberg REST catalog.
Feature View definitions are not: they are Databricks Python objects with no export format.

**Public evidence (Oct 2026).** No public Feast → Databricks migration write-up with measured
results was found; plan the parity tests above as the evidence. The nearest is Coinbase (fraud
features), all figures vendor-published by Databricks:
- Customer story: Structured Streaming Real-Time Mode replacing tuned micro-batch; freshness
  ~800 ms → 100–250 ms, p99 < 100 ms, >250 features on one engine, "99%" online/offline
  consistency, estimated 51% annual compute reduction. Change was the trigger type, not the logic.
- Summit session "Right Features, Right Time" (Coinbase): Declarative Feature APIs with CI/CD
  ("features as code"), Lakebase serving targeting p99 < 50 ms; *early-testing estimates*: ~770 ms
  → 100–200 ms freshness, >90% potential streaming infra cost cut, 25–35% productivity from
  retiring self-built batch feature pipelines.
- Transferable rules: measure freshness as event-time → online-commit, not pipeline runtime; put
  CI guardrails on feature definitions before opening self-serve; Real-Time Mode needs dedicated
  compute with task slots ≥ tasks in all stages, so use it only where sub-second matters.

## 11. Gotchas

| Trap | Fix |
|---|---|
| `FeatureStoreClient` on UC tables | Use `FeatureEngineeringClient` |
| `mlflow.<flavor>.log_model` | Use `fe.log_model(training_set=...)` or score_batch/auto-lookup fail |
| `score_batch` given feature columns | Pass keys (+ timestamp) only |
| `timeseries_columns` (plural) from a docs page | API arg is `timeseries_column` (singular) |
| No `timestamp_lookup_key` on rolling features | Leakage |
| `publish_table` fails | Enable CDF; PK columns NOT NULL |
| Online store name with underscores | DNS-compliant names only |
| `fe.get_online_store` in try/except | It returns `None` |
| Rerun of `create_feature` raises AlreadyExists | Catch and `fe.get_feature(full_name=...)` |
| Throwaway Feature View test on a cron | Teardown in `try/finally`; otherwise it loops and bills |
| Kafka topic missing (MSK auto-create off) | Create topic before `create_stream` |
| Feature Views beta APIs (`create_kafka_config`, `ContinuousWindow`, `create_pipeline`, `offset=`, `schema_json`) | Rejected/renamed — `create_stream`, `RollingWindow`, `materialize_features`, `delay=`, `dataframe_schema` |
| `backfill_features(feature_full_names=...)` | Deprecated in 0.18.2; pass `features=[...]` |
| Materialized from a personal notebook | Only that person can delete it; materialize as a CI service principal |
| `tags`/`budget_policy_id` on an existing online table | Silently ignored; materialize to a new online table |
| Expecting the online store to scale to zero | It cannot; delete unused stores |
| Same feature table published to two online tables | Endpoints read the oldest; publish once |

## Sources
- https://github.com/databricks/databricks-agent-skills — `skills/databricks-ml-training/references/feature-store.md`, `feature-views.md` (adapted)
- https://docs.databricks.com/aws/en/machine-learning/feature-store/uc/feature-tables-uc
- https://docs.databricks.com/aws/en/machine-learning/feature-store/time-series
- https://docs.databricks.com/aws/en/machine-learning/feature-store/declarative-apis
- https://docs.databricks.com/aws/en/machine-learning/feature-store/declarative-api-reference
- https://docs.databricks.com/aws/en/machine-learning/feature-store/online-feature-store
- https://docs.databricks.com/aws/machine-learning/feature-store/migrate-from-online-tables
- https://docs.databricks.com/aws/en/machine-learning/feature-store/automatic-feature-lookup
- https://docs.databricks.com/aws/en/machine-learning/feature-store/feature-serving-tutorial
- Feature Views GA (12 Oct 2026): https://docs.databricks.com/aws/en/release-notes/product/2026/october
- https://docs.databricks.com/aws/en/machine-learning/feature-store/feature-views
- https://docs.databricks.com/aws/en/machine-learning/feature-store/feature-views-api-reference
- https://docs.databricks.com/aws/en/machine-learning/feature-store/materialized-features
- https://docs.databricks.com/aws/en/machine-learning/feature-store/streams
- https://docs.databricks.com/aws/en/machine-learning/feature-store/cost-management
- Client release notes (0.14.0–0.18.2): https://docs.databricks.com/aws/en/release-notes/feature-store/databricks-feature-store
- Bundle resource types: https://docs.databricks.com/aws/en/dev-tools/bundles/resources
- Data quality monitoring: https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-quality-monitoring/ , .../anomaly-detection/ , .../data-profiling/
- Real-time mode: https://docs.databricks.com/aws/en/structured-streaming/real-time
- Coinbase (vendor-published): https://www.databricks.com/customers/coinbase/lakeflow , https://www.databricks.com/dataaisummit/session/right-features-right-time-modernizing-real-time-fraud-feature-serving
- Feast concepts: https://docs.feast.dev/ (mapping from general knowledge; not re-verified this session)
