# Joins, skew and Storage Partitioned Join

All plan markers and behaviours marked "verified" were observed on local PySpark 4.0.1 (with Iceberg 1.10.0
for SPJ).

## 1. How Spark picks a join

| Strategy | Plan node | Chosen when | Cost profile |
|---|---|---|---|
| Broadcast hash | `BroadcastHashJoin` + `BroadcastExchange` | Equi-join; one side's estimated size ≤ `spark.sql.autoBroadcastJoinThreshold` (10MB), or a `BROADCAST` hint; join type allows that side to be built | No shuffle of the big side. Build side is collected to the driver then sent to all executors. Hard cap 8 GB. |
| Shuffled hash | `ShuffledHashJoin` | `SHUFFLE_HASH` hint; or `preferSortMergeJoin=false` and one side much smaller; or AQE conversion (`maxShuffledHashJoinLocalMapThreshold` > 0) | Both sides shuffle, no sort. Per-partition build side must fit in memory (OOM risk on skew). |
| Sort-merge | `SortMergeJoin` | Default for big-big equi-joins | Both sides shuffle and sort. Spills gracefully. AQE skew splitting applies. |
| Broadcast nested loop | `BroadcastNestedLoopJoin` | Non-equi join with a small side | O(n×m). Not disabled by `autoBroadcastJoinThreshold=-1`. |
| Cartesian | `CartesianProduct` | Non-equi join, both large, or `crossJoin` | Avoid |
| Storage partitioned | `SortMergeJoin`/hash join with **no `Exchange`** under it; scans show `groupedBy=…` | Both sides are V2 tables partitioned compatibly on the join keys, and SPJ configs are on | No shuffle at all |

**Hints** (SQL `/*+ … */` or `df.hint("…")`):
- Join hints: `BROADCAST` (aliases BROADCASTJOIN, MAPJOIN), `MERGE`, `SHUFFLE_HASH`, `SHUFFLE_REPLICATE_NL`.
  Priority when both sides are hinted: BROADCAST > MERGE > SHUFFLE_HASH > SHUFFLE_REPLICATE_NL.
- Partitioning hints: `COALESCE(n)`, `REPARTITION(n, cols)`, `REPARTITION_BY_RANGE(n, cols)`,
  `REBALANCE(cols)`.
- A hint is a request, not a guarantee. For example, you cannot broadcast the preserved side of an outer join.
  **Always check the plan.**

**Statistics drive the static choice.**
- Iceberg reports file-level row counts and sizes. With `spark.sql.iceberg.report-column-stats`=true (default),
  Puffin column stats are passed through, but only if `spark.sql.cbo.enabled`=true (default false).
- A filtered side's size is estimated from the unfiltered size times selectivity, so it is often wrong. AQE
  fixes this at runtime by converting SMJ to BHJ once the real size is known
  (`spark.sql.adaptive.autoBroadcastJoinThreshold`). That is cheaper than finishing the SMJ, though not as
  cheap as planning a broadcast up front.
- Runtime filters, on by default: dynamic partition pruning (`spark.sql.optimizer.dynamicPartitionPruning.enabled`)
  and runtime bloom filters (`spark.sql.optimizer.runtime.bloomFilter.enabled`, 3.3+). These prune the big side
  of a star join using the filtered dimension.

## 2. Exploding joins (not skew, but often mistaken for it)

- Rows-out ≫ rows-in on the join node in the SQL tab means duplicate keys on both sides (many-to-many).
- Check `df.groupBy(keys).count().filter("count > 1")` on **both** sides. Fix by deduplicating the dimension,
  or by joining on the full natural key.
- NULL keys never match in an equi-join, but on an outer join they still flow through, all into one partition.

## 3. AQE skew join

- A shuffle partition is "skewed" when its size is greater than **both**:
  - `skewedPartitionFactor` (5.0) × the median partition size, and
  - `skewedPartitionThresholdInBytes` (256MB).
- AQE splits the skewed partition into roughly `advisoryPartitionSizeInBytes` pieces and replicates the
  matching partition of the other side.
- **Verified plan markers:** `SortMergeJoin(skew=true)`, `AQEShuffleRead coalesced and skewed`.
- **Which side can be split (verified on 4.0.1):**
  - Inner: either side.
  - LEFT OUTER: left side only (skew on the right side of a left join is **not** fixed).
  - FULL OUTER: **neither**.

  So with a left join and a hot key on the right, swap to a right join or restructure.
- AQE handles skew in **joins** (and in `REBALANCE` via `optimizeSkewsInRebalancePartitions`). It does not
  split skewed **aggregations** or window partitions. For those, salt.
- If the skewed partition sits under 256MB but is still 50× the median, lower the threshold (e.g.
  `64MB`–`128MB`). Keep the threshold above the advisory size.
- `spark.sql.adaptive.forceOptimizeSkewedJoin=true` (3.3+) allows the fix even if it adds an extra shuffle.
- **AQE is blind to skew above 2,000 shuffle partitions by default.** Past that count (internal
  `spark.shuffle.minNumPartitionsToHighlyCompress`, 2000) map outputs record block sizes as an average,
  except blocks over `spark.shuffle.accurateBlockThreshold` (100 MB). A hot partition built from many
  sub-100 MB blocks looks normal. Set `spark.shuffle.accurateBlockSkewedFactor` (3.3+, default -1 = off) to
  the same value as `skewedPartitionFactor` (5.0), as the config doc recommends. ByteDance's fix for this
  made 12,000+ apps/day 35% faster on average (field-results.md).

