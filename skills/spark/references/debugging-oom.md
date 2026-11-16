# Debugging: Spark UI field guide, memory model, OOM and failure triage

## 1. Spark UI: where to look and what it means

The tabs are Jobs, Stages, Storage, Environment, Executors, SQL / DataFrame, Structured Streaming, and the
JDBC/ODBC Server. On open-source Spark, the History Server shows finished apps if
`spark.eventLog.enabled=true` (event logs rolling by default since 4.0). On EMR use the persistent
application UI. On K8s, port-forward the driver's port 4040 or run a History Server against the S3 event-log
directory.

### Jobs tab
- **Event timeline:**
  - Red jobs or removed executors: start at section 3.
  - Gaps of a minute or more between jobs: the driver is busy. Likely causes are Python code, `collect`,
    planning, file listing, Iceberg manifest reading, or Glue calls. Profile the driver, not the executors.
  - Many tiny jobs: a loop of actions, `count()` checks, or schema inference.
- **Job descriptions** contain the call-site (file:line), which is how to map UI to code. Use
  `spark.sparkContext.setJobDescription("…")` / `setJobGroup` to label them.

### SQL / DataFrame tab (start here for DataFrame code)
- Plan graph with per-operator metrics: rows output, data size, scan time, shuffle bytes, spill size, peak
  memory, and Python worker data transfer for UDF operators.
- Checks:
  - **Scan:** "number of files read" vs "size of files read". A tiny avg file size means a small-files problem.
    Pruning only shows up as fewer files.
  - **Rows out of a join ≫ rows in:** an exploding join (duplicate keys or a missing join condition).
  - **Exchange "data size":** the shuffle volume that dominates cost.
  - **Final AQE plan markers** (verified 4.0.1):
    - `AdaptiveSparkPlan isFinalPlan=true`
    - `AQEShuffleRead coalesced` (partitions merged)
    - `AQEShuffleRead coalesced and skewed` plus `SortMergeJoin(skew=true)` (skew split happened)
    - `BroadcastHashJoin` replacing a planned SMJ (runtime broadcast conversion)
- Details section: the formatted physical plan, and `Statistics(..., isRuntime=true)` for AQE runtime stats.

### Stages tab (stage detail page)
Summary metrics show min / 25th / median / 75th / max across tasks:

| Metric | What it tells you |
|---|---|
| Duration | Skew if max ≫ 75th percentile (Databricks: more than 50% above p75) |
| GC time | JVM GC. Above about 10% of duration means heap pressure (rule of thumb) |
| Scheduler delay | Time waiting to be scheduled. High means tiny tasks or overloaded driver |
| Task deserialization time | Large closures, or broadcasting via closure instead of `broadcast()` |
| Result serialization / getting result time | Large results returned to the driver |
| Peak execution memory | Memory used by shuffle / agg / join structures |
| Input size / records | Read volume per task. Uneven means uneven files or splits |
| Shuffle read size / records | Uneven means key skew |
| Shuffle read fetch wait time | Waiting on remote blocks: network, lost executors, overloaded shuffle |
| Shuffle remote reads | Fraction fetched over network |
| Shuffle write size / time | Map-side cost |
| **Shuffle spill (memory)** | Deserialized size of data that was spilled |
| **Shuffle spill (disk)** | Serialized on-disk size of the same data. Any spill means partitions are too big for execution memory |

- The **task table** sorted by duration or shuffle read shows which executor and host. If the slow tasks
  all sit on one host, the problem is the node (bad disk, noisy neighbour), not skew. Speculation helps with
  that, not with skew.
- The **"Aggregated metrics by executor"** table shows whether one executor did most of the work.

### Executors tab
- Storage memory used / total, disk used, cores, active / failed / complete tasks, task time (GC time is
  shown red when high), input, shuffle read / write.
- Use it to answer: do I have the executors I asked for? Is one executor failing repeatedly (bad node)? Is
  GC high everywhere (heap sizing) or on one executor (skew)?
- Thread dump link: use it on a stuck task to see what it is doing, e.g. a Python UDF, an S3 read, or a lock.

### Storage tab
- Cached RDDs and DataFrames, fraction cached, size in memory and on disk. Partially cached plus high spill
  means the cache is fighting execution memory.

