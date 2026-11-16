# Catalogs and interop: AWS (Glue, S3 Tables), REST, Databricks, Snowflake

Vendor features move fast. Every vendor claim below carries the date or doc it came from; re-check before committing to a design. Facts gathered 1 Oct 2026.

## How to choose

1. **One writer-catalog per table.** Every commit must go through the same catalog, or commits race and history forks. Other platforms read through federation, a REST endpoint, or a read-only "foreign/externally managed" table.
2. **Prefer REST-speaking catalogs** for anything multi-engine: Glue's Iceberg REST endpoint, S3 Tables REST, Unity Catalog IRC, Polaris/Horizon. REST gives credential vending (no long-lived S3 keys in engines), server-side commit validation and, from Iceberg 1.11, remote scan planning.
3. **Match maintenance to the catalog owner.** Glue optimizers, S3 Tables maintenance, Databricks predictive optimization and Snowflake-managed tables all maintain their own tables; do not also run Spark maintenance on them.
4. **Check v3 support per engine** before `format-version=3` (matrix below).

## Spark catalog configurations

Common to all: `spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions` (Spark 3.x), `spark.sql.catalog.<cat>=org.apache.iceberg.spark.SparkCatalog`. Package the runtime matching Spark/Scala (`iceberg-spark-runtime-3.5_2.12`, `-4.0_2.13`, `-4.1_2.13`) plus `org.apache.iceberg:iceberg-aws-bundle` for S3FileIO/Glue/SigV4.

```properties
# A. Glue Data Catalog via GlueCatalog (classic)
spark.sql.catalog.glue=org.apache.iceberg.spark.SparkCatalog
spark.sql.catalog.glue.type=glue                                   # = catalog-impl org.apache.iceberg.aws.glue.GlueCatalog
spark.sql.catalog.glue.warehouse=s3://my-lake/warehouse/
spark.sql.catalog.glue.io-impl=org.apache.iceberg.aws.s3.S3FileIO
# spark.sql.catalog.glue.glue.id=<other-account-id>                # cross-account catalog

# B. Glue Data Catalog via the Glue Iceberg REST endpoint
spark.sql.catalog.gluerest.type=rest
spark.sql.catalog.gluerest.uri=https://glue.<region>.amazonaws.com/iceberg
spark.sql.catalog.gluerest.warehouse=<account-id>                  # S3 Tables: <account-id>:s3tablescatalog/<table-bucket>
spark.sql.catalog.gluerest.rest.sigv4-enabled=true
spark.sql.catalog.gluerest.rest.signing-name=glue
spark.sql.catalog.gluerest.rest.signing-region=<region>

# C. S3 Tables via its own REST endpoint (single table bucket, basic access)
spark.sql.catalog.s3t.type=rest
spark.sql.catalog.s3t.uri=https://s3tables.<region>.amazonaws.com/iceberg
spark.sql.catalog.s3t.warehouse=arn:aws:s3tables:<region>:<account-id>:bucket/<bucket>
spark.sql.catalog.s3t.rest.sigv4-enabled=true
spark.sql.catalog.s3t.rest.signing-name=s3tables
spark.sql.catalog.s3t.rest.signing-region=<region>
spark.sql.catalog.s3t.io-impl=org.apache.iceberg.aws.s3.S3FileIO

# D. S3 Tables via the AWS Labs client catalog (jar software.amazon.s3tables:s3-tables-catalog-for-iceberg-runtime)
spark.sql.catalog.s3t.catalog-impl=software.amazon.s3tables.iceberg.S3TablesCatalog
spark.sql.catalog.s3t.warehouse=arn:aws:s3tables:<region>:<account-id>:bucket/<bucket>

# E. Databricks Unity Catalog Iceberg REST (IRC)
spark.sql.catalog.uc.type=rest
spark.sql.catalog.uc.uri=https://<workspace-host>/api/2.1/unity-catalog/iceberg-rest
spark.sql.catalog.uc.warehouse=<uc-catalog-name>
spark.sql.catalog.uc.token=<PAT>                                   # or rest.auth.type=oauth2 + client credentials
spark.sql.catalog.uc.header.X-Iceberg-Access-Delegation=vended-credentials

# F. Snowflake Horizon Catalog (Snowflake-managed Iceberg tables)
spark.sql.catalog.sf.type=rest
spark.sql.catalog.sf.uri=https://<account_identifier>.snowflakecomputing.com/polaris/api/catalog
spark.sql.catalog.sf.warehouse=<snowflake-database>
spark.sql.catalog.sf.credential=<PAT>
spark.sql.catalog.sf.scope=session:role:<role>
spark.sql.catalog.sf.header.X-Iceberg-Access-Delegation=vended-credentials

# G. Hive Metastore / Nessie / JDBC
spark.sql.catalog.hms.type=hive          # .uri=thrift://host:9083
spark.sql.catalog.nessie.type=nessie     # .uri=http://nessie:19120/api/v2, .ref=main
spark.sql.catalog.jdbc.type=jdbc         # .uri=jdbc:postgresql://..., tests only
```

