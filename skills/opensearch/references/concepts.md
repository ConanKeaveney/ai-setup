# OpenSearch concepts, use cases, and when to use it

Plain-English glossary first, then what OpenSearch is good at, then when to pick something else.
Version tags: **[2.x]**, **[3.0+]**, **[AWS]** = Amazon OpenSearch Service specific. Deeper
detail on any term lives in SKILL.md and the other files in this folder.

## 1. Glossary

### Cluster and nodes

- **Cluster**: a group of servers (nodes) that together hold your data and answer queries as one
  system. Clients talk to any node; the cluster routes the work.
- **Node**: one OpenSearch process, usually one machine or container. By default every node does
  every job (cluster manager eligible, data, ingest, coordinating); bigger clusters split the jobs.
- **Node roles**: the jobs a node is allowed to do, set with `node.roles`.
  - `cluster_manager` (called `master` before 2.0): keeps the cluster state (which indexes exist,
    their mappings, where each shard lives). Run 3 dedicated ones so a majority can always agree.
  - `data`: stores shards and does the indexing and searching. This is where the heavy lifting is.
  - `ingest`: runs ingest pipelines (in-cluster transforms) before a document is stored.
  - Coordinating-only (`node.roles: []`): receives requests, fans them out to shards, merges the
    results. Useful when big aggregation merges or many clients overload the data nodes.
  - `warm` / `search`: newer roles for reading searchable snapshots and for serving search-only
    replicas, so reads don't compete with writes. Check your version's docs; details are moving.
- **Cluster state**: the cluster manager's master copy of all metadata. Every mapping change or
  new index updates it, which is why thousands of indexes or constantly changing mappings slow
  the whole cluster down.

### Data model

- **Index**: a named collection of documents with one mapping, roughly "a table". Example:
  `orders-2026-10`. Physically it is split into shards.
- **Document**: one JSON record in an index, the unit you write and get back. Example: one order
  with its status, total and timestamps.
- **`_id`**: the document's unique key within an index. Set it to your business key
  (`order_id`) so re-sending the same record overwrites instead of duplicating.
- **`_source`**: the original JSON you sent, stored as-is and returned in search hits. It is not
  what searches or aggregations read; they use the inverted index and doc_values.
- **Mapping**: the schema of an index: each field's type and how it is indexed. You can add new
  fields later, but changing an existing field's type means reindexing into a new index.
- **Dynamic mapping**: OpenSearch guessing a type the first time it sees a field. Convenient for
  exploration, dangerous in production: every string becomes `text` plus `keyword`, and a typo
  becomes a permanent field. Set `dynamic: strict` for real indexes.
- **Field types**: the main ones are `keyword` (exact values: IDs, statuses; filter, sort,
  aggregate), `text` (analysed for full-text search), numbers (`long`, `integer`,
  `scaled_float`, …), `date`, `boolean`, `object`, `nested` (array items kept as separate hidden
  documents so their fields stay paired), `flat_object` [2.7+] (arbitrary keys, no aggregations),
  and `knn_vector` (embeddings).
- **Multi-field**: one source field indexed two ways, e.g. `name` as `text` for search plus
  `name.raw` as `keyword` for sorting and grouping.
- **Analyzer**: the pipeline that turns `text` into searchable terms: optional character filters
  (strip HTML), exactly one tokenizer (split into words), then token filters (lowercase, stem,
  synonyms). Example: "Walked Dogs" is stored as the terms `walk` and `dog`, so a search for
  "dog walking" can match. The same analyzer runs on the query text.
- **Lucene**: the Java search library underneath OpenSearch (and Elasticsearch). Each shard is
  one Lucene index; segments, the inverted index and doc_values are all Lucene concepts.
  OpenSearch 3.0 moved to Lucene 10.
- **Inverted index**: a map from each term to the list of documents that contain it, like the
  index at the back of a book. It is why "find documents containing X" is fast regardless of
  how many documents there are.
- **doc_values**: a column-oriented copy of each non-`text` field, stored on disk, mapping
  document to value. Sorting and aggregations read these. On by default; turn off only for fields
  you never sort or aggregate on.
