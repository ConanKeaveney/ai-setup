# Pulsar Java / Kotlin client

Defaults from `ClientConfigurationData`, `ProducerConfigurationData`, `ConsumerConfigurationData` at v4.2.5
(same in v4.0.14 and v5.0.1 unless noted). Builder method names checked against the v4.2.5
`pulsar-client-api` interfaces. The 5.0 `pulsar-client-v5` module is a separate API for scalable topics; the
classic client below is unchanged in 5.0.

## 1. Defaults that matter

| Area | Setting | Default |
|---|---|---|
| Client | `memoryLimit` | 64 MB (0 disables) |
| Client | `operationTimeout` / `connectionTimeout` / `lookupTimeout` | 30 s / 10 s / -1 (= operation timeout) |
| Client | `numIoThreads` / `numListenerThreads` | available processors / available processors |
| Client | `connectionsPerBroker` | 1 |
| Client | backoff initial / max | 100 ms / 60 s |
| Producer | `sendTimeout` | 30 s |
| Producer | `blockIfQueueFull` | false |
| Producer | `maxPendingMessages` | 0 = no count limit, bounded by `memoryLimit`; falls back to 1000 if the client memory limit is disabled |
| Producer | batching | on; `batchingMaxPublishDelay` 1 ms, `batchingMaxMessages` 1000, `batchingMaxBytes` 128 KB, `BatcherBuilder.DEFAULT` |
| Producer | `compressionType` | NONE |
| Producer | `hashingScheme` | JavaStringHash |
| Producer | `messageRoutingMode` | unset: keyed messages hash to a partition; unkeyed go round-robin, switching partition per batch |
| Producer | `chunkingEnabled` | false |
| Producer | `accessMode` | Shared (also Exclusive, WaitForExclusive, ExclusiveWithFencing) |
| Consumer | `subscriptionType` | Exclusive |
| Consumer | `subscriptionInitialPosition` | Latest |
| Consumer | `receiverQueueSize` | 1000; `maxTotalReceiverQueueSizeAcrossPartitions` 50,000 |
| Consumer | `acknowledgmentGroupTime` | 100 ms; `maxAcknowledgmentGroupSize` 1000 |
| Consumer | `ackTimeout` | 0 (off) |
| Consumer | `negativeAckRedeliveryDelay` | 1 min |
| Consumer | `enableRetry` | false |
| Consumer | `enableBatchIndexAcknowledgment` | **false in 4.0.14, true in 4.2.5 and 5.0.1** (broker must also enable it) |
| Consumer | `readCompacted` | false |
| Consumer | `autoUpdatePartitions` | true, every 60 s |
| Consumer | `expireTimeOfIncompleteChunkedMessage` / `maxPendingChunkedMessage` | 1 min / 10 |

## 2. Producer

```java
PulsarClient client = PulsarClient.builder()
    .serviceUrl("pulsar+ssl://pulsar.example.internal:6651")
    .authentication(AuthenticationFactory.token(System.getenv("PULSAR_TOKEN")))
    .memoryLimit(128, SizeUnit.MEGA_BYTES)
    .build();                                    // one per process; share it

Producer<OrderEvent> producer = client.newProducer(Schema.AVRO(OrderEvent.class))
    .topic("persistent://orders/events/order-updated")
    .producerName("order-service-updated")       // stable name: needed for broker dedup
    .compressionType(CompressionType.LZ4)
    .blockIfQueueFull(true)                      // back-pressure instead of ProducerQueueIsFullError
    .batcherBuilder(BatcherBuilder.KEY_BASED)    // required if any subscription is Key_Shared
    .sendTimeout(30, TimeUnit.SECONDS)
    .create();

producer.newMessage()
    .key(order.id())                             // drives partition and Key_Shared routing
    .value(order)
    .property("source", "order-service")
    .sendAsync()
    .whenComplete((id, ex) -> { if (ex != null) log.error("publish failed", ex); });

producer.newMessage().value(reminder).deliverAfter(15, TimeUnit.MINUTES).sendAsync(); // Shared/Key_Shared only
```

Rules:
- `sendAsync` keeps order per producer. When the oldest pending message passes `sendTimeout`, the producer
  fails **every** pending message with a `TimeoutException`; handle errors per future and do not resend
  blindly out of order.
- Retrying after a `TimeoutException` can duplicate. For no duplicates enable broker deduplication on the
  namespace and keep `producerName` stable across restarts.
- Do not call blocking `send()` from inside another future's callback or a message listener; those run on
  client threads.
- Large messages: either raise nothing and enable chunking (`enableChunking(true)` with
  `enableBatching(false)`, persistent topics only), or store the payload in S3 and send a pointer.
