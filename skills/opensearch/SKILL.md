---
name: opensearch
description: Reference for OpenSearch 2.x/3.x and Amazon OpenSearch Service (mostly applies to Elasticsearch). Concepts glossary and when-to-use; index/mapping design, shard sizing, refresh vs throughput, bulk indexing, upserts of mutable docs, aggregations for real-time reporting, pagination, ISM/rollover/aliases, tiers, Kafka/Data Prepper ingestion, cluster troubleshooting. Triggers: "opensearch", "elasticsearch", "what is opensearch", "opensearch vs", "shard", "replica", "segment", "mapping", "keyword vs text", "doc_values", "refresh interval", "bulk indexing", "upsert", "version conflict", "aggregation", "composite", "cardinality", "date_histogram", "search_after", "point in time", "cluster red", "yellow cluster", "unassigned shards", "circuit breaker", "429 rejected", "mapping explosion", "too many shards", "index template", "rollover", "ISM", "UltraWarm", "Data Prepper", "OSIS", "real-time reporting index".
---

# OpenSearch

Reference for designing, running and debugging OpenSearch, with a bias toward **real-time
analytics over mutable data** (e.g. order reports served within seconds, behind an API).
Version tags: **[2.x]**, **[3.0+]**, **[AWS]** = Amazon OpenSearch Service specific.
Everything else applies to both OpenSearch and Elasticsearch 7.10-era behaviour.

Deeper material:
- [references/query-dsl-aggregations.md](references/query-dsl-aggregations.md) — queries, aggregations, pagination, caching, profiling
- [references/operations-troubleshooting.md](references/operations-troubleshooting.md) — `_cat`/`_cluster` cheat-sheet, runbooks, tiers, ISM, reindex
- [references/ingestion.md](references/ingestion.md) — bulk API, Kafka paths, Data Prepper/OSIS, pull-based ingestion, versioning
- [references/opensearch-vs-elasticsearch.md](references/opensearch-vs-elasticsearch.md) — fork history, feature/API mapping, client gotchas
- [references/concepts.md](references/concepts.md) — plain-English glossary of the core terms, use cases, full when-to-use table, OpenSearch vs Elasticsearch vs ClickHouse/Druid

## When to use it / when not to

| Situation | Verdict | Use instead (why) |
|---|---|---|
| Full-text search, facets, autocomplete | **Use** | |
| Logs, traces, events searched by time window | **Use** | ClickHouse if it is mostly aggregations and cost per TB dominates |
| Live dashboards/APIs over recent mutable data (orders) with seconds freshness | **Use, with care** | Overwrite by `_id` + external versioning; bound queries by tenant and time (section 7) |
| Vector or hybrid search with filters | **Use** | |
| Source of truth, transactions | **Don't** | Postgres: no multi-doc transactions or constraints, refresh delay. Feed OpenSearch by CDC |
| Heavy joins, years of history, BI | **Don't** | Snowflake/Databricks, or ClickHouse/Druid: no general joins, hot storage is costly |
| Append-only, high-cardinality OLAP at scale | **Usually don't** | ClickHouse/Druid/Pinot: exact, faster group-bys, better compression |
| Exact financial totals of record | **Don't** | Database or warehouse: some aggs are approximate, data is as of the last refresh |
| Tiny data (under ~1M rows) | **Don't** | Just use the database (Postgres full-text search or pgvector): a second system costs more than it saves |

Glossary, use-case examples and the full comparison: [references/concepts.md](references/concepts.md).

## 1. Mental model

- **Cluster** = nodes with roles: `cluster_manager` (was `master` before 2.0; keep 3 dedicated),
  `data`, `ingest`, coordinating-only (no roles), plus `warm`/`search` roles for tiering.
- **Index** = logical namespace split into **primary shards** (fixed at creation; changing needs
  split/shrink/reindex) each with N **replicas** (changeable any time). A shard is one Lucene index.
- **Shard** = a set of immutable **segments** plus an in-memory buffer and a **translog** (WAL).
  - *Index op* → buffer + translog. Durable when the translog is fsynced (default per request).
  - *Refresh* (default every 1s) → buffer becomes a new searchable segment. **Freshness = refresh.**
  - *Flush* → Lucene commit, translog trimmed. *Merge* → background compaction of small segments,
    which is also when deleted/updated docs are physically removed.
