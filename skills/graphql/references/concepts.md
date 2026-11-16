# GraphQL concepts, use cases, and when to use it

Back to [SKILL.md](../SKILL.md). A plain-English glossary first, then typical use
cases, then when GraphQL is and is not the right tool. The other reference files go
deeper on each topic; this one is for "what does this word mean" and "should we use
GraphQL here at all".

## 1. Glossary

### Schema and type system

- **Schema**: the server's published contract listing every type, field and
  operation a client may ask for. Requests are checked against it before anything
  runs, so a client cannot ask for a field that does not exist.
- **SDL (Schema Definition Language)**: the text syntax for writing a schema, usually
  in `.graphqls` files. Example: `type Campaign { id: ID! name: String! }`.
- **Type system**: the set of kinds a schema is built from: object, scalar, enum,
  interface, union, input, plus the list and non-null wrappers. Every field has
  exactly one type, which is what makes responses predictable and tooling possible.
- **Object type**: a named type with fields, the main building block of responses.
  `type User { id: ID! email: String }`.
- **Field**: one named value on a type, which can take arguments and has its own
  resolver. Clients choose fields one by one, which is why a response only contains
  what was asked for.
- **Scalar**: a leaf value with no sub-fields. The spec defines five: `Int` (signed
  32-bit, so it overflows above 2,147,483,647), `Float`, `String`, `Boolean` and `ID`.
- **Custom scalar**: a scalar the server defines and serialises itself, such as
  `DateTime`, `Long` or `Decimal`. The built-in `@specifiedBy(url:)` directive points
  clients to the format it follows.
- **Enum**: a fixed set of allowed values, such as `enum Interval { HOUR DAY WEEK }`.
  Use enums for closed sets (dimensions, sort keys) so clients get validation and
  autocomplete instead of free-form strings.
- **Interface**: an abstract type listing fields that several object types share.
  `interface Node { id: ID! }` lets a client fetch any object by ID and then branch
  on its concrete type.
- **Union**: a type that is "one of" several object types that need not share any
  fields. `union SearchResult = Campaign | User`.
- **Input type**: an object-like type used only for arguments, never for output.
  `input TimeRange { from: DateTime! to: DateTime! }`. It is kept separate from output
  types because the two evolve under different compatibility rules.
- **`@oneOf` input**: an input type where the client must set exactly one field, for
  example look up a user by `id` or by `email` but not both. It is in the September
  2025 spec edition; check your server library supports it.
- **List**: a wrapper meaning "many of this type", written `[T]`. `[Tag!]!` means the
  list is never null and no item in it is null.
- **Non-null**: the `!` wrapper meaning the field is promised never to be null. It
  makes clients simpler, but if the server cannot deliver it, the null spreads upward
  (see null propagation below).
- **Deprecation**: marking a field, argument, input field or enum value with
  `@deprecated(reason: "...")` so tools warn clients while it still works. This is
  how GraphQL APIs evolve without numbered versions.

### Operations and documents

- **Document**: the text a client sends, containing one or more operations and any
  fragments they use. The server parses and validates the whole document before
  executing one operation from it.
- **Operation**: one request inside a document: a query, a mutation or a
  subscription, ideally with a name (`query CampaignPage { ... }`). Named operations
  make logs, metrics and persisted queries usable. Each operation starts at the
  matching root type: `Query`, `Mutation` or `Subscription`.
- **Query**: a read operation. The spec allows the server to resolve its top-level
  fields in parallel.
- **Mutation**: a write operation. Its top-level fields run one after another, in
  order, so `createReport` then `publishReport` in one request is predictable.
- **Subscription**: a long-lived operation that returns a stream of results, one per
  event, usually over WebSocket or Server-Sent Events. Good for discrete events such
  as alerts; rarely the right fit for refreshing aggregated dashboards.
- **Arguments**: named inputs on a field, such as `campaign(id: "c1")`. Any field at
  any depth can take arguments, not just top-level ones.
- **Variables**: placeholders like `$id` declared on the operation and sent as
  separate JSON. They keep the document text constant across calls, which is what
  makes caching, persisted queries and safe logging possible.
- **Alias**: a client-chosen name for a field in the response, which lets one request
  call the same field twice with different arguments.
  `thisWeek: metrics(range: $a) { ... } lastWeek: metrics(range: $b) { ... }`.
  Also an abuse vector, because 200 aliases cost 200 calls.
- **Fragment**: a named, reusable set of fields on a type
  (`fragment CampaignHeader on Campaign { id name }`), spread into a query with
  `...CampaignHeader`. UI frameworks use them to let each component declare its own
  data needs. An inline fragment, `... on Campaign { budget }`, asks for fields that
  only one concrete type of an interface or union has.
