# Analytics and metrics APIs over GraphQL (OpenSearch-backed)

Back to [SKILL.md](../SKILL.md). For OpenSearch internals (aggregation types,
limits, caching, mappings) load the separate `opensearch` skill; this file covers the
GraphQL side and the mapping between the two.

## 1. The core tension

GraphQL lets clients compose arbitrary queries; analytics backends are expensive per
query and scale with **time span x granularity x group-by cardinality x metrics**.
The schema must make bad queries impossible to express or cheap to reject.

## 2. Schema shape

```graphql
type Query {
  """Aggregated metrics. Range max 93 days; max 1,000 time buckets; max 2 group-by dimensions."""
  metrics(
    filter: MetricFilter!
    range: TimeRange!
    interval: Interval              # null = no time bucketing (totals only)
    timeZone: String = "UTC"        # IANA name; affects DAY/WEEK/MONTH boundaries
    groupBy: [Dimension!] = []
    orderBy: MetricOrder            # e.g. {metric: REVENUE, direction: DESC}
    first: Int = 50                 # group rows per page (max 500)
    after: String                   # opaque cursor (composite after_key)
  ): MetricResult!

  """Raw events for drill-down. Always paginated, newest first."""
  events(filter: EventFilter!, range: TimeRange!, first: Int = 50, after: String): EventConnection!
}

input TimeRange { from: DateTime!, to: DateTime! }    # half-open [from, to)
enum Interval { MINUTE HOUR DAY WEEK MONTH }
enum Dimension { CHANNEL COUNTRY DEVICE CAMPAIGN }
enum Metric { COUNT REVENUE UNIQUE_USERS P95_LATENCY }

input MetricFilter {
  campaignIds: [ID!]                # max 100
  channels: [Channel!]
  countries: [CountryCode!]
}

type MetricResult {
  totals: MetricValues!
  series: [TimeBucket!]!            # present when interval != null and groupBy is empty
  rows: MetricRowConnection!        # present when groupBy is non-empty
  meta: ResultMeta!
}
type TimeBucket { start: DateTime!, values: MetricValues! }
type MetricRow  { key: [DimensionValue!]!, series: [TimeBucket!], values: MetricValues! }
type DimensionValue { dimension: Dimension!, value: String!, label: String }
type MetricValues {
  count: Long!
  revenue: Decimal
  uniqueUsers: Long                 # approximate (HyperLogLog++), see meta
  p95LatencyMs: Float               # approximate (t-digest)
}
type ResultMeta {
  asOf: DateTime!                   # data complete up to here (ingest lag)
  timeZone: String!
  isPartial: Boolean!               # shard failures or timeouts
  approximateFields: [String!]!
}
```

Design notes:

- **Typed metric fields** (`revenue`, `uniqueUsers`) let the resolver request only
  the aggregations whose fields were selected, let each field carry its own cost and
  deprecation, and give clients types. A generic `values(metrics: [Metric!]!): [MetricValue!]!`
  is acceptable when the metric catalogue is dynamic; then the `metrics` argument
  drives the aggregation list.
- **Enums for dimensions** map to known keyword fields server-side. Never accept a
  field name string.
- **Filters are structured inputs** with list-size caps. No free-text query DSL or
  Lucene syntax passthrough. If full-text search is needed, use one `search: String`
  argument mapped to a controlled `simple_query_string` over fixed fields.
- `series` is a **plain list**, bounded by range divided by interval; it does not need
  a connection. Group rows **do** need pagination because cardinality is data-dependent.
- `orderBy` on a metric with `terms` is approximate across shards; with `composite`
  ordering is by key only. Decide which you promise.

## 3. Validation rules (enforce before touching OpenSearch)

```java
record Limits(Duration maxSpan, int maxBuckets, int maxGroupBy, int maxFirst) {}

void validate(MetricArgs a, Limits l) {
  if (!a.range().to().isAfter(a.range().from())) throw bad("RANGE_EMPTY");
  Duration span = Duration.between(a.range().from(), a.range().to());
  if (span.compareTo(l.maxSpan()) > 0) throw bad("RANGE_TOO_LARGE");
  if (a.interval() != null) {
    long buckets = span.dividedBy(a.interval().approxDuration());   // approx for calendar units
    if (buckets > l.maxBuckets()) throw bad("TOO_MANY_BUCKETS");
  }
  if (a.groupBy().size() > l.maxGroupBy()) throw bad("TOO_MANY_DIMENSIONS");
  if (a.first() > l.maxFirst()) throw bad("PAGE_TOO_LARGE");
  ZoneId.of(a.timeZone());                                          // throws on bad zone
}
```

Also: total buckets returned is roughly `rows x buckets per row`; cap the product,
not just each factor. OpenSearch also has a cluster-wide `search.max_buckets` limit;
your API limits should be well below it.

## 4. Resolver strategy: one backend request per report

```java
@QueryMapping
Mono<MetricResult> metrics(@Arguments MetricArgs args,
                           DataFetchingFieldSelectionSet sel,
                           @ContextValue TenantId tenant) {
  validate(args, limits);
  MetricPlan plan = MetricPlan.builder()
      .tenant(tenant)                                   // mandatory tenant filter
      .args(args)
      .wantTotals(sel.contains("totals/**"))
      .wantSeries(sel.contains("series/**") || sel.contains("rows/**/series/**"))
      .metrics(selectedMetrics(sel))                    // only aggs for selected fields
      .build();
  return metricsClient.execute(plan)                    // ONE OpenSearch search, size: 0
      .map(resp -> MetricResultMapper.map(resp, plan)); // leaves read from memory
}
```

