# Kafka to Pulsar: concept map, glossary, surprises

Defaults are from Pulsar v4.0.14 / v4.2.5 / v5.0.1 source (`broker.conf`, client config classes) unless a
version is named. Kafka facts are Kafka 4.x.

## 1. Full concept map

| Kafka | Pulsar | Notes |
|---|---|---|
| Cluster | Cluster (brokers + bookies + metadata store) inside an **instance** | An instance is one or more clusters sharing a configuration store |
| (none) | **Tenant** | Admin roles, allowed clusters |
| (naming convention) | **Namespace** | Unit of policy: retention, quotas, TTL, replication, schema rules |
| Topic | Topic `persistent://tenant/ns/name` | Non-partitioned by default when auto-created |
| Partition | Partition = internal topic `name-partition-N` | Placed independently by bundle hash; can be increased, not decreased |
| Partition leader + ISR | Owning broker (serving) + BookKeeper ensemble (storage) | Serving and storage are separate; no replica catch-up on broker move |
| `replication.factor` / `min.insync.replicas` | Write quorum Qw / ack quorum Qa (ensemble E) | Defaults E/Qw/Qa = 2/2/2 |
| Segment file | BookKeeper **ledger** (managed-ledger segment) | Ledger striped across E bookies; rolls at 50k entries / 240 min / 2 GB |
| Record batch | Batch = one **entry** | Ack and redelivery act on the entry unless batch-index ack is on |
| Consumer group | **Subscription** | Durable cursor stored by the broker |
| Group member assignment | Subscription **type** (Exclusive, Failover, Shared, Key_Shared) | Chosen by the consumer at subscribe time; all consumers on a subscription must agree |
| Committed offset | Mark-delete position + individually-deleted ranges | "Holes" of acked messages above the mark-delete are tracked |
| Consumer lag | Subscription **backlog** (`msgBacklog`, backlog size, backlog age) | Backlog is what pins storage |
| `auto.offset.reset` | `subscriptionInitialPosition` (Latest default) | Only on creation |
| `seek` / `kafka-consumer-groups --reset-offsets` | `consumer.seek(...)`, `pulsar-admin topics reset-cursor` | By MessageId or publish time |
| Static membership / sticky assignor | Failover with `priorityLevel`, Key_Shared STICKY ranges | |
| Rebalance | None for Shared; per-key handover in Key_Shared; failover switch | No stop-the-world group rebalance |
| `retention.ms` / `retention.bytes` | Retention (acked data only) + backlog quota (unacked) + TTL | See SKILL.md retention section |
| `cleanup.policy=compact` | Topic compaction (manual or `brokerServiceCompactionThresholdInBytes`, default 0 = off) | Consumers opt in with `readCompacted(true)`; compacted view plus uncompacted tail |
| Tombstone (null value) | Message with key and empty payload | `topicCompactionRetainNullKey=false` |
| Idempotent producer / EOS | Broker dedup + producer sequence ids; transactions | Both off by default |
| `max.in.flight.requests` | `maxPendingMessages` + client `memoryLimit` | |
| `linger.ms` / `batch.size` | `batchingMaxPublishDelay` 1 ms / `batchingMaxBytes` 128 KB / `batchingMaxMessages` 1000 | |
| `message.max.bytes` | `maxMessageSize` 5 MB; producer chunking for larger | |
| Partitioner (murmur2) | `MessageRouter` / `hashingScheme` (`JavaStringHash` default, or `Murmur3_32Hash`) | Placement differs from Kafka either way |
| Kafka Connect | Pulsar IO (sources and sinks on function workers) + Kafka Connect Adaptor | Connectors live in `apache/pulsar-connectors` from 5.0 |
| Debezium on Connect | Pulsar IO Debezium sources (MySQL, MariaDB, Postgres, MongoDB, SQL Server, Oracle); Debezium Server `debezium.sink.type=pulsar` | |
| Kafka Streams / ksqlDB | Pulsar Functions (Java, Python, Go) | Window functions Java only |
| Schema Registry (subjects) | Per-topic schema registry in BookKeeper | No global subject namespace |
| MirrorMaker 2 / cluster linking | Geo-replication | Built in, async, per namespace or topic |
| KRaft controllers | Metadata store (ZooKeeper / Oxia) + configuration store | |
| Tiered storage (KIP-405) | Tiered storage offload | Ledger format in object storage |
| Share groups (KIP-932, production-ready in Kafka 4.2) | Shared / Key_Shared subscriptions | Pulsar also has delayed delivery, DLQ, retry topics |
| Quotas (client-id / user) | Publish / dispatch / subscribe rate limits, resource groups | Per namespace or topic |
| ACLs | Role-based permissions on namespace or topic (produce, consume, functions, sources, sinks, packages) | Tenant admins delegate |

