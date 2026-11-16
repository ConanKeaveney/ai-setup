# Designing data systems on Databricks

Design judgement, not a feature list: which shape to choose and why. Every rule is tagged
**[D]** official docs, **[V]** vendor claim, **[O]** independent opinion, **[S]** this skill's
recommendation built on documented mechanics. Pages checked 28 Oct 2026.

## Contents
1. Best resources to read
2. Medallion layers (and when they are overkill)
3. Workspaces, catalogs, schemas per environment and domain
4. Pipelines vs jobs; streaming tables vs materialized views vs MERGE
5. Idempotency, re-runs and backfills
6. CDC and SCD design
7. Data quality
8. CI/CD and environments with bundles
9. Multi-team self-serve platform
10. Feature platform
11. Observability
12. Sources

## 1. Best resources to read

| Resource | Why it is worth it |
|---|---|
| [Developer best practices](https://docs.databricks.com/aws/en/developers/best-practices) | The de facto CI/CD + environments page: workspaces, catalogs, service principals, test layers (the old `dev-tools/ci-cd/best-practices` URL now 404s) |
| [Unity Catalog best practices](https://docs.databricks.com/aws/en/data-governance/unity-catalog/best-practices) | Metastore, catalog, storage and ownership rules in one place |
| [Workspace strategy](https://docs.databricks.com/aws/en/lakehouse-architecture/deployment-guide/workspace-strategy) | How many workspaces and the only good reasons to split |
| [Well-architected lakehouse](https://docs.databricks.com/aws/en/lakehouse-architecture/well-architected) | Seven pillars, each with a best-practice checklist; use as a design-review rubric |
| [Pipelines best practices](https://docs.databricks.com/aws/en/ldp/best-practices) | ST vs MV choice, splitting ingestion from transformation, parameters |
| [Incremental refresh for MVs](https://docs.databricks.com/aws/en/optimizations/incremental-refresh) | When an MV is actually incremental — the hidden cost driver of MV-heavy designs |
| [What is CDC](https://docs.databricks.com/aws/en/ldp/what-is-change-data-capture) | SCD1 vs SCD2 and change feed vs snapshot, decided properly |
| [Backfill flows](https://docs.databricks.com/aws/en/ldp/flows-backfill) | The supported way to backfill a pipeline without breaking streaming state |
| [Jobs system tables](https://docs.databricks.com/aws/en/admin/system-tables/jobs) | Monitoring and cost-per-run queries plus their caveats |
| [Cost optimization best practices](https://docs.databricks.com/aws/en/lakehouse-architecture/cost-optimization/best-practices) | Tags, policies, job compute — the official FinOps baseline |
| [MLOps workflow](https://docs.databricks.com/aws/en/machine-learning/mlops/mlops-workflow) | "Promote code, not models" and environment separation for ML |
| [Medallion: truth or fiction](https://dataengineeringcentral.substack.com/p/medallion-architecture-truth-or-fiction) | Independent counterweight to three-layers-everywhere [O] |

## 2. Medallion layers

- Bronze = append-only raw as landed (strings/VARIANT/binary + provenance columns such as
  `_metadata.file_path`, ingest time). Keeps history for reprocessing and audit; analysts don't
  query it. [D]
- Never write silver straight from ingestion; read bronze as a stream (batch reads only for small
  dimensions). [D]
- Silver = at least one validated, non-aggregated row per record: dedupe, casts, late data,
  conformed joins. CDC is applied here (bronze holds the change events, silver the current or SCD2
  state). [D] / [S]
- Gold = per consumer, aggregated; several gold sets per domain are fine; no copying large history
  into gold. [D]
- The three layers are "a recommended best practice but not a requirement". [D] Skip gold when
  consumers read silver facts directly; skip a separate silver when bronze is already clean typed
  CDC from Lakeflow Connect (its streaming tables are effectively silver). [O]/[S]
- Ingestion cadence is a cost/latency dial: continuous (most expensive) > triggered/available-now
  > manual batch. [D]
- Snowflake mapping: bronze ≈ raw landing schema, silver ≈ staging/intermediate dbt models, gold ≈
  marts. Same discipline, different storage. [S]

## 3. Workspaces, catalogs, schemas

- One metastore per region holds dev, staging and prod; metastores are not isolation units. [D]
- Workspaces: small team starts with dev + prod; growing team adds staging that is "functionally
  representative of production". Never a workspace per team or project — isolate with catalogs.
  Don't exceed 50–100 workspaces without strong justification; AWS default limit 10 (Premium) /
  50 (Enterprise). Split only for data-protection, business-unit, platform-needs, SDLC, region or
  limit reasons. [D]
- Catalogs: separate dev / staging / prod catalogs [D developer page]; the governance pillar
  recommends a catalog per business domain [D]. Reconcile as `<env>_<domain>` (`prod_ml`,
  `dev_sales`) — UC best practices allow "environment scope, team, business unit, or some
  combination". [S]
- Managed storage at catalog level on a dedicated bucket nothing outside UC can reach; never reuse
  the DBFS root. [D]
- Bind the prod catalog `ISOLATED` to the prod workspace (default `OPEN` exposes every catalog to
  every attached workspace); bindings can be read-only, and external locations / credentials can be
  bound too. Give dev workspaces a read-only binding to prod if scientists need real data. [D]
- Personal schemas in non-prod catalogs (`dev_ml.${user}`). [D]
- Prod catalogs/schemas owned by groups; only service principals get `MODIFY` in prod. End users
  get volumes, not `READ FILES` on external locations. [D]
- New workspaces created after 30 Sep 2026 are UC-only (no DBFS root/mounts, no Hive metastore,
  no DBR < 13.3). [D, uc-only-migration page]

## 4. Pipelines vs jobs; ST vs MV vs MERGE

| Choose | When | Why |
|---|---|---|
| Lakeflow declarative pipeline | Logic fits SQL/declarative tables; ingestion, CDC, medallion transforms | Orchestration, retries, expectations, incremental state and compute come built in [D] |
| Lakeflow Job + notebook/wheel | Fine-grained control, complex procedural rules, external APIs, ML training, manual tuning | Pipelines restrict what you can do inside a flow [D] |
| Jobs as the outer DAG | Always | One place for dependencies across pipelines, notebooks, SQL, dbt [D] |
| Streaming table | Ingestion and append-only/event data; each input row processed once | Exactly-once incremental append [D] |
| Materialized view | Joins/aggregations whose inputs update or delete | Correct under change; incremental only on serverless with row tracking + DVs + CDF on sources, otherwise full recompute [D] |
| MERGE in a job (`foreachBatch` or batch) | Logic AUTO CDC can't express; multi-table transactional writes | Full control; you own idempotency [D]/[S] |

- Never build an MV over a source that can only be read once (Kafka, Auto Loader): every MV source
  must survive a full refresh. Land to a streaming table first. [D]
- Separate pipelines for ingestion (bronze) and transformation (silver/gold): independent schedules,
  failure domains and full refreshes. [D]
- Pass catalog/schema as pipeline parameters (GA 12 Oct 2026), never hardcode. [D]
- Deleting a UC pipeline now keeps its tables unless `cascade=true` (25 Sep 2026). [D]
- Sub-second latency: Real-Time Mode (Structured Streaming / pipelines; Public Preview since 27 May
  2026) needs dedicated compute with task slots ≥ tasks in all stages — budget for it. [D]

## 5. Idempotency, re-runs and backfills

- Batch rewrites: `REPLACE WHERE` (atomic; fails if a row falls outside the predicate) or
  `REPLACE USING`; dynamic partition overwrite is "not recommended for new workloads". An empty
  source under `REPLACE` can delete rows — guard with a row-count expectation. [D]
- `foreachBatch` is at-least-once: make the MERGE idempotent (dedupe + sequence guard), and use
  `txnAppId`/`txnVersion` for multi-table writes; a new checkpoint needs a new `txnAppId`. [D]
- One checkpoint directory per stream, in a volume; `Trigger.AvailableNow` for scheduled streams
  (with `Once`, the only triggers on serverless); restart on failure; task retries "on failure". [D]
- Pipeline backfill: an `append once` flow into bronze. It re-runs on full refresh, so downstream
  must tolerate duplicates. One-time `AUTO CDC FROM SNAPSHOT` seeds SCD1 from an authoritative
  snapshot. [D]
- Job backfills inject `{{backfill.iso_datetime}}` into date parameters; ≤100 runs; always the
  whole job; pipeline tasks are not parameterised by it — write date-ranged code. [D]
- Protect bronze streaming tables from full refresh: `pipelines.reset.allowed = false`. [D, see
  pipelines-cdc.md]

## 6. CDC and SCD

- SCD1 when only current values matter (keeps downstream MVs incrementally refreshable); SCD2 for
  audit, point-in-time reporting, feature backfills. [D] For a feature store, SCD2 dimensions give
  point-in-time joins for free. [S]
- `AUTO CDC` for a change feed (Debezium, Lakeflow Connect, Delta CDF); `AUTO CDC FROM SNAPSHOT`
  for full dumps. Snapshot + change feed together: SCD1 only, triggered, one snapshot flow. [D]
- Sequencing column: sortable, increasing, never NULL; break ties with a STRUCT (`ts_ms`, LSN). [D]
- Deletes: `APPLY AS DELETE WHEN` (SCD1 removes, SCD2 closes the version); `TRACK HISTORY ...
  EXCEPT` stops noisy columns opening versions. [D]
- Read downstream of a CDC target through its change feed, not by rescanning. [D]
- Log-based (gateway / integrated pipeline / Debezium) beats query-based when you need deletes;
  query-based connectors miss hard deletes. [D, glossary]

## 7. Data quality

- Expectations: warn (default; keep + metric), drop, fail (stops update, no metrics). Fail only on
  invariants whose violation makes output wrong (PK nulls); drop + quarantine for bad records. [D]
- Quarantine: flag `is_quarantined`, split valid/invalid via views; keep rules in a Delta table to
  reuse across pipelines. [D]
- Expectations don't block downstream tables. To gate, validate in its own pipeline and make the
  downstream job task depend on it. [D]
- Table-level freshness/completeness: anomaly detection per schema (Public Preview) — catches the
  "pipeline succeeded but wrote nothing" case expectations miss. [D]

## 8. CI/CD and environments (Declarative Automation Bundles)

- Bundles are the recommended CI/CD path; Terraform only for account/workspace/network resources. [D]
- Separate deploy SP (minimal data access) from per-job run-as SPs; OIDC workload identity
  federation, no long-lived secrets. [D]
- `mode: production` refuses deploys from a non-matching branch, blocks dev-mode pipelines and
  cluster overrides, requires explicit `run_as`/permissions; `mode: development` prefixes names
  per user and pauses schedules. [D]
- Three test layers: pytest unit tests on every PR → `bundle validate` + deploy to non-prod →
  staging integration tests with data assertions; promote when main and staging pass. [D]
- Pipeline unit testing is Beta (26 Jul 2026; DBR 18.1+, triggered, Python, mock data in a temp
  schema) and runs from the Pipelines Editor — keep transforms as pure functions so pytest covers
  them in CI. [D] / [S]
- Git folders don't version job/pipeline config; use them for dev only. [D]
- Shared Serverless for Asset Bundles (Beta, 22 Oct 2026): notebooks/files in one bundle share
  compute and a `pyproject.toml` environment. [D]

## 9. Multi-team self-serve platform

- Governance: hybrid — central control of sensitive data and the platform, federated domain
  ownership of data products. [D]
- Ownership: groups own catalogs/schemas/tables; SPs run prod; pipelines can now run as a group
  (5 Oct 2026) so a team owns them without a personal identity. [D]
- Attribution: compute policies with required tags on classic; serverless usage policies (Public
  Preview) for serverless — they attribute, they don't cap; budgets (GA 6 Jul 2026, ACLs 16 Oct)
  alert, they don't stop. [D]
- Guardrails: per-team compute policies, no unrestricted cluster creation, serverless compute
  access control (GA 3 Aug 2026), query tags on warehouses (GA 30 Sep 2026). [D]
- Golden paths: bundle templates (`databricks bundle init` with a custom template) per workload
  type, so a new pipeline or model is a PR. [S]
- Default compute: serverless for ad hoc and bursty work; classic jobs compute for steady,
  long-running batch where measured cost per run favours it (see compute-jobs-cost.md §7). [D]/[S]

## 10. Feature platform

- Offline = UC Delta tables with PK (+ `TIMESERIES`); online = Lakebase. "Databricks recommends
  Feature Views for new use cases." [D]
- Time-series feature tables whenever values change over time; ≤2 PK columns; liquid clustering on
  (key, ts). [D]
- Freshness SLA per feature tier decides the trigger: daily cron (batch), `TableTrigger` (minutes),
  `StreamingMode` (~200 ms p99). Cost rises steeply along that line; default to the slowest tier
  the model tolerates. [D]/[S]
- Skew: log models with `fe.log_model` so serving looks features up itself; callers pass keys.
  Databricks claims this "eliminates" skew [V]; verify with inference-table profiles.
- Promote code, not models or tables; scientists have no write/compute in prod. MLOps Stacks
  templates dev/staging/prod with bundles. [D]
- Naming/ownership at ~1,000 features: no official convention exists; see feature-store.md §9. [S]

## 11. Observability

- System tables are free to read (you pay compute); free retention is per table (audit 365 days;
  enabling configurable retention, Beta 9 Sep 2026, makes it 395 days for supported tables).
  `system.access.audit` is Public Preview. Core set: `system.billing.usage`, `system.lakeflow.*`,
  `system.query.history` (GA 21 Sep 2026), `system.access.table_lineage`/`column_lineage`,
  `system.data_quality_monitoring.table_results`. [D]
- `system.lakeflow` tables are regional, lag ~1 h, and `jobs`/`job_tasks`/`pipelines` are SCD2 —
  take the latest row per id. Runs longer than 1 h are split into hourly rows. Cost per run is
  exact on job compute and serverless, approximate on all-purpose. [D]
- Alerts: SQL alerts on system tables (SLA breaches from `job_run_timeline`), job notifications to
  PagerDuty/Opsgenie via webhooks, budget alerts, anomaly-detection alerts. [D]
- Lineage before any drop or rename; register external lineage (Kafka, BI) so the graph is whole
  (external lineage GA 8 Jun 2026). [D]

## 12. Sources

- https://docs.databricks.com/aws/en/lakehouse/medallion
- https://docs.databricks.com/aws/en/data-governance/unity-catalog/best-practices
- https://docs.databricks.com/aws/en/lakehouse-architecture/well-architected
- https://docs.databricks.com/aws/en/lakehouse-architecture/data-governance/best-practices
- https://docs.databricks.com/aws/en/lakehouse-architecture/operational-excellence/best-practices
- https://docs.databricks.com/aws/en/lakehouse-architecture/cost-optimization/best-practices
- https://docs.databricks.com/aws/en/lakehouse-architecture/deployment-guide/workspace-strategy
- https://docs.databricks.com/aws/en/lakehouse-architecture/deployment-guide/compute
- https://docs.databricks.com/aws/en/developers/best-practices
- https://docs.databricks.com/aws/en/dev-tools/ci-cd/
- https://docs.databricks.com/aws/en/dev-tools/bundles/deployment-modes
- https://docs.databricks.com/aws/en/data-governance/unity-catalog/access-control/workspace-catalog-binding
- https://docs.databricks.com/aws/en/data-governance/unity-catalog/upgrade/uc-only-migration
- https://docs.databricks.com/aws/en/ldp/best-practices
- https://docs.databricks.com/aws/en/ldp/cdc
- https://docs.databricks.com/aws/en/ldp/what-is-change-data-capture
- https://docs.databricks.com/aws/en/ldp/expectations
- https://docs.databricks.com/aws/en/ldp/expectation-patterns
- https://docs.databricks.com/aws/en/ldp/flows-backfill
- https://docs.databricks.com/aws/en/ldp/unit-testing
- https://docs.databricks.com/aws/en/ldp/parameters
- https://docs.databricks.com/aws/en/data-engineering/procedural-vs-declarative
- https://docs.databricks.com/aws/en/optimizations/incremental-refresh
- https://docs.databricks.com/aws/en/delta/selective-overwrite
- https://docs.databricks.com/aws/en/structured-streaming/production
- https://docs.databricks.com/aws/en/structured-streaming/delta-lake
- https://docs.databricks.com/aws/en/structured-streaming/real-time
- https://docs.databricks.com/aws/en/jobs/backfill-jobs
- https://docs.databricks.com/aws/en/admin/system-tables/
- https://docs.databricks.com/aws/en/admin/system-tables/jobs
- https://docs.databricks.com/aws/en/admin/usage/budget-policies
- https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-quality-monitoring/anomaly-detection/
- https://docs.databricks.com/aws/en/machine-learning/feature-store/concepts
- https://docs.databricks.com/aws/en/machine-learning/feature-store/time-series
- https://docs.databricks.com/aws/en/machine-learning/mlops/mlops-workflow
- https://docs.databricks.com/aws/en/machine-learning/mlops/mlops-stacks
- Release notes Jun–Oct 2026: https://docs.databricks.com/aws/en/release-notes/product/2026/june , .../july , .../august , .../september , .../october
- Big Book of Data Engineering (vendor ebook): https://www.databricks.com/resources/ebook/big-book-of-data-engineering
- Data mesh on Databricks (vendor, 2022; names dated): https://www.databricks.com/blog/2022/10/19/building-data-mesh-based-databricks-lakehouse-part-2.html
- Medallion counterpoint [O]: https://dataengineeringcentral.substack.com/p/medallion-architecture-truth-or-fiction
