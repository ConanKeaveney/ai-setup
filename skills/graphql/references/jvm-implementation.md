# JVM implementation reference: graphql-java, Spring for GraphQL, Netflix DGS

Back to [SKILL.md](../SKILL.md). Code is Java unless marked Kotlin. Versions checked
in October 2026: graphql-java 26.x, Spring for GraphQL 2.0.x (Spring Boot 4.x), DGS
on its Spring-for-GraphQL-based starter. Check the repo's actual versions before
copying API details.

## 1. graphql-java (the engine)

Everything below in Spring and DGS compiles down to this.

```java
// Schema-first wiring
TypeDefinitionRegistry types = new SchemaParser().parse(sdlString);
RuntimeWiring wiring = RuntimeWiring.newRuntimeWiring()
    .scalar(ExtendedScalars.DateTime)
    .scalar(ExtendedScalars.GraphQLLong)
    .type("Query", t -> t
        .dataFetcher("campaign", env -> campaignService.byId(env.getArgument("id"))))
    .type("Campaign", t -> t
        .dataFetcher("owner", ownerFetcher))       // DataLoader-backed, see section 4
    .build();
GraphQLSchema schema = new SchemaGenerator().makeExecutableSchema(types, wiring);

GraphQL graphQL = GraphQL.newGraphQL(schema)
    .instrumentation(new ChainedInstrumentation(List.of(
        new MaxQueryDepthInstrumentation(10),
        new MaxQueryComplexityInstrumentation(2_000, complexityCalculator),
        new TimingInstrumentation(meterRegistry))))
    .build();

// Per request
ExecutionInput input = ExecutionInput.newExecutionInput()
    .query(query)
    .operationName(operationName)
    .variables(variables)
    .graphQLContext(Map.of("principal", principal))
    .dataLoaderRegistry(newRegistryForThisRequest())
    .build();
CompletableFuture<ExecutionResult> result = graphQL.executeAsync(input);
```

Key types:

- `DataFetcher<T>`: `T get(DataFetchingEnvironment env)`. May return a value, a
  `CompletableFuture`, or a `DataFetcherResult<T>` (data plus errors plus local context).
- `DataFetchingEnvironment`: `getSource()` (parent object), `getArgument(name)`,
  `getGraphQlContext()`, `getDataLoader(name)`, `getSelectionSet()` (look-ahead),
  `getExecutionStepInfo()` (path), `getLocalContext()`.
- Default fetcher is `PropertyDataFetcher` (getters, record components, map keys), so
  you only wire fields that need logic.
- **Only `AsyncExecutionStrategy`** (the default for queries) works with DataLoader.
  Mutations use `AsyncSerialExecutionStrategy` for top-level fields.

Look-ahead with the selection set, the most useful tool for reporting APIs:

```java
DataFetcher<CompletableFuture<MetricResult>> metrics = env -> {
  DataFetchingFieldSelectionSet sel = env.getSelectionSet();
  boolean wantTotals  = sel.contains("totals");
  boolean wantRevenue = sel.contains("rows/edges/node/values/revenue")
                     || sel.contains("totals/revenue");
  MetricQuery q = MetricQuery.from(env.getArguments(), wantTotals, wantRevenue);
  return reportingService.run(q);        // ONE OpenSearch request
};
```

`contains` takes glob patterns over `/`-separated paths (for example `"rows/**"`).

## 2. Spring for GraphQL

Boot starter `spring-boot-starter-graphql` plus a web starter. Schema files go in
`src/main/resources/graphql/**/*.graphqls` (`.gqls` also accepted).

Useful properties:

```properties
spring.graphql.http.path=/graphql
spring.graphql.schema.locations=classpath:graphql/**/
spring.graphql.schema.introspection.enabled=false   # prod, public APIs
spring.graphql.graphiql.enabled=false
spring.graphql.schema.printer.enabled=true          # GET /graphql/schema (internal only)
spring.graphql.websocket.path=/graphql              # enables WebSocket subscriptions
```

### Controllers

```java
@Controller
class ReportController {
  private final ReportingService reporting;
  ReportController(ReportingService reporting) { this.reporting = reporting; }

  @QueryMapping                                     // Query.metrics
  Mono<MetricResult> metrics(@Argument @Valid MetricFilter filter,
                             @Argument TimeRange range,
                             @Argument List<Dimension> groupBy,
                             @Argument Interval interval,
                             DataFetchingFieldSelectionSet selection,
                             @ContextValue String tenantId) {
    return reporting.run(MetricQuery.of(tenantId, filter, range, groupBy, interval, selection));
  }

  @SchemaMapping(typeName = "Campaign", field = "stats")   // Campaign.stats
  CompletableFuture<CampaignStats> stats(Campaign campaign, @Argument TimeRange range,
                                         DataLoader<StatsKey, CampaignStats> loader) {
    return loader.load(new StatsKey(campaign.id(), range));
  }

  @BatchMapping                                     // Campaign.owner, batched
  Mono<Map<Campaign, Owner>> owner(List<Campaign> campaigns) {
    return ownerClient.byIds(campaigns.stream().map(Campaign::ownerId).toList())
        .map(byId -> campaigns.stream().collect(toMap(c -> c, c -> byId.get(c.ownerId()))));
  }

  @MutationMapping
  CreateReportResult createReport(@Argument CreateReportInput input) { /* ... */ }
}
```