- **Directive**: an annotation starting with `@` that changes how something is
  treated. Executable directives go in requests (built-ins `@include(if:)` and
  `@skip(if:)`); schema directives go in SDL (`@deprecated`, `@specifiedBy`, `@oneOf`,
  or your own such as `@auth`).
- **`@defer` and `@stream`**: directives that let the server send slow parts of a
  response later, in pieces. They are not in the September 2025 spec edition; some
  servers and clients support them experimentally, and the wire format has changed
  before, so treat them as non-standard.
- **Introspection**: the built-in ability to query the schema itself through
  `__schema` and `__type` (plus `__typename` on every object, which clients use to tell
  which branch of a union they got). It powers GraphiQL, codegen and IDE autocomplete;
  public APIs often disable it in production, though that alone is not a security
  control.

### Execution

- **Resolver**: the function that produces the value for one field, given the parent
  object, the field's arguments and the request context. The server calls one per
  field per object, walking the request tree.
- **Data fetcher (`DataFetcher`)**: graphql-java's name for a resolver,
  `T get(DataFetchingEnvironment env)`, where the environment gives the parent object
  (`getSource()`), arguments, context, DataLoaders and selection set. If none is wired,
  the default `PropertyDataFetcher` reads a getter, record component or map key with
  the field's name.
- **Selection set**: the `{ ... }` block listing which fields to return for an
  object. Resolvers can inspect the selection set below them ("look-ahead") to fetch
  only what was asked, for example building one OpenSearch request with only the
  selected aggregations.
- **Parse, validate, execute**: the three steps of every request. Validation checks
  the document against the schema (fields exist, argument types match), and depth and
  cost limits usually run there too, before any backend is touched; execution then
  walks the operation, calls resolvers level by level, and builds JSON in the same
  shape as the request.
- **Context**: per-request data available to every resolver, such as the signed-in
  user, tenant and DataLoader registry. Anything request-scoped belongs here, never in
  a shared singleton.
- **N+1 problem**: one call to fetch a list, then one more call per item for a nested
  field. `campaigns(first: 50) { owner { name } }` naively makes 51 backend calls;
  this is GraphQL's default performance failure.
- **DataLoader**: a per-request utility that collects every key requested at one
  level of the tree, then calls a batch function once with all of them, and caches
  per key for the rest of the request. It turns those 51 calls into 2. The batch
  function must return one result per key in key order, or a map from key to value.

### Responses and errors

- **Response**: a JSON object with `data` (the result, shaped like the request),
  optional `errors` (a list), and optional `extensions` (anything extra, such as cost
  or tracing). Each error can carry its own `extensions` with a machine-readable
  `code` such as `BAD_REQUEST`, because `message` is for humans.
- **Request error vs field error**: a request error means the document failed to
  parse or validate, so nothing ran and there is no `data`. A field (execution) error
  means one resolver failed: that field becomes `null`, an entry appears in `errors`
  with a `path` pointing at it, and the rest of the response still comes back.
- **Partial data**: a response with both `data` and `errors`. This is normal in
  GraphQL, and clients must handle it rather than treating any error as total failure.
- **Null propagation ("null bubbling")**: if a non-null field fails, its parent
  becomes null instead, and so on upward until a nullable field absorbs it, possibly
  making all of `data` null. This is why fields backed by fallible services should
  usually be nullable.
- **Errors as data**: modelling expected business failures (validation failed, quota
  exceeded) as types in the schema, such as a union result
  `CreateReportSuccess | QuotaExceeded`, instead of as entries in `errors`. Clients get
  typed, exhaustive handling.

### Pagination

- **Connection**: the Relay convention for a paginated list: a type with `edges` and
  `pageInfo`, taking `first`/`after` (forward) or `last`/`before` (backward).
  Widely used even by non-Relay clients.
- **Edge**: one item in a connection, holding the `node` (the item itself) and its
  `cursor`. Edges are where per-relationship data, such as "added to team on", can live.
- **Cursor**: an opaque string marking a position in the list, which the client sends
  back as `after` to get the next page. It is usually a base64-encoded sort key, not a
  row number, so pages stay correct while data changes.
- **PageInfo**: the object telling the client whether there is more:
  `hasNextPage`, `hasPreviousPage`, `startCursor`, `endCursor`.

### Performance and security

- **Persisted query (persisted document)**: a document stored on the server ahead of
  time under an ID, usually its hash, so the client sends the ID instead of the full
  text. Saves bandwidth and allows GET requests that CDNs can cache.
