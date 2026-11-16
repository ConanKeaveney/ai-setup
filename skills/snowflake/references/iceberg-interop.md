# Snowflake ↔ Iceberg lakehouse interop

For Iceberg format internals (snapshots, delete files, maintenance procedures, v3) load the `iceberg` skill; this file is the Snowflake side.

## The objects

| Object | What it holds | Notes |
|---|---|---|
| **External volume** | Account-level pointer to S3/GCS/Azure location(s) plus the IAM role Snowflake assumes | One volume serves many tables. `ALLOW_WRITES = TRUE` needed for Snowflake-managed tables. `EXTERNAL_VOLUME = 'SNOWFLAKE_MANAGED'` stores the files in Snowflake storage instead |
| **Catalog integration** | How to find table metadata when Snowflake is *not* the catalog | `CATALOG_SOURCE = ICEBERG_REST` (Polaris/Open Catalog, Unity Catalog, Glue REST, S3 Tables, any REST), `OBJECT_STORE` (point at metadata files), legacy `GLUE` |
| **Iceberg table** | Snowflake table object over Iceberg metadata + Parquet data | `CATALOG = 'SNOWFLAKE'` → Snowflake-managed; `CATALOG = '<integration>'` → externally managed |
| **Catalog-linked database** | A Snowflake database mirroring a whole remote REST catalog | Auto-discovers namespaces/tables, can create/drop schemas and tables remotely |
| **Horizon Catalog Iceberg REST endpoint** | Snowflake acting as an Iceberg REST catalog for other engines | Spark/Trino/Flink read and write Snowflake-managed Iceberg tables with vended credentials |

## Which table type

| | Snowflake-managed | Externally managed |
|---|---|---|
| Who commits snapshots | Snowflake | External catalog (Spark/Databricks/Glue jobs) |
| Snowflake DML | Full | Writes supported through REST catalogs and catalog-linked DBs; no multi-statement transactions |
| External engine writes | Via Horizon REST endpoint (v2 and v3) | Natively |
| Maintenance (compaction, manifest compaction, snapshot expiry) | Automatic (`ENABLE_DATA_COMPACTION`, default TRUE) | **Yours** — Snowflake doesn't do it |
| Clustering keys | Yes | No |
| Time Travel / Fail-safe | Time Travel yes; Fail-safe only on Snowflake storage | No Fail-safe |
| Freshness in Snowflake | Immediate | `AUTO_REFRESH` polling (default 30 s) or manual `ALTER ICEBERG TABLE … REFRESH` |
| Storage bill | Your cloud account (external volume) or Snowflake (`SNOWFLAKE_MANAGED`) | Your cloud account |

Rule of thumb for a lakehouse where Spark/Databricks own most tables: keep them **externally managed** and expose them to Snowflake through a catalog-linked database; make a table **Snowflake-managed** only when Snowflake is the main writer (e.g. a Snowflake-built mart that Spark also needs to read).

## Setup

External volume (S3):
```sql
CREATE OR REPLACE EXTERNAL VOLUME lake_vol
  STORAGE_LOCATIONS = ((
    NAME = 'lake-eu-west-1'
    STORAGE_PROVIDER = 'S3'
    STORAGE_BASE_URL = 's3://company-lake/iceberg/'
    STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::123456789012:role/snowflake-iceberg'
  ))
  ALLOW_WRITES = TRUE;
DESC EXTERNAL VOLUME lake_vol;   -- read STORAGE_AWS_IAM_USER_ARN and STORAGE_AWS_EXTERNAL_ID into the role's trust policy
SELECT SYSTEM$VERIFY_EXTERNAL_VOLUME('lake_vol');
```

Snowflake-managed table:
```sql
CREATE ICEBERG TABLE mart.daily_revenue (tenant_id NUMBER, day DATE, revenue NUMBER(18,2))
  CATALOG = 'SNOWFLAKE'
  EXTERNAL_VOLUME = 'lake_vol'
  BASE_LOCATION = 'mart/daily_revenue'           -- immutable after create
  STORAGE_SERIALIZATION_POLICY = COMPATIBLE      -- default OPTIMIZED is best for Snowflake only
  ICEBERG_VERSION = 2;                           -- 2 (default) or 3
```