## 2. Glossary (Pulsar terms a Kafka engineer will meet)

- **Bookie**: a BookKeeper storage server. Holds ledger fragments; has a journal and ledger storage.
- **Ledger**: append-only, single-writer log replicated across an ensemble of bookies; immutable once closed.
- **Entry**: the unit written to a ledger; one message or one batch.
- **Ensemble / Qw / Qa**: bookies a ledger is striped across / copies written per entry / copies that must ack.
- **Managed ledger**: the broker library that presents one topic as a chain of ledgers plus cursors.
- **Cursor**: a subscription's position in a managed ledger; persisted in a ledger of its own.
- **Mark-delete position**: everything at or before it is acked. Individually acked messages beyond it are tracked separately.
- **Backlog**: messages after a subscription's mark-delete position that are not acked.
- **Bundle**: a hash range of a namespace; the unit a broker owns and the load manager moves.
- **Unload**: release a bundle so another broker takes it; clients reconnect.
- **Configuration store**: instance-wide metadata (tenants, namespaces, clusters, partitioned-topic metadata).
- **Proxy**: optional stateless gateway in front of brokers (useful on Kubernetes or across networks).
- **Reader**: a consumer with a non-durable cursor that never acks; position chosen by MessageId.
- **TableView**: a client-side key-to-latest-value map built from a (usually compacted) topic.
- **Function worker**: runs Pulsar Functions and Pulsar IO connectors (thread, process or Kubernetes runtime).
- **System topics**: internal topics such as `__change_events` (topic policies) and transaction logs.
- **Non-persistent topic**: in-memory only; no durability.
- **Scalable topic** (5.0): segments split and merge automatically; used through the V5 client.

## 3. Behaviours that surprise Kafka users

1. **Data with no subscription is not kept.** Default retention 0 means a topic with no subscription keeps
   nothing once the ledger trims. Kafka keeps it for `retention.ms` regardless.
2. **Unacked data is kept forever.** No backlog quota, no TTL, no subscription expiry by default. Kafka would
   have deleted it after `retention.ms` and the consumer would see an out-of-range reset.
3. **A subscription is a server-side object.** Turning a consumer off does not remove it; delete it with
   `pulsar-admin topics unsubscribe`.
4. **Acks are per message.** A Shared consumer can ack out of order; the broker tracks holes. Many holes cost
   cursor storage (bounded by `managedLedgerMaxUnackedRangesToPersist`).
5. **No consumer-side commit loop.** Ack after processing; acks are grouped for 100 ms and sent async.
6. **Topics appear on first use** (auto-create on) and **vanish when idle** with no subscriptions
   (`brokerDeleteInactiveTopicsEnabled=true`).
7. **Partition count is not the parallelism cap** for Shared and Key_Shared.
8. **Ordering depends on subscription type**, not just partitioning. Shared gives none.
9. **Moving load is cheap.** Losing a broker moves bundles; no data copy, so no long under-replicated window.
   Losing a bookie triggers BookKeeper auto-recovery to re-replicate ledgers.
10. **Batch boundaries leak into semantics**: nack, ack timeout and partial acks redeliver whole batches
    unless batch-index ack is on (default on from 4.2.5; off in 4.0).
11. **Delayed delivery exists** (Shared and Key_Shared only) and pins storage while waiting.
12. **Geo-replication does not move consumer positions** unless replicated subscriptions are enabled per
    subscription.
13. **Schema checks are on by default** (`FULL`), but enforcement against schema-less producers is off.

## 4. Operating both: patterns

| Need | Pattern |
|---|---|
| Service events into the lakehouse when Kafka-to-Iceberg already runs | Pulsar IO Kafka sink per topic set, one owner, alert on the bridge subscription's backlog |
| Database CDC that services also consume as events | Debezium into Kafka for the data platform; publish domain events to Pulsar from the services, not from CDC |
| Kafka-native tools on Pulsar data without a bridge | Not available in Apache Pulsar today (KoP archived); vendor KSN / Ursa only |
| One schema contract across both | Keep the schema source in a repo; register it in each system from CI |