- **APQ (Automatic Persisted Queries)**: Apollo's runtime variant: the client sends a
  SHA-256 hash in `extensions.persistedQuery`; on a miss the server replies
  `PERSISTED_QUERY_NOT_FOUND` and the client retries with the full text, which the
  server then stores. It accepts any query, so it is a bandwidth optimisation, not a
  security control.
- **Trusted documents**: persisted documents registered at build time from your own
  client code, with the server refusing anything not on the list. This is an
  allowlist, the strongest defence against expensive or malicious queries, but it only
  works when you control all the clients.
- **Query depth limit**: rejecting documents nested deeper than a set number of
  levels (typically 7 to 15). Cheap, but misses wide or aliased queries.
- **Query complexity (cost) analysis**: giving each field a cost, multiplied by list
  sizes such as `first: 100`, and rejecting documents over a budget before execution.
  Clients can also be rate-limited by total cost rather than request count. There is a
  community draft spec for `@cost` and `@listSize` directives, which Apollo Router
  implements as "demand control".

### Federation and governance

- **Federation**: splitting one logical GraphQL API across several services owned by
  different teams, composed into a single schema that clients see as one graph.
  Apollo Federation v2 is the dominant implementation.
- **Subgraph**: one team's GraphQL service within a federated graph. It is an
  ordinary GraphQL server plus federation directives and two extra fields
  (`_service` and `_entities`).
- **Supergraph**: the combined schema produced from all subgraphs, plus the routing
  information the router needs. Clients see the public part of it (the API schema).
- **Entity**: a type that more than one subgraph can contribute fields to, identified
  by a key. A `Campaign` might get `name` from the campaigns subgraph and `stats` from
  the reporting subgraph.
- **`@key`**: the directive that marks a type as an entity and names the fields that
  identify it, such as `type Campaign @key(fields: "id")`.
- **Reference resolver**: the function in a subgraph that turns a key such as
  `{__typename: "Campaign", id: "c1"}` into a full object when the router asks through
  `_entities`. It receives many keys at once and must be batched.
- **Router**: the single entry point clients call in a federated graph (Apollo Router,
  written in Rust). It plans each operation into calls to subgraphs, runs them, and
  merges the results. Its step-by-step list of subgraph calls is the query plan,
  which is where to look when a federated query is slow.
- **Composition**: the build step that merges subgraph schemas into a supergraph and
  fails if they conflict. It runs in CI (Rover CLI or a managed registry) so broken
  combinations never reach production.
- **Schema registry**: a service that stores every published version of a schema,
  runs composition and breaking-change checks against real client traffic, and serves
  the current supergraph to routers. Its schema checks run in CI and block a change
  that would break operations clients actually send. Apollo GraphOS and GraphQL Hive
  are the main ones.
- **Schema stitching**: an older way of combining several GraphQL schemas in a
  gateway, with the merge logic in the gateway rather than in each service. Mostly
  replaced by federation for multi-team graphs.

### Transport

- **GraphQL over HTTP**: the convention, being written up as a draft spec, for
  sending GraphQL over HTTP. Servers must accept POST; GET is allowed for queries only,
  never mutations. With the newer `application/graphql-response+json` response type,
  requests that fail validation get a 4xx status; with legacy `application/json`, 200
  is common even when there are errors.
- **GraphQL over WebSocket**: the usual subscription transport. The current protocol
  is the `graphql-ws` library's, with WebSocket subprotocol `graphql-transport-ws`;
  the deprecated `subscriptions-transport-ws` library used a subprotocol confusingly
  named `graphql-ws`, and the two are not compatible.
- **GraphQL over SSE**: subscriptions delivered as Server-Sent Events over plain HTTP.
  Simpler through proxies and load balancers than WebSocket; Spring for GraphQL
  supports both.

### JVM: graphql-java, Spring for GraphQL, Netflix DGS

- **graphql-java**: the Java GraphQL engine that Spring for GraphQL, DGS and
  graphql-kotlin all run on. Knowledge of its types (`DataFetcher`,
  `DataFetchingEnvironment`, `ExecutionInput`) carries across all of them. Seeing
  `RuntimeWiring.newRuntimeWiring()`, which attaches data fetchers to a schema parsed
  from SDL, means a service uses raw graphql-java.
- **Instrumentation**: graphql-java's hook interface around parsing, validation,
  execution and each field fetch. Used for metrics, tracing and limits such as
  `MaxQueryDepthInstrumentation` and `MaxQueryComplexityInstrumentation`.
