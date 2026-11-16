#!/usr/bin/env python3
"""A check that cannot go red may not go green.

This is the enforcement half of the ``verify`` skill. It uses
a PASS/FAIL/N/A vocabulary, the
pure-verdict / impure-probe split — and adds the one thing no surveyed tool
does: **every check must ship a negative control, and the control is run before
the live result is believed.**

## Why

Across eight days of sessions, twelve distinct incidents were assertions that
were structurally incapable of failing. Not wrong answers — non-answers wearing
a green tick:

* ``pgrep -f "arm-f/ingest.py"`` against a process whose argv was ``ingest.py``.
  Matched nothing, reported DONE in seconds, made a two-hour job look finished.
* A document count that reconciled while 63 documents had zero chunks.
* A 300s client timeout against a *synchronous* server. The retry deduped,
  returned HTTP 200, and 8 of 34 documents were checkpointed complete while
  half-written — the four largest documents in the corpus.
* A Qdrant collection with ``hnsw_config.m = 0`` and ``indexed_vectors_count:
  0``. No vector index at all; every query a brute-force scan.
* A status file reading "ready, 16,063 documents embedded" while five services
  refused connections.
* An approximate ``cardinality`` aggregation reporting a phantom gap of 2 where
  coverage was complete.
* Two worktrees sharing a ``CARGO_TARGET_DIR``: one got ``Finished in 0.21s,
  nothing compiled`` and kept the other's artifact — a green suite on code it
  did not contain.

Every one of them would have been caught in seconds by asking the check to
fail on purpose first.

## The contract this module enforces mechanically

1. **A verdict is a pure function of an observation.** Probes do I/O and return
   an :class:`Observation`; verdicts map an ``Observation`` to a status. That
   split is what makes a negative control possible at all — you can hand a
   verdict a fabricated known-bad observation without a broken service to hand.

2. **No PASS without a named runtime probe.** :class:`Observation` carries the
   exact command, URL or query that was run and the raw bytes that came back.
   A PASS whose ``probe`` is empty is downgraded to ``UNPROVEN``. A config
   value, a status file, an exit code and an approximate aggregate are all
   claims; only ``probe`` + ``raw`` is evidence.

3. **No PASS without a negative control that went red.** :func:`run_check`
   takes ``controls``: labelled known-bad observations that MUST verdict to
   ``FAIL``. Any control that does not go red makes the whole check
   ``UNPROVEN`` — the live result is discarded, not reported. A check with no
   controls at all is ``UNPROVEN`` by construction.

``UNPROVEN`` is deliberately distinct from ``N/A``. ``N/A`` means *this backend
cannot answer this question* and is an honest, final answer. ``UNPROVEN`` means
*this check is not trustworthy* and is a bug in the check.

## Usage

    from verify_lib import Observation, Status, run_check, render, exit_code

    def probe_owner(port):
        raw = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True).stdout
        return Observation(probe=f"lsof -nP -iTCP:{port} -sTCP:LISTEN",
                           raw=raw, value=parse_pids(raw))

    check = run_check(
        "port 7741 owned by the eval daemon",
        verdict=owner_verdict(expect_argv_contains="--data ~/eval-data"),
        observation=probe_owner(7741),
        controls=[
            ("nothing listening", Observation("synthetic", "", [])),
            ("wrong owner", Observation("synthetic", "x", [proc(argv="nginx")])),
        ],
    )

Stdlib only. No network calls, no subprocesses, no writes: everything here is
pure, so it is testable without a live service. ``selftest.py`` beside this file
runs the module's own negative controls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence


class Status(str, Enum):
    """One check's verdict.

    ``PASS``/``FAIL``/``N/A``/``DOWN`` carry the meanings established in
    ``bench/lib/reconcile.py``. ``UNPROVEN`` is new and is the point of this
    module.
    """

    #: Verified at runtime, with the probe named and the observation quoted.
    PASS = "PASS"
    #: Verified at runtime, and wrong.
    FAIL = "FAIL"
    #: This target genuinely cannot answer this question, or the answer it
    #: could give would mislead. An honest, final non-answer — never a pass.
    NA = "N/A"
    #: The read that would answer this failed for connectivity reasons rather
    #: than content reasons. Tolerated; not evidence either way.
    DOWN = "DOWN"
    #: The check itself is not trustworthy: no negative control, a control that
    #: failed to go red, or a PASS with no named runtime probe. The live result
    #: is discarded rather than reported.
    UNPROVEN = "UNPROVEN"


@dataclass(frozen=True)
class Observation:
    """What a probe saw, and exactly how it looked.

    Attributes:
        probe: The literal thing that was run — a shell command, an HTTP method
            and URL, a SQL statement. Not a description of it. This string is
            what a PASS is allowed to point at, and an empty one forfeits PASS.
        raw: The unedited bytes/text that came back, truncated for display but
            never summarised away. ``""`` means the probe returned nothing,
            which is itself an observation (see the ``pgrep`` incident: a probe
            that matches nothing must not read as "not running").
        value: The parsed form the verdict reasons over.
        source: Where this observation came from. ``"runtime"`` for a real
            probe, ``"synthetic"`` for a fabricated negative control. Only
            ``"runtime"`` observations may produce a PASS.
    """

    probe: str
    raw: str
    value: Any = None
    source: str = "runtime"

    @staticmethod
    def synthetic(value: Any, note: str = "") -> "Observation":
        """A fabricated known-bad observation for a negative control."""
        return Observation(probe=f"synthetic control{': ' + note if note else ''}",
                           raw="", value=value, source="synthetic")

    def short_raw(self, limit: int = 300) -> str:
        flat = " ".join(self.raw.split())
        return flat if len(flat) <= limit else flat[:limit] + "…"


@dataclass(frozen=True)
class ControlRun:
    """One negative control's result: did the check go red on known-bad input."""

    label: str
    got: Status
    went_red: bool

    def render(self) -> str:
        mark = "red as required" if self.went_red else f"DID NOT GO RED (got {self.got.value})"
        return f"      control [{self.label}] -> {mark}"