- **fielddata**: the in-heap equivalent of doc_values for `text` fields. Off by default and
  should stay off: it is the classic way to run out of heap.

### Shards and the write path

- **Shard**: one slice of an index, and the unit OpenSearch spreads across nodes. An index with 3
  primaries is three independent Lucene indexes. Too many small shards is a more common problem
  than too few big ones: aim for roughly 10–30 GiB per shard for search, up to 50 GiB for logs.
- **Primary shard**: the copy that accepts writes first. The primary count is fixed at index
  creation; changing it needs a split, shrink or reindex.
- **Replica shard**: a copy of a primary on a different node. It provides failover and extra read
  capacity. The replica count can be changed at any time.
- **Routing**: how a document picks its shard: a hash of `_id`, or of a custom routing value
  such as `merchant_id`. Custom routing lets a single-tenant query hit one shard but risks one
  big tenant creating a hot shard.
- **Segment**: an immutable chunk of a shard's data on disk. A shard is many segments; a search
  reads all of them. Because segments never change, an update is really "mark old copy deleted,
  write a new copy".
- **Translog**: the shard's write-ahead log. Each write goes to an in-memory buffer and the
  translog; by default the translog is fsynced before the write is acknowledged, so an
  acknowledged write survives a crash even before it is in a segment.
- **Refresh**: turning the in-memory buffer into a new searchable segment. Default every 1 s, so
  **freshness is set by the refresh interval**: a document is invisible to search until the next
  refresh. Faster refresh means more tiny segments and more merging.
- **Flush**: a Lucene commit: segments are fsynced to disk and the translog is trimmed. Happens
  automatically (e.g. when the translog passes `index.translog.flush_threshold_size`, 512 MB by
  default). It is about durability and recovery time, not freshness.
- **Merge**: background compaction of small segments into bigger ones. It is also the only point
  where deleted and overwritten documents are physically removed, so update-heavy indexes merge a
  lot and carry a share of deleted docs in the meantime.
- **Document vs segment replication** [2.x]: with document replication (the default) every
  replica re-does the indexing work. With segment replication the primary indexes once and
  replicas copy the finished segments, which raises write throughput but makes replicas lag
  slightly behind.
- **Remote-backed storage** [2.10+]: segments and translog are also written to an object store
  such as S3, so a lost node can be rebuilt from there. Requires segment replication.

### Searching

- **Query DSL**: OpenSearch's JSON query language (`bool`, `term`, `match`, `range`, …). PPL and
  SQL exist as alternatives for ad-hoc analysis.
- **Query context vs filter context**: a clause in query context (`must`, `should`, `match`)
  asks "how well does this match?" and contributes to the score. A clause in filter context
  (`bool.filter`, `must_not`) asks only "yes or no?", skips scoring, and can be cached. For
  reporting and dashboards, everything belongs in `filter`.
- **Relevance scoring**: how full-text results are ranked, by default with **BM25**: a term that
  is rare across the index, appears often in this document, and sits in a short field scores
  higher. Example: "refund" in a short title beats "refund" buried in a long description.
- **`term` vs `match`**: `term` looks for the exact stored value (use on `keyword`); `match` runs
  the analyzer on your input first (use on `text`). `term` on a `text` field almost never matches.
- **Aggregations**: computing summaries over matching documents, the "GROUP BY" of OpenSearch.
  Three kinds:
  - **Bucket**: group documents (`terms` by status, `date_histogram` by day, `range`,
    `composite` for paging through every group).
  - **Metric**: compute a number per group (`sum`, `avg`, `min`/`max`, `cardinality` for
    approximate distinct counts, `percentiles`).
  - **Pipeline**: compute from other aggregations' output (`derivative`, `cumulative_sum`,
    `bucket_selector` to filter groups, `bucket_sort`).
  Example: revenue per day for one merchant = filter on merchant, `date_histogram` by day, `sum`
  of `total_minor` inside.
- **Approximate aggregations**: `terms` top-N across shards and `cardinality` are estimates by
  design. Exact alternatives are `composite` paging or routing a tenant to one shard.
