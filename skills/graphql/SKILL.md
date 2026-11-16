---
name: graphql
description: Server-side GraphQL reference for the JVM (Java and Kotlin), with emphasis on GraphQL as an API over analytics and reporting data (for example a real-time reporting API backed by OpenSearch). Load whenever the work touches GraphQL — reading or designing a schema, writing resolvers or data fetchers, reviewing a GraphQL PR, diagnosing slow GraphQL queries, or integrating with another team's GraphQL API. Triggers on "graphql", "gql", "SDL", ".graphqls", "resolver", "data fetcher", "dataloader", "N+1", "batch loading", "federation", "subgraph", "supergraph", "apollo router", "graphql-java", "DGS", "spring graphql", "@QueryMapping", "@BatchMapping", "query complexity", "depth limit", "persisted queries", "APQ", "relay pagination", "cursor pagination", "errors as data", "introspection", "reporting API", "metrics API over OpenSearch", "graphql vs rest", "graphql vs grpc".
---

# GraphQL on the JVM — reference skill

Scope: GraphQL from the **server side**, in **Java/Kotlin**, mainly as an API over
**aggregated, analytics and reporting data**. Client libraries (Apollo Client, Relay)
are out of scope except where they constrain server design.

Deeper material (load only the one you need):

| File | Use it for |
|---|---|
| [references/schema-design.md](references/schema-design.md) | Naming, nullability, connections, errors-as-data, inputs, evolution and deprecation, review checklist |
| [references/jvm-implementation.md](references/jvm-implementation.md) | graphql-java, Spring for GraphQL, Netflix DGS code: resolvers, DataLoader, instrumentation, errors, testing, tracing |
| [references/performance-security.md](references/performance-security.md) | Depth, complexity and cost limits, timeouts, parser limits, persisted queries, caching, authorisation, introspection |
| [references/federation.md](references/federation.md) | Apollo Federation v2: entities, directives, router, Spring/DGS subgraphs |
| [references/analytics-api-design.md](references/analytics-api-design.md) | Designing metric/report queries over OpenSearch: filters, time ranges, group-by, bucket limits, freshness |
| [references/concepts.md](references/concepts.md) | Plain-English glossary of every main term, typical use cases, full when-to-use table, GraphQL vs REST vs gRPC |

## When to use it / when not to

| Situation | Verdict |
|---|---|
| Several UI clients (web, mobile, partners) needing different slices of the same data | GraphQL |
| A screen that aggregates many backend services | GraphQL (one round trip, server-side batching) |
| Many teams contributing to one product API | GraphQL with federation |
| Dashboards choosing metrics and dimensions | GraphQL, bounded by range, bucket and cost limits |
| Simple CRUD with one client | REST: the schema and limits are overhead with no payoff |
| Internal service-to-service calls | gRPC: binary, generated stubs, deadlines, streaming |
| Bulk export or file transfer | REST download, pre-signed S3 URLs or batch jobs |
| Public, read-heavy content behind a CDN | REST + CDN: URLs cache naturally, GraphQL POSTs do not |
| Ad hoc analysis by analysts | A SQL endpoint or semantic layer: the questions cannot be anticipated in a schema |
| Thousands of raw events per second to stream | Kafka, plain WebSocket or SSE, not subscriptions |

Reasons, use cases, the GraphQL vs REST vs gRPC table and a glossary of every term
used in this skill are in [references/concepts.md](references/concepts.md).

## 1. Mental model

- **One endpoint, client-shaped responses.** The client sends a *document* (operations
  plus fragments); the server validates it against the *schema*, then executes it by
  calling one *resolver* (graphql-java: `DataFetcher`) per field. Response shape mirrors
  the request shape.
- **The schema is the contract.** SDL (`type`, `input`, `enum`, `interface`, `union`,
  `scalar`, directives) is the source of truth. Three root types: `Query` (read,
  fields may run in parallel), `Mutation` (write, top-level fields run serially),
  `Subscription` (event stream, usually over WebSocket or SSE).
- **Execution is a tree walk, level by level.** Each field's resolver receives the
  parent's result (`source`), its arguments and a per-request context. That is what
  makes N+1 the default failure mode and DataLoader the default fix.
- **Partial success is normal.** A response is `{data, errors, extensions}`. A failing
  nullable field becomes `null` with an entry in `errors`; a failing non-null field
  nulls its nearest nullable ancestor. HTTP status is usually 200 even with errors
  (see the GraphQL-over-HTTP note in the performance reference).
