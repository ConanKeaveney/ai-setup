# Cluster shape on AWS: executor sizing, spot, Graviton, remote shuffle

For self-run Spark on EMR on EC2 (YARN), EMR on EKS, or plain Kubernetes. Spark keys were read from the
4.2.0 config and running-on-kubernetes pages; EMR values from AWS docs and the AWS EMR best-practices guides.
"Rule of thumb" marks community or vendor guidance, not a Spark default.

## 1. Executor sizing

**Method, per node type:**
1. Cores per executor: **4–5** (AWS EMR best-practices guide; rule of thumb). More cores per executor means
   less execution memory per task and more Python workers fighting for overhead; 1-core executors waste the
   per-JVM overhead and broadcast copies.
2. Executors per node = (vCPUs − about 1 for OS/daemons) / cores per executor.
3. Container memory per executor = node memory available to YARN/K8s / executors per node.
4. Split the container: heap = container / (1 + overhead factor); overhead = the rest. Then add
   `spark.executor.pyspark.memory` and `spark.memory.offHeap.size` if set (both are **added** to the request).
5. Check **per-task execution memory** ≈ (heap − 300 MiB) × 0.6 / cores. That number, not the heap,
   decides whether a partition spills.

**Overhead factor depends on where you run:**

| Platform | Effective default | Source |
|---|---|---|
| OSS Spark on YARN / K8s JVM jobs | `spark.executor.memoryOverheadFactor` = 0.10, floor `spark.executor.minMemoryOverhead` 384m (4.0+) | Spark config |
| OSS Spark on K8s, **non-JVM jobs (PySpark, R)** | 0.40 | Spark config: "defaults to 0.10 except for Kubernetes non-JVM jobs, which defaults to 0.40" |
| EMR on EC2 (YARN) | 0.1875 (`spark.yarn.executor.memoryOverheadFactor`) | AWS EMR best-practices guide |

- Setting `spark.executor.memoryOverhead` explicitly overrides the factor. `spark.kubernetes.memoryOverheadFactor`
  (0.1, since 2.4.0) is overridden by the general keys.
- **PySpark:** Python workers live in overhead unless `spark.executor.pyspark.memory` is set (then that is the
  Python cap and is added to the container). With pandas/Arrow UDFs, budget overhead at 0.2–0.4 of heap or set
  `pyspark.memory` explicitly (rule of thumb); lower `spark.sql.execution.arrow.maxRecordsPerBatch` (10000)
  if a batch is wide.
- **`spark.kubernetes.local.dirs.tmpfs=true`** puts scratch space in RAM, which counts against pod memory:
  raise overhead to match or pods get OOMKilled.

**EMR on EC2 specifics** (AWS docs):
- EMR sets `spark.executor.memory`/`cores` from the core and task instance types; dynamic allocation is on
  (since EMR 4.4.0) with the shuffle service configured.
- `maximizeResourceAllocation=true` sizes one executor per node from the **core** fleet's instance type and
  sets `spark.default.parallelism` = 2 × YARN vCores. Do not rely on it with mixed instance fleets.
- `spark.yarn.heterogeneousExecutors.enabled` (EMR, on by default) sizes executors per node; set it `false` if
  executor sizes come out uneven or slower.
- EMR guide: set `spark.sql.shuffle.partitions` to total vCores or a multiple. With AQE, set it high and let
  AQE coalesce (SKILL.md section 7).

**Kubernetes specifics** (Spark docs):
- `spark.kubernetes.executor.request.cores` (fractional allowed, e.g. `3.5`) sets the pod CPU request only;
  task slots still come from `spark.executor.cores`. Requesting slightly less than the slots bin-packs better.
- Shuffle and spill go to `emptyDir` on node ephemeral storage unless a volume named `spark-local-dir-*` is
  mounted. On NVMe instance types (r6id, m7gd, …) mount the instance store as `spark-local-dir-1`; for big
  shuffles the docs show an OnDemand PVC (`…persistentVolumeClaim.spark-local-dir-1.options.claimName=OnDemand`).
- PVC reuse (`spark.kubernetes.driver.ownPersistentVolumeClaim` / `reusePersistentVolumeClaim`, both true
  since 3.2.0) plus `spark.shuffle.sort.io.plugin.class=org.apache.spark.shuffle.KubernetesLocalDiskShuffleDataIO`
  lets a replacement executor pick up a lost executor's shuffle files.
- 4.2: pods allocated 20 at a time (`spark.kubernetes.allocation.batch.size`), and a NetworkPolicy limits
  executor ingress to the driver and peers.

