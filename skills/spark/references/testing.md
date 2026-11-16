# Testing Spark code: correctness and performance regressions

## 1. Make code testable first
- Write transformations as pure functions `DataFrame -> DataFrame` (plus plain parameters); keep reads,
  writes, `SparkSession` creation and config parsing in a thin entrypoint. Chain with `df.transform(f)`.
  Then a unit test is "build a tiny input DataFrame, call the function, compare".
- Keep fixtures as small authored rows, never copies of production data.
- Pass the clock and run date in as parameters (no `current_date()` buried in logic) so tests are deterministic.

## 2. Built-in assertions: `pyspark.testing` (3.5+)

| Function | Since | What it checks |
|---|---|---|
| `assertDataFrameEqual(actual, expected, …)` | 3.5.0 | Schema and rows. Accepts Spark DataFrames, pandas DataFrames, pandas-on-Spark DataFrames, or a list of `Row`s as `expected`. |
| `assertSchemaEqual(actual, expected, ignoreNullable=True, ignoreColumnOrder=False, ignoreColumnName=False)` | 3.5.0 (options 4.0) | Schemas only, with a diff on failure. |

`assertDataFrameEqual` parameters (all from 4.0.0 unless noted):
- `checkRowOrder=False` (3.5): rows compared as a multiset by default; set true only when order is the
  thing under test (it forces a sort-sensitive comparison).
- `rtol=1e-05`, `atol=1e-08` (3.5): float tolerance.
- `ignoreNullable=True`, `ignoreColumnOrder=False`, `ignoreColumnName=False`, `ignoreColumnType=False`.
- `maxErrors=None`, `showOnlyDiff=False`, `includeDiffRows=False` (puts unequal rows on the
  `PySparkAssertionError` for programmatic inspection).

```python
from pyspark.testing import assertDataFrameEqual, assertSchemaEqual

def test_dedupe_keeps_latest(spark):
    src = spark.createDataFrame([(1, "a", 1), (1, "b", 2), (2, "c", 1)], "id int, v string, seq int")
    expected = spark.createDataFrame([(1, "b"), (2, "c")], "id int, v string")
    assertDataFrameEqual(dedupe_latest(src), expected)
```

- pandas-on-Spark has `pyspark.pandas.testing.assert_frame_equal` / `assert_series_equal`.
- **chispa** (`assert_df_equality`, `assert_column_equality`, `assert_approx_df_equality`; options
  `ignore_row_order`, `ignore_column_order`, `ignore_nullable`, `allow_nan_equality`) predates
  `pyspark.testing` and gives coloured column-level diffs. Its CI tests PySpark 3.5, 4.0 and 4.1. On 3.5+
  prefer the built-ins (no extra dependency, maintained with Spark) unless you want chispa's diff output.

## 3. Local session fixture (pytest)

```python
import pytest
from pyspark.sql import SparkSession

@pytest.fixture(scope="session")
def spark():
    s = (SparkSession.builder.master("local[2]").appName("tests")
         .config("spark.sql.shuffle.partitions", "2")          # 200 tiny tasks per shuffle is most of test time
         .config("spark.ui.enabled", "false")
         .config("spark.sql.session.timeZone", "UTC")
         .getOrCreate())
    yield s
    s.stop()
```

- One session per test run (`scope="session"`); JVM start-up dominates. Use `local[2]`, not `local[1]`, so
  code that only breaks with more than one partition still breaks.
- Pin the same Spark, Python, pyarrow and Iceberg versions as production, and set
  `PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` to the same interpreter (a mismatch fails with
  `PYTHON_VERSION_MISMATCH`).
- For Iceberg logic, add the runtime jar via `spark.jars.packages` and a `hadoop`-type catalog on a
  `tmp_path` warehouse; that tests MERGE/overwrite semantics without AWS.
- Test with ANSI on (the 4.x default) so casts that would throw in production throw in tests.
- The official guide's examples use `unittest` (`setUpClass`/`tearDownClass`) or a pytest fixture; both are fine.

## 4. Testing for performance regressions

Unit tests on tiny data cannot measure speed, but they can pin the **plan**, which is where most
regressions come from (a join that stops broadcasting, a lost SPJ, a new shuffle).

**Plan-shape assertions (cheap, run in CI):**
```python
def plan_of(df) -> str:
    return df._jdf.queryExecution().executedPlan().toString()   # internal API, test use only

def test_dims_join_broadcasts(spark, facts, dims):
    plan = plan_of(enrich(facts, dims))
    assert "BroadcastHashJoin" in plan
    assert plan.count("Exchange") <= 1
```
- Assert on the things that matter: join strategy, number of `Exchange`s, absence of
  `CartesianProduct`/`BroadcastNestedLoopJoin`, pushed filters on the scan (`PushedFilters`).
- Spark itself does this at scale: `PlanStabilitySuite` stores approved TPC-DS physical plans as golden
  files and fails when a change alters them. Copy the idea for your top jobs: save `explain("formatted")`
  output for a fixed input, diff it in review, regenerate deliberately.
- With AQE on, the plan before execution is not the final plan; run an action first, or set
  `spark.sql.adaptive.enabled=false` in plan-stability tests (Spark's own suite disables AQE).

**Metric regressions (scheduled, on a fixed realistic input):**
- Run the job on a fixed snapshot (Iceberg time travel gives a frozen input) on a fixed cluster shape, and
  compare per-stage metrics run to run: executor run time, shuffle bytes, spill, GC time, input bytes, files
  read. Wall-clock alone is too noisy on shared clusters.
- Collect metrics with **sparkMeasure** (`ch.cern.sparkmeasure:spark-measure_2.13:0.28`, Spark 4.x;
  `pip install sparkmeasure`; `StageMetrics(spark)` → `begin()` / `end()` /
  `aggregate_stage_metrics()`), or from the History Server REST API
  (`/api/v1/applications/<id>/stages`) on the event logs.
- Alert on relative change (for example shuffle bytes +20% or a new spill) rather than absolute times.
- Before an engine upgrade (3.5 → 4.x, OSS → EMR/Databricks), shadow-run the job to a staging location on
  the same input and diff both outputs (row counts, checksums, `assertDataFrameEqual` on samples) and
  metrics. Uber did this for 2M+ jobs moving 2.4 → 3.3 (field-results.md). The diff recipe, its hash traps
  and the CI gating rules are in benchmarking.md sections 4–5.

## Sources
- https://spark.apache.org/docs/latest/api/python/getting_started/testing_pyspark.html
- https://spark.apache.org/docs/latest/api/python/reference/pyspark.testing.html
- https://spark.apache.org/docs/4.0.0/api/python/reference/api/pyspark.testing.assertDataFrameEqual.html (parameter versions)
- https://spark.apache.org/docs/3.5.6/api/python/reference/api/pyspark.testing.assertDataFrameEqual.html
- https://github.com/MrPowers/chispa
- https://github.com/LucaCanali/sparkMeasure
- https://github.com/apache/spark/blob/master/sql/core/src/test/scala/org/apache/spark/sql/PlanStabilitySuite.scala
- https://www.uber.com/blog/ubers-strategy-to-upgrading-2m-spark-jobs/