@dataclass
class Check:
    """One named check, its verdict, its evidence, and its controls."""

    name: str
    status: Status
    detail: str
    observation: Observation | None = None
    controls: list[ControlRun] = field(default_factory=list)

    def render(self, verbose: bool = True) -> str:
        lines = [f"  [{self.status.value:>8}] {self.name}: {self.detail}"]
        if self.observation is not None and self.observation.probe:
            lines.append(f"      probed: {self.observation.probe}")
            lines.append(f"      saw:    {self.observation.short_raw() or '(empty)'}")
        if verbose:
            lines.extend(c.render() for c in self.controls)
        return "\n".join(lines)


Verdict = Callable[[Observation], tuple[Status, str]]


def run_check(
    name: str,
    verdict: Verdict,
    observation: Observation,
    controls: Sequence[tuple[str, Observation]],
) -> Check:
    """Run the negative controls, then — only if they all went red — the live verdict.

    Order matters and is not negotiable. The controls run first, and a control
    that fails to go red discards the live result rather than annotating it. A
    check that reports PASS alongside "by the way, my control was green too" is
    the exact failure this module exists to prevent: the reader takes the PASS.

    Args:
        name: What is being checked, phrased as the claim being tested.
        verdict: Pure function from an :class:`Observation` to
            ``(status, detail)``. Must not do I/O — it is called with
            fabricated inputs.
        observation: The live, runtime observation.
        controls: ``(label, known_bad_observation)`` pairs. At least one is
            mandatory. Each must make ``verdict`` return ``FAIL``.

    Returns:
        A :class:`Check`. ``UNPROVEN`` when there are no controls, when any
        control did not go red, or when a would-be PASS has no runtime probe
        behind it.
    """
    if not controls:
        return Check(
            name,
            Status.UNPROVEN,
            "no negative control supplied — an assertion nobody has seen fail is not a check",
            observation,
        )

    runs: list[ControlRun] = []
    for label, bad in controls:
        got, _ = verdict(bad)
        runs.append(ControlRun(label, got, got is Status.FAIL))

    dead = [r for r in runs if not r.went_red]
    if dead:
        which = ", ".join(f"{r.label!r} returned {r.got.value}" for r in dead)
        return Check(
            name,
            Status.UNPROVEN,
            f"negative control did not go red ({which}) — this check cannot fail, so its "
            "live result is discarded rather than reported",
            observation,
            runs,
        )

    status, detail = verdict(observation)

    if status is Status.PASS and observation.source != "runtime":
        return Check(name, Status.UNPROVEN,
                     f"would have passed on a {observation.source} observation; only a runtime "
                     "probe may produce a PASS", observation, runs)
    if status is Status.PASS and not observation.probe.strip():
        return Check(name, Status.UNPROVEN,
                     "would have passed with no probe named — a config value, a status file or an "
                     "exit code is a claim, not evidence", observation, runs)

    return Check(name, status, detail, observation, runs)