## 2. Spot and decommissioning

**Placement rules:**
- **Driver on On-Demand, always.** Losing the driver loses the job. On EMR on EC2, keep master and core nodes
  On-Demand and put Spot only in task fleets with several instance types (AWS EMR best practices). On EKS, pin
  the driver with node affinity on `eks.amazonaws.com/capacityType` (EMR on EKS guide).
- Mix Spot and On-Demand per job by SLA; a whole SLA-critical job on Spot is a gamble (Notion, 2026, below).
- Do not put stateful streaming on Spot without a plan for state reloads.

**Graceful decommissioning (Spark 3.1+):**

| Key | Default | Since |
|---|---|---|
| `spark.decommission.enabled` | false | 3.1.0 |
| `spark.storage.decommission.enabled` | false | 3.1.0 |
| `spark.storage.decommission.shuffleBlocks.enabled` | true | 3.1.0 |
| `spark.storage.decommission.rddBlocks.enabled` | true | 3.1.0 |
| `spark.storage.decommission.fallbackStorage.path` | (none), e.g. `s3a://bucket/spark-fallback/` | 3.1.0 |
| `spark.storage.decommission.shuffleBlocks.maxThreads` | 8 | 3.1.0 |
| `spark.executor.decommission.forceKillTimeout` | (none); set it high so migration finishes | 3.2.0 |
| `spark.stage.ignoreDecommissionFetchFailure` | true from 4.0 (false in 3.5) | 3.4.0 |

- The fallback path is not cleaned up by Spark: put an S3 lifecycle (TTL) rule on it.
- Spot gives a 2-minute notice; on K8s the pod's `terminationGracePeriodSeconds` (default 30s) bounds the
  migration, so raise it to just under the notice (EMR on EKS guide). Migration of large shuffle output often
  does not finish in time, so treat decommissioning as damage limitation, not a guarantee; a remote shuffle
  service is the robust fix.
- EMR on EC2 adds its own YARN-side handling (`spark.decommissioning.timeout.threshold`=20s since EMR 5.11,
  `spark.blacklist.decommissioning.enabled`=true); use EMR 5.11+ / any 6.x/7.x with Spot.
- Dynamic allocation without an external shuffle service works through `spark.dynamicAllocation.shuffleTracking.enabled`
  (true since 3.0) or decommissioning with shuffle migration; executors holding live shuffle data are not
  released, so shuffle tracking can keep a cluster bigger than you expect.

**Karpenter (EMR on EKS guide):** separate NodePools for drivers (`consolidationPolicy: WhenEmpty`) and
executors (`WhenEmptyOrUnderutilized`); node expiry longer than the longest job; capacity preference
arm Spot > x86 Spot > arm On-Demand > x86 On-Demand; wire the Spot interruption SQS queue.

## 3. Graviton

| Measurement | Result | Conditions |
|---|---|---|
| AWS, Graviton2 vs x86 on EMR (2020) | runtime −11.6 to −21.5%, cost −21.6 to −31.7% (M6g/R6g vs M5/R5); individual queries regressed up to 31% | EMR 5.30.1 runtime, TPC-DS 3 TB |
| AWS, Graviton3 C7g vs C6g (2023) | cost −7.9 to −13.4%, runtime −13.7 to −18.7% | EMR 6.9, TPC-DS 3 TB |
| GoDaddy, Graviton2 on EMR Serverless (2023) | cost −13 to −33% (avg −23.85%); runtime from 6% slower to 17% faster, 4 of 6 jobs slower | 6 production jobs, ≥ 3 runs each |
| Graviton4 on EMR | No AWS-published Spark number found (unverified) | |

Rules:
- Expect most of the saving from the lower hourly price, not speed. Benchmark each heavy job; some regress.
- Native code in jars (JNI `.so` for compression, ML libs) needs aarch64 builds; find them with
  `find . -name "*.so" -exec file {} \;`. Use JDK 17+ (already required by Spark 4).
- Do not set `spark.kryo.unsafe=true` on fleets that mix Intel, AMD and Graviton (EMR best practices).
- Python wheels need aarch64 builds too; check pandas/pyarrow/numpy pins in the image.

## 4. Remote / disaggregated shuffle

Default Spark shuffle writes map output to the executor's local disk and serves it from the executor (or the
YARN external shuffle service). Remote shuffle moves it to a separate service.

