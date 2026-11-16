# Ingestion: bulk API, Kafka, Data Prepper / OpenSearch Ingestion, versioning

Version tags: **[2.x]**, **[3.0+]**, **[AWS]**. Focus: keeping a mutable entity index (e.g. orders)
within a seconds-level freshness SLA.

## 1. Bulk API essentials

```
POST _bulk?filter_path=errors,items.*.status,items.*.error      (NDJSON, trailing newline)
{ "index":  { "_index": "orders", "_id": "o-1", "version": 1759300000123, "version_type": "external" } }
{ "order_id": "o-1", "status": "PAID", "total_minor": 4599, "updated_at": "2026-10-01T10:00:00Z" }
{ "update": { "_index": "orders", "_id": "o-2", "retry_on_conflict": 3 } }
{ "doc": { "status": "REFUNDED" }, "doc_as_upsert": true }
{ "delete": { "_index": "orders", "_id": "o-3", "version": 1759300000999, "version_type": "external" } }
```

- Actions: `index` (create or replace), `create` (fail if it exists), `update` (partial or
  scripted, `doc_as_upsert`, `upsert`, `scripted_upsert`), `delete`.
- **A bulk is not a transaction.** HTTP 200 with `"errors": true` means some items failed. Always
  inspect per-item `status`:
  - `429` → retry *that item* with backoff.
  - `409` (version conflict) → for external versioning, this is a **stale event: drop it**.
  - `400` (mapping error) → route to a DLQ. Don't retry.
  - `404` on `update` without upsert → the doc doesn't exist yet. Decide upsert vs DLQ.
- Size: start at **5–15 MiB** (OSS tuning docs) / 3–5 MiB (AWS best practice), and raise until
  throughput plateaus. [AWS] OR1 recommends ~10 MB. Use gzip (`Content-Encoding: gzip`). Use
  `filter_path` to shrink responses, but keep the fields needed to identify failed items.
- Concurrency: several parallel bulk clients, but keep per-key ordering (see section 3).
- `refresh` param: leave it unset (`false`). `wait_for` blocks until the next refresh (handy in
  tests, bad at volume, and **unsupported with segment replication**). `true` forces a refresh
  per request, which creates tiny segments. Never use it in production pipelines.

## 2. Cost of updates

- Lucene segments are immutable, so **every update = mark old doc deleted + index full new doc**.
  The deleted doc is purged at merge time.
- `_update` (partial): on the primary, it fetches the latest version (real-time, from the
  translog/version map if not yet refreshed), merges the `doc` or runs the script, then re-indexes
  the whole doc. That is CPU plus a read per op, serialised per `_id`. `detect_noop: true`
  (default) skips no-change updates.
- Full `index` with the whole doc avoids the read. Prefer it when the source (CDC/Kafka) emits
  complete records.
- `nested` children are re-indexed with the parent on every update. Big arrays multiply the cost.
- Symptoms of update pressure: high `docs.deleted`, rising `merges.current` and
  `total_throttled_time`, segment counts climbing, and freshness lag.

## 3. Ordering and idempotency (Kafka → OpenSearch)

Kafka guarantees order **per partition**. Key messages by entity ID (`order_id`) so all versions
of an order land in the same partition. After that, order can still break through parallel bulk
workers, retries, consumer rebalances (at-least-once redelivery), or multiple pipelines.

**Make writes order-independent with external versioning**:
- Pick a monotonic version per entity from the source: a DB commit LSN/SCN, a per-row version
  column, or `updated_at` epoch-millis if it is strictly increasing per row.
- Send `index` (not `update`) with `version: <v>`, `version_type: external` (accept if
  `v > current`) or `external_gte` (accept if `v >= current`; idempotent replays succeed).