- **Cost is set by the client, not by the endpoint.** One HTTP request can ask for
  anything the schema allows. Every list, nesting level and alias multiplies backend
  work, so limits must be designed in, not bolted on.
- **Versionless by evolution.** Add fields freely, deprecate with `@deprecated(reason:)`,
  remove only after usage telemetry says nobody calls it.
- **Fragments** are reusable selection sets and the unit of client co-location;
  **variables** keep documents static (needed for persisted queries and caching);
  **aliases** let one document call the same field twice with different arguments,
  which is useful for "this week vs last week" reports and is also an abuse vector.

## 2. Schema design checklist

Detail and examples are in [references/schema-design.md](references/schema-design.md).

- [ ] Designed from **client use cases**, not from the index or table layout. No
      OpenSearch field names, index names or query DSL leak into the schema.
- [ ] Every type and field has a **description** (`"""docstring"""`).
- [ ] **Nullability is deliberate.** Non-null (`!`) only where the server can always
      deliver; fields backed by another service or a fallible aggregation stay nullable.
      Lists are `[Item!]!` unless null items are meaningful.
- [ ] Unbounded lists are **paginated** with Relay connections (`first`/`after`,
      `edges { cursor node }`, `pageInfo`). There is a default and a **maximum** page size.
- [ ] IDs use `ID`; domain values use custom scalars (`DateTime`, `Date`, `Long`,
      `Decimal`). **GraphQL `Int` is signed 32-bit**, so counts and sums that can exceed
      2,147,483,647 need a `Long` scalar or `Float`.
- [ ] Fixed value sets are **enums** (metric names, dimensions, intervals, sort keys).
- [ ] Mutations take a single `input:` argument and return a **payload type**; expected
      business failures are modelled as **errors-as-data** (union or `errors` field on the
      payload), unexpected ones go to top-level `errors`.
- [ ] Mutually exclusive inputs use `@oneOf` (in the September 2025 spec edition; check
      your graphql-java version supports it) or are split into separate fields.
- [ ] No **required argument added** to an existing field, no type narrowed, no field
      removed without a deprecation period. Breaking-change check runs in CI.
- [ ] Naming: `camelCase` fields and arguments, `PascalCase` types, `SCREAMING_SNAKE`
      enum values, verb-first mutations (`createReport`), `Input`/`Payload` suffixes.

## 3. N+1 and DataLoader

**The problem.** `campaigns(first: 50) { owner { name } }` calls `Campaign.owner` 50
times: one query for the list plus 50 for the owners. With nesting it multiplies.

**The fix.** A DataLoader collects the keys requested while one level of the tree is
being resolved, then calls a *batch function* once with all of them, and caches per
key for the rest of the request. Rules:

1. **One DataLoader registry per request.** A shared registry leaks one user's data to another.
2. **The batch function must return results in key order**, one per key (`BatchLoader`),
   or a `Map` (`MappedBatchLoader`, where missing keys resolve to `null`).
3. Resolvers **return the `CompletableFuture`** from `loader.load(key)`. Never call
   `load()` inside your own `supplyAsync`, because the engine cannot see it to dispatch.
4. Set `maxBatchSize` to stay under backend limits (OpenSearch `terms`/`ids` sizes,
   SQL `IN` lists).
5. For aggregations, the "key" can be a **query spec** (a record of filter, range and
   dimension) so that identical sub-aggregations requested from several places in one
   document run once.

**Spring for GraphQL (simplest):**

```java
@Controller
class CampaignController {
  private final OwnerRepository owners;
  CampaignController(OwnerRepository owners) { this.owners = owners; }

  @QueryMapping
  Window<Campaign> campaigns(ScrollSubrange subrange) { /* ... */ }

  // Called once per level with every Campaign in the batch, not once per campaign.
  @BatchMapping
  Map<Campaign, Owner> owner(List<Campaign> campaigns) {
    Set<String> ids = campaigns.stream().map(Campaign::ownerId).collect(toSet());
    Map<String, Owner> byId = owners.findAllById(ids);          // ONE backend call
    return campaigns.stream().collect(toMap(c -> c, c -> byId.get(c.ownerId())));
  }
}
```

**Plain graphql-java (what Spring and DGS do underneath):**