- **Pagination**:
  - `from` + `size`: fine for the first few pages; capped at 10,000 hits by default.
  - **`search_after`**: "give me the next page after this sort value", for deep paging. Needs a
    unique tiebreaker in the sort.
  - **PIT (point in time)** [2.4+]: a frozen view of the index so a series of `search_after`
    pages stays consistent while data keeps changing. Create with
    `POST <index>/_search/point_in_time?keep_alive=1m`, then pass the PIT ID on each page.
  - Scroll: the older way to export everything; prefer PIT plus `search_after`.
- **Caches**: the node query cache keeps filter results per segment; the shard request cache
  keeps whole `size: 0` responses but is wiped on every refresh that changed the shard, so it is
  nearly useless on a 1 s-refresh live index.

### Index lifecycle

- **Alias**: a second name that points at one or more indexes. Clients use the alias, so you can
  rebuild an index and switch to it atomically. Example: alias `orders` moves from `orders-v1`
  to `orders-v2` in one call.
- **Index template**: settings and mappings applied automatically to any new index whose name
  matches a pattern. Composable templates (`_index_template`) are built from reusable component
  templates (`_component_template`).
- **Rollover**: starting a fresh index behind a write alias or data stream when the current one
  gets too big or too old. Example: `logs-000001` rolls to `logs-000002` at 30 GB. Designed for
  append-only data; it breaks updates to documents that live in an older index.
- **ISM (Index State Management)**: OpenSearch's lifecycle automation (Elasticsearch calls its
  equivalent ILM). A policy moves an index through states such as hot, warm, delete, running
  actions like rollover, force-merge, change replicas, snapshot or delete.
- **Data stream**: one name you append to and search, backed by hidden indexes that roll over
  for you. Built for logs, events and metrics: it accepts `create` operations only, and every
  document needs a timestamp (`@timestamp` by default). Not for data you update.
- **Reindex**: copying documents from one index into another, usually to change a mapping or
  shard count. Combine with an alias swap for zero downtime.
- **Snapshot**: an incremental backup of indexes to a repository such as S3, restorable to the
  same or another cluster. [AWS] takes automated hourly snapshots and keeps them 14 days.
- **Hot / warm / cold tiers**: hot = fast local disks for current, writable data; warm =
  cheaper storage for older, read-mostly data; cold = cheapest, not directly searchable. In
  open-source OpenSearch this is done with node attributes plus ISM, or searchable snapshots.
- **UltraWarm** [AWS]: managed warm tier backed by S3 with a local cache. Only primary data is
  billed, but indexes are **read-only** there, so it suits finished logs, not mutable data.
- **Cold storage** [AWS]: indexes detached to S3. Not searchable until moved back to UltraWarm,
  which is free to do. For data you keep for compliance and rarely query.

### Health and resilience

- **Cluster health**: green = every primary and replica is assigned; yellow = all primaries are
  assigned but some replicas aren't (working, but less redundant); red = at least one primary is
  missing, so some data is unavailable and results may be incomplete.
- **Shard allocation**: the cluster manager deciding which node holds each shard copy, subject to
  rules (a primary and its replica never share a node, disk limits, zone awareness).
  `GET _cluster/allocation/explain` tells you why a shard is unassigned.
- **Disk watermarks**: thresholds that stop new shards landing on a filling disk (85% low, 90%
  high) and, at 95% (flood stage), make indexes on that node read-only to protect the cluster.
- **Circuit breakers**: memory guards that reject a request with `circuit_breaking_exception`
  rather than let the JVM run out of heap. Defaults: parent 95% of heap (real memory use),
  request 60% (aggregation structures), fielddata 40%. A tripped breaker usually means a query
  that is too big, not a breaker that is too small.
- **Thread pools and 429s**: each node has bounded queues for write and search work. When they
  fill, requests get HTTP 429 (`rejected_execution`); clients should back off and retry.
- **JVM heap**: OpenSearch runs on Java. Give it about half the machine's RAM, capped near 32 GiB;
  the rest is used by the operating system to cache segment files, which matters just as much.

### Getting data in

- **Bulk API**: the way to write at volume: many index, update and delete actions in one
  request. It is not a transaction; check each item's status in the response.
