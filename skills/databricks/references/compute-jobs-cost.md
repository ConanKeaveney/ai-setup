# Compute, jobs, bundles and cost

Compute types and their limits, Photon, Lakeflow Jobs, Declarative Automation Bundles, and
cost attribution with system tables. Bundle layout and execution-mode guidance adapted from the
official `databricks-dabs`, `databricks-jobs` and `databricks-execution-compute` skills
(https://github.com/databricks/databricks-agent-skills).

## Contents
1. Compute types
2. Serverless: what you give up
3. Classic compute settings that matter on AWS
4. Photon
5. Lakeflow Jobs
6. Declarative Automation Bundles (DABs)
7. Cost model
8. Cost queries (system tables)
9. Cost controls

## 1. Compute types

| Type | Billing SKU family | Start | Use |
|---|---|---|---|
| Serverless notebooks | Serverless interactive | seconds | Default for interactive Python/SQL |
| Serverless jobs | Serverless jobs ("standard" or "performance-optimized" mode) | seconds–~1 min | Default for scheduled work |
| Serverless pipelines | Serverless DLT/SDP | seconds–minutes | Lakeflow pipelines; required for incremental MV refresh |
| Serverless SQL warehouse | SQL serverless | 2–6 s | BI, dbt, SQL ETL, Genie/dashboards |
| Pro / Classic SQL warehouse | SQL pro / classic | minutes | Only if serverless not possible |
| Classic jobs compute | Jobs compute | ~3–7 min | Needs custom confs, init scripts, JARs, GPUs, instance types |
| Classic all-purpose | All-purpose (highest) | ~3–7 min | Interactive R/Scala/RDD; never schedule jobs on it |
| Instance pools | (no DBU while idle; EC2 cost) | faster classic start | Classic clusters that start often |
| Model / Feature Serving | Model serving | — | Endpoints; scale-to-zero |
| Lakebase | Lakebase | — | Online feature store, synced tables, app OLTP |

Access modes (classic): **standard** (formerly "shared": multi-user, UC-enforced, Python/SQL/
Scala, no RDDs) and **dedicated** (formerly "single user": one user or group, full API). Serverless
behaves like standard mode.

Execution from a laptop: Databricks Connect
(`DatabricksSession.builder.profile("p").serverless(True).getOrCreate()`) runs DataFrame code on
remote compute; best for IDE dev and unit-ish tests.

## 2. Serverless: what you give up

- Most Spark confs are not settable (only a small allow-list); no `spark.conf` tuning of shuffle
  partitions, AQE knobs, etc.
- No RDD API, no `SparkContext`, no init scripts, no cluster-scoped JARs / Maven libraries;
  Python deps via notebook `%pip` or job **environments** (`client` version + `dependencies`;
  environment version 6 since 3 Sep 2026; `pyproject.toml` job environments Beta 22 Oct 2026).
- Changed in 2026 (release notes): **JAR tasks run on serverless — GA 6 Aug**; `df.cache()` /
  `persist()` on serverless — Public Preview 23 Oct (env version 5+); serverless compute access
  control GA 3 Aug; private connectivity from serverless to AWS-managed resources GA 12 Oct;
  environment variables for serverless jobs Beta 3 Aug.
- No instance type, spot, or GPU choice (GPU serverless exists separately for AI workloads).
- Network egress governed by serverless network policies; private connectivity via NCC
  (network connectivity configurations).
- Before porting OSS Spark code, grep it for `sparkContext`, `rdd`, `spark.conf.set`, custom
  JARs, Hadoop FS calls — those need rework or classic jobs compute. The official
  `databricks-serverless-migration` skill covers this in depth.

## 3. Classic compute on AWS

- `aws_attributes`: `availability: SPOT_WITH_FALLBACK`, `first_on_demand: 1` (driver on-demand),
  `zone_id: auto`; EBS volume type/size; Graviton instance families for price/performance.
- Autoscaling `min_workers`/`max_workers`; enable autoscaling local storage.
- DBR: pick an LTS (e.g. 16.4 LTS, 17.3 LTS); ML runtimes (`-ml`) for training.
- `custom_tags` propagate to EC2 and to `system.billing.usage.custom_tags`.
- Compute policies enforce all of the above and are the main cost guardrail.

## 4. Photon

On for serverless and SQL warehouses; opt-in on classic at a higher DBU rate. Speeds up scans,
joins, aggregations, Delta writes, MERGE/UPDATE/DELETE (with deletion vectors via predictive I/O),
and point-in-time feature joins (`use_spark_native_join=True`). Falls back to Spark for
unsupported operators — check the query profile for non-Photon nodes. Python UDF-heavy and
RDD jobs gain little; compare **cost per run** with Photon on and off.

## 5. Lakeflow Jobs (formerly Workflows)

- **Tasks**: notebook, Python script, Python wheel, JAR, SQL (query/file/dashboard/alert), pipeline,
  dbt, run-job (call another job), `for_each` (fan out over a list), `condition` (if/else),
  Spark submit (legacy).
- **Triggers**: cron schedule, file arrival (on a UC location), table update (when upstream UC
  tables change; on OpenSharing objects and system tables GA 30 Sep 2026), continuous. Manual /
  API. Up to five triggers per job, each pausable (Beta, 5 Oct 2026).
- Run a subset of tasks with their dependencies (30 Jun 2026); job-level query performance metrics
  (GA 26 Oct 2026). Continuous pipelines are best orchestrated by continuous jobs (10 Aug 2026).
- **Parameters**: job-level parameters pushed to tasks; dynamic values (`{{job.run_id}}`,
  `{{job.start_time.iso_date}}`); task values for passing small outputs between tasks.
- **Reliability**: per-task retries, timeouts, `max_concurrent_runs`, **repair run** (rerun only
  failed tasks), notifications/webhooks, health rules (duration thresholds).
- **Identity**: `run_as` a service principal. Jobs compute is per-job-cluster or shared job
  cluster across tasks; serverless via `environment_key`.
- **System tables**: `system.lakeflow.jobs`, `job_tasks`, `job_run_timeline`, `job_task_run_timeline`.
- Airflow: `DatabricksRunNowOperator` triggers a bundle-deployed job; keep orchestration in one
  place if possible.

## 6. Declarative Automation Bundles (DABs, formerly Databricks Asset Bundles)

```
project/
├── databricks.yml
├── resources/
│   ├── features.pipeline.yml
│   └── train.job.yml
└── src/ (notebooks, .py, .sql)
```

```yaml
# databricks.yml
bundle:
  name: fraud-features
include: [resources/*.yml]
variables:
  catalog: {default: dev_ml}
targets:
  dev:
    mode: development          # prefixes resource names per user, pauses schedules
    default: true
    workspace: {host: https://<dev-workspace>.cloud.databricks.com}
  prod:
    mode: production
    workspace: {host: https://<prod-workspace>.cloud.databricks.com}
    variables: {catalog: prod_ml}
    run_as: {service_principal_name: <sp-application-id>}
```

```yaml
# resources/train.job.yml
resources:
  jobs:
    train_fraud:
      name: train-fraud
      schedule: {quartz_cron_expression: "0 0 3 * * ?", timezone_id: UTC}
      environments:
        - environment_key: default
          spec: {client: "4", dependencies: ["databricks-feature-engineering>=0.16.0"]}
      tasks:
        - task_key: refresh_features
          pipeline_task: {pipeline_id: ${resources.pipelines.fraud_features.id}}
        - task_key: train
          depends_on: [{task_key: refresh_features}]
          environment_key: default
          notebook_task:
            notebook_path: ../src/train.py
            base_parameters: {catalog: ${var.catalog}}
      tags: {team: ml-platform, cost_center: fraud}
```

```bash
databricks bundle init                  # templates (default-python, default-sql, pipelines...)
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run train_fraud -t dev
databricks bundle deploy -t prod        # from CI with a service principal (OAuth M2M)
```

Notes: CLI ≥1.3 uses the direct deployment engine by default (no Terraform). Pipelines can be
scaffolded with `databricks pipelines init`. Code changes only take effect after `deploy`.
Keep one bundle per deployable unit; share config via variables, not copy-paste.

## 7. Cost model

Cost = DBUs × $/DBU (by SKU: product, tier, serverless or not, Photon) + for classic, EC2/EBS in
your AWS bill + S3 storage/requests + networking. Serverless DBU prices include the compute
infrastructure, so compare serverless DBU cost against classic DBU **plus** EC2. All-purpose DBU
rate is materially higher than jobs compute for the same work. (Databricks' pricing pages render
rates client-side; read current $/DBU from `system.billing.list_prices`, not from blogs.)

**Serverless vs classic, measured.** Capital One, 8 Jan 2026, TPC-DS SF1000, 95 queries, DBR
16.4, 8× r6idn.xlarge, EC2 included for classic [vendor-neutral but single benchmark]:

| Config | P99 (s) | Total cost |
|---|---|---|
| Jobs classic, Photon on, spot | 82 | $10.22 |
| Jobs classic, Photon off, spot | 163 | $7.81 |
| Jobs serverless, standard | 231 | $12.95 |
| Jobs serverless, performance-optimized | 159 | $18.20 |
| Serverless SQL warehouse, Medium | 2.05 | $2.70 |

Rules this rests on: classic jobs compute was 27–78% cheaper than serverless jobs for steady SQL
batch; Photon cost +31% here for 2× better P99 — keep it where latency matters, measure where it
doesn't; **SQL-shaped batch on a serverless SQL warehouse beat both** despite the higher $/DBU.
Serverless wins on bursty, short or idle-prone work (no idle, no cluster start). Opposite data
point: a Feb 2024 community PoC (CSV output, untuned, m5d) found EMR 2–6× cheaper than Databricks
with Photon — benchmark your own jobs, writing Delta, with equal tuning on both sides.

Cheaper serverless knobs (release notes): standard performance mode for one-time runs via Jobs API
(11 Sep 2026), for MV/ST refreshes in jobs (6 Jul) and for dbt-task refreshes (20 Aug).

## 8. Cost queries

Enable system schemas first (account admin; `system.billing` is on by default, others may need
enabling), and grant `SELECT` on them to the FinOps group.

Spend by product, last 30 days (list price):

```sql
SELECT u.billing_origin_product, u.product_features.is_serverless AS serverless,
       SUM(u.usage_quantity * p.pricing.default) AS list_cost_usd
FROM system.billing.usage u
JOIN system.billing.list_prices p
  ON u.cloud = p.cloud AND u.sku_name = p.sku_name
 AND u.usage_start_time >= p.price_start_time
 AND (u.usage_end_time <= p.price_end_time OR p.price_end_time IS NULL)
WHERE u.usage_date >= current_date() - INTERVAL 30 DAYS
GROUP BY ALL ORDER BY list_cost_usd DESC;
```

Spend by team tag (works for classic `custom_tags` and serverless usage-policy tags):

```sql
SELECT coalesce(u.custom_tags['team'], '<untagged>') AS team, u.billing_origin_product,
       SUM(u.usage_quantity * p.pricing.default) AS list_cost_usd
FROM system.billing.usage u
JOIN system.billing.list_prices p
  ON u.cloud = p.cloud AND u.sku_name = p.sku_name
 AND u.usage_start_time >= p.price_start_time
 AND (u.usage_end_time <= p.price_end_time OR p.price_end_time IS NULL)
WHERE u.usage_date >= current_date() - INTERVAL 30 DAYS
GROUP BY ALL ORDER BY list_cost_usd DESC;
```

Most expensive jobs, 30 days (from the Databricks jobs-cost doc, verbatim):

```sql
with list_cost_per_job as (
  SELECT t1.workspace_id, t1.usage_metadata.job_id,
    COUNT(DISTINCT t1.usage_metadata.job_run_id) as runs,
    SUM(t1.usage_quantity * list_prices.pricing.default) as list_cost,
    first(identity_metadata.run_as, true) as run_as,
    first(t1.custom_tags, true) as custom_tags,
    MAX(t1.usage_end_time) as last_seen_date
  FROM system.billing.usage t1
  INNER JOIN system.billing.list_prices list_prices on
    t1.cloud = list_prices.cloud and t1.sku_name = list_prices.sku_name and
    t1.usage_start_time >= list_prices.price_start_time and
    (t1.usage_end_time <= list_prices.price_end_time or list_prices.price_end_time is null)
  WHERE t1.billing_origin_product = "JOBS"
    AND t1.usage_date >= CURRENT_DATE() - INTERVAL 30 DAY
  GROUP BY ALL
),
most_recent_jobs as (
  SELECT *, ROW_NUMBER() OVER(PARTITION BY workspace_id, job_id ORDER BY change_time DESC) as rn
  FROM system.lakeflow.jobs QUALIFY rn=1
)
SELECT t2.name, t1.job_id, t1.workspace_id, t1.runs, t1.run_as,
       SUM(list_cost) as list_cost, t1.last_seen_date
FROM list_cost_per_job t1
LEFT JOIN most_recent_jobs t2 USING (workspace_id, job_id)
GROUP BY ALL ORDER BY list_cost DESC
```

Other useful cuts (`billing_origin_product` values from the billing reference, Oct 2026):
- Pipelines: `usage_metadata.dlt_pipeline_id`, `billing_origin_product = 'DLT'`.
- Warehouses: `usage_metadata.warehouse_id`; join `system.compute.warehouses`; query-level cost
  attribution via `system.query.history` (GA 21 Sep 2026) and query tags (GA 30 Sep 2026).
- Serving: `'MODEL_SERVING'`, `usage_metadata.endpoint_name`.
- Lakebase / online stores: `'LAKEBASE'` (also `'DATABASE'`; legacy online tables `'ONLINE_TABLES'`),
  `usage_metadata.database_instance_id`.
- Feature View materialization: `'FEATURE_STORE'`; split by `usage_metadata.data_source` /
  `.operation`.
- Lakeflow Connect: `'LAKEFLOW_CONNECT'`. Data quality monitoring: `'DATA_QUALITY_MONITORING'`.
  Predictive optimization: `'PREDICTIVE_OPTIMIZATION'` + `system.storage.predictive_optimization_operations_history`.
- Serverless usage policy: `usage_metadata.usage_policy_id` (`budget_policy_id` is deprecated) and
  the policy's tags in `custom_tags`.
- Serverless performance mode: `product_features.performance_target` (`STANDARD` /
  `PERFORMANCE_OPTIMIZED`); Photon: `product_features.is_photon`.
- Jobs on all-purpose clusters (waste): usage with `usage_metadata.job_id IS NOT NULL` and
  `sku_name LIKE '%ALL_PURPOSE%'`.

Background spend by product, week over week — catches the line items nobody launched by hand:

```sql
SELECT billing_origin_product, date_trunc('WEEK', usage_date) AS wk, SUM(usage_quantity) AS dbus
FROM system.billing.usage
WHERE usage_date >= current_date() - INTERVAL 8 WEEKS
  AND billing_origin_product IN ('PREDICTIVE_OPTIMIZATION','DATA_QUALITY_MONITORING','LAKEBASE',
      'DATABASE','FEATURE_STORE','MODEL_SERVING','LAKEFLOW_CONNECT','DEFAULT_STORAGE','NETWORKING')
GROUP BY ALL ORDER BY billing_origin_product, wk;
```

Untagged serverless spend (who has no usage policy):

```sql
SELECT identity_metadata.run_as, billing_origin_product, SUM(usage_quantity) AS dbus
FROM system.billing.usage
WHERE product_features.is_serverless AND usage_metadata.usage_policy_id IS NULL
  AND usage_date >= current_date() - INTERVAL 30 DAYS
GROUP BY ALL ORDER BY dbus DESC;
```

Failing pipeline updates (tables GA 21 Oct 2026; SCD2 definitions, take the latest row):

```sql
SELECT p.name, t.pipeline_id, count_if(t.result_state = 'FAILED') AS failed, count(*) AS updates
FROM system.lakeflow.pipeline_update_timeline t
LEFT JOIN (SELECT * FROM system.lakeflow.pipelines
           QUALIFY row_number() OVER (PARTITION BY workspace_id, pipeline_id ORDER BY change_time DESC) = 1) p
  USING (workspace_id, pipeline_id)
WHERE t.period_start_time >= current_date() - INTERVAL 7 DAYS
GROUP BY ALL ORDER BY failed DESC;
```

(The `result_state` value spelling is unverified — check `SELECT DISTINCT result_state` first.)

Gotchas: `usage_quantity` has ORIGINAL/RETRACTION/RESTATEMENT records — aggregate with `SUM`;
list price ≠ your negotiated price; ORIGINAL records typically land within 12 hours (longer for
new workspaces), so do not alert on today's partial day. Saving an unchanged job no longer adds
rows to `system.lakeflow.jobs` (19 Oct 2026). Query text in system tables is masked by default
since 26 Aug 2026 (account admins and `databricks_pii_access` can read it).

**Common bill surprises** (each a documented mechanic):
- Online feature stores and Lakebase computes without scale-to-zero bill 24/7.
- Serving endpoints left warm outside prod; orphaned Feature View materializations.
- Data quality monitoring / profiling on many or large tables (serverless, per table and refresh).
- Predictive optimization is billed separately as serverless — expected, but surprises finance.
- Serverless performance-optimized mode as the default for batch that could run standard.
- MVs recomputed fully because a source lacks row tracking/CDF or compute is classic.
- Classic jobs scheduled on all-purpose clusters; clusters without auto-termination.
- Continuous pipelines (and Lakeflow Connect gateways) running always-on for daily-freshness needs.
- Genie: free for users through 31 Jan 2027, but service-principal usage is billed (3 Aug 2026).

## 9. Cost controls

- **Compute policies** (classic): max workers/DBU per hour, auto-termination ≤ 30–60 min, spot
  with fallback, allowed instance families, required `custom_tags`, pinned DBR.
- **Serverless usage policies** (Public Preview; formerly budget policies; tags applied to
  serverless notebooks, jobs, pipelines, serving endpoints, Lakebase Autoscaling projects, Apps) —
  the only way to attribute serverless spend per team. They attribute, they do not cap. Traps: a
  user with several policies gets the alphabetically first unless they choose; pipelines triggered
  by a job do not inherit the job's policy; existing assets are not back-filled; tag changes apply
  only to new usage. Feature Store materializations take `budget_policy_id` at creation.
- **Budgets** (GA 6 Jul 2026; Budget Manager/Viewer ACLs 16 Oct 2026) on tags/workspaces with
  email alerts; they alert, never stop compute. The account usage dashboard.
- **SQL warehouses**: serverless, auto-stop of a few minutes, max clusters cap, one per workload
  class; check `system.query.history` for runaway queries; query timeouts.
- **Jobs**: serverless standard mode for non-urgent batch; `availableNow` streams instead of
  always-on clusters where latency allows; timeouts on every job.
- **Pipelines**: triggered not continuous unless needed; development mode only in dev.
- **Storage**: predictive optimization (VACUUM) on managed tables; S3 lifecycle on landing
  buckets; watch compatibility-mode copies.
- **Serving/online**: scale-to-zero outside prod; one online store per domain; delete orphaned
  endpoints, materialized features, and online stores.

## Sources
- https://github.com/databricks/databricks-agent-skills — `skills/databricks-dabs`, `databricks-jobs`, `databricks-execution-compute`, `databricks-serverless-migration`, `databricks-unity-catalog/references/5-system-tables.md` (adapted)
- https://docs.databricks.com/aws/en/compute/choose-compute
- https://docs.databricks.com/aws/en/admin/system-tables/billing
- https://docs.databricks.com/aws/en/admin/system-tables/jobs-cost
- https://docs.databricks.com/aws/en/admin/usage/budget-policies
- https://docs.databricks.com/aws/en/optimizations/predictive-optimization
- https://docs.databricks.com/aws/en/dev-tools/bundles/
- https://docs.databricks.com/aws/en/release-notes/dev-tools/bundles
- https://docs.databricks.com/aws/en/admin/system-tables/jobs (pipelines tables GA: .../release-notes/product/2026/october)
- https://docs.databricks.com/aws/en/machine-learning/feature-store/cost-management
- Release notes Jul–Oct 2026: https://docs.databricks.com/aws/en/release-notes/product/2026/july , .../august , .../september , .../october
- Serverless vs classic benchmark (Capital One, 8 Jan 2026): https://capitalonesoftware.com/blog/databricks-benchmarks-classic-jobs-serverless-jobs-dbsql-comparison
- EMR vs Databricks PoC counter-example (community, Feb 2024): https://community.databricks.com/t5/get-started-discussions/poc/m-p/60433
