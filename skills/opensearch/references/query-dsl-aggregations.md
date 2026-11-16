# Query DSL, aggregations, pagination and caching

Version tags: **[2.x]**, **[3.0+]**, **[AWS]**. Untagged = OpenSearch 2.x/3.x and ES 7.10-era.

## 1. Query vs filter context

- **Query context** (`must`, `should`, top-level `match`) computes `_score`. Use it only for
  relevance ranking.
- **Filter context** (`bool.filter`, `bool.must_not`, `constant_score`, filter aggs) is a
  yes/no match with no scoring. Frequently used filters are cached in the node **query cache**
  (per segment, as bitsets). For reporting, **everything goes in `filter`**.

```json
{ "query": { "bool": {
    "filter":   [ { "term": { "merchant_id": "m-123" } },
                  { "range": { "created_at": { "gte": "2026-09-01", "lt": "2026-10-01" } } } ],
    "must_not": [ { "term": { "status": "DELETED" } } ],
    "should":   [ { "match": { "notes": "allergy" } } ],
    "minimum_should_match": 0
} } }
```

Clause pitfalls:
- `term` on a `text` field almost never matches (the field is analysed). Use the `keyword` field.
- `match` on `keyword` is an exact match. Fine, but say so.
- **Leading wildcards** (`*abc`), `regexp`, and `script` queries scan terms or docs. The
  alternatives are an `ngram`/`wildcard` field type, or indexing the derived value.
- `terms` with huge lists hits `index.max_terms_count` (65,536). Use a `terms` lookup or
  restructure.
- `bool` clause count is bounded by `indices.query.bool.max_clause_count`.
- **User input to `query_string`**: strip `<`/`>` (they can't be escaped and can produce very slow
  queries), or prefer `simple_query_string` or structured queries.
- Date math: `now-1d/d` rounds. Rounded `now` (`now/m`) keeps query text stable across calls.
  The request cache docs say queries with relative `now` are not cacheable, so for cacheable
  dashboards compute absolute bounds in the API layer.

## 2. Hits: sorting, totals, source

- `track_total_hits` defaults to **10,000** (accurate up to that, then `gte`). Set `false` when
  the UI doesn't need a count. That is cheaper.
- `_source` filtering (`"_source": ["id","total"]`) or `docvalue_fields` cut fetch cost.
- Sort on `keyword`/numeric/date (doc_values). Add a unique tiebreaker (`order_id`) for
  stable paging.
- `collapse: { field: "order_id" }` returns one hit per key (latest version if sorted by
  `updated_at desc`). This is useful when the index holds event versions.
- `timeout: "2s"` plus `allow_partial_search_results` lets API backends bound latency. Check
  `timed_out` and `_shards.failed` in responses and surface partial results.

## 3. Pagination

| Method | Use when | Limits |
|---|---|---|
| `from` + `size` | First few pages of UI results | `from+size ≤ index.max_result_window` (10,000). Cost grows with depth |
| `search_after` | Deep/infinite paging | Needs a sort with a unique tiebreaker. Without PIT, results shift as data refreshes |
| `search_after` + **PIT** [2.4+] | Consistent deep paging or exports over live data | `search.max_open_pit_context` 300 per node, `point_in_time.max_keep_alive` 24h. PITs are lost on node failure |
| `scroll` | Legacy bulk export | Forward-only, bound to one query, holds segments. Prefer PIT |
| `composite` agg | Paging through *buckets* (all groups) | `after_key`, `size` default 10 |

```json
POST /orders/_search/point_in_time?keep_alive=5m        → { "pit_id": "..." }

GET /_search
{ "size": 500,
  "pit": { "id": "<pit_id>", "keep_alive": "5m" },
  "sort": [ { "updated_at": "desc" }, { "order_id": "asc" } ],
  "search_after": [ 1759300000000, "o-991" ],
  "query": { "bool": { "filter": [ { "term": { "merchant_id": "m-123" } } ] } } }

DELETE /_search/point_in_time   { "pit_id": ["<pit_id>"] }
```

Note: with PIT, the request goes to `/_search` with no index in the path (the PIT pins the indexes).

