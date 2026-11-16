# Operations and troubleshooting

Version tags: **[2.x]**, **[3.0+]**, **[AWS]**. Untagged = OpenSearch 2.x/3.x.
Approach (borrowed from elastic/agent-skills `elasticsearch-cluster-health`): stay **read-only
first**, narrow to **one index and one shard**, separate the **trigger** (`unassigned_info.reason`)
from the **root cause** (allocation deciders), quote the decider text, and only then propose a change.

## 1. Cluster architecture details

| Role | Purpose | Sizing notes |
|---|---|---|
| `cluster_manager` (formerly `master`, renamed 2.0) | Cluster state, shard allocation, mappings | 3 dedicated (odd count, quorum). Small heap but keep CPU < 50% ([AWS] alarm) |
| `data` | Holds shards, runs index/search | Heap 50% RAM ≤ ~32 GiB. Rest is page cache |
| `ingest` | Runs ingest pipelines | Separate only if pipelines are heavy |
| coordinating-only (`node.roles: []`) | Scatter/gather, agg reduce | Helps when aggregation reduce or many clients overload data nodes. [AWS] "dedicated coordinator nodes" |
| `remote_cluster_client` | Cross-cluster search/replication | |
| `warm` / `search` | Tiering and searchable snapshots; reader/writer separation in newer versions | Check the version's docs. Experimental in places |

Shard copy placement: primary and replica never share a node. Use zone awareness
(`cluster.routing.allocation.awareness.attributes: zone`) for multi-AZ. [AWS] "Multi-AZ with
Standby" = 3 AZs, 2 active, needs 2 replicas.

Durability pieces: translog (`index.translog.durability: request` fsyncs before ack; `async`
every `sync_interval` 5s), snapshots to a repository (S3), and [2.10+] remote-backed storage
(translog and segments to remote, fixed at cluster bootstrap, needs segment replication).

## 2. `_cat` / `_cluster` cheat-sheet

```
GET _cluster/health?pretty                       # status, active_shards, unassigned_shards, pending_tasks
GET _cluster/health?level=indices                # which index is red/yellow
GET _cat/indices?v&s=store.size:desc&h=health,index,pri,rep,docs.count,docs.deleted,store.size,pri.store.size
GET _cat/shards?v&s=store:desc&h=index,shard,prirep,state,docs,store,node,unassigned.reason
GET _cat/allocation?v                            # shards + disk per node
GET _cat/nodes?v&h=name,node.role,heap.percent,ram.percent,cpu,load_1m,disk.used_percent
GET _cat/thread_pool/write,search,get?v&h=node_name,name,active,queue,rejected,completed
GET _cat/segments/<index>?v                      # segment count/size, deleted docs per segment
GET _cat/recovery?v&active_only=true             # ongoing shard recoveries
GET _cat/pending_tasks?v
GET _cat/cluster_manager?v                       # (_cat/master is the deprecated alias)
GET _cat/fielddata?v
GET _cat/aliases?v ; GET _cat/templates?v
POST _cluster/allocation/explain                 # explains first unassigned shard; or pass {"index","shard","primary"}
GET _nodes/stats/jvm,breaker,thread_pool,indices # GC, breakers, refresh/merge/indexing stats
GET _nodes/hot_threads                           # what is burning CPU now
GET _tasks?actions=*search*&detailed=true        # long-running searches; POST _tasks/<id>/_cancel
GET <index>/_stats/refresh,merge,indexing,search
GET _cluster/settings?include_defaults=true&flat_settings=true
```

## 3. Runbooks

### Red cluster (a primary is unassigned)
1. `GET _cluster/health?level=indices` → pick the red index.
2. `GET _cat/shards/<index>?v&h=index,shard,prirep,state,unassigned.reason,node`.
3. `POST _cluster/allocation/explain {"index":"<i>","shard":N,"primary":true}`.
   - `no_valid_shard_copy` → every copy is gone. Bring the departed node back, or restore that
     index from snapshot. `allocate_stale_primary` (stale data) / `allocate_empty_primary` (empty
     shard) **lose data**. Use them only with explicit sign-off.
   - Decider says disk / filter / awareness → fix that and the primary allocates.
