---
name: verify
description: >-
  Verify that a job, service, index, corpus or test run actually did what it
  claims — and prove each check can fail before believing it. A check may not
  report PASS from a config value, a status file, an exit code, a process-name
  match or an approximate aggregate; it must name what it probed at runtime, and
  it must ship a negative control that was run first. Use BEFORE reporting that
  an ingest finished, a service is ready, an index is built, a corpus is
  complete, a suite passed, or a bug is fixed — and whenever a green result
  arrived suspiciously fast or cheaply. Triggers on "verify", "is it done",
  "did it finish", "is it actually working", "confirm the ingest", "check the
  index", "is the corpus complete", "sanity check the run", "did the tests
  really run", "prove it works", "negative control", "is this check real",
  "why is this passing".
---

# verify — a check that cannot go red may not go green

## The contract

**A check may not report PASS from a config value, a status file, an exit code,
or an approximate aggregate. It must name what it probed at runtime.**

**A negative control is only valid if nothing else can write to what you
sabotaged, between breaking it and running.** On a shared filesystem or worktree,
sabotage-run-restore is not atomic: another process restoring the file mid-window
makes the control report **PASS**, which reads as "the check is sound" rather than
"the control never ran". So: confirm the sabotage
is present **immediately before and immediately after** the run, not only before.

**And check the control before you doubt the thing it tests.** A control that
reports failure may itself be broken — a guard hook tested with `bash -c 'sleep 20
# <id>'` looked broken because `bash` execs `sleep` and the id never reaches the
final argv, so there was nothing to match. The hook was right; the control was
wrong. Ask "would this control fire if the thing were working?" before concluding
anything from it.

**And every check ships a negative control — a paired assertion that it goes red
against known-bad input, run *before* the check is trusted.**

Assertions structurally incapable of failing are non-answers wearing a green
tick. `references/failure-catalog.md` lists each failure with the check it
needed.

The control runs **first**, and a control that comes back green **discards** the
live result rather than annotating it. A report that says "PASS (note: my
control was also green)" is read as PASS. `scripts/verify_lib.py` enforces this
mechanically: no controls, a control that failed to go red, or a PASS with no
named probe all collapse to `UNPROVEN`.

## The three tells

Learn these three sentences. Most failures are one of them.

**(0) The one that catches the other three: a check can be real, correctly
computed, and still not constrain the property anyone cares about.** Examples
are in `references/failure-catalog.md`.

**Ask of every green check: what would have to be true for this to be green and
the thing still broken?** If you cannot answer, the check is not yet a check.

**A shared cause does not imply a shared symptom.** Defects with one root cause
do not have one detector; a check's stated reach must not exceed what it
constrains.

**A proxy can fail in the direction that hides the finding.** A check that a
*term* is absent is not a check that an *answer* is absent. When a proxy breaks,
ask whether the property broke, and check by looking at the actual hits.

**(a) A count that reconciles is not evidence of content.**
Onyx registered 63 documents in Postgres with zero chunks in OpenSearch.
PrivateGPT checkpointed 8 of 34 documents complete while half-written — the four
largest in the corpus. Both would have reconciled to 16,063 exactly. Always pair
a count with a coverage check that counts units holding *nothing*, and count
them **exactly**: an approximate `cardinality` aggregation reported a phantom
gap of 2 on an index whose coverage was complete, so the same machinery can as
easily report a phantom zero.

**(b) A process that is listening is not evidence of an owner, or of a working
index.**
Ask *who* owns the port, by full argv — not whether something does. `pgrep -f
"arm-f/ingest.py"` against a process whose argv was `ingest.py` matched nothing,
reported DONE in seconds, and made a two-hour job look finished; a match count
collapses "nothing is running" and "the running thing doesn't match my pattern"
into the same zero. A PrivateGPT server answered `/health` while its ingest was
dead. A status file read "ready, 16,063 documents embedded" while five services
refused connections. Never assume the owner of a port from the port alone.

The index half: a Qdrant collection reported `status: green` — its own segment
health, not a build signal — while `hnsw_config.m = 0` and
`indexed_vectors_count: 0` against a non-zero `points_count` meant no vector
index existed at all and every query was a brute-force scan.

