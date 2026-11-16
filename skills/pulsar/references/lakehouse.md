# Pulsar into the lakehouse (Iceberg / Delta)

Status checked Oct 2026 against the sources at the end. "Vendor" means maintained by StreamNative
(Apache-2.0 code unless noted), not by the Apache Pulsar project.

## 1. Choose a route

| Situation | Route |
|---|---|
| Spark jobs on Databricks (DBR 14.1+) | Databricks native `pulsar` source (Public Preview) |
| OSS Spark on EMR / Kubernetes writing Iceberg | StreamNative `pulsar-spark` connector + Iceberg Spark sink |
| A Kafka-to-Iceberg / Kafka-to-Databricks path already runs and is owned | Pulsar IO Kafka sink into Kafka, then the existing path |
| Low-latency upserts / CDC-style mirrors | Flink (`apache/flink-connector-pulsar`) + Iceberg Flink sink |
| Raw archive files, no table needed yet | StreamNative Cloud Storage sink (vendor) to S3, then Auto Loader or Iceberg `add_files` |
| Direct Iceberg/Delta writes from Pulsar IO | StreamNative Lakehouse sink (vendor, stale; Hadoop/Hive catalogs only) |
| Kafka-protocol tooling against Pulsar | Not in Apache Pulsar (KoP archived); StreamNative KSN / Ursa only |

Whatever the route:
- One **dedicated subscription per pipeline**, named for the pipeline, with an owner and a backlog-age alert.
  A retired pipeline's subscription must be deleted, or it pins storage forever (default no expiry).
- Decide what happens on schema change before the first deploy: set the namespace to a `_TRANSITIVE`
  compatibility strategy and disable auto-update for contract topics.
- Land raw first (append-only bronze table with Pulsar metadata columns), then MERGE downstream. Keep
  `messageId`, `publishTime`, `eventTime`, key and properties: they are the dedupe and replay keys.