The nested types (`MetricValues`, `TimeBucket`) then use default property fetchers;
no field below `metrics` touches OpenSearch. If a nested field must call a backend
(for example `DimensionValue.label` from a lookup service), batch it with a DataLoader.

When the same report is requested several times in one document via aliases (this
week versus last week), route through a DataLoader keyed by the normalised `MetricPlan`
so identical plans run once and different plans can go out in one `_msearch`.

## 5. GraphQL argument to OpenSearch mapping

| GraphQL | OpenSearch (size: 0 search) |
|---|---|
| `range` | `bool.filter` `range` on the timestamp field, `gte` from, `lt` to (half-open) |
| `filter.*` lists | `bool.filter` `terms` on keyword fields (filter context, cacheable, no scoring) |
| tenant from context | `bool.filter` `term` on tenant field (or a per-tenant filtered alias) |
| `interval` + `timeZone` | `date_histogram` with `calendar_interval` (day, week, month) or `fixed_interval` (minutes, hours), `time_zone`, `min_doc_count: 0` and `extended_bounds` to get empty buckets |
| `groupBy` (paged) | `composite` aggregation with `terms` sources; `first` becomes `size`; cursor is base64 of `after_key` |
| `groupBy` top-N by metric | `terms` with `order` on a metric sub-agg and `size`; flag approximate counts (`doc_count_error_upper_bound`) |
| `count` | `doc_count` (or `value_count` on a field) |
| `revenue` | `sum` (scaled long or double; convert to `Decimal` carefully) |
| `uniqueUsers` | `cardinality` (approximate, `precision_threshold`) |
| `p95LatencyMs` | `percentiles` with `percents: [95]` (approximate) |
| `meta.isPartial` | `_shards.failed > 0` or `timed_out: true` |
| `meta.asOf` | An ingest watermark you track (max event time indexed, or pipeline lag), not `now()` |

Example generated request for
`metrics(range: last 7 days, interval: DAY, timeZone: "Europe/Dublin", groupBy: [CHANNEL], first: 50)`:

```json
{
  "size": 0,
  "timeout": "5s",
  "query": { "bool": { "filter": [
    { "term":  { "tenant_id": "t-123" } },
    { "range": { "@timestamp": { "gte": "2026-09-24T00:00:00+01:00", "lt": "2026-10-01T00:00:00+01:00" } } }
  ]}},
  "aggs": {
    "rows": {
      "composite": { "size": 50, "sources": [ { "channel": { "terms": { "field": "channel" } } } ] },
      "aggs": {
        "series": {
          "date_histogram": { "field": "@timestamp", "calendar_interval": "day",
                              "time_zone": "Europe/Dublin", "min_doc_count": 0,
                              "extended_bounds": { "min": "2026-09-24T00:00:00+01:00", "max": "2026-09-30T00:00:00+01:00" } },
          "aggs": { "revenue": { "sum": { "field": "revenue_minor" } } }
        },
        "revenue": { "sum": { "field": "revenue_minor" } }
      }
    },
    "total_revenue": { "sum": { "field": "revenue_minor" } }
  }
}
```

The next page sends `"after": <after_key>` decoded from the GraphQL cursor. When the
response has no `after_key`, or fewer than `size` buckets, `hasNextPage` is false.

## 6. Real-time specifics

- **Freshness is part of the contract.** Index refresh interval plus pipeline lag
  means the latest bucket is incomplete. Expose `meta.asOf` so clients can show
  "data as of 10:42"; optionally flag the last bucket as `isComplete: false`.
- **Polling over subscriptions** for dashboards: a cached `metrics` query polled
  every 15 to 60 seconds scales through caches; subscriptions per dashboard tile
  multiply backend load. Use subscriptions for events (threshold alerts).
- **Cache key**: tenant + normalised plan + range snapped to the interval (and `now`
  rounded, for example to the minute). Completed historical buckets can be cached far
  longer than the current one; splitting "closed" and "open" ranges is a common
  optimisation.
- **Rollups**: for long ranges, route to pre-aggregated indices (hourly or daily
  rollups produced by the pipeline) and fall back to raw indices only for recent or
  fine-grained data. The GraphQL contract stays the same; the resolver picks the source
  by span and interval.

## 7. Numbers and types

- Counts: `Long` custom scalar (GraphQL `Int` is 32-bit). JavaScript clients receiving
  `Long` as a JSON number lose precision above 2^53; serialise as a string if values
  can get that large.
- Money: store minor units as `long` in OpenSearch; expose `Decimal` (string) or a
  `Money { amountMinor: Long!, currency: CurrencyCode! }` type. Avoid `Float` for money.
- Ratios and averages: compute from sums server-side (`sum(a)/sum(b)`), never as an
  average of averages across buckets.
- Empty buckets: `count: 0` and `revenue: 0` when no data matched; `null` when the
  metric is undefined (for example p95 of zero events). Document which.

## 8. Review checklist for an analytics GraphQL API

- [ ] Every entry point requires a time range and enforces max span and max buckets
- [ ] Dimensions, metrics, intervals and sort keys are enums
- [ ] Group rows paginated with opaque cursors; series lists bounded
- [ ] One backend request per report (verify with logs or traces); no per-row fetches
- [ ] Only selected aggregations are requested (selection-set look-ahead)
- [ ] Tenant filter applied in the plan builder, including batch and `_entities` paths
- [ ] Timeouts set on the OpenSearch request, with partial results flagged
- [ ] Approximate metrics flagged; `asOf` exposed
- [ ] `Long`/`Decimal` scalars for big numbers and money; time zones explicit
- [ ] Complexity calculator prices `metrics` by buckets x rows x metrics