Supported handler arguments include `@Argument`, `@Arguments`, `ArgumentValue<T>`
(tells "omitted" from "explicit null"), the source object, `DataLoader<K,V>`,
`@ContextValue`, `@LocalContextValue`, `GraphQLContext`, `Principal`,
`@AuthenticationPrincipal`, `DataFetchingFieldSelectionSet`, `Locale`, and
`DataFetchingEnvironment`. Return types: `T`, `Mono`, `Flux`, `CompletableFuture`,
`Callable` (runs on a configured executor; good with virtual threads),
`DataFetcherResult<T>`.

### Registering DataLoaders explicitly

```java
@Configuration
class LoaderConfig {
  LoaderConfig(BatchLoaderRegistry registry, StatsService stats) {
    registry.forTypePair(StatsKey.class, CampaignStats.class)
        .withOptions(o -> o.setMaxBatchSize(200))
        .registerMappedBatchLoader((keys, env) -> stats.loadMany(keys)); // Mono<Map<K,V>>
  }
}
```

The loader name defaults to the value class name; the `DataLoader<K,V>` controller
argument is resolved by that name. A new `DataLoaderRegistry` is created per request.

### Pagination

```java
@QueryMapping
Window<Campaign> campaigns(ScrollSubrange subrange, @Argument CampaignFilter filter) {
  ScrollPosition pos = subrange.position().orElse(ScrollPosition.keyset());
  int count = Math.min(subrange.count().orElse(20), 200);    // enforce a max
  return repo.findBy(filter, pos, count);                    // Spring Data Window
}
```

Declare `campaigns(first: Int, after: String, ...): CampaignConnection` in SDL; the
Boot starter's `ConnectionTypeDefinitionConfigurer` generates the connection types
and the `Window` result is adapted, with cursors encoded by a `CursorStrategy`
(base64 by default). For OpenSearch, write a custom `ConnectionAdapter` or return
your own connection records built from `search_after` or `after_key`.

### Errors

```java
@ControllerAdvice
class GraphQlErrors {
  @GraphQlExceptionHandler
  GraphQLError badRange(InvalidRangeException ex, GraphqlErrorBuilder<?> b) {
    return b.errorType(ErrorType.BAD_REQUEST).message(ex.getMessage())
            .extensions(Map.of("code", "RANGE_TOO_LARGE", "maxDays", 93)).build();
  }
  @GraphQlExceptionHandler
  GraphQLError timeout(OpenSearchTimeoutException ex, GraphqlErrorBuilder<?> b) {
    return b.errorType(ErrorType.INTERNAL_ERROR).message("Report timed out").build();
  }
}
```

Unresolved exceptions become `INTERNAL_ERROR` with a generic message and the
execution ID, so stack traces do not leak. Lower level: a
`DataFetcherExceptionResolverAdapter` bean.

### Interceptors, context and timeouts

```java
@Component
class TenantInterceptor implements WebGraphQlInterceptor {
  @Override
  public Mono<WebGraphQlResponse> intercept(WebGraphQlRequest req, Chain chain) {
    String tenant = req.getHeaders().getFirst("X-Tenant-Id");
    req.configureExecutionInput((in, b) -> b.graphQLContext(Map.of("tenantId", tenant)).build());
    return chain.next(req);
  }
}

@Bean
TimeoutWebGraphQlInterceptor timeout() { return new TimeoutWebGraphQlInterceptor(Duration.ofSeconds(10)); }
```

Any `graphql.execution.instrumentation.Instrumentation` bean is added to the engine
by Boot. Use `GraphQlSourceBuilderCustomizer` for anything else
(`builder.configureGraphQl(g -> g.preparsedDocumentProvider(...))`).

Startup check worth enabling: `builder.inspectSchemaMappings(report -> log.info(report))`
lists unmapped fields, unmapped controller methods and nullness mismatches.

### Kotlin