GraphQL/API mapping: expose an opaque cursor that base64-encodes the `search_after` sort values
(plus the PIT ID for exports). Never expose `from` for deep pages.

## 4. Aggregations

### Bucket aggs

```json
"aggs": {
  "by_status": { "terms": { "field": "status", "size": 20, "missing": "UNKNOWN",
                            "order": { "_count": "desc" } } },

  "by_hour": { "date_histogram": { "field": "created_at", "fixed_interval": "1h",
                                   "time_zone": "America/New_York", "min_doc_count": 0 } },

  "by_merchant_day": { "composite": { "size": 1000,
      "sources": [ { "merchant": { "terms": { "field": "merchant_id" } } },
                   { "day": { "date_histogram": { "field": "created_at", "calendar_interval": "day" } } } ],
      "after": { "merchant": "m-122", "day": 1759190400000 } },
    "aggs": { "revenue": { "sum": { "field": "total_minor" } } } },

  "basket_size": { "range": { "field": "total_minor",
      "ranges": [ { "to": 1000 }, { "from": 1000, "to": 5000 }, { "from": 5000 } ] } },

  "paid_only": { "filter": { "term": { "status": "PAID" } },
                 "aggs": { "rev": { "sum": { "field": "total_minor" } } } },

  "by_channel_and_type": { "multi_terms": { "terms": [ { "field": "channel" }, { "field": "order_type" } ], "size": 20 } }
}
```

- `calendar_interval` (`minute|hour|day|week|month|quarter|year`, DST-aware) vs `fixed_interval`
  (`30m`, `1h`, `7d` as exact durations). Mixing them up is a common bug.
- `extended_bounds` / `hard_bounds` give empty buckets for charts.
- **terms accuracy**: each shard returns its top `shard_size` (default `size*1.5+10`), and the
  coordinator merges them. Inspect `doc_count_error_upper_bound` and `sum_other_doc_count`, and use
  `show_term_doc_count_error: true` for per-bucket error. Accuracy figures apply only to the
  default `_count desc` order. For "rarest", use `rare_terms`. Sorting `terms` by a sub-agg
  metric is also approximate.
- **One shard answers exactly**: if the query is routed (`?routing=merchant_id`) to a single
  shard, `terms` is exact.
- `execution_hint: map` (small result sets after a selective filter) vs `global_ordinals`
  (default for keyword).

### Metric aggs

| Agg | Notes |
|---|---|
| `sum`, `avg`, `min`, `max`, `value_count`, `stats`, `extended_stats` | Exact (floating-point caveats on `double`; prefer `long` minor units for money) |
| `cardinality` | HyperLogLog++. `precision_threshold` default 3000, max 40000. Near-exact below the threshold, typically within ~6% above it. A hybrid collector is the default [3.4+] |
| `percentiles`, `percentile_ranks` | t-digest by default, or HDR (`hdr: {number_of_significant_value_digits}`). Approximate |
| `top_hits` | Docs per bucket. Expensive across thousands of buckets |
| `weighted_avg`, `median_absolute_deviation`, `scripted_metric` | `scripted_metric` is slow and memory-hungry. Last resort |

### Pipeline aggs

`bucket_script` (ratio per bucket, e.g. refund rate), `bucket_selector` (HAVING),
`bucket_sort` (sort/truncate parent buckets), `cumulative_sum`, `derivative`,
`moving_fn`, `sum_bucket`/`avg_bucket`/`max_bucket` (sibling).

```json
"per_day": { "date_histogram": { "field": "created_at", "calendar_interval": "day" },
  "aggs": {
    "gross":   { "sum": { "field": "total_minor" } },
    "refunds": { "filter": { "term": { "status": "REFUNDED" } },
                 "aggs": { "amt": { "sum": { "field": "total_minor" } } } },
    "refund_rate": { "bucket_script": {
        "buckets_path": { "r": "refunds>amt", "g": "gross" },
        "script": "params.g == 0 ? 0 : params.r / params.g" } },
    "running": { "cumulative_sum": { "buckets_path": "gross" } } } }
```

### Memory and limits

- `search.max_buckets` caps total buckets per response. [AWS] documents a default of 65,536 and
  **10,000 when UltraWarm is enabled**. Prefer `composite` paging to raising it.
