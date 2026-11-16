# OpenSearch vs Elasticsearch

## History (why the APIs look the same)

- OpenSearch is the AWS-led fork of **Elasticsearch 7.10.2 and Kibana 7.10.2**, made in 2021
  after Elastic moved off Apache-2.0 (to SSPL/Elastic License). OpenSearch is Apache-2.0 and now
  governed by the OpenSearch Software Foundation (Linux Foundation). Elastic later added AGPL as
  a license option. Treat licence questions as needing a current check.
- Query DSL, `_bulk`, `_cat`, `_cluster`, mappings, analyzers and aggregations are broadly
  compatible with ES 7.10. Both projects have diverged since, so ES 8.x/9.x docs are **not**
  reliable for OpenSearch details (and vice versa).
- OpenSearch 3.0: JDK 21 minimum, Lucene 10, indexes created before 2.x unsupported,
  512-byte `_id` limit enforced everywhere, transport-nio removed.

## Feature / API mapping

| Area | Elasticsearch | OpenSearch |
|---|---|---|
| Lifecycle | ILM (`_ilm`) | **ISM** (`_plugins/_ism`). Different policy JSON |
| UI | Kibana | OpenSearch Dashboards |
| Security | X-Pack security (tiered licensing historically) | Security plugin (free): roles, FGAC, audit logs |
| Pipe/SQL query language | ES\|QL, ES SQL | **PPL** and SQL plugin |
| Runtime fields | `runtime_mappings` | **Derived fields** [2.15+] |
| Unbounded-key object | `flattened` (supports terms aggs) | **`flat_object`** [2.7+]. **No aggregations or sorting** |
| Roles | `master` | `cluster_manager` [2.0+] (`master` deprecated); `_cat/cluster_manager` |
| Mapping types | Removed in 8.0 | Removed in 2.0 |
| Replication | Document replication (Serverless/stateless differs) | Document **or segment replication** [2.x]; **remote-backed storage** [2.10+] |
| Ingest from streams | Connectors / Logstash / Elastic Agent | Data Prepper / OSIS, **pull-based ingestion** [3.0+] |
| Pre-aggregation | Transforms, rollups (deprecated), TSDS/downsampling | Index transforms/rollups plugins, **star-tree index** [GA 3.1] |
| Time-series index mode | TSDS (`index.mode: time_series`) | No equivalent; data streams exist |
| Concurrent segment search | Partial (aggs parallelised in 8.x for some cases) | GA 2.12, default `auto` [3.0+] |
| Vector search | `dense_vector` + `knn` | k-NN plugin, `knn_vector` (Lucene/Faiss engines; NMSLIB deprecated 3.0) |
| Alerting / AD | Watcher, ML jobs | Alerting plugin, Anomaly Detection plugin |
| Point in time | `_pit` (ES 7.10+) | `_search/point_in_time` [2.4+]. **Different endpoint** |
| Cross-cluster replication | Licensed feature | CCR plugin |

## Client and tooling gotchas

- **Elastic's official clients ≥ 7.14 do a product check and refuse non-Elastic servers.** Use
  `opensearch-java`, `opensearch-py`, `opensearch-js`, `opensearch-go`, or pin old 7.x ES clients
  only as a last resort.
- Logstash: use `logstash-output-opensearch`. Beats: OSS 7.12.x-era versions only, or switch to
  Fluent Bit / Data Prepper / OTel.
- [AWS] Domains may still run legacy Elasticsearch (up to 7.10). The engine version string
  (`Elasticsearch_7.10` vs `OpenSearch_2.x`) tells you which docs apply.
- Version-number confusion: OpenSearch 1.x ≈ ES 7.10 feature set. 2.x/3.x numbers don't
  correspond to ES 8/9.
- When reading an ES blog for a tuning trick, check that the setting exists in OpenSearch
  (`GET _cluster/settings?include_defaults=true`) before recommending it.