def unproven(name: str, why: str) -> Check:
    """A check that was not written yet, or was written and cannot be trusted."""
    return Check(name, Status.UNPROVEN, why)


def na(name: str, why: str) -> Check:
    """This target cannot answer this question. Honest, final, and not a pass."""
    return Check(name, Status.NA, why)


# ---------------------------------------------------------------------------
# The three tells, as reusable verdicts
# ---------------------------------------------------------------------------


def count_verdict(expected: int, unit: str = "items") -> Verdict:
    """Tell (a), first half: a count that reconciles.

    This verdict passes an equal count and fails an unequal one, and that is
    *all* it does. It is here mostly so its docstring can say what it does not
    prove: a reconciling count is not evidence of content. Onyx registered 63
    documents with zero chunks and this check would have passed. PrivateGPT
    checkpointed 8 half-written documents as complete and this check would have
    passed. Pair it with :func:`coverage_verdict` or do not report it.

    Args:
        expected: The manifest's authoritative figure.
        unit: Noun for the detail string.
    """

    def verdict(obs: Observation) -> tuple[Status, str]:
        actual = obs.value
        if actual is None:
            return Status.DOWN, f"could not read a {unit} count"
        if actual == expected:
            return Status.PASS, (f"{actual} == {expected} {unit}. Reconciles — which is not "
                                 "evidence of content; see the coverage check")
        gap = actual - expected
        return Status.FAIL, f"{actual} != {expected} {unit} ({'over' if gap > 0 else 'short'} by {abs(gap)})"

    return verdict


def coverage_verdict(total_key: str = "total", empty_key: str = "empty", *, exact: bool = True) -> Verdict:
    """Tell (a), second half: how many units have zero content.

    ``obs.value`` is a mapping with a total and a count of units holding
    nothing — zero chunks, zero vectors, zero rows. This is the check that
    catches what a count cannot.

    Args:
        total_key: Key holding the number of units considered.
        empty_key: Key holding the number with zero content.
        exact: False when the count came from a sampled or approximate source.
            An approximate aggregation is not permitted to produce a PASS: an
            approximate ``cardinality`` reported a phantom gap of 2 on a
            complete index, so the same machinery can equally report a phantom
            zero. Sampling can prove a gap exists; it can never prove none does.
    """

    def verdict(obs: Observation) -> tuple[Status, str]:
        v = obs.value
        if not isinstance(v, dict) or v.get(empty_key) is None or v.get(total_key) is None:
            return Status.DOWN, "could not compute a coverage figure"
        empty, total = v[empty_key], v[total_key]
        if empty > 0:
            return Status.FAIL, f"{empty} of {total} units hold zero content"
        if not exact:
            return Status.NA, (f"0 of {total} units appear empty, but the figure is sampled or "
                               "approximate — that can prove a gap, never its absence")
        return Status.PASS, f"0 of {total} units hold zero content, counted exactly"

    return verdict