- Commit to Iceberg no more often than about once a minute per table (Iceberg's streaming guidance); see the
  `iceberg` and `spark` skills for maintenance.

## 2. Databricks native source

- Docs: "In Databricks Runtime 14.1 and above, you can use Structured Streaming to stream data from Apache
  Pulsar on Databricks." Status **Public Preview**. Exactly-once processing for data read from Pulsar.
- Format `pulsar`. Required: `service.url` and one of `topic`, `topics`, `topicsPattern`.
- Output: Avro / JSON schema topics expand to their fields; schema-less or primitive topics land in `value`;
  `allowDifferentTopicSchemas` loads raw `value` when topics differ. Metadata columns `__key` (binary),
  `__topic`, `__messageId` (binary), `__publishTime`, `__eventTime`, `__messageProperties` (map).
- Auth: TLS keystore / truststore and auth plugins through `pulsar.client.*` options
  (`pulsar.client.authPluginClassName`, `pulsar.client.authParams`, `pulsar.client.useKeyStoreTls`, ...);
  keep secrets in a secret scope.
- `startingOffsets`: accepts a JSON of per-topic message ids (built with `JsonUtils.topicOffsets`); other
  accepted values are on the options page (not re-read here).
- **Not stated in the docs:** a Pulsar sink, `availableNow` support, serverless compute, Unity Catalog
  standard/shared access mode. Test before depending on any of them.

```python
df = (spark.readStream.format("pulsar")
      .option("service.url", "pulsar+ssl://pulsar.example.internal:6651")
      .option("topics", "persistent://orders/events/order-updated")
      .option("pulsar.client.authPluginClassName", "org.apache.pulsar.client.impl.auth.AuthenticationToken")
      .option("pulsar.client.authParams", dbutils.secrets.get("pulsar", "token"))
      .load())
(df.writeStream.format("delta")
   .option("checkpointLocation", "s3://lake/_chk/orders_bronze")
   .trigger(processingTime="1 minute")
   .toTable("bronze.orders_events"))
```

## 3. OSS Spark: StreamNative `pulsar-spark`

| Connector | Spark | Pulsar client | Brokers | Scala | Status |
|---|---|---|---|---|---|
| 4.1.1.x | 4.1.1 | 4.0.5 | 3.0 - 4.x | 2.13 | Current |
| 4.0.1.x | 4.0.1 | 4.0.5 | 3.0 - 4.x | 2.13 | Stable |
| 3.5.6.x | 3.5.6 | 4.0.5 | 3.0 - 4.x | 2.13 | Stable |
| 3.4.x | 3.4 | 2.10.x | 2.10 - 3.x | 2.13 | Legacy |

- Artifact `io.streamnative.connectors:pulsar-spark-connector_2.13:<version>`. Scala 2.12 builds are not
  listed: EMR images on Scala 2.12 need checking. Pulsar 5.0 brokers are not in the tested matrix yet.
- Options: `service.url` (required), `topic`/`topics`/`topicsPattern`, `startingOffsets`
  (`earliest`/`latest`/JSON), `failOnDataLoss`, `maxBytesPerTrigger` (needs `admin.url`),
  `predefinedSubscription` or `subscriptionPrefix` (the subscription that tracks progress), `pulsar.client.*`,
  `pulsar.reader.*`, `pulsar.admin.*`.
- Offsets live in the Spark checkpoint; the subscription holds data on the broker. After deleting a job,
  delete its subscription (the README does not say the connector removes it).
- Sink is **at-least-once**: "some records may be duplicated".
- `failOnDataLoss` (default true) fails the query when data it expected was deleted (e.g. by retention or TTL);
  the README warns of false alarms. Keep it true for bronze ingestion and fix retention rather than flipping it.

```python
df = (spark.readStream.format("pulsar")
      .option("service.url", "pulsar://pulsar.example.internal:6650")
      .option("admin.url", "http://pulsar.example.internal:8080")
      .option("topics", "persistent://orders/events/order-updated")
      .option("predefinedSubscription", "lake-orders-bronze")
      .option("startingOffsets", "earliest")
      .option("maxBytesPerTrigger", str(512 * 1024 * 1024))
      .load())
(df.writeStream.format("iceberg")
   .option("checkpointLocation", "s3://lake/_chk/orders_bronze")
   .trigger(processingTime="1 minute")
   .toTable("glue.bronze.orders_events"))
```

Option names come from the connector README, which shows `__key` and `value` columns; inspect
`df.printSchema()` for the full set before writing.

## 4. Bridge through Kafka

- `apache/pulsar-connectors` ships a Kafka **sink** (Pulsar to Kafka) and Kafka **source**; from Pulsar 5.0 the
  connectors release separately from Pulsar (versions compatible across 4.x per the repo README).
- Pays a second copy and a second hop, but the lakehouse side (Iceberg Kafka Connect sink with exactly-once
  commits, Databricks Kafka source, Snowflake connectors) is mature.
- Monitor both: Pulsar backlog of the sink's subscription and Kafka consumer lag of the lakehouse writer.
- Keys: carry the Pulsar key as the Kafka key; partition placement will differ (different hash functions).

## 5. Flink

- `apache/flink-connector-pulsar` (latest tag v4.2.0) provides a Pulsar source and sink for Flink.
- Use when the target is an upserting Iceberg table with seconds of latency; Flink's Iceberg sink writes
  equality deletes, which need aggressive compaction (see `iceberg` skill).

## 6. Pulsar IO sinks to object storage or tables (vendor)

| Connector | Latest | Writes | Limits |
|---|---|---|---|
| `streamnative/pulsar-io-cloud-storage` | v4.3.1 (Aug 2026) | JSON (default), Avro, Parquet, bytes files to S3 (`aws-s3` or `s3v2`), GCS, Azure; time-partitioned paths | Files, not a table: add an Iceberg `add_files` / Auto Loader step; README claims exactly-once "according to your environment" |
| `streamnative/pulsar-io-lakehouse` | v4.0.3.1 (Mar 2025) | Delta, Hudi, Iceberg sink; Delta source | Iceberg catalogs only `hadoopCatalog` and `hiveCatalog`; no Glue, REST, S3 Tables or Unity; low release activity |

Pulsar IO runs on function workers: a sink is a Shared (or Failover for effectively-once) subscription with
the same backlog risks as any consumer. Processing guarantees: at-most-once, at-least-once (default),
effectively-once.

## 7. Kafka protocol on Pulsar

- **KoP** (Kafka-on-Pulsar protocol handler) open-source repo was **archived** (last push Jan 2024; last
  release v3.1.1.1). Its README points to KSN (Kafka on StreamNative).
- **KSN** and the **Ursa** storage engine (Kafka and Pulsar protocols, data kept as Iceberg / Delta tables on
  object storage) are StreamNative Cloud products: vendor-only, not Apache.
- So with Apache Pulsar, Kafka-native tools (Kafka Connect, Spark Kafka source) cannot read Pulsar topics
  directly; use a bridge.

## Sources

- https://docs.databricks.com/aws/en/connect/streaming/pulsar
- https://github.com/streamnative/pulsar-spark (README compatibility matrix and options)
- https://github.com/streamnative/pulsar-io-lakehouse/blob/master/docs/lakehouse-sink.md
- https://github.com/streamnative/pulsar-io-cloud-storage
- https://github.com/streamnative/kop
- https://github.com/apache/pulsar-connectors
- https://github.com/apache/flink-connector-pulsar
- https://pulsar.apache.org/docs/functions-concepts/ (processing guarantees)
- https://docs.streamnative.io/cloud/overview/data-streaming-engine
