# Failure catalog

Twelve incidents in eight days, each an assertion that could not have failed.
Each entry gives what was asserted, why it could not go red, and the check that
catches it — closing with a **Verdict** line naming the helper in
`../scripts/verify_lib.py` that encodes it.

Read this when writing a check for a subsystem not already covered. The pattern
generalises better than the specifics: **ask what observation would make this
check fail, and if you cannot construct one, you do not have a check.**

---

## 1. The process match that matched nothing

**Asserted:** `pgrep -f "arm-f/ingest.py"` returns non-empty ⇒ the ingest is
running; empty ⇒ it finished.

**Why it could not fail:** the pattern was a path-qualified name; the process's
actual argv was the bare `ingest.py`. The match count was zero from the first
second. Zero was read as "finished" and a two-hour job was reported DONE in
seconds.

**The deeper bug:** a match *count* collapses two different states — "nothing is
running" and "something is running but does not match my pattern" — into the
same `0`, and offers no way to see what it looked at.

**Check instead:** enumerate the listeners or processes and return their **full
argv strings**. The two states are then different values with different
verdicts, and the evidence is in the output. `ps -ww -o command=` — without
`-ww`, macOS truncates argv to terminal width, which is how a check ends up
matching a prefix and missing the flag that distinguishes two instances of the
same binary.

**Verdict:** `owner_verdict`. **Controls:** empty list ⇒ FAIL; a list whose argv
does not contain the needle ⇒ FAIL.

---

## 2. The document count that passed while 63 documents were empty

**Asserted:** documents registered in Postgres == corpus manifest ⇒ indexed.

**Why it could not fail:** Onyx's celery workers crashed mid-index holding
batches. The registry rows were written; the chunks in OpenSearch never were. 63
documents had zero chunks and the count reconciled exactly.

**Check instead:** count the units holding **nothing**. Coverage, not
population.

**Verdict:** `coverage_verdict`. **Controls:** `{total: N, empty: 63}` ⇒ FAIL;
`{total: N, empty: 1}` ⇒ FAIL.

---

## 3. The approximate aggregation that invented a gap

**Asserted:** OpenSearch `cardinality` agg over `document_id` == document count
⇒ complete coverage.

**Why it could not fail — in the other direction:** `cardinality` is
approximate. It reported a phantom gap of 2 on an index whose coverage was
actually complete. The same machinery that fabricates a gap can fabricate a
zero.

**Check instead:** exact enumeration — a composite aggregation paginating
buckets, or a real `SELECT`. One request per ~1000 distinct documents instead of
one approximate count is the correct trade.

**Verdict:** `coverage_verdict(exact=False)`, which **cannot return PASS**: a
sampled or approximate zero is `N/A`, because sampling can prove a gap exists
and can never prove none does.

---

## 4. The client timeout recorded as success

**Asserted:** the ingest driver's checkpoint says `ok` ⇒ the document is
indexed.

**Why it could not fail:** the driver ran `--timeout 300 --retries 4` against a
**synchronous** PrivateGPT ingest handler. When the client gave up, the server
kept working. The retry hit the server's dedup check, found partial nodes
already in Qdrant, and returned **HTTP 200 with `n_docs: 0`** — which the driver
recorded as done. 8 of 34 checkpoint rows were `attempt: 2, elapsed_ms: ~302000,
n_docs: 0`. Four artefacts have no `Finished loading index` line anywhere in the
log: the four largest documents in the corpus (27,593 / 18,647 / 11,036 / 9,008
nodes), partially indexed and permanently checkpointed complete.

**Check instead:** a client timeout is `N/A` — neither failure nor success — and
must escalate to a server-side probe: the server's own log, or a chunk-level
count. And **`HTTP 200` with zero units written is a FAIL**, not a success: it is
a dedup no-op, evidence about the retry rather than about the original request.

**Verdict:** `client_timeout_verdict`. **Controls:** `client_timeout` ⇒ N/A;
`{outcome: ok, units_written: 0}` ⇒ FAIL.

---

## 5. The vector store with no vector index

**Asserted:** Qdrant collection `status: green` ⇒ the index is fine.

**Why it could not fail:** `status` is Qdrant's own segment/optimizer health,
not an ANN-build signal. `hnsw_config.m = 0` meant no HNSW graph was ever built,
and `indexed_vectors_count: 0` sat against a non-zero `points_count`. Every
query was a brute-force scan and every latency number taken from it was
meaningless.

**Check instead:** `indexed >= stored`, **and** the build parameter is non-zero.
Where a backend has no separate build phase, say `N/A` with the reason rather
than passing silently.

**Verdict:** `index_state_verdict`. **Controls:**
`{stored: 44210, indexed: 0, build_param: 0}` ⇒ FAIL; `{stored: 100, indexed:
40}` ⇒ FAIL.

> **Live, 2026-08-05:** `pgpt_bench_collection` is reproducing this exactly —
> `points_count: 446581`, `indexed_vectors_count: 0`, `hnsw m: 0`, `status:
> green`. If `m` is 0 deliberately for bulk ingest, it must be restored and
> verified *before* any measurement is taken from this arm.

---

## 6. The status file that outlived its process

**Asserted:** the status file says "ready, 16,063 documents embedded" ⇒ ready.

**Why it could not fail:** a file is a claim written by a process that may no
longer exist. Five services were refusing connections at the time. The file was
not lying about what had once been true; it simply was not a probe.

**Check instead:** the claim is corroborating detail on a live probe's PASS and
contradicting detail on its FAIL. It is never the evidence.

**Verdict:** `status_file_verdict`. **Controls:** `{live_ok: False}` ⇒ FAIL; no
live probe at all ⇒ DOWN.

---