_PROC_ARGV = "argv"


def owner_verdict(expect_argv_contains: str | Sequence[str]) -> Verdict:
    """Tell (b): a process that is listening is not evidence of an owner.

    ``obs.value`` is a list of process dicts, each with an ``argv`` string —
    the **full** command line, not a name and not a pattern that was matched
    against one. The distinction is the ``pgrep -f "arm-f/ingest.py"``
    incident: the pattern was a path prefix, the argv was a bare filename, the
    match count was zero, and zero matches was read as "finished".

    A verdict over a list of argv strings cannot make that mistake, because the
    empty list and the non-matching list are different inputs with different
    verdicts, and both are FAIL. A ``pgrep`` exit code collapses them into one.

    Args:
        expect_argv_contains: Substring, or all of several substrings, that the
            owner's argv must contain.
    """
    needles = [expect_argv_contains] if isinstance(expect_argv_contains, str) else list(expect_argv_contains)

    def verdict(obs: Observation) -> tuple[Status, str]:
        procs = obs.value
        if procs is None:
            return Status.DOWN, "could not enumerate listening processes"
        if not procs:
            return Status.FAIL, ("nothing is listening — no owner at all. Note this is a distinct "
                                 "finding from 'the wrong thing is listening'; a match count "
                                 "conflates them")
        for p in procs:
            argv = str(p.get(_PROC_ARGV, ""))
            if all(n in argv for n in needles):
                return Status.PASS, f"owner pid {p.get('pid')} argv: {argv}"
        seen = "; ".join(f"pid {p.get('pid')} argv: {p.get(_PROC_ARGV, '')}" for p in procs)
        return Status.FAIL, (f"something is listening but no owner argv contains {needles!r}. "
                             f"Actually listening: {seen}")

    return verdict


def progress_verdict(min_cpu_seconds: float = 0.5) -> Verdict:
    """Tell (b), and the flat-vs-stalled distinction: responsiveness is not progress.

    ``obs.value`` is ``{"counter_delta", "cpu_delta_seconds", "window_seconds"}``
    sampled twice over a window. Four quadrants, and only one of them is a
    stall:

    ==================  ======================  ==============================
    counter             cpu                     verdict
    ==================  ======================  ==============================
    advanced            any                     PASS — advancing
    flat                burning cpu             N/A — busy inside one unit of
                                                work; this window cannot tell
                                                progress from a slow document
    flat                idle                    FAIL — no progress and no work
    unavailable         any                     N/A — cpu alone is liveness
    ==================  ======================  ==============================

    The middle row is the expensive one. An ingest counter sat still for ten
    minutes while the server was at 99% CPU part-way through a large document.
    A stall check that ignores CPU calls that job dead; a CPU check that ignores
    the counter calls an idle daemon working.

    Note ``cpu_delta_seconds`` must be a *delta of cumulative CPU time* across
    the window, not ``ps -o %cpu``. On macOS ``%cpu`` is an average over the
    process's whole lifetime, so a process that worked hard for an hour and has
    since been idle for ten minutes still reports a healthy percentage.

    Args:
        min_cpu_seconds: CPU-seconds consumed during the window below which the
            process counts as idle.
    """

    def verdict(obs: Observation) -> tuple[Status, str]:
        v = obs.value
        if not isinstance(v, dict):
            return Status.DOWN, "no progress sample taken"
        window = v.get("window_seconds")
        cpu = v.get("cpu_delta_seconds")
        counter = v.get("counter_delta")
        if cpu is None and counter is None:
            return Status.DOWN, "neither a counter nor a cpu sample was taken"
        if counter is None:
            return Status.NA, (f"no artefact counter available; the process consumed {cpu}s of CPU "
                               f"over {window}s, which is liveness, not progress")
        if counter > 0:
            return Status.PASS, (f"counter advanced by {counter} over {window}s "
                                 f"(cpu {cpu}s) — the artefact is growing")
        if cpu is not None and cpu >= min_cpu_seconds:
            return Status.NA, (f"counter flat over {window}s but the process burned {cpu}s of CPU — "
                               "busy, not stalled. This window cannot distinguish progress inside "
                               "one large unit of work from a spin; widen it before concluding")
        return Status.FAIL, (f"counter flat over {window}s and cpu consumed {cpu}s "
                             f"(< {min_cpu_seconds}s) — no progress and no work")

    return verdict


