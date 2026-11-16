# Unity Catalog and Iceberg interop

UC object model, storage, grants, fine-grained access, volumes, lineage, and every way Iceberg
meets Databricks: managed Iceberg, UniForm / External Iceberg Reads, compatibility mode, the
Iceberg REST catalog, and federating an existing Glue catalog. Iceberg rules and the
read/write matrix are adapted from the official `databricks-iceberg` and
`databricks-unity-catalog` skills (https://github.com/databricks/databricks-agent-skills).

## Contents
1. Object model
2. Storage: credentials, external locations, managed storage
3. Managed vs external vs foreign tables
4. Privileges and grants
5. Fine-grained access
6. Volumes
7. Lineage, audit, tags
8. Iceberg on Databricks
9. External engines via the Iceberg REST catalog
10. Federating Glue / Hive metastore
11. Environment and workspace isolation

## 1. Object model

```
account
 └─ metastore (one per region; attached to workspaces)
     ├─ storage credentials, external locations, connections, service credentials
     └─ catalog  (standard | foreign | shared)
         └─ schema
             ├─ table (managed | external | foreign) · view · materialized view · streaming table
             ├─ volume (managed | external)
             ├─ function (SQL / Python UDF)
             ├─ registered model (+ versions, aliases)
             └─ feature (Feature Views) · stream (Kafka, Feature Views)
```

Always use three-part names. `USE CATALOG x; USE SCHEMA y;` sets defaults per session. Workspace
admins ≠ metastore admins; ownership of securables drives what you can grant.

## 2. Storage

```sql
-- IAM role trusted by Databricks' UC master role + external ID (created in UI/API, then):
CREATE EXTERNAL LOCATION raw_landing
  URL 's3://acme-raw/landing/' WITH (STORAGE CREDENTIAL acme_raw_role);
GRANT READ FILES ON EXTERNAL LOCATION raw_landing TO `ingest-sp`;

CREATE CATALOG prod_ml MANAGED LOCATION 's3://acme-lake-prod/uc/prod_ml/';
```

- Give each catalog (or schema) its own managed location so data is separated per env/domain
  and on your bucket. Workspaces created with **default storage** use Databricks-managed storage;
  some features (credential vending to external engines, streaming Feature Views) do not support
  default storage — prefer your own S3 for a platform team.
- Do not use instance profiles or DBFS mounts for new work; they bypass UC.
- Enable **file events** on external locations used by Auto Loader.

## 3. Table kinds

| Kind | Files owned by | DROP | Maintenance | Use |
|---|---|---|---|---|
| Managed (Delta or Iceberg) | UC | Files deleted after recovery window (default 7 days; `UNDROP`) | Predictive optimization, auto liquid clustering, metadata caching, multi-statement transactions | Default |
| External | You (path under an external location) | Metadata only | Manual OPTIMIZE/VACUUM | Another system must own the path |
| Foreign | Another catalog (Glue, HMS, Snowflake, a database via federation) | n/a | Owner system | Query in place, migration stepping stone |

Convert to managed (convert-to-managed page, Oct 2026) — **Delta sources only**:
- External Delta: `ALTER TABLE c.s.t SET MANAGED;` (DBR 17.3 LTS+ or serverless). Copies without
  reader downtime; writers blocked ~1–5 min per 10 TB (docs estimate). Undo with `UNSET MANAGED`
  within 14 days. Add `TRUNCATE UNIFORM HISTORY` if Iceberg reads are on.
- Foreign Delta (HMS/Glue federation): `SET MANAGED MOVE` (disables the source in Glue; rollback =
  `UNSET MANAGED` then `DROP TABLE` — in that order, or data loss) or `SET MANAGED COPY` (source
  untouched; you own the dual-copy period). DBR 17.3+, `OWNER`/`MANAGE` + `CREATE` on the location.
- Foreign → external UC table: `ALTER TABLE ... SET EXTERNAL` (DBR 17.3+; Delta, Parquet, ORC,
  Avro, JSON, CSV, TEXT), keeps history and path.
- **Foreign Iceberg → managed Iceberg: `DEEP CLONE` only** (DBR 16.4 LTS+). "Zero-copy migration
  from a foreign catalog is not supported"; history is not copied (time travel restarts); no shallow
  clone for Iceberg.

## 4. Privileges

| Privilege | On | Meaning |
|---|---|---|
| `BROWSE` | catalog | See metadata without data access (discovery) |
| `USE CATALOG` / `USE SCHEMA` | catalog / schema | Required to reach anything inside |
| `SELECT` / `MODIFY` | table, schema, catalog | Read / write data |
| `CREATE TABLE`, `CREATE VOLUME`, `CREATE FUNCTION`, `CREATE MODEL` | schema | Create objects |
| `READ VOLUME` / `WRITE VOLUME` | volume | File access |
| `EXECUTE` | function, model | Call UDF / use model |
| `READ FILES` / `WRITE FILES` / `CREATE EXTERNAL TABLE` | external location | Path-level access |
| `EXTERNAL USE SCHEMA` | schema | External engines through IRC / credential vending |
| `MANAGE` | any | Grant/revoke without ownership |
| `ALL PRIVILEGES` | any | Everything except MANAGE/ownership semantics |

Privileges inherit downward (a `SELECT` on a schema covers current and future tables). Grant to
account groups; set owners to groups; jobs `run_as` service principals.

```sql
SHOW GRANTS ON SCHEMA prod_ml.features;
ALTER TABLE prod_ml.features.user_txn_features OWNER TO `ml-platform`;
```

## 5. Fine-grained access

```sql
CREATE FUNCTION gov.policies.region_filter(region STRING)
RETURN is_account_group_member('global-analysts') OR region = 'EU';
ALTER TABLE sales.orders SET ROW FILTER gov.policies.region_filter ON (region);

CREATE FUNCTION gov.policies.mask_email(email STRING)
RETURN CASE WHEN is_account_group_member('pii-readers') THEN email ELSE sha2(email, 256) END;
ALTER TABLE crm.customers ALTER COLUMN email SET MASK gov.policies.mask_email;
```

At scale use governed tags + ABAC policies (attach a mask/filter to every column tagged `pii`)
instead of per-table functions. Row filters/masks block some features (automatic CDF, some sharing
paths); plan for that on feature tables.

UC governance changes Jun–Oct 2026 (release notes): cross-engine ABAC GA 1 Oct (external engines
read ABAC-protected managed tables, enforced by serverless); ABAC on views, DENY policies,
metastore-level policies, time-travel enforcement all Beta (Sep, DBR 19+); identity attributes in
masks Beta (Aug); `READ METADATA` GA 10 Aug; `INSERT`/`UPDATE`/`DELETE` privileges Beta 24 Aug
(DBR 18.1+, narrower than `MODIFY`); `MANAGE` no longer needs `USE CATALOG`/`USE SCHEMA`
(3 Aug — audit existing `MANAGE` grants); secrets in UC GA 3 Aug; external lineage GA 8 Jun;
configurable drop-recovery period Public Preview 15 Jun; governed tag propagation Beta 12 Oct;
Data Classification API GA 14 Oct. New workspaces after 30 Sep 2026 are UC-only (no DBFS root,
mounts, Hive metastore, DBR < 13.3).

## 6. Volumes

`/Volumes/<catalog>/<schema>/<volume>/path`. Managed volumes live in the schema's managed
storage; external volumes map an S3 prefix. Use for landing files, Auto Loader schema/checkpoint
locations, wheels/JARs, ML artifacts. From the CLI, prefix with `dbfs:` (`databricks fs ls
dbfs:/Volumes/...`).

## 7. Lineage, audit, tags

- Lineage captured automatically for UC queries from notebooks, jobs, pipelines, SQL warehouses:
  `system.access.table_lineage`, `system.access.column_lineage`. External lineage (e.g. upstream
  Kafka or downstream BI) can be registered via the external lineage API.
- Audit: `system.access.audit` (who read/granted/dropped what).
- Tags and comments on catalogs/schemas/tables/columns drive search, data classification and ABAC.

```sql
SELECT source_table_full_name, target_table_full_name, entity_type, event_time
FROM system.access.table_lineage
WHERE target_table_full_name = 'prod_ml.features.user_txn_features'
ORDER BY event_time DESC LIMIT 50;
```

## 8. Iceberg on Databricks

Status: managed Iceberg tables, foreign Iceberg tables and Iceberg v3 (deletion vectors, VARIANT,
row lineage) **GA 21 May 2026**; sharing managed Iceberg GA 14 Aug; multi-statement transactions
over managed Delta *and* Iceberg GA 14 Oct (`BEGIN ATOMIC ... END;`, needs catalog commits);
managed Iceberg MVs Public Preview 7 Jul (account team); auto TTL row deletion GA 12 Jun.

Hard rules:
- Requires UC, **DBR 16.4 LTS+**, and serverless for metadata maintenance with network access to
  the bucket. **Predictive optimization must be enabled** to create a managed Iceberg table (Iceberg
  page, 27 Oct 2026). Do not install an Iceberg library on DBR (built in).
- External writers to managed tables: v2 **position and equality deletes are not supported**; v3
  row-level changes must be copy-on-write or deletion vectors. EMR/Flink jobs writing merge-on-read
  v2 must switch to CoW (or v3 DVs) before UC owns the table. Recommended client: Iceberg ≥1.9.2.
- Partition evolution on managed tables only via external engines, not Databricks SQL; no
  `BINARY` partition columns; zstd only (codec cannot be changed).
- Do not set `write.metadata.path` / `write.metadata.previous-versions-max`.
- Managed Iceberg `PARTITIONED BY` accepts plain columns only — no `bucket()`, `days()` etc.
  transforms. UC maps `PARTITIONED BY` or `CLUSTER BY` to Iceberg partition fields that external
  engines can prune on, and to liquid clustering internally.
- `CLUSTER BY` on Iceberg **v2** needs `'delta.enableDeletionVectors'=false,
  'delta.enableRowTracking'=false`; v3 and `PARTITIONED BY` handle this automatically.
- Managed Iceberg uses zstd Parquet by default; old readers may need snappy.
- No `SHALLOW CLONE` for Iceberg; use `DEEP CLONE` or CTAS.

```sql
CREATE TABLE prod.events.clicks USING ICEBERG PARTITIONED BY (event_date)
AS SELECT * FROM raw.events.clicks_src;

CREATE TABLE prod.events.clicks_v3 USING ICEBERG
TBLPROPERTIES ('format-version' = '3') CLUSTER BY (event_date, user_id)
AS SELECT * FROM raw.events.clicks_src;

-- Delta table readable as Iceberg (UniForm / "External Iceberg Reads")
ALTER TABLE prod.sales.orders SET TBLPROPERTIES (
  'delta.columnMapping.mode' = 'name',
  'delta.enableIcebergCompatV2' = 'true',
  'delta.universalFormat.enabledFormats' = 'iceberg');

-- Streaming table / MV readable as Iceberg: compatibility mode (writes a separate copy)
CREATE OR REFRESH STREAMING TABLE events_st
TBLPROPERTIES ('delta.universalFormat.enabledFormats' = 'compatibility',
               'delta.universalFormat.compatibility.location' = 's3://acme-iceberg-compat/events_st/')
AS SELECT * FROM STREAM read_files('/Volumes/raw/events/landing/');
```

| | Managed Iceberg | Delta + UniForm | Delta + compatibility mode |
|---|---|---|---|
| Databricks read/write | Yes / Yes | Yes / Yes (as Delta) | Yes / Yes |
| External read via IRC | Yes | Yes (as Iceberg) | Yes (copy) |
| External **write** via IRC | **Yes** | No via IRC; external Spark can write managed Delta via the Unity REST API (GA 13 Oct 2026, catalog commits required) | No |
| CDF | No on v2 (automatic CDF covers v3 on DBR 19+) | Yes | Yes |
| STs / MVs | MVs Public Preview (7 Jul 2026) | No | Yes |
| Deletion vectors | v3 only | Must be off for UniForm v2 | — |
| Min DBR | **16.4 LTS** (Iceberg docs; *corrected* — earlier text said 16.1 from the official skill) | 14.3 | 16.1 (official skill; not re-checked) |

Choose: managed Iceberg when external engines must write; UniForm when Databricks is the only
writer and you want Delta features; compatibility mode for pipeline outputs. UniForm metadata
generation is asynchronous — external readers lag slightly; check `DESCRIBE EXTENDED`.
Iceberg v3 (deletion vectors, VARIANT, row lineage) needs Iceberg ≥1.9 on external readers.
Snowflake catalog integration sees only the last 1000 Iceberg commits — compact high-frequency
writers.

## 9. External engines via the Iceberg REST catalog

Endpoint: `https://<workspace-host>/api/2.1/unity-catalog/iceberg-rest` (the older
`/api/2.1/unity-catalog/iceberg` read-only endpoint is in maintenance mode). Needs
`EXTERNAL USE SCHEMA` plus normal data grants; credential vending gives the engine short-lived
S3 credentials (not on default storage). Use OAuth M2M with a service principal.

OSS Spark / EMR:

```python
spark = (SparkSession.builder
  .config("spark.jars.packages",
          "org.apache.iceberg:iceberg-spark-runtime-3.5_2.12:<ver>,org.apache.iceberg:iceberg-aws-bundle:<ver>")
  .config("spark.sql.extensions", "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions")
  .config("spark.sql.catalog.uc", "org.apache.iceberg.spark.SparkCatalog")
  .config("spark.sql.catalog.uc.type", "rest")
  .config("spark.sql.catalog.uc.uri", f"{HOST}/api/2.1/unity-catalog/iceberg-rest")
  .config("spark.sql.catalog.uc.rest.auth.type", "oauth2")
  .config("spark.sql.catalog.uc.oauth2-server-uri", f"{HOST}/oidc/v1/token")
  .config("spark.sql.catalog.uc.credential", f"{CLIENT_ID}:{CLIENT_SECRET}")
  .config("spark.sql.catalog.uc.scope", "all-apis")
  .config("spark.sql.catalog.uc.warehouse", "prod")          # UC catalog name
  .getOrCreate())
spark.sql("SELECT * FROM uc.events.clicks LIMIT 10")
```

PyIceberg, Trino, Flink and Snowflake connect to the same endpoint with equivalent settings.

## 10. Federating Glue / Hive metastore

- **Hive metastore federation** (incl. AWS Glue): create a UC connection to Glue → a **foreign
  catalog** that mirrors Glue databases/tables; tables are discovered automatically; UC grants
  apply; workloads run in HMS-compatibility mode. Then convert per §3: Delta in place with
  `SET MANAGED MOVE|COPY` (keeps history); **Iceberg only by `DEEP CLONE`** (history lost). An
  all-Iceberg Glue estate therefore pays one full copy per table to reach managed Iceberg.
- Glue federation specifics (hms-federation-glue page): needs a self-assuming IAM role + service
  credential; compute in standard access mode on DBR 13.3/14.3/15.1+; **Iceberg tables read only if
  the foreign catalog has its own `storage_root`** (`ALTER CATALOG c SET MANAGED LOCATION ...`,
  then `REFRESH FOREIGN CATALOG`); only tables under the catalog's *authorized paths* are
  queryable. **Lake Formation permissions on the service credential must stay continuously
  granted** — a lapse can drop and recreate schemas and wipe schema-level grants; never
  revoke-then-grant. Serverless reaches the public Glue endpoint; classic should use PrivateLink.
- Foreign Iceberg tables are read-only in Databricks; time travel only to snapshots Databricks has
  already read; bucket transforms can slow conditional filters (Iceberg page).
- **Catalog federation** covers Iceberg tables in Glue, HMS or Snowflake Horizon as read-only
  foreign Iceberg tables.
- Federation lets you migrate team by team: existing EMR jobs keep writing to Glue while
  Databricks reads; cut a table over once all writers have moved.

## 11. Environment and workspace isolation

- Catalog per environment (`dev_*`, `staging_*`, `prod_*`) or per domain+env; bind catalogs to
  workspaces (workspace-catalog binding) so a dev workspace cannot see or write prod.
- Prod writes only by service principals from CI-deployed bundles; humans read-only in prod.
- Delta Sharing for cross-account/cross-org consumers instead of copying.

## Sources
- https://github.com/databricks/databricks-agent-skills — `skills/databricks-iceberg` (SKILL.md, references 2, 3, 5), `skills/databricks-unity-catalog` (adapted)
- https://docs.databricks.com/aws/en/tables/managed
- https://docs.databricks.com/aws/en/iceberg/
- https://docs.databricks.com/external-access/iceberg
- https://docs.databricks.com/external-access/compatibility-mode
- https://docs.databricks.com/aws/en/query-federation/hms-federation-glue
- https://docs.databricks.com/aws/en/query-federation/hms-federation-concepts
- https://docs.databricks.com/aws/en/query-federation/catalog-federation
- https://docs.databricks.com/aws/en/delta/deletion-vectors
- https://docs.databricks.com/aws/en/tables/convert-to-managed
- https://docs.databricks.com/aws/en/tables/convert-foreign-external
- https://docs.databricks.com/aws/en/iceberg/clone
- https://docs.databricks.com/aws/en/transactions/
- https://docs.databricks.com/aws/en/external-access/unity-rest
- https://docs.databricks.com/aws/en/external-access/cross-engine-abac
- https://docs.databricks.com/aws/en/data-governance/unity-catalog/upgrade/uc-only-migration
- Release notes: https://docs.databricks.com/aws/en/release-notes/product/2026/may (Iceberg GA 21 May) , .../june , .../july , .../august , .../september , .../october