### Environment tab
- The **effective** config. Always verify a setting actually took effect here (or with
  `spark.conf.get`). Many "tuning didn't work" cases are a key set too late, a typo, or the wrong scope.

### Without the UI
- Use `df.explain(mode="formatted")` (modes: simple, extended, codegen, cost, formatted).
- After an action, `df._jdf.queryExecution().executedPlan().toString()` contains the final AQE plan in
  PySpark (this is an internal API, so use it for debugging only).
- REST: `http://<driver>:4040/api/v1/applications/<app-id>/stages` (also on the History Server at
  `:18080/api/v1/...`) gives stage metrics as JSON, which is useful for scripted comparisons.

## 2. Memory model (executor)

```
container (YARN/K8s pod) = spark.executor.memory (heap)
                         + spark.executor.memoryOverhead   (default max(384m, 0.10 × heap); 0.40 for K8s non-JVM)
                         + spark.memory.offHeap.size        (if offHeap.enabled)
                         + spark.executor.pyspark.memory    (if set)

heap = 300 MiB reserved
     + (heap − 300 MiB) × (1 − spark.memory.fraction[0.6])   "user memory": UDF objects, metadata
     + (heap − 300 MiB) × spark.memory.fraction                unified region M
           ├── execution (shuffle, sort, hash agg, joins) — can evict storage down to R
           └── storage (cache, broadcast)  R = M × spark.memory.storageFraction[0.5] is protected
```

The execution memory available **per task** is about M / (concurrent tasks = `executor.cores`).
A partition whose working set exceeds that share spills. If it cannot spill (e.g. a giant single row,
a huge `collect_list` array, or a hash-join build side), it causes an OOM. So to give each task more memory
without bigger machines, **reduce `spark.executor.cores`** or increase partition count.

What lives **outside the heap** (and counts against memoryOverhead):
- Python worker processes (one per concurrently running Python task)
- Arrow buffers for pandas UDFs and `toPandas`
- Netty shuffle buffers
- RocksDB state store
- Thread stacks
- Native libraries

This is why PySpark and streaming jobs get killed by the container manager while the JVM heap looks fine.

## 3. Failure triage by error message