- **Spring for GraphQL**: Spring's official GraphQL integration, built on graphql-java.
  Schema files live in `src/main/resources/graphql/`, and resolvers are methods on
  `@Controller` classes.
- **`@SchemaMapping`**: Spring annotation that makes a controller method the data
  fetcher for one field, such as `@SchemaMapping(typeName = "Book", field = "author")`.
  The parent object arrives as a method parameter.
- **`@QueryMapping`, `@MutationMapping`, `@SubscriptionMapping`**: shortcuts for
  `@SchemaMapping` with the type preset to `Query`, `Mutation` or `Subscription`; the
  field name defaults to the method name.
- **`@BatchMapping`**: Spring shortcut that registers a batch loader and wires the
  field to it in one step. The method receives the whole list of parents and returns a
  map from parent to value, which removes N+1 without hand-written DataLoader code.
- **Netflix DGS**: Netflix's GraphQL framework for Spring Boot, now running on top of
  Spring for GraphQL, known for its code generation of Java and Kotlin types and
  client query builders. Data fetchers live in classes marked `@DgsComponent`.
- **`@DgsQuery`, `@DgsMutation`, `@DgsData`**: DGS's resolver annotations.
  `@DgsQuery` is shorthand for `@DgsData(parentType = "Query")`; `@DgsData(parentType
  = "Campaign", field = "owner")` resolves a nested field.
- **`@DgsDataLoader`**: marks a class implementing a batch loader so DGS registers it
  per request; fetchers get it with `dfe.getDataLoader(OwnerDataLoader.class)`.

## 2. Use cases

Situations where GraphQL tends to pay for itself, each with a concrete example.

| Use case | Example | Why GraphQL fits |
|---|---|---|
| Aggregating many backends for UI clients | A product page needs catalogue, price, stock, reviews and recommendations from five services. One GraphQL layer (often called a backend-for-frontend) serves `product(id) { name price stock reviews(first: 3) }` in one round trip. | The client makes one request; the server fans out in parallel and batches; the UI team changes what it fetches without a backend release. |
| Mobile, bandwidth-sensitive clients | A mobile feed screen needs 6 of a post's 40 fields, and older app versions stay installed for years. GraphQL started at Facebook in 2012 for exactly this. | No over-fetching, one round trip on high-latency networks, and old app versions keep working because fields are only added and deprecated, never versioned away. |
| One product API, many client shapes | A web app, an iOS app, an Android app and a partner integration each need different slices of the same orders and customers. GitHub and Shopify run public APIs this way. | Each client asks for its own shape from one schema, instead of the server maintaining a growing set of tailored endpoints. |
| A federated graph across teams | Campaigns, users and reporting are owned by three teams. Each publishes a subgraph; the router lets a client ask `campaign(id) { name owner { email } stats(range: $r) { revenue } }` as if it were one service. | Teams ship independently; composition and schema checks in CI catch conflicts; clients see one consistent API. |
| A reporting API with flexible field selection | A dashboard tile asks `metrics(range: LAST_7_DAYS, interval: DAY) { series { start values { count revenue } } }`; another asks for unique users by country. The resolver turns each selection into one OpenSearch aggregation request. | Clients pick metrics and dimensions from typed enums; the server computes only the aggregations that were selected; limits on range, buckets and cost keep it bounded. |

## 3. When to use it, when not to

| Situation | Verdict | Use instead | Why |
|---|---|---|---|
| Several UI clients needing different slices of the same data | Use GraphQL | | Client-shaped responses without endpoint sprawl |
| UI that aggregates many backend services per screen | Use GraphQL | | One round trip; server-side fan-out and batching |
| Multiple teams contributing to one customer-facing API | Use GraphQL (federation) | | Independent ownership with composed, checked schema |
| Reporting or dashboard API where clients choose metrics and dimensions | Use GraphQL, with strict limits | | Field selection maps well to "compute only what was asked"; must be bounded by range, buckets and cost |
| Simple CRUD with one client (for example an admin screen for one table) | Avoid | REST | Schema, resolvers and limits are overhead with no payoff when the shape never varies |
| Service-to-service internal calls | Avoid | gRPC | Binary Protocol Buffers, generated stubs, deadlines and streaming are built for RPC; GraphQL's flexibility is not needed between services you control |
| Bulk data export or file transfer | Avoid | REST download, pre-signed S3 URLs, batch jobs | GraphQL returns one JSON document per request, which is poor for gigabytes or binary; file upload is not in the core spec |
| Public, read-heavy content that should sit behind a CDN | Avoid, or GET plus persisted queries only | REST + CDN | A URL per resource caches naturally; GraphQL defaults to POST to one URL and needs extra work to cache |
| Ad hoc analysis by analysts (joins, arbitrary group-bys) | Avoid | A SQL endpoint on the warehouse, or a semantic layer | Analysts need open-ended queries; a GraphQL schema has to anticipate every question and would be rebuilt as a weaker SQL |
| High-frequency streaming of raw events (thousands per second) | Avoid | Kafka, plain WebSocket or SSE | Subscriptions run a full GraphQL execution per event; a stream or message bus is cheaper |
| Webhooks or event notifications to third parties | Avoid | Webhooks (HTTP callbacks) | Push to a URL the partner owns; GraphQL is a request/response API |
| Public API for unknown third parties | Use with care | REST if the shape is simple | Possible (GitHub, Shopify do it), but needs cost limits, rate limiting by cost, and no trusted-document allowlist is possible |