- **External versioning**: sending your own monotonically increasing version with each write so
  OpenSearch rejects out-of-order (older) updates with a 409. The standard fix for mutable data
  arriving from Kafka out of order.
- **Ingest pipeline**: a chain of processors (rename, parse dates, set fields, run a script) that
  runs inside the cluster on ingest nodes before a document is stored. Fine for light clean-up;
  heavy enrichment belongs upstream.
- **Data Prepper**: OpenSearch's standalone, open-source collector: a pipeline of source (Kafka,
  S3, HTTP, OpenTelemetry), optional buffer and processors, and sink (usually OpenSearch).
  Common for logs and traces.
- **OSIS (Amazon OpenSearch Ingestion)** [AWS]: Data Prepper run as a managed, serverless AWS
  service, scaled and billed in OCUs (OpenSearch Compute Units).
- **Pull-based ingestion** [3.0+]: shards read directly from Kafka (or Kinesis) partitions instead
  of clients pushing writes. Set at index creation; such an index has no ingest pipelines, no
  dynamic mapping, no rollover, and rejects normal REST writes.

### Search features and plugins

- **k-NN / vector search**: finding the documents whose embedding vectors are closest to a query
  vector, the basis of semantic search and RAG retrieval. Fields use `knn_vector`; approximate
  search uses HNSW or IVF graphs from the Faiss engine (the default) or Lucene; NMSLIB is
  deprecated. Exact brute-force search also exists for small or heavily filtered sets.
- **Neural and hybrid search**: neural search generates embeddings for you inside OpenSearch
  through a connected model. Hybrid search blends keyword (BM25) and vector scores in a search
  pipeline, usually beating either alone. Neural sparse search is a cheaper middle ground.
- **Security plugin**: authentication (internal users, SAML, OpenID Connect, LDAP), role-based
  access down to index, document and field level, TLS encryption, and audit logs. Free in
  OpenSearch. [AWS] calls it fine-grained access control (FGAC).
- **OpenSearch Dashboards**: the web UI (the fork of Kibana): Discover for browsing data,
  visualisations and dashboards, a query workbench for SQL/PPL, and screens for plugins such as
  alerting, anomaly detection, observability and security analytics.
- **Alerting and anomaly detection**: plugins that run saved queries on a schedule and notify on
  conditions, and that learn normal patterns in a metric and flag unusual values.
- **Security Analytics**: a SIEM plugin that runs detectors with prepackaged Sigma rules (over
  2,200) against security logs such as Windows events or CloudTrail, producing findings and alerts.
- **PPL and SQL**: piped and SQL query languages over indexes. PPL in 3.x supports joins and
  lookups with limits (for example a 50,000-row cap on the joined side by default), so it is for
  ad-hoc work, not a relational engine.

### Amazon OpenSearch Service

- **Domain** [AWS]: AWS's word for a managed OpenSearch cluster. You choose instance types and
  counts; AWS runs the nodes, patches and snapshots. Some cluster settings and APIs are locked.
- **OpenSearch-optimized instances (OR1, OR2, OM2, OI2)** [AWS]: data nodes that keep a local
  copy and synchronously copy writes to S3, giving higher indexing throughput, automatic recovery
  of lost shards from S3, and cheaper large-volume storage. Trade-offs: `refresh_interval` must
  be at least 10 s, replicas lag by seconds, and migrating onto them is irreversible. Good for
  logs and observability, wrong for second-level freshness.
- **Serverless collection** [AWS]: OpenSearch without a cluster to manage. You pick a collection
  type (search, time series, or vector search) that can't be changed later; AWS scales indexing
  and search compute separately in OCUs and stores data in S3. Shards, refresh (about 10 s) and
  many admin APIs are not yours to control; time series collections reject custom document IDs
  and upserts. Treat it as a different product from a domain.

## 2. Use cases