4. [AWS] Red blocks automated snapshots (`AutomatedSnapshotFailure`). OR1-family auto-restores
   red shards from S3.
5. Writes to a red index fail for docs routed to the missing shard. Searches return partial
   results (`_shards.failed`).

### Yellow cluster (a replica is unassigned)
- `NODE_LEFT` + within `index.unassigned.node_left.delayed_timeout` (default **1m**) → wait.
- Replicas ≥ data nodes (a 1-node cluster with 1 replica is always yellow) → lower
  `number_of_replicas` or add nodes.
- Disk above the **85% low watermark** → replicas won't allocate there.
- Allocation retried 5 times (`index.allocation.max_retries`) → fix the cause, then
  `POST _cluster/reroute?retry_failed=true`.
- `cluster.routing.allocation.enable` left at `primaries`/`none` after maintenance → reset it to `all`.

### Disk watermarks
Defaults: low **85%** (no new shards to the node), high **90%** (relocate shards away),
flood stage **95%** (`index.blocks.read_only_allow_delete` on every index with a shard there.
**Auto-released** once usage falls below high). Fix: delete or snapshot old indexes, add nodes or
storage, or reduce replicas temporarily. [AWS] alarm `FreeStorageSpace` ≤ 25% of the node and
`ClusterIndexWritesBlocked` ≥ 1.

### Heap, GC and circuit breakers
Breaker defaults: parent `indices.breaker.total.limit` **95% heap** (with
`use_real_memory: true`, else 70%), fielddata **40%**, request **60%**, in-flight requests
**100%**. Script compilations: 75 per 5 min per context.
- `circuit_breaking_exception [parent]` → overall heap is too full. Find the culprit with
  `_nodes/stats/breaker` (which breaker has `tripped` > 0), `_cat/fielddata`, and in-flight tasks.
- Typical culprits: `terms` with a large `size` over high-cardinality fields, `fielddata: true`
  on text, deep `from`, huge bulk bodies, too many shards per node (per-shard overhead).
- [AWS] alarms: `JVMMemoryPressure` ≥ 95% and `OldGenJVMMemoryPressure` ≥ 80% (1 min ×3).
  AWS sets heap to half RAM up to 32 GiB. Scale vertically to 64 GiB RAM, then horizontally.

### 429 / rejected execution
- `_cat/thread_pool` shows `rejected` rising on `write` or `search`.
- Write: too many concurrent small bulks, hot shards (skewed routing), slow disks, merge
  throttling. Use fewer, larger bulks (5–15 MiB), retry 429s with exponential backoff + jitter,
  and spread primaries evenly.
- Search: too many shards per query, expensive aggs, traffic spikes. [2.4+] search backpressure
  (`search_backpressure.mode`: `monitor_only` default, `enforced`, `disabled`) can cancel hogs.
  Shard indexing backpressure guards writes.
- [AWS] alarms: `ThreadpoolWriteQueue` avg ≥ 100, `ThreadpoolSearchQueue` avg ≥ 500 / max ≥ 5000,
  any increase in `Threadpool*Rejected`.

### Slow search
1. Search slow log (shard): `index.search.slowlog.threshold.query.warn: 2s` etc. (disabled `-1`
   by default). Request slow log [2.12+]: `cluster.search.request.slowlog.threshold.*`.
   [AWS] you must enable log publishing **and** set thresholds or nothing reaches CloudWatch.
2. `GET _nodes/hot_threads`, `GET _tasks?actions=*search*&detailed`.
3. `profile: true` (see query-dsl-aggregations.md, section 7).
4. Common fixes: filter context, time-bounded index targeting, tenant routing, fewer/larger
   shards, `eager_global_ordinals` for hot keyword aggs, avoid scripts and leading wildcards, and
   check skew (one hot node: `_cat/allocation`, `_cat/shards` sorted by store).

### Slow indexing / freshness lag
- `GET <idx>/_stats/indexing,refresh,merge`: watch `index_time_in_millis/index_total`,
  `refresh.total_time`, `merges.current`, `merges.total_throttled_time`.
