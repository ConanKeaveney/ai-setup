# Pulsar operations: defaults, admin CLI, metrics, runbooks

## 1. Broker defaults by version

Read from `conf/broker.conf` at tags v4.0.14, v4.2.5 and v5.0.1, cross-checked with
`ServiceConfiguration.java` (the code default wins when `broker.conf` omits a key). All of these can be
overridden per namespace and, with `topicLevelPoliciesEnabled=true` (default), per topic.

| Key | 4.0.14 | 4.2.5 | 5.0.1 |
|---|---|---|---|
| `defaultRetentionTimeInMinutes` / `defaultRetentionSizeInMB` | 0 / 0 | 0 / 0 | 0 / 0 |
| `backlogQuotaDefaultLimitBytes` / `...LimitSecond` | -1 / -1 | -1 / -1 | -1 / -1 |
| `backlogQuotaDefaultRetentionPolicy` | producer_request_hold | same | same |
| `backlogQuotaCheckIntervalInSeconds` | 60 | 60 | 60 |
| `ttlDurationDefaultInSeconds` | 0 | 0 | 0 |
| `subscriptionExpirationTimeMinutes` | 0 | 0 | 0 |
| `brokerDeleteInactiveTopicsEnabled` / `...Mode` / `...FrequencySeconds` | true / delete_when_no_subscriptions / 60 | same | same |
| `allowAutoTopicCreation` / `...Type` / `defaultNumPartitions` | true / non-partitioned / 1 | same | same |
| `allowAutoSubscriptionCreation` | true | true | true |
| `managedLedgerDefaultEnsembleSize` / `WriteQuorum` / `AckQuorum` | 2 / 2 / 2 | same | same |
| `managedLedgerMaxEntriesPerLedger` | 50000 | 50000 | 50000 |
| `managedLedgerMin/MaxLedgerRolloverTimeMinutes` | 10 / 240 | same | same |
| `managedLedgerMaxSizePerLedgerMbytes` | 2048 | 2048 | 2048 |
| `managedLedgerCacheSizeMB` | 1/5 of direct memory (min 64) | same | same |
| `managedLedgerOffloadAutoTriggerSizeThresholdBytes` / `...ThresholdInSeconds` | -1 / -1 | same | same |
| `managedLedgerOffloadDeletionLagMs` | 14400000 (4 h) | same | same |
| `managedLedgerDataReadPriority` | tiered-storage-first | same | same |
| `defaultNumberOfNamespaceBundles` | **4** | **4** | **32** |
| `loadManagerClassName` | ModularLoadManagerImpl | same | same |
| `loadBalancerLoadSheddingStrategy` | ThresholdShedder | ThresholdShedder | **AvgShedder** |
| `loadBalancerNamespaceBundleMaxTopics` / `MaxSessions` / `MaxMsgRate` / `MaxBandwidthMbytes` | 1000 / 1000 / 30000 / 100 | same | same |
| `loadBalancerNamespaceMaximumBundles` | 128 | 128 | 128 |
| `loadBalancerBrokerOverloadedThresholdPercentage` | 85 | 85 | 85 |
| `schemaCompatibilityStrategy` | FULL | FULL | FULL |
| `isAllowAutoUpdateSchemaEnabled` | true | true | true |
| `delayedDeliveryEnabled` / `delayedDeliveryTickTimeMillis` | true / 1000 | same | same |
| `delayedDeliveryTrackerFactoryClassName` | InMemoryDelayedDeliveryTrackerFactory | same | same |
| `maxUnackedMessagesPerConsumer` / `PerSubscription` | 50000 / 200000 | same | same |
| `acknowledgmentAtBatchIndexLevelEnabled` | **false** | **true** | **true** |
| `subscriptionKeySharedUseConsistentHashing` / replica points | true / 100 | same | same |
| `keySharedLookAheadMsgInReplayThresholdPerConsumer` / `PerSubscription` | 2000 / 20000 | 2000 / 20000 | **4000 / 40000** |
| `dispatcherMaxReadBatchSize` | 100 | 100 | **500** |
| `brokerDeduplicationEnabled` | false | false | false |
| `transactionCoordinatorEnabled` | false | false | false |
| `enableReplicatedSubscriptions` / snapshot ms | true / 1000 | same | same |
| `authenticationEnabled` / `authorizationEnabled` | false / false | same | same |
| `maxMessageSize` | 5242880 | same | same |
| `maxProducersPerTopic`, `maxConsumersPerSubscription`, `maxTopicsPerNamespace` | 0 (unlimited) | same | same |
| `exposeTopicLevelMetricsInPrometheus` / `exposeConsumerLevelMetricsInPrometheus` | true / false | same | same |
| `exposeBundlesMetricsInPrometheus` / `exposeSubscriptionBacklogAgeInPrometheus` | false / false | same | same |
| `brokerServiceCompactionThresholdInBytes` | 0 (auto-compaction off) | same | same |

## 2. `pulsar-admin` cheat sheet (command names checked in v4.2.5 source)

```bash
# Inspect
pulsar-admin tenants list
pulsar-admin namespaces list my-tenant
pulsar-admin namespaces policies my-tenant/my-ns              # every policy on the namespace
pulsar-admin topics list my-tenant/my-ns
pulsar-admin topics stats          persistent://my-tenant/my-ns/t   # rates, backlog per subscription, consumers
pulsar-admin topics partitioned-stats persistent://my-tenant/my-ns/t --per-partition
pulsar-admin topics stats-internal persistent://my-tenant/my-ns/t   # ledgers, cursors, mark-delete positions
pulsar-admin topics subscriptions  persistent://my-tenant/my-ns/t
pulsar-admin topics peek-messages  persistent://my-tenant/my-ns/t -s my-sub -n 5
pulsar-admin topics analyze-backlog persistent://my-tenant/my-ns/t -s my-sub

# Create
pulsar-admin tenants create my-tenant --admin-roles team-a --allowed-clusters us-east
pulsar-admin namespaces create my-tenant/my-ns --bundles 16
pulsar-admin topics create-partitioned-topic persistent://my-tenant/my-ns/t -p 12
pulsar-admin topics update-partitioned-topic persistent://my-tenant/my-ns/t -p 24   # increase only
pulsar-admin topics create-subscription persistent://my-tenant/my-ns/t -s my-sub     # before producing

# Policies (namespace; most also exist as `pulsar-admin topicPolicies set-...`)
pulsar-admin namespaces set-retention     my-tenant/my-ns --size 10G --time 3d
pulsar-admin namespaces set-backlog-quota my-tenant/my-ns --limit 50G --policy producer_exception
pulsar-admin namespaces set-message-ttl   my-tenant/my-ns --messageTTL 604800
pulsar-admin namespaces set-subscription-expiration-time my-tenant/my-ns --time 10080
pulsar-admin namespaces set-offload-threshold my-tenant/my-ns --size 10G
pulsar-admin namespaces set-persistence   my-tenant/my-ns -e 3 -w 3 -a 2 -r 0
pulsar-admin namespaces set-schema-compatibility-strategy my-tenant/my-ns --compatibility BACKWARD_TRANSITIVE
pulsar-admin namespaces set-is-allow-auto-update-schema   my-tenant/my-ns --disable
pulsar-admin namespaces set-schema-validation-enforce     my-tenant/my-ns --enable
pulsar-admin namespaces set-deduplication my-tenant/my-ns --enable
pulsar-admin namespaces set-clusters      my-tenant/my-ns --clusters us-east,eu-west
pulsar-admin namespaces grant-permission  my-tenant/my-ns --role svc-a --actions produce,consume

# Fix backlog
pulsar-admin topics unsubscribe   persistent://my-tenant/my-ns/t -s stale-sub
pulsar-admin topics clear-backlog persistent://my-tenant/my-ns/t -s my-sub
pulsar-admin topics skip          persistent://my-tenant/my-ns/t -s my-sub -n 1000
pulsar-admin topics expire-messages-all-subscriptions persistent://my-tenant/my-ns/t -t 3600
pulsar-admin topics reset-cursor  persistent://my-tenant/my-ns/t -s my-sub -t 2h
pulsar-admin namespaces clear-backlog my-tenant/my-ns -s stale-sub   # one subscription across the namespace

# Load
pulsar-admin namespaces unload       my-tenant/my-ns
pulsar-admin namespaces split-bundle my-tenant/my-ns -b 0x00000000_0x40000000
pulsar-admin topics unload persistent://my-tenant/my-ns/t
pulsar-admin topics offload persistent://my-tenant/my-ns/t -s 1G
pulsar-admin topics compact persistent://my-tenant/my-ns/t
```

`set-persistence`: `-e` ensemble, `-w` write quorum, `-a` ack quorum, `-r` mark-delete max rate.
`create-subscription -m` defaults to `latest`; pass `-m earliest` to start from retained data.
`reset-cursor -t` goes back a relative time from now. Rate and unacked limits: `set-publish-rate`,
`set-dispatch-rate`, `set-max-unacked-messages-per-consumer`, `set-max-unacked-messages-per-subscription`.

## 3. Metrics (names from the 5.0.x metrics reference)

