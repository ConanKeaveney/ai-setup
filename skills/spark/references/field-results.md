# Field results: measured tuning outcomes and the rules they support

Production write-ups with numbers. Each row gives what was changed, what was measured, and the rule that
carries over. Infrastructure results (push-based and remote shuffle, Graviton, Spot on EKS, EMR runtime, Iceberg
object-storage layout) are in cluster-sizing-aws.md section 5. Numbers are as the authors reported them;
"(mirror)" means the original was unreachable and a copy was read.

## AQE, skew and upgrades

| Who / when | Change | Measured result | Rule |
|---|---|---|---|
| ByteDance, Data+AI Summit 2022 | Fixed AQE skew detection, which was blind above 2,000 shuffle partitions | 12,000+ apps/day covered, 35% faster on average; one job 2 h → 20 min (max partition 9.9 GB → 1.4 GB) | Above 2,000 shuffle partitions Spark records map output sizes approximately (`HighlyCompressedMapStatus`), so AQE under-sees skew. Set `spark.shuffle.accurateBlockSkewedFactor` (3.3+, default -1 = off) to the same value as `skewedPartitionFactor` (5.0) before reaching for salting. AQE cannot help skew from one mapper, skew under an aggregate or window, or broadcast joins. |
| Slack, 2024 | Spark 2.4 → 3 (EMR 5.36 → 6) | Most Airflow tasks 30–60% faster, some about 90%; one job's shuffle partitions 3,000 → 348 after AQE coalescing | After upgrading, set a high `coalescePartitions.initialPartitionNum` and delete hand-written salting that AQE skew join now covers. |
| Uber, 2025 | Spark 2.4 → 3.3 across about 20k scheduled jobs | 85% migrated in 6 months; over 60% of jobs improved by more than 10% | Shadow-run each job to a staging location and diff outputs before cutover; check any custom shuffle manager works with AQE first (Uber's did not). |

## Memory and OOM

| Who / when | Change | Measured result | Rule |
|---|---|---|---|
| Netflix, 2026 (mirror) | Diagnosed OOMs in a sessionisation job | `collect_list` over one huge session caused the OOM, not volume; slimmer rows took peak executor memory 112% → 58% of the slot with zero spill; AQE runtime broadcasts pinned about 3.1 GB on one executor until `spark.sql.adaptive.autoBroadcastJoinThreshold=10MB` | Shrink rows and cap per-key collections before window/collect stages. Cap AQE's **runtime** broadcast threshold separately from the static one. Tune on full-size data: a 1% sample hides the long tail. `row_number()` filtering still buffers whole window partitions. |
| Pinterest, 2026 (InfoQ summary) | Automatic retry of OOM-failed jobs with more memory | OOM failures −96% over 90k+ jobs/day | Size executors for the typical case and retry OOM failures on bigger executors, instead of sizing every job for its worst run. |

## Native engines

| Who / when | Change | Measured result | Rule |
|---|---|---|---|
| Zhihu, 2026 (repost) | Apache Gluten + Velox on 2,446 of 3,200 candidate jobs | Core-hours −44.6%, memory −57%; of the top 200 jobs run side by side, about 40% gained nothing or regressed | Move the top resource consumers to a native engine (Gluten, Photon, EMR runtime) only after side-by-side runs; IO-bound, spill-heavy, union-heavy and text-format jobs often gain nothing. |

## Not found
- No measured production write-up for a Spark 3 → 4 upgrade, or for replacing pandas UDFs with built-ins
  (only synthetic benchmarks exist).
- Airbnb (Spark 3 + Iceberg migration), Apple (SPJ/Iceberg talks), LinkedIn right-sizing and Pinterest
  "Saving Millions From Millions" (Data+AI Summit 2025): originals unreachable, numbers unverified, so
  not used.

## Sources
- https://microsites.databricks.com/sites/default/files/2022-07/Apache-Spark-AQE-SkewedJoin-Optimization-and-Practice-in-ByteDance.pdf
- https://slack.engineering/unlocking-efficiency-and-performance-navigating-the-spark-3-and-emr-6-upgrade-journey-at-slack
- https://www.uber.com/blog/ubers-strategy-to-upgrading-2m-spark-jobs/
- https://noise.getoto.net/2026/10/14/running-apache-spark-experiments-in-my-sleep-and-on-a-plane/ (mirror of the Netflix Tech Blog post)
- https://infoq.com/news/2026/04/pinterest-spark-oom-reduction
- https://www.besthub.dev/articles/how-zhihu-boosted-spark-job-performance-with-gluten-a-practical-case-study-75d3d8836ee4 (repost)
- https://spark.apache.org/docs/latest/configuration.html (`spark.shuffle.accurateBlockSkewedFactor`, `spark.shuffle.accurateBlockThreshold`)
- https://github.com/apache/spark/blob/v4.2.0/core/src/main/scala/org/apache/spark/internal/config/package.scala (`spark.shuffle.minNumPartitionsToHighlyCompress` = 2000, internal)