Glue via Iceberg REST (read and write):
```sql
CREATE CATALOG INTEGRATION glue_rest
  CATALOG_SOURCE = ICEBERG_REST
  TABLE_FORMAT = ICEBERG
  CATALOG_NAMESPACE = 'analytics'
  REST_CONFIG = (
    CATALOG_URI = 'https://glue.eu-west-1.amazonaws.com/iceberg'
    CATALOG_API_TYPE = AWS_GLUE
    CATALOG_NAME = '123456789012'                -- AWS account id
  )
  REST_AUTHENTICATION = (
    TYPE = SIGV4
    SIGV4_IAM_ROLE = 'arn:aws:iam::123456789012:role/snowflake-glue'
    SIGV4_SIGNING_REGION = 'eu-west-1'
  )
  ENABLED = TRUE;
```

Databricks Unity Catalog via its Iceberg REST API:
```sql
CREATE CATALOG INTEGRATION unity_rest
  CATALOG_SOURCE = ICEBERG_REST
  TABLE_FORMAT = ICEBERG
  CATALOG_NAMESPACE = 'default'
  REST_CONFIG = (
    CATALOG_URI = 'https://<workspace-host>/api/2.1/unity-catalog/iceberg-rest'   -- check current Databricks path
    CATALOG_NAME = '<uc_catalog>'
    ACCESS_DELEGATION_MODE = VENDED_CREDENTIALS
  )
  REST_AUTHENTICATION = (
    TYPE = OAUTH
    OAUTH_TOKEN_URI = 'https://<workspace-host>/oidc/v1/token'               -- check current Databricks path
    OAUTH_CLIENT_ID = '<sp-client-id>'
    OAUTH_CLIENT_SECRET = '<secret>'
    OAUTH_ALLOWED_SCOPES = ('all-apis')
  )
  ENABLED = TRUE;
```
(Snowflake's documented Unity example uses `TYPE = BEARER` with a PAT and `CATALOG_API_TYPE = PRIVATE` for a private endpoint; prefer a service principal with OAuth for production.)

One table from a catalog:
```sql
CREATE ICEBERG TABLE lake.orders
  EXTERNAL_VOLUME = 'lake_vol'                   -- omit when using VENDED_CREDENTIALS
  CATALOG = 'glue_rest'
  CATALOG_TABLE_NAME = 'orders'
  CATALOG_NAMESPACE = 'analytics'
  AUTO_REFRESH = TRUE;
ALTER ICEBERG TABLE lake.orders REFRESH;          -- manual sync
SELECT SYSTEM$GET_ICEBERG_TABLE_INFORMATION('lake.orders');
```

Whole catalog at once:
```sql
CREATE DATABASE lake LINKED_CATALOG = (CATALOG = 'glue_rest');   -- SYNC_INTERVAL_SECONDS default 30
```
Catalog-linked DB limits: Iceberg REST catalogs only; no replication or cloning; remote catalog access policies don't sync (re-apply Snowflake RBAC, masking and tags); discovery and schema/table DDL are billed as cloud services.

## Spark reading/writing Snowflake-managed tables (Horizon REST)

```python
spark = (SparkSession.builder
  .config("spark.sql.catalog.sf", "org.apache.iceberg.spark.SparkCatalog")
  .config("spark.sql.catalog.sf.type", "rest")
  .config("spark.sql.catalog.sf.uri", "https://<account_identifier>.snowflakecomputing.com/polaris/api/catalog")
  .config("spark.sql.catalog.sf.credential", PAT)                    # or key-pair JWT, External OAuth, WIF
  .config("spark.sql.catalog.sf.scope", "session:role:<role>")
  .config("spark.sql.catalog.sf.header.X-Iceberg-Access-Delegation", "vended-credentials")
  .getOrCreate())
```
- Read and write supported for Snowflake-managed Iceberg v2/v3 tables. Not for native Snowflake tables, externally managed tables or remote tables.
- Writes: no `CREATE TABLE … LOCATION`, no CTAS, no equality deletes.
- Snowflake RBAC, masking and row access policies apply to the external engine.
- Billing: 0.5 credits per million API requests as cloud services, starting H2 2026. Spark compute is on your side — this is how you read Snowflake-produced data **without** a Snowflake warehouse.

## Open Catalog / Polaris / Horizon — which one

- **Apache Polaris**: open-source Iceberg REST catalog (originated at Snowflake).
- **Snowflake Open Catalog**: Snowflake-hosted Polaris. Internal catalogs (read/write from any engine) and external catalogs (read-only mirror). **Closed to new customers**; existing ones can keep using it. Request billing 0.5 credits per million, listed as free for a limited period.
- **Horizon Catalog**: Snowflake's built-in governance catalog, now exposing an Iceberg REST endpoint (Polaris-based). Snowflake's recommended path for new multi-engine setups.
- If the lakehouse already standardises on Glue or Unity Catalog, keep that as the source of truth and federate Snowflake into it; don't introduce a second writable catalog for the same tables.

## Cost model for interop

- Queries on any Iceberg table use your warehouse as usual; pruning relies on Iceberg manifest stats, so file layout and compaction (done by Spark for external tables) drive Snowflake cost.
- Auto-refresh of externally managed tables is billed on the Snowpipe line at 1.25× compute (no per-file charge for Iceberg); look for the table name in `PIPE_USAGE_HISTORY.pipe_name`. Many tables × frequent commits = steady serverless spend — turn `AUTO_REFRESH` off for rarely-queried tables and refresh on demand.
- Snowflake-managed tables: compaction and maintenance consume Snowflake credits; storage is billed by your cloud provider when on an external volume.
- Cross-region reads/writes incur egress.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Rows that were deleted in Spark still visible / table unreadable | Writer produced **equality deletes** (common from Flink upserts) — unsupported in Snowflake | Rewrite with position deletes (MoR position deletes v2, deletion vectors v3) or compact deletes away before exposing |
| Snowflake shows stale data | Auto-refresh off or failing; DDL-only schema change (needs manual refresh); or commits outrun the polling interval (`REFRESH_INTERVAL_SECONDS` on the integration) | `SELECT SYSTEM$AUTO_REFRESH_STATUS('<table>')`; on an unrecoverable error disable auto-refresh, `ALTER ICEBERG TABLE … REFRESH`, re-enable; align maintenance and refresh schedules |
| Slow Snowflake scans on lakehouse tables | Thousands of small files / many manifests from streaming writers | Run `rewrite_data_files` / `rewrite_manifests` in Spark; target ~128–512 MB files |
| Spark can't read a Snowflake-written table well | Default `STORAGE_SERIALIZATION_POLICY = OPTIMIZED` | Create with `COMPATIBLE` for shared tables |
| Two systems fighting over files | Both Snowflake (managed table compaction) and Spark expiring snapshots/removing orphans | One owner per table; external engines must never run orphan-file cleanup on Snowflake-managed locations |
| Non-Parquet data files | Iceberg-on-ORC/Avro | Snowflake supports Parquet only |

## When to keep a workload off Snowflake

Customer-facing, high-QPS, per-tenant reads are where per-second warehouse billing hurts most: a multi-cluster warehouse sized for peak concurrency runs whether or not tenants are querying. Patterns that keep Snowflake for what it's good at:
- Snowflake builds the mart (dynamic tables / tasks) into a **Snowflake-managed Iceberg** table; the serving layer (Spark/Trino, an OLAP store, or a cache) reads it via Horizon REST with no Snowflake compute.
- Lakehouse-owned tables stay externally managed; Snowflake gets read access via a catalog-linked database for analysts and internal BI.
- Measure before moving: cost per tenant query from `QUERY_ATTRIBUTION_HISTORY` (by `query_tag` per tenant/app) plus the warehouse's idle share.

Sources: https://docs.snowflake.com/en/user-guide/tables-iceberg · https://docs.snowflake.com/en/sql-reference/sql/create-iceberg-table-snowflake · https://docs.snowflake.com/en/sql-reference/sql/create-iceberg-table-rest · https://docs.snowflake.com/en/sql-reference/sql/create-catalog-integration-rest · https://docs.snowflake.com/en/user-guide/tables-iceberg-configure-catalog-integration-rest-glue · https://docs.snowflake.com/en/sql-reference/sql/create-external-volume · https://docs.snowflake.com/en/user-guide/tables-iceberg-catalog-linked-database · https://docs.snowflake.com/en/user-guide/tables-iceberg-query-using-external-query-engine-snowflake-horizon · https://docs.snowflake.com/en/user-guide/tables-iceberg-manage · https://docs.snowflake.com/en/user-guide/tables-iceberg-auto-refresh · https://docs.snowflake.com/en/user-guide/opencatalog/overview · Service Consumption Table https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf
