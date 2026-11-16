---
name: pulsar
description: Reference for Apache Pulsar (4.0 LTS and 4.2, with what changes in 5.0 LTS) for an engineer who already knows Kafka and SQS: Pulsar vs Kafka vs SQS, architecture, subscriptions, acks and redelivery, retention and backlog, tiered storage, geo-replication, Pulsar-to-lakehouse pipelines, and client gotchas. Load whenever work touches a Pulsar topic, subscription, client, namespace policy or cluster. Triggers: "pulsar", "bookkeeper", "bookie", "managed ledger", "namespace bundle", "key_shared", "backlog quota", "pulsar vs kafka", "pulsar functions", "geo-replication", "negative ack", "dead letter topic", "reconsumeLater", "deliverAfter", "KoP", "oxia", "pulsar-admin".
---

# Apache Pulsar - reference for Kafka people

Use this when reading, designing, operating or debugging anything on Pulsar, or moving Pulsar data into a
lakehouse. Broker defaults were read from `conf/broker.conf` and `ServiceConfiguration.java` at tags
**v4.0.14, v4.2.5 and v5.0.1**, client defaults from the client config classes at **v4.2.5** (checked against
v4.0.14 and v5.0.1). Where a value differs between versions, the version is named. Docs read Oct 2026; the
docs site defaults to 5.0.x.

Deeper material:
- [references/kafka-to-pulsar.md](references/kafka-to-pulsar.md) - full concept map, glossary, and the behaviours that surprise Kafka users.
- [references/operations.md](references/operations.md) - broker defaults across 4.0 / 4.2 / 5.0, `pulsar-admin` cheat sheet, metrics, and runbooks (backlog emergency, bookie full, hot bundle).
- [references/java-client.md](references/java-client.md) - producer and consumer settings with verified defaults, DLQ / retry / Key_Shared code, Kotlin notes.
- [references/lakehouse.md](references/lakehouse.md) - every route from Pulsar into Iceberg or Delta, with config and status.

For the Spark side of a streaming job load the `spark` skill; for the table side load `iceberg` or `databricks`.

## Version facts (re-check before quoting)

| Line | Type | Released | Support |
|---|---|---|---|
| 5.0 (5.0.1 on 26 Oct 2026) | LTS | 5 Oct 2026 | active to Oct 2028, security to Oct 2029 |
| 4.2 | feature | Mar 2026 | ended Sep 2026 |
| 4.1 | feature | Sep 2025 | ended Mar 2026 |
| 4.0 | LTS | 21 Oct 2024 | active ended 21 Oct 2026, security to 21 Oct 2027 |
| 3.0 | LTS | May 2023 | out of security support (May 2026) |

**5.0 changes that matter** (release notes): new **scalable topics** (range-based segments that split and
merge, keeping per-key order) with a new additive `pulsar-client-v5` module (the existing client is
unchanged); **Oxia** is the recommended metadata store for new clusters; the **etcd** backend is removed;
built-in **IO connectors moved** to `apache/pulsar-connectors`; `javax.*` to `jakarta.*` (custom broker
plugins and auth providers must be rebuilt); `defaultNumberOfNamespaceBundles` 4 to **32**; modular load
manager shedding `ThresholdShedder` to **`AvgShedder`**. Java: brokers run on 17; the 4.0 Java client is built
for Java 8.

## When to use it / when not to

| Situation | Pick | Why |
|---|---|---|
| Hundreds of services sharing one messaging platform, needing isolation, quotas and per-team auth | **Pulsar** | Tenants and namespaces with per-namespace policy are built in |
| Work queues (per-message ack, redelivery, DLQ, delayed delivery) and pub/sub on one system | **Pulsar** | Shared / Key_Shared subscriptions; Kafka share groups (production-ready since Kafka 4.2) are younger and lack built-in delay |
| Per-key ordering with more consumers than partitions | **Pulsar** Key_Shared | Parallelism is not capped by partition count |
| Very many topics (per tenant / per entity) | **Pulsar** | Topics are metadata grouped into bundles; no per-partition leader/replica set |
| Built-in multi-region replication, per namespace | **Pulsar** | Geo-replication is a namespace/topic policy; Kafka needs MirrorMaker 2 or a vendor link |
| Scale brokers without moving data | **Pulsar** | Brokers are stateless; a bundle moves in seconds. Kafka moves partition data (tiered storage reduces it) |
| CDC, Kafka Connect, ksqlDB / Kafka Streams, widest lakehouse and vendor ecosystem | **Kafka** | Debezium, Connect sinks (Iceberg, S3, Snowflake), native Spark/Flink/Databricks sources |
| Stateful stream processing (joins, windows, large state) | **Flink or Kafka Streams** | Pulsar Functions are lightweight per-message functions, not a stream processor |
| Low-volume AWS queue, no cluster to run | **SQS** (+ SNS for fan-out) | Fully managed; no ordering beyond FIFO groups, no replay |
| Rich routing (exchanges, headers, RPC reply-to) at modest scale | **RabbitMQ** | Routing model Pulsar and Kafka lack |
| One team, one use case, no Pulsar operators | **Managed Kafka or SQS** | Pulsar is three distributed systems to run (brokers, bookies, metadata store) |

**Why organisations run both.** Pulsar usually serves service-to-service messaging (queues plus pub/sub,
multi-tenant, DLQ and delay semantics), owned by a platform team. Kafka usually serves the data platform:
CDC through Debezium, Connect, and native sources in Spark, Flink and Databricks. Rules for the seam:
- Bridge each stream in **one direction, with one owner** (Pulsar IO Kafka sink/source, or a dedicated job).
- Monitor lag on **both** sides: Pulsar subscription backlog of the bridge, and the Kafka consumer lag after it.
- Do not assume key-to-partition placement matches: Pulsar hashes keys with `JavaStringHash` by default, Kafka with murmur2.
- Schemas do not carry over: Pulsar stores a per-topic schema version in message metadata; Confluent-style registries put a schema id in the payload prefix.

## Architecture (60 seconds)

```
clients ──> [proxy, optional] ──> brokers (stateless: own bundles, cache tail, dispatch to subscriptions)
                                      │ write entries (E/Qw/Qa)          │ ownership, policies, ledger ids
                                      v                                   v
                         BookKeeper bookies                       metadata store (ZooKeeper | Oxia)
                         journal (WAL, fsync) + ledger storage    + configuration store (instance-wide:
                                      │ sealed ledgers                tenants, namespaces, clusters)
                                      v
                         tiered storage (S3 / GCS / Azure / filesystem), optional
```

- **Topic = managed ledger = a chain of BookKeeper ledgers** ("segments"). A ledger rolls over at
  `managedLedgerMaxEntriesPerLedger` 50,000 entries, `...MaxLedgerRolloverTimeMinutes` 240 or
  `...MaxSizePerLedgerMbytes` 2048, not before `...MinLedgerRolloverTimeMinutes` 10. **Deletion is per whole
  ledger**, never per message; disk is freed after rollover plus bookie garbage collection.
- An **entry** is one message or one **batch**. Acks, redelivery and nack act on entries unless batch-index ack is on.
- **Replication inside a cluster:** ensemble E, write quorum Qw, ack quorum Qa. Defaults
  `managedLedgerDefaultEnsembleSize/WriteQuorum/AckQuorum` = **2/2/2**; 3/3/2 is the common production choice
  (convention, not a doc default). Set per namespace with `set-persistence`.