## 7. Listening ≠ healthy

**Asserted:** `/health` returns 200 ⇒ the service is working.

**Why it could not fail:** a PrivateGPT server answered `/health` while the
ingest behind it was dead. The HTTP layer and the job are different subsystems
and only one of them was being asked.

**Check instead:** health-endpoint liveness answers only "the socket is
answering". Pair it with the artefact: is the thing it produces growing?

**Verdict:** `progress_verdict` alongside the port check.

---

## 8. Flat ≠ stalled

**Asserted:** the ingest counter has not moved in 10 minutes ⇒ the job is
stalled.

**Why it was wrong:** the server was at 99% CPU part-way through a very large
document. A stall check that ignores CPU reports a working job as dead; a CPU
check that ignores the counter reports an idle daemon as working.

**Check instead:** sample **both** over the same window. Four quadrants, one
stall:

| counter | cpu | verdict |
| --- | --- | --- |
| advanced | any | PASS — advancing |
| flat | burning | N/A — busy inside one unit of work; widen the window |
| flat | idle | FAIL — no progress and no work |
| unavailable | any | N/A — cpu alone is liveness, not progress |

**Use a CPU-time delta, never `ps -o %cpu`.** On macOS `%cpu` is an average over
the process's whole lifetime, so a process that worked hard for an hour and has
been idle for ten minutes still reports a healthy percentage.

**Verdict:** `progress_verdict`. **Controls:** `{counter_delta: 0,
cpu_delta_seconds: 0.0}` ⇒ FAIL.

> **Live, 2026-08-05:** the converse also happens. `private-gpt serve` burned
> only 0.63s of CPU over 20s while the Qdrant point count rose by 832 — the work
> was in Ollama and Qdrant, not in the named pid. A CPU-only stall check would
> have called a healthy ingest dead.

---

## 9. The port whose owner was assumed

**Asserted:** port 7739 is bound ⇒ it is my Meilisearch bridge.

**Why it could not fail:** the port was correctly identified and the owner was
never checked. The bridge belonged to a sibling agent, and it was killed.

**Check instead:** verify the full argv — **data dir *and* port** — before
signalling anything. Never `pkill` by pattern: a pattern matching the binary and
subcommand (`pkill -f "release/app daemon"`) also kills the user's live
deployment.

**Verdict:** `owner_verdict` with all needles required.

> **Live, 2026-08-05:** port 11434 is bound and the port map calls it Ollama.
> The actual owner is `python scripts/ollama_fanout.py --port 11434 --backends
> http://127.0.0.1:11435 http://127.0.0.1:11436` — a fan-out proxy in front of
> two real Ollama instances. `nc -z 11434` and `curl 127.0.0.1:11434` both say
> "Ollama is up".

---

## 10. The mixed embedding space that dimensions cannot see

**Asserted:** all sampled vectors are 384-dimensional ⇒ one embedding provider.

**Why it could not fail:** AnythingLLM had ~71 documents embedded with its
bundled Xenova ONNX model and the rest via Ollama's `all-minilm`, in one LanceDB
table. **Both are 384-dimensional.** Distances between the two groups are
meaningless, and a dimension check would have missed exactly the real failure.

**Check instead:** a uniform-dimension sample is `N/A`, never `PASS` — it can
prove a mix exists (non-uniform dims ⇒ FAIL) and can never prove one does not.
Where the backend stores an embedder identity per row, check that instead; where
it is fixed at compile time, say so, because "the code has no other model to
use" is stronger evidence than "every vector happens to agree".

**Verdict:** `coverage_verdict`-style disclosure; report
what the sample can and cannot prove.

---

## 11. The green suite on code it did not contain

**Asserted:** `cargo test` passed ⇒ this tree's code is correct.

**Why it could not fail:** two worktrees shared a `CARGO_TARGET_DIR`. Cargo's
`-C metadata` for a path package does not encode which worktree it came from, so
both compile to the same artifact filename behind a fingerprint keyed on source
mtime through a workspace-relative path. Worktree C got `Finished in 0.21s,
nothing compiled` and kept worktree B's artifact. Last writer wins, and every
sibling whose edit predates that write gets a green suite on code it does not
contain. No warning, no rebuild — just a fast green run.

**Check instead:** did the build compile anything, and is the artifact directory
shared with another checkout? A suspiciously fast green is the tell.

**Verdict:** `build_freshness_verdict`. **Controls:** `{compiled_units: 0}` ⇒
FAIL; `{artifact_dir_shared_with: [...]}` ⇒ FAIL.

---

## 12. The environment variable that named nothing

**Asserted:** `BRAIN_TEST_STORE` is set ⇒ the store-bound tests are testing a
store.

**Why it could not fail:** a default fixture path rotted. The tests went green
and nothing said they had stopped looking at anything. **An environment variable
is a claim, not evidence.**

**Check instead:** a good fixture check verifies
the four components a store *is*, present and non-empty; population counts read
from the store's own bookkeeping; internal consistency between the vector matrix
and its id sidecar; and a content signature that deliberately **excludes** the
file the store rewrites on every open, because a digest that cannot hold still
passes exactly once. It also writes down what it cannot catch, which is the part
most gates skip.

**Verdict:** `status_file_verdict` — an environment variable, like a status
file, records what was configured and never observes what happened.

---

## The shape they share

Nine of the twelve are the same move: **a cheap proxy was measured, and the
expensive thing was reported.** A count proxies for content. A port proxies for
an owner. A process match proxies for a running job. A status file proxies for a
live service. An exit code proxies for work performed. A dimension proxies for a
model. A timeout proxies for a server's state.

The proxy is usually fine. The failure is reporting the proxy's result in the
expensive thing's words — and never once watching the proxy go red.
