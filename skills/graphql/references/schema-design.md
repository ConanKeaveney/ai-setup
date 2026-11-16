# Schema design reference

Back to [SKILL.md](../SKILL.md). Ground rules partly adapted from Apollo's
`graphql-schema` agent skill (MIT, https://github.com/apollographql/skills).

## 1. Core type system recap

```graphql
"""A marketing campaign."""                 # description, shown in tooling
type Campaign implements Node {
  id: ID!
  name: String!
  status: CampaignStatus!
  owner: User                                # nullable: separate service, may fail
  createdAt: DateTime!
  tags: [String!]!                           # list never null, items never null
  stats(range: TimeRange!): CampaignStats    # field arguments are normal
}
interface Node { id: ID! }                   # shared shape; client uses ... on Campaign
union SearchResult = Campaign | User         # disjoint types; no shared fields required
enum CampaignStatus { DRAFT ACTIVE PAUSED ENDED }
scalar DateTime                              # serialisation defined in code
input TimeRange { from: DateTime!, to: DateTime! }  # inputs cannot reuse output types
directive @auth(role: Role!) on FIELD_DEFINITION     # custom schema directive
```

Operations and fragments on the client side:

```graphql
query CampaignPage($id: ID!, $range: TimeRange!) {
  campaign: node(id: $id) {
    ... on Campaign { ...CampaignHeader stats(range: $range) { impressions clicks } }
  }
}
fragment CampaignHeader on Campaign { id name status owner { name } }
```

- **Interfaces versus unions**: interface when the types share fields that clients
  query generically; union when results are unrelated (search results, mutation
  result variants).
- **Input versus output types** are separate by spec. Do not try to share them;
  they evolve under different compatibility rules.
- **Custom scalars**: `DateTime` (ISO-8601 with offset), `Date`, `Long`, `Decimal`
  (as a string), `JSON` (avoid; it is an escape hatch with no typing). In Java,
  `com.graphql-java:graphql-java-extended-scalars` provides `DateTime`, `Date`, `Long`,
  `BigDecimal`, `JSON` and others.

## 2. Naming

| Element | Convention | Example |
|---|---|---|
| Types, interfaces, unions, enums, inputs | PascalCase | `MetricResult`, `TimeRange` |
| Fields, arguments | camelCase | `bucketStart`, `groupBy` |
| Enum values | SCREAMING_SNAKE_CASE | `LAST_7_DAYS` |
| Inputs | `...Input` (mutations), descriptive for filters | `CreateReportInput`, `MetricFilter` |
| Mutation payloads | `...Payload` | `CreateReportPayload` |
| Mutations | verb + noun | `createReport`, `pauseCampaign` |
| Booleans | `is`/`has`/`can` prefix | `isPartial`, `hasNextPage` |

Avoid `get` prefixes on query fields (`campaign`, not `getCampaign`), and avoid
abbreviations that only make sense inside the team.

## 3. Nullability

GraphQL fields are nullable by default so that one failure nulls one field, not the
whole response. A non-null field that fails propagates null to its nearest nullable
parent ("null bubbling"), possibly up to `data: null`.

Decision rule per field:

| Field | Recommendation |
|---|---|
| `id`, fields on the same record that always exist | `!` |
| Field resolved from another service, index or aggregation | nullable |
| Lists | `[T!]!`; an empty list means "none" |
| Root query fields fetching by ID | nullable (`null` means not found) |
| Mutation payload | non-null payload, nullable result object inside |
| Arguments | `!` only if truly required. Adding a required argument later is breaking. |

Compatibility asymmetry (remember it as "outputs can tighten, inputs can loosen"):

- **Output** nullable to non-null is safe; non-null to nullable is **breaking**.
- **Input** non-null to nullable is safe; nullable to non-null is **breaking**.

The "semantic nullability" / `@semanticNonNull` work in the GraphQL Nullability WG
aims to separate "null because of error" from "null as a value". It is not in the
September 2025 spec edition; do not depend on it in a JVM server without checking
library support.

## 4. Pagination (Relay connections)

Spec: https://relay.dev/graphql/connections.htm

```graphql
type Query {
  campaigns(first: Int = 20, after: String, filter: CampaignFilter, orderBy: CampaignOrder): CampaignConnection!
}
type CampaignConnection {
  edges: [CampaignEdge!]!
  pageInfo: PageInfo!
  totalCount: Long          # optional extension, NOT in the Relay spec; can be expensive
}
type CampaignEdge { cursor: String!, node: Campaign! }
type PageInfo {
  hasNextPage: Boolean!
  hasPreviousPage: Boolean!
  startCursor: String
  endCursor: String
}
```

- Arguments: forward `first`/`after`, backward `last`/`before`. Support forward only
  if backward paging is not needed; that is allowed.
- **Cursors are opaque**: base64 of a sort key plus tiebreaker (for example
  `{"ts":..., "id":...}`), or an OpenSearch `search_after` array or a composite
  `after_key`. Never a raw offset if the data changes under the reader.
- Enforce `first` max (for example 100 to 500); return a validation error above it.
- `totalCount` should be opt-in and documented as approximate if it comes from
  `track_total_hits` limits. On OpenSearch, total hits are only exact up to 10,000 by
  default unless `track_total_hits: true`.
- Many teams add a `nodes: [Campaign!]!` shortcut alongside `edges`.
- Spring for GraphQL generates `XConnection`/`XEdge`/`PageInfo` automatically for any
  field returning `XConnection` (the Boot starter registers
  `ConnectionTypeDefinitionConfigurer`), and adapts Spring Data `Window` results.

For bucketed aggregations, connections are for **rows of group-by keys**, not for
time buckets. A time series with at most N buckets is better returned as a plain list,
bounded by the range and interval limits.

## 5. Errors: top-level errors versus errors-as-data

Two channels:

1. **Top-level `errors`**: unexpected failures, validation, auth failures, timeouts.
   Each has `message`, `path`, `locations`, and `extensions` (put a machine-readable
   `code` and `classification` here). graphql-java and Spring map exceptions here via
   `DataFetcherExceptionResolver` and `@GraphQlExceptionHandler`. Spring's
   `ErrorType`: `BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `INTERNAL_ERROR`.
2. **Errors as data**: expected business outcomes that the client must handle, typed
   in the schema (Sasha Solomon, "200 OK! Error Handling in GraphQL").

```graphql
type Mutation { createReport(input: CreateReportInput!): CreateReportResult! }
union CreateReportResult = CreateReportSuccess | ValidationFailed | QuotaExceeded
type CreateReportSuccess { report: Report! }
interface UserError { message: String!, code: String! }
type ValidationFailed implements UserError { message: String!, code: String!, field: String }
type QuotaExceeded implements UserError { message: String!, code: String!, retryAfter: DateTime }
```

Simpler, payload-style alternative (common in Shopify-style APIs):

```graphql
type CreateReportPayload { report: Report, userErrors: [UserError!]! }
```

Rule of thumb: if the client UI has a specific branch for it, model it as data. If
it is "something broke", use a top-level error. For **queries** over reporting data,
expected conditions (such as "range exceeds retention") are usually better as a
validation error up front, and partial data as `meta.isPartial: true` plus a
top-level error entry with a `path`.

Errors-as-data costs more schema and is harder to evolve (adding a union member can
break exhaustive client switches; tell clients to always handle `__typename` defaults).

## 6. Mutations

- One `input:` argument with a dedicated `Input` type, which lets you add optional
  fields without breaking.
- Return a payload with the mutated object so clients can update caches.
- Make mutations **idempotent** where possible (client-supplied `clientMutationId`
  or idempotency key) because retries happen.
- Top-level mutation fields execute **serially**; nested fields do not.

## 7. Subscriptions

- Transport: `graphql-transport-ws` protocol over WebSocket (Spring:
  `spring.graphql.websocket.path`), or SSE (Spring for GraphQL supports SSE; DGS
  notes gaps in its Spring integration).
- For real-time reporting, subscriptions are rarely the right tool for aggregated
  data: polling a cached query every N seconds is simpler, scales through caches, and
  the data is bucketed anyway. Use subscriptions for discrete events (alerts, job
  completion).

## 8. Evolution, deprecation and versioning

GraphQL APIs are usually versionless: "new capabilities can be added via new types
or new fields on existing types without creating a breaking change" (graphql.org).

Safe changes: add a type, add a nullable or defaulted field, add an optional
argument, add an enum value (with care, since clients with exhaustive switches may
break), deprecate.

Breaking changes: remove or rename a field, type or enum value; change a field type;
make an output nullable; make an input or argument required; add a required argument;
remove a union member or interface implementation that clients rely on.

Process:

```graphql
type MetricValues {
  revenue: Decimal @deprecated(reason: "Use grossRevenue. Removal after 2026-12-31.")
  grossRevenue: Decimal
}
```

1. Add the replacement and deprecate the old one with a reason and a date.
   `@deprecated` is allowed on fields, enum values, arguments and input fields.
2. Watch **field usage** in traces/metrics (per client name; ask clients to send a
   `apollographql-client-name` style header or similar) until it reaches zero.
3. Remove. Run a schema diff in CI (GraphQL Inspector, `rover subgraph check`,
   or graphql-java `SchemaDiff`) to block accidental breaks.

## 9. Reporting-specific schema rules

- Dimensions, metrics, intervals and sort keys are **enums**. Free-form strings that
  become OpenSearch field names are an injection and cost hazard.
- Time is **half-open** `[from, to)`, with an explicit time zone for calendar buckets.
- Distinguish **zero** from **no data** (`0` versus `null`), and document which.
- Approximate values (cardinality, percentiles, top-N terms) are flagged in `meta`.
- Keep metric fields typed (`count: Long!`, `revenue: Decimal`); add new metrics as
  new fields.

## 10. Schema review checklist

- [ ] Descriptions on all public types and fields
- [ ] Every list paginated or provably bounded; defaults and maxima documented
- [ ] Nullability chosen per field with the failure mode in mind
- [ ] No backend leakage (index, column or service names; DSL passthrough)
- [ ] Enums for closed sets; custom scalars for time, money and 64-bit numbers
- [ ] Mutations use input and payload types; expected errors typed
- [ ] No breaking change against the previous published schema (CI diff)
- [ ] Deprecations have a reason and a target date
- [ ] Cost hints present for expensive fields (complexity weights or `@cost`/`@listSize` under federation)
