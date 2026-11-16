# Apollo Federation v2 reference

Back to [SKILL.md](../SKILL.md). Partly informed by Apollo's `apollo-federation`
and `apollo-router` agent skills (MIT, https://github.com/apollographql/skills),
which go deeper on router YAML and Rover.

## 1. Architecture

```
clients ──> Router (query planner) ──┬──> subgraph: campaigns (Spring for GraphQL)
                │                    ├──> subgraph: reporting  (DGS, OpenSearch)
          supergraph schema          └──> subgraph: users      (any language)
       (composed in CI / GraphOS)
```

- **Subgraph**: a normal GraphQL service whose schema uses federation directives and
  also exposes `_service { sdl }` and `_entities(representations: [_Any!]!): [_Entity]!`.
- **Composition** merges subgraph schemas into a **supergraph** schema (Rover CLI
  `rover supergraph compose`, or GraphOS managed federation). Composition errors are
  caught before deploy.
- **Router** (Apollo Router, Rust; the Node `@apollo/gateway` is legacy) exposes the
  **API schema** (supergraph minus `@inaccessible` parts), plans each operation into
  subgraph fetches (parallel and sequential), and merges results.
- Federation versions: subgraphs declare a version in `@link`. v2.11 (June 2025) and
  v2.12 (November 2025, requires Router 2.8.0+) were the latest I could verify; newer
  versions may exist. Use the highest version all your routers support.

## 2. Entities

```graphql
extend schema
  @link(url: "https://specs.apollo.dev/federation/v2.12",
        import: ["@key", "@shareable", "@external", "@requires", "@inaccessible"])

# campaigns subgraph: owns Campaign
type Campaign @key(fields: "id") {
  id: ID!
  name: String!
  budget: Decimal
}

# reporting subgraph: contributes stats to Campaign
type Campaign @key(fields: "id") {
  id: ID!
  stats(range: TimeRange!): CampaignStats      # resolved here
}
```

- `@key(fields: "id")` marks an entity; compound keys (`"tenantId id"`) and multiple
  `@key`s are allowed. `@key(fields: "id", resolvable: false)` lets a subgraph
  *reference* an entity without implementing a reference resolver.
- The router fetches entity fields from a subgraph by sending
  `_entities(representations: [{__typename: "Campaign", id: "c1"}, ...])`; the
  subgraph's **reference resolver** turns each representation into an object. It
  receives a **list** of representations per fetch, so it must be batched.

## 3. Directives (Federation 2)

| Directive | Use |
|---|---|
| `@key(fields, resolvable)` | Declare an entity and its identity |
| `@shareable` | Field or type can be resolved by more than one subgraph (value types, shared fields) |
| `@external` | Field defined elsewhere, referenced here by `@requires` or `@provides` |
| `@requires(fields: "...")` | This field's resolver needs other subgraphs' fields (router fetches them first) |
| `@provides(fields: "...")` | At this path, this subgraph can also return those external fields |
| `@override(from: "other", label: "percent(10)")` | Move a field's ownership between subgraphs, optionally progressively |
| `@inaccessible` | Hide from the API schema (staged rollouts, internal fields) |
| `@tag(name:)` | Metadata for contracts and tooling |
| `@interfaceObject` | Contribute fields to an interface entity defined elsewhere |
| `@authenticated`, `@requiresScopes`, `@policy` | Router-enforced authorisation (GraphOS feature) |
| `@cost(weight:)`, `@listSize(...)` | Inputs to router demand control |

`@requires` is the classic reporting case: `stats` might `@requires(fields: "timeZone")`
so the reporting subgraph gets the campaign's time zone without its own lookup.

## 4. JVM subgraphs

### Spring for GraphQL (1.3+)

```java
@Configuration
class FederationConfig {
  @Bean FederationSchemaFactory federationSchemaFactory() { return new FederationSchemaFactory(); }
  @Bean GraphQlSourceBuilderCustomizer federation(FederationSchemaFactory f) {
    return b -> b.schemaFactory(f::createGraphQLSchema);
  }
}

@Controller
class CampaignEntityController {
  // Batched reference resolver: one call per _entities fetch, results in id order
  @EntityMapping
  List<Campaign> campaign(@Argument List<String> idList) { return repo.findAllInOrder(idList); }

  @SchemaMapping
  CompletableFuture<CampaignStats> stats(Campaign c, @Argument TimeRange range,
                                         DataLoader<StatsKey, CampaignStats> loader) {
    return loader.load(new StatsKey(c.id(), range));
  }
}
```

Needs the Apollo federation-jvm library on the classpath (Maven group
`com.apollographql.federation`; artifact `federation-graphql-java-support`). Map
`@EntityMapping` exceptions with `@GraphQlExceptionHandler`; they appear in the
`_entities` response errors.

### DGS

```java
@DgsComponent
public class CampaignEntities {
  @DgsEntityFetcher(name = "Campaign")
  public Campaign campaign(Map<String, Object> values) {
    return new Campaign((String) values.get("id"));        // stub; fields resolved below
  }
  @DgsData(parentType = "Campaign", field = "stats")
  public CompletableFuture<CampaignStats> stats(DgsDataFetchingEnvironment dfe) { /* DataLoader */ }
}
```

DGS invokes the entity fetcher per representation; return a light stub and do the real
work in DataLoader-backed field fetchers so the work is batched.

### Plain graphql-java

Use `com.apollographql.federation.graphqljava.Federation.transform(schema)
.fetchEntities(...).resolveEntityType(...).build()` from federation-jvm.

## 5. Design guidance for a reporting subgraph

- **Prefer a dedicated root field** (`reports`, `metrics`) for dashboards. Entity
  extension (`Campaign.stats`) is convenient but lets clients ask for stats on every
  item of a 500-item list from another subgraph, which turns into one `_entities`
  call with 500 representations. That is fine **only** if your reference resolver and
  `stats` field turn it into one OpenSearch request (a `terms` or `filters` aggregation
  keyed by campaign ID), and the cost limits know about it.
- Put `@listSize`/`@cost` on reporting fields so router demand control can price them.
- Keep reporting types `@shareable` only when the values are genuinely identical
  across subgraphs.
- Query plans are visible: inspect them (Router `include_query_plan`-style
  debugging, or Apollo Sandbox) when an operation is slow, to see sequential hops.
- Subgraph-to-subgraph calls should go through the router or be avoided; do not
  build a hidden mesh.

## 6. Operational notes

- Schema checks in CI (`rover subgraph check`) compare against recent client
  operations, which is the safest way to evolve a shared graph.
- Subgraphs should not be publicly reachable; the router is the edge. Still enforce
  auth in subgraphs.
- Router config handles CORS, headers propagation, persisted queries, demand control,
  rate limits, entity caching and telemetry (OpenTelemetry). See Apollo's
  `apollo-router` skill for YAML.
- Some router features (safelisting, demand control, authorisation directives,
  entity caching) depend on GraphOS plan; check the plan before designing around them.
