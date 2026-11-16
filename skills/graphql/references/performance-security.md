# Performance and security reference

Back to [SKILL.md](../SKILL.md). The threat model for a GraphQL API is mostly
**denial of service by expensive documents**, followed by **authorisation gaps at
field level** and **information disclosure**. graphql.org's security page recommends
a layered approach and notes that hiding introspection and errors "will typically not
be sufficient when used on their own (a document allowlist is likely to be a more
effective solution)".

## 1. Layers, in order of request processing

| Stage | Control | JVM mechanism |
|---|---|---|
| HTTP | Body size, request timeout, rate limit, auth | Servlet/Netty limits, gateway, Spring Security, `TimeoutWebGraphQlInterceptor` |
| Document lookup | Trusted documents / persisted query allowlist | `PreparsedDocumentProvider`, Apollo Router `persisted_queries.safelist` |
| Parse | Max characters, tokens, whitespace tokens, recursion | graphql-java `ParserOptions` (defaults: 1 MB characters, 15,000 tokens) |
| Validate | Depth, field count, aliases, complexity or cost | `MaxQueryDepthInstrumentation`, `MaxQueryComplexityInstrumentation`, graphql-java 26 `QueryComplexityLimits` |
| Execute | Per-field authorisation, argument validation, page and range caps, per-fetcher timeout | Resolvers, `@Valid`, domain services |
| Backend | Query timeouts, bucket caps, circuit breakers | OpenSearch `timeout`, `search.max_buckets`, cancellation |
| Response | Error masking, no introspection for externals | `DataFetcherExceptionResolver`, `spring.graphql.schema.introspection.enabled=false` |

## 2. Depth limiting

```java
new MaxQueryDepthInstrumentation(10)
```

Guidance borrowed from Apollo's `graphql-schema` skill: simple APIs 5 to 7, complex 7
to 10, internal tools 10 to 15. Introspection queries are deep, so check that your
tooling still works or exempt it for internal callers.

graphql-java **26.0** enforces built-in limits by default through
`QueryComplexityLimits`: `maxDepth` 100 and `maxFieldsCount` 100,000, failing with
`MaxQueryDepthExceeded` / `MaxQueryFieldsExceeded`. Override per request via
`GraphQLContext` with `QueryComplexityLimits.KEY`, or disable with
`QueryComplexityLimits.NONE`. These defaults are a backstop, not a policy; set your
own lower limits. graphql-java also has "good faith introspection" checks that reject
abusive introspection documents.

## 3. Complexity and cost analysis

Depth alone misses `first: 1000` and aliases. Give every field a cost that scales with
list sizes, and reject documents over a budget **before** executing.

```java
FieldComplexityCalculator calc = (env, childComplexity) -> {
  Map<String, Object> args = env.getArguments();
  String field = env.getField().getName();
  int pageSize = args.get("first") instanceof Integer f ? f : 20;   // default page size
  return switch (field) {
    // Reporting: cost ~ buckets x group rows x metrics selected
    case "metrics" -> 10 + estimateBuckets(args) * Math.max(1, childComplexity);
    // Connections multiply their children
    case "campaigns", "rows" -> 1 + pageSize * Math.max(1, childComplexity);
    default -> 1 + childComplexity;
  };
};
GraphQL.newGraphQL(schema)
    .instrumentation(new MaxQueryComplexityInstrumentation(5_000, calc))
    .build();
```

- The default calculator is `1 + childComplexity` per field.
- `env` gives `getField()`, `getFieldDefinition()`, `getParentType()`, `getArguments()`
  and `getParentEnvironment()`. Variables are already resolved in `getArguments()`.
- Put the cost hints next to the schema: a custom directive such as
  `@cost(weight: 5)` plus `@listSize(slicingArguments: ["first"])` read by the
  calculator keeps policy close to the type. Under federation, Apollo Router's
  **demand control** implements exactly these directives (IBM GraphQL Cost Directive
  spec): run it in `measure` mode first, then `enforce`.

```yaml
# Apollo Router
demand_control:
  enabled: true
  mode: measure          # then: enforce
  strategy:
    static_estimated:
      list_size: 10      # assumed size for lists without @listSize
      max: 1000
```

- Also **count aliases and root fields** (breadth limiting). A document with 200
  aliases of `metrics(...)` has depth 3 and still costs 200 OpenSearch queries. A small
  custom validation (walk the document, count `Field` nodes with aliases at each level)
  is enough.
- **Rate limit by cost**: subtract the computed cost from a per-client token bucket
  instead of counting requests.
- Return the cost in `extensions` (for example `extensions.cost.requested` and
  `extensions.cost.limit`) so client developers can self-correct.

## 4. Pagination and range limits

- Every list field has a default and a maximum (`first` above the max is a
  `BAD_REQUEST`, which is clearer than silently clamping).
- Reporting fields additionally cap time span, interval granularity relative to span
  (maximum buckets), number of group-by dimensions, and number of terms per dimension.
- Never expose offset pagination over OpenSearch past `index.max_result_window`
  (10,000 by default). Use `search_after` with a point-in-time for hit lists and
  composite aggregation `after_key` for grouped rows.

## 5. Timeouts and cancellation