**When it is worth it** (from the production reports in section 5; no published head-to-head of local vs
remote shuffle on Spark 4 was found):
- Executors are on Spot or K8s autoscaling and lost shuffle files cause stage recomputes
  (`FetchFailedException`, `MetadataFetchFailedException`).
- Shuffle volume per job is large (hundreds of GB and up) or local disks fill or wear out.
- You want dynamic allocation to release executors right after their map stage.

**When it is not:** small shuffles, short jobs (minutes), or clusters on NVMe with stable On-Demand nodes:
the extra network hop makes each shuffle slightly slower, and many small partitions can regress (Pinterest).

| Option | What it is | Key facts |
|---|---|---|
| Push-based shuffle (Magnet) | Spark built-in, merges blocks on the shuffle service | `spark.shuffle.push.enabled` (false, 3.2.0). **YARN with external shuffle service only.** Built for HDD-backed on-prem YARN. |
| Apache Celeborn | Standalone remote shuffle service (Spark 3.x/4.x clients, Flink, MR). Latest 0.7.0 (Aug 2026) | `spark.shuffle.manager=org.apache.spark.shuffle.celeborn.SparkShuffleManager`, `spark.celeborn.master.endpoints=host:9097,…`, `spark.shuffle.service.enabled=false`. Dynamic allocation without ESS needs Spark ≥ 3.5 and `spark.shuffle.sort.io.plugin.class=org.apache.spark.shuffle.celeborn.CelebornShuffleDataIO`. Celeborn recommends `spark.sql.adaptive.localShuffleReader.enabled=false`. |
| Apache Uniffle | Another remote shuffle service | Latest v0.10.0 (Sep 2025); site lists Spark up to 3.3 and no benchmarks. Prefer Celeborn on Spark 4. |
| EMR Serverless serverless storage | AWS-managed disaggregated shuffle, EMR 7.12+ | `spark.aws.serverlessStorage.enabled=true`; AWS claims up to 20% lower cost, pays off above about 10 GB shuffle, under 200 GB per job (AWS blog, Jan 2026). |
| EMR Serverless shuffle-optimised disks | Bigger, faster worker disks, EMR 7.1+ | `spark.emr-serverless.executor.disk.type=shuffle_optimized`, 20 GB–2 TB per worker. |
| Celeborn on EKS for EMR | AWS reference architecture (Jul 2026) | Serves EMR on EC2 and EMR on EKS; no measured numbers published. |

Celeborn gotchas from production (Pinterest, 2024):
- Shuffle byte counts differ from local shuffle, so AQE coalescing and skew decisions change and output
  file counts differ: expect file-count diffs in validation.
- Very large shuffles flood the driver with partition-split messages; raise the split threshold.
- Prefer stage retry over replicating shuffle data (it halved disk and network for them).

## 5. Measured results behind these rules

| Who / when | Change | Measured result | Transferable rule |
|---|---|---|---|
| LinkedIn, 2020 | Push-based shuffle on HDD YARN | One 2 TB-shuffle job: fetch wait −98%, runtime 42 → 31 min, task time −41%; shuffle disk use about 2x | Push-based shuffle fixes small random reads on HDD; budget double shuffle disk |
| LinkedIn, 2021 | Same, fleet-wide (15–18 PB/day) | Compute −16%; 45% of workflows ≥ 10% faster; locality 30x | Measure fleet-wide as an on/off comparison of similar workloads |
| Uber, 2022 | Remote Shuffle Service | SSD life about 3 → 36 months; HDFS/NFS shuffle plugins were 2–5x slower | Use a dedicated shuffle service, not a filesystem-backed shuffle plugin |
| Pinterest, 2024 | Uber-RSS-based service → Celeborn on EKS (≈ 25 PB/day) | Shuffle disk −50%, compute about −40%; some small-partition jobs regressed | Among remote shuffle services, Celeborn is the current choice on K8s; test small-partition jobs and expect AQE decisions to shift |
| AWS, Nov 2025 | EMR 7.12 runtime vs OSS Spark 3.5.6, both on Iceberg 1.10 | TPC-DS 3 TB: total runtime 1,350 s vs 6,114 s (AWS: "4.5x"); geomean about 3x; cost 3.6x lower | Re-benchmark OSS vs EMR runtime on your own queries before deciding where to run; vendor numbers use vendor-chosen setups |
| Amazon Ads, 2024 | Iceberg object-storage layout (1.7+) on a 570 TB backfill | Runtime −22%, S3 5xx −77%, failed steps about 50% → 0 | Set `write.object-storage.enabled=true` for high-rate writes to one prefix; raise S3 retries |
| Notion, 2026 | EMR on EC2 → EMR on EKS + Karpenter, per-job Spot mix | "60–90% savings" across workloads; decommissioning often missed the 2-minute notice | Bin-pack on K8s; choose the Spot share per job; don't count on decommissioning |