- A `409` means a newer version is already indexed. Count it and drop it.
- `_update` does **not** support `version_type: external`. Use `if_seq_no` + `if_primary_term`
  (optimistic concurrency against OpenSearch's own sequence numbers) or `retry_on_conflict`
  (fine for commutative scripts, e.g. counters).

Deletes:
- External-versioned deletes are remembered for `index.gc_deletes` (**60s** default). An older
  event that arrives later than that **recreates** the doc.
- Safer for CDC: soft delete (`index` the doc with `is_deleted: true` and the new version), filter
  it out in queries, and purge with a periodic `delete_by_query` or by dropping time indexes.

Exactly-once is not available end to end. Aim for **at-least-once + idempotent writes**
(`_id` = key, external version).

## 4. Freshness budget (example: 7 s SLA)

| Stage | Typical | Knob |
|---|---|---|
| Source commit → Kafka (CDC/Debezium/outbox) | 0.1–1 s | Connector poll interval |
| Consumer batching | **≤ 1 s** | Flush on size *or* time. **Data Prepper `flush_timeout` default is 60,000 ms**, so set it low |
| Bulk request | 50–500 ms | Bulk size, cluster headroom |
| Refresh | 0–`refresh_interval` | `1s` explicit (not search-idle) |
| Replica catch-up | ~0 (doc replication) / seconds (segment replication, OR1) | Replication type, `preference` |
| API/GraphQL cache | 0–TTL | Keep the TTL ≤ 1–2 s on "live" queries |

Measure it: stamp `ingested_at` (an ingest pipeline `set` with `{{_ingest.timestamp}}`, or the
writer's clock) next to the source `updated_at`. Chart `now - max(updated_at)` per tenant and
the p99 of `ingested_at - updated_at`.

## 5. Ingestion options

### a) Custom consumer (Java/Go/Python client → `_bulk`)
Most control: per-item error handling, external versioning, DLQ, metrics. Use the official
`opensearch-java` / `opensearch-py` clients (**Elasticsearch clients ≥ 7.14 refuse to talk to
OpenSearch**, see opensearch-vs-elasticsearch.md). Commit Kafka offsets only after the bulk
items for those offsets succeeded or were dead-lettered.

### b) Data Prepper (OSS) / Amazon OpenSearch Ingestion (OSIS, managed Data Prepper) [AWS]
Pipeline YAML: `source` → `buffer` → `processor`s → `sink`.

```yaml
version: "2"
orders-pipeline:
  source:
    kafka:
      bootstrap_servers: ["b-1.msk:9098"]
      acknowledgments: true            # end-to-end acks: offsets committed after sink success
      topics:
        - name: orders.cdc
          group_id: opensearch-orders
          workers: 4                   # default 2, max 200
          auto_offset_reset: earliest  # default
          serde_format: json           # default plaintext
      # aws: { msk: { arn: ... }, region: ... }   # [AWS] MSK via PrivateLink, IAM auth
  processor:
    - date: { match: [ { key: updated_at, patterns: ["yyyy-MM-dd'T'HH:mm:ss.SSSX"] } ], destination: "@timestamp" }
  sink:
    - opensearch:
        hosts: ["https://search-domain.eu-west-1.es.amazonaws.com"]
        aws: { region: eu-west-1, sts_role_arn: "arn:aws:iam::...:role/osis" }
        index: orders
        action: index                       # create | index | update | upsert | delete (default index)
        document_id: "${/order_id}"
        document_version: "${/version}"     # must evaluate to a long
        document_version_type: external     # external | external_gte | internal
        routing: "${/merchant_id}"          # optional
        bulk_size: 5                        # MiB, default 5
        flush_timeout: 1000                 # ms, default 60000, so lower it for freshness
        dlq: { s3: { bucket: osis-dlq, region: eu-west-1 } }
```

- The CDC delete action can be driven by an expression (e.g. `action: '${getMetadata("opensearch_action")}'`
  or conditional `actions:`). Check the sink docs for your Data Prepper version.
- OSIS scales in OCUs. Each OCU runs one consumer per topic. Set max OCUs ≈ partition count (max
  96 per pipeline). AWS recommends ≥ 10 partitions per topic.
- The Data Prepper docs do not state ordering guarantees. **Assume no ordering across workers**,
  and rely on external versioning.
- Other sources: `s3`, `dynamodb` (export + stream), `documentdb`, `rds`/`aurora` (zero-ETL
  style CDC), `http`, `otel_*`. Sink options also cover index templates (`template_type`,
  `template_file`) and `ism_policy_file`.

### c) Kafka Connect sink
The **Aiven OpenSearch sink connector** (`opensearch-connector-for-apache-kafka`, Apache-2.0) is
the common OSS choice. Typical settings: `key.ignore=false` (use the record key as `_id`),
`behavior.on.null.values=delete` (tombstones → deletes), an upsert write method, and
`behavior.on.version.conflict`. **Verify the property names against the connector version.**
The Confluent Elasticsearch sink targets Elastic and may fail against OpenSearch 2.x.

### d) Stream processor sink
Flink `flink-connector-opensearch` (sink with a bulk processor; at-least-once with checkpoints)
or Spark Structured Streaming via `opensearch-hadoop`. Good when you already join or pre-aggregate
upstream (e.g. order + items + merchant enrichment).

### e) Pull-based ingestion [3.0+]
OpenSearch shards **pull directly from Kafka (or Kinesis) partitions**, one partition per shard.

```json
PUT /orders
{ "settings": {
    "ingestion_source": { "type": "kafka", "pointer.init.reset": "earliest",
      "param": { "topic": "orders", "bootstrap_servers": "broker:9092" } },
    "index.number_of_shards": 8, "index.number_of_replicas": 1,
    "index": { "replication.type": "SEGMENT" } } }
```

- Message body: `{"_id": "...", "_version": 123, "_op_type": "index|create|delete", "_source": {...}}`.
  `_version` gives external-version semantics (older versions dropped). Delivery is at-least-once.
- Updates to a doc must come from the **same partition** (keyed by `_id`).
- `error_strategy`: `DROP` (default) or `BLOCK`.
- Limitations (current docs): set only at index creation. **No ingest pipelines, no dynamic
  mapping, no rollover, REST indexing APIs disabled** on that index. Segment replication with
  remote store is recommended.
- Status: introduced as experimental in 3.0. Current docs mark the **Kafka plugin GA and
  Kinesis experimental**. Requires the `ingestion-kafka` plugin. Check whether your managed
  service exposes it (not confirmed for Amazon OpenSearch Service).

## 6. Ingest pipelines (in-cluster)

`PUT _ingest/pipeline/<id>` with processors (`set`, `rename`, `date`, `script`, `remove`,
`convert`, …), applied via `?pipeline=` or `index.default_pipeline`/`final_pipeline`. They run
on `ingest` nodes and cost CPU per doc. Keep heavy enrichment upstream.

## 7. Backfill / re-index recipe for a live mutable index

1. Create `orders-v2` (new mapping), `refresh_interval: -1`, `number_of_replicas: 0`.
2. Start a **second consumer group** on the CDC topic writing to `orders-v2` with external
   versioning (dual-write from now on). **If the routing key changes**, start dual-writing several
   days before the bulk copy, for longer than soft-delete retention, so deletes aren't lost.
3. Bulk-load the snapshot (DB export, or `_reindex` from v1) also with external versions. Stale
   rows lose the version check automatically.
4. Restore `refresh_interval` and replicas, wait for green, and compare counts and sample aggs
   between v1 and v2.
5. Atomic alias swap. Stop the v1 consumer. Delete v1 later.