- **Bookie:** the journal (fsync'd write-ahead log) belongs on its own fast disk; journal latency is the
  publish latency floor. Ledger storage holds the data.
- **Brokers hold no durable state.** Each owns some namespace bundles; the managed-ledger cache (default 1/5 of
  direct memory) serves tailing reads; catch-up reads go to bookies or tiered storage.
- **Metadata store:** ZooKeeper (`metadataStoreUrl=zk:...`) is the 4.x default. Oxia's provider ships in the
  code since 3.3 but is absent from the 4.x admin docs; 5.0 docs recommend it for new clusters. etcd is
  removed in 5.0. RocksDB / memory are standalone only.
- **Bundles:** a namespace's hash range is split into bundles; each topic hashes to one bundle; one broker owns
  a bundle. Defaults: `defaultNumberOfNamespaceBundles` **4** (4.x) / **32** (5.0); auto-split on (above 1000
  topics, 1000 sessions, 30,000 msg/s or 100 MB/s per bundle), max 128 bundles per namespace.
  Load manager default `ModularLoadManagerImpl` (shedder `ThresholdShedder` in 4.x, `AvgShedder` in 5.0);
  `ExtensibleLoadManagerImpl` exists since 3.0 (shedder `TransferShedder`). An **unload** gives clients a short
  reconnect blip.
- **Partitioned topic** = N internal topics `<name>-partition-<i>`, each placed independently. A
  non-partitioned topic lives on one broker, so its throughput is one broker's. Partitions can be added, not
  removed. **Auto-created topics are non-partitioned** (`allowAutoTopicCreationType=non-partitioned`,
  `defaultNumPartitions=1`).
- **Persistent vs non-persistent:** `persistent://` writes to bookies; `non-persistent://` never touches disk
  and drops messages when a consumer is slow or a broker restarts.
- Names: `persistent://tenant/namespace/topic`; a bare `my-topic` means `persistent://public/default/my-topic`.

## Kafka to Pulsar concept map

| Kafka | Pulsar | Difference that bites |
|---|---|---|
| Topic partition | Partition of a partitioned topic (itself a topic) | Non-partitioned topics are normal; auto-create makes those |
| Consumer group | **Subscription** (+ subscription type) | Broker-side durable cursor; each subscription gets every message |
| Committed offset | Cursor **mark-delete position** + individually acked ranges | Acks are per message, not "offset up to" (except cumulative ack) |
| `auto.offset.reset` | `subscriptionInitialPosition` (default **Latest**) | Applies only when the subscription is first created |
| `retention.ms` deletes regardless of readers | Unacked data kept **forever** by default; retention covers only **acked** data | See the retention section |
| Log compaction | Topic compaction + `readCompacted(true)` | Auto-compaction off (`brokerServiceCompactionThresholdInBytes=0`) |
| Seek by offset/time | `seek(MessageId | timestamp)`, `reset-cursor` | MessageId = ledger:entry:partition:batchIndex |
| Kafka Connect | **Pulsar IO** (sources/sinks run by function workers) | Smaller catalogue; Kafka Connect Adaptor runs Connect connectors |
| Kafka Streams / ksqlDB | **Pulsar Functions** | Per-message functions, light state; use Flink for real stream processing |
| Schema Registry | **Built-in per-topic schema registry** | Default compatibility `FULL`; auto-update on |
| MirrorMaker 2 | **Geo-replication** | Namespace/topic policy; subscriptions not replicated unless opted in |
| KRaft / ZooKeeper | **Metadata store** (ZooKeeper / Oxia) + BookKeeper's metadata | Three systems to operate, not one |
| Idempotent producer | Broker deduplication (`brokerDeduplicationEnabled=false`) | Off by default; needs a stable producer name |
| Transactions | Transactions (`transactionCoordinatorEnabled=false`) | Off by default |
| `message.max.bytes` 1 MB | `maxMessageSize` **5 MB**; chunking for larger | Chunking cannot combine with batching |
| Tiered storage (KIP-405) | Tiered storage offload of sealed ledgers | Offloaded data is ledger format, not Parquet |

Full map and glossary: [references/kafka-to-pulsar.md](references/kafka-to-pulsar.md).

## Subscriptions

| Type | Consumers | Ordering | Cumulative ack | Use for |
|---|---|---|---|---|
| **Exclusive** (default) | One; a second gets an error | Total per partition | Yes | Single ordered reader, replay jobs |
| **Failover** | Many; one active per partition, rest standby | Per partition; duplicates or reordering possible at switchover | Yes | Kafka-consumer-group-style ordered processing with HA |
| **Shared** | Many, round-robin | **None** | No | Work queues, SQS-style |
| **Key_Shared** | Many, by key hash | Per key | No | Per-entity ordering with parallelism beyond partitions |

- A subscription is created on first subscribe (`allowAutoSubscriptionCreation=true`) and **lives until
  deleted**: `subscriptionExpirationTimeMinutes=0` means never expire.
- **Key_Shared** modes: `AUTO_SPLIT` (default; consistent hashing on, 100 replica points) and `STICKY`
  (consumer declares hash ranges). Since **4.0** a key moves to a new consumer only after its
  outstanding unacked messages are acked or the old consumer disconnects ("draining hashes"); hash space is
  2^16. `subscriptionKeySharedUseClassicPersistentImplementation` (4.x, default false) restores the old
  dispatcher. `KeySharedPolicy...setAllowOutOfOrderDelivery(true)` trades ordering for throughput.
- **Key_Shared producers must disable batching or use `BatcherBuilder.KEY_BASED`**; otherwise a batch of
  mixed keys goes to one consumer.
- A slow consumer on a hot key stalls look-ahead for others: limits
  `keySharedLookAheadMsgInReplayThresholdPerConsumer` 2000 / `...PerSubscription` 20000 (4000 / 40000 in 5.0).
- Dispatch to a consumer stops at `maxUnackedMessagesPerConsumer` **50,000**, to a subscription at
  `maxUnackedMessagesPerSubscription` **200,000** ("consumers connected but nothing arrives").
- **Readers** use a non-durable cursor and never ack: they can only replay what retention keeps.

### Acks, redelivery, DLQ, delay

| Mechanism | Default | Rule |
|---|---|---|
| Individual ack | - | The only ack on Shared / Key_Shared |
| Cumulative ack | - | Exclusive / Failover only |
| Batch-index ack | Off in 4.0 (broker `acknowledgmentAtBatchIndexLevelEnabled=false`, client `batchIndexAckEnabled=false`); **on** in 4.2.5 and 5.0 | Without it, acking part of a batch redelivers the whole batch |
| Ack grouping | 100 ms (`acknowledgementsGroupTime`) | Acks are sent asynchronously; a crash inside the window redelivers |
| Negative ack | Redelivery after **1 min** | Add `MultiplierRedeliveryBackoff`; nack of a batched message redelivers the batch; on ordered types it reorders |
| Ack timeout | **0 = off** | Prefer nack; timeouts are hard to tune and cause duplicate work |
| Dead-letter topic | Off; name `<topic>-<subscription>-DLQ` | `deadLetterPolicy(maxRedeliverCount)`; **Shared and Key_Shared only**; set `initialSubscriptionName` or DLQ messages can be deleted (no subscription + no retention) |
| Retry-letter topic | Off; name `<topic>-<subscription>-RETRY` | `enableRetry(true)` + `reconsumeLater(msg, delay)`; docs say Shared only; counter travels in the `RECONSUMETIMES` property, so it survives restarts |
| Delayed delivery | Broker on (`delayedDeliveryEnabled=true`, tick 1 s, in-memory tracker) | `deliverAfter` / `deliverAt`; **Shared and Key_Shared only**, other types deliver at once |

- The nack/ack-timeout redelivery counter is **in memory and can reset**, so `maxRedeliverCount` may never
  trigger; use the retry-letter topic when the cap must hold.
- Long delays **pin ledgers** (no mid-topic deletion), count toward backlog quota, and TTL acks them anyway.
  The in-memory tracker's memory grows with delayed-message count; `BucketDelayedDeliveryTrackerFactory`
  persists the index for large volumes.

## Retention, backlog, TTL

Kafka deletes by time whatever readers have done. **Pulsar keeps everything any subscription has not acked,
and deletes acked data at once unless retention says otherwise.** Same values in 4.0.14, 4.2.5 and 5.0.1:

| Setting (broker default, overridable per namespace/topic) | Default | Meaning |
|---|---|---|
| `defaultRetentionTimeInMinutes` / `defaultRetentionSizeInMB` | 0 / 0 | Acked data (and data on topics with **no subscription**) is deleted at the next ledger trim |
| `backlogQuotaDefaultLimitBytes` / `...LimitSecond` | -1 / -1 | **No backlog limit** |
| `backlogQuotaDefaultRetentionPolicy` | `producer_request_hold` | When a quota is hit, producers block until `sendTimeout` (30 s), then fail |
| `ttlDurationDefaultInSeconds` | 0 | Unacked messages never expire |
| `subscriptionExpirationTimeMinutes` | 0 | Idle subscriptions never expire |
| `brokerDeleteInactiveTopicsEnabled` / mode | true / `delete_when_no_subscriptions` | Topics with no producers and no subscriptions are deleted (checked every 60 s) |
| `allowAutoTopicCreation` | true (non-partitioned) | A typo creates a new topic |

Pitfalls:
1. **The forgotten subscription fills the bookies.** One subscription nobody reads (decommissioned service,
   test consumer, renamed subscription, a crashed connector job) pins every ledger after its mark-delete
   position. With no quota and no TTL nothing pushes back until bookie disks pass their threshold, bookies go
   read-only (`bookie_SERVER_STATUS`=0), and **writes fail for every tenant on those bookies**. Defend in
   depth: a backlog quota per namespace, a TTL or subscription expiry where loss is acceptable, alerts on
   per-subscription backlog size and age, and an owner per subscription.
2. **Producing before anyone subscribes loses data** (retention 0). Create the subscription first
   (`pulsar-admin topics create-subscription`), or set retention.
3. Retention must be at least the backlog quota, or setting both errors.
4. Space returns only after ledger rollover plus bookie GC, so a cleared backlog does not free disk at once.
5. `consumer_backlog_eviction` silently drops the oldest unacked messages; use it only where loss is fine.

```bash
pulsar-admin namespaces set-retention    my-tenant/my-ns --size 10G --time 3d
pulsar-admin namespaces set-backlog-quota my-tenant/my-ns --limit 50G --policy producer_exception
pulsar-admin namespaces set-backlog-quota my-tenant/my-ns --limitTime 86400 --policy producer_exception --type message_age
pulsar-admin namespaces set-message-ttl  my-tenant/my-ns --messageTTL 604800
pulsar-admin namespaces set-subscription-expiration-time my-tenant/my-ns --time 10080   # minutes
pulsar-admin topics subscriptions persistent://my-tenant/my-ns/t                       # find the stray one
pulsar-admin topics unsubscribe   persistent://my-tenant/my-ns/t -s stale-sub
```

### Tiered storage

- Offloads **sealed ledgers** (never the open one) to S3 (`aws-s3` via jclouds, or S3-compatible), GCS, Azure,
  Aliyun OSS or a Hadoop filesystem. Offloaders ship in a separate `apache-pulsar-offloaders` tarball; the
  `apachepulsar/pulsar` image includes them except the filesystem one.
- Automatic offload is **off** (`managedLedgerOffloadAutoTriggerSizeThresholdBytes=-1`,
  `...ThresholdInSeconds=-1`); turn it on per namespace with `set-offload-threshold --size/--time`. Bookie
  copies are deleted `managedLedgerOffloadDeletionLagMs` = **4 h** after offload. Reads prefer tiered storage
  (`managedLedgerDataReadPriority=tiered-storage-first`).
- Offload moves bytes, it does not change **what** is kept: retention and backlog still decide deletion.
- Add an S3 lifecycle rule that aborts incomplete multipart uploads after a day or two.
- Offloaded data is BookKeeper ledger format. It is cheap replay storage, **not a lakehouse table**.

## Multi-tenancy, security, geo-replication

- Hierarchy: instance > cluster > **tenant** (admin roles, allowed clusters) > **namespace** (the unit of
  policy) > topic. Topic-level policies (`topicLevelPoliciesEnabled=true`) override namespace, which overrides
  broker defaults.
- Namespace policies to set on day one: retention, backlog quota, TTL, subscription expiry, offload threshold,
  schema compatibility and validation, replication clusters, publish / dispatch / subscribe rates,
  max producers / consumers / subscriptions, deduplication, persistence (E/Qw/Qa), auto-topic-creation
  override, bundles. Per-object limits default to **0 = unlimited**.
- Noisy-neighbour levers: publish and dispatch rate limits, resource groups, namespace isolation policies
  (pin namespaces to broker groups), bookie affinity groups.
- **Auth is off by default** (`authenticationEnabled=false`, `authorizationEnabled=false`). Providers: mTLS,
  JWT, OAuth 2.0, OpenID Connect, Kerberos, Athenz, basic. Authorization: superusers, tenant admins, and
  `grant-permission` (produce, consume, functions...) on namespaces or topics.
- **Geo-replication** is asynchronous: `tenants create --allowed-clusters`, then `namespaces set-clusters` or
  `topics set-replication-clusters`; per message `replicationClusters(...)` / `disableReplication()`.
  Only topic data replicates; subscriptions stay local unless a consumer sets
  `replicateSubscriptionState(true)` (broker `enableReplicatedSubscriptions=true`, snapshot every 1000 ms,
  needs two-way replication). Only the mark-delete position replicates, so failover redelivers some messages,
  and consumers active in both clusters process most messages twice. Watch `pulsar_replication_backlog`.

## Schemas

- Registry is **per topic**, stored in BookKeeper, versioned; each message carries its schema version.
  Types: primitives, Avro, JSON, Protobuf, ProtobufNative, KeyValue (INLINE or SEPARATED), AUTO_CONSUME /
  AUTO_PRODUCE.
- Broker default `schemaCompatibilityStrategy=FULL` (docs: Avro/JSON FULL, other types ALWAYS_INCOMPATIBLE).

| Strategy | Means | Upgrade first |
|---|---|---|
| ALWAYS_COMPATIBLE / ALWAYS_INCOMPATIBLE | No check / no change allowed | any / n/a |
| BACKWARD (`_TRANSITIVE`) | New consumers read data from the last (all) producer versions | Consumers |
| FORWARD (`_TRANSITIVE`) | Last (all) consumer versions read data from the new producer | Producers |
| FULL (`_TRANSITIVE`) | Both, against the latest (all) versions | Any order |

- `isAllowAutoUpdateSchemaEnabled=true`: any producer with a compatible new schema registers it. For topics the
  data platform consumes, disable auto-update per namespace and register schemas from CI.
- Schema validation is **not enforced** by default: a `bytes` producer can write to a schema'd topic. Turn on
  `set-schema-validation-enforce` for contract topics.
- For lakehouse ingestion, `_TRANSITIVE` strategies stop a chain of individually compatible changes from
  breaking old partitions.

## Getting Pulsar data into the lakehouse

| Route | Status (Oct 2026) | Notes |
|---|---|---|
| **Databricks** `spark.readStream.format("pulsar")` | Native, **Public Preview**, DBR **14.1+** | Exactly-once read; `service.url` + `topic`/`topics`/`topicsPattern`; columns `__key`, `__topic`, `__messageId`, `__publishTime`, `__eventTime`, `__messageProperties`. Sink, serverless and UC access-mode support **not stated** in docs |
| **OSS Spark**: StreamNative `pulsar-spark` connector | Vendor-maintained, Apache-2.0; 4.1.1.x for Spark 4.1.1, 4.0.1.x, 3.5.6.x; Scala 2.13 only | Source plus at-least-once sink; `maxBytesPerTrigger` needs `admin.url`; tracks progress through a subscription (`predefinedSubscription` or random from `subscriptionPrefix`), so check for orphans after jobs are retired (inferred from README, not documented) |
| **Pulsar IO Kafka sink** into the existing Kafka-to-lakehouse path | Apache (`apache/pulsar-connectors`) | Extra hop, but reuses the Iceberg Kafka Connect sink or Databricks Kafka source the platform already runs |
| **Flink** `apache/flink-connector-pulsar` + Iceberg Flink sink | Apache | Best for upserts with low latency; Flink to operate |
| StreamNative **Lakehouse sink** (Iceberg / Delta / Hudi) | **Vendor**, last release v4.0.3.1 (Mar 2025) | Iceberg catalogs: `hadoopCatalog` and `hiveCatalog` only, so no Glue, REST or S3 Tables |
| StreamNative **Cloud Storage sink** (JSON / Avro / Parquet / bytes to S3) | **Vendor**, v4.3.1 (Aug 2026) | Files only; then Auto Loader or Iceberg `add_files` |
| Kafka protocol on Pulsar: **KoP** | Open-source repo **archived Jan 2024** | Successors KSN and Ursa (writes Iceberg/Delta directly) are **StreamNative-only** |

Rules: consume with a dedicated **subscription per pipeline**, owned and alerted on; keep Spark trigger at a
minute or more into Iceberg; never write Iceberg from a fleet of hand-rolled Shared-subscription consumers
(small files, commit storms). Detail and config: [references/lakehouse.md](references/lakehouse.md).

## Java / Kotlin client gotchas

| Setting | Default | Gotcha |
|---|---|---|
| `PulsarClient` | - | One per process (it owns IO/listener threads and connections). Close consumers and producers, then the client; a leaked consumer keeps its unacked messages assigned until disconnect |
| `sendTimeout` | 30 s | A timed-out send may have landed: retries duplicate unless broker dedup is on with a stable `producerName` |
| `blockIfQueueFull` | false | `sendAsync` fails fast with `ProducerQueueIsFullError` when full |
| `maxPendingMessages` | 0 (no count limit; bounded by client `memoryLimit` **64 MB**) | Firehose producers: set `blockIfQueueFull(true)` |
| Batching | on; 1 ms, 1000 msgs, 128 KB | A batch is one entry: nack, ack-timeout and partial acks redeliver the batch (see batch-index ack). Key_Shared needs `BatcherBuilder.KEY_BASED` |
| `compressionType` | NONE | Set LZ4 or ZSTD |
| `hashingScheme` | `JavaStringHash` | Not Kafka's murmur2 |
| `receiverQueueSize` | 1000 per consumer (`maxTotalReceiverQueueSizeAcrossPartitions` 50,000) | On Shared subscriptions with slow handlers prefetch hoards work: lower it (1-10). 0 disables prefetch but breaks batches and partitioned topics |
| `subscriptionInitialPosition` | Latest | Set Earliest for new pipelines that must see existing data |
| `ackTimeout` / nack delay | off / 1 min | Nack explicitly on failure; do not rely on ack timeout |
| Message listener | `numListenerThreads` = cores | Blocking in a listener stalls every consumer on that thread |

Never call blocking `send()` / `receive()` inside an async callback (it runs on a client thread). In Kotlin use
the `*Async` methods with `kotlinx.coroutines.future.await()`, not `runBlocking` in listeners. Code:
[references/java-client.md](references/java-client.md).

## Operating checklist

Watch (Prometheus names; topic-level on by default, consumer-level and bundle metrics off by default):

| Metric | Watch for |
|---|---|
| `pulsar_subscription_back_log`, `pulsar_msg_backlog`, `pulsar_storage_backlog_size` | Steady growth on one subscription: stuck or orphaned consumer |
| `pulsar_subscription_storage_backlog_age_seconds` (needs `exposeSubscriptionBacklogAgeInPrometheus=true`), `pulsar_storage_backlog_age_seconds` | Age past the SLA; the best "forgotten subscription" signal |
| `pulsar_rate_in` vs `pulsar_rate_out` | Out persistently below in |
| `pulsar_storage_size`, `pulsar_storage_offloaded_size`, `pulsar_storage_backlog_quota_limit` | Approaching quota or disk |
| `pulsar_subscription_unacked_messages`, `pulsar_subscription_blocked_on_unacked_messages` | Blocked = 1 means dispatch stopped |
| `pulsar_subscription_msg_rate_redeliver` | Poison messages or handlers timing out |
| `bookie_journal_JOURNAL_ADD_ENTRY`, `pulsar_storage_write_latency_le_*`, `pulsar_broker_publish_latency` | Publish latency comes from the journal disk |
| `bookie_ledger_writable_dirs`, `bookie_SERVER_STATUS` | Disk filling; 0 = bookie read-only |
| `pulsar_lb_unload_bundle_total`, `pulsar_lb_bundles_split_total` (`exposeBundlesMetricsInPrometheus=true`) | Unload churn shows as client latency blips |
| `pulsar_replication_backlog`, `pulsar_replication_delay_in_seconds` | Geo-replication falling behind |
| `pulsar_ml_cache_hits_rate` / `_misses_rate` | Catch-up readers driving bookie reads |

Pitfalls:
1. No backlog quota, TTL or subscription expiry on a shared cluster (the forgotten-subscription outage).
2. Producing to a topic before its subscription exists (retention 0 deletes it).
3. Auto-created non-partitioned topics carrying production load on one broker.
4. Ledger quorum left at 2/2/2 for data that must survive a bookie loss during maintenance.
5. Journal and ledger storage on the same disk.
6. Key_Shared producers with default batching.
7. Shared subscriptions with `receiverQueueSize` 1000 and slow handlers (one consumer hoards, others idle).
8. Expecting `maxRedeliverCount` to cap retries exactly; use the retry-letter topic.
9. DLQ with no subscription, so dead letters are deleted.
10. Long delayed-delivery times pinning ledgers and tripping quotas.
11. Schema auto-update and no validation on topics the data platform reads.
12. Topic-level metrics on hundreds of thousands of topics (Prometheus cardinality); aggregate at namespace.
13. Running consumers active-active on a replicated subscription (most messages processed twice).
14. Treating tiered storage as an archive table instead of replay storage.
15. Upgrading 4.x to 5.0 with custom `javax.*` plugins or an etcd metadata store.

Runbooks (backlog emergency, bookie read-only, hot bundle): [references/operations.md](references/operations.md).

## Sources

Apache Pulsar docs (read Oct 2026, site default 5.0.x; 4.0.x / 4.2.x where named), under
https://pulsar.apache.org/docs/: `concepts-messaging`, `concepts-architecture-overview`,
`concepts-broker-load-balancing-concepts`, `cookbooks-retention-expiry` (and 4.2.x), `tiered-storage-overview`,
`concepts-replication`, `administration-geo`, `schema-understand`, `security-overview`, `functions-concepts`,
`reference-metrics`, `4.0.x/administration-metadata-store`, `4.2.x/administration-metadata-store`; plus
https://pulsar.apache.org/contribute/release-policy/.

Source at tags v4.0.14, v4.2.5, v5.0.1 (https://github.com/apache/pulsar): `conf/broker.conf`,
`ServiceConfiguration`, `ProducerConfigurationData`, `ConsumerConfigurationData`, `ClientConfigurationData`,
`ProducerImpl`, `RetryMessageUtil`, `KeySharedPolicy`, `CmdNamespaces`, `CmdTopics`; release notes v5.0.0 and
v5.0.0-M1 (https://github.com/apache/pulsar/releases); https://github.com/apache/pulsar-connectors;
https://github.com/apache/flink-connector-pulsar.

Ecosystem: https://docs.databricks.com/aws/en/connect/streaming/pulsar;
https://github.com/streamnative/pulsar-spark; https://github.com/streamnative/pulsar-io-lakehouse;
https://github.com/streamnative/pulsar-io-cloud-storage; https://github.com/streamnative/kop (archived);
https://docs.streamnative.io/cloud/overview/data-streaming-engine (vendor);
https://kafka.apache.org/42/getting-started/upgrade/ (share groups production-ready in 4.2);
https://debezium.io/documentation/reference/stable/operations/debezium-server.html (Pulsar sink).