## 6. Committers on S3
- **Iceberg needs no output committer**: commits swap the metadata pointer atomically, with no listing or rename.
- **Plain Parquet/ORC files on `s3a://`**: Spark 4.1+ uses the S3A **magic committer** by default
  (migration guide). On older versions set `spark.hadoop.fs.s3a.committer.name=magic` plus
  `spark.sql.sources.commitProtocolClass=org.apache.spark.internal.io.cloud.PathOutputCommitProtocol` and
  `spark.sql.parquet.output.committer.class=org.apache.spark.internal.io.cloud.BindingParquetOutputCommitter`
  (needs `spark-hadoop-cloud`). The S3A committers do **not** support dynamic partition overwrite (4.2 docs:
  the write fails), so use Iceberg `overwritePartitions()` for partition replacement on S3.
- **EMR** uses its EMRFS S3-optimised committer by default (EMR 5.20+; Parquet, ORC, CSV, JSON from 6.4).

## Sources
Spark (4.2.0 docs, read Oct 2026):
- https://spark.apache.org/docs/latest/configuration.html
- https://spark.apache.org/docs/latest/running-on-kubernetes.html
- https://spark.apache.org/docs/latest/cloud-integration.html
- https://spark.apache.org/docs/latest/core-migration-guide.html

AWS:
- https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-spark-configure.html
- https://aws.github.io/aws-emr-best-practices/docs/bestpractices/Applications/Spark/performance
- https://aws.github.io/aws-emr-containers-best-practices/cost-optimization/docs/cost-optimization/
- https://aws.github.io/aws-emr-containers-best-practices/cost-optimization/docs/node-decommission/
- https://aws.github.io/aws-emr-containers-best-practices/performance/docs/karpenter/
- https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-spark-s3-optimized-committer.html
- https://docs.aws.amazon.com/emr/latest/EMR-Serverless-UserGuide/jobs-shuffle-optimized-disks.html
- https://aws.amazon.com/blogs/big-data/amazon-emr-serverless-eliminates-local-storage-provisioning-reducing-data-processing-costs-by-up-to-20/
- https://aws.amazon.com/blogs/big-data/high-performance-remote-shuffle-service-on-amazon-emr-with-apache-celeborn/
- https://aws.amazon.com/blogs/big-data/run-apache-spark-and-iceberg-4-5x-faster-than-open-source-spark-with-amazon-emr
- https://aws.amazon.com/blogs/big-data/amazon-emr-now-provides-up-to-30-lower-cost-and-up-to-15-improved-performance-for-spark-workloads-on-graviton2-based-instances/
- https://www.amazonaws.cn/en/blog-selection/amazon-emr-launches-support-for-amazon-ec2-c7g-graviton3-instances-to-improve-cost-performance-for-spark-workloads-by-7-13/
- https://aws.amazon.com/blogs/big-data/godaddy-benchmarking-results-in-up-to-24-better-price-performance-for-their-spark-workloads-with-aws-graviton2-on-amazon-emr-serverless
- https://github.com/aws/aws-graviton-getting-started/blob/main/java.md
- https://aws.amazon.com/blogs/storage/how-amazon-ads-uses-iceberg-optimizations-to-accelerate-their-spark-workload-on-amazon-s3

Remote shuffle:
- https://celeborn.apache.org/download/
- https://celeborn.apache.org/docs/latest/deploy/
- https://uniffle.apache.org/
- https://www.linkedin.com/blog/engineering/open-source/introducing-magnet
- https://www.linkedin.com/blog/engineering/open-source/push-based-shuffle-in-apache-spark
- https://www.uber.com/en-US/blog/ubers-highly-scalable-and-distributed-shuffle-as-a-service/
- https://www.apachecon.com/acna2024/slides/01_Harnessing_The_Power_of_Apache_Celeborn_for_Efficient_and_Scalable_Shuffle_Systems_at_Pinterest.pdf

Other:
- https://www.notion.com/en-gb/blog/balancing-cost-and-reliability-for-spark-on-kubernetes
- https://hadoop.apache.org/docs/stable/hadoop-aws/tools/hadoop-aws/committers.html
- https://iceberg.apache.org/docs/latest/reliability/