- Global ordinals for keyword aggs are built lazily on first agg after each refresh. On
  frequently refreshed indexes with high-cardinality keyword aggs, `eager_global_ordinals: true`
  moves that cost into refresh. That trades query latency against refresh time and heap.
- The request circuit breaker (60% heap) trips on huge bucket trees. Fix the query, not the breaker.
- Concurrent segment search [GA 2.12, default `auto` in 3.0+] parallelises per-segment work.
  Big wins for heavy aggs. More CPU. Some aggs (sampler, join `parent`) fall back to sequential.

## 5. Pre-aggregation options for real-time reporting

| Option | Fits mutable data? | Notes |
|---|---|---|
| Query-time aggs on the order index | Yes | Simplest. Scale by shard count/routing, filters, and bounded time ranges |
| **Star-tree index** (experimental 2.18, **GA 3.1**, multi-terms support 3.3) | **No**: requires `index.append_only.enabled: true` | 2–10 ordered dimensions, numeric metrics (sum/min/max/value_count/avg). Up to ~100× faster aggs. Avoid high-cardinality dimensions |
| Index transforms / rollups (plugins) | Partly: periodic jobs, not seconds-fresh | Summary indexes for historical ranges. Combine with a live index for "today" |
| Upstream pre-aggregation (Flink/Kafka Streams → counter docs) | Yes, with idempotent upserts | Moves complexity out of OpenSearch. Docs keyed by `(tenant, bucket)` |
| Append-only event index + `collapse`/latest | Yes | Every state change appended; star-tree eligible; queries must pick the latest version |

## 6. Caching

| Cache | What | Default size | Invalidation |
|---|---|---|---|
| Node **query cache** | Filter bitsets per segment (only on segments above a size threshold, for frequently used filters) | 10% heap (`indices.queries.cache.size`, ES-inherited default) | Per segment. New segments start cold |
| Shard **request cache** | Whole shard-level response, **only `size: 0` by default** | 1% heap (`indices.requests.cache.size`) | **Every refresh that changed the shard**. On a 1 s-refresh hot index the hit rate is near zero |
| Fielddata | `text` fielddata / global ordinals | breaker 40% heap | Evicted on segment change |
| OS page cache | Segment files, doc_values | Off-heap (leave ~50% RAM to the OS) | Kernel |

- `?request_cache=true` forces caching for a request. [2.19+]
  `indices.requests.cache.maximum_cacheable_size` allows caching responses with `size > 0`.
  Tiered (on-heap + disk) request cache exists in recent 2.x (check your version).
- For real-time dashboards, split the read path: historical ranges (closed indexes, cache-friendly)
  vs today (live index, uncached), then merge in the API layer, or cache in the API layer for 1–5 s.

## 7. Profiling a slow query

1. Reproduce with `"profile": true`. Find the dominant `query` type and its `time_in_nanos`
   breakdown (`next_doc`, `build_scorer`, `match`), plus `aggregations` collectors.
2. Check the mapping of the hot field (`GET idx/_mapping/field/<f>`).
3. Rewrite: move clauses to filter, remove scripts/wildcards, narrow the time range, route by
   tenant, reduce `size`/`shard_size`.
4. Re-profile. Declare success only when the dominant component changes or drops. `took` alone
   is noisy.
5. Production evidence: search slow log (shard level) and request slow log [2.12+]. See
   operations-troubleshooting.md.

Client-measured time ≫ server `took` means the problem is client-side (serialisation, thread
pool, network, large `_source`), not the query.

## 8. Other query-time features

- **Derived fields** [2.15+]: script-computed fields at query time (OpenSearch's answer to ES
  runtime fields). Slow on large scans, so use them for exploration, then index the field.
- **PPL / SQL** plugin: piped and SQL query languages (OpenSearch's analogue of ES|QL). Good for
  ad-hoc analysis. The API layer should still use the DSL.
- **Async search** plugin: long-running aggregations stored and polled. Keep responses < 10 MB on AWS.
- `search_type=dfs_query_then_fetch` only for scoring accuracy on tiny indexes. Never needed for filters/aggs.