- Close order on shutdown: `producer.flush()`, `producer.close()`, then `client.close()`.

## 3. Consumer with nack backoff, DLQ and retry topic

```java
Consumer<OrderEvent> consumer = client.newConsumer(Schema.AVRO(OrderEvent.class))
    .topic("persistent://orders/events/order-updated")
    .subscriptionName("billing-service")
    .subscriptionType(SubscriptionType.Shared)
    .subscriptionInitialPosition(SubscriptionInitialPosition.Earliest)
    .receiverQueueSize(50)                       // smaller prefetch spreads work across slow handlers
    .negativeAckRedeliveryBackoff(MultiplierRedeliveryBackoff.builder()
        .minDelayMs(1_000).maxDelayMs(60_000).multiplier(2).build())
    .enableRetry(true)                           // creates <topic>-billing-service-RETRY
    .deadLetterPolicy(DeadLetterPolicy.builder()
        .maxRedeliverCount(5)                    // <topic>-billing-service-DLQ
        .initialSubscriptionName("billing-dlq")  // without it DLQ messages can be deleted
        .build())
    .subscribe();

while (running) {
    Message<OrderEvent> msg = consumer.receive();
    try {
        handle(msg.getValue());
        consumer.acknowledge(msg);
    } catch (TransientException e) {
        consumer.reconsumeLater(msg, 30, TimeUnit.SECONDS);   // counted in RECONSUMETIMES; DLQ after max
    } catch (Exception e) {
        consumer.negativeAcknowledge(msg);                    // in-memory counter, may reset
    }
}
```

- Exactly one of ack, nack or reconsumeLater per message, on every code path. A missing ack blocks dispatch
  once 50,000 unacked messages sit on the consumer.
- DLQ and retry topics are ordinary topics: give them retention, a backlog quota and an owner.
- The docs list retry-letter support for Shared subscriptions and DLQ for Shared and Key_Shared.

## 4. Key_Shared

```java
client.newConsumer(Schema.AVRO(OrderEvent.class))
    .topic("persistent://orders/events/order-updated")
    .subscriptionName("ledger-writer")
    .subscriptionType(SubscriptionType.Key_Shared)
    .keySharedPolicy(KeySharedPolicy.autoSplitHashRange())   // default mode
    .subscribe();
```

- Producers: `BatcherBuilder.KEY_BASED` or `enableBatching(false)`.
- Since 4.0, adding a consumer does not reorder a key: the key moves only when its unacked messages drain.
  A consumer that never acks holds its keys and stalls look-ahead for everyone.
- `KeySharedPolicy.stickyHashRange().ranges(Range.of(0, 32767))` pins ranges (hash space 0..65535);
  coverage gaps leave keys undelivered.
- `.setAllowOutOfOrderDelivery(true)` on the policy relaxes ordering for throughput.

## 5. Readers and TableView

```java
Reader<byte[]> reader = client.newReader()
    .topic("persistent://orders/events/order-updated")
    .startMessageId(MessageId.earliest)          // or a stored MessageId, or startMessageFromRollbackDuration
    .create();
```

Readers do not ack and do not hold data: only retention keeps what they replay. `client.newTableView(...)`
builds a key-to-latest-value map from a (preferably compacted) topic.

## 6. Kotlin

```kotlin
import kotlinx.coroutines.future.await

suspend fun publish(producer: Producer<OrderEvent>, e: OrderEvent): MessageId =
    producer.newMessage().key(e.id).value(e).sendAsync().await()

suspend fun consume(consumer: Consumer<OrderEvent>) {
    while (currentCoroutineContext().isActive) {
        val msg = consumer.receiveAsync().await()
        runCatching { handle(msg.value) }
            .onSuccess { consumer.acknowledgeAsync(msg).await() }
            .onFailure { consumer.negativeAcknowledge(msg) }
    }
}
```

- Never `runBlocking` inside a `messageListener`; it blocks a client listener thread.
- `Schema.AVRO(Class)` and `Schema.JSON(Class)` reflect on the class: Kotlin data classes need nullable or
  defaulted fields that match the Avro schema; prefer generated Avro classes or explicit `SchemaDefinition`.
- Cancellation does not cancel the underlying `CompletableFuture`; close the consumer to stop receives.

## 7. Framework options

- `apache/pulsar-client-reactive` (Reactor API; 0.7.0, Jun 2025).
- Spring for Apache Pulsar (Spring Boot auto-configuration, `PulsarTemplate`, `@PulsarListener`); check the
  Pulsar client version it pins against your brokers.