- Indexing slow log: `index.indexing.slowlog.threshold.index.warn` etc.
- Causes: tiny bulks, update-heavy load (read + reindex, deleted docs, merges), `nested` arrays,
  too many fields, ingest pipelines, refresh too frequent for the write rate, replica lag
  (segment replication: `GET _cat/segment_replication?v` [2.x]; [AWS] `ReplicationLagMaxTime`).

### Mapping explosion
Symptoms: `Limit of total fields [1000] has been exceeded`, a huge cluster state, slow
cluster-manager, high heap. Check the field count with `GET idx/_mapping`. Causes: dynamic
objects keyed by IDs, user-supplied attributes, logs with arbitrary JSON. Fix: `dynamic:
strict|false`, `flat_object` [2.7+], key/value nested pairs, or `dynamic_templates` mapping
unknown strings to `keyword` with `index: false`. Then reindex. Limits: total_fields 1000, depth
20, nested_fields 50, nested_objects 10000, field_name_length 50000.

### Too many shards
Symptoms: high heap at idle, slow cluster-state updates, `this action would add [N] total shards,
but this cluster currently has [M]/[1000×nodes] maximum shards open`. Rule: ≤ 25 shards per GiB
heap. [AWS] alarm `shards.active ≥ 25 × heap GiB × data nodes`. Fix: ISM delete/retention, daily
→ weekly/monthly indexes, rollover on size instead of age, `_shrink` read-only indexes, 1 primary
for small indexes, and close or delete empty indexes.

### Cluster-manager instability
`_cat/cluster_manager` changes, `pending_tasks` piling up. Causes: too many shards or fields
(cluster state size), underpowered dedicated managers, network partitions. Fix: 3 dedicated
managers sized for the shard count, and reduce cluster-state churn (fewer dynamic mapping updates).

## 4. Index lifecycle: templates, aliases, rollover, ISM

```json
PUT _component_template/orders-settings
{ "template": { "settings": { "number_of_shards": 3, "number_of_replicas": 1,
                              "refresh_interval": "1s", "codec": "zstd_no_dict" } } }

PUT _index_template/orders
{ "index_patterns": ["orders-*"], "priority": 100, "composed_of": ["orders-settings"],
  "template": { "mappings": { "dynamic": "strict", "properties": { "order_id": { "type": "keyword" } } } } }

POST _aliases
{ "actions": [ { "remove": { "index": "orders-v1", "alias": "orders" } },
               { "add":    { "index": "orders-v2", "alias": "orders", "is_write_index": true } } ] }
```

- Codecs [2.9+]: `zstd` and `zstd_no_dict` (docs: ~7% and ~14% better write throughput, ~30%
  storage saving for `zstd_no_dict`). `index.codec.compression_level` 1–6 (default 3).
- **Rollover** needs a write alias (`plugins.index_state_management.rollover_alias` on the index
  for ISM) or a data stream. Conditions: `min_size`, `min_primary_shard_size`, `min_doc_count`,
  `min_index_age`. **Rollover is for append-only data.** For mutable docs, see SKILL.md section 7.
- **ISM** policy = states → actions → transitions. Job interval default 5 min. Actions include
  `rollover`, `force_merge`, `replica_count`, `read_only`, `shrink`, `snapshot`, `allocation`
  (OSS hot-warm via node attributes), `warm_migration`/`cold_migration` [AWS], `delete`.
  `ism_template` auto-attaches policies to new matching indexes.

```json
PUT _plugins/_ism/policies/events-retention
{ "policy": { "description": "hot 7d → warm → delete 90d", "default_state": "hot",
  "ism_template": { "index_patterns": ["order-events-*"], "priority": 100 },
  "states": [
    { "name": "hot", "actions": [ { "rollover": { "min_primary_shard_size": "30gb", "min_index_age": "1d" } } ],
      "transitions": [ { "state_name": "warm", "conditions": { "min_index_age": "7d" } } ] },
    { "name": "warm", "actions": [ { "force_merge": { "max_num_segments": 1 } }, { "warm_migration": {} } ],
      "transitions": [ { "state_name": "delete", "conditions": { "min_index_age": "90d" } } ] },
    { "name": "delete", "actions": [ { "delete": {} } ] } ] } }
```
(`warm_migration` is [AWS] UltraWarm. On OSS use `allocation: {require: {box_type: warm}}`.)