def client_timeout_verdict() -> Verdict:
    """Tell (c): a client timeout is evidence of neither server failure nor success.

    ``obs.value`` is ``{"outcome": "ok"|"client_timeout"|"error", ...}``.

    This verdict refuses to convert a client-side timeout into either verdict,
    and that refusal is the whole point. PrivateGPT's ingest handler is
    synchronous: when the 300s client timeout fired the server kept working, the
    retry hit the server's dedup check, found partial nodes already written, and
    returned **HTTP 200 with n_docs: 0** — which the driver recorded as done.
    Eight of thirty-four documents were checkpointed complete while half
    written, including the four largest in the corpus.

    So: a timeout is ``N/A`` and must escalate to a server-side probe — the
    server's own log, or a chunk-level count — never to a retry whose success is
    read as the original request's success.
    """

    def verdict(obs: Observation) -> tuple[Status, str]:
        v = obs.value
        if not isinstance(v, dict) or "outcome" not in v:
            return Status.DOWN, "no request outcome recorded"
        outcome = v["outcome"]
        if outcome == "client_timeout":
            return Status.NA, ("the client gave up; the server may still be working, may have "
                               "finished, or may have written a partial artefact. Not a failure "
                               "and not a success — go read the server's own log or count its "
                               "chunks. A retry that returns 200 after a dedup check is evidence "
                               "about the retry, not about the original request")
        if outcome == "error":
            return Status.FAIL, f"server returned an error: {v.get('detail', '')}"
        if outcome == "ok":
            if v.get("units_written") == 0:
                return Status.FAIL, ("HTTP 200 with zero units written — a dedup no-op, not work "
                                     "done. This is the shape that checkpointed 8 half-written "
                                     "documents as complete")
            return Status.PASS, f"server returned success with {v.get('units_written')} units written"
        return Status.DOWN, f"unrecognised outcome {outcome!r}"

    return verdict


def index_state_verdict() -> Verdict:
    """A store that holds vectors is not a store that can search them.

    ``obs.value`` is ``{"stored", "indexed", "build_param"}``. A Qdrant
    collection reported ``status: green`` — its own segment health, not an
    ANN-build signal — while ``hnsw_config.m = 0`` meant no graph was ever
    built and ``indexed_vectors_count`` sat at 0 against a non-zero
    ``points_count``. Every query was a brute-force scan and every latency
    number taken from it was meaningless.

    Where a backend has no separate build phase, do not call this: say ``N/A``
    with the reason, per ``reconcile.no_index_state_notion_check``.
    """

    def verdict(obs: Observation) -> tuple[Status, str]:
        v = obs.value
        if not isinstance(v, dict) or v.get("stored") is None or v.get("indexed") is None:
            return Status.DOWN, "could not read stored/indexed vector counts"
        stored, indexed, m = v["stored"], v["indexed"], v.get("build_param")
        if stored == 0:
            return Status.NA, "nothing stored yet, no index to build"
        if m is not None and m == 0:
            return Status.FAIL, (f"build parameter is 0 with {stored} vectors stored — no index is "
                                 "being built at all; every query is a brute-force scan")
        if indexed < stored:
            return Status.FAIL, f"indexed={indexed} < stored={stored} — vectors stored but not searchable"
        return Status.PASS, f"indexed={indexed} >= stored={stored}, build parameter {m}"

    return verdict