Other useful catalog properties: `cache-enabled` (true) and `cache.expiration-interval-ms` (30 s) - stale reads within a long-lived session come from here; `table-default.<prop>` / `table-override.<prop>`; `default-namespace`.

`SparkSessionCatalog` wraps `spark_catalog` so Hive/Spark tables and Iceberg tables share one metastore - useful during migration, but catalog-scoped `system.*` functions do not work through it before Spark 4.2.

## AWS

### Glue Data Catalog (`GlueCatalog`)

- Iceberg namespace = Glue database; table = Glue table; every commit = Glue TableVersion. Commits use Glue **optimistic locking** on the table version id (AWS SDK 2.17.131+; older SDKs need the DynamoDB lock manager).
- `glue.skip-archive` defaults to **true** - keep it, or streaming tables create a Glue table version per commit and hit quotas.
- Lake Formation can govern Iceberg tables and vend credentials to external engines ("allow external engines ... full table access" in Application integration settings).
- **Glue table optimizers** (managed, per table or per catalog): compaction (binpack, sort, z-order), snapshot retention, orphan file deletion. Limits from the AWS notes page: tables must not share an S3 location (orphan deletion on one deletes the other's files); S3 lifecycle expiration rules on table paths can delete live files; set `orphanFileRetentionPeriodInDays` above your longest commit delay; at most 1,000,000 files deleted per run (the rest stay as orphans); compaction suspends after 4 consecutive failures; no compaction on cross-account/cross-Region tables, resource links or S3 Express One Zone; z-order does not support decimal or timestamp-without-zone columns; only SSE-S3/SSE-KMS. Branch/tag retention takes precedence over optimizer settings.

### Amazon S3 Tables

- Table buckets with built-in Iceberg tables; accessed via the S3 Tables REST endpoint, the Glue REST endpoint (after integrating table buckets with the Glue Data Catalog / Lake Formation), or the AWS Labs client catalog.
- **Managed maintenance is on by default**: compaction (target 512 MB, configurable 64-512 MB; strategies `auto` (default), `binpack`, `sort`, `z-order` - sort/z-order need a sort order in the table metadata), snapshot management (`minSnapshotsToKeep` 1, `maxSnapshotAgeHours` 120), and unreferenced file removal. Configure with `aws s3tables put-table-maintenance-configuration --type icebergCompaction|icebergSnapshotManagement`.
- **Snapshot management fails for the whole table** if any user-defined branch or tag exists, or if `history.expire.max-snapshot-age-ms` / `history.expire.min-snapshots-to-keep` are set as table properties. Diagnose with `aws s3tables get-table-maintenance-job-status`.
- Expired-snapshot files become noncurrent and are permanently deleted after `NoncurrentDays`; recovery only via AWS Support.
- S3 Tables REST endpoint limits: no `stage-create` (so no CTAS through it), drops must be `purge=true` (some Spark versions send false - use `DROP TABLE ... PURGE` or the DeleteTable API), single-level namespaces only, no OAuth, no view APIs, metadata.json over 50 MB rejected. AWS recommends the Glue REST endpoint for anything beyond basic single-bucket access.
- v3: deletion vectors and row lineage since Nov 2025; all v3 types (variant, timestamp_ns, geometry, geography, unknown) announced 30 Sep 2026, Parquet only, needing Spark 4.0+ engines (Glue 6.0+, EMR 8.1+); those types cannot be in a compaction sort order.

### S3FileIO and layout

- Use `org.apache.iceberg.aws.s3.S3FileIO` (default for GlueCatalog), not Hadoop S3A. It reads `s3a://`/`s3n://` paths written earlier.
- `write.object-storage.enabled=true` adds a 20-bit hash directory prefix after `write.data.path` to spread S3 request load (avoids 503 SlowDown); `write.object-storage.partitioned-paths=false` drops partition values from keys.
- Useful catalog props: `s3.sse.type` (`none|s3|kms|dsse-kms|custom`) + `s3.sse.key`; `s3.checksum-enabled`; `s3.write.tags.*`; `s3.delete-enabled=false` + `s3.delete.tags.*` to tag instead of delete (pair with a lifecycle rule on the tag - a soft-delete safety net for maintenance); `s3.analytics-accelerator.enabled` (AWS Analytics Accelerator Library, CRT client).
- Scheduled credential refresh for vended credentials arrived in 1.11 (long jobs no longer die mid-run on expired tokens).

### Engine support for v3 on AWS (as published Aug-Sep 2026; verify per service)

| Engine | v3 tables | DVs + row lineage | New v3 types (variant etc.) |
|---|---|---|---|
| Athena | **No** ("Cannot read unsupported version 3") | No | No |
| EMR Spark 7.12+ | Yes | Yes | No |
| EMR Spark 8.x (Spark 4) | Yes | Yes | Yes (S3 Tables blog says EMR 8.1+) |
| Glue 5.1 | Yes | Yes | No |
| Glue 6.0 (Spark 4) | Yes | Yes | Yes |
| Redshift | Documented on its own v3 page | Yes | Check |
| S3 Tables / Glue Data Catalog | Yes | Yes | Yes (S3 Tables, Parquet only) |

Consequence: **if Athena reads the table, stay on v2.** The upgrade is one-way.

## Databricks (as of Databricks docs updated 22 Sep 2026)

Load the `databricks` skill as well for UC grants, Delta and compute.

| Option | What it is | Iceberg clients | Status / runtime |
|---|---|---|---|
| **Managed Iceberg** (`CREATE TABLE ... USING ICEBERG` in UC) | Native Iceberg, UC is the catalog | Read **and write** via UC IRC | GA, DBR 16.4 LTS+ (serverless must reach storage) |
| **Iceberg v3 managed tables** | DVs, VARIANT, row lineage, geometry/geography, write defaults | Read/write via IRC | DBR 18 LTS+; no initial defaults, no timestamp_ns, no multi-arg transforms |
| **Delta + Iceberg reads (UniForm)** | Delta table that also writes Iceberg metadata asynchronously | Read-only | DBR 14.3 LTS+; needs column mapping, `IcebergCompatV2`, and no Delta deletion vectors (v3 reads change this) |
| **Streaming tables / MVs** | External Iceberg access via `IcebergCompatV3` per current docs (older docs and the Databricks skill call this "Compatibility Mode", which writes a separate copy) | Read-only | Lakeflow pipelines |
| **Foreign Iceberg tables** | UC federation over Glue, HMS, Snowflake Horizon | Read-only in Databricks | Catalog federation |

Enable UniForm on an existing Delta table:

```sql
ALTER TABLE cat.sch.t SET TBLPROPERTIES (
  'delta.columnMapping.mode' = 'name',
  'delta.enableIcebergCompatV2' = 'true',
  'delta.universalFormat.enabledFormats' = 'iceberg');
-- status: DESCRIBE EXTENDED / SHOW TBLPROPERTIES -> converted_delta_version, converted_delta_timestamp
```

Rules for Databricks-managed Iceberg (from the Databricks agent skill, consistent with current docs):

- Do **not** install an Iceberg jar on DBR; it ships its own.
- Do **not** set `write.metadata.path` or `write.metadata.previous-versions-max` on UC-managed tables.
- Parquet only. v2 tables: no position or equality delete files (Databricks writes v3 DVs instead). No branches/tags - only `main` is visible. Partition evolution on managed tables only from external engines. Unsupported types: UUID, fixed, time, nested required structs.
- Managed Iceberg uses liquid clustering; `PARTITIONED BY` with plain columns is the portable DDL, and UC exposes those as Iceberg partition fields to external engines. The Databricks skill reports that transform expressions (`bucket()`, `days()`) are not accepted in `PARTITIONED BY` there - verify before porting DDL from OSS Spark.
- Maintenance: predictive optimization (`OPTIMIZE`, `VACUUM`, `ANALYZE`) instead of Iceberg Spark procedures.
- External engines need `EXTERNAL USE SCHEMA` on the schema in addition to data privileges, and IP access lists must admit them. Old endpoint `/api/2.1/unity-catalog/iceberg` is legacy; use `/iceberg-rest`.
- No Change Data Feed on Iceberg tables; use Delta + UniForm if CDF matters.

**Migration paths from an OSS Iceberg-on-Glue estate to Databricks:**

1. *Read in place first*: UC foreign catalog over Glue (read-only in Databricks). Zero copy, writes stay in the existing Spark/Glue jobs.
2. *Move ownership table by table*: `CREATE TABLE uc.sch.t USING ICEBERG AS SELECT * FROM glue_foreign.db.t` (or `DEEP CLONE` from Delta). New owner is UC; repoint writers; other engines read through UC IRC. History (snapshots) does not carry over.
3. Keep tables whose readers include Athena on v2 and outside UC until Athena reads v3/REST catalogs as needed.

## Snowflake (docs as of Sep 2026; also load the `snowflake` skill)

| Mode | Catalog | Snowflake writes | Who maintains |
|---|---|---|---|
| **Snowflake-managed** (`CATALOG = 'SNOWFLAKE'`) | Snowflake (Horizon) | Yes | Snowflake (compaction etc.) |
| **Externally managed** via catalog integration | Glue, any Iceberg REST (Polaris/Open Catalog, Unity IRC) | Yes for v2/v3 via REST catalog integrations (position deletes only, no equality deletes) | You / the owning catalog |
| Object-store metadata files | none (points at metadata.json) | No | You |

```sql
-- Snowflake reading/writing Glue-catalogued tables through the Glue Iceberg REST endpoint
CREATE CATALOG INTEGRATION glue_rest_int
  CATALOG_SOURCE = ICEBERG_REST
  TABLE_FORMAT = ICEBERG
  CATALOG_NAMESPACE = 'my_glue_db'
  REST_CONFIG = (
    CATALOG_URI = 'https://glue.us-east-1.amazonaws.com/iceberg'
    CATALOG_API_TYPE = AWS_GLUE
    CATALOG_NAME = '123456789012' )
  REST_AUTHENTICATION = (
    TYPE = SIGV4
    SIGV4_IAM_ROLE = 'arn:aws:iam::123456789012:role/snowflake-glue'
    SIGV4_SIGNING_REGION = 'us-east-1' )
  ENABLED = TRUE;

-- Expose a whole namespace and keep it in sync (catalog-linked database; REST integrations only)
CREATE DATABASE lake_db LINKED_CATALOG = (CATALOG = 'glue_rest_int', ALLOWED_NAMESPACES = ('my_glue_db'));
SELECT SYSTEM$CATALOG_LINK_STATUS('lake_db');
```

- Glue integration needs an IAM role trusted by Snowflake and, with Lake Formation, `lakeformation:GetDataAccess`. Without vended credentials an `EXTERNAL VOLUME` is required for S3 access.
- Unity Catalog as the source: same pattern with `CATALOG_URI = 'https://<ws>/api/2.1/unity-catalog/iceberg-rest'`, `WAREHOUSE = '<uc catalog>'`, `ACCESS_DELEGATION_MODE = VENDED_CREDENTIALS`, bearer or OAuth auth (pattern from the Databricks agent skill).
- **Horizon Catalog REST** (`https://<account>.snowflakecomputing.com/polaris/api/catalog`) exposes **Snowflake-managed** tables to Spark, Trino, DuckDB etc. Current docs say external engines can read and write Snowflake-managed v2 and v3 tables through it; the 7 May 2026 v3 GA release note excluded external v3 writes at the time - check your account.
- v3 GA 7 May 2026: DVs, row lineage, VARIANT, default values, geo types. Reported (third-party summary, not verified in Snowflake docs) as not yet supported in v3: in-place v2-to-v3 upgrade, structured types on externally managed tables, append-only streams on externally managed tables.
- Snowflake does no lifecycle management of externally managed tables: your Spark/Glue maintenance still runs, and frequent commits raise refresh cost.

## Polaris, Nessie, Hive

- **Apache Polaris**: graduated to an Apache top-level project on 19 Feb 2026; vendor-neutral Iceberg REST catalog with RBAC, credential vending, catalog federation; monthly release train (1.4 in 2026 added STS session tags among others). Snowflake Open Catalog is the managed service of it.
- **Nessie**: Git-like branches/commits across many tables (multi-table transactions), via its own catalog type or REST. Smaller ecosystem; consider only if cross-table atomicity is a hard requirement.
- **Hive Metastore**: lock-based commits; HMS positional type checks break column reorders/drops. Legacy only.

## Sources

AWS: [S3 Tables REST endpoint](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-open-source.html), [S3 Tables via Glue REST](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-integrating-glue-endpoint.html), [S3 Tables client catalog](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-client-catalog.html), [S3 Tables maintenance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables-maintenance.html), [Glue Iceberg REST](https://docs.aws.amazon.com/glue/latest/dg/connect-glu-iceberg-rest.html), [Glue optimizers](https://docs.aws.amazon.com/glue/latest/dg/table-optimizers.html), [Glue optimizer limits](https://docs.aws.amazon.com/glue/latest/dg/optimizer-notes.html), [v3 DV/row lineage announcement (Nov 2025)](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-apache-iceberg-v3-deletion-vectors-row-lineage), [S3 Tables v3 types (30 Sep 2026)](https://aws.amazon.com/blogs/aws/amazon-s3-tables-now-support-all-apache-iceberg-v3-data-types/), [Iceberg AWS integration docs](https://iceberg.apache.org/docs/latest/aws/), [v3-on-AWS matrix by H. Konishi (third party)](https://hidekazu-konishi.com/entry/apache_iceberg_v3_on_aws.html).

Databricks: [Iceberg overview](https://docs.databricks.com/aws/en/iceberg/), [Iceberg v3](https://docs.databricks.com/aws/en/iceberg/iceberg-v3), [Iceberg reads (UniForm)](https://docs.databricks.com/aws/en/delta/uniform), [Access from Iceberg clients](https://docs.databricks.com/aws/en/external-access/iceberg); [databricks-agent-skills `databricks-iceberg`](https://github.com/databricks/databricks-agent-skills/tree/main/skills/databricks-iceberg).

Snowflake: [Iceberg tables](https://docs.snowflake.com/en/user-guide/tables-iceberg), [Glue REST catalog integration](https://docs.snowflake.com/en/user-guide/tables-iceberg-configure-catalog-integration-rest-glue), [Horizon for external engines](https://docs.snowflake.com/en/user-guide/tables-iceberg-access-using-external-query-engine-snowflake-horizon), [v3 GA release note](https://docs.snowflake.com/en/release-notes/2026/other/2026-05-07-iceberg-v3-ga), [Atlan v3 summary (third party)](https://atlan.com/know/snowflake/apache-iceberg-v3/).

Iceberg: [Spark configuration](https://iceberg.apache.org/docs/latest/spark-configuration/), [Polaris graduation](https://polaris.apache.org/blog/2026/02/19/apache-polaris-graduates-to-top-level-project/).