- **Segments are immutable, so an update is a delete plus a re-index of the whole document.**
  The old copy is marked deleted until a merge reclaims it. Update-heavy indexes therefore pay
  write amplification, carry deleted docs, and need merge headroom.
- **Replication** [2.x]: *document* replication (default; every replica re-indexes each op) or
  *segment* replication (`index.replication.type: SEGMENT`; primary indexes, replicas copy
  segments after refresh). Segment replication gives higher indexing throughput, but replicas lag
  the primary and `refresh=wait_for|true` is unsupported. Remote-backed storage [2.10+] requires
  segment replication.
- **Search** = scatter to one copy of every shard, gather top hits / partial aggs at the
  coordinator. Cost scales with *shards touched*, not just docs. Aggregations run on
  **doc_values** (columnar, on disk), not `_source`.

## 2. Index-design checklist

1. **Write mappings explicitly.** Set `"dynamic": "strict"` (reject unknown fields) or `false`
   (store but don't index them). Dynamic mapping turns every string into `text` plus `.keyword`,
   which doubles the cost, and the first document locks in the wrong types for good.
2. **keyword vs text**: `keyword` for IDs, enums, statuses, tenant/merchant IDs, and anything you
   filter, aggregate or sort on. `text` only for full-text search. Need both? Use `text` plus a
   `fields.raw: keyword` multi-field, with `ignore_above` on the keyword.
3. **doc_values** are on by default for every non-text field and are needed for aggs and sorting.
   Set `doc_values: false` only on fields you never aggregate or sort. Never enable `fielddata`
   on `text` fields (it is heap-resident and the classic way to blow the fielddata breaker).
4. **Numbers**: use the smallest type that fits. Money is best stored as `long` minor units (or
   `scaled_float`). Don't map numeric IDs as numbers: `term` lookups on `keyword` are faster than
   numeric point queries.
5. **Dates**: use one `date` field per business event (`created_at`, `updated_at`), stored in UTC.
   Use `date_nanos` only when you need it.
6. **Nested** documents are hidden separate docs. Updating any field re-indexes the parent and
   every nested child. Avoid `nested` on frequently-updated documents with big arrays, and avoid
   `join` (parent/child) for analytics. Denormalise instead.
7. **Unknown or unbounded keys** (attributes, metadata maps): use `flat_object` [2.7+] (no aggs or
   sort) or a key/value `nested` pair, never a dynamic object.
8. **`_id`** = the business key (e.g. `order_id`), so writes are idempotent. Use custom
   `routing` (e.g. merchant ID) only if most queries are single-tenant, and watch for hot shards.
   If routed, set `"_routing": {"required": true}` so unrouted writes fail loudly.
   `routing_partition_size` (≤ shard count) spreads a big tenant over several shards: lower
   prunes better but risks hotspots.
9. **Templates**: put shards, replicas, refresh, codec and mappings in a composable index template
   (`_index_template` + `_component_template`) so every new or rolled index is correct.
10. **Aliases always.** Clients read and write through an alias, so reindex and cutover is an
    atomic `_aliases` swap.
11. **Limits** (defaults): `index.mapping.total_fields.limit` 1000, `depth.limit` 20,
    `nested_fields.limit` 50, `nested_objects.limit` 10000, `index.max_result_window` 10000.
    Raising them treats the symptom, not the cause.
12. **Analyzers**: search-as-you-type is an `edge_ngram` index analyzer paired with a
    **non-ngram** `search_analyzer` (ngramming the query too over-matches). Case-insensitive exact
    match on `keyword` is a `normalizer` with `lowercase` + `asciifolding`. Every analyzer and
    normalizer a mapping references must be defined in `settings.analysis`, or creation fails.
13. **Verify what you created**: GET the mapping back and diff it against what you sent. Integration
    tests run against a real engine with the production mapping; mocks can't reproduce analyzers.

## 3. Shard sizing rules

| Rule | Value | Source |
|---|---|---|
| Shard size, latency-sensitive search | 10–30 GiB | AWS |
| Shard size, write-heavy/logs | 30–50 GiB (50 GiB max) | AWS |
| Shards per node | ≤ 25 per GiB of heap (32 GiB heap → ≤ 800) | AWS |
| Hard limit | `cluster.max_shards_per_node` = 1000 (OSS default) | OSS docs |
| [AWS] 2.17+ | 1000 per 16 GiB heap, up to 4000 per node | AWS |
| CPU | start at ~1.5 vCPU per *active* shard | AWS |
| Distribution | primaries (×copies) a multiple of the data-node count | AWS |
| Heap | 50% of RAM, ≤ ~32 GiB (compressed oops) | OSS/AWS |

Primary count ≈ `(source GiB + growth) × 1.1 / target shard GiB`. Small data (< ~10 GiB)
→ **1 primary**. Too many small shards is a far more common failure than too few big ones.
Default primaries: 1 in OSS [2.x+]; **5 on [AWS]** unless a template says otherwise.

## 4. Freshness vs throughput

Time to visibility ≈ upstream lag + client batching delay + bulk latency + **refresh interval**
(worst case) + replica lag (segment replication). Budget each term. A **~7 s** freshness SLA
leaves roughly 1–2 s for refresh.

| Setting | Freshness-first (real-time reports) | Throughput-first (backfill/logs) |
|---|---|---|
| `index.refresh_interval` | `1s`–`2s`, **set explicitly** | `30s`+, or `-1` during backfill |
| `number_of_replicas` | ≥1 (reads need copies) | `0` during a one-off backfill, then restore |
| Client bulk flush | ≤ 1 s or ~5–15 MiB, whichever first | 5–15 MiB, raise until no gain |
| `index.translog.durability` | `request` (default) | `async` only if replayable from Kafka |
| `translog.flush_threshold_size` | default 512mb | up to ~25% of heap |
| Replication type | document, or segment with lag monitored | segment [2.x] (+40% throughput in docs) |
| `refresh=wait_for` per request | avoid on hot paths; unsupported with segment replication | never |
| Request cache | mostly useless (invalidated every refresh) | useful on closed/old indexes |

Gotchas:
- **Search-idle shards**: if `refresh_interval` is *not set explicitly*, shards that get no
  search for `index.search.idle.after` (30 s) stop refreshing, and the next search blocks until a
  refresh. A quiet tenant's dashboard sees a latency spike. Set the interval explicitly.
- **[AWS] OR1/OR2/OM2/OI2 (OpenSearch-optimized) instances enforce `refresh_interval` ≥ 10 s**
  (default 10 s), and replicas lag the primary by seconds. They are incompatible with a sub-10 s
  freshness SLA. Check the instance family first.
- **[AWS] UltraWarm/cold indexes are read-only**, so mutable data must stay hot.
- Each refresh makes a tiny segment, so 1 s refresh plus heavy updates means constant merging.
  Watch `_cat/segments` counts and merge throttling.

## 5. Aggregations cheat-sheet

Put filters in `bool.filter` (no scoring, cacheable) and use `size: 0` when you only want aggs.

```json
GET orders/_search
{ "size": 0, "track_total_hits": false,
  "query": { "bool": { "filter": [
    { "term":  { "merchant_id": "m-123" } },
    { "terms": { "status": ["PAID","REFUNDED"] } },
    { "range": { "created_at": { "gte": "now-7d/d", "lt": "now/m", "time_zone": "Europe/Dublin" } } }
  ]}},
  "aggs": {
    "per_day": { "date_histogram": { "field": "created_at", "calendar_interval": "day",
                 "time_zone": "Europe/Dublin", "min_doc_count": 0,
                 "extended_bounds": { "min": "now-7d/d", "max": "now/d" } },
      "aggs": { "revenue": { "sum": { "field": "total_minor" } },
                "aov":     { "avg": { "field": "total_minor" } } } },
    "top_items": { "terms": { "field": "item_sku", "size": 10, "shard_size": 100 } },
    "unique_customers": { "cardinality": { "field": "customer_id", "precision_threshold": 10000 } }
  } }
```

| Need | Use | Accuracy note |
|---|---|---|
| Top-N by count | `terms` (`size`, `shard_size` default `size*1.5+10`) | Approximate across shards. Check `doc_count_error_upper_bound`; raise `shard_size`; or route by tenant so one shard answers |
| All groups / export | `composite` + `after_key` paging | Exact, and pages through every bucket |
| Group by 2+ fields, top-N | `multi_terms` or nested `terms` | Same caveats as `terms` |
| Distinct count | `cardinality` (HyperLogLog++) | Near-exact below `precision_threshold` (default 3000, max 40000); typically within ~6% above it |
| Time series | `date_histogram` (`calendar_interval` or `fixed_interval`) | Always pass `time_zone` for business days |
| Percentiles | `percentiles` (t-digest) | Approximate; `tdigest.compression` trades memory for accuracy |
| Latest doc per entity | `collapse` on keyword, or `top_hits` size 1 | `top_hits` is expensive at high bucket counts |
| Filter on agg result | `bucket_selector`; sort/page buckets with `bucket_sort` | Runs after the shard reduce, so it doesn't save work |

Limits: `search.max_buckets` (AWS documents a default of 65,536, and **10,000 when UltraWarm is
enabled**). Deep pagination of hits uses `search_after` + PIT [2.4+], not `from/size` beyond
10k. Full DSL in [references/query-dsl-aggregations.md](references/query-dsl-aggregations.md).

Pre-aggregation options: **star-tree index** (GA [3.1], experimental from 2.18) precomputes
aggs up to ~100× faster, **but needs `index.append_only.enabled: true` (no updates or deletes)**,
so it can't be used on mutable order docs. The alternatives are an append-only event index, or
rollups/transforms. Concurrent segment search is **on by default (`auto`) [3.0+]** and speeds
up heavy aggs at the cost of more CPU.

## 6. Troubleshooting runbook

Always start read-only: health → which index → which shard → *why* (allocation explain). Quote
the decider text before changing anything.

| Symptom | Check | Fix |
|---|---|---|
| Cluster **red** | `GET _cluster/health?level=indices`; `GET _cat/shards?v&h=index,shard,prirep,state,unassigned.reason,node \| grep UNASSIGNED`; `GET _cluster/allocation/explain` | A primary is missing. Bring the node back, or restore from snapshot. `allocate_stale_primary` / `allocate_empty_primary` **lose data** (last resort). [AWS] OR1 auto-restores from S3 |
| Cluster **yellow** | same; often `NODE_LEFT` within `delayed_timeout` (1m) | Wait out the delayed allocation. Check that disk is below the 85% low watermark, that replicas ≤ nodes−1, and awareness/filter rules. `POST _cluster/reroute?retry_failed=true` after 5 failed attempts |
| Writes fail `index ... read_only_allow_delete` | `GET _cat/allocation?v` (disk.percent) | Flood stage hit (95%). Free disk or add nodes. The block auto-clears below the high watermark (90%) |
| **429** / `es_rejected_execution_exception` | `GET _cat/thread_pool/write,search?v&h=node_name,name,active,queue,rejected` | Back off and retry with jitter. Make fewer, larger bulks. Fix hot shards. Scale out |
| `circuit_breaking_exception` | `GET _nodes/stats/breaker`; `_cat/fielddata?v` | Find the big agg (high-cardinality `terms`, `fielddata` on text, huge `size`). Parent breaker = 95% heap (real memory) |
| JVM pressure high / long GC | `GET _cat/nodes?v&h=name,heap.percent,ram.percent,cpu,load_1m,node.role`; `_nodes/stats/jvm` | Fewer shards, smaller aggs, scale up. [AWS] alarm: JVMMemoryPressure ≥ 95%, OldGen ≥ 80% |
| Slow searches | `GET _nodes/hot_threads`; `GET _tasks?actions=*search*&detailed`; `"profile": true`; slow log | Move clauses to filter, remove leading wildcards/scripts, reduce shards touched (routing, time-bounded indexes) |
| Indexing lag / freshness SLA missed | `_cat/indices?v&h=index,docs.count,docs.deleted,pri.store.size`; `_nodes/stats/indices/refresh,merges,indexing` | Merge or refresh pressure from updates, under-sized bulks, too-frequent client flushes |
| Mapping explosion | `GET idx/_mapping` field count; error `Limit of total fields [1000]` | `dynamic: strict`, `flat_object`, reindex. Don't just raise the limit |
| Too many shards | `GET _cat/shards \| wc -l`; `_cluster/health` `active_shards` vs heap×25 | ISM delete/shrink, merge daily into monthly indexes, fewer primaries |
| Split brain / cluster-manager flaps | `GET _cat/cluster_manager?v`; manager CPU/JVM | 3 dedicated cluster-manager nodes. [AWS] MasterCPU ≥ 50% means size up |

Full commands, decision trees and AWS alarm table: [references/operations-troubleshooting.md](references/operations-troubleshooting.md).

## 7. Pitfalls with mutable data (orders, carts, tickets)

1. **Use `_id` = business key and send full documents** (`index` action) when the source (CDC,
   Kafka) has the whole record. A partial `_update` does read + merge + reindex on the primary,
   so it costs more and is serialised per doc.
2. **Out-of-order events**: parallel consumers or retries re-order updates. Use
   **external versioning**: `index` with `version: <monotonic source version>` and
   `version_type: external` (or `external_gte`). Stale writes get **409** and should be
   *dropped, not retried*. The `_update` API does **not** support external versioning.
3. **Deletes plus late events**: a deleted doc's version is remembered only for
   `index.gc_deletes` (**60s**). A late, older `index` op after that window *resurrects* the doc.
   Prefer soft deletes (`status: DELETED`, `deleted_at`) and filter them out, or raise `gc_deletes`.
4. **Read-modify-write** races: use `if_seq_no` + `if_primary_term`, or
   `retry_on_conflict: N` for commutative `_update` scripts (counters).
5. **Rollover breaks updates.** After a rollover, the write alias points at the *new* index, so an
   update for an order created last month **creates a duplicate** there. Fixes: index name derived
   from an immutable date (`orders-2026-10` from `created_at`) with explicit targeting, or a single
   (or few) appropriately sharded index with retention by `delete_by_query` (expensive) or by
   month index drop. Data streams are append-only and can't be used for mutable docs.
6. **Deleted-doc bloat**: high update rates leave `docs.deleted` at 20–50% of a shard. That costs
   disk, cache and query time. Merges reclaim it. Leave headroom, and avoid
   `_forcemerge` on indexes still being written.
7. **`detect_noop`** (default true) skips no-change `_update`s, but plain `index` ops always
   rewrite, so dedupe unchanged events upstream.
8. **Replica staleness**: with segment replication (and on OR1), two consecutive requests can hit
   different copies and show the numbers going *backwards*. Pin a session to the same copies with
   `preference=<session-or-tenant-id>` (or `_primary` at a cost to load spreading).
9. **Totals vs line items**: if line items are `nested`, every order edit re-indexes all of
   them. Keep pre-computed totals on the parent; put item-level analytics in a separate
   append-only index if needed.
10. **Reports need stable "as of" semantics**: always filter on an explicit time bound and expose
    `max(updated_at)` or the query time to the API, so consumers know the freshness.

## 8. Working rules for Claude

- Ask (or check) **version, distribution (OSS vs AWS managed vs Serverless) and instance family**
  before recommending settings. Several answers flip on these.
- Prefer read-only diagnosis, then a single proposed change with its trade-off. Never suggest
  `allocate_empty_primary`, deleting indexes, or `refresh_interval: -1` on a live serving index
  without flagging the data or freshness impact.
- When raising a limit (fields, buckets, shards, max_result_window), say what the limit was
  protecting against.
- Measure with `profile`, `_nodes/stats` and slow logs before and after. `took` alone is noisy.

## Sources

- OpenSearch docs (docs.opensearch.org; source at github.com/opensearch-project/documentation-website):
  index settings, mapping explosion limits, cluster settings (watermarks, max_shards_per_node),
  circuit breakers, segment replication, remote-backed storage, pull-based ingestion, update API,
  terms/composite/cardinality aggregations, point in time, request cache, concurrent segment
  search, slow logs, ISM policies, flat_object, star-tree, eager_global_ordinals, search API
  `preference`, indexing-speed tuning, breaking changes.
- AWS: Amazon OpenSearch Service Developer Guide — "Choosing the number of shards"
  (bp-sharding), "Operational best practices" (bp), "Recommended CloudWatch alarms",
  "UltraWarm storage", "OpenSearch Optimized Instances" (or1), "OpenSearch Ingestion with Amazon MSK".
- OpenSearch 3.1 release blog (star-tree GA).
- Prior art checked and borrowed from: `elastic/agent-skills` (Apache-2.0) —
  `elasticsearch-cluster-health` (read-only triage, trigger-vs-root-cause via allocation explain,
  quote decider text), `elasticsearch-index-design` (access-pattern-first mapping table,
  `flattened` for unbounded keys → `flat_object` here), `elasticsearch-query-optimization`
  (profile-driven, filter-context rewrites, re-profile to confirm). `opensearch-project/opensearch-agent-skills`
  (Apache-2.0) — search/observability/cloud/ingest skills, no ops/mapping/aggregation coverage, so
  nothing copied. `anthropics/skills` has no search-engine skill.