```java
BatchLoader<String, Owner> ownerBatch = ids ->
    CompletableFuture.supplyAsync(() -> ownerService.loadInOrder(ids), executor);

// per request:
DataLoaderRegistry registry = new DataLoaderRegistry();
registry.register("owner", DataLoaderFactory.newDataLoader(ownerBatch,
    DataLoaderOptions.newOptions().setMaxBatchSize(500)));
ExecutionInput input = ExecutionInput.newExecutionInput()
    .query(query).variables(vars).dataLoaderRegistry(registry).build();

// field resolver:
DataFetcher<CompletableFuture<Owner>> ownerFetcher = env -> {
  Campaign c = env.getSource();
  return env.<String, Owner>getDataLoader("owner").load(c.ownerId());
};
```

DGS (`@DgsDataLoader`) and Kotlin variants are in the JVM reference. Dispatch is
level-by-level; a loader that calls another loader ("chained") needs graphql-java 25+
with chaining enabled, or it can stall until the next level.

**Better than DataLoader for reporting:** look ahead. The top-level resolver can read
`DataFetchingFieldSelectionSet` and build **one** OpenSearch request with exactly the
aggregations that were selected. See [references/analytics-api-design.md](references/analytics-api-design.md).

## 4. Performance and safety checklist

Detail and code are in [references/performance-security.md](references/performance-security.md).

- [ ] **Depth limit** (`MaxQueryDepthInstrumentation`, typically 7 to 12; graphql-java
      26 also enforces built-in defaults of depth 100 and 100,000 fields).
- [ ] **Complexity/cost limit** (`MaxQueryComplexityInstrumentation` with a custom
      `FieldComplexityCalculator` that multiplies by `first`/`limit`/bucket count).
- [ ] **Breadth/alias limit**: cap top-level fields and aliases per operation.
- [ ] **Parser limits**: graphql-java `ParserOptions` max tokens (15,000 default) and characters.
- [ ] **Pagination caps**: every list has a default and a hard max; reject over-max (do
      not silently clamp unless documented).
- [ ] **Time-range caps** for reporting: required range, maximum span, maximum buckets
      (span divided by interval).
- [ ] **Timeouts** at three layers: HTTP request (Spring `TimeoutWebGraphQlInterceptor`),
      per data fetcher, and the backend call (OpenSearch request timeout and cancellation).
- [ ] **Trusted documents/persisted queries** for first-party clients; APQ is a
      bandwidth and cache optimisation, **not** a security control.
- [ ] **Introspection off in production** for public APIs
      (`spring.graphql.schema.introspection.enabled=false`), or gated to internal callers.
- [ ] **Error masking**: no stack traces or backend messages in `errors[].message`.
- [ ] **Field-level authorisation** in the domain layer, not only at the endpoint.
- [ ] **Rate limiting by cost**, not only by request count.

## 5. JVM frameworks compared

| | graphql-java | Spring for GraphQL | Netflix DGS | graphql-kotlin (Expedia) |
|---|---|---|---|---|
| What it is | The engine everything else uses | Spring's official integration over graphql-java | Netflix's framework; now runs **on top of** Spring for GraphQL | Kotlin code-first library and Spring server |
| Schema style | SDL or code | Schema-first (`src/main/resources/graphql/*.graphqls`) | Schema-first, plus codegen of Java/Kotlin types | Code-first (schema generated from Kotlin classes) |
| Resolver model | `DataFetcher` + `RuntimeWiring` | `@Controller` + `@QueryMapping`/`@SchemaMapping`/`@BatchMapping` | `@DgsComponent` + `@DgsQuery`/`@DgsData` | Kotlin functions on `Query` classes |
| Batching | `DataLoaderRegistry` by hand | `@BatchMapping`, `BatchLoaderRegistry` | `@DgsDataLoader` classes | `KotlinDataLoader` |
| Pagination | By hand | `ConnectionTypeDefinitionConfigurer`, `Window`, `ScrollSubrange` | Relay types via codegen or by hand | By hand |
| Federation | federation-jvm | `@EntityMapping` + `FederationSchemaFactory` | `@DgsEntityFetcher` | Built-in federation support |
| Observability | `Instrumentation` | Micrometer `graphql.request`/`graphql.datafetcher` observations | Micrometer/Spring metrics | Instrumentation hooks |
| Testing | Execute `GraphQL` directly | `GraphQlTester`, `@GraphQlTest` slice | `DgsQueryExecutor`, `@EnableDgsTest` | Spring test support |
| Pick when | Non-Spring service or full control | Default for a new Spring Boot service | Team already on DGS, or wants its codegen and conventions | Kotlin-first team that wants code-first |