| Workload | Why OpenSearch fits | Concrete example |
|---|---|---|
| **Search** (site, product, document) | Inverted index, analyzers, BM25 relevance, typo tolerance, facets, autocomplete | An online shop: "red running shoes size 10" ranked by relevance, with brand/price/size filters and counts per facet |
| **Log analytics and observability** | High-volume append-only ingest, time-based indexes with rollover and ISM, full-text search over messages, Dashboards, trace analytics | All service logs and OpenTelemetry traces via Data Prepper; on-call engineers search "timeout AND payment" over the last hour and drill into one trace |
| **Real-time operational analytics and reporting over recent, mutable data** | Documents can be overwritten by `_id`, visible within about a second of refresh, and aggregated with filters at query time; no batch window | A merchant dashboard API showing today's orders, revenue per hour and top items, where order status changes (paid, refunded) appear within seconds |
| **Vector and semantic search, RAG retrieval** | k-NN on embeddings with keyword filters and hybrid scoring in the same engine as the documents | A support chatbot retrieves the 5 most relevant help articles for "how do I get my money back", filtered to the user's region and language |
| **Security analytics (SIEM)** | Security Analytics plugin with Sigma rules, correlation, alerting, long-tail search over security logs | CloudTrail and VPC flow logs scanned by detectors; a finding fires when an access key is used from a new country |
| **Alerting and anomaly detection on metrics or events** | Scheduled monitors and learned baselines over data already indexed | Alert when checkout error rate per minute goes above 2%, or when order volume drops unusually for a Tuesday lunchtime |

## 3. When to use it and when not to

| Situation | Verdict | Better alternative and why |
|---|---|---|
| Full-text search with relevance, facets, autocomplete | **Use** | It is what the engine is built for |
| Logs, traces, events: append-only, searched by time window | **Use** | Rollover, ISM and tiers fit; consider ClickHouse if queries are mostly aggregations, not text search, and cost per TB dominates |
| Dashboards/APIs over recent data that changes (orders, tickets) with seconds-level freshness | **Use**, with care | Fits well when documents are overwritten by `_id` with external versioning and queries are bounded by tenant and time. Watch update cost, deleted-doc bloat, and rollover creating duplicates |
| Vector or hybrid search alongside filters and keyword search | **Use** | Keeps documents, filters and vectors in one place. A dedicated vector database is worth a look only for vector-only workloads at very large scale |
| **Source of truth / transactional data** | **Don't** | **Postgres** (or your OLTP database). OpenSearch has no multi-document transactions, no foreign keys or constraints, and a refresh delay before reads see writes. Index a copy from the database via CDC |
| **Heavy joins, long-history analytics, BI over years of data** | **Don't** | **Snowflake / Databricks** for the warehouse, or **ClickHouse / Druid** for fast OLAP. OpenSearch has no general joins (only nested, parent/child, and limited PPL joins), and keeping years of data hot is expensive |
| **Append-only, high-cardinality OLAP at large scale** (billions of events, group by user or SKU) | **Usually don't** | **ClickHouse / Druid / Pinot**. Column stores compress far better and do exact high-cardinality group-bys faster; OpenSearch `terms` and `cardinality` are approximate and heap-hungry at high cardinality |
| Exact financial totals, reconciliation, statements | **Don't** as the system of record | The database or warehouse. OpenSearch aggregations can be approximate and only reflect refreshed data; fine for a live "approximately now" view |
| **Tiny data** (under about a million rows, simple filters) | **Don't** | **Just use the database**: an index on Postgres, or Postgres full-text search or pgvector. A second system adds sync, ops and cost for no gain |
| Key-value lookups by ID at very high rates | **Don't** | DynamoDB, Redis, or the primary database. OpenSearch can do it, but you pay for a search engine you don't use |
| Long-term archive queried a few times a year | **Don't keep it hot** | S3 plus Athena, or Iceberg tables. If it must stay in OpenSearch, use UltraWarm/cold [AWS] or searchable snapshots |
| Arbitrary, user-defined keys per document (thousands of distinct fields) | **Careful** | `flat_object` (no aggregations) or key/value `nested`. Otherwise you hit mapping explosion |

### OpenSearch vs Elasticsearch vs ClickHouse/Druid for real-time analytics