## 4. GraphQL vs REST vs gRPC

| | GraphQL | REST | gRPC |
|---|---|---|---|
| Contract | Schema in SDL; strongly typed | Optional (OpenAPI); conventions per team | `.proto` files; strongly typed |
| Who shapes the response | The client, per request | The server, per endpoint | The server, per method |
| Endpoints | One URL; many operations | One URL per resource | One method per RPC |
| Transport and format | Usually HTTP POST, JSON; subscriptions over WebSocket or SSE | HTTP with methods and status codes; usually JSON | HTTP/2 with binary Protocol Buffers |
| HTTP caching | Hard by default (POST); possible with GET plus persisted queries | Natural (GET, URLs, `Cache-Control`, CDNs) | Not HTTP-cacheable; cache in the application |
| Streaming | Subscriptions | Not built in (use SSE or WebSocket alongside) | Built in: server, client and bidirectional streaming |
| Browser support | Native | Native | Needs gRPC-Web and a proxy such as Envoy |
| Errors | `errors` list alongside partial `data`; often HTTP 200 | HTTP status codes | gRPC status codes |
| Evolution | Add and deprecate fields; no versions | Often versioned URLs (`/v2/`) | Add fields with new numbers; never reuse numbers |
| Main risks | N+1, unbounded query cost, harder caching | Over- and under-fetching, endpoint sprawl | Browser and debugging friction; tight coupling through generated code |
| Best for | UI-facing APIs with many shapes; aggregation layers; federated product APIs | Simple resources, public cacheable content, file transfer | Internal service-to-service calls; low latency; streaming |

## Sources

- GraphQL specification, September 2025 edition (type system, built-in scalars and
  directives, execution, error propagation, introspection): https://spec.graphql.org/September2025/
- GraphQL learn pages: security (trusted documents, depth, complexity):
  https://graphql.org/learn/security/ ; serving over HTTP:
  https://graphql.org/learn/serving-over-http/ ; caching:
  https://graphql.org/learn/caching/
- GraphQL over HTTP draft spec: https://graphql.github.io/graphql-over-http/draft/
- Origin at Facebook in 2012 for mobile News Feed: https://engineering.fb.com/2015/09/14/core-infra/graphql-a-data-query-language/
- IBM GraphQL Cost Directive draft spec: https://ibm.github.io/graphql-specs/cost-spec.html
- Relay cursor connections spec: https://relay.dev/graphql/connections.htm
- Apollo Automatic Persisted Queries: https://www.apollographql.com/docs/apollo-server/performance/apq
- Apollo Federation directives: https://www.apollographql.com/docs/graphos/reference/federation/directives
- GraphQL Hive schema registry: https://the-guild.dev/graphql/hive/docs/schema-registry
- graphql-ws protocol (`graphql-transport-ws`): https://github.com/enisdenjo/graphql-ws/blob/master/PROTOCOL.md ;
  npm package notes on the legacy `subscriptions-transport-ws` naming: https://www.npmjs.com/package/graphql-ws
- graphql-java data fetching: https://www.graphql-java.com/documentation/data-fetching/
- Spring for GraphQL controllers and transports:
  https://docs.spring.io/spring-graphql/reference/controllers.html ,
  https://docs.spring.io/spring-graphql/reference/transports.html
- Netflix DGS data fetching: https://netflix.github.io/dgs/datafetching/
- gRPC core concepts and gRPC-Web: https://grpc.io/docs/what-is-grpc/core-concepts/ ,
  https://grpc.io/docs/platforms/web/basics/
- Incremental delivery (`@defer`/`@stream`) RFC, not yet in the spec:
  https://github.com/graphql/graphql-over-http/blob/main/rfcs/IncrementalDelivery.md