All four run on graphql-java, so instrumentation, `DataFetchingEnvironment`,
`ExecutionInput` and DataLoader knowledge carries across. Reading a sister team's
service? Look for `@DgsComponent` (DGS), `@Controller` with `@QueryMapping` (Spring),
or `RuntimeWiring.newRuntimeWiring()` (raw graphql-java).

## 6. Federation overview

Detail is in [references/federation.md](references/federation.md).

- A **supergraph** is composed from several **subgraphs** (each an ordinary GraphQL
  service plus federation directives). A **router** (Apollo Router, written in Rust;
  the older Node `@apollo/gateway` is legacy) receives client operations, builds a
  **query plan**, calls subgraphs, and stitches the results.
- **Entities** are types with `@key(fields: "id")`. Any subgraph can contribute fields
  to an entity; the router fetches them through the subgraph's `_entities` query and
  that subgraph's **reference resolver**, which must be batched or it becomes N+1
  across the network.
- Federation 2 schemas opt in with
  `extend schema @link(url: "https://specs.apollo.dev/federation/v2.x", import: ["@key", ...])`.
  Main directives: `@key`, `@shareable`, `@external`, `@requires`, `@provides`,
  `@override` (with progressive `label`), `@inaccessible`, `@tag`, `@interfaceObject`,
  plus router-enforced `@authenticated`, `@requiresScopes`, `@cost`, `@listSize`.
- Composition happens in CI (`rover supergraph compose` or GraphOS); breaking changes
  are caught by schema checks against real operation traffic.
- For a reporting subgraph: expose metrics as fields on shared entities only when the
  join is cheap and batched. Otherwise keep a dedicated `reports` root field, because a
  router query plan that fans a list of 1,000 entities out to an aggregation subgraph is
  the federated version of N+1.

## 7. Reporting-API design pattern

Detail and OpenSearch mapping are in [references/analytics-api-design.md](references/analytics-api-design.md).

```graphql
"""Time-bucketed metrics. Bounded: range <= 93 days, buckets <= 1,000."""
type Query {
  metrics(
    filter: MetricFilter!            # typed, enum-keyed; no free-form query strings
    range: TimeRange!                # required; server enforces max span
    groupBy: [Dimension!] = []       # enum; max 2-3 dimensions
    interval: Interval               # null = one total bucket; else MINUTE|HOUR|DAY|WEEK|MONTH
    timeZone: String = "UTC"         # IANA zone, for calendar bucketing
    first: Int = 100, after: String  # pages the group rows (composite agg after_key)
  ): MetricResult!
}
input TimeRange { from: DateTime!, to: DateTime! }   # half-open [from, to)
type MetricResult {
  rows: MetricRowConnection!
  totals: MetricValues!
  meta: ResultMeta!                  # asOf (data freshness), sampled, partial, timeZone
}
type MetricRow { key: [DimensionValue!]!, bucketStart: DateTime, values: MetricValues! }
type MetricValues { count: Long!, revenue: Decimal, p95LatencyMs: Float }
```

Principles:

1. **Make every query bounded by construction**: required time range, maximum span,
   maximum buckets, maximum group-by cardinality, maximum page size, enum dimensions only.
2. **Push work down**: one resolver turns the selection set into one OpenSearch
   request (`filter` context, `date_histogram`, `composite`/`terms`, metric aggs). Leaf
   fields read from the in-memory response; they never query.
3. **Typed metric fields over generic `[{name, value}]`**, so clients get types and you
   get per-field cost and deprecation. Use a generic shape only for truly dynamic metrics.
4. **Report freshness and accuracy** in `meta` (`asOf`, `isPartial`, approximate
   cardinality and percentiles). Real-time data is never exactly "now".
5. **Make caching possible**: snap ranges to bucket boundaries, keep documents static
   with variables, and add short TTL caching keyed by the normalised query spec.

## 8. Pitfalls