**(c) A client timeout is evidence of neither server failure nor success.**
PrivateGPT's ingest handler is synchronous. When the 300s client timeout fired
the server kept working; the retry hit the server's dedup check, found partial
nodes already written, and returned **HTTP 200 with `n_docs: 0`**, which the
driver recorded as done. A timeout is `N/A` and must escalate to a server-side
probe — the server's own log, or a chunk-level count. Never to a retry whose
success is read as the original request's success.

## Five statuses, and why `N/A` is not a pass

Generalised from a benchmark harness that already ran this discipline.

| Status | Meaning |
| --- | --- |
| `PASS` | Verified at runtime, with the probe named and the observation quoted. |
| `FAIL` | Verified at runtime, and wrong. |
| `N/A` | This target genuinely cannot answer this question, or the answer would mislead. An honest, final non-answer — **never** folded into a pass. |
| `DOWN` | The read failed for connectivity reasons, not content reasons. Evidence of nothing. |
| `UNPROVEN` | The *check* is not trustworthy: no control, a control that stayed green, or a PASS with no probe. |

Keeping `N/A` distinct from `PASS` is the pattern worth copying hardest. A
backend with no separate index-build phase has no index-build state to verify;
saying so is honest, and silently passing is how "we checked" gets claimed.
`UNPROVEN` outranks `PASS` in any roll-up, for the same reason a
partial reconciliation must not read as "reconciled".

## How to write a check

1. **Split the probe from the verdict.** The probe does I/O and returns an
   `Observation` (the literal command/URL/query, the raw bytes, the parsed
   value). The verdict is a pure function from `Observation` to
   `(Status, detail)`. This split is what makes a negative control possible at
   all — you can hand a pure verdict a fabricated known-bad observation without
   needing a broken service to hand.
2. **Write the known-bad cases first**, from the failure catalog: nothing
   listening, the wrong process listening, the counter flat, zero units written,
   `indexed < stored`, the file missing. Each must produce `FAIL`.
3. **Run the controls, then the live probe** — `run_check` does this in that
   order and will not let you reverse it.
4. **Put the evidence in the detail string.** Actual numbers, actual argv,
   actual method. "chunk coverage passed" is not a result; "0 of 16,063
   documents have zero chunks, via exact composite aggregation over
   `document_id` (not `cardinality`)" is.
5. **State what the check cannot catch.** Sampled? Say sampling can prove a gap
   and never its absence. Dimension-only? Say two 384-dim models are
   indistinguishable this way — that is the AnythingLLM incident exactly.

## Running it

```bash
python3 ~/.claude/skills/verify/scripts/selftest.py   # 44 controls; run before trusting the library
```

`scripts/verify_lib.py` supplies `run_check` plus ready-made verdicts for every
tell: `count_verdict`, `coverage_verdict`, `owner_verdict`, `progress_verdict`,
`client_timeout_verdict`, `index_state_verdict`, `status_file_verdict`,
`build_freshness_verdict`. Import it by path; it is stdlib-only and does no I/O.

For live-service questions — port bound, who owns it, is it advancing, does it
reconcile, memory headroom — use `owner_verdict` and `progress_verdict` from this
library rather than a hand-rolled `pgrep`/`lsof` loop.

## Two rules that are not negotiable here

- **Read-only unless the task says otherwise.** Verification that restarts the
  thing it is measuring has destroyed the measurement. Never `pkill` by pattern:
  match your own port or data dir, and check `pgrep -fl` first.
- **Treat live production services as read-only.** Never bind, restart or kill
  them, and do not send them requests that write records you are measuring.

## Process checks that lie

- A `pgrep -f`, `ps | grep` or `pkill -f` pattern also matches the shell running
  it, so a wait-loop on it never ends. Match a string absent from the waiter's
  own argv (the binary's path, `pgrep -x`, a pid file).
- An empty `pgrep -f "$dir"` does not prove a directory idle: users hold it as
  cwd or in a variable. Prove idle with `lsof +D "$dir"` or each process's cwd.
- Verify a hook or guard against a captured real payload, never one you wrote.
- Report only observed numbers. Elapsed time comes from clock or log readings;
  anything inferred is labelled an estimate. When corrected, recheck everything
  else in the answer that came from the same inference.

## Reference

`references/failure-catalog.md` — all twelve incidents, the assertion that let
each one through, and the check that catches it. Read it when writing a check
for a new kind of subsystem.