| Error / symptom | Where | Meaning | Fix |
|---|---|---|---|
| `java.lang.OutOfMemoryError: Java heap space` in executor log | Executor | A task's heap need > its share | More partitions (`shuffle.partitions`, lower `advisoryPartitionSizeInBytes`). Fewer cores per executor. Bigger heap. Remove giant per-key arrays. Check skew. |
| `OutOfMemoryError: GC overhead limit exceeded` | Executor | Thrashing GC on near-full heap | Same as above. Also cache less, and avoid UDFs that create many objects. |
| `Container killed by YARN for exceeding memory limits. X GB of Y GB physical memory used. Consider boosting spark.executor.memoryOverhead` | YARN NodeManager | Off-heap / native / Python grew beyond overhead | Raise `spark.executor.memoryOverhead`. Set `spark.executor.pyspark.memory`. Lower `arrow.maxRecordsPerBatch`. Bound RocksDB. |
| Pod `OOMKilled`, exit code 137 | Kubernetes | Same as above, enforced by the cgroup | Same. Note the 0.40 overhead factor default for non-JVM jobs on K8s. |
| `ExecutorLostFailure (executor N exited caused by one of the running tasks) Reason: Container killed …` | Driver log | An executor died, usually from one of the two rows above | Find the executor's own log. Do not just retry. |
| `FetchFailedException` / `MetadataFetchFailedException: Missing an output location for shuffle` | Executor | The shuffle files' host died, so the stage is recomputed | Fix the cause of executor death (often OOM or spot loss). Enable decommissioning on spot/K8s. Use the external shuffle service on YARN. |
| `OutOfMemoryError` in driver, or `Total size of serialized results … is bigger than spark.driver.maxResultSize` | Driver | `collect`/`toPandas`/`take` big data, a large broadcast build, or a huge task count or plan | Do not collect. Write instead. Raise `spark.driver.memory`. Keep `maxResultSize` as a guard. Reduce files or tasks (compaction). |
| `Cannot broadcast the table that is larger than 8GB` | Driver | Broadcast hint, or a stats underestimate | Remove the hint. Set `autoBroadcastJoinThreshold=-1` for the query. Fix stats. |
| `SparkException: Could not execute broadcast in 300 secs` | Driver | The broadcast side is slow to compute | Persist the small side first, raise `spark.sql.broadcastTimeout`, or disable broadcast for that join |
| `PythonException … [PYTHON_VERSION_MISMATCH]` | Executor | Python minor version differs between driver and worker | Set `PYSPARK_PYTHON` and `PYSPARK_DRIVER_PYTHON` to the same interpreter (hit while verifying this skill) |
| `[CAST_INVALID_INPUT]`, `[DIVIDE_BY_ZERO]`, `[ARITHMETIC_OVERFLOW]` after upgrading to 4.x | Executor | ANSI mode is on by default in 4.0+ | Fix the data or use `try_cast` / `try_divide`. Setting `spark.sql.ansi.enabled=false` is a migration crutch. |
| Stage retried repeatedly, then the job aborted after 4 failures | Driver | `spark.task.maxFailures` (4) reached | Read the **first** task failure's stack trace, not the last |
| Job "hangs" at 199/200 tasks | Stage page | Skew (one huge task) or a stuck task | Check that task's shuffle read and its thread dump |
| `Task not serializable` | Driver | A lambda captured a non-serializable driver object | Make it serializable, build it inside the lambda, or build it once per partition with `mapPartitions` / `foreachPartition` |
| Injected service is null or unconfigured inside a task | Executor | Dependency injection doesn't reach executors | Static, thread-safe holders initialised once per executor JVM |
| Persisted Dataset unreadable after a class change | Reader | It was written with a Kryo encoder | Kryo encoders are fine for in-flight data, not persisted data. Use bean or product encoders for anything written |
| `NoSuchMethodError` / `ClassNotFoundException` | Driver or executor | Usually a dependency version conflict with the Spark runtime | Inspect the dependency tree and exclude (or shade) the clashing artifact |

### Getting the executor log
- YARN: `yarn logs -applicationId <appId>`
- K8s: `kubectl logs <executor-pod>`. Pods are deleted on exit by default, so ship logs or set
  `spark.kubernetes.executor.deleteOnTermination=false` while debugging.
- EMR: S3 log URI under `containers/`.
- The UI's Executors tab has stdout/stderr links while the app is alive.

## 4. OOM decision tree

1. **Driver or executor?** Driver errors show in the driver log / notebook. Executor errors show in the
   executor log as "ExecutorLostFailure".
2. **Driver:** look for `collect`, `toPandas`, broadcasts, or huge plans (loops of `withColumn` or `union`,
   thousands of files). Fix the code, then add memory only if needed.
3. **Executor, heap OOM:** look at the failing stage's shuffle-read max vs median.
   - If skewed, apply the skew playbook (SKILL.md section 5).
   - If even but big, add partitions or reduce cores per executor.
   - If one row is huge (arrays/maps), restructure.
4. **Executor, killed by container manager:** it is off-heap. Look for PySpark UDFs, Arrow, RocksDB, or many
   cores, each with a Python worker. Raise memoryOverhead or set `pyspark.memory`, and bound RocksDB.
5. **After the fix, check** that spill is gone or acceptable, GC time is reasonable, and no executors were lost.

## 5. Useful one-liners

```python
# Partition count and per-partition row counts (skew / emptiness)
df.rdd.getNumPartitions()
df.groupBy(F.spark_partition_id().alias("pid")).count().orderBy(F.desc("count")).show(5)

# Effective config
spark.conf.get("spark.sql.shuffle.partitions")
sorted(spark.sparkContext.getConf().getAll())

# Label work so it is findable in the UI
spark.sparkContext.setJobDescription("dedupe orders: stage 2")

# PySpark UDF profiling (4.0+): "perf" or "memory"
spark.conf.set("spark.sql.pyspark.udf.profiler", "perf")
# ... run the query ...
spark.profile.show(type="perf")
```

(The profiler was verified on local PySpark 4.0.1. It printed `Profile of UDF<id=…>`.)