- **Unbounded lists** (`[Thing!]!` with no `first`): eventually someone asks for all of them.
- **`Int` overflow** on counts and sums; floating-point money (use a `Decimal` scalar serialised as a string).
- **Resolvers that query per row** in reporting types, which is N+1 against OpenSearch.
- **Shared DataLoader across requests**, leaking data between users.
- **Calling `load()` inside `supplyAsync`** or blocking on `.join()` in a fetcher: batching stalls or the thread pool starves.
- **Non-null everywhere**: one failing sub-aggregation nulls the whole report.
  **Nullable everywhere**: clients null-check everything. Decide per field.
- **Throwing for expected outcomes** (validation, not found, quota): use errors-as-data for mutations and meaningful nulls for queries.
- **Leaking backend shape**: `_source`, index names, keyword versus text subfields, raw query DSL arguments.
- **Aliases bypassing limits**: 100 aliased copies of an expensive field pass a depth check. Count aliases and use cost analysis.
- **APQ mistaken for an allowlist**: APQ registers any query on first sight.
- **GET with mutations**, or caching authenticated responses on a shared CDN.
- **Breaking changes via "harmless" edits**: nullable to non-null on an *input*, non-null to nullable on an *output*, adding a required argument, renaming enum values.
- **Timezone bugs** in day/week buckets: always accept and echo the zone; document half-open ranges.
- **Deep offset pagination** on OpenSearch (`from + size` above `index.max_result_window`, 10,000 by default): use `search_after` with point-in-time for hits, `composite` `after_key` for buckets.
- **Silent sampling or approximation** (`cardinality`, percentiles, `terms` doc-count error): flag it in the response.
- **Introspection and GraphiQL left on** in production for an external API.

## 9. Working with the user

- Java first, Kotlin where the codebase is Kotlin. Prefer Spring for GraphQL idioms
  unless the repo is DGS.
- When reviewing a sister team's GraphQL API, start with: the schema file(s), where
  limits are enforced, how resolvers reach OpenSearch (one request or many), and the
  DataLoader registrations.

## Sources

Existing agent skills checked (borrowed from where noted):
- Apollo GraphQL agent skills, MIT: https://github.com/apollographql/skills —
  `graphql-schema` (ground rules: descriptions everywhere, `[Type!]!`, paginate with
  defaults, no required arguments without defaults, enums over strings, depth guidance
  of 5 to 15 levels by API type, dangerous nested-pagination example) and the
  `apollo-federation`/`apollo-router` skill list. Borrowed and adapted for the JVM.
- rynr/spring-skills `spring-graphql` skill, MIT (Spring GraphQL vs DGS, DataLoader,
  federation, testing outline): https://github.com/rynr/spring-skills
- Also looked at: Hashnode/gql-skill (client-side, for one API; not used),
  jabrena/cursor-rules-java (no GraphQL-specific rule found), dev.to "Cursor Rules for
  GraphQL" article (generic; not used). No GraphQL skill exists in anthropics/skills.

Primary documentation:
- GraphQL learn pages (schema, best practices, performance, security, pagination): https://graphql.org/learn/
- GraphQL spec, September 2025 edition: https://spec.graphql.org/September2025/ ; `@oneOf` announcement: https://graphql.org/blog/2025-09-04-multioption-inputs-with-oneof/
- GraphQL over HTTP draft: https://http-spec.graphql.org/draft/
- Relay cursor connections spec: https://relay.dev/graphql/connections.htm
- graphql-java docs (batching, instrumentation): https://www.graphql-java.com/documentation/batching/ , https://www.graphql-java.com/documentation/instrumentation/ ; releases: https://github.com/graphql-java/graphql-java/releases
- Spring for GraphQL reference: https://docs.spring.io/spring-graphql/reference/ ; Spring Boot GraphQL: https://docs.spring.io/spring-boot/reference/web/spring-graphql.html
- Netflix DGS: https://netflix.github.io/dgs/ (data loaders, testing, Spring GraphQL integration)
- Apollo Federation directives: https://www.apollographql.com/docs/graphos/reference/federation/directives ; versions: https://www.apollographql.com/docs/graphos/schema-design/federated-schemas/reference/versions
- Apollo Router demand control and persisted queries: https://www.apollographql.com/docs/graphos/routing/security/demand-control , https://www.apollographql.com/docs/graphos/platform/security/persisted-queries
- Sasha Solomon, "200 OK! Error Handling in GraphQL": https://medium.com/@sachee/200-ok-error-handling-in-graphql-7ec869aec9bc
