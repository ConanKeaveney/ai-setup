#!/usr/bin/env python3
"""Negative controls for ``verify_lib`` itself. Run this before trusting it.

The skill's contract is that every check ships a paired assertion proving it
goes red against known-bad input, and that the pairing runs *before* the check
is believed. A library that enforces that on its callers and exempts itself is
the same failure one level up, so this runs both directions on every verdict in
``verify_lib``:

* **red direction** — a fabricated known-bad observation must produce ``FAIL``.
* **green direction** — a fabricated known-good observation must produce the
  status the verdict claims for it (usually ``PASS``, sometimes ``N/A``).

Plus four **meta-controls** on :func:`verify_lib.run_check`, which is the thing
that actually enforces the contract:

1. A check with no negative control at all is ``UNPROVEN``.
2. A check whose control comes back green is ``UNPROVEN``, and its live PASS is
   discarded rather than annotated.
3. A would-be PASS with no named probe is ``UNPROVEN``.
4. A would-be PASS built on a synthetic observation is ``UNPROVEN``.

Every case is a fabricated in-memory value: no service is contacted, nothing is
started or stopped, and this is safe to run mid-ingest.

    python3 selftest.py          # one line per case
    python3 selftest.py -q       # summary only
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_lib import (  # noqa: E402
    Observation,
    Status,
    build_freshness_verdict,
    client_timeout_verdict,
    count_verdict,
    coverage_verdict,
    index_state_verdict,
    owner_verdict,
    parse_cpu_time,
    progress_verdict,
    run_check,
    status_file_verdict,
)

RESULTS: list[tuple[bool, str]] = []


def case(label: str, got: Status, want: Status) -> None:
    RESULTS.append((got is want, f"{label}: want {want.value}, got {got.value}"))


def obs(value, probe="synthetic", source="synthetic"):
    return Observation(probe=probe, raw="", value=value, source=source)


def live(value, probe="live probe", raw="raw output"):
    return Observation(probe=probe, raw=raw, value=value, source="runtime")


# ---------------------------------------------------------------------------
# Per-verdict controls: red direction and green direction
# ---------------------------------------------------------------------------

def verdict_controls() -> None:
    # -- tell (a): count reconciles ------------------------------------------
    v = count_verdict(16063, "documents")
    case("count / short by 63", v(obs(16000))[0], Status.FAIL)
    case("count / over by 1", v(obs(16064))[0], Status.FAIL)
    case("count / unreadable", v(obs(None))[0], Status.DOWN)
    case("count / exact", v(live(16063))[0], Status.PASS)

    # -- tell (a): coverage is the check that counts --------------------------
    v = coverage_verdict()
    case("coverage / 63 empty (the Onyx shape)", v(obs({"total": 16063, "empty": 63}))[0], Status.FAIL)
    case("coverage / 1 empty", v(obs({"total": 10, "empty": 1}))[0], Status.FAIL)
    case("coverage / complete", v(live({"total": 16063, "empty": 0}))[0], Status.PASS)
    # An approximate source may not pass, even reading zero. This is the
    # `cardinality` phantom-gap-of-2 lesson pointed the other way.
    approx = coverage_verdict(exact=False)
    case("coverage / zero but approximate", approx(live({"total": 16063, "empty": 0}))[0], Status.NA)
    case("coverage / gap and approximate", approx(obs({"total": 16063, "empty": 2}))[0], Status.FAIL)

    # -- tell (b): who owns the port -----------------------------------------
    v = owner_verdict("ingest.py")
    case("owner / nothing listening", v(obs([]))[0], Status.FAIL)
    case("owner / wrong process listening",
         v(obs([{"pid": 1, "argv": "/usr/sbin/nginx -g daemon off;"}]))[0], Status.FAIL)
    # The pgrep incident, exactly: the pattern was a path, the argv was a bare
    # filename. A substring verdict over full argv must still fail on the
    # over-specified pattern rather than silently matching.
    strict = owner_verdict("arm-f/ingest.py")
    case("owner / pgrep-2026-08 over-specified pattern vs bare argv",
         strict(obs([{"pid": 2, "argv": "python ingest.py --corpus corpus-frozen"}]))[0], Status.FAIL)
    case("owner / correct owner",
         v(live([{"pid": 2, "argv": "python ingest.py --corpus corpus-frozen"}]))[0], Status.PASS)
    case("owner / all needles required",
         owner_verdict(["ingest.py", "--corpus"])(obs([{"pid": 2, "argv": "python ingest.py"}]))[0],
         Status.FAIL)

    # -- flat vs stalled ------------------------------------------------------
    v = progress_verdict(min_cpu_seconds=0.5)
    case("progress / flat and idle = stalled",
         v(obs({"counter_delta": 0, "cpu_delta_seconds": 0.0, "window_seconds": 20}))[0], Status.FAIL)
    # The 10-minutes-flat-at-99%-CPU case. A stall check that ignores CPU calls
    # this dead. It must not.
    case("progress / flat but burning cpu = busy, not stalled",
         v(live({"counter_delta": 0, "cpu_delta_seconds": 19.4, "window_seconds": 20}))[0], Status.NA)
    case("progress / advancing",
         v(live({"counter_delta": 12, "cpu_delta_seconds": 18.0, "window_seconds": 20}))[0], Status.PASS)
    case("progress / cpu only is liveness, not progress",
         v(live({"counter_delta": None, "cpu_delta_seconds": 19.0, "window_seconds": 20}))[0], Status.NA)
    case("progress / no sample", v(obs(None))[0], Status.DOWN)

    # -- tell (c): a client timeout proves nothing ---------------------------
    v = client_timeout_verdict()
    case("timeout / client gave up", v(obs({"outcome": "client_timeout"}))[0], Status.NA)
    case("timeout / HTTP 200 with n_docs 0 (the dedup no-op)",
         v(obs({"outcome": "ok", "units_written": 0}))[0], Status.FAIL)
    case("timeout / server error", v(obs({"outcome": "error", "detail": "500"}))[0], Status.FAIL)
    case("timeout / real success", v(live({"outcome": "ok", "units_written": 27593}))[0], Status.PASS)

    # -- stored is not searchable --------------------------------------------
    v = index_state_verdict()
    case("index / hnsw m=0, indexed 0 (the Qdrant shape)",
         v(obs({"stored": 44210, "indexed": 0, "build_param": 0}))[0], Status.FAIL)
    case("index / partially built", v(obs({"stored": 100, "indexed": 40, "build_param": 16}))[0], Status.FAIL)
    case("index / empty collection", v(obs({"stored": 0, "indexed": 0, "build_param": 16}))[0], Status.NA)
    case("index / fully built",
         v(live({"stored": 44210, "indexed": 44210, "build_param": 16}))[0], Status.PASS)

    # -- a status file is a claim --------------------------------------------
    v = status_file_verdict()
    case("status file / claims ready while nothing answers",
         v(obs({"claim": "ready, 16063 documents embedded", "live_ok": False,
                "live_probe": "curl 127.0.0.1:8001/health"}))[0], Status.FAIL)
    case("status file / no live probe at all", v(obs({"claim": "ready"}))[0], Status.DOWN)
    case("status file / corroborated",
         v(live({"claim": "ready", "live_ok": True, "live_probe": "curl 127.0.0.1:8001/health"}))[0],
         Status.PASS)

    # -- a green suite on code it did not compile ----------------------------
    v = build_freshness_verdict()
    case("build / shared CARGO_TARGET_DIR",
         v(obs({"compiled_units": 0, "artifact_dir": "/t/target",
                "artifact_dir_shared_with": ["../wt-b"]}))[0], Status.FAIL)
    case("build / Finished in 0.21s, nothing compiled",
         v(obs({"compiled_units": 0, "artifact_dir": "/t/target"}))[0], Status.FAIL)
    case("build / really rebuilt",
         v(live({"compiled_units": 143, "artifact_dir": "/t/target"}))[0], Status.PASS)


# ---------------------------------------------------------------------------
# Meta-controls on the enforcement itself
# ---------------------------------------------------------------------------

def always_pass(_obs):
    """A check structurally incapable of failing. The thing being guarded against."""
    return Status.PASS, "everything is fine, as it always is"


def meta_controls() -> None:
    good = live([{"pid": 2, "argv": "python ingest.py"}])

    c = run_check("no control supplied", owner_verdict("ingest.py"), good, controls=[])
    case("meta / no negative control -> UNPROVEN", c.status, Status.UNPROVEN)

    c = run_check("control that cannot go red", always_pass, good,
                  controls=[("nothing listening", obs([]))])
    case("meta / control came back green -> UNPROVEN", c.status, Status.UNPROVEN)
    RESULTS.append((c.observation is good and "discarded" in c.detail,
                    "meta / green control discards the live result rather than annotating it"))

    c = run_check("passing with no probe named", owner_verdict("ingest.py"),
                  Observation(probe="", raw="", value=[{"pid": 2, "argv": "python ingest.py"}]),
                  controls=[("nothing listening", obs([]))])
    case("meta / PASS with no probe named -> UNPROVEN", c.status, Status.UNPROVEN)

    c = run_check("passing on a synthetic observation", owner_verdict("ingest.py"),
                  obs([{"pid": 2, "argv": "python ingest.py"}]),
                  controls=[("nothing listening", obs([]))])
    case("meta / PASS on synthetic input -> UNPROVEN", c.status, Status.UNPROVEN)

    c = run_check("a properly controlled check", owner_verdict("ingest.py"), good,
                  controls=[("nothing listening", obs([])),
                            ("wrong process", obs([{"pid": 1, "argv": "nginx"}]))])
    case("meta / controls red + runtime probe -> PASS", c.status, Status.PASS)
    RESULTS.append((len(c.controls) == 2 and all(r.went_red for r in c.controls),
                    "meta / both controls recorded as having gone red"))


def parser_controls() -> None:
    """``ps -o time=`` parsing, which silently poisons every CPU delta if wrong."""
    RESULTS.append((parse_cpu_time("27:46.65") == 1666.65, "cpu time / MM:SS.ss"))
    RESULTS.append((parse_cpu_time("1:02:03") == 3723.0, "cpu time / HH:MM:SS"))
    RESULTS.append((parse_cpu_time("2-01:00:00") == 176400.0, "cpu time / D-HH:MM:SS"))
    RESULTS.append((parse_cpu_time("garbage") is None, "cpu time / unparseable is None, not 0.0"))


def main() -> int:
    quiet = "-q" in sys.argv
    verdict_controls()
    meta_controls()
    parser_controls()
    failures = [msg for ok, msg in RESULTS if not ok]
    if not quiet:
        for ok, msg in RESULTS:
            print(f"  [{'ok' if ok else 'BROKEN'}] {msg}")
    print(f"\nverify_lib self-test: {len(RESULTS) - len(failures)}/{len(RESULTS)} controls behaved as required")
    for msg in failures:
        print(f"  BROKEN: {msg}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