- **Reindex / mapping change**: create `v2` with new mappings → `POST _reindex`
  (`?slices=auto&wait_for_completion=false`, track via `_tasks`) with refresh off and replicas 0 on
  the target → catch up the delta (replay from Kafka by offset or timestamp, or a second
  `_reindex` with a `range` on `updated_at`) → restore settings → atomic alias swap. Mutable
  data needs the catch-up step, or you lose updates made during the copy.
- `_split` (increase primaries by a factor) and `_shrink` (decrease to a factor) need a
  read-only source. `_shrink` also needs all copies on one node.

## 5. Storage tiers

| Tier | Where | Writes? | Notes |
|---|---|---|---|
| Hot | Data nodes (EBS/instance store) | Yes | Everything mutable lives here |
| [AWS] OpenSearch-optimized (OR1/OR2/OM2/OI2) | Local + synchronous S3 copy | Yes | 2.11+ new domains (2.15+ existing). **`refresh_interval` ≥ 10s**. Replicas lag. Migration to them is irreversible |
| [AWS] **UltraWarm** | S3 + node cache | **Read-only** | Needs dedicated masters. Only primaries billed. ≤ 50 GiB shards. Migration force-merges. Cost-effective from ~2.5 TiB. `search.max_buckets` defaults to 10,000 when enabled |
| [AWS] Cold | S3, detached | Not searchable until re-attached to warm | Cheapest |
| OSS hot-warm | Node attribute `box_type` + `index.routing.allocation.require.box_type` | Yes (just slower hardware) | Driven by ISM `allocation` |
| OSS searchable snapshots | Snapshot repo + `search` nodes | Read-only | Check version docs |

## 6. [AWS] Amazon OpenSearch Service specifics

- Default 5 primaries per index unless templated. No direct `opensearch.yml`/JVM access. Some
  cluster settings are allowed via the API, others are not.
- Recommended alarms (from AWS docs): `ClusterStatus.red` ≥1 (1 min), `ClusterStatus.yellow` ≥1
  (1 min ×5), `FreeStorageSpace` ≤ 25% of per-node storage, `ClusterIndexWritesBlocked` ≥1 (5 min),
  `Nodes` < expected (1 day), `AutomatedSnapshotFailure` ≥1, `CPUUtilization` ≥80% (15 min ×3),
  `JVMMemoryPressure` ≥95%, `OldGenJVMMemoryPressure` ≥80%, `MasterCPUUtilization` ≥50%,
  `MasterJVMMemoryPressure` ≥95%, `shards.active` ≥ 25×heap×nodes, 5xx ≥10% of requests,
  `ThreadpoolWriteQueue` avg ≥100, `ThreadpoolSearchQueue` avg ≥500 / max ≥5000, and any
  increase in `ThreadpoolSearchRejected` / `ThreadpoolWriteRejected`.
- Configuration changes may trigger **blue/green deployments** (shard relocation for hours).
  Don't schedule them during peak. Dedicated masters keep them non-disruptive.
- Auto-Tune adjusts queue/cache/JVM settings. Review its actions when chasing behaviour changes.
- Service software updates are auto-applied about two weeks after availability.
- **OpenSearch Serverless** (collections: search / time series / vector) has no shards or
  replicas to manage, many `_cat`/`_cluster`/ISM APIs are unsupported, and refresh semantics
  differ. Treat it as a different product when reading this skill.

## 7. Snapshots

- `PUT _snapshot/<repo>` (S3 via repository-s3), `PUT _snapshot/<repo>/<snap>?wait_for_completion=false`,
  `POST _snapshot/<repo>/<snap>/_restore` with `indices` and `rename_pattern`.
- Snapshots are incremental at the segment level. A red cluster can still snapshot the green
  indexes (`partial: true`).
- [AWS] automated snapshots go to `cs-automated(-enc)` (hourly, 14 days). Take manual snapshots
  to your own registered repo for migrations.
