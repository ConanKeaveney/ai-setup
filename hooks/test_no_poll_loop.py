"""Tests for no-poll-loop.py: BLOCK cases are poll loops; ALLOW cases are negative controls."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "no-poll-loop.py"
spec = importlib.util.spec_from_file_location("npl", HOOK)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
import tempfile
m.STATE_DIR = Path(tempfile.mkdtemp())

MAIN = {"tool_name": "Bash", "session_id": "s"}

# Real poll loops, from the transcripts. All must be REFUSED.
POLL = [
    'until ! pgrep -f cargo-mutants >/dev/null 2>&1; do sleep 60; done; tail -15 m.log',
    'until grep -qE "mutants tested|error:" run.log; do sleep 120; done; tail -20 run.log',
    'while pgrep -x cargo-nextest > /dev/null 2>&1; do sleep 30; done; tail -20 suite.log',
    'until [ -s mutants.out/caught.txt ]; do sleep 45; done; echo done',
    'for i in $(seq 1 58); do if grep -q PASS out.log; then break; fi; sleep 30; done',
    'while ! grep -q "Finished" build.log; do sleep 15; done',
    'sleep 300; tail -40 deploy.log',
    'tail -f ~/app/logs/deploy.log',
    'echo standby536',
    'true',
    'date; echo waiting',
    'sleep 150; echo holding',
    'sleep 100; sleep 100; tail -3 a.log',
]

# Must all be ALLOWED. Several are commands this session actually needed.
ALLOW = [
    'ls -la',
    'git status --porcelain',
    'cargo check -p brain-core',
    "grep -nE 'worktree|sccache|cargo build|clean' scripts/deploy_local.sh",
    "~/app/bin/app status --data ~/app/data | grep -E 'restarted|degraded'",
    'sleep 2',                       # a short settle is ordinary
    'sleep 90; tail -20 deploy.log', # a wait of two minutes or less
    'sleep 120',
    'sleep 5; echo holding',
    'sleep 5; ps -p 46597',          # ditto
    'echo "the loop used to sleep 60 in a while"',   # prose, no loop construct
    'for f in *.rs; do wc -l "$f"; done',            # a loop with no wait
    'python3 - <<EOF\nwhile True:\n    time.sleep(60)\nEOF',  # heredoc body
    'CLAUDE_POLL_LOOP=off until pgrep -f x; do sleep 10; done',  # override
    'date',
    'date +%H:%M:%S',
    "~/.claude/bin/wait-for --log run.log --until '^EXIT=|FAILED' --max 540",
    'echo "build finished" > status.txt',
]

REPEATED = "cat /tmp/x/tasks/b0vfl9kjq.output; date +%H:%M:%S"
VARIED = ["grep -n foo src/a.rs", "sed -n '10,40p' src/a.rs", "sed -n '50,90p' src/a.rs", "sed -n '95,120p' src/a.rs"]
NOT_READONLY = "cargo nextest run -p brain-core"



def verdict(cmd, background=False, transcript=None):
    ti = {"command": cmd}
    if background:
        ti["run_in_background"] = True
    payload = dict(MAIN, tool_input=ti)
    if transcript:
        payload["transcript_path"] = transcript
    shape, why = m.classify(payload)
    return shape, why


def main() -> int:
    failures = 0
    print("=== must be REFUSED (real transcript poll loops) ===")
    for cmd in POLL:
        shape, why = verdict(cmd)
        ok = shape is not None
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'}  {shape or 'ALLOWED(' + why + ')':<34} {cmd[:62]}")

    print("\n=== must be ALLOWED (negative controls) ===")
    for cmd in ALLOW:
        shape, why = verdict(cmd)
        ok = shape is None
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'}  {why if ok else 'REFUSED(' + shape + ')':<34} {cmd[:62]!r}")

    print("\n=== backgrounding is the fix, so it is exempt ===")
    shape, why = verdict(POLL[0], background=True)
    ok = shape is None
    failures += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'}  run_in_background -> {why}")

    print("\n=== the third identical status check in the window is refused ===")
    got = [verdict(REPEATED, transcript="/t/a.jsonl")[0] is not None for _ in range(3)]
    ok = got == [False, False, True]
    failures += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'}  refusals {got}")
    other = verdict(REPEATED, transcript="/t/b.jsonl")[0] is None
    failures += 0 if other else 1
    print(f"{'ok  ' if other else 'FAIL'}  another agent is counted separately")
    varied = all(verdict(c, transcript="/t/c.jsonl")[0] is None for c in VARIED * 1)
    failures += 0 if varied else 1
    print(f"{'ok  ' if varied else 'FAIL'}  different reads are not repeats")
    builds = all(verdict(NOT_READONLY, transcript="/t/d.jsonl")[0] is None for _ in range(4))
    failures += 0 if builds else 1
    print(f"{'ok  ' if builds else 'FAIL'}  a repeated test run is not a status check")

    print("\n=== fails open on junk input ===")
    for junk in ("", "not json", "{}"):
        p = subprocess.run([sys.executable, str(HOOK)], input=junk,
                           capture_output=True, text=True)
        ok = p.returncode == 0 and not p.stdout.strip()
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'}  {junk!r:<12} -> exit {p.returncode}, stdout {p.stdout.strip()!r}")

    print("\n=== the refusal names the replacement ===")
    text = m.deny_text("until ...; do sleep n; done")
    for needle in ("wait-for", "run_in_background", "600000", "FAILURE"):
        ok = needle in text
        failures += 0 if ok else 1
        print(f"{'ok  ' if ok else 'FAIL'}  mentions {needle}")

    print(f"\n{'ALL PASS' if failures == 0 else str(failures) + ' FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