| | OpenSearch | Elasticsearch | ClickHouse | Druid |
|---|---|---|---|---|
| Core design | Search engine (Lucene, inverted index plus doc_values) | Same lineage as OpenSearch (forked from 7.10 in 2021), diverged since | Column-store SQL database (MergeTree) | Column-store OLAP built around time-partitioned, immutable segments |
| Licence | Apache-2.0, Linux Foundation | AGPLv3, SSPL or Elastic License (user's choice) since 2024 | Apache-2.0 | Apache-2.0 |
| Freshness | About 1 s refresh (10 s on [AWS] OR1/OR2 and Serverless) | About 1 s refresh | Visible once an insert commits; small inserts should be batched or use async inserts | Kafka/Kinesis rows queryable on arrival |
| Updating rows | Strong: overwrite by `_id`, external versioning, per-document updates | Same as OpenSearch | Historically weak (`ReplacingMergeTree`, heavy mutations); lightweight SQL `UPDATE` added in 25.7, beta in 25.8 | Weak: overwrite whole time ranges by reindexing; no row-level update |
| Aggregation speed on large data | Good when filtered to a tenant and a time window; approximate top-N and distinct counts | Similar, plus TSDS and LogsDB index modes that cut storage for metrics and logs | Excellent: exact, vectorised group-bys over billions of rows | Excellent for time-bucketed rollups and high-concurrency dashboards |
| Joins | None in the DSL; limited PPL joins | ES\|QL `LOOKUP JOIN` (GA 8.19/9.1) for enrichment only | Full SQL joins | SQL joins supported, but it performs best denormalised |
| Full-text search | Best in class (analyzers, BM25 ranking) | Best in class | Text (inverted) index GA in 26.2 speeds up token filtering; not a relevance-ranking engine | Basic |
| Pick it when | You need search plus live analytics over data that changes, on AWS or open source | Same, and you want Elastic's newer features (ES\|QL, LogsDB) and accept its licence/cloud | Mostly analytical SQL over large append-mostly data, cost per TB matters | Very high query concurrency on time-series rollups with streaming ingest |

Pinot belongs next to Druid: also Apache-2.0 real-time OLAP, but with native full and partial
**upserts** on real-time tables keyed by primary key, which makes it the column store most
comfortable with mutable entities like orders (at the cost of per-key metadata and partitioning
the stream by key).

## Sources

- OpenSearch docs, from github.com/opensearch-project/documentation-website (main branch):
  data streams (`_im-plugin/data-streams.md`: append-only, `create` only, `@timestamp`), circuit
  breaker settings (95/60/40% defaults), point in time, index aliases, text analysis
  (`_analyzers/index.md`), similarity (BM25 default), Flush API, cluster health API, cluster
  formation and node roles (`_tuning-your-cluster/index.md`), vector search techniques and k-NN
  methods and engines (Faiss default, NMSLIB deprecated), security overview, Data Prepper
  overview, PPL `join` command (limits, 50,000-row subsearch cap).
- AWS Amazon OpenSearch Service Developer Guide: "What is Amazon OpenSearch Serverless?"
  (collection types, ~10 s refresh, time series restrictions), "OpenSearch Optimized Instances"
  (OR1/OR2/OM2/OI2, 10 s minimum refresh, replica lag, irreversible migration), "UltraWarm
  storage" (read-only, cold storage not searchable), "Security Analytics for Amazon OpenSearch
  Service".
- OpenSearch Security Analytics docs (docs.opensearch.org/latest/security-analytics/): detectors,
  2,200+ prepackaged Sigma rules, findings.
- ClickHouse: release 25.7 blog and "How we built fast UPDATEs for the ClickHouse column store"
  (lightweight updates via patch parts; beta and on by default from 25.8), and "Announcing General
  Availability of ClickHouse Full-text Search" (text index GA in 26.2).
- Apache Druid docs, "Data updates" (time-range overwrite and reindex). Apache Pinot docs,
  "Stream ingestion with upsert" (full and partial upsert).
- Elastic: "Elasticsearch is open source again" (AGPL option, 2024) and the 9.0/8.18 release
  notes plus 8.19/9.1 notes (ES|QL LOOKUP JOIN, LogsDB GA).