```kotlin
@Controller
class ReportController(private val reporting: ReportingService) {
  @QueryMapping
  suspend fun metrics(@Argument filter: MetricFilter, @Argument range: TimeRange): MetricResult =
    reporting.run(filter, range)                          // coroutines supported

  @BatchMapping
  suspend fun owner(campaigns: List<Campaign>): Map<Campaign, Owner> { /* ... */ }
}
```

`Flow<T>` is adapted to `Flux<T>` for `@BatchMapping` and subscriptions.

## 3. Netflix DGS

DGS is built on graphql-java and now runs on Spring for GraphQL internally (use the
`com.netflix.graphql.dgs:dgs-starter`, also known as
`graphql-dgs-spring-graphql-starter`). Netflix recommends sticking to one programming
model per service rather than mixing DGS and Spring annotations.

```java
@DgsComponent
public class ReportDataFetcher {
  @DgsQuery
  public CompletableFuture<MetricResult> metrics(@InputArgument MetricFilter filter,
                                                 @InputArgument TimeRange range,
                                                 DgsDataFetchingEnvironment dfe) {
    return reporting.run(filter, range, dfe.getSelectionSet());
  }

  @DgsData(parentType = "Campaign", field = "owner")
  public CompletableFuture<Owner> owner(DgsDataFetchingEnvironment dfe) {
    Campaign c = dfe.getSource();
    DataLoader<String, Owner> loader = dfe.getDataLoader(OwnerDataLoader.class);
    return loader.load(c.ownerId());
  }
}

@DgsDataLoader(name = "owners", maxBatchSize = 500)
public class OwnerDataLoader implements MappedBatchLoader<String, Owner> {
  private final OwnerClient client;
  public OwnerDataLoader(OwnerClient client) { this.client = client; }
  @Override
  public CompletionStage<Map<String, Owner>> load(Set<String> keys) {
    return CompletableFuture.supplyAsync(() -> client.byIds(keys));
  }
}
```

- Loaders are request-scoped; caching within the request is on by default in DGS 2+.
- `BatchLoaderWithContext` / `MappedBatchLoaderWithContext` give access to the request
  context (tenant, auth).
- Return `Try<V>` per key from a batch loader to fail single keys instead of the batch.
- **Codegen** (Gradle plugin `com.netflix.dgs.codegen`) generates Java/Kotlin types,
  constants for type/field names, and typed client query builders (`GraphQLQueryRequest`,
  `*ProjectionRoot`).
- Federation: `@DgsEntityFetcher(name = "Campaign")` receives `Map<String, Object>` of
  key fields.
- Kotlin: data fetchers may be `suspend` functions.

## 4. DataLoader details (applies to all three)

- **Contract**: `BatchLoader<K,V>` returns `List<V>` in key order with the same size;
  `MappedBatchLoader<K,V>` returns `Map<K,V>` and missing keys become `null`. For
  OpenSearch `mget`/`terms` lookups the mapped form is less error-prone.
- **Keys must have good `equals`/`hashCode`**: use records. For aggregation keys
  include every argument that changes the result (`StatsKey(campaignId, range, tz)`).
- **Per-key failures**: return `List<Try<V>>` from the batch function and build the
  loader with `DataLoaderFactory.newDataLoaderWithTry(...)`, so one bad key fails only
  its own `load()` future instead of the whole batch.
- **Dispatch**: the engine dispatches loaders when a level of the tree has been
  resolved. If a fetcher loads from loader A and then, in the callback, from loader B
  (chained loaders), older versions could wait for the next level. graphql-java 25.0+
  supports chained dispatch:
  `GraphQL.unusualConfiguration(graphQLContext).dataloaderConfig().enableDataLoaderChaining(true)`
  (exact accessor on `GraphQL` versus `GraphQLContext`: check the batching docs for
  your version).
- **Cross-request caching** goes in a `ValueCache` (`DataLoaderOptions.setValueCache`),
  for example Redis. Keep request-level caching separate from shared caching.
- **Statistics**: `DataLoaderRegistry` and `DataLoader.getStatistics()` give batch
  counts and sizes; export them to verify batching actually happens.

## 5. Instrumentation (metrics, logging, limits)

```java
public class SlowOperationInstrumentation extends SimplePerformantInstrumentation {
  private final MeterRegistry meters;
  public SlowOperationInstrumentation(MeterRegistry meters) { this.meters = meters; }

  @Override
  public InstrumentationContext<ExecutionResult> beginExecution(
      InstrumentationExecutionParameters params, InstrumentationState state) {
    long start = System.nanoTime();
    String op = Optional.ofNullable(params.getOperation()).orElse("anonymous");
    return SimpleInstrumentationContext.whenCompleted((result, t) -> {
      long nanos = System.nanoTime() - start;
      meters.timer("graphql.operation", "operation", op,
                   "errors", String.valueOf(result != null && !result.getErrors().isEmpty()))
            .record(nanos, TimeUnit.NANOSECONDS);
    });
  }
}
```