| Area | Metrics | Alert idea |
|---|---|---|
| Backlog | `pulsar_msg_backlog`, `pulsar_subscription_back_log`, `pulsar_subscription_back_log_no_delayed`, `pulsar_storage_backlog_size` | Per-subscription growth over N minutes |
| Backlog age | `pulsar_storage_backlog_age_seconds`, `pulsar_subscription_storage_backlog_age_seconds` (needs `exposeSubscriptionBacklogAgeInPrometheus=true`) | Age above SLA; age above a day for any subscription = probable orphan |
| Quota | `pulsar_storage_backlog_quota_limit`, `pulsar_storage_backlog_quota_limit_time`, `pulsar_storage_backlog_quota_exceeded_evictions_total` | Size above 80% of limit |
| Rates | `pulsar_rate_in`, `pulsar_rate_out`, `pulsar_throughput_in/out`, `pulsar_broker_rate_in/out` | Out below in for a sustained window |
| Storage | `pulsar_storage_size`, `pulsar_storage_logical_size`, `pulsar_storage_offloaded_size` | Growth without matching traffic growth |
| Consumers | `pulsar_subscription_unacked_messages`, `pulsar_subscription_blocked_on_unacked_messages`, `pulsar_subscription_msg_rate_redeliver`, `pulsar_subscription_consumers_count`, `pulsar_subscription_delayed` | Blocked = 1; redeliver rate above a floor; zero consumers on a subscription with backlog |
| Latency | `pulsar_broker_publish_latency`, `pulsar_storage_write_latency_le_*`, `pulsar_storage_ledger_write_latency_*` | p99 publish above budget |
| Bookies | `bookie_journal_JOURNAL_ADD_ENTRY`, `bookie_ledger_writable_dirs`, `bookie_SERVER_STATUS` | Status 0 (read-only) pages someone |
| Load balancing | `pulsar_lb_unload_bundle_total`, `pulsar_lb_bundles_split_total` (needs `exposeBundlesMetricsInPrometheus=true`); extensible LM `pulsar_lb_unload_broker_breakdown_total`, `pulsar_lb_bundles_split_breakdown_total` | Unload rate spikes correlating with client latency |
| Cache | `pulsar_ml_cache_hits_rate`, `pulsar_ml_cache_misses_rate`, `pulsar_ml_cache_used_size` | Misses rising = catch-up readers |
| Replication | `pulsar_replication_backlog`, `pulsar_replication_delay_in_seconds`, `pulsar_replication_connected_count` | Delay above RPO |

Cardinality: topic-level metrics are on by default; with very many topics set
`exposeTopicLevelMetricsInPrometheus=false` and work from namespace aggregates plus `topics stats` on demand.

## 4. Runbooks

### Backlog emergency (bookie disk climbing)
1. Find the top subscriptions by backlog size and age (`pulsar_subscription_back_log`, age metric, or
   `topics stats` per hot topic).
2. For each: is a consumer connected (`consumers` in stats)? Is `blockedSubscriptionOnUnackedMsgs` true?
3. Orphaned (owner gone, nobody connected for days): confirm with the owning team, then `unsubscribe`.
4. Live but slow: scale consumers (Shared / Key_Shared), raise `receiverQueueSize` only if handlers are fast,
   check for redelivery loops (`msg_rate_redeliver`) and poison messages (add a DLQ).
5. Loss acceptable: `expire-messages` or `clear-backlog` for that subscription only.
6. Afterwards: set a backlog quota and an age alert on the namespace so it cannot recur silently.

### Bookie read-only
1. `bookie_SERVER_STATUS`=0 or `bookie_ledger_writable_dirs`=0: disk crossed the bookie's usage threshold.
2. Free space by removing what pins it (runbook above). Disk returns only after ledger trim and bookie GC.
3. Add bookies if the steady-state size simply grew. Do not delete ledger files by hand.
4. Writes resume when enough bookies in each ensemble are writable; check `pulsar_broker_publish_latency`.

### Hot bundle / hot broker
1. Find the broker with high CPU or bandwidth and its bundles (`pulsar-admin broker-stats topics` or
   load-report).
2. A single bundle carrying many busy topics: `split-bundle`, then let the load manager move a half; or unload.
3. A single non-partitioned topic carrying the load: it cannot be split; make it partitioned (new topic,
   migrate producers then consumers).
4. Persistent imbalance: tune the shedder, or consider the extensible load manager (since 3.0).

### Consumers connected, nothing delivered
1. `blockedSubscriptionOnUnackedMsgs` / `blockedConsumerOnUnackedMsgs` true: a consumer is not acking
   (handler bug, forgotten ack on an error path). Limits are 50,000 per consumer, 200,000 per subscription.
2. Key_Shared: one consumer holds a hot key and is slow; look-ahead limit reached. Check the draining-hash stats
   in `topics stats`.
3. Delayed messages: `pulsar_subscription_delayed` high and `back_log_no_delayed` low means waiting, not stuck.