- HTTP level: Spring `TimeoutWebGraphQlInterceptor(Duration.ofSeconds(10))`.
- Fetcher level: `CompletableFuture.orTimeout(...)` / Reactor `.timeout(...)`; map
  timeouts to a typed error with a `code` such as `TIMEOUT`.
- Backend level: set the OpenSearch request `timeout` and the client socket timeout,
  and cancel the search when the GraphQL request is cancelled. A request timed out at
  HTTP but still running in OpenSearch is how clusters fall over.
- Mark slow fields as nullable so a timed-out sub-aggregation degrades to `null` plus an
  error rather than failing the whole response.

## 6. Persisted queries, APQ and trusted documents

| | Automatic Persisted Queries (APQ) | Trusted documents (persisted query list) |
|---|---|---|
| Registration | At runtime: client sends hash; on miss, resends with full text, server caches it | At build time: client build extracts operations; CI publishes the list |
| Security | **None**: any query is accepted and cached | Allowlist: unknown operations rejected |
| Benefit | Smaller requests, enables GET plus CDN caching | Same, plus safelisting, plus plan-cache warm-up |
| Fits | Public APIs with unknown clients | First-party clients (internal dashboards) |

- Spring for GraphQL / graphql-java: APQ via
  `new ApolloPersistedQuerySupport(new InMemoryPersistedQueryCache(Map.of()))`
  plugged in with `configureGraphQl(b -> b.preparsedDocumentProvider(provider))`. For
  an allowlist, implement a `PreparsedDocumentProvider` (or a `WebGraphQlInterceptor`)
  that looks up the ID in a store and rejects anything else.
- Apollo Router config progression: `persisted_queries.enabled` then `log_unknown: true`
  (audit) then `safelist.enabled: true` then `safelist.require_id: true`, and
  `apq.enabled: false` once safelisting is on.
- graphql-java's `PreparsedDocumentProvider` also acts as a **parse/validate cache**;
  caching parsed documents is a cheap CPU win even without persisted queries.

## 7. Caching

- **HTTP/CDN**: only with GET requests (queries only; the GraphQL-over-HTTP spec
  forbids mutations via GET), persisted IDs to keep URLs short, and
  `Cache-Control` derived from the least-cacheable field in the response. Never cache
  per-user or per-tenant data on a shared CDN without the tenant in the cache key and
  `Vary` on auth.
- **Server-side response cache**: key on (normalised document hash, variables,
  tenant, auth scope). For reporting, snap time ranges to bucket boundaries and use
  short TTLs matching data freshness (for example 15 to 60 seconds for real-time
  dashboards); closed historical buckets can be cached much longer.
- **Entity and fragment caching**: DataLoader `ValueCache` (Redis, Caffeine) for
  per-key data; Apollo Router has entity/response caching for federated graphs.
- **Within one request**: DataLoader per-key memoisation dedupes repeated keys.
- **Backend**: OpenSearch shard request cache applies to `size: 0` aggregation
  requests and is invalidated on refresh; rounding `now` to the minute (`now/m`) in
  range filters makes requests cacheable.
- Compress responses (gzip or brotli); GraphQL JSON compresses very well.

## 8. Authentication and authorisation

- Authenticate at the transport (Spring Security filter chain); put the principal and
  tenant into the GraphQL context.
- **Authorise in the domain/service layer per field and per object**, not only at the
  endpoint, because any field is reachable via any path (and via `node(id:)`).
- Spring: `@PreAuthorize` on controller or service methods works; `@AuthenticationPrincipal`
  is a supported handler argument.
- Batch loaders must apply the same tenant filter as single fetches; pass the context
  through `BatchLoaderWithContext` or the Spring `BatchLoaderEnvironment`.
- Federation: Apollo Router can enforce `@authenticated` / `@requiresScopes` /
  `@policy` before planning, but subgraphs must still enforce, because they are
  reachable directly unless the network forbids it.

## 9. Information disclosure

- Introspection off for external clients (`spring.graphql.schema.introspection.enabled=false`).
  Field suggestions ("Did you mean ...?") in validation errors can leak schema too;
  some servers allow disabling them.
- Mask unexpected exceptions; return codes in `extensions.code`, not messages from
  OpenSearch or SQL.
- Do not put internal index names or cluster details in descriptions.

## 10. HTTP semantics (GraphQL over HTTP)

- POST with `application/json` must be supported; GET may be used for queries only.
- The draft spec defines `application/graphql-response+json`; with it, servers use
  4xx for request errors (parse or validation failure, where there is no `data`), so
  gateways and monitors can see them. With legacy `application/json`, 200 is common
  even for errors. Check which mode the sister team's API uses before alerting on status codes.

## 11. Performance checklist

- [ ] No resolver issues a backend call per parent: batched or looked-ahead
- [ ] DataLoader batch sizes observed in metrics (not assumed)
- [ ] Parsed and validated documents cached (`PreparsedDocumentProvider`)
- [ ] Depth, complexity, alias and page-size limits, each with a test
- [ ] Timeouts at HTTP, fetcher and backend, with backend cancellation
- [ ] Response cache keyed by tenant and normalised operation; ranges snapped
- [ ] Operation-level latency and error metrics by operation name and client
- [ ] Blocking calls off the event loop (WebFlux) or on virtual threads (`Callable` return types)