- `SimplePerformantInstrumentation` is the no-op base class (replaces the old
  `SimpleInstrumentation`). Combine several with `ChainedInstrumentation`.
- Built-ins: `MaxQueryDepthInstrumentation`, `MaxQueryComplexityInstrumentation`,
  `TracingInstrumentation` (Apollo tracing format, legacy).
- Hooks include `beginExecution`, `beginParse`, `beginValidation`,
  `beginExecuteOperation`, `beginFieldFetch` (renamed in recent versions; check the
  javadoc), `instrumentDataFetcher`, `instrumentExecutionResult`.
- Prefer tagging by **operation name**, not query text; require clients to name
  operations (reject or label anonymous ones).

## 6. Observability and tracing

- **Spring for GraphQL + Micrometer**: `GraphQlObservationInstrumentation` (auto-
  configured by Boot when Actuator/observation is present) emits a `graphql.request`
  observation per request and `graphql.datafetcher` per *non-trivial* data fetcher
  (plain property reads are skipped), plus DataLoader batch observations in recent
  versions. These become metrics and traces (OTLP, Zipkin) through Micrometer Tracing.
- **OpenTelemetry Java agent** ships graphql-java instrumentation (operation spans;
  data-fetcher spans are off by default and can be very noisy). Check the agent's
  instrumentation list for current flags.
- What to record per operation: operation name, client name/version header, duration,
  error count by `extensions.code`, depth and complexity score, number of backend
  calls, OpenSearch `took` time, DataLoader batch sizes.
- Field-usage metrics (which fields each client selects) are what make safe
  deprecation possible. Apollo GraphOS collects these from the router; without it, log
  normalised operation signatures.
- Never log variables verbatim if they can contain personal data.

## 7. Testing

### Spring for GraphQL

```java
@GraphQlTest(ReportController.class)              // slice: controllers + GraphQL infra
class ReportControllerTest {
  @Autowired GraphQlTester tester;
  @MockitoBean ReportingService reporting;        // @MockBean on Boot 3.3 and older

  @Test
  void returnsBucketedCounts() {
    when(reporting.run(any())).thenReturn(Mono.just(fixture()));
    tester.documentName("metricsByDay")           // src/test/resources/graphql-test/metricsByDay.graphql
          .variable("from", "2026-09-01T00:00:00Z")
          .variable("to",   "2026-09-08T00:00:00Z")
          .execute()
          .path("metrics.rows.edges[*].node.values.count")
          .entityList(Long.class).hasSize(7);
  }

  @Test
  void rejectsOversizedRange() {
    tester.document("{ metrics(filter:{}, range:{from:\"2020-01-01T00:00:00Z\", to:\"2026-01-01T00:00:00Z\"}) { totals { count } } }")
          .execute()
          .errors().expect(e -> e.getErrorType() == ErrorType.BAD_REQUEST).verify();
  }
}
```

- Testers: `ExecutionGraphQlServiceTester` (server-side, no transport),
  `HttpGraphQlTester` (via `WebTestClient`, mock or live server),
  `WebSocketGraphQlTester` (subscriptions).
- `.errors().verify()` fails the test if any unexpected error is present; filter
  expected ones with `.errors().filter(...)`.
- Dependency: `org.springframework.graphql:spring-graphql-test`.
- The `@GraphQlTest` annotation's package moved in Spring Boot 4's modularisation;
  let the IDE import it.

### DGS

```java
@SpringBootTest(classes = {ReportDataFetcher.class, OwnerDataLoader.class})
@EnableDgsTest
class ReportDataFetcherTest {
  @Autowired DgsQueryExecutor executor;
  @MockitoBean ReportingService reporting;

  @Test
  void totals() {
    Long count = executor.executeAndExtractJsonPathAsObject(
        "{ metrics(filter:{}, range:{from:\"...\", to:\"...\"}) { totals { count } } }",
        "data.metrics.totals.count", Long.class);
    assertThat(count).isEqualTo(42L);
  }
}
```

### What to test, beyond resolvers

- **Batching works**: assert the backend mock was called once for N parents.
- **Limits work**: depth, complexity, page-size and range limits each have a test that
  sends an over-limit query and expects rejection.
- **Schema compatibility**: diff against the last released schema in CI.
- **Golden operations**: run the real client operations (from the persisted query
  list) against the schema in CI to catch breaks.
- **OpenSearch integration**: Testcontainers (`opensearchproject/opensearch`) with a
  seeded index to check the generated aggregation DSL and bucket mapping, including
  empty buckets and time zones.