## 4. Manual skew fixes

### 4a. Filter or split hot junk keys
```python
hot = F.col("customer_id").isNull() | F.col("customer_id").isin("", "-1", "UNKNOWN")
clean = facts.filter(~hot).join(dims, "customer_id", "left")
junk  = facts.filter(hot)                     # handle separately (or join to a default row)
result = clean.unionByName(junk, allowMissingColumns=True)
```

### 4b. Two-phase salted aggregation (verified)
```python
SALT = 16
agg = (facts.withColumn("salt", (F.rand(seed=42) * SALT).cast("int"))
       .groupBy("key", "salt").agg(F.sum("amount").alias("amount"), F.count("*").alias("n"))
       .groupBy("key").agg(F.sum("amount").alias("amount"), F.sum("n").alias("n")))
```
This works for algebraic aggregations (sum, count, min, max). Averages must be rebuilt from sum and count.
Distinct counts need care: salt by a hash of the distinct column, not by `rand`.

### 4c. Salted join (verified: same row count as the unsalted join)
```python
SALT = 16
big   = facts.withColumn("salt", (F.rand(seed=7) * SALT).cast("int"))
small = dims.withColumn("salt", F.explode(F.sequence(F.lit(0), F.lit(SALT - 1))))
joined = big.join(small, ["key", "salt"]).drop("salt")
```
This multiplies the small side by SALT. To keep that cheap, salt only the hot keys: compute the top-N keys,
give non-hot rows salt 0, and only explode the small side for hot keys.

### 4d. Hot-key isolation
```python
top = [r.key for r in facts.groupBy("key").count().orderBy(F.desc("count")).limit(20).collect()]
hot_part  = facts.filter(F.col("key").isin(top)).join(F.broadcast(dims.filter(F.col("key").isin(top))), "key")
rest_part = facts.filter(~F.col("key").isin(top)).join(dims, "key")
joined = hot_part.unionByName(rest_part)
```

### 4e. Skewed window functions
`Window.partitionBy("user_id")` with one giant user means one task holds that user's rows. Options:
- pre-aggregate;
- add a time bucket to the partition key if semantics allow;
- handle the hot key separately.

## 5. Storage Partitioned Join (SPJ) on Iceberg

SPJ removes the shuffle when both tables are partitioned compatibly on the join keys. A typical setup is
`bucket(N, customer_id)` on both, with the same N. It generalises Hive bucket joins to V2 sources.

**Verified locally** (Spark 4.0.1 + Iceberg 1.10.0): two tables `PARTITIONED BY (bucket(8, cust))`, joined
on `cust`.
- Default configs: 2 `Exchange`s.
- With the configs below: **0 `Exchange`s**, and the scans show `groupedBy=cust_bucket`.

```python
spark.conf.set("spark.sql.sources.v2.bucketing.enabled", "true")            # default false in 3.5/4.0, true in 4.1+
spark.conf.set("spark.sql.sources.v2.bucketing.pushPartValues.enabled", "true")  # default true (3.4+)
spark.conf.set("spark.sql.iceberg.planning.preserve-data-grouping", "true") # Iceberg; default false
spark.conf.set("spark.sql.requireAllClusterKeysForCoPartition", "false")    # default true (3.4+)
# Optional, for skewed buckets (3.4+): split big buckets, replicate the other side
spark.conf.set("spark.sql.sources.v2.bucketing.partiallyClusteredDistribution.enabled", "true")
```

Requirements and gotchas:
- Join keys must cover the partition columns. With `requireAllClusterKeysForCoPartition=true`, the join keys
  must equal the clustering keys exactly. 4.0 adds `allowJoinKeysSubsetOfPartitionKeys.enabled` for joins on
  a subset.
- Partition transforms must be compatible: same bucket count. 4.0 adds
  `allowCompatibleTransforms.enabled` for, e.g., different bucket counts that divide evenly.
- `pushPartValues` lets one side have partition values the other lacks (it fills in empty partitions).
- A pre-join operator that changes partitioning (a projection that renames or casts the key, an aggregation,
  a repartition) breaks SPJ. Check the plan.
- Too few buckets means too few tasks, which turns into a parallelism problem. Pick N so that per-bucket
  size is about 100 MB–1 GB, and make N a multiple of the cores you expect to have.
- MERGE INTO on Iceberg can also benefit from SPJ when target and source share the bucket spec.

## 6. Join checklist

1. Read `explain("formatted")` and the **final** plan in the SQL tab. Which strategy ran? How many Exchanges?
2. Could the small side be broadcast (≤ a few hundred MB, with driver memory to spare)? Hint it.
3. Big-big joins on the same key, repeatedly? Co-bucket the Iceberg tables and use SPJ.
4. Skewed? Use AQE (check `skew=true`), then salt or isolate.
5. Rows exploding? Check key uniqueness on both sides.
6. Key types identical on both sides (no implicit cast)? Mismatched types defeat pushdown, DPP and SPJ.