def status_file_verdict() -> Verdict:
    """A status file is a claim by a process that may no longer exist.

    ``obs.value`` is ``{"claim", "live_ok", "live_probe"}``. One status file
    read "ready, 16,063 documents embedded" while five services refused
    connections. The file was not lying about what had once been true; it was
    simply not a probe.

    This verdict never passes on the claim alone: the claim is corroborating
    detail on a live probe's PASS, and contradicting detail on its FAIL.
    """

    def verdict(obs: Observation) -> tuple[Status, str]:
        v = obs.value
        if not isinstance(v, dict) or "live_ok" not in v:
            return Status.DOWN, "no live probe accompanied the status file"
        if v["live_ok"] is None:
            return Status.DOWN, f"live probe {v.get('live_probe')!r} did not complete"
        if not v["live_ok"]:
            return Status.FAIL, (f"status file claims {v.get('claim')!r} but the live probe "
                                 f"{v.get('live_probe')!r} says otherwise — the file records what "
                                 "was true when some process last wrote it")
        return Status.PASS, f"live probe {v.get('live_probe')!r} agrees with the file's {v.get('claim')!r}"

    return verdict


def build_freshness_verdict() -> Verdict:
    """A test suite is not evidence about code it did not compile.

    ``obs.value`` is ``{"compiled_units", "artifact_dir", "artifact_dir_shared_with"}``.
    Two worktrees shared a ``CARGO_TARGET_DIR``; one reported ``Finished in
    0.21s`` having compiled nothing, kept the other worktree's artifact, and ran
    a green suite against code it did not contain.
    """

    def verdict(obs: Observation) -> tuple[Status, str]:
        v = obs.value
        if not isinstance(v, dict) or v.get("compiled_units") is None:
            return Status.DOWN, "could not tell how many units the build compiled"
        shared = v.get("artifact_dir_shared_with") or []
        if shared:
            return Status.FAIL, (f"artifact dir {v.get('artifact_dir')} is shared with {shared} — the "
                                 "binary under test may have been built from another checkout")
        if v["compiled_units"] == 0:
            return Status.FAIL, ("the build compiled nothing and reused a cached artifact; this run "
                                 "is evidence about whatever produced that artifact, not about the "
                                 "current tree")
        return Status.PASS, (f"{v['compiled_units']} units compiled into {v.get('artifact_dir')}, "
                             "not shared with another checkout")

    return verdict


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_DURATION = re.compile(r"^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$")


def parse_cpu_time(text: str) -> float | None:
    """Parse ``ps -o time=`` into seconds. Handles ``MM:SS.ss``, ``HH:MM:SS``, ``D-HH:MM:SS``."""
    m = _DURATION.match(text.strip())
    if not m:
        return None
    days, hours, minutes, seconds = m.groups()
    return (int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds))


def overall(checks: Sequence[Check]) -> Status:
    """Roll checks up. Any FAIL or UNPROVEN wins; all-DOWN is DOWN; else PASS.

    ``UNPROVEN`` outranks ``PASS`` for the same reason a partial reconciliation
    outranks it in ``reconcile.overall_status``: a report that could not check
    everything must not read as "checked".
    """
    if not checks:
        return Status.DOWN
    if any(c.status is Status.FAIL for c in checks):
        return Status.FAIL
    if any(c.status is Status.UNPROVEN for c in checks):
        return Status.UNPROVEN
    if all(c.status is Status.DOWN for c in checks):
        return Status.DOWN
    if any(c.status is Status.DOWN for c in checks):
        return Status.FAIL
    return Status.PASS


def render(title: str, checks: Sequence[Check], verbose: bool = True) -> str:
    """Render a full report, controls included."""
    head = f"{title}\n  overall: {overall(checks).value}"
    return "\n".join([head, *(c.render(verbose) for c in checks)])


def exit_code(checks: Sequence[Check]) -> int:
    """0 only when nothing failed and nothing was unproven."""
    return 1 if overall(checks) in (Status.FAIL, Status.UNPROVEN) else 0
